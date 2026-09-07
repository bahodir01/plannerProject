"""Отслеживание использования API провайдеров и расчет расходов."""
import os
import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_LOG_DIR = os.environ.get("LOG_DIR", "logs")
_USAGE_LOG = os.path.join(_LOG_DIR, "api_usage.jsonl")


def _ensure_dir():
    os.makedirs(_LOG_DIR, exist_ok=True)


def log_api_call(provider: str, service: str, tokens: int = 0, duration_ms: int = 0, cost: float = 0.0) -> None:
    """Логирует вызов API.

    Args:
        provider: Название провайдера (assemblyai, gemini, openai)
        service: Тип сервиса (stt, nlp)
        tokens: Количество токенов (для NLP)
        duration_ms: Длительность в миллисекундах
        cost: Стоимость в USD
    """
    _ensure_dir()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "service": service,
        "tokens": tokens,
        "duration_ms": duration_ms,
        "cost": cost,
    }
    try:
        with open(_USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error("Failed to log API call: %s", e)


def get_usage_stats(days: int = 30) -> dict:
    """Получает статистику использования за последние N дней.

    Returns:
        {
            "period_days": 30,
            "timestamp_until": "2026-08-30",
            "total_cost": 0.45,
            "by_provider": {
                "assemblyai": {"calls": 15, "tokens": 0, "cost": 0.10, "duration_hours": 2.5},
                "gemini": {"calls": 42, "tokens": 145000, "cost": 0.00, "duration_hours": 0},
                "openai": {"calls": 3, "tokens": 8500, "cost": 0.35, "duration_hours": 0},
            },
            "by_service": {
                "stt": {"calls": 15, "cost": 0.10},
                "nlp": {"calls": 45, "cost": 0.35},
            }
        }
    """
    _ensure_dir()
    cutoff_date = datetime.now() - timedelta(days=days)
    stats = {
        "period_days": days,
        "timestamp_until": datetime.now().isoformat()[:10],
        "total_cost": 0.0,
        "by_provider": {},
        "by_service": {},
    }

    if not os.path.exists(_USAGE_LOG):
        return stats

    try:
        with open(_USAGE_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    entry_time = datetime.fromisoformat(entry["timestamp"])
                    if entry_time < cutoff_date:
                        continue

                    provider = entry.get("provider", "unknown")
                    service = entry.get("service", "unknown")
                    tokens = entry.get("tokens", 0)
                    duration_ms = entry.get("duration_ms", 0)
                    cost = entry.get("cost", 0.0)

                    # Агрегируем по провайдерам
                    if provider not in stats["by_provider"]:
                        stats["by_provider"][provider] = {
                            "calls": 0, "tokens": 0, "cost": 0.0, "duration_hours": 0.0
                        }
                    stats["by_provider"][provider]["calls"] += 1
                    stats["by_provider"][provider]["tokens"] += tokens
                    stats["by_provider"][provider]["cost"] += cost
                    stats["by_provider"][provider]["duration_hours"] += duration_ms / (1000 * 3600)

                    # Агрегируем по сервисам
                    if service not in stats["by_service"]:
                        stats["by_service"][service] = {"calls": 0, "cost": 0.0}
                    stats["by_service"][service]["calls"] += 1
                    stats["by_service"][service]["cost"] += cost

                    stats["total_cost"] += cost
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.error("Failed to read usage log: %s", e)

    return stats


def get_free_tier_status() -> dict:
    """Получает информацию о free tier провайдеров.

    Returns информацию о лимитах и оставшихся квотах.
    """
    now = datetime.now()

    return {
        "assemblyai": {
            "name": "AssemblyAI",
            "free_tier_limit": "185 часов/месяц",
            "limit_hours": 185,
            "reset_date": (now.replace(day=1) + timedelta(days=32)).replace(day=1).isoformat()[:10],
            "status": "active",
            "docs": "https://www.assemblyai.com"
        },
        "gemini": {
            "name": "Google Gemini",
            "free_tier_limit": "1,000,000 токенов/день",
            "limit_tokens": 1_000_000,
            "reset_time": "00:00 UTC",
            "status": "active",
            "docs": "https://ai.google.dev"
        },
        "openai": {
            "name": "OpenAI",
            "free_tier_limit": "Платный",
            "status": "paid",
            "docs": "https://platform.openai.com"
        }
    }
