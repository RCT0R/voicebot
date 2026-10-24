"""Telephony helpers that do not depend on LiveKit.

Keeping these functions pure makes the inbound setup plan and number validation
testable without network access.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def is_e164(value: str | None) -> bool:
    """Return True only for an E.164 number such as +918071387434."""
    return bool(value and E164_RE.fullmatch(value.strip()))


def normalize_phone(value: str | None) -> str | None:
    """Normalize common phone formatting to E.164, or return None.

    This accepts spaces, hyphens, dots, and parentheses. It does not guess a
    country code: the caller must supply a leading plus sign.
    """
    if not value:
        return None
    cleaned = re.sub(r"[\s().-]", "", value.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned if is_e164(cleaned) else None


def mask_phone(value: str | None) -> str:
    """Mask a phone number for logs while keeping the country code and last four digits."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 7:
        return "*" * len(digits)
    return f"+{digits[:2]}{'*' * max(0, len(digits) - 6)}{digits[-4:]}"


def derive_sip_endpoint(livekit_url: str, override: str | None = None) -> str:
    """Derive the LiveKit SIP hostname that Vobiz should use as its destination.

    LiveKit Cloud projects use ``wss://<subdomain>.livekit.cloud`` and the SIP
    endpoint is ``<subdomain>.sip.livekit.cloud``. Self-hosted deployments must
    set ``LIVEKIT_SIP_URI`` because the hostname cannot be derived reliably.
    """
    if override and override.strip():
        host = override.strip().removeprefix("sip:").removeprefix("sips:")
        return host.rstrip("/")

    parsed = urlparse(livekit_url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("LIVEKIT_URL must contain a hostname")
    if host.startswith("sip."):
        return host
    if host.endswith(".livekit.cloud"):
        subdomain = host.split(".")[0]
        return f"{subdomain}.sip.livekit.cloud"
    raise ValueError(
        "Cannot derive a SIP endpoint from a self-hosted LIVEKIT_URL. "
        "Set LIVEKIT_SIP_URI to the SIP hostname."
    )


def transfer_target(number: str | None) -> str | None:
    """Return a validated E.164 transfer target.

    Only phone numbers are accepted. Arbitrary SIP URIs are rejected so a model
    cannot dial an unintended host.
    """
    return normalize_phone(number)
