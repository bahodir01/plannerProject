"""Структурированное логирование событий (задачи, действия админа).

Пишет в logs/events.jsonl (по строке JSON на событие) — панель читает его
для отображения. Параллельно обычные текстовые логи бота идут в logs/bot.log.
"""
import os
import json
import threading
from datetime import datetime

_LOCK = threading.Lock()
_LOG_DIR = os.environ.get("LOG_DIR", "logs")
_EVENTS_PATH = os.path.join(_LOG_DIR, "events.jsonl")


def _ensure() -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)


def log_event(kind: str, actor: str, message: str, **extra) -> None:
    """Записывает событие. kind: task_created | task_cancelled | admin_login |
    settings_changed | error | access_denied и т.п."""
    _ensure()
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "actor": actor,
        "message": message,
    }
    if extra:
        row["extra"] = extra
    with _LOCK:
        with open(_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_events(limit: int = 200, kind: str | None = None) -> list[dict]:
    """Читает последние события (новые сверху)."""
    _ensure()
    if not os.path.exists(_EVENTS_PATH):
        return []
    with _LOCK:
        with open(_EVENTS_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind and row.get("kind") != kind:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def read_bot_log(lines: int = 200) -> str:
    """Возвращает хвост текстового лога бота."""
    path = os.path.join(_LOG_DIR, "bot.log")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-lines:])
