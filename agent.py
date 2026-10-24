"""Inbound AI phone receptionist built on LiveKit Agents.

The worker registers one dispatch name, ``receptionist`` by default. It answers
inbound SIP calls and also accepts explicit outbound dispatches from the
optional dashboard and ``make_call.py``.

Inbound routing is configured with ``setup_inbound.py``. The agent greets the
caller, runs the STT/LLM/TTS pipeline, and records one call row when the call
ends. A caller who hangs up, an AI pipeline failure, and the maximum call
duration all lead to cleanup instead of a silent room.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv(".env.local", override=True)

from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RoomInputOptions,
    cli,
    llm,
)

import config
from calls import (
    CallStore,
    CallTracker,
    build_transcript,
    outcome_from_close_reason,
    safe_error,
    send_call_event,
    summarize_transcript,
)
from config import ConfigError
from logging_setup import configure_logging, get_logger, redact_secrets
from providers import (
    build_llm,
    build_noise_cancellation,
    build_stt,
    build_tts,
    build_vad,
)
from telephony import is_e164, normalize_phone, transfer_target

logger = get_logger("receptionist.agent")

INBOUND_AGENT_NAME = (os.getenv("AGENT_NAME") or "receptionist").strip() or "receptionist"

SIP_PARTICIPANT_KIND = rtc.ParticipantKind.PARTICIPANT_KIND_SIP


def _sip_caller(ctx: JobContext) -> rtc.RemoteParticipant | None:
    for participant in ctx.room.remote_participants.values():
        if participant.kind == SIP_PARTICIPANT_KIND:
            return participant
    return None


def _caller_number(ctx: JobContext) -> str | None:
    participant = _sip_caller(ctx)
    if participant is None:
        return None
    for key in ("sip.phoneNumber", "sip.trunkPhoneNumber"):
        value = participant.attributes.get(key)
        if value:
            return value
    identity = participant.identity
    return identity.removeprefix("sip_") or None


def _metadata_phone(ctx: JobContext) -> str | None:
    candidates: list[str] = []
    for raw in (ctx.job.metadata, ctx.room.metadata):
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("phone_number"):
            candidates.append(str(data["phone_number"]))
    for candidate in candidates:
        normalized = normalize_phone(candidate)
        if normalized:
            return normalized
    return None


def dispatch_mode(ctx: JobContext) -> tuple[str, str | None, bool]:
    """Return (direction, phone number, should_dial) from room or job metadata."""
    dial = True
    for raw in (ctx.job.metadata, ctx.room.metadata):
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("direction") == "inbound":
            return "inbound", None, False
        if data.get("dial") is False:
            dial = False
    phone_number = _metadata_phone(ctx)
    if phone_number:
        return "outbound", phone_number, dial
    return "inbound", None, False


def resolve_outcome(
    *,
    timed_out: bool,
    fallback: bool,
    exception: BaseException | None,
    close_reason: Any,
    shutdown: bool,
) -> str:
    if timed_out:
        return "max_duration"
    if fallback or exception is not None:
        return "failed"
    if close_reason is not None:
        return outcome_from_close_reason(close_reason)
    if shutdown:
        return "shutdown"
    return "completed"


class ErrorPolicy:
    """Allow one transient error, then speak a fallback and end the call."""

    def __init__(self, threshold: int = 2, window_seconds: float = 15.0) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._times: list[float] = []

    def record(self, now: float | None = None) -> str:
        current = time.monotonic() if now is None else now
        self._times = [value for value in self._times if current - value <= self.window_seconds]
        self._times.append(current)
        return "fallback" if len(self._times) >= self.threshold else "retry"


def build_tools(
    settings: config.Settings,
    ctx: JobContext,
    session: AgentSession,
    spawn: Callable[[Any], None] | None = None,
) -> list[Any]:
    """Build the tool closures for one call.

    Transfers accept E.164 numbers only. Arbitrary SIP URIs are rejected so the
    model cannot dial an unintended host.
    """

    ending = {"value": False}
    run_task = spawn or (lambda coro: asyncio.create_task(coro))

    @llm.function_tool(
        description=(
            "End the phone call after you have said goodbye. Use this only when "
            "the caller is finished or asks to end the call."
        )
    )
    async def end_call() -> str:
        if ending["value"]:
            return "The call is already ending."
        ending["value"] = True

        def close_later() -> Any:
            async def _close() -> None:
                await asyncio.sleep(settings.end_call_grace_seconds)
                with suppress(Exception):
                    await session.aclose()
                ctx.shutdown(reason="agent ended call")

            return _close()

        run_task(close_later())
        return "The call is ending. Say a short goodbye now."

    tools: list[Any] = [end_call]

    if settings.enable_transfer:

        @llm.function_tool(
            description=(
                "Transfer the caller to a human phone number. Use only when the "
                "caller asks for a human and the transfer is appropriate."
            )
        )
        async def transfer_call(destination: str | None = None) -> str:
            target = transfer_target(destination or settings.default_transfer_number)
            if target is None:
                return "I need a valid phone number with a country code to transfer this call."
            participant = _sip_caller(ctx)
            if participant is None:
                return "I could not find the caller's phone connection."
            try:
                await ctx.transfer_sip_participant(participant, transfer_to=target)
            except Exception as exc:
                logger.error(
                    "SIP transfer failed: %s",
                    redact_secrets(str(exc)),
                    extra={"event": "transfer_failed", "error": safe_error(exc)},
                )
                return "The transfer could not be started. Tell the caller the transfer failed."
            logger.info("SIP transfer started", extra={"event": "transfer_started"})
            return "The transfer has started. Tell the caller they are being connected."

        tools.append(transfer_call)

    return tools


class Receptionist(Agent):
    def __init__(self, instructions: str, tools: list[Any]) -> None:
        super().__init__(instructions=instructions, tools=tools)


async def _speak_and_close(
    settings: config.Settings,
    session: AgentSession,
    ctx: JobContext,
    state: dict[str, Any],
    message: str,
    reason: str,
) -> None:
    if state["closing"]:
        return
    state["closing"] = True
    try:
        handle = session.say(message, allow_interruptions=False)
        await asyncio.wait_for(handle.wait_for_playout(), timeout=15)
    except Exception as exc:
        logger.warning(
            "fallback speech failed: %s",
            redact_secrets(str(exc)),
            extra={"event": "fallback_speech_failed"},
        )
    with suppress(Exception):
        await asyncio.wait_for(session.aclose(), timeout=5)
    ctx.shutdown(reason=reason)


async def _max_duration_watchdog(
    settings: config.Settings,
    session: AgentSession,
    ctx: JobContext,
    state: dict[str, Any],
) -> None:
    await asyncio.sleep(settings.max_call_duration_seconds)
    state["timed_out"] = True
    logger.info(
        "maximum call duration reached",
        extra={"event": "max_duration", "call_id": state["call_id"]},
    )
    await _speak_and_close(
        settings,
        session,
        ctx,
        state,
        settings.timeout_message,
        "max call duration",
    )


def _open_store(settings: config.Settings) -> CallStore:
    try:
        return CallStore(settings.database_path)
    except Exception as exc:
        logger.error(
            "call database unavailable; using in-memory storage: %s",
            redact_secrets(str(exc)),
            extra={"event": "database_fallback", "error": safe_error(exc)},
        )
        return CallStore(":memory:")


async def _greet(settings: config.Settings, session: AgentSession) -> None:
    try:
        handle = session.say(settings.resolved_greeting, allow_interruptions=False)
        await asyncio.wait_for(handle.wait_for_playout(), timeout=30)
        logger.info(
            "greeting finished",
            extra={"event": "greeting_finished"},
        )
    except Exception as exc:
        # A caller can hang up while the greeting is playing. Do not mark the
        # call as failed for that expected case.
        logger.info(
            "greeting did not finish: %s",
            redact_secrets(str(exc)),
            extra={"event": "greeting_interrupted"},
        )


async def _run_call(
    ctx: JobContext,
    direction: str,
    *,
    dial_number: str | None = None,
    dial: bool = True,
) -> None:
    try:
        settings = config.get_settings()
    except ConfigError as exc:
        logger.error("configuration error: %s", exc, extra={"event": "config_error"})
        ctx.shutdown(reason="configuration error")
        return

    configure_logging(settings.log_level, settings.log_format)
    logger.info(
        "call started",
        extra={"event": "call_started", "call_id": ctx.job.id, "direction": direction},
    )

    store = _open_store(settings)
    try:
        tracker = CallTracker(store, ctx.job.id, direction)
    except Exception as exc:
        logger.error(
            "could not start call record; using in-memory storage: %s",
            redact_secrets(str(exc)),
            extra={"event": "database_fallback", "error": safe_error(exc)},
        )
        with suppress(Exception):
            store.close()
        store = CallStore(":memory:")
        tracker = CallTracker(store, ctx.job.id, direction)
    state: dict[str, Any] = {
        "call_id": ctx.job.id,
        "closing": False,
        "timed_out": False,
        "fallback": False,
        "shutdown": False,
        "close_reason": None,
        "exception": None,
        "caller_number": None,
    }
    session: AgentSession | None = None
    max_duration_task: asyncio.Task[None] | None = None
    background: set[asyncio.Task[Any]] = set()
    closed = asyncio.Event()

    def spawn(coro: Any) -> None:
        task = asyncio.create_task(coro)
        background.add(task)

        def done(completed: asyncio.Task[Any]) -> None:
            background.discard(completed)
            if not completed.cancelled() and completed.exception() is not None:
                logger.error(
                    "background task failed: %s",
                    redact_secrets(str(completed.exception())),
                    extra={"event": "background_task_failed"},
                )

        task.add_done_callback(done)

    async def on_shutdown(*_args: Any) -> None:
        state["shutdown"] = True
        closed.set()

    ctx.add_shutdown_callback(on_shutdown)

    try:
        await asyncio.wait_for(ctx.connect(), timeout=15)
        logger.info(
            "connected to room",
            extra={
                "event": "room_connected",
                "call_id": ctx.job.id,
                "direction": direction,
            },
        )

        session = AgentSession(
            vad=build_vad(),
            stt=build_stt(settings),
            llm=build_llm(settings),
            tts=build_tts(settings),
        )
        agent = Receptionist(
            settings.resolved_system_prompt,
            build_tools(settings, ctx, session, spawn=spawn),
        )
        error_policy = ErrorPolicy()

        @session.on("close")
        def on_close(event: Any) -> None:
            state["close_reason"] = getattr(event, "reason", None)
            closed.set()

        @session.on("error")
        def on_error(event: Any) -> None:
            error = getattr(event, "error", event)
            logger.error(
                "voice pipeline error: %s",
                redact_secrets(str(error)),
                extra={
                    "event": "session_error",
                    "call_id": ctx.job.id,
                    "error": safe_error(error),
                },
            )
            if error_policy.record() == "fallback":
                state["fallback"] = True
                spawn(
                    _speak_and_close(
                        settings,
                        session,
                        ctx,
                        state,
                        settings.fallback_message,
                        "pipeline failure",
                    )
                )

        @session.on("user_input_transcribed")
        def on_user_input(event: Any) -> None:
            text = getattr(event, "transcript", "") or ""
            logger.info(
                "caller speech transcribed",
                extra={
                    "event": "caller_speech",
                    "call_id": ctx.job.id,
                    "text_length": len(text),
                    "is_final": bool(getattr(event, "is_final", False)),
                },
            )

        @ctx.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            if participant.kind == SIP_PARTICIPANT_KIND:
                state["close_reason"] = "participant_disconnected"
                closed.set()

        await asyncio.wait_for(
            session.start(
                room=ctx.room,
                agent=agent,
                record=False,
                room_input_options=RoomInputOptions(
                    noise_cancellation=build_noise_cancellation(settings.noise_cancellation),
                    close_on_disconnect=True,
                ),
            ),
            timeout=30,
        )
        max_duration_task = asyncio.create_task(
            _max_duration_watchdog(settings, session, ctx, state)
        )
        logger.info(
            "agent session started",
            extra={"event": "session_started", "call_id": ctx.job.id, "direction": direction},
        )

        if direction == "inbound":
            if _sip_caller(ctx) is None:
                try:
                    await asyncio.wait_for(
                        ctx.wait_for_participant(kind=SIP_PARTICIPANT_KIND),
                        timeout=15,
                    )
                except TimeoutError as exc:
                    raise RuntimeError(
                        "no SIP caller joined within 15 seconds"
                    ) from exc
            state["caller_number"] = _caller_number(ctx)
            logger.info(
                "speaking greeting",
                extra={"event": "greeting_started", "call_id": ctx.job.id},
            )
            await _greet(settings, session)
        else:
            # Outbound is retained for the existing dashboard and CLI. The call
            # is placed only after the agent session is ready to speak.
            number = dial_number
            if not number or not is_e164(number):
                raise ValueError("outbound phone number must be E.164, for example +918071387434")
            if dial:
                if not settings.outbound_trunk_id:
                    raise ValueError(
                        "OUTBOUND_TRUNK_ID or VOBIZ_SIP_TRUNK_ID is required for outbound calls"
                    )
                if _sip_caller(ctx) is None:
                    await ctx.api.sip.create_sip_participant(
                        api.CreateSIPParticipantRequest(
                            room_name=ctx.room.name,
                            sip_trunk_id=settings.outbound_trunk_id,
                            sip_call_to=number,
                            participant_identity=f"sip_{uuid.uuid4().hex[:12]}",
                            ringing_timeout=timedelta(seconds=30),
                            max_call_duration=timedelta(
                                seconds=settings.max_call_duration_seconds + 30
                            ),
                            wait_until_answered=True,
                        )
                    )
            elif _sip_caller(ctx) is None:
                # The dashboard created the SIP participant before dispatch.
                # Never dial a second time.
                try:
                    await asyncio.wait_for(
                        ctx.wait_for_participant(kind=SIP_PARTICIPANT_KIND),
                        timeout=30,
                    )
                except TimeoutError as exc:
                    raise RuntimeError(
                        "the pre-created SIP call did not join the room"
                    ) from exc
            state["caller_number"] = _caller_number(ctx) or number
            await _greet(settings, session)

        await closed.wait()

    except asyncio.CancelledError:
        state["shutdown"] = True
        raise
    except Exception as exc:
        state["exception"] = exc
        logger.error(
            "call failed: %s",
            redact_secrets(str(exc)),
            extra={"event": "call_failed", "call_id": ctx.job.id, "error": safe_error(exc)},
        )
        if session is not None:
            await _speak_and_close(
                settings,
                session,
                ctx,
                state,
                settings.fallback_message,
                "call failure",
            )
    finally:
        if max_duration_task is not None:
            max_duration_task.cancel()
            with suppress(asyncio.CancelledError):
                await max_duration_task
        for task in list(background):
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        transcript = ""
        if settings.call_summary_enabled and session is not None:
            transcript = build_transcript(session.history)
        if session is not None:
            with suppress(Exception):
                await asyncio.wait_for(session.aclose(), timeout=5)

        outcome = resolve_outcome(
            timed_out=state["timed_out"],
            fallback=state["fallback"],
            exception=state["exception"],
            close_reason=state["close_reason"],
            shutdown=state["shutdown"],
        )
        try:
            summary: str | None = None
            if transcript:
                summary = await summarize_transcript(
                    transcript,
                    api_key=settings.summary_api_key,
                    base_url=settings.summary_base_url,
                    model=settings.resolved_summary_model,
                    timeout=settings.summary_timeout_seconds,
                )

            caller_number = state["caller_number"] if settings.store_caller_number else None
            if settings.store_caller_number and not caller_number and dial_number:
                caller_number = dial_number
            record = tracker.finish(
                outcome,
                summary=summary,
                error=safe_error(state["exception"]) if state["exception"] else None,
                caller_number=caller_number,
            )
            if record is not None:
                logger.info(
                    "call finished",
                    extra={
                        "event": "call_finished",
                        "call_id": record.call_id,
                        "direction": record.direction,
                        "outcome": record.outcome,
                        "duration_seconds": round(record.duration_seconds, 2),
                    },
                )
                if settings.call_event_webhook_url:
                    await send_call_event(
                        url=settings.call_event_webhook_url,
                        token=settings.call_event_webhook_token,
                        record=record,
                        timeout=settings.call_event_timeout_seconds,
                    )
        except Exception as exc:
            logger.error(
                "failed to persist the call record: %s",
                redact_secrets(str(exc)),
                extra={"event": "call_record_failed", "call_id": ctx.job.id},
            )
        finally:
            with suppress(Exception):
                store.close()
            ctx.shutdown(reason="call finished")


server = AgentServer(num_idle_processes=1)


@server.rtc_session(agent_name=INBOUND_AGENT_NAME)
async def receptionist_session(ctx: JobContext) -> None:
    logger.info(
        "job received",
        extra={
            "event": "job_received",
            "job_id": ctx.job.id,
            "room": ctx.room.name,
            "agent_name": ctx.job.agent_name,
        },
    )
    direction, phone_number, dial = dispatch_mode(ctx)
    await _run_call(ctx, direction, dial_number=phone_number, dial=dial)


if __name__ == "__main__":
    cli.run_app(server)
