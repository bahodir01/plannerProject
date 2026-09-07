"""Абстракция для работы с разными AI провайдерами.

Поддерживает:
- Speech-to-Text: AssemblyAI, OpenAI Whisper
- Text Processing: Google Gemini, OpenAI ChatGPT
"""
import logging
from typing import Optional
import config
import api_usage

log = logging.getLogger(__name__)

# ============ SPEECH-TO-TEXT ============


class STTProvider:
    """Базовый класс для провайдеров speech-to-text."""

    def transcribe(self, audio_file: str) -> dict:
        """Транскрибирует аудио в текст.

        Args:
            audio_file: Путь к аудиофайлу

        Returns:
            {"text": "...", "confidence": 0.95, "cost": 0.05, "provider": "assemblyai"}
        """
        raise NotImplementedError


class AssemblyAIProvider(STTProvider):
    """AssemblyAI speech-to-text (бесплатно: 185 часов/месяц)."""

    def transcribe(self, audio_file: str) -> dict:
        """Транскрибирует используя AssemblyAI API."""
        try:
            import assemblyai as aai

            api_key = config.ai_providers_config().get("assemblyai_key")
            if not api_key:
                return {"error": "AssemblyAI API key not configured", "provider": "assemblyai"}

            aai.settings.api_key = api_key
            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(audio_file)

            if transcript.status == aai.TranscriptStatus.error:
                log.error("AssemblyAI error: %s", transcript.error)
                return {"error": transcript.error, "provider": "assemblyai"}

            # Логируем использование
            import os
            duration_sec = os.path.getsize(audio_file) / (16000 * 2)  # примерно
            api_usage.log_api_call("assemblyai", "stt", duration_ms=int(duration_sec * 1000), cost=0.0)

            return {
                "text": transcript.text,
                "confidence": 0.95,  # AssemblyAI не返回confidence
                "cost": 0.0,  # free tier
                "provider": "assemblyai",
            }
        except Exception as e:
            log.error("AssemblyAI transcription failed: %s", e)
            return {"error": str(e), "provider": "assemblyai"}


class WhisperProvider(STTProvider):
    """OpenAI Whisper speech-to-text."""

    def transcribe(self, audio_file: str) -> dict:
        """Транскрибирует используя OpenAI Whisper API."""
        try:
            from openai import OpenAI

            api_key = config.ai_providers_config().get("openai_key")
            if not api_key:
                return {"error": "OpenAI API key not configured", "provider": "whisper"}

            client = OpenAI(api_key=api_key)

            with open(audio_file, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )

            # Логируем использование (стоимость зависит от размера)
            import os
            file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
            cost = file_size_mb * 0.006  # примерно $0.006 за минуту
            api_usage.log_api_call("openai", "stt", cost=cost)

            return {
                "text": transcript.text,
                "confidence": 0.98,
                "cost": cost,
                "provider": "whisper",
            }
        except Exception as e:
            log.error("Whisper transcription failed: %s", e)
            return {"error": str(e), "provider": "whisper"}


# ============ TEXT PROCESSING ============


class NLPProvider:
    """Базовый класс для провайдеров обработки текста."""

    def process(self, text: str, task: str = "classify") -> dict:
        """Обрабатывает текст.

        Args:
            text: Текст для обработки
            task: Тип задачи ("classify", "extract", "generate")

        Returns:
            {"result": "...", "cost": 0.01, "provider": "gemini"}
        """
        raise NotImplementedError


class GeminiProvider(NLPProvider):
    """Google Gemini text processing (бесплатно: 1M токенов/день)."""

    def process(self, text: str, task: str = "classify") -> dict:
        """Обрабатывает текст используя Google Gemini."""
        try:
            import google.generativeai as genai

            api_key = config.ai_providers_config().get("gemini_key")
            if not api_key:
                return {"error": "Gemini API key not configured", "provider": "gemini"}

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-pro')

            prompt = f"""Обработай следующий текст и определи направление задачи.

Текст: {text}

Верни JSON:
{{"direction": "IT|HR|QA|Finance|...", "confidence": 0.95}}"""

            response = model.generate_content(prompt)

            # Логируем использование (Gemini бесплатно до 1M токенов/день)
            # Примерно 1 токен = 4 символа
            tokens_used = len(text) // 4
            api_usage.log_api_call("gemini", "nlp", tokens=tokens_used, cost=0.0)

            return {
                "result": response.text,
                "cost": 0.0,  # free tier
                "provider": "gemini",
            }
        except Exception as e:
            log.error("Gemini processing failed: %s", e)
            return {"error": str(e), "provider": "gemini"}


class OpenAIProvider(NLPProvider):
    """OpenAI ChatGPT text processing."""

    def process(self, text: str, task: str = "classify") -> dict:
        """Обрабатывает текст используя OpenAI ChatGPT."""
        try:
            from openai import OpenAI

            api_key = config.ai_providers_config().get("openai_key")
            if not api_key:
                return {"error": "OpenAI API key not configured", "provider": "openai"}

            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты помощник для классификации задач."},
                    {"role": "user", "content": f"Классифицируй эту задачу: {text}"}
                ],
                temperature=0.7,
            )

            result_text = response.choices[0].message.content

            # Логируем использование
            tokens_used = response.usage.total_tokens
            cost = (response.usage.prompt_tokens * 0.0005 + response.usage.completion_tokens * 0.0015) / 1000
            api_usage.log_api_call("openai", "nlp", tokens=tokens_used, cost=cost)

            return {
                "result": result_text,
                "cost": cost,
                "provider": "openai",
            }
        except Exception as e:
            log.error("OpenAI processing failed: %s", e)
            return {"error": str(e), "provider": "openai"}


# ============ ПРОВАЙДЕРЫ С FALLBACK ============


def get_stt_provider() -> STTProvider:
    """Получает основной провайдер speech-to-text или fallback."""
    cfg = config.ai_providers_config()
    primary = cfg.get("stt_primary", "assemblyai")

    providers = {
        "assemblyai": AssemblyAIProvider,
        "openai": WhisperProvider,
    }

    return providers.get(primary, AssemblyAIProvider)()


def get_stt_fallback_provider() -> Optional[STTProvider]:
    """Получает резервный провайдер speech-to-text."""
    cfg = config.ai_providers_config()
    fallback = cfg.get("stt_fallback")

    if not fallback:
        return None

    providers = {
        "assemblyai": AssemblyAIProvider,
        "openai": WhisperProvider,
    }

    return providers.get(fallback)


def transcribe_with_fallback(audio_file: str) -> dict:
    """Транскрибирует с fallback логикой."""
    primary = get_stt_provider()
    result = primary.transcribe(audio_file)

    # Если основной провайдер упал — пробуем fallback
    if "error" in result:
        log.warning("Primary STT provider failed, trying fallback")
        fallback = get_stt_fallback_provider()
        if fallback:
            result = fallback.transcribe(audio_file)
            if "error" not in result:
                log.info("Fallback STT provider succeeded")

    return result


def get_nlp_provider() -> NLPProvider:
    """Получает основной провайдер NLP."""
    cfg = config.ai_providers_config()
    primary = cfg.get("nlp_primary", "gemini")

    providers = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
    }

    return providers.get(primary, GeminiProvider)()


def get_nlp_fallback_provider() -> Optional[NLPProvider]:
    """Получает резервный провайдер NLP."""
    cfg = config.ai_providers_config()
    fallback = cfg.get("nlp_fallback")

    if not fallback:
        return None

    providers = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
    }

    return providers.get(fallback)


def process_with_fallback(text: str, task: str = "classify") -> dict:
    """Обрабатывает текст с fallback логикой."""
    primary = get_nlp_provider()
    result = primary.process(text, task)

    # Если основной провайдер упал — пробуем fallback
    if "error" in result:
        log.warning("Primary NLP provider failed, trying fallback")
        fallback = get_nlp_fallback_provider()
        if fallback:
            result = fallback.process(text, task)
            if "error" not in result:
                log.info("Fallback NLP provider succeeded")

    return result
