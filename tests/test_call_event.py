from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from calls import CallRecord, post_call_event


def _record() -> CallRecord:
    return CallRecord(
        call_id="call-1",
        direction="inbound",
        started_at="2026-10-24T10:00:00Z",
        ended_at="2026-10-24T10:00:12.500Z",
        duration_seconds=12.5,
        outcome="completed",
        summary=None,
        error=None,
        caller_number=None,
    )


async def _start_server(handler):
    app = web.Application()
    app.router.add_post("/api/calls", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/api/calls"


@pytest.mark.asyncio
async def test_call_event_sends_bearer_token_and_payload():
    received: dict = {}

    async def handler(request: web.Request) -> web.Response:
        received["authorization"] = request.headers.get("Authorization")
        received["body"] = await request.json()
        return web.json_response({"ok": True}, status=202)

    runner, url = await _start_server(handler)
    try:
        ok = await post_call_event(
            url,
            "dashboard-token-1234567890",
            _record().as_event(),
            timeout=3,
        )
    finally:
        await runner.cleanup()

    assert ok is True
    assert received["authorization"] == "Bearer dashboard-token-1234567890"
    assert received["body"]["call_id"] == "call-1"
    assert received["body"]["outcome"] == "completed"
    assert received["body"]["duration_seconds"] == 12.5


@pytest.mark.asyncio
async def test_call_event_rejection_is_reported_without_raising():
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "no"}, status=500)

    runner, url = await _start_server(handler)
    try:
        ok = await post_call_event(url, "token", _record().as_event(), timeout=3)
    finally:
        await runner.cleanup()

    assert ok is False


@pytest.mark.asyncio
async def test_call_event_timeout_is_reported_without_raising():
    async def handler(request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.json_response({"ok": True})

    runner, url = await _start_server(handler)
    try:
        ok = await post_call_event(url, "token", _record().as_event(), timeout=0.05)
    finally:
        await runner.cleanup()

    assert ok is False


@pytest.mark.asyncio
async def test_unconfigured_webhook_is_a_no_op():
    assert await post_call_event("", "token", _record().as_event()) is True
