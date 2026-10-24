"""List LiveKit inbound and outbound SIP trunks."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import ListSIPInboundTrunkRequest, ListSIPOutboundTrunkRequest

load_dotenv(".env")
load_dotenv(".env.local", override=True)


async def main() -> None:
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise SystemExit("Error: LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required.")

    lk_api = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        outbound = await lk_api.sip.list_outbound_trunk(ListSIPOutboundTrunkRequest())
        print(f"Outbound trunks: {len(outbound.items)}")
        for trunk in outbound.items:
            print(f"  {trunk.sip_trunk_id}  {trunk.name}  {list(trunk.numbers)}")

        inbound = await lk_api.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
        print(f"Inbound trunks: {len(inbound.items)}")
        for trunk in inbound.items:
            print(f"  {trunk.sip_trunk_id}  {trunk.name}  {list(trunk.numbers)}")
    finally:
        await lk_api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
