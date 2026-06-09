from pathlib import Path

from fastapi.testclient import TestClient


def test_api_config_and_proxy_crud(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CADDY_CONFIG_DIR", str(tmp_path / "caddy"))

    import hola.main as main
    from hola.config_store import ConfigStore
    from hola.sync import SyncManager

    main.store = ConfigStore.from_env()
    main.sync_manager = SyncManager(main.store)

    with TestClient(main.app) as client:
        config = client.get("/api/config").json()
        assert config["project"] == "Hola"

        response = client.post(
            "/api/admin/password",
            json={"username": "admin", "password": "123456"},
        )
        assert response.status_code == 200

        response = client.post(
            "/api/login",
            json={"username": "admin", "password": "123456"},
        )
        assert response.status_code == 200

        response = client.post(
            "/api/proxies",
            json={
                "hostname": "nas.example.com",
                "upstream_url": "http://192.168.1.20:5000",
                "enabled": True,
                "note": "NAS",
            },
        )
        assert response.status_code == 200
        proxy = response.json()
        assert proxy["hostname"] == "nas.example.com"

        response = client.delete(f"/api/proxies/{proxy['id']}")
        assert response.status_code == 200


def test_api_reads_allowed_service_logs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CADDY_CONFIG_DIR", str(tmp_path / "caddy"))

    import hola.main as main
    from hola.config_store import ConfigStore
    from hola.sync import SyncManager

    async def fake_get_container_logs(service: str, tail: int = 200) -> str:
        assert service == "cloudflare"
        assert tail == 50
        return "cloudflared log line\n"

    main.store = ConfigStore.from_env()
    main.sync_manager = SyncManager(main.store)
    monkeypatch.setattr(main, "get_container_logs", fake_get_container_logs)

    with TestClient(main.app) as client:
        response = client.get("/api/logs/cloudflare?tail=50")

    assert response.status_code == 200
    assert response.json() == {
        "service": "cloudflare",
        "tail": 50,
        "logs": "cloudflared log line\n",
    }


def test_api_creates_cloudflare_tunnel_and_saves_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CADDY_CONFIG_DIR", str(tmp_path / "caddy"))

    import hola.main as main
    from hola.config_store import ConfigStore
    from hola.sync import SyncManager

    async def fake_create_cloudflared_tunnel(name: str) -> dict[str, str]:
        assert name == "hola-home"
        return {
            "tunnel_name": name,
            "tunnel_id": "11111111-1111-1111-1111-111111111111",
            "credentials_file": "/etc/cloudflared/credentials-hola-home.json",
        }

    main.store = ConfigStore.from_env()
    main.sync_manager = SyncManager(main.store)
    monkeypatch.setattr(main, "create_cloudflared_tunnel", fake_create_cloudflared_tunnel)
    monkeypatch.setattr(main, "schedule_sync", lambda background_tasks: None)

    with TestClient(main.app) as client:
        response = client.post("/api/cloudflare/tunnel", json={"name": "hola-home"})

    assert response.status_code == 200
    cloudflare = response.json()["cloudflare"]
    assert cloudflare["enabled"] is True
    assert cloudflare["tunnel_name"] == "hola-home"
    assert cloudflare["tunnel_id"] == "11111111-1111-1111-1111-111111111111"
    assert cloudflare["credentials_file"] == "/etc/cloudflared/credentials-hola-home.json"


def test_api_logs_out_cloudflare_and_clears_local_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CADDY_CONFIG_DIR", str(tmp_path / "caddy"))
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path / "cloudflared"))

    import hola.main as main
    from hola.config_store import ConfigStore
    from hola.sync import SyncManager

    main.store = ConfigStore.from_env()
    main.sync_manager = SyncManager(main.store)
    monkeypatch.setattr(main, "schedule_sync", lambda background_tasks: None)

    config = main.store.read(decrypt=True)
    config.cloudflare.enabled = True
    config.cloudflare.tunnel_id = "11111111-1111-1111-1111-111111111111"
    config.cloudflare.credentials_file = "/etc/cloudflared/credentials-hola.json"
    main.store.write(config)

    cert_path = tmp_path / "cloudflared" / ".cloudflared" / "cert.pem"
    cert_path.parent.mkdir(parents=True)
    cert_path.write_text("certificate", encoding="utf-8")

    with TestClient(main.app) as client:
        response = client.delete("/api/cloudflare/login")

    assert response.status_code == 200
    cloudflare = response.json()["cloudflare"]
    assert cloudflare["enabled"] is False
    assert cloudflare["tunnel_id"] == ""
    assert cloudflare["credentials_file"] == ""
    assert response.json()["login_status"]["state"] == "warning"
    assert not cert_path.exists()


def test_cloudflare_login_status_forces_cloudflare_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_APP_DATA", str(tmp_path))
    monkeypatch.setenv("HOLA_CONFIG_PATH", str(tmp_path / "hola.yaml"))
    monkeypatch.setenv("HOLA_CADDY_CONFIG_DIR", str(tmp_path / "caddy"))
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path / "cloudflared"))

    import hola.main as main
    from hola.config_store import ConfigStore
    from hola.sync import SyncManager

    main.store = ConfigStore.from_env()
    main.sync_manager = SyncManager(main.store)

    cert_path = tmp_path / "cloudflared" / ".cloudflared" / "cert.pem"
    cert_path.parent.mkdir(parents=True)
    cert_path.write_text("certificate", encoding="utf-8")

    with TestClient(main.app) as client:
        response = client.get("/api/cloudflare/login/status")

    assert response.status_code == 200
    assert response.json()["state"] == "ok"
    assert main.store.read(decrypt=True).cloudflare.enabled is True
