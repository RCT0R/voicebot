"""Provider construction.

Groq is used through its OpenAI-compatible endpoint. Deepgram is kept for
streaming telephony STT and low-latency TTS because it is already used by the
project and its free credit covers the initial deployment.
"""

from __future__ import annotations

import logging
from typing import Any

from livekit.plugins import deepgram, noise_cancellation, openai, silero

from config import Settings

logger = logging.getLogger("receptionist.providers")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def build_llm(settings: Settings) -> Any:
    if settings.llm_provider == "groq":
        logger.info(
            "using Groq LLM",
            extra={"event": "provider_selected", "provider": "groq", "model": settings.groq_model},
        )
        return openai.LLM(
            base_url=GROQ_BASE_URL,
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=settings.groq_temperature,
            max_completion_tokens=settings.llm_max_completion_tokens,
            max_retries=1,
        )

    logger.info(
        "using OpenAI LLM",
        extra={
            "event": "provider_selected",
            "provider": "openai",
            "model": settings.openai_llm_model,
        },
    )
    return openai.LLM(
        api_key=settings.openai_api_key,
        model=settings.openai_llm_model,
        temperature=settings.groq_temperature,
        max_completion_tokens=settings.llm_max_completion_tokens,
        max_retries=1,
    )


def build_stt(settings: Settings) -> Any:
    if settings.stt_provider == "deepgram":
        logger.info(
            "using Deepgram STT",
            extra={"event": "provider_selected", "provider": "deepgram", "model": settings.stt_model},
        )
        return deepgram.STT(
            model=settings.stt_model,
            language=settings.stt_language,
            api_key=settings.deepgram_api_key,
            interim_results=True,
            punctuate=True,
            smart_format=True,
        )

    groq_language = "" if settings.stt_language.lower() == "multi" else settings.stt_language
    logger.info(
        "using Groq Whisper STT",
        extra={
            "event": "provider_selected",
            "provider": "groq",
            "model": settings.groq_stt_model,
        },
    )
    return openai.STT(
        base_url=GROQ_BASE_URL,
        api_key=settings.groq_api_key,
        model=settings.groq_stt_model,
        language=groq_language,
        use_realtime=False,
    )


def build_tts(settings: Settings) -> Any:
    if settings.tts_provider == "deepgram":
        logger.info(
            "using Deepgram TTS",
            extra={
                "event": "provider_selected",
                "provider": "deepgram",
                "model": settings.deepgram_tts_model,
            },
        )
        return deepgram.TTS(
            model=settings.deepgram_tts_model,
            api_key=settings.deepgram_api_key,
        )

    if settings.tts_provider == "groq":
        logger.info(
            "using Groq Orpheus TTS",
            extra={
                "event": "provider_selected",
                "provider": "groq",
                "model": settings.groq_tts_model,
            },
        )
        return openai.TTS(
            base_url=GROQ_BASE_URL,
            api_key=settings.groq_api_key,
            model=settings.groq_tts_model,
            voice=settings.groq_tts_voice,
            response_format="wav",
        )

    logger.info(
        "using OpenAI TTS",
        extra={
            "event": "provider_selected",
            "provider": "openai",
            "model": settings.openai_tts_model,
        },
    )
    return openai.TTS(
        api_key=settings.openai_api_key,
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
    )


def build_vad() -> Any:
    return silero.VAD.load()


def build_noise_cancellation(enabled: bool) -> Any | None:
    if not enabled:
        return None
    try:
        return noise_cancellation.BVCTelephony()
    except Exception as exc:
        logger.warning(
            "telephony noise cancellation unavailable; continuing without it: %s",
            exc,
            extra={"event": "noise_cancellation_unavailable"},
        )
        return None
