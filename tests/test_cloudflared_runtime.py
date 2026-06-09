from pathlib import Path

import httpx
import pytest
import yaml

from hola.clients import (
    cloudflared_ingress_config,
    cloudflared_origin_cert_path,
    delete_cloudflare_tunnel_dns,
    decode_docker_log_stream,
    get_cloudflared_login_status,
    logout_cloudflared_login,
    route_cloudflared_dns,
    write_cloudflared_runtime,
)


def test_write_cloudflared_runtime_supports_proxy_with_http2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))

    write_cloudflared_runtime(
        "11111111-1111-1111-1111-111111111111",
        "/etc/cloudflared/credentials-hola.json",
        True,
        "socks5://127.0.0.1:1080",
        ["nas.example.com"],
    )

    assert (tmp_path / "tunnel-id").read_text() == "11111111-1111-1111-1111-111111111111"
    runtime_env = (tmp_path / "runtime.env").read_text()
    assert "TUNNEL_ID=11111111-1111-1111-1111-111111111111" in runtime_env
    assert "TUNNEL_CRED_FILE=/etc/cloudflared/credentials-hola.json" in runtime_env
    assert f"TUNNEL_CONFIG_FILE={tmp_path / 'config.yml'}" in runtime_env
    assert "TUNNEL_TRANSPORT_PROTOCOL=http2" in runtime_env
    assert "ALL_PROXY=socks5://127.0.0.1:1080" in runtime_env
    assert "HTTPS_PROXY=socks5://127.0.0.1:1080" in runtime_env
    assert "service: http://caddy:80" in (tmp_path / "config.yml").read_text()


def test_write_cloudflared_runtime_uses_quic_without_proxy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))

    write_cloudflared_runtime("11111111-1111-1111-1111-111111111111", "/etc/cloudflared/credentials-hola.json", False, "")

    assert (tmp_path / "runtime.env").read_text() == (
        "TUNNEL_ID=11111111-1111-1111-1111-111111111111\n"
        "TUNNEL_CRED_FILE=/etc/cloudflared/credentials-hola.json\n"
        f"TUNNEL_CONFIG_FILE={tmp_path / 'config.yml'}\n"
        "TUNNEL_TRANSPORT_PROTOCOL=quic\n"
    )


def test_cloudflared_ingress_routes_hostnames_to_caddy() -> None:
    payload = yaml.safe_load(cloudflared_ingress_config(
        "11111111-1111-1111-1111-111111111111",
        "/etc/cloudflared/credentials-hola.json",
        ["nas.example.com", "git.example.com"],
    ))

    assert payload == {
        "tunnel": "11111111-1111-1111-1111-111111111111",
        "credentials-file": "/etc/cloudflared/credentials-hola.json",
        "ingress": [
            {"hostname": "nas.example.com", "service": "http://caddy:80"},
            {"hostname": "git.example.com", "service": "http://caddy:80"},
            {"service": "http_status:404"},
        ],
    }


def test_decode_docker_log_stream_merges_stdout_and_stderr() -> None:
    stdout = b"hello\n"
    stderr = b"error\n"
    payload = (
        b"\x01\x00\x00\x00" + len(stdout).to_bytes(4, "big") + stdout
        + b"\x02\x00\x00\x00" + len(stderr).to_bytes(4, "big") + stderr
    )

    assert decode_docker_log_stream(payload) == "hello\nerror\n"


def test_decode_docker_log_stream_accepts_plain_text() -> None:
    assert decode_docker_log_stream(b"plain log\n") == "plain log\n"


def test_cloudflared_origin_cert_prefers_persistent_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))
    cert_path = tmp_path / ".cloudflared" / "cert.pem"
    cert_path.parent.mkdir()
    cert_path.write_text("certificate", encoding="utf-8")

    assert cloudflared_origin_cert_path() == cert_path
    assert get_cloudflared_login_status()["state"] == "ok"


def test_cloudflared_origin_cert_accepts_legacy_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))
    cert_path = tmp_path / "cert.pem"
    cert_path.write_text("certificate", encoding="utf-8")

    assert cloudflared_origin_cert_path() == cert_path
    status = get_cloudflared_login_status()
    assert status["state"] == "ok"
    assert "origin_cert" not in status


def test_cloudflared_logout_removes_login_certificates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))
    cert_path = tmp_path / ".cloudflared" / "cert.pem"
    legacy_cert_path = tmp_path / "cert.pem"
    cert_path.parent.mkdir()
    cert_path.write_text("certificate", encoding="utf-8")
    legacy_cert_path.write_text("legacy certificate", encoding="utf-8")

    status = logout_cloudflared_login()

    assert status["state"] == "warning"
    assert not cert_path.exists()
    assert not legacy_cert_path.exists()


@pytest.mark.asyncio
async def test_route_cloudflared_dns_uses_tunnel_route_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOLA_CLOUDFLARED_DATA", str(tmp_path))
    cert_path = tmp_path / ".cloudflared" / "cert.pem"
    cert_path.parent.mkdir()
    cert_path.write_text("certificate", encoding="utf-8")
    captured_command = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_command.extend(args)
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    await route_cloudflared_dns("11111111-1111-1111-1111-111111111111", "Nas.Example.Com.")

    assert captured_command == [
        "cloudflared",
        "tunnel",
        "--origincert",
        str(cert_path),
        "route",
        "dns",
        "--overwrite-dns",
        "11111111-1111-1111-1111-111111111111",
        "nas.example.com",
    ]


@pytest.mark.asyncio
async def test_delete_cloudflare_tunnel_dns_removes_matching_cname(monkeypatch) -> None:
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            assert kwargs["base_url"] == "https://api.cloudflare.com/client/v4"
            assert kwargs["headers"] == {"Authorization": "Bearer token-1"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path, params):
            calls.append(("get", path, params))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": [
                        {"id": "record-1", "content": "11111111-1111-1111-1111-111111111111.cfargotunnel.com"},
                        {"id": "record-2", "content": "other.cfargotunnel.com"},
                    ],
                },
            )

        async def delete(self, path):
            calls.append(("delete", path))
            return httpx.Response(200, json={"success": True})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    deleted = await delete_cloudflare_tunnel_dns(
        "zone-1",
        "token-1",
        "11111111-1111-1111-1111-111111111111",
        "Old.Example.Com.",
    )

    assert deleted == 1
    assert calls == [
        ("get", "/zones/zone-1/dns_records", {"type": "CNAME", "name": "old.example.com", "per_page": "100"}),
        ("delete", "/zones/zone-1/dns_records/record-1"),
    ]
