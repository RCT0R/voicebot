"""Create a LiveKit outbound SIP trunk for Vobiz.

This is only needed for optional outbound calling. Inbound answering does not
use the Vobiz SIP domain or credentials.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo

load_dotenv(".env")
load_dotenv(".env.local", override=True)


async def main() -> None:
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise SystemExit("Error: LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required.")

    sip_address = os.getenv("VOBIZ_SIP_DOMAIN")
    username = os.getenv("VOBIZ_USERNAME")
    password = os.getenv("VOBIZ_PASSWORD")
    number = os.getenv("VOBIZ_OUTBOUND_NUMBER")
    if not (sip_address and username and password):
        raise SystemExit(
            "Error: VOBIZ_SIP_DOMAIN, VOBIZ_USERNAME, and VOBIZ_PASSWORD are required."
        )

    lk_api = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        trunk = await lk_api.sip.create_outbound_trunk(
            CreateSIPOutboundTrunkRequest(
                trunk=SIPOutboundTrunkInfo(
                    name="Vobiz outbound",
                    address=sip_address,
                    auth_username=username,
                    auth_password=password,
                    numbers=[number] if number else [],
                )
            )
        )
        print(f"Created outbound trunk: {trunk.sip_trunk_id}")
    finally:
        await lk_api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
