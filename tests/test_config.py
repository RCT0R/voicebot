from __future__ import annotations

import pytest

from config import ConfigError, Settings


def test_missing_required_values_are_reported_together_without_secrets():
    env = {
        "LIVEKIT_URL": "wss://demo-project.livekit.cloud",
        "GROQ_API_KEY": "gsk_super_secret_value_1234567890",
    }
    with pytest.raises(ConfigError) as exc:
        Settings.from_env(env)

    message = str(exc.value)
    assert "LIVEKIT_API_KEY" in message
    assert "LIVEKIT_API_SECRET" in message
    assert "DEEPGRAM_API_KEY" in message
    assert "gsk_super_secret_value_1234567890" not in message


def test_provider_defaults_are_groq_llm_and_deepgram_audio(env):
    settings = Settings.from_env(env)

    assert settings.llm_provider == "groq"
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.stt_provider == "deepgram"
    assert settings.stt_model == "nova-3"
    assert settings.stt_language == "multi"
    assert settings.tts_provider == "deepgram"
    assert settings.max_call_duration_seconds == 600
    assert settings.llm_max_completion_tokens == 200


def test_invalid_provider_is_rejected(env):
    env["LLM_PROVIDER"] = "unknown"
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        Settings.from_env(env)


def test_groq_key_is_not_required_when_no_groq_provider_is_selected(env):
    env.pop("GROQ_API_KEY")
    env["LLM_PROVIDER"] = "openai"
    env["OPENAI_API_KEY"] = "openai_test_do_not_use"

    settings = Settings.from_env(env)
    assert settings.llm_provider == "openai"


def test_default_greeting_with_business_name_is_explicit(env):
    env["BUSINESS_NAME"] = "Acme Clinic"
    settings = Settings.from_env(env)

    assert "Acme Clinic" in settings.resolved_greeting
    assert "AI receptionist" in settings.resolved_greeting
    assert "How can I help you today?" in settings.resolved_greeting


def test_greeting_without_business_does_not_invent_a_name(env):
    settings = Settings.from_env(env)

    assert "Thank you for calling." in settings.resolved_greeting
    assert settings.business_name == ""
    assert "not configured" in settings.resolved_system_prompt
    assert "en-IN" in settings.resolved_system_prompt


def test_custom_greeting_and_prompt_override_defaults(env):
    env["GREETING"] = "Hello from the front desk."
    env["SYSTEM_PROMPT"] = "Custom instructions."
    settings = Settings.from_env(env)

    assert settings.resolved_greeting == "Hello from the front desk."
    assert settings.resolved_system_prompt == "Custom instructions."


def test_webhook_requires_https_and_a_strong_token(env):
    env["CALL_EVENT_WEBHOOK_URL"] = "http://dashboard.example.com/api/calls"
    env["CALL_EVENT_WEBHOOK_TOKEN"] = "short"
    with pytest.raises(ConfigError) as exc:
        Settings.from_env(env)

    message = str(exc.value)
    assert "CALL_EVENT_WEBHOOK_URL must use https" in message
    assert "CALL_EVENT_WEBHOOK_TOKEN must be at least 16 characters" in message


def test_transfer_requires_a_valid_number(env):
    env["ENABLE_TRANSFER"] = "true"
    with pytest.raises(ConfigError, match="DEFAULT_TRANSFER_NUMBER"):
        Settings.from_env(env)

    env["DEFAULT_TRANSFER_NUMBER"] = "+918071387434"
    settings = Settings.from_env(env)
    assert settings.enable_transfer is True
    assert settings.default_transfer_number == "+918071387434"


def test_invalid_duration_and_agent_name_are_rejected(env):
    env["MAX_CALL_DURATION_SECONDS"] = "5"
    env["AGENT_NAME"] = "bad name"
    with pytest.raises(ConfigError) as exc:
        Settings.from_env(env)

    message = str(exc.value)
    assert "MAX_CALL_DURATION_SECONDS" in message
    assert "AGENT_NAME" in message


def test_allowed_addresses_are_parsed_and_invalid_values_rejected(env):
    env["INBOUND_SIP_ALLOWED_ADDRESSES"] = "192.0.2.0/24, 198.51.100.10"
    settings = Settings.from_env(env)
    assert settings.inbound_sip_allowed_addresses == ("192.0.2.0/24", "198.51.100.10")

    env["INBOUND_SIP_ALLOWED_ADDRESSES"] = "not-an-address"
    with pytest.raises(ConfigError, match="INBOUND_SIP_ALLOWED_ADDRESSES"):
        Settings.from_env(env)


def test_redacted_summary_contains_no_credentials(env):
    settings = Settings.from_env(env)
    summary = str(settings.redacted_summary())

    assert "gsk_test_do_not_use_1234567890" not in summary
    assert "dg_test_do_not_use_1234567890" not in summary
    assert "lk_test_secret_do_not_use" not in summary
    assert "receptionist" in summary


def test_caller_number_and_summary_are_private_by_default(env):
    settings = Settings.from_env(env)
    assert settings.store_caller_number is False
    assert settings.call_summary_enabled is False


def test_summary_follows_the_selected_llm_provider(env):
    env.pop("GROQ_API_KEY")
    env["LLM_PROVIDER"] = "openai"
    env["OPENAI_API_KEY"] = "openai_test_do_not_use"
    env["OPENAI_LLM_MODEL"] = "gpt-4o-mini"

    settings = Settings.from_env(env)
    assert settings.summary_api_key == "openai_test_do_not_use"
    assert settings.summary_base_url is None
    assert settings.resolved_summary_model == "gpt-4o-mini"
