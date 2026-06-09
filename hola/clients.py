from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlparse

import httpx
import yaml

from .models import HolaConfig, ProxyRule


class ExternalServiceError(RuntimeError):
    pass


class ExternalServiceAuthError(ExternalServiceError):
    pass


LOG_CONTAINERS = {
    "caddy": "hola-caddy",
    "cloudflare": "hola-cloudflared",
}

CLOUDFLARED_CONNECTED_MARKERS = (
    "Registered tunnel connection",
    "Connection registered",
)
CLOUDFLARED_ERROR_MARKERS = (
    "Could not lookup srv records",
    "edge discovery: error looking up Cloudflare edge IPs",
    "precheck complete hard_fail=true",
    "cloudflared may not be able to establish a tunnel",
    "Unauthorized",
    "Initiating shutdown",
)
CLOUDFLARED_LOGIN_PROCESS: asyncio.subprocess.Process | None = None


def cloudflared_data_dir() -> Path:
    return Path(os.getenv("HOLA_CLOUDFLARED_DATA", "./data/cloudflared"))


def cloudflared_origin_cert_path() -> Path:
    for path in cloudflared_origin_cert_candidates():
        if path.exists():
            return path
    return cloudflared_home_cert_path()


def cloudflared_home_dir() -> Path:
    return cloudflared_data_dir()


def cloudflared_home_cert_path() -> Path:
    return cloudflared_home_dir() / ".cloudflared" / "cert.pem"


def cloudflared_origin_cert_candidates() -> tuple[Path, ...]:
    data_dir = cloudflared_data_dir()
    return (
        data_dir / ".cloudflared" / "cert.pem",
        data_dir / "cert.pem",
    )


def cloudflared_credentials_path(tunnel_id: str) -> Path:
    safe_tunnel_id = tunnel_id.strip()
    return cloudflared_data_dir() / f"{safe_tunnel_id}.json"


def cloudflared_named_credentials_path(tunnel_name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", tunnel_name.strip()).strip(".-") or "tunnel"
    return cloudflared_data_dir() / f"credentials-{safe_name[:80]}.json"


def cloudflared_config_path() -> Path:
    return cloudflared_data_dir() / "config.yml"


async def get_container_logs(service: str, tail: int = 200) -> str:
    container = LOG_CONTAINERS.get(service)
    if not container:
        raise ExternalServiceError(f"Unknown log service: {service}")
    bounded_tail = max(1, min(tail, 1000))
    params = {
        "stdout": "1",
        "stderr": "1",
        "timestamps": "1",
        "tail": str(bounded_tail),
    }
    response = await docker_get(f"/containers/{quote(container, safe='')}/logs", params=params)
    if response.status_code == 404:
        raise ExternalServiceError(f"Container not found: {container}")
    if response.status_code >= 400:
        raise ExternalServiceError(response.text)
    return decode_docker_log_stream(response.content)


async def get_container_state(service: str) -> dict[str, Any]:
    container = LOG_CONTAINERS.get(service)
    if not container:
        raise ExternalServiceError(f"Unknown log service: {service}")
    response = await docker_get(f"/containers/{quote(container, safe='')}/json")
    if response.status_code == 404:
        raise ExternalServiceError(f"Container not found: {container}")
    if response.status_code >= 400:
        raise ExternalServiceError(response.text)
    data = response.json()
    state = data.get("State") or {}
    return {
        "container": container,
        "status": state.get("Status") or "unknown",
        "running": bool(state.get("Running")),
        "restarting": bool(state.get("Restarting")),
        "exit_code": state.get("ExitCode"),
        "error": state.get("Error") or "",
    }


async def docker_get(path: str, params: dict[str, str] | None = None) -> httpx.Response:
    socket_path = os.getenv("HOLA_DOCKER_SOCKET", "/var/run/docker.sock")
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
            return await client.get(path, params=params)
    except OSError as exc:
        raise ExternalServiceError(f"Docker socket unavailable: {exc}") from exc


async def docker_post(path: str, params: dict[str, str] | None = None) -> httpx.Response:
    socket_path = os.getenv("HOLA_DOCKER_SOCKET", "/var/run/docker.sock")
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=15) as client:
            return await client.post(path, params=params)
    except OSError as exc:
        raise ExternalServiceError(f"Docker socket unavailable: {exc}") from exc


async def restart_container(service: str) -> None:
    container = LOG_CONTAINERS.get(service)
    if not container:
        raise ExternalServiceError(f"Unknown container service: {service}")
    response = await docker_post(f"/containers/{quote(container, safe='')}/restart")
    if response.status_code >= 400:
        raise ExternalServiceError(response.text)


async def start_cloudflared_login() -> dict[str, str]:
    global CLOUDFLARED_LOGIN_PROCESS

    existing_cert = cloudflared_origin_cert_path()
    if existing_cert.exists():
        return {
            "state": "ok",
            "login_url": "",
            "message": "Cloudflare login certificate is already available.",
        }

    if CLOUDFLARED_LOGIN_PROCESS and CLOUDFLARED_LOGIN_PROCESS.returncode is None:
        terminate_process(CLOUDFLARED_LOGIN_PROCESS)

    directory = cloudflared_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cloudflared_home_cert_path().parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(cloudflared_home_dir()),
        "TUNNEL_ORIGIN_CERT": str(cloudflared_home_cert_path()),
    }
    process = await asyncio.create_subprocess_exec(
        "cloudflared",
        "tunnel",
        "login",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    CLOUDFLARED_LOGIN_PROCESS = process
    output = await read_until_login_url(process)
    login_url = extract_first_url(output)
    if not login_url:
        existing_cert = cloudflared_origin_cert_path()
        if existing_cert.exists():
            return {
                "state": "ok",
                "login_url": "",
                "message": "Cloudflare login certificate is already available.",
            }
        terminate_process(process)
        raise ExternalServiceError(output.strip() or "cloudflared did not print a login URL")
    return {
        "state": "syncing",
        "login_url": login_url,
        "message": "Open the login URL, choose your Cloudflare account, and authorize the certificate.",
    }


async def create_cloudflared_tunnel(tunnel_name: str) -> dict[str, str]:
    name = tunnel_name.strip()
    if not name:
        raise ExternalServiceError("Tunnel name is required")
    origin_cert = cloudflared_origin_cert_path()
    if not origin_cert.exists():
        raise ExternalServiceError("Cloudflare login is not complete. Run cloudflared tunnel login first.")
    credentials_file = cloudflared_named_credentials_path(name)

    process = await asyncio.create_subprocess_exec(
        "cloudflared",
        "tunnel",
        "--origincert",
        str(origin_cert),
        "create",
        "--output",
        "json",
        "--credentials-file",
        str(credentials_file),
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise ExternalServiceError(error or output or "cloudflared tunnel create failed")

    data = parse_cloudflared_create_output(output)
    tunnel_id = data.get("id", "").strip()
    credentials_file = data.get("credentials_file", "").strip() or str(credentials_file)
    if not tunnel_id:
        raise ExternalServiceError(output or "cloudflared did not return a tunnel ID")
    return {
        "tunnel_name": name,
        "tunnel_id": tunnel_id,
        "credentials_file": credentials_file,
    }


async def route_cloudflared_dns(tunnel_id: str, hostname: str, overwrite: bool = True) -> None:
    tunnel = tunnel_id.strip()
    host = hostname.strip().lower().rstrip(".")
    if not tunnel:
        raise ExternalServiceError("Cloudflare Tunnel ID is required")
    if not host:
        raise ExternalServiceError("Cloudflare DNS hostname is required")
    origin_cert = cloudflared_origin_cert_path()
    if not origin_cert.exists():
        raise ExternalServiceError("Cloudflare login is not complete. Run cloudflared tunnel login first.")

    command = [
        "cloudflared",
        "tunnel",
        "--origincert",
        str(origin_cert),
        "route",
        "dns",
    ]
    if overwrite:
        command.append("--overwrite-dns")
    command.extend([tunnel, host])

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise ExternalServiceError(error or output or f"cloudflared tunnel route dns failed for {host}")


async def delete_cloudflare_tunnel_dns(zone_id: str, api_token: str, tunnel_id: str, hostname: str) -> int:
    zone = zone_id.strip()
    token = api_token.strip()
    tunnel = tunnel_id.strip()
    host = hostname.strip().lower().rstrip(".")
    if not zone:
        raise ExternalServiceError("Cloudflare Zone ID is required to delete DNS records")
    if not token:
        raise ExternalServiceError("Cloudflare API token is required to delete DNS records")
    if not tunnel:
        raise ExternalServiceError("Cloudflare Tunnel ID is required")
    if not host:
        raise ExternalServiceError("Cloudflare DNS hostname is required")

    target = f"{tunnel}.cfargotunnel.com"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url="https://api.cloudflare.com/client/v4", timeout=20, headers=headers) as client:
        response = await client.get(f"/zones/{zone}/dns_records", params={"type": "CNAME", "name": host, "per_page": "100"})
        raise_for_cloudflare_api_error(response)
        records = response.json().get("result") or []
        deleted = 0
        for record in records:
            content = str(record.get("content") or "").rstrip(".")
            if content != target:
                continue
            record_id = str(record.get("id") or "")
            if not record_id:
                continue
            delete_response = await client.delete(f"/zones/{zone}/dns_records/{record_id}")
            raise_for_cloudflare_api_error(delete_response)
            deleted += 1
    return deleted


def raise_for_cloudflare_api_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        data = response.json()
        if data.get("success", True):
            return
    try:
        data = response.json()
    except json.JSONDecodeError:
        raise ExternalServiceError(response.text or f"Cloudflare API request failed with {response.status_code}") from None
    errors = data.get("errors") or []
    message = "; ".join(str(error.get("message") or error) for error in errors) if errors else response.text
    raise ExternalServiceError(message or f"Cloudflare API request failed with {response.status_code}")


def get_cloudflared_login_status() -> dict[str, Any]:
    origin_cert = cloudflared_origin_cert_path()
    if origin_cert.exists():
        return {
            "state": "ok",
            "message": "Cloudflare login certificate is available.",
            "login_running": False,
        }
    if CLOUDFLARED_LOGIN_PROCESS and CLOUDFLARED_LOGIN_PROCESS.returncode is None:
        return {
            "state": "syncing",
            "message": "Waiting for Cloudflare browser authorization.",
            "login_running": True,
        }
    return {
        "state": "warning",
        "message": "Cloudflare login has not completed.",
        "login_running": False,
    }


def logout_cloudflared_login() -> dict[str, Any]:
    global CLOUDFLARED_LOGIN_PROCESS

    if CLOUDFLARED_LOGIN_PROCESS and CLOUDFLARED_LOGIN_PROCESS.returncode is None:
        terminate_process(CLOUDFLARED_LOGIN_PROCESS)
    CLOUDFLARED_LOGIN_PROCESS = None

    removed: list[str] = []
    for path in cloudflared_origin_cert_candidates():
        if not path.exists():
            continue
        path.unlink()
        removed.append(str(path))

    status = get_cloudflared_login_status()
    status["removed"] = removed
    return status


def parse_cloudflared_create_output(output: str) -> dict[str, str]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        tunnel_id = ""
        credentials_file = ""
        id_match = re.search(r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b", output)
        if id_match:
            tunnel_id = id_match.group(1)
        credential_match = re.search(r"(/[^\s]+\.json)", output)
        if credential_match:
            credentials_file = credential_match.group(1)
        return {"id": tunnel_id, "credentials_file": credentials_file}
    return {
        "id": str(data.get("id") or data.get("ID") or ""),
        "credentials_file": str(data.get("credentials_file") or data.get("credentialsFile") or ""),
    }


async def read_until_login_url(process: asyncio.subprocess.Process) -> str:
    chunks: list[str] = []
    assert process.stdout is not None
    for _ in range(40):
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=0.5)
        except asyncio.TimeoutError:
            if process.returncode is not None:
                break
            continue
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        chunks.append(text)
        if extract_first_url("".join(chunks)):
            return "".join(chunks)
    return "".join(chunks)


def extract_first_url(output: str) -> str:
    match = re.search(r"https?://\S+", output)
    return match.group(0).rstrip(".,)") if match else ""


def terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return


async def check_cloudflared_connection() -> tuple[str, str]:
    state = await get_container_state("cloudflare")
    if not state["running"]:
        return "error", f"cloudflared container is not running ({state['status']})"

    logs = await get_container_logs("cloudflare", 250)
    lines = [line for line in logs.splitlines() if line.strip()]
    if any(marker in logs for marker in CLOUDFLARED_CONNECTED_MARKERS):
        return "ok", "Cloudflare Tunnel connected"

    latest_error = ""
    for line in reversed(lines):
        if any(marker in line for marker in CLOUDFLARED_ERROR_MARKERS):
            latest_error = line
            break
    if latest_error:
        return "error", f"Cloudflare Tunnel is not connected: {simplify_log_line(latest_error)}"
    return "warning", "Cloudflare Tunnel runtime initialized; waiting for connector"


def simplify_log_line(line: str) -> str:
    parts = line.split(" ", 2)
    if len(parts) == 3 and parts[0].startswith("20") and len(parts[1]) == 3:
        return parts[2]
    return line


def decode_docker_log_stream(payload: bytes) -> str:
    frames: list[bytes] = []
    offset = 0
    while offset + 8 <= len(payload):
        header = payload[offset : offset + 8]
        stream_type = header[0]
        if stream_type not in {1, 2} or header[1:4] != b"\x00\x00\x00":
            return payload.decode("utf-8", errors="replace")
        size = int.from_bytes(header[4:8], "big")
        offset += 8
        if offset + size > len(payload):
            return payload.decode("utf-8", errors="replace")
        frames.append(payload[offset : offset + size])
        offset += size
    if offset != len(payload):
        return payload.decode("utf-8", errors="replace")
    return b"".join(frames).decode("utf-8", errors="replace")


@dataclass
class CaddyClient:
    admin_url: str

    async def test(self) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.admin_url.rstrip('/')}/config/")
        if response.status_code >= 400:
            raise ExternalServiceError(response.text)
        return "Caddy Admin API is reachable"

    async def load_config(self, config: HolaConfig) -> None:
        payload = build_caddy_config(config)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.admin_url.rstrip('/')}/load",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise ExternalServiceError(response.text)


@dataclass
class AdGuardClient:
    url: str
    username: str
    password: str

    async def test(self) -> str:
        async with httpx.AsyncClient(timeout=10, auth=(self.username, self.password)) as client:
            response = await client.get(f"{self.url.rstrip('/')}/control/rewrite/list")
        self._raise_for_error(response)
        return "AdGuard Home API is reachable"

    async def check_auth(self) -> None:
        async with httpx.AsyncClient(timeout=10, auth=(self.username, self.password)) as client:
            response = await client.get(f"{self.url.rstrip('/')}/control/rewrite/list")
        self._raise_for_error(response)

    async def set_rewrite(self, domain: str, answer: str) -> None:
        async with httpx.AsyncClient(timeout=15, auth=(self.username, self.password)) as client:
            response = await client.post(
                f"{self.url.rstrip('/')}/control/rewrite/add",
                json={"domain": domain, "answer": answer},
            )
        self._raise_for_error(response)

    async def delete_rewrite(self, domain: str, answer: str) -> None:
        async with httpx.AsyncClient(timeout=15, auth=(self.username, self.password)) as client:
            response = await client.post(
                f"{self.url.rstrip('/')}/control/rewrite/delete",
                json={"domain": domain, "answer": answer},
            )
        self._raise_for_error(response, ignore_statuses={404})

    def _raise_for_error(self, response: httpx.Response, ignore_statuses: set[int] | None = None) -> None:
        if ignore_statuses and response.status_code in ignore_statuses:
            return
        if response.status_code in {401, 403}:
            raise ExternalServiceAuthError("AdGuard Home authentication failed. Check the username and password.")
        if response.status_code >= 400:
            raise ExternalServiceError(response.text)


CADDY_BOOTSTRAP_CONFIG = {
    "admin": {"listen": "0.0.0.0:2019"},
}


def ensure_caddy_bootstrap(config_dir: str) -> bool:
    """Create a minimal Caddy bootstrap config if one doesn't exist.

    Returns True if the file was created (first run), False if it already existed.
    """
    config_path = Path(config_dir) / "caddy.json"
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(CADDY_BOOTSTRAP_CONFIG, indent=2) + "\n", encoding="utf-8")
    return True


def build_caddy_config(config: HolaConfig) -> dict[str, Any]:
    routes = []
    for proxy in config.proxies:
        if not proxy.enabled:
            continue
        upstream = urlparse(proxy.upstream_url)
        dial = upstream.netloc
        handler: dict[str, Any] = {
            "handler": "reverse_proxy",
            "upstreams": [{"dial": dial}],
        }
        if upstream.scheme == "https":
            handler["transport"] = {"protocol": "http", "tls": {}}
        routes.append(
            {
                "match": [{"host": [proxy.hostname]}],
                "handle": [handler],
                "terminal": True,
            }
        )
    routes.append(
        {
            "handle": [
                {
                    "handler": "static_response",
                    "status_code": 404,
                    "body": "Hola has no proxy rule for this host.\n",
                }
            ]
        }
    )
    tls_policy: dict[str, Any] = {"issuers": [{"module": "acme"}]}
    if config.caddy.acme_email:
        tls_policy["issuers"][0]["email"] = config.caddy.acme_email
    return {
        "admin": {"listen": "0.0.0.0:2019"},
        "apps": {
            "http": {
                "servers": {
                    "hola": {
                        "listen": [":80", ":443"],
                        "routes": routes,
                    }
                }
            },
            "tls": {
                "automation": {
                    "policies": [tls_policy],
                }
            },
        }
    }


def cloudflared_ingress_config(tunnel_id: str, credentials_file: str, hostnames: list[str], caddy_origin: str = "http://caddy:80") -> str:
    payload = {
        "tunnel": tunnel_id,
        "credentials-file": credentials_file,
        "ingress": [{"hostname": hostname, "service": caddy_origin} for hostname in hostnames] + [{"service": "http_status:404"}],
    }
    return yaml.safe_dump(payload, sort_keys=False)


def write_cloudflared_runtime(
    tunnel_id: str,
    credentials_file: str,
    proxy_enabled: bool = False,
    proxy_url: str = "",
    hostnames: list[str] | None = None,
) -> Path:
    directory = cloudflared_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    tunnel_path = directory / "tunnel-id"
    tunnel_path.write_text(tunnel_id, encoding="utf-8")
    os.chmod(tunnel_path, 0o600)
    config_path = cloudflared_config_path()
    config_path.write_text(cloudflared_ingress_config(tunnel_id, credentials_file, hostnames or []), encoding="utf-8")
    os.chmod(config_path, 0o600)
    runtime_path = directory / "runtime.env"
    lines = [
        f"TUNNEL_ID={shlex.quote(tunnel_id)}",
        f"TUNNEL_CRED_FILE={shlex.quote(credentials_file)}",
        f"TUNNEL_CONFIG_FILE={shlex.quote(str(config_path))}",
    ]
    if proxy_enabled and proxy_url:
        lines.extend(
            [
                "TUNNEL_TRANSPORT_PROTOCOL=http2",
                f"ALL_PROXY={shlex.quote(proxy_url)}",
                f"HTTPS_PROXY={shlex.quote(proxy_url)}",
                f"HTTP_PROXY={shlex.quote(proxy_url)}",
            ]
        )
    else:
        lines.append("TUNNEL_TRANSPORT_PROTOCOL=quic")
    runtime_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(runtime_path, 0o600)
    return tunnel_path
