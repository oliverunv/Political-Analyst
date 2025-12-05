"""Shared pytest fixtures to keep smoke tests lightweight and isolated."""

import types

import pytest


@pytest.fixture(autouse=True)
def stub_openai(monkeypatch):
    """Provide a dummy OpenAI client and placeholder API keys.

    The production modules instantiate ``OpenAI`` at import time; this
    stub prevents the tests from requiring real credentials or network
    calls.
    """

    class DummyChatCompletions:
        @staticmethod
        def create(*args, **kwargs):
            message = types.SimpleNamespace(content="")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=DummyChatCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GNEWS_API_KEY", "test-gnews")
    monkeypatch.setattr("openai.OpenAI", DummyClient)

    yield
