"""Распознавание речи (многоязычное) и парсинг задачи. Настройки — динамические."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import ai_providers

log = logging.getLogger(__name__)


def transcribe(file_path: str) -> str:
    """Транскрибирует аудиофайл используя настроенные провайдеры с fallback."""
    result = ai_providers.transcribe_with_fallback(file_path)

    if "error" in result:
        log.error("Transcription failed: %s", result["error"])
        raise RuntimeError(f"Transcription failed: {result['error']}")

    text = (result.get("text") or "").strip()
    log.info("Transcribed (%s): %s", result.get("provider"), text)
    return text


def detect_lang(text: str) -> str:
    cyr = sum("а" <= c.lower() <= "я" for c in text)
    lat = sum("a" <= c.lower() <= "z" for c in text)
    return "ru" if cyr > lat else "uz_en"


def parse_task(text: str) -> dict:
    """Парсит задачу используя настроенные NLP провайдеры с fallback."""
    tz = config.timezone()
    today = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    depts = ", ".join(config.department_names())

    # Используем Gemini как основной провайдер, OpenAI как fallback
    nlp_text = (
        "Ты извлекаешь задачу из сообщения главного менеджера для журнала Planner. "
        "Сообщение может быть на английском, узбекском или в смеси языков. "
        f"Сегодня {today}, таймзона {tz}. "
        "Относительные сроки (tomorrow, ertaga, завтра, keyingi hafta, через 2 дня) "
        "конвертируй в конкретную дату в формате DD.MM.YYYY. "
        "Если срок не указан или задача регулярная — верни 'Regular'. "
        f"Направление (department) выбирай ТОЛЬКО из списка: {depts}. "
        "Если направление явно не названо — верни null. "
        "Верни ТОЛЬКО JSON без пояснений:\n"
        '{"task": "текст задачи (Task/Activity)", '
        '"deadline": "DD.MM.YYYY или Regular", '
        '"comment": "доп. комментарий или пустая строка", '
        '"department": "одно из направлений или null"}'
        f"\n\nСообщение: {text}"
    )

    # Пробуем основной провайдер
    result = ai_providers.process_with_fallback(nlp_text, task="parse")

    if "error" in result:
        log.error("Parse task failed: %s", result["error"])
        raise RuntimeError(f"Parse task failed: {result['error']}")

    try:
        data = json.loads(result.get("result", "{}"))
    except json.JSONDecodeError:
        log.error("Failed to parse JSON response: %s", result)
        raise RuntimeError("Failed to parse JSON response from AI provider")

    log.info("Parsed task (%s): %s", result.get("provider"), data)
    return data
