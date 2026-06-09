from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator
from pydantic import ConfigDict


SECRET_PLACEHOLDER = "********"


class TargetState(str, Enum):
    unknown = "unknown"
    ok = "ok"
    warning = "warning"
    error = "error"
    syncing = "syncing"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdminConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = "admin"
    password_hash: str = ""


class CloudflareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    tunnel_name: str = ""
    tunnel_id: str = ""
    credentials_file: str = ""
    zone_id: str = ""
    zone_name: str = ""
    account_id: str = ""
    api_token: str = ""
    proxy_enabled: bool = False
    proxy_url: str = ""

    @field_validator("zone_name")
    @classmethod
    def normalize_zone_name(cls, value: str) -> str:
        return value.strip().lower().rstrip(".")

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parsed = HttpUrl(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https", "socks5"}:
            raise ValueError("proxy_url must use http://, https://, or socks5://")
        return str(parsed).rstrip("/")


class AdGuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    url: str = ""
    username: str = ""
    password: str = ""


class CaddyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_url: str = "http://caddy:2019"
    local_ip: str = ""
    acme_email: str = ""
    http01_enabled: bool = True


class ProxyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    hostname: str
    upstream_url: str
    enabled: bool = True
    note: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    @field_validator("hostname")
    @classmethod
    def normalize_hostname(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not value or "/" in value or " " in value:
            raise ValueError("hostname must be a domain name")
        return value

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream(cls, value: str) -> str:
        parsed = HttpUrl(value)
        return str(parsed).rstrip("/")


class TargetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: TargetState = TargetState.unknown
    message: str = "Not synced yet"
    updated_at: str = Field(default_factory=utc_now)


class SyncStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: TargetStatus = Field(default_factory=TargetStatus)
    cloudflare: TargetStatus = Field(default_factory=TargetStatus)
    caddy: TargetStatus = Field(default_factory=TargetStatus)
    adguard: TargetStatus = Field(default_factory=TargetStatus)


class HolaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = "Hola"
    version: str = "0.1.0"
    author: str = "Hanako"
    github: str = "https://github.com/hanakokoizumi/hola"
    homepage: str = "https://hanako.me"
    admin: AdminConfig = Field(default_factory=AdminConfig)
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    adguard: AdGuardConfig = Field(default_factory=AdGuardConfig)
    caddy: CaddyConfig = Field(default_factory=CaddyConfig)
    proxies: list[ProxyRule] = Field(default_factory=list)
    status: SyncStatus = Field(default_factory=SyncStatus)

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        for section, keys in {
            "cloudflare": ["api_token"],
            "adguard": ["password"],
        }.items():
            for key in keys:
                if data[section].get(key):
                    data[section][key] = SECRET_PLACEHOLDER
        if data["admin"].get("password_hash"):
            data["admin"]["password_hash"] = SECRET_PLACEHOLDER
        return data
