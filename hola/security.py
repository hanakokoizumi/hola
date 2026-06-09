from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    prefix = "enc:v1:"

    def __init__(self, key_path: Path) -> None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            os.chmod(key_path, 0o600)
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        if not value or value.startswith(self.prefix):
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{self.prefix}{token}"

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith(self.prefix):
            return value
        token = value.removeprefix(self.prefix)
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    rounds = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, rounds, salt, digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt.encode("ascii")),
            int(rounds),
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(expected).decode("ascii"), digest)
    except (ValueError, TypeError):
        return False


def make_session_token(username: str, secret: str) -> str:
    raw = f"{username}:{secret}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")
