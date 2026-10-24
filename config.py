"""Central configuration for the inbound AI receptionist.

All values come from environment variables. ``Settings.from_env`` validates the
whole configuration and reports every missing or invalid value at once without
including secret values in the error message.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from dotenv import load_dotenv

from telephony import normalize_phone

VALID_LLM_PROVIDERS = ("groq", "openai")
VALID_STT_PROVIDERS = ("deepgram", "groq")
VALID_TTS_PROVIDERS = ("deepgram", "groq", "openai")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
VALID_LOG_FORMATS = ("text", "json")
AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ROOM_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")

DEFAULT_SYSTEM_PROMPT = """You are {display_name}, an AI phone receptionist answering an inbound telephone call.

{identity}

How to speak:
- Start in {language} unless the caller uses another language you can handle confidently.
- Speak naturally and warmly. Keep every answer to one or two short sentences.
- Ask one clarifying question at a time.
- If the caller speaks a language you can handle confidently, reply in that language. Otherwise ask them to continue in English.
- Never read out lists, formatting, or markdown. You are on a phone call.

What you know:
- You only know what the caller tells you and the information in these instructions.
- Never invent a business name, address, opening hours, price, service, booking, or policy.
- If you do not know something, say so plainly. Do not guess.

What you must not do:
- Never claim that you booked, changed, cancelled, transferred, messaged, or charged anything unless a tool confirmed it.
- Do not ask for payment card numbers, passwords, one-time codes, or other sensitive credentials.
- Do not give legal, medical, or financial advice.

Ending the call:
- If the caller says goodbye or the conversation is clearly finished, say a short goodbye and call end_call.
{transfer_rule}"""


def _read(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    return value.strip() if value else ""


def _parse_bool(env: Mapping[str, str], name: str, default: bool, errors: list[str]) -> bool:
    raw = _read(env, name)
    if not raw:
        return default
    value = raw.lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    errors.append(f"{name} must be true or false")
    return default


def _parse_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int:
    raw = _read(env, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be an integer")
        return default
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return default
    return value


def _parse_float(
    env: Mapping[str, str],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
    errors: list[str],
) -> float:
    raw = _read(env, name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{name} must be a number")
        return default
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return default
    return value


def _parse_allowed_addresses(env: Mapping[str, str], errors: list[str]) -> tuple[str, ...]:
    raw = _read(env, "INBOUND_SIP_ALLOWED_ADDRESSES")
    if not raw:
        return ()
    result: list[str] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            errors.append(
                "INBOUND_SIP_ALLOWED_ADDRESSES must be a comma-separated list of IP addresses or CIDR ranges"
            )
            return ()
        result.append(candidate)
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True)
class Settings:
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_uri: str = ""

    groq_api_key: str = ""
    openai_api_key: str = ""
    deepgram_api_key: str = ""

    llm_provider: str = "groq"
    groq_model: str = "openai/gpt-oss-120b"
    groq_temperature: float = 0.4
    llm_max_completion_tokens: int = 200
    openai_llm_model: str = "gpt-4o-mini"

    stt_provider: str = "deepgram"
    stt_model: str = "nova-3"
    stt_language: str = "multi"
    groq_stt_model: str = "whisper-large-v3-turbo"

    tts_provider: str = "deepgram"
    deepgram_tts_model: str = "aura-2-andromeda-en"
    groq_tts_model: str = "canopylabs/orpheus-v1-english"
    groq_tts_voice: str = "troy"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"

    agent_name: str = "receptionist"
    business_name: str = ""
    agent_display_name: str = "AI receptionist"
    greeting: str = ""
    system_prompt: str = ""
    language: str = "en-IN"

    max_call_duration_seconds: int = 600
    fallback_message: str = (
        "Sorry, I'm having trouble right now. Please call back in a moment."
    )
    timeout_message: str = (
        "This call has reached the maximum time limit. Thank you for calling. Goodbye."
    )
    end_call_grace_seconds: int = 6

    enable_transfer: bool = False
    default_transfer_number: str = ""
    vobiz_sip_domain: str = ""
    vobiz_inbound_number: str = ""
    inbound_sip_allowed_addresses: tuple[str, ...] = ()
    inbound_sip_auth_username: str = ""
    inbound_sip_auth_password: str = ""
    room_prefix: str = "call-"

    outbound_trunk_id: str = ""
    vobiz_outbound_number: str = ""

    call_summary_enabled: bool = False
    summary_model: str = ""
    summary_timeout_seconds: int = 8
    store_caller_number: bool = False

    database_path: str = "data/calls.db"
    call_event_webhook_url: str = ""
    call_event_webhook_token: str = ""
    call_event_timeout_seconds: int = 5

    noise_cancellation: bool = True
    log_level: str = "INFO"
    log_format: str = "text"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build and validate settings from a mapping such as os.environ."""
        env = env if env is not None else os.environ
        errors: list[str] = []
        missing: list[str] = []

        def required(name: str) -> str:
            value = _read(env, name)
            if not value:
                missing.append(name)
            return value

        livekit_url = required("LIVEKIT_URL")
        livekit_api_key = required("LIVEKIT_API_KEY")
        livekit_api_secret = required("LIVEKIT_API_SECRET")

        llm_provider = (_read(env, "LLM_PROVIDER") or "groq").lower()
        stt_provider = (_read(env, "STT_PROVIDER") or "deepgram").lower()
        tts_provider = (_read(env, "TTS_PROVIDER") or "deepgram").lower()

        if llm_provider not in VALID_LLM_PROVIDERS:
            errors.append(f"LLM_PROVIDER must be one of {', '.join(VALID_LLM_PROVIDERS)}")
        if stt_provider not in VALID_STT_PROVIDERS:
            errors.append(f"STT_PROVIDER must be one of {', '.join(VALID_STT_PROVIDERS)}")
        if tts_provider not in VALID_TTS_PROVIDERS:
            errors.append(f"TTS_PROVIDER must be one of {', '.join(VALID_TTS_PROVIDERS)}")

        groq_api_key = required("GROQ_API_KEY") if (
            llm_provider == "groq" or stt_provider == "groq" or tts_provider == "groq"
        ) else _read(env, "GROQ_API_KEY")
        deepgram_api_key = required("DEEPGRAM_API_KEY") if (
            stt_provider == "deepgram" or tts_provider == "deepgram"
        ) else _read(env, "DEEPGRAM_API_KEY")
        openai_api_key = required("OPENAI_API_KEY") if (
            llm_provider == "openai" or tts_provider == "openai"
        ) else _read(env, "OPENAI_API_KEY")

        agent_name = (_read(env, "AGENT_NAME") or "receptionist").strip()
        if not AGENT_NAME_RE.fullmatch(agent_name):
            errors.append("AGENT_NAME must contain only letters, numbers, hyphens, and underscores")

        room_prefix = (_read(env, "ROOM_PREFIX") or "call-").strip()
        if not ROOM_PREFIX_RE.fullmatch(room_prefix):
            errors.append("ROOM_PREFIX must contain only letters, numbers, hyphens, and underscores")

        business_name = _read(env, "BUSINESS_NAME")
        if len(business_name) > 120:
            errors.append("BUSINESS_NAME must be 120 characters or fewer")

        agent_display_name = _read(env, "AGENT_DISPLAY_NAME") or "AI receptionist"
        if len(agent_display_name) > 80:
            errors.append("AGENT_DISPLAY_NAME must be 80 characters or fewer")

        greeting = _read(env, "GREETING")
        if len(greeting) > 600:
            errors.append("GREETING must be 600 characters or fewer")

        system_prompt = _read(env, "SYSTEM_PROMPT")
        if len(system_prompt) > 12000:
            errors.append("SYSTEM_PROMPT must be 12000 characters or fewer")

        max_call_duration_seconds = _parse_int(
            env, "MAX_CALL_DURATION_SECONDS", 600, 30, 3600, errors
        )
        end_call_grace_seconds = _parse_int(env, "END_CALL_GRACE_SECONDS", 6, 1, 15, errors)
        summary_timeout_seconds = _parse_int(
            env, "CALL_SUMMARY_TIMEOUT_SECONDS", 8, 2, 30, errors
        )
        call_event_timeout_seconds = _parse_int(
            env, "CALL_EVENT_TIMEOUT_SECONDS", 5, 1, 30, errors
        )
        groq_temperature = _parse_float(env, "GROQ_TEMPERATURE", 0.4, 0.0, 1.0, errors)
        llm_max_completion_tokens = _parse_int(
            env, "LLM_MAX_COMPLETION_TOKENS", 200, 50, 2000, errors
        )

        enable_transfer = _parse_bool(env, "ENABLE_TRANSFER", False, errors)
        default_transfer_number = normalize_phone(_read(env, "DEFAULT_TRANSFER_NUMBER")) or ""
        if enable_transfer and not default_transfer_number:
            errors.append(
                "DEFAULT_TRANSFER_NUMBER must be a valid E.164 number when ENABLE_TRANSFER is true"
            )

        vobiz_inbound_number = normalize_phone(_read(env, "VOBIZ_INBOUND_NUMBER")) or ""
        if _read(env, "VOBIZ_INBOUND_NUMBER") and not vobiz_inbound_number:
            errors.append("VOBIZ_INBOUND_NUMBER must be a valid E.164 number")

        allowed_addresses = _parse_allowed_addresses(env, errors)

        inbound_sip_auth_username = _read(env, "INBOUND_SIP_AUTH_USERNAME")
        inbound_sip_auth_password = _read(env, "INBOUND_SIP_AUTH_PASSWORD")
        if bool(inbound_sip_auth_username) != bool(inbound_sip_auth_password):
            errors.append(
                "INBOUND_SIP_AUTH_USERNAME and INBOUND_SIP_AUTH_PASSWORD must be set together"
            )

        call_summary_enabled = _parse_bool(env, "CALL_SUMMARY_ENABLED", False, errors)
        store_caller_number = _parse_bool(env, "STORE_CALLER_NUMBER", False, errors)
        noise_cancellation = _parse_bool(env, "NOISE_CANCELLATION", True, errors)

        log_level = (_read(env, "LOG_LEVEL") or "INFO").upper()
        if log_level not in VALID_LOG_LEVELS:
            errors.append(f"LOG_LEVEL must be one of {', '.join(VALID_LOG_LEVELS)}")
            log_level = "INFO"

        log_format = (_read(env, "LOG_FORMAT") or "text").lower()
        if log_format not in VALID_LOG_FORMATS:
            errors.append(f"LOG_FORMAT must be one of {', '.join(VALID_LOG_FORMATS)}")
            log_format = "text"

        webhook_url = _read(env, "CALL_EVENT_WEBHOOK_URL")
        webhook_token = _read(env, "CALL_EVENT_WEBHOOK_TOKEN")
        if webhook_url:
            parsed = urlparse(webhook_url)
            is_local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
                errors.append("CALL_EVENT_WEBHOOK_URL must use https")
            if len(webhook_token) < 16:
                errors.append(
                    "CALL_EVENT_WEBHOOK_TOKEN must be at least 16 characters when CALL_EVENT_WEBHOOK_URL is set"
                )

        if livekit_url:
            parsed_url = urlparse(livekit_url)
            if parsed_url.scheme not in {"wss", "ws"} or not parsed_url.hostname:
                errors.append("LIVEKIT_URL must start with wss:// or ws://")
            livekit_url = livekit_url.rstrip("/")

        database_path = _read(env, "DATABASE_PATH") or "data/calls.db"
        if database_path.strip() == "":
            errors.append("DATABASE_PATH must not be empty")

        if missing or errors:
            parts: list[str] = []
            if missing:
                parts.append(
                    "missing required environment variables: " + ", ".join(dict.fromkeys(missing))
                )
            parts.extend(errors)
            raise ConfigError("Invalid configuration: " + "; ".join(parts))

        return cls(
            livekit_url=livekit_url,
            livekit_api_key=livekit_api_key,
            livekit_api_secret=livekit_api_secret,
            livekit_sip_uri=_read(env, "LIVEKIT_SIP_URI"),
            groq_api_key=groq_api_key,
            openai_api_key=openai_api_key,
            deepgram_api_key=deepgram_api_key,
            llm_provider=llm_provider,
            groq_model=_read(env, "GROQ_MODEL") or "openai/gpt-oss-120b",
            groq_temperature=groq_temperature,
            llm_max_completion_tokens=llm_max_completion_tokens,
            openai_llm_model=_read(env, "OPENAI_LLM_MODEL") or "gpt-4o-mini",
            stt_provider=stt_provider,
            stt_model=_read(env, "STT_MODEL") or "nova-3",
            stt_language=_read(env, "STT_LANGUAGE") or "multi",
            groq_stt_model=_read(env, "GROQ_STT_MODEL") or "whisper-large-v3-turbo",
            tts_provider=tts_provider,
            deepgram_tts_model=_read(env, "DEEPGRAM_TTS_MODEL") or "aura-2-andromeda-en",
            groq_tts_model=_read(env, "GROQ_TTS_MODEL") or "canopylabs/orpheus-v1-english",
            groq_tts_voice=_read(env, "GROQ_TTS_VOICE") or "troy",
            openai_tts_model=_read(env, "OPENAI_TTS_MODEL") or "tts-1",
            openai_tts_voice=_read(env, "OPENAI_TTS_VOICE") or "alloy",
            agent_name=agent_name,
            business_name=business_name,
            agent_display_name=agent_display_name,
            greeting=greeting,
            system_prompt=system_prompt,
            language=_read(env, "AGENT_LANGUAGE") or "en-IN",
            max_call_duration_seconds=max_call_duration_seconds,
            end_call_grace_seconds=end_call_grace_seconds,
            enable_transfer=enable_transfer,
            default_transfer_number=default_transfer_number,
            vobiz_sip_domain=_read(env, "VOBIZ_SIP_DOMAIN"),
            vobiz_inbound_number=vobiz_inbound_number,
            inbound_sip_allowed_addresses=allowed_addresses,
            inbound_sip_auth_username=inbound_sip_auth_username,
            inbound_sip_auth_password=inbound_sip_auth_password,
            room_prefix=room_prefix,
            outbound_trunk_id=(
                _read(env, "OUTBOUND_TRUNK_ID") or _read(env, "VOBIZ_SIP_TRUNK_ID")
            ),
            vobiz_outbound_number=_read(env, "VOBIZ_OUTBOUND_NUMBER"),
            call_summary_enabled=call_summary_enabled,
            summary_model=_read(env, "CALL_SUMMARY_MODEL"),
            summary_timeout_seconds=summary_timeout_seconds,
            store_caller_number=store_caller_number,
            database_path=database_path,
            call_event_webhook_url=webhook_url,
            call_event_webhook_token=webhook_token,
            call_event_timeout_seconds=call_event_timeout_seconds,
            noise_cancellation=noise_cancellation,
            log_level=log_level,
            log_format=log_format,
        )

    @property
    def resolved_greeting(self) -> str:
        if self.greeting:
            return self.greeting
        if self.agent_display_name == "AI receptionist":
            identity = "the AI receptionist"
        else:
            identity = self.agent_display_name
        if self.business_name:
            return (
                f"Thank you for calling {self.business_name}. "
                f"This is {identity}. How can I help you today?"
            )
        return f"Thank you for calling. This is {identity}. How can I help you today?"

    @property
    def resolved_system_prompt(self) -> str:
        if self.system_prompt:
            return self.system_prompt
        if self.business_name:
            identity = f"You work for {self.business_name}."
        else:
            identity = (
                "The business name is not configured. Do not invent a business name or claim "
                "to represent a named organisation."
            )
        if self.enable_transfer:
            transfer_rule = (
                "- If the caller asks for a human and a transfer is appropriate, use transfer_call."
            )
        else:
            transfer_rule = (
                "- If the caller asks for a human, say you cannot transfer the call and suggest "
                "they contact the business directly."
            )
        return DEFAULT_SYSTEM_PROMPT.format(
            display_name=self.agent_display_name,
            identity=identity,
            language=self.language,
            transfer_rule=transfer_rule,
        )

    @property
    def summary_api_key(self) -> str:
        if self.llm_provider == "groq":
            return self.groq_api_key
        return self.openai_api_key

    @property
    def summary_base_url(self) -> str | None:
        if self.llm_provider == "groq":
            return "https://api.groq.com/openai/v1"
        return None

    @property
    def resolved_summary_model(self) -> str:
        if self.summary_model:
            return self.summary_model
        return self.groq_model if self.llm_provider == "groq" else self.openai_llm_model

    def redacted_summary(self) -> dict[str, object]:
        """Return non-secret configuration for logs and status output."""
        return {
            "agent_name": self.agent_name,
            "llm_provider": self.llm_provider,
            "groq_model": self.groq_model if self.llm_provider == "groq" else None,
            "stt_provider": self.stt_provider,
            "stt_model": self.stt_model if self.stt_provider == "deepgram" else self.groq_stt_model,
            "tts_provider": self.tts_provider,
            "tts_model": (
                self.deepgram_tts_model
                if self.tts_provider == "deepgram"
                else self.groq_tts_model
                if self.tts_provider == "groq"
                else self.openai_tts_model
            ),
            "max_call_duration_seconds": self.max_call_duration_seconds,
            "call_summary_enabled": self.call_summary_enabled,
            "store_caller_number": self.store_caller_number,
            "transfer_enabled": self.enable_transfer,
            "call_events_configured": bool(self.call_event_webhook_url),
            "database_path": self.database_path,
        }


class ConfigError(RuntimeError):
    """Raised when the environment is missing or invalid."""


def load_environment() -> None:
    """Load .env, then let .env.local override it for local development."""
    load_dotenv(".env")
    load_dotenv(".env.local", override=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_environment()
    return Settings.from_env()
