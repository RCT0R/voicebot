from __future__ import annotations

import json
import logging

from logging_setup import JsonFormatter, redact_secrets


def test_redact_secrets_removes_bearer_tokens_and_api_keys():
    text = (
        "Authorization: Bearer abc123.def456 "
        "key gsk_abcdefghijklmnop "
        "url https://example.com?token=super-secret"
    )
    redacted = redact_secrets(text)

    assert "abc123.def456" not in redacted
    assert "gsk_abcdefghijklmnop" not in redacted
    assert "super-secret" not in redacted


def test_json_formatter_includes_operational_fields_without_credentials():
    record = logging.LogRecord(
        name="receptionist.agent",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="failed with key gsk_abcdefghijklmnop",
        args=(),
        exc_info=None,
    )
    record.event = "call_failed"
    record.call_id = "call-1"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["event"] == "call_failed"
    assert payload["call_id"] == "call-1"
    assert "gsk_abcdefghijklmnop" not in payload["message"]
