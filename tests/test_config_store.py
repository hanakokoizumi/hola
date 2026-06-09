from pathlib import Path

import yaml

from hola.config_store import ConfigStore
from hola.models import HolaConfig, ProxyRule, SECRET_PLACEHOLDER


def test_yaml_store_encrypts_secrets_and_preserves_placeholders(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "hola.yaml", tmp_path)
    config = HolaConfig()
    config.adguard.password = "adguard-pass"
    store.write(config, backup=False)

    raw = yaml.safe_load((tmp_path / "hola.yaml").read_text())
    assert raw["adguard"]["password"].startswith("enc:v1:")
    assert store.read(decrypt=True).adguard.password == "adguard-pass"

    public = store.read(decrypt=False).public_dict()
    public["cloudflare"]["proxy_url"] = "http://127.0.0.1:7890"
    updated = store.update_from_public_payload(public)
    assert updated.cloudflare.proxy_url == "http://127.0.0.1:7890"
    assert store.read(decrypt=True).adguard.password == "adguard-pass"


def test_config_store_creates_backup_on_write(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "hola.yaml", tmp_path)
    store.write(HolaConfig(), backup=False)
    config = store.read(decrypt=True)
    config.proxies.append(ProxyRule(hostname="nas.example.com", upstream_url="http://192.168.1.20:5000"))
    store.write(config)
    assert list((tmp_path / "backups").glob("hola.*.yaml"))
