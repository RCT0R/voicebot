r"""Read-only diagnostics for the inbound call path.

This script never creates, updates, or deletes LiveKit resources.
It prints trunk, dispatch-rule, and recent-room state without printing secrets.

Run from the project directory on Windows:

    .\.venv\Scripts\python.exe diagnose_inbound.py
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from livekit import api

from config import load_environment
from logging_setup import redact_secrets
from telephony import normalize_phone

REQUIRED_ENV = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "VOBIZ_INBOUND_NUMBER",
)


def _set(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _rule_agents(rule: api.SIPDispatchRuleInfo) -> list[str]:
    try:
        return [agent.agent_name for agent in rule.room_config.agents]
    except Exception:
        return []


def _rule_details(rule: api.SIPDispatchRuleInfo) -> tuple[str, str]:
    try:
        kind = rule.rule.WhichOneof("rule") or "unknown"
    except Exception:
        return "unknown", ""
    if kind == "dispatch_rule_individual":
        return kind, rule.rule.dispatch_rule_individual.room_prefix
    if kind == "dispatch_rule_direct":
        return kind, rule.rule.dispatch_rule_direct.room_name
    if kind == "dispatch_rule_callee":
        return kind, rule.rule.dispatch_rule_callee.room_prefix
    return kind, ""


def _duration_seconds(value: object) -> str:
    try:
        return str(value.seconds)  # type: ignore[attr-defined]
    except Exception:
        return "unset"


async def main() -> int:
    load_environment()

    missing = [name for name in REQUIRED_ENV if not _set(name)]
    if missing:
        print("Missing required environment variables (values not printed):")
        for name in missing:
            print(f"  - {name}")
        print("\nSet these in .env before running diagnostics.")
        return 2

    url = os.environ["LIVEKIT_URL"].strip()
    key = os.environ["LIVEKIT_API_KEY"].strip()
    secret = os.environ["LIVEKIT_API_SECRET"].strip()
    number = normalize_phone(os.getenv("VOBIZ_INBOUND_NUMBER"))
    agent_name = (os.getenv("AGENT_NAME") or "receptionist").strip()
    sip_host = (os.getenv("LIVEKIT_SIP_URI") or "").strip()
    if sip_host:
        sip_host = sip_host.removeprefix("sip:").removeprefix("sips:").rstrip("/")

    print("Inbound diagnostics")
    print(f"  LiveKit project URL: {url}")
    print(f"  Expected SIP host:   {sip_host or 'MISSING (set LIVEKIT_SIP_URI)'}")
    print(f"  Vobiz number:        {number or 'INVALID/MISSING'}")
    print(f"  Agent dispatch name: {agent_name}")
    print("  Secrets:             present, values not printed")
    print()

    if not number:
        print("FAIL: VOBIZ_INBOUND_NUMBER must be a valid E.164 number.")
        return 2

    lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        trunks = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
    except Exception as exc:
        print(f"ERROR: LiveKit API request failed: {redact_secrets(str(exc))}")
        return 1
    finally:
        await lk.aclose()

    trunk_items = list(trunks.items)
    rule_items = list(rules.items)
    room_items = sorted(
        list(rooms.rooms),
        key=lambda room: getattr(room, "creation_time", 0),
        reverse=True,
    )[:20]

    print(f"Inbound trunks: {len(trunk_items)}")
    for trunk in trunk_items:
        auth = "yes" if getattr(trunk, "auth_username", "") else "no"
        print(
            f"  - {trunk.sip_trunk_id} | {trunk.name} | "
            f"numbers={list(trunk.numbers)} | "
            f"allowed_addresses={list(trunk.allowed_addresses)} | "
            f"auth={auth} | max_call_duration={_duration_seconds(trunk.max_call_duration)}s"
        )
    if not trunk_items:
        print("  (none)")

    print(f"\nDispatch rules: {len(rule_items)}")
    for rule in rule_items:
        kind, destination = _rule_details(rule)
        print(
            f"  - {rule.sip_dispatch_rule_id} | {rule.name} | "
            f"trunks={list(rule.trunk_ids)} | "
            f"agents={_rule_agents(rule)} | type={kind} | destination={destination}"
        )
    if not rule_items:
        print("  (none)")

    print(f"\nRecent LiveKit rooms: {len(room_items)}")
    for room in room_items:
        created = datetime.fromtimestamp(room.creation_time, tz=UTC).isoformat()
        print(
            f"  - {room.name} | participants={room.num_participants} | "
            f"created={created}"
        )
    if not room_items:
        print("  (none)")

    matching_trunks = [trunk for trunk in trunk_items if number in list(trunk.numbers)]
    bound_rules = [
        rule
        for rule in rule_items
        if any(trunk.sip_trunk_id in list(rule.trunk_ids) for trunk in matching_trunks)
    ]
    agent_rules = [rule for rule in bound_rules if agent_name in _rule_agents(rule)]

    print("\nChecks")
    print(f"  [{'PASS' if sip_host else 'FAIL'}] LIVEKIT_SIP_URI is configured")
    print(
        f"  [{'PASS' if matching_trunks else 'FAIL'}] "
        f"LiveKit inbound trunk claims {number}"
    )
    if matching_trunks and any(getattr(t, "auth_username", "") for t in matching_trunks):
        print(
            "  [WARN] The inbound trunk requires SIP digest authentication. "
            "Vobiz inbound may not send it. Remove INBOUND_SIP_AUTH_* unless confirmed."
        )
    print(
        f"  [{'PASS' if bound_rules else 'FAIL'}] "
        "A dispatch rule is bound to that trunk"
    )
    print(
        f"  [{'PASS' if agent_rules else 'FAIL'}] "
        f"The dispatch rule targets agent '{agent_name}'"
    )
    print(
        f"  [{'PASS' if room_items else 'UNVERIFIED'}] "
        "A recent LiveKit room exists"
    )

    print("\nInterpretation")
    if not matching_trunks:
        print(
            "  The agent can be registered while LiveKit has no inbound trunk for the "
            "number. The call cannot be matched to a room. Create the trunk and rule."
        )
    elif not agent_rules:
        print(
            "  The number has a trunk, but no dispatch rule targets the agent. Inbound "
            "calls will not start the worker. Fix the dispatch rule."
        )
    elif not room_items:
        print(
            "  LiveKit routing objects exist, but no recent room is visible. The INVITE "
            "may not be reaching LiveKit, or the room may have expired. Check the Vobiz "
            "call detail SIP status and the agent log for job_received."
        )
    else:
        print(
            "  LiveKit routing objects exist. Check the agent log for job_received and "
            "call_started, and check the room's SIP participant."
        )

    print(
        "\nProvider checks that this script cannot perform: Vobiz KYC approval, "
        "trial-vs-active number status, prepaid balance, and whether Vobiz sent the "
        "INVITE. Use the Vobiz call detail and support channel for those."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
