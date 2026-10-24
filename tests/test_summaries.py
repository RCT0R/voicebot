from __future__ import annotations

from types import SimpleNamespace

import pytest

from calls import summarize_transcript


class FakeCompletions:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


@pytest.mark.asyncio
async def test_summary_uses_private_prompt_and_normalizes_output():
    completions = FakeCompletions("  Caller   asked about hours.  Follow up tomorrow. ")
    client = FakeClient(completions)

    result = await summarize_transcript(
        "Caller: What time do you open?\nAgent: I can help with that.",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        client_factory=lambda **kwargs: client,
    )

    assert result == "Caller asked about hours. Follow up tomorrow."
    assert completions.kwargs is not None
    assert completions.kwargs["model"] == "openai/gpt-oss-120b"
    assert completions.kwargs["max_tokens"] == 120
    system_prompt = completions.kwargs["messages"][0]["content"]
    assert "Do not include names" in system_prompt
    assert "phone numbers" in system_prompt


@pytest.mark.asyncio
async def test_summary_returns_none_for_empty_transcript_without_calling_api():
    called = {"value": False}

    def factory(**kwargs):
        called["value"] = True
        return FakeClient(FakeCompletions("unused"))

    result = await summarize_transcript(
        "   ",
        api_key="test-key",
        base_url=None,
        model="gpt-4o-mini",
        client_factory=factory,
    )

    assert result is None
    assert called["value"] is False


@pytest.mark.asyncio
async def test_summary_returns_none_when_the_provider_fails():
    completions = FakeCompletions(error=RuntimeError("429 rate limited"))
    result = await summarize_transcript(
        "Caller: Hello",
        api_key="test-key",
        base_url=None,
        model="gpt-4o-mini",
        client_factory=lambda **kwargs: FakeClient(completions),
    )

    assert result is None


@pytest.mark.asyncio
async def test_summary_is_bounded_to_500_characters():
    completions = FakeCompletions("x" * 800)
    result = await summarize_transcript(
        "Caller: Hello",
        api_key="test-key",
        base_url=None,
        model="gpt-4o-mini",
        client_factory=lambda **kwargs: FakeClient(completions),
    )

    assert result is not None
    assert len(result) == 500


@pytest.mark.asyncio
async def test_summary_without_api_key_returns_none():
    result = await summarize_transcript(
        "Caller: Hello",
        api_key="",
        base_url=None,
        model="gpt-4o-mini",
        client_factory=lambda **kwargs: FakeClient(FakeCompletions("unused")),
    )
    assert result is None
