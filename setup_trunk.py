"""Update the credentials on an existing Vobiz outbound trunk."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")
load_dotenv(".env.local", override=True)


async def main() -> None:
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    trunk_id = os.getenv("OUTBOUND_TRUNK_ID") or os.getenv("VOBIZ_SIP_TRUNK_ID")
    if not (url and key and secret):
        raise SystemExit("Error: LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required.")
    if not trunk_id:
        raise SystemExit("Error: OUTBOUND_TRUNK_ID or VOBIZ_SIP_TRUNK_ID is required.")

    lk_api = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        await lk_api.sip.update_outbound_trunk_fields(
            trunk_id,
            address=os.getenv("VOBIZ_SIP_DOMAIN"),
            auth_username=os.getenv("VOBIZ_USERNAME"),
            auth_password=os.getenv("VOBIZ_PASSWORD"),
            numbers=[os.getenv("VOBIZ_OUTBOUND_NUMBER")]
            if os.getenv("VOBIZ_OUTBOUND_NUMBER")
            else [],
        )
        print(f"Updated outbound trunk: {trunk_id}")
    finally:
        await lk_api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
