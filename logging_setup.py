"""Structured logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"\b(gsk_|sk-|xai-)[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)([?&](?:token|key|secret|password)=)[^&\s]+"),
)

_LOGGER_NAME = "receptionist"
_CONFIGURED = False


def redact_secrets(text: str) -> str:
    """Remove common credential shapes from a string before it is logged."""
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}[redacted]", redacted)
    return redacted


class RedactingFormatter(logging.Formatter):
    """Text formatter that redacts credentials from the final message."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line with stable operational fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        for key in (
            "event",
            "call_id",
            "direction",
            "outcome",
            "duration_seconds",
            "provider",
            "model",
            "error",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = redact_secrets(str(value)) if key == "error" else value
        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def configure_logging(level: str = "INFO", log_format: str = "text") -> None:
    """Configure the application logger once.

    LiveKit configures its own loggers. This function only touches the
    ``receptionist`` logger and its children.
    """
    global _CONFIGURED

    logger = logging.getLogger(_LOGGER_NAME)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.propagate = False

    if _CONFIGURED:
        for handler in list(logger.handlers):
            handler.setLevel(numeric_level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    logger.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str = _LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)
