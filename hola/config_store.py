from __future__ import annotations

import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import HolaConfig, SECRET_PLACEHOLDER
from .security import SecretBox, hash_password


SECRET_FIELDS = {
    ("cloudflare", "api_token"),
    ("adguard", "password"),
}


class ConfigStore:
    def __init__(self, config_path: Path, app_data: Path) -> None:
        self.config_path = config_path
        self.app_data = app_data
        self.secret_box = SecretBox(app_data / "secret.key")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "ConfigStore":
        app_data = Path(os.getenv("HOLA_APP_DATA", "./data/app"))
        config_path = Path(os.getenv("HOLA_CONFIG_PATH", str(app_data / "hola.yaml")))
        return cls(config_path=config_path, app_data=app_data)

    def ensure_exists(self) -> None:
        if self.config_path.exists():
            return
        config = HolaConfig()
        env_defaults = {
            "caddy": {
                "admin_url": os.getenv("HOLA_CADDY_ADMIN_URL", "http://caddy:2019"),
                "local_ip": os.getenv("HOLA_LOCAL_IP", ""),
                "acme_email": os.getenv("HOLA_ACME_EMAIL", ""),
            },
            "cloudflare": {
                "tunnel_name": os.getenv("HOLA_CLOUDFLARE_TUNNEL_NAME", ""),
                "tunnel_id": os.getenv("HOLA_CLOUDFLARE_TUNNEL_ID", ""),
                "credentials_file": os.getenv("HOLA_CLOUDFLARE_CREDENTIALS_FILE", ""),
                "zone_id": os.getenv("HOLA_CLOUDFLARE_ZONE_ID", ""),
                "zone_name": os.getenv("HOLA_CLOUDFLARE_ZONE_NAME", ""),
                "account_id": os.getenv("HOLA_CLOUDFLARE_ACCOUNT_ID", ""),
                "api_token": os.getenv("HOLA_CLOUDFLARE_API_TOKEN", ""),
            },
        }
        data = config.model_dump()
        for section, values in env_defaults.items():
            data[section].update({key: value for key, value in values.items() if value})
        if os.getenv("HOLA_ADMIN_PASSWORD"):
            data["admin"]["password_hash"] = hash_password(os.environ["HOLA_ADMIN_PASSWORD"])
        config = HolaConfig.model_validate(data)
        self.write(config)

    def read(self, decrypt: bool = False) -> HolaConfig:
        self.ensure_exists()
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if decrypt:
            raw = self._decrypt_data(raw)
        return HolaConfig.model_validate(raw)

    def write(self, config: HolaConfig, backup: bool = True) -> HolaConfig:
        encrypted = self._encrypt_data(config.model_dump(mode="json"))
        validated = HolaConfig.model_validate(encrypted)
        payload = yaml.safe_dump(
            validated.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=".hola.",
            suffix=".yaml",
            dir=str(self.config_path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if backup and self.config_path.exists():
            self._backup_current_config()
        os.replace(tmp_name, self.config_path)
        return validated

    def _backup_current_config(self) -> None:
        backups_dir = self.app_data / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        backup_path = backups_dir / f"{self.config_path.stem}.{timestamp}{self.config_path.suffix}"
        shutil.copy2(self.config_path, backup_path)

    def update_from_public_payload(self, payload: dict[str, Any]) -> HolaConfig:
        current_encrypted = self.read(decrypt=False)
        merged = self._merge_secret_placeholders(
            incoming=deepcopy(payload),
            current=current_encrypted.model_dump(),
        )
        try:
            config = HolaConfig.model_validate(merged)
        except ValidationError:
            raise
        return self.write(config)

    def _merge_secret_placeholders(
        self,
        incoming: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        for section, key in SECRET_FIELDS:
            value = incoming.get(section, {}).get(key)
            if value == SECRET_PLACEHOLDER:
                incoming[section][key] = current.get(section, {}).get(key, "")
        if incoming.get("admin", {}).get("password_hash") == SECRET_PLACEHOLDER:
            incoming["admin"]["password_hash"] = current.get("admin", {}).get("password_hash", "")
        return incoming

    def _encrypt_data(self, data: dict[str, Any]) -> dict[str, Any]:
        encrypted = deepcopy(data)
        for section, key in SECRET_FIELDS:
            if section in encrypted:
                encrypted[section][key] = self.secret_box.encrypt(encrypted[section].get(key, ""))
        return encrypted

    def _decrypt_data(self, data: dict[str, Any]) -> dict[str, Any]:
        decrypted = deepcopy(data)
        for section, key in SECRET_FIELDS:
            if section in decrypted:
                decrypted[section][key] = self.secret_box.decrypt(decrypted[section].get(key, ""))
        return decrypted
