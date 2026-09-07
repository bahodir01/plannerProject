"""Доступ к настройкам для бота. Тонкая обёртка над settings_store —
всегда возвращает актуальные значения (бот подхватывает правки из админки)."""
import settings_store


def s() -> dict:
    return settings_store.load()


# --- Telegram ---
def telegram_token() -> str:
    return s()["telegram"]["token"]


def allowed_user_ids() -> set[int]:
    return {int(x) for x in s()["telegram"].get("allowed_user_ids", [])}


# --- OpenAI ---
def openai_key() -> str:
    return s()["openai"]["api_key"]


# --- Google Sheets ---
def google_creds_path() -> str:
    return s()["google"]["creds_path"]


def sheet_name() -> str:
    return s()["google"]["sheet_name"]


# --- Поведение ---
def require_confirmation() -> bool:
    return bool(s()["behavior"].get("require_confirmation", True))


def timezone() -> str:
    return s()["behavior"].get("timezone", "Asia/Tashkent")


def default_status() -> str:
    return s()["behavior"].get("default_status", "In Progress")


# --- Направления ---
def departments() -> list[dict]:
    return s().get("departments", [])


def department_names() -> list[str]:
    return [d["name"] for d in departments()]


def get_department(name: str) -> dict | None:
    key = (name or "").strip().lower()
    for d in departments():
        if d["name"].strip().lower() == key:
            return d
    return None


def resolve_department(text: str) -> str | None:
    """Определяет направление по тексту (алиасы -> имя листа)."""
    src = (text or "").lower()
    for d in departments():
        if any(a in src for a in d.get("aliases", [])):
            return d["name"]
    for d in departments():
        if d["name"].lower() in src:
            return d["name"]
    return None


# --- AI Провайдеры ---
def ai_providers_config() -> dict:
    """Получает конфигурацию AI провайдеров."""
    return s().get("ai_providers", {})
