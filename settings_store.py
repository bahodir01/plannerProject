"""Динамическое хранилище настроек — единый источник истины для бота и админки.

Все настройки лежат в data/settings.json. И бот, и админ-панель читают/пишут
через этот модуль. Бот подхватывает изменения без перезапуска: перед каждым
использованием проверяется mtime файла, и при изменении кеш перечитывается.
"""
import os
import json
import threading
import logging
from datetime import datetime

log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_DATA_DIR = os.environ.get("DATA_DIR", "data")
_SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")

_cache: dict | None = None
_cache_mtime: float = 0.0

# Значения по умолчанию при первом запуске
_DEFAULTS = {
    "telegram": {
        "token": "",
        "allowed_user_ids": []          # список int — доступ к боту
    },
    "openai": {
        "api_key": ""
    },
    "google": {
        "creds_path": "google-creds.json",  # путь к JSON-кредам
        "sheet_name": "Planner"
    },
    "behavior": {
        "require_confirmation": True,
        "timezone": "Asia/Tashkent",
        "default_status": "In Progress"
    },
    "departments": [
        {
            "name": "IT",
            "staff_name": "Bakhodir Sayfiddinov",
            "aliases": ["it", "айти", "ит", "информационные технологии"]
        }
    ],
    "ai_providers": {
        "stt_primary": "assemblyai",
        "stt_fallback": "openai",
        "nlp_primary": "gemini",
        "nlp_fallback": "openai",
        "assemblyai_key": "",
        "gemini_key": "",
        "openai_key": ""
    },
    "admin": {
        # логин/хеш пароля задаются при первом запуске из .env, см. admin/auth.py
        "username": "",
        "password_hash": ""
    }
}


def _ensure_file() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    if not os.path.exists(_SETTINGS_PATH):
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_DEFAULTS, f, ensure_ascii=False, indent=2)
        log.info("Created default settings at %s", _SETTINGS_PATH)


def _read_from_disk() -> dict:
    with open(_SETTINGS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # мягкое слияние с дефолтами (чтобы новые ключи не ломали старый файл)
    merged = json.loads(json.dumps(_DEFAULTS))
    _deep_update(merged, data)
    return merged


def _deep_update(base: dict, upd: dict) -> None:
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def load(force: bool = False) -> dict:
    """Возвращает актуальные настройки. Перечитывает файл, если он изменился
    (mtime), поэтому бот видит правки из админки без перезапуска."""
    global _cache, _cache_mtime
    with _LOCK:
        _ensure_file()
        mtime = os.path.getmtime(_SETTINGS_PATH)
        if force or _cache is None or mtime != _cache_mtime:
            _cache = _read_from_disk()
            _cache_mtime = mtime
            log.debug("Settings reloaded (mtime=%s)", mtime)
        return json.loads(json.dumps(_cache))  # копия, чтобы не мутировали кеш


def save(new_settings: dict) -> None:
    """Атомарно сохраняет настройки на диск и сбрасывает кеш."""
    global _cache, _cache_mtime
    with _LOCK:
        _ensure_file()
        tmp = _SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SETTINGS_PATH)
        _cache = _read_from_disk()
        _cache_mtime = os.path.getmtime(_SETTINGS_PATH)
        log.info("Settings saved")


def update_section(section: str, values: dict) -> dict:
    """Обновляет один раздел настроек и сохраняет."""
    with _LOCK:
        s = load()
        if section not in s or not isinstance(s[section], dict):
            s[section] = {}
        _deep_update(s[section], values)
        save(s)
        return s


def set_departments(departments: list[dict]) -> dict:
    with _LOCK:
        s = load()
        s["departments"] = departments
        save(s)
        return s
