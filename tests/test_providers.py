from __future__ import annotations

from config import Settings
from providers import build_llm, build_noise_cancellation, build_stt, build_tts


def _settings(**overrides) -> Settings:
    values = {
        "groq_api_key": "gsk_test_placeholder",
        "deepgram_api_key": "dg_test_placeholder",
        "openai_api_key": "openai_test_placeholder",
    }
    values.update(overrides)
    return Settings(**values)


def test_groq_llm_is_configured_through_the_compatible_endpoint():
    llm = build_llm(_settings())

    assert llm.model == "openai/gpt-oss-120b"
    assert llm.provider == "api.groq.com"


def test_openai_llm_is_available_as_an_alternative():
    llm = build_llm(
        _settings(llm_provider="openai", openai_llm_model="gpt-4o-mini")
    )

    assert llm.model == "gpt-4o-mini"
    assert llm.provider == "api.openai.com"


def test_deepgram_is_the_default_audio_pipeline():
    settings = _settings()

    stt = build_stt(settings)
    tts = build_tts(settings)

    assert stt.model == "nova-3"
    assert tts.model == "aura-2-andromeda-en"
    assert stt.provider == "Deepgram"
    assert tts.provider == "Deepgram"


def test_groq_whisper_and_orpheus_are_selectable():
    settings = _settings(stt_provider="groq", tts_provider="groq")

    stt = build_stt(settings)
    tts = build_tts(settings)

    assert stt.model == "whisper-large-v3-turbo"
    assert tts.model == "canopylabs/orpheus-v1-english"
    assert stt.provider == "api.groq.com"
    assert tts.provider == "api.groq.com"


def test_noise_cancellation_can_be_disabled_without_loading_the_plugin():
    assert build_noise_cancellation(False) is None
