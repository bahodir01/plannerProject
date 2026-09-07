"""Аутентификация админа: хеш пароля + подписанные cookie-сессии."""
import os
import hmac
import hashlib
import secrets
import base64
import json
import time

import settings_store

# Секрет для подписи сессий (из окружения или генерируется и хранится в data)
_SECRET_PATH = os.path.join(os.environ.get("DATA_DIR", "data"), ".session_secret")


def _get_secret() -> bytes:
    env = os.environ.get("ADMIN_SESSION_SECRET")
    if env:
        return env.encode()
    if os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(_SECRET_PATH), exist_ok=True)
    secret = secrets.token_bytes(32)
    with open(_SECRET_PATH, "wb") as f:
        f.write(secret)
    return secret


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2-хеш пароля в формате salt$hash."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


def ensure_admin_bootstrap() -> None:
    """Создаёт админа при первом запуске из переменных окружения
    ADMIN_USERNAME / ADMIN_PASSWORD, если он ещё не задан."""
    s = settings_store.load()
    if s["admin"].get("password_hash"):
        return
    user = os.environ.get("ADMIN_USERNAME", "admin")
    pwd = os.environ.get("ADMIN_PASSWORD", "admin")
    s["admin"]["username"] = user
    s["admin"]["password_hash"] = hash_password(pwd)
    settings_store.save(s)


def check_login(username: str, password: str) -> bool:
    s = settings_store.load()
    adm = s["admin"]
    if not hmac.compare_digest(username, adm.get("username", "")):
        return False
    return verify_password(password, adm.get("password_hash", ""))


def set_credentials(username: str, password: str) -> None:
    s = settings_store.load()
    s["admin"]["username"] = username
    if password:
        s["admin"]["password_hash"] = hash_password(password)
    settings_store.save(s)


# ---- Подписанные сессионные токены ----
def create_session(username: str, ttl: int = 86400) -> str:
    payload = {"u": username, "exp": int(time.time()) + ttl}
    raw = json.dumps(payload).encode()
    body = base64.urlsafe_b64encode(raw).decode()
    sig = hmac.new(_get_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(token: str) -> str | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_get_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body))
    except Exception:  # noqa: BLE001
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("u")
