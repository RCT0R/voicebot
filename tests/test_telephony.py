from __future__ import annotations

import pytest

from telephony import (
    derive_sip_endpoint,
    is_e164,
    mask_phone,
    normalize_phone,
    transfer_target,
)


@pytest.mark.parametrize(
    "number",
    ["+918071387434", "+14155550123", "+919999999999"],
)
def test_valid_e164_numbers(number):
    assert is_e164(number) is True


@pytest.mark.parametrize(
    "number",
    ["8071387434", "+0123456789", "+91 80713 87434", "sip:agent@example.com", ""],
)
def test_invalid_e164_numbers(number):
    assert is_e164(number) is False


def test_normalize_phone_accepts_common_formatting():
    assert normalize_phone("+91 80713-87434") == "+918071387434"
    assert normalize_phone("(+91) 80713.87434") == "+918071387434"
    assert normalize_phone("0091 8071387434") == "+918071387434"


def test_normalize_phone_rejects_missing_country_code():
    assert normalize_phone("8071387434") is None


def test_mask_phone_does_not_expose_the_full_number():
    masked = mask_phone("+918071387434")
    assert masked.startswith("+91")
    assert masked.endswith("7434")
    assert "807138" not in masked


def test_derive_livekit_cloud_sip_endpoint():
    assert (
        derive_sip_endpoint("wss://demo-project.livekit.cloud")
        == "demo-project.sip.livekit.cloud"
    )


def test_derive_sip_endpoint_honors_override():
    assert (
        derive_sip_endpoint("wss://demo-project.livekit.cloud", "sip:custom.example.com:5060")
        == "custom.example.com:5060"
    )


def test_derive_sip_endpoint_rejects_unknown_self_hosted_host():
    with pytest.raises(ValueError, match="LIVEKIT_SIP_URI"):
        derive_sip_endpoint("wss://voice.example.com")


def test_transfer_only_accepts_phone_numbers():
    assert transfer_target("+91 80713 87434") == "+918071387434"
    assert transfer_target("sip:attacker@example.com") is None
