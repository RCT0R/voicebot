from __future__ import annotations

from types import SimpleNamespace

import pytest
from livekit.agents.voice.events import CloseReason

from agent import ErrorPolicy, build_tools, dispatch_mode, resolve_outcome
from calls import (
    CallStore,
    CallTracker,
    build_transcript,
    outcome_from_close_reason,
    safe_error,
)
from config import Settings


def test_call_store_persists_a_finished_call(tmp_path):
    store = CallStore(tmp_path / "calls.db")
    try:
        store.start_call("call-1", "inbound", started_at="2026-10-24T10:00:00Z")
        record = store.finish_call(
            "call-1",
            "completed",
            ended_at="2026-10-24T10:05:30Z",
            summary="Caller asked about opening hours.",
        )

        assert record.duration_seconds == 330
        assert record.outcome == "completed"
        assert record.summary == "Caller asked about opening hours."
        recent = store.recent()
        assert len(recent) == 1
        assert recent[0]["call_id"] == "call-1"
    finally:
        store.close()

    reopened = CallStore(tmp_path / "calls.db")
    try:
        assert reopened.recent()[0]["call_id"] == "call-1"
    finally:
        reopened.close()


def test_call_store_rejects_unknown_outcome(tmp_path):
    store = CallStore(tmp_path / "calls.db")
    try:
        store.start_call("call-1", "inbound")
        with pytest.raises(ValueError, match="outcome"):
            store.finish_call("call-1", "maybe")
    finally:
        store.close()


def test_call_store_redacts_errors_and_bounds_summary(tmp_path):
    store = CallStore(tmp_path / "calls.db")
    try:
        store.start_call("call-1", "inbound")
        record = store.finish_call(
            "call-1",
            "failed",
            summary="x" * 2500,
            error="Authorization: Bearer super-secret-token",
        )
        assert len(record.summary) == 2000
        assert "super-secret-token" not in (record.error or "")
        assert "[redacted]" in (record.error or "")
    finally:
        store.close()


def test_caller_number_is_only_stored_when_supplied(tmp_path):
    store = CallStore(tmp_path / "calls.db")
    try:
        store.start_call("call-1", "inbound")
        record = store.finish_call("call-1", "completed")
        assert record.caller_number is None

        store.start_call("call-2", "inbound")
        record = store.finish_call("call-2", "completed", caller_number="+918071387434")
        assert record.caller_number == "+918071387434"
    finally:
        store.close()


def test_tracker_finish_is_idempotent():
    store = CallStore(":memory:")
    try:
        tracker = CallTracker(store, "call-1", "inbound")
        first = tracker.finish("completed")
        second = tracker.finish("failed")

        assert first is not None
        assert second is None
        assert tracker.record is first
        assert len(store.recent()) == 1
    finally:
        store.close()


def test_close_reason_mapping():
    assert outcome_from_close_reason(CloseReason.PARTICIPANT_DISCONNECTED) == "caller_hangup"
    assert outcome_from_close_reason(CloseReason.JOB_SHUTDOWN) == "shutdown"
    assert outcome_from_close_reason(CloseReason.ERROR) == "failed"
    assert outcome_from_close_reason(CloseReason.TASK_COMPLETED) == "completed"
    assert outcome_from_close_reason("participant_disconnected") == "caller_hangup"


def test_timeout_takes_precedence_and_fallback_is_failure():
    assert (
        resolve_outcome(
            timed_out=True,
            fallback=True,
            exception=RuntimeError("boom"),
            close_reason=CloseReason.ERROR,
            shutdown=False,
        )
        == "max_duration"
    )
    assert (
        resolve_outcome(
            timed_out=False,
            fallback=True,
            exception=None,
            close_reason=None,
            shutdown=False,
        )
        == "failed"
    )
    assert (
        resolve_outcome(
            timed_out=False,
            fallback=False,
            exception=None,
            close_reason=CloseReason.PARTICIPANT_DISCONNECTED,
            shutdown=False,
        )
        == "caller_hangup"
    )


def test_dispatch_mode_reads_inbound_and_outbound_metadata():
    inbound_ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"direction":"inbound"}'),
        room=SimpleNamespace(metadata=""),
    )
    outbound_ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"phone_number":"+91 80713 87434"}'),
        room=SimpleNamespace(metadata=""),
    )
    missing_ctx = SimpleNamespace(
        job=SimpleNamespace(metadata=""),
        room=SimpleNamespace(metadata="not json"),
    )
    preconnected_ctx = SimpleNamespace(
        job=SimpleNamespace(
            metadata='{"phone_number":"+918071387434","direction":"outbound","dial":false}'
        ),
        room=SimpleNamespace(metadata=""),
    )

    assert dispatch_mode(inbound_ctx) == ("inbound", None, False)
    assert dispatch_mode(outbound_ctx) == ("outbound", "+918071387434", True)
    assert dispatch_mode(preconnected_ctx) == ("outbound", "+918071387434", False)
    assert dispatch_mode(missing_ctx) == ("inbound", None, False)


def test_error_policy_allows_one_error_then_falls_back():
    policy = ErrorPolicy(threshold=2, window_seconds=15)
    assert policy.record(now=0) == "retry"
    assert policy.record(now=1) == "fallback"
    assert policy.record(now=100) == "retry"


def test_transfer_tool_is_absent_unless_enabled():
    ctx = SimpleNamespace(shutdown=lambda **kwargs: None)
    session = SimpleNamespace(aclose=lambda: None)

    default_tools = build_tools(Settings(), ctx, session)
    transfer_tools = build_tools(
        Settings(enable_transfer=True, default_transfer_number="+918071387434"),
        ctx,
        session,
    )

    assert len(default_tools) == 1
    assert len(transfer_tools) == 2


def test_build_transcript_skips_system_and_maps_roles():
    history = [
        SimpleNamespace(role="system", text_content="internal"),
        SimpleNamespace(role="user", text_content="  I need help  "),
        SimpleNamespace(role="assistant", text_content="How can I help?"),
    ]
    transcript = build_transcript(history)

    assert transcript == "Caller: I need help\nAgent: How can I help?"
    assert "internal" not in transcript


def test_build_transcript_keeps_recent_turns_when_truncated():
    history = [
        SimpleNamespace(role="user", text_content="a" * 50),
        SimpleNamespace(role="assistant", text_content="b" * 50),
    ]
    transcript = build_transcript(history, max_chars=60)

    assert transcript.startswith("[earlier turns truncated]")
    assert transcript.endswith("b" * 50)


def test_safe_error_redacts_and_truncates():
    error = safe_error("Bearer abc123 " + "x" * 1000)
    assert "abc123" not in error
    assert len(error) <= 500
