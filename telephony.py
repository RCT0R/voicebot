"""Telephony helpers that do not depend on LiveKit.

Keeping these functions pure makes the inbound setup plan and number validation
testable without network access.
"""

from __future__ import annotations

import re

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
    """Return the LiveKit SIP hostname that Vobiz should use.

    A LiveKit Cloud project URL and its SIP endpoint are different values.
    For example, the project URL can be ``wss://novi-s0tn6cma.livekit.cloud``
    while the SIP URI is ``sip:34omoz45ad8.sip.livekit.cloud``.

    Never infer the SIP host from the project URL. Require the value shown in
    LiveKit Cloud under Settings > Project > SIP URI.
    """
    if override and override.strip():
        host = override.strip().removeprefix("sip:").removeprefix("sips:")
        return host.rstrip("/")

    raise ValueError(
        "LIVEKIT_SIP_URI is required. Copy the SIP URI from LiveKit Cloud "
        "Settings > Project. The project URL subdomain and the SIP subdomain "
        "can differ. Do not include the sip: prefix."
    )


def transfer_target(number: str | None) -> str | None:
    """Return a validated E.164 transfer target.

    Only phone numbers are accepted. Arbitrary SIP URIs are rejected so a model
    cannot dial an unintended host.
    """
    return normalize_phone(number)
