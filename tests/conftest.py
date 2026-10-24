from __future__ import annotations

import pytest

BASE_ENV = {
    "LIVEKIT_URL": "wss://demo-project.livekit.cloud",
    "LIVEKIT_API_KEY": "lk_test_key",
    "LIVEKIT_API_SECRET": "lk_test_secret_do_not_use",
    "GROQ_API_KEY": "gsk_test_do_not_use_1234567890",
    "DEEPGRAM_API_KEY": "dg_test_do_not_use_1234567890",
    "VOBIZ_INBOUND_NUMBER": "+918071387434",
}


@pytest.fixture
def env() -> dict[str, str]:
    return dict(BASE_ENV)
