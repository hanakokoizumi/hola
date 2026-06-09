from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .clients import (
    AdGuardClient,
    CaddyClient,
    ExternalServiceError,
    create_cloudflared_tunnel,
    ensure_caddy_bootstrap,
    get_cloudflare_zone,
    get_cloudflared_login_status,
    get_container_logs,
    read_cloudflared_origin_cert,
    logout_cloudflared_login,
    restart_container,
    start_cloudflared_login,
)
from .config_store import ConfigStore
from .models import HolaConfig, ProxyRule, SECRET_PLACEHOLDER, utc_now
from .security import hash_password, verify_password
from .sync import SyncManager


store = ConfigStore.from_env()
sync_manager = SyncManager(store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure required data directories exist
    app_data = Path(os.getenv("HOLA_APP_DATA", "/app/data"))
    cloudflared_data = Path(os.getenv("HOLA_CLOUDFLARED_DATA", "/etc/cloudflared"))
    caddy_config_dir = Path(os.getenv("HOLA_CADDY_CONFIG_DIR", "/caddy-config"))

    for directory in [app_data, cloudflared_data, caddy_config_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    store.ensure_exists()
    if ensure_caddy_bootstrap(str(caddy_config_dir)):
        try:
            await restart_container("caddy")
        except ExternalServiceError:
            pass
    yield


app = FastAPI(
    title="Hola",
    description="HomeLab split-access proxy manager",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginPayload(BaseModel):
    username: str
    password: str


class PasswordPayload(BaseModel):
    username: str = "admin"
    password: str = Field(min_length=6, max_length=256)


class TunnelCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)


async def run_sync_background() -> None:
    sync_manager.request_reconcile_until_stable()


def schedule_sync(background_tasks: BackgroundTasks) -> None:
    background_tasks.add_task(run_sync_background)


def hostname_in_zone(hostname: str, zone_name: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    zone = zone_name.strip().lower().rstrip(".")
    return bool(zone and (host == zone or host.endswith(f".{zone}")))


def require_proxy_hostname_in_zone(config: HolaConfig, proxy: ProxyRule) -> None:
    zone_name = config.cloudflare.zone_name
    if not zone_name:
        return
    if not hostname_in_zone(proxy.hostname, zone_name):
        raise HTTPException(
            status_code=422,
            detail=f"Hostname must be within the selected Cloudflare Zone: {zone_name}",
        )


async def sync_cloudflare_zone_from_login(config: HolaConfig) -> bool:
    try:
        cert = read_cloudflared_origin_cert()
    except ExternalServiceError:
        return False
    changed = False
    for key in ["zone_id", "account_id", "api_token"]:
        value = cert.get(key, "")
        if value and getattr(config.cloudflare, key) != value:
            setattr(config.cloudflare, key, value)
            changed = True
    if cert.get("zone_id") and cert.get("api_token"):
        try:
            zone = await get_cloudflare_zone(cert["zone_id"], cert["api_token"])
        except ExternalServiceError:
            zone = {}
        for source_key, target_key in {
            "zone_id": "zone_id",
            "zone_name": "zone_name",
            "account_id": "account_id",
        }.items():
            value = zone.get(source_key, "")
            if value and getattr(config.cloudflare, target_key) != value:
                setattr(config.cloudflare, target_key, value)
                changed = True
    return changed


async def sync_cloudflare_zone_from_config(config: HolaConfig) -> bool:
    cf = config.cloudflare
    if not cf.zone_id or not cf.api_token:
        return False
    try:
        zone = await get_cloudflare_zone(cf.zone_id, cf.api_token)
    except ExternalServiceError:
        return False
    changed = False
    for source_key, target_key in {
        "zone_id": "zone_id",
        "zone_name": "zone_name",
        "account_id": "account_id",
    }.items():
        value = zone.get(source_key, "")
        if value and getattr(cf, target_key) != value:
            setattr(cf, target_key, value)
            changed = True
    return changed


@app.get("/api/config")
async def get_config() -> dict:
    return store.read(decrypt=False).public_dict()


@app.put("/api/config")
async def put_config(payload: dict, background_tasks: BackgroundTasks) -> dict:
    try:
        config = store.update_from_public_payload(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    decrypted = store.read(decrypt=True)
    if await sync_cloudflare_zone_from_config(decrypted):
        config = store.write(decrypted)
    schedule_sync(background_tasks)
    return config.public_dict()


@app.post("/api/admin/password")
async def set_admin_password(payload: PasswordPayload) -> dict:
    config = store.read(decrypt=True)
    config.admin.username = payload.username
    config.admin.password_hash = hash_password(payload.password)
    store.write(config)
    return {"ok": True}


@app.post("/api/login")
async def login(payload: LoginPayload) -> dict:
    config = store.read(decrypt=True)
    if payload.username != config.admin.username or not verify_password(payload.password, config.admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"ok": True, "username": config.admin.username}


@app.get("/api/proxies")
async def list_proxies() -> list[dict]:
    return [proxy.model_dump() for proxy in store.read(decrypt=True).proxies]


@app.post("/api/proxies")
async def create_proxy(payload: ProxyRule, background_tasks: BackgroundTasks) -> dict:
    config = store.read(decrypt=True)
    if not config.cloudflare.zone_name and await sync_cloudflare_zone_from_config(config):
        config = store.write(config)
    require_proxy_hostname_in_zone(config, payload)
    if any(proxy.hostname == payload.hostname for proxy in config.proxies):
        raise HTTPException(status_code=409, detail="Hostname already exists")
    config.proxies.append(payload)
    saved = store.write(config)
    schedule_sync(background_tasks)
    return saved.proxies[-1].model_dump()


@app.put("/api/proxies/{proxy_id}")
async def update_proxy(proxy_id: str, payload: ProxyRule, background_tasks: BackgroundTasks) -> dict:
    config = store.read(decrypt=True)
    if not config.cloudflare.zone_name and await sync_cloudflare_zone_from_config(config):
        config = store.write(config)
    require_proxy_hostname_in_zone(config, payload)
    for index, proxy in enumerate(config.proxies):
        if proxy.id == proxy_id:
            payload.id = proxy_id
            payload.created_at = proxy.created_at
            payload.updated_at = utc_now()
            config.proxies[index] = payload
            saved = store.write(config)
            schedule_sync(background_tasks)
            return saved.proxies[index].model_dump()
    raise HTTPException(status_code=404, detail="Proxy not found")


@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str, background_tasks: BackgroundTasks) -> dict:
    config = store.read(decrypt=True)
    removed = next((proxy for proxy in config.proxies if proxy.id == proxy_id), None)
    if not removed:
        raise HTTPException(status_code=404, detail="Proxy not found")
    config.proxies = [proxy for proxy in config.proxies if proxy.id != proxy_id]
    store.write(config)
    background_tasks.add_task(sync_manager.remove_proxy, removed)
    return {"ok": True}


@app.post("/api/sync")
async def sync_now() -> dict:
    status = await sync_manager.reconcile()
    return status.model_dump()


@app.get("/api/status")
async def get_status() -> dict:
    return store.read(decrypt=False).status.model_dump()


@app.get("/api/logs/{service}")
async def read_logs(service: str, tail: int = 200) -> dict:
    try:
        logs = await get_container_logs(service, tail)
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"service": service, "tail": max(1, min(tail, 1000)), "logs": logs}


@app.post("/api/test/cloudflare")
async def test_cloudflare(payload: dict | None = None) -> dict:
    config = store.read(decrypt=True)
    cf = config.cloudflare
    if not cf.tunnel_id or not cf.credentials_file:
        raise HTTPException(status_code=400, detail="Cloudflare Tunnel not created")
    return {"ok": True, "message": "Cloudflare Tunnel configured"}


@app.post("/api/cloudflare/login")
async def cloudflare_login() -> dict:
    try:
        result = await start_cloudflared_login()
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result["state"] == "ok":
        config = store.read(decrypt=True)
        await sync_cloudflare_zone_from_login(config)
        config.cloudflare.enabled = True
        saved = store.write(config)
        result["cloudflare"] = saved.public_dict()["cloudflare"]
    return result


@app.get("/api/cloudflare/login/status")
async def cloudflare_login_status() -> dict:
    status = get_cloudflared_login_status()
    config = store.read(decrypt=True)
    if status["state"] == "ok":
        zone_changed = await sync_cloudflare_zone_from_login(config)
        if not config.cloudflare.enabled or zone_changed:
            config.cloudflare.enabled = True
            store.write(config)
            config = store.read(decrypt=True)
    status["cloudflare"] = config.public_dict()["cloudflare"]
    return status


@app.delete("/api/cloudflare/login")
async def cloudflare_logout(background_tasks: BackgroundTasks) -> dict:
    status = logout_cloudflared_login()
    config = store.read(decrypt=True)
    config.cloudflare.enabled = False
    config.cloudflare.tunnel_id = ""
    config.cloudflare.credentials_file = ""
    config.cloudflare.zone_id = ""
    config.cloudflare.zone_name = ""
    config.cloudflare.account_id = ""
    config.cloudflare.api_token = ""
    saved = store.write(config)
    schedule_sync(background_tasks)
    return {
        "ok": True,
        "cloudflare": saved.public_dict()["cloudflare"],
        "login_status": status,
    }


@app.post("/api/cloudflare/tunnel")
async def cloudflare_create_tunnel(payload: TunnelCreatePayload, background_tasks: BackgroundTasks) -> dict:
    try:
        tunnel = await create_cloudflared_tunnel(payload.name)
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    config = store.read(decrypt=True)
    config.cloudflare.enabled = True
    config.cloudflare.tunnel_name = tunnel["tunnel_name"]
    config.cloudflare.tunnel_id = tunnel["tunnel_id"]
    config.cloudflare.credentials_file = tunnel["credentials_file"]
    saved = store.write(config)
    schedule_sync(background_tasks)
    return {
        "ok": True,
        "cloudflare": saved.public_dict()["cloudflare"],
    }


@app.post("/api/test/adguard")
async def test_adguard(payload: dict | None = None) -> dict:
    config = store.read(decrypt=True)
    ag = config.adguard
    try:
        message = await AdGuardClient(ag.url, ag.username, ag.password).test()
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": message}


@app.post("/api/test/caddy")
async def test_caddy(payload: dict | None = None) -> dict:
    config = store.read(decrypt=True)
    try:
        message = await CaddyClient(config.caddy.admin_url).test()
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": message}


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    index = frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "name": "Hola",
        "message": "Frontend build not found. Run `npm install && npm run build` in frontend/.",
        "secret_placeholder": SECRET_PLACEHOLDER,
    }


def main() -> None:
    import uvicorn

    uvicorn.run(
        "hola.main:app",
        host=os.getenv("HOLA_HOST", "0.0.0.0"),
        port=int(os.getenv("HOLA_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
