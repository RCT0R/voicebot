"""Call records, optional summaries, and the optional Cloudflare call-event webhook.

The local SQLite database is the source of truth during a call. If a webhook URL
is configured, each finished record is also sent to the Cloudflare dashboard.
Webhook failures never change the call outcome and are never retried here; the
dashboard upserts by ``call_id``, so a safe manual retry is possible.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from logging_setup import redact_secrets

logger = logging.getLogger("receptionist.calls")

FINAL_OUTCOMES = (
    "completed",
    "caller_hangup",
    "max_duration",
    "failed",
    "shutdown",
)
IN_PROGRESS = "in_progress"


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit]


def safe_error(exc: BaseException | str | None) -> str | None:
    """Return a short, redacted error string suitable for a call record."""
    if exc is None:
        return None
    text = str(exc)
    return _clean_text(redact_secrets(text), 500)


@dataclass(frozen=True)
class CallRecord:
    call_id: str
    direction: str
    started_at: str
    ended_at: str
    duration_seconds: float
    outcome: str
    summary: str | None = None
    error: str | None = None
    caller_number: str | None = None

    def as_event(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "direction": self.direction,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": round(self.duration_seconds, 3),
            "outcome": self.outcome,
            "summary": self.summary,
            "error": self.error,
            "caller_number": self.caller_number,
        }


def outcome_from_close_reason(reason: Any) -> str:
    """Map a LiveKit CloseReason (or string) to a stable call outcome."""
    raw = getattr(reason, "value", reason)
    key = str(raw or "").strip().lower()
    if key.startswith("closereason."):
        key = key.split(".", 1)[1]
    return {
        "participant_disconnected": "caller_hangup",
        "job_shutdown": "shutdown",
        "error": "failed",
        "user_initiated": "completed",
        "task_completed": "completed",
    }.get(key, "completed")


class CallStore:
    """Small SQLite store. One row per call, no transcript or audio by default."""

    def __init__(self, path: str | Path = "data/calls.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.path,
            timeout=5.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS calls (
                    call_id TEXT PRIMARY KEY,
                    direction TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL,
                    outcome TEXT NOT NULL,
                    summary TEXT,
                    error TEXT,
                    caller_number TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_calls_started_at
                    ON calls(started_at DESC);
                """
            )
            self._conn.commit()

    def start_call(
        self,
        call_id: str,
        direction: str,
        *,
        started_at: str | None = None,
    ) -> None:
        if direction not in {"inbound", "outbound"}:
            raise ValueError("direction must be inbound or outbound")
        timestamp = started_at or isoformat(utc_now())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO calls (call_id, direction, started_at, outcome)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(call_id) DO NOTHING
                """,
                (call_id, direction, timestamp, IN_PROGRESS),
            )
            self._conn.commit()

    def finish_call(
        self,
        call_id: str,
        outcome: str,
        *,
        ended_at: str | None = None,
        duration_seconds: float | None = None,
        summary: str | None = None,
        error: str | None = None,
        caller_number: str | None = None,
        direction: str = "inbound",
    ) -> CallRecord:
        if outcome not in FINAL_OUTCOMES:
            raise ValueError(f"outcome must be one of {', '.join(FINAL_OUTCOMES)}")
        if direction not in {"inbound", "outbound"}:
            raise ValueError("direction must be inbound or outbound")
        ended = ended_at or isoformat(utc_now())
        summary_text = _clean_text(summary, 2000)
        error_text = _clean_text(redact_secrets(error or ""), 500)
        caller_text = _clean_text(caller_number, 32)

        with self._lock:
            row = self._conn.execute(
                "SELECT started_at FROM calls WHERE call_id = ?", (call_id,)
            ).fetchone()
            if row is None:
                started = ended
                self._conn.execute(
                    """
                    INSERT INTO calls (call_id, direction, started_at, ended_at,
                                       duration_seconds, outcome, summary, error, caller_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        direction,
                        started,
                        ended,
                        0.0 if duration_seconds is None else max(0.0, duration_seconds),
                        outcome,
                        summary_text,
                        error_text,
                        caller_text,
                    ),
                )
            else:
                started = row["started_at"]
                if duration_seconds is None:
                    start_dt = _parse_iso(started)
                    end_dt = _parse_iso(ended)
                    if start_dt and end_dt:
                        duration_seconds = max(0.0, (end_dt - start_dt).total_seconds())
                    else:
                        duration_seconds = 0.0
                self._conn.execute(
                    """
                    UPDATE calls
                       SET ended_at = ?, duration_seconds = ?, outcome = ?,
                           summary = ?, error = ?, caller_number = ?
                     WHERE call_id = ?
                    """,
                    (
                        ended,
                        max(0.0, duration_seconds or 0.0),
                        outcome,
                        summary_text,
                        error_text,
                        caller_text,
                        call_id,
                    ),
                )
            self._conn.commit()
            saved = self._conn.execute(
                "SELECT * FROM calls WHERE call_id = ?", (call_id,)
            ).fetchone()
        if saved is None:
            raise RuntimeError("call record was not saved")
        return CallRecord(
            call_id=saved["call_id"],
            direction=saved["direction"],
            started_at=saved["started_at"],
            ended_at=saved["ended_at"],
            duration_seconds=float(saved["duration_seconds"] or 0.0),
            outcome=saved["outcome"],
            summary=saved["summary"],
            error=saved["error"],
            caller_number=saved["caller_number"],
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT call_id, direction, started_at, ended_at, duration_seconds,
                       outcome, summary, error, caller_number
                  FROM calls
                 ORDER BY started_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()["n"]
            today = utc_now().date().isoformat()
            calls_today = self._conn.execute(
                "SELECT COUNT(*) AS n FROM calls WHERE substr(started_at, 1, 10) = ?",
                (today,),
            ).fetchone()["n"]
            last = self._conn.execute(
                "SELECT MAX(started_at) AS value FROM calls"
            ).fetchone()["value"]
        return {"total_calls": total, "calls_today": calls_today, "last_call_at": last}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class CallTracker:
    """One call's lifecycle. ``finish`` is idempotent for safe cleanup paths."""

    def __init__(
        self,
        store: CallStore,
        call_id: str,
        direction: str,
        *,
        started_at: datetime | None = None,
    ) -> None:
        self.store = store
        self.call_id = call_id
        self.direction = direction
        self.started_at = started_at or utc_now()
        self._started_monotonic = time.monotonic()
        self._record: CallRecord | None = None
        self.store.start_call(call_id, direction, started_at=isoformat(self.started_at))

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._started_monotonic)

    @property
    def record(self) -> CallRecord | None:
        return self._record

    def finish(
        self,
        outcome: str,
        *,
        summary: str | None = None,
        error: str | None = None,
        caller_number: str | None = None,
    ) -> CallRecord | None:
        if self._record is not None:
            return None
        self._record = self.store.finish_call(
            self.call_id,
            outcome,
            ended_at=isoformat(utc_now()),
            duration_seconds=self.elapsed_seconds,
            summary=summary,
            error=error,
            caller_number=caller_number,
            direction=self.direction,
        )
        return self._record


def build_transcript(history: Any, max_chars: int = 12000) -> str:
    """Build plain text from a LiveKit ChatContext or an iterable of chat items."""
    try:
        items: Iterable[Any] = history.messages() if callable(
            getattr(history, "messages", None)
        ) else history
    except Exception:
        return ""
    lines: list[str] = []
    for item in items or []:
        role = getattr(item, "role", "")
        if role not in {"user", "assistant"}:
            continue
        content = getattr(item, "text_content", None)
        if callable(content):
            content = content()
        text = " ".join(str(content or "").split())
        if not text:
            continue
        lines.append(f"{'Caller' if role == 'user' else 'Agent'}: {text}")
    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = "[earlier turns truncated]\n" + transcript[-max_chars:]
    return transcript


SUMMARY_PROMPT = (
    "Summarize this phone call in one or two short sentences. State the caller's "
    "intent and any agreed follow-up. Do not include names, phone numbers, email "
    "addresses, account numbers, or other personal data. If the call had no useful "
    "content, reply with 'No actionable content.'"
)


async def summarize_transcript(
    transcript: str,
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    timeout: float = 8.0,
    client_factory: Callable[..., Any] | None = None,
) -> str | None:
    """Summarize a transcript with the configured LLM. Returns None on failure."""
    if not transcript.strip() or not api_key:
        return None
    factory = client_factory
    if factory is None:
        from openai import AsyncOpenAI

        factory = AsyncOpenAI
    try:
        client = factory(api_key=api_key, base_url=base_url)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": transcript[-12000:]},
                ],
                temperature=0.2,
                max_tokens=120,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str):
            return None
        summary = " ".join(content.split())
        return summary[:500] or None
    except Exception as exc:
        logger.warning(
            "call summary failed: %s",
            redact_secrets(str(exc)),
            extra={"event": "summary_failed", "error": safe_error(exc)},
        )
        return None


async def post_call_event(
    url: str,
    token: str,
    payload: Mapping[str, Any],
    *,
    timeout: float = 5.0,
) -> bool:
    """POST one call record to the Cloudflare dashboard. Never raises."""
    if not url:
        return True
    try:
        import aiohttp

        client_timeout = aiohttp.ClientTimeout(total=timeout)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ai-receptionist/1.0",
        }
        async with (
            aiohttp.ClientSession(timeout=client_timeout) as session,
            session.post(url, json=dict(payload), headers=headers) as response,
        ):
            if 200 <= response.status < 300:
                return True
            logger.warning(
                "call event rejected by dashboard",
                extra={"event": "call_event_rejected", "error": f"status={response.status}"},
            )
            return False
    except Exception as exc:
        logger.warning(
            "call event delivery failed: %s",
            redact_secrets(str(exc)),
            extra={"event": "call_event_failed", "error": safe_error(exc)},
        )
        return False


async def send_call_event(
    *,
    url: str,
    token: str,
    record: CallRecord,
    timeout: float = 5.0,
) -> bool:
    return await post_call_event(url, token, record.as_event(), timeout=timeout)
