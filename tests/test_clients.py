import httpx
import pytest

import hola.sync as sync_module
from hola.clients import AdGuardClient, ExternalServiceAuthError, build_caddy_config
from hola.config_store import ConfigStore
from hola.models import HolaConfig, ProxyRule
from hola.sync import SyncManager


@pytest.mark.asyncio
async def test_adguard_test_detects_invalid_credentials(monkeypatch) -> None:
    captured_paths = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            assert kwargs["auth"] == ("admin", "bad-password")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            captured_paths.append(url)
            return httpx.Response(401, text="Unauthorized")

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(ExternalServiceAuthError, match="authentication failed"):
        await AdGuardClient("http://adguard.test", "admin", "bad-password").test()

    assert captured_paths == ["http://adguard.test/control/rewrite/list"]


@pytest.mark.asyncio
async def test_adguard_sync_checks_auth_without_proxy_rules(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path / "cloudflared"))
    store = ConfigStore.from_env()
    config = store.read(decrypt=True)
    config.caddy.admin_url = ""
    config.adguard.url = "http://adguard.test"
    config.adguard.username = "admin"
    config.adguard.password = "bad-password"
    store.write(config)

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            assert kwargs["auth"] == ("admin", "bad-password")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            return httpx.Response(401, text="Unauthorized")

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    status = await SyncManager(store).reconcile()

    assert status.adguard.state == "error"
    assert "AdGuard Home authentication failed" in status.adguard.message


def test_build_caddy_config_routes_hosts_to_upstreams() -> None:
    config = HolaConfig()
    config.caddy.acme_email = "admin@example.com"
    config.proxies = [
        ProxyRule(hostname="nas.example.com", upstream_url="http://192.168.1.20:5000"),
        ProxyRule(hostname="git.example.com", upstream_url="https://192.168.1.30:8443"),
    ]

    payload = build_caddy_config(config)
    routes = payload["apps"]["http"]["servers"]["hola"]["routes"]
    assert routes[0]["match"][0]["host"] == ["nas.example.com"]
    assert routes[0]["handle"][0]["upstreams"][0]["dial"] == "192.168.1.20:5000"
    assert routes[1]["handle"][0]["transport"]["tls"] == {}
    assert payload["apps"]["tls"]["automation"]["policies"][0]["issuers"][0]["email"] == "admin@example.com"


@pytest.mark.asyncio
async def test_cloudflare_sync_routes_enabled_proxy_hostnames(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path / "cloudflared"))
    store = ConfigStore.from_env()
    config = store.read(decrypt=True)
    config.caddy.admin_url = ""
    config.adguard.enabled = False
    config.cloudflare.enabled = True
    config.cloudflare.tunnel_id = "11111111-1111-1111-1111-111111111111"
    config.cloudflare.credentials_file = "/etc/cloudflared/credentials-hola.json"
    config.proxies = [
        ProxyRule(hostname="nas.example.com", upstream_url="http://192.168.1.20:5000"),
        ProxyRule(hostname="off.example.com", upstream_url="http://192.168.1.21:5000", enabled=False),
    ]
    store.write(config)
    routed = []
    runtime = {}

    async def fake_route_cloudflared_dns(tunnel_id: str, hostname: str, overwrite: bool = True) -> None:
        routed.append((tunnel_id, hostname, overwrite))

    async def fake_restart_container(service: str) -> None:
        assert service == "cloudflare"

    async def fake_wait_for_cloudflared_connection(timeout: int = 45, interval: int = 3, since: int | None = None) -> tuple[str, str]:
        assert since is not None
        return "ok", "Cloudflare Tunnel connected"

    def fake_write_cloudflared_runtime(tunnel_id: str, credentials_file: str, proxy_enabled: bool, proxy_url: str, hostnames: list[str]) -> None:
        runtime.update(
            {
                "tunnel_id": tunnel_id,
                "credentials_file": credentials_file,
                "proxy_enabled": proxy_enabled,
                "proxy_url": proxy_url,
                "hostnames": hostnames,
            }
        )

    async def fake_wait_for_tls_certificates(hostnames: list[str], connect_host: str = "caddy", port: int = 443, timeout: int = 45, interval: int = 5) -> tuple[bool, str]:
        return True, f"SSL certificates are ready for {len(hostnames)} hostname(s)"

    monkeypatch.setattr(sync_module, "route_cloudflared_dns", fake_route_cloudflared_dns)
    monkeypatch.setattr(sync_module, "restart_container", fake_restart_container)
    monkeypatch.setattr(sync_module, "wait_for_cloudflared_connection", fake_wait_for_cloudflared_connection)
    monkeypatch.setattr(sync_module, "write_cloudflared_runtime", fake_write_cloudflared_runtime)
    monkeypatch.setattr(sync_module, "wait_for_tls_certificates", fake_wait_for_tls_certificates)

    status = await SyncManager(store).reconcile()

    assert routed == [("11111111-1111-1111-1111-111111111111", "nas.example.com", True)]
    assert runtime["hostnames"] == ["nas.example.com"]
    assert status.cloudflare.state == "ok"
    assert "DNS routes synced for 1 hostname(s)" in status.cloudflare.message


@pytest.mark.asyncio
async def test_adguard_sync_uses_caddy_lan_ip_for_rewrites(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    store = ConfigStore.from_env()
    config = store.read(decrypt=True)
    config.cloudflare.enabled = False
    config.caddy.admin_url = ""
    config.caddy.local_ip = "192.168.1.10"
    config.adguard.url = "http://adguard.test"
    config.adguard.username = "admin"
    config.adguard.password = "good-password"
    config.proxies = [
        ProxyRule(hostname="nas.example.com", upstream_url="http://192.168.1.20:5000"),
        ProxyRule(hostname="off.example.com", upstream_url="http://192.168.1.21:5000", enabled=False),
    ]
    store.write(config)
    rewrites = []

    class FakeAdGuardClient:
        def __init__(self, url: str, username: str, password: str) -> None:
            assert (url, username, password) == ("http://adguard.test", "admin", "good-password")

        async def check_auth(self) -> None:
            return None

        async def set_rewrite(self, domain: str, answer: str) -> None:
            rewrites.append(("set", domain, answer))

        async def delete_rewrite(self, domain: str, answer: str) -> None:
            rewrites.append(("delete", domain, answer))

    monkeypatch.setattr(sync_module, "AdGuardClient", FakeAdGuardClient)

    status = await SyncManager(store).reconcile()

    assert rewrites == [
        ("set", "nas.example.com", "192.168.1.10"),
        ("delete", "off.example.com", "192.168.1.10"),
    ]
    assert status.adguard.state == "ok"


@pytest.mark.asyncio
async def test_caddy_waits_for_cloudflare_before_requesting_certificates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    store = ConfigStore.from_env()
    config = store.read(decrypt=True)
    config.cloudflare.enabled = True
    config.cloudflare.tunnel_id = "11111111-1111-1111-1111-111111111111"
    config.cloudflare.credentials_file = "/etc/cloudflared/credentials-hola.json"
    config.caddy.admin_url = "http://caddy.test"
    config.adguard.enabled = False
    config.proxies = [
        ProxyRule(hostname="notes.example.com", upstream_url="http://192.168.1.20:5000"),
    ]
    store.write(config)
    loaded = False

    async def fake_route_cloudflared_dns(tunnel_id: str, hostname: str, overwrite: bool = True) -> None:
        return None

    async def fake_restart_container(service: str) -> None:
        return None

    async def fake_wait_for_cloudflared_connection(timeout: int = 45, interval: int = 3, since: int | None = None) -> tuple[str, str]:
        return "warning", "Cloudflare Tunnel runtime initialized; waiting for connector"

    def fake_write_cloudflared_runtime(tunnel_id: str, credentials_file: str, proxy_enabled: bool, proxy_url: str, hostnames: list[str]) -> None:
        return None

    class FakeCaddyClient:
        def __init__(self, admin_url: str) -> None:
            return None

        async def load_config(self, config: HolaConfig) -> None:
            nonlocal loaded
            loaded = True

    monkeypatch.setattr(sync_module, "route_cloudflared_dns", fake_route_cloudflared_dns)
    monkeypatch.setattr(sync_module, "restart_container", fake_restart_container)
    monkeypatch.setattr(sync_module, "wait_for_cloudflared_connection", fake_wait_for_cloudflared_connection)
    monkeypatch.setattr(sync_module, "write_cloudflared_runtime", fake_write_cloudflared_runtime)
    monkeypatch.setattr(sync_module, "CaddyClient", FakeCaddyClient)

    status = await SyncManager(store).reconcile()

    assert status.cloudflare.state == "syncing"
    assert status.caddy.state == "syncing"
    assert status.overall.state == "syncing"
    assert status.caddy.message == "Waiting for Cloudflare Tunnel before requesting SSL certificates"
    assert loaded is False


@pytest.mark.asyncio
async def test_remove_proxy_cleans_external_dns_and_rewrites(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    store = ConfigStore.from_env()
    removed = ProxyRule(hostname="old.example.com", upstream_url="http://192.168.1.20:5000")
    remaining = ProxyRule(hostname="new.example.com", upstream_url="http://192.168.1.21:5000")
    config = store.read(decrypt=True)
    config.caddy.admin_url = ""
    config.caddy.local_ip = "192.168.1.10"
    config.cloudflare.enabled = True
    config.cloudflare.tunnel_id = "11111111-1111-1111-1111-111111111111"
    config.cloudflare.credentials_file = "/etc/cloudflared/credentials-hola.json"
    config.cloudflare.zone_id = "zone-1"
    config.cloudflare.api_token = "token-1"
    config.adguard.url = "http://adguard.test"
    config.adguard.username = "admin"
    config.adguard.password = "good-password"
    config.proxies = [remaining]
    store.write(config)
    deleted_dns = []
    rewrites = []
    runtime = {}

    async def fake_delete_cloudflare_tunnel_dns(zone_id: str, api_token: str, tunnel_id: str, hostname: str) -> int:
        deleted_dns.append((zone_id, api_token, tunnel_id, hostname))
        return 1

    async def fake_route_cloudflared_dns(tunnel_id: str, hostname: str, overwrite: bool = True) -> None:
        return None

    async def fake_restart_container(service: str) -> None:
        return None

    async def fake_wait_for_cloudflared_connection(timeout: int = 45, interval: int = 3, since: int | None = None) -> tuple[str, str]:
        return "ok", "Cloudflare Tunnel connected"

    def fake_write_cloudflared_runtime(tunnel_id: str, credentials_file: str, proxy_enabled: bool, proxy_url: str, hostnames: list[str]) -> None:
        runtime["hostnames"] = hostnames

    async def fake_wait_for_tls_certificates(hostnames: list[str], connect_host: str = "caddy", port: int = 443, timeout: int = 45, interval: int = 5) -> tuple[bool, str]:
        return True, f"SSL certificates are ready for {len(hostnames)} hostname(s)"

    class FakeAdGuardClient:
        def __init__(self, url: str, username: str, password: str) -> None:
            return None

        async def check_auth(self) -> None:
            return None

        async def set_rewrite(self, domain: str, answer: str) -> None:
            rewrites.append(("set", domain, answer))

        async def delete_rewrite(self, domain: str, answer: str) -> None:
            rewrites.append(("delete", domain, answer))

    monkeypatch.setattr(sync_module, "delete_cloudflare_tunnel_dns", fake_delete_cloudflare_tunnel_dns)
    monkeypatch.setattr(sync_module, "route_cloudflared_dns", fake_route_cloudflared_dns)
    monkeypatch.setattr(sync_module, "restart_container", fake_restart_container)
    monkeypatch.setattr(sync_module, "wait_for_cloudflared_connection", fake_wait_for_cloudflared_connection)
    monkeypatch.setattr(sync_module, "write_cloudflared_runtime", fake_write_cloudflared_runtime)
    monkeypatch.setattr(sync_module, "wait_for_tls_certificates", fake_wait_for_tls_certificates)
    monkeypatch.setattr(sync_module, "AdGuardClient", FakeAdGuardClient)

    status = await SyncManager(store).remove_proxy(removed)

    assert deleted_dns == [("zone-1", "token-1", "11111111-1111-1111-1111-111111111111", "old.example.com")]
    assert ("delete", "old.example.com", "192.168.1.10") in rewrites
    assert ("set", "new.example.com", "192.168.1.10") in rewrites
    assert runtime["hostnames"] == ["new.example.com"]
    assert status.cloudflare.state == "ok"
    assert status.adguard.state == "ok"
