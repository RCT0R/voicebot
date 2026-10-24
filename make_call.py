"""Dispatch an optional outbound call through the receptionist worker.

Outbound calling is retained for the dashboard and for manual testing. The
agent places the call only after it joins the room, using the LiveKit outbound
trunk configured in OUTBOUND_TRUNK_ID or VOBIZ_SIP_TRUNK_ID.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

from dotenv import load_dotenv
from livekit import api

from telephony import normalize_phone

load_dotenv(".env")
load_dotenv(".env.local", override=True)


async def dispatch_outbound(number: str, *, dry_run: bool = False) -> None:
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and api_key and api_secret):
        raise SystemExit(
            "Error: LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required."
        )

    agent_name = (os.getenv("AGENT_NAME") or "receptionist").strip()
    room_name = f"outbound-{uuid.uuid4().hex[:12]}"
    metadata = json.dumps({"phone_number": number, "direction": "outbound", "dial": True})

    print(f"Room: {room_name}")
    print(f"Agent: {agent_name}")
    print(f"Number: {number}")
    if dry_run:
        print("Dry run: no dispatch was created.")
        return

    lk_api = api.LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)
    try:
        dispatch = await lk_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=room_name,
                metadata=metadata,
            )
        )
        print(f"Dispatch created: {dispatch.id}")
        print("The agent will dial the number after it joins the room.")
        print("Watch the agent logs for call_started and call_finished.")
    finally:
        await lk_api.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch an optional outbound call.")
    parser.add_argument("--to", required=True, help="Destination in E.164 form, for example +918071387434")
    parser.add_argument("--dry-run", action="store_true", help="Print the dispatch details only")
    args = parser.parse_args()

    number = normalize_phone(args.to)
    if number is None:
        raise SystemExit("Error: phone number must be E.164, for example +918071387434")

    asyncio.run(dispatch_outbound(number, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
