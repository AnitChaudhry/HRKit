"""Tests for provider HTTP wiring in hrkit.ai."""

from __future__ import annotations

import json
import sqlite3

import pytest

from hrkit import ai, branding


@pytest.fixture
def memconn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    branding.set_settings(conn, {
        "ai_provider": "upfyn",
        "ai_api_key": "upfyn-test-key",
        "ai_model": "gpt-4o-mini",
    })
    yield conn
    conn.close()


class _FakeResponse:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode("utf-8")

    def read(self, *_args, **_kwargs):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_list_models_sends_browser_safe_user_agent(memconn, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["timeout"] = timeout
        return _FakeResponse({"data": [
            {"id": "upfynai-mini-v3", "capabilities": ["chat"], "free": True},
            {
                "id": "upfynai-chatterbox",
                "capabilities": ["voice-generation", "voice-cloning"],
                "credits_per_request": 10,
            },
        ]})

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)

    out = ai.list_models(memconn)

    assert out["ok"] is True
    by_id = {model["id"]: model for model in out["models"]}
    assert by_id["upfynai-mini-v3"]["free"] is True
    assert by_id["upfynai-mini-v3"]["chat_compatible"] is True
    assert by_id["upfynai-chatterbox"]["chat_compatible"] is False
    assert by_id["upfynai-chatterbox"]["capabilities"] == [
        "voice-generation",
        "voice-cloning",
    ]
    assert seen["headers"]["User-agent"].startswith("Mozilla/5.0")
    assert seen["headers"]["Authorization"] == "Bearer upfyn-test-key"


def test_chat_complete_sends_browser_safe_user_agent(memconn, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["timeout"] = timeout
        return _FakeResponse({
            "choices": [{"message": {"content": "Hello from provider"}}]
        })

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)

    text = ai.chat_complete(
        [{"role": "user", "content": "Hello"}],
        conn=memconn,
    )

    assert text == "Hello from provider"
    assert seen["headers"]["User-agent"].startswith("Mozilla/5.0")
    assert seen["headers"]["Content-type"] == "application/json"


def test_build_openai_client_sets_browser_safe_user_agent(monkeypatch):
    seen = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)

    ai._build_openai_client(
        base_url="https://ai.upfyn.com/v1",
        api_key="upfyn-test-key",
    )

    assert seen["base_url"] == "https://ai.upfyn.com/v1"
    assert seen["api_key"] == "upfyn-test-key"
    assert seen["default_headers"]["User-Agent"].startswith("Mozilla/5.0")
