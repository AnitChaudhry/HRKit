"""Tests for AI tool gating against COMPOSIO_DISABLED_TOOLS."""

from __future__ import annotations

import sqlite3

import pytest

from hrkit import ai, branding


@pytest.fixture
def memconn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    yield c
    c.close()


# ---------------------------------------------------------------------------
# A pydantic-ai-style "tool object" — has a `.name` attribute
# ---------------------------------------------------------------------------
class _NamedTool:
    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, *a, **kw):  # pragma: no cover - never called in these tests
        return None


def _local_query_records():  # name comes from __name__
    return None


# ---------------------------------------------------------------------------
# filter_disabled_tools — defaults
# ---------------------------------------------------------------------------
def test_filter_returns_input_when_no_disabled_set(memconn):
    tools = [_NamedTool("GMAIL_SEND_EMAIL"), _NamedTool("SLACK_SEND_MESSAGE")]
    assert ai.filter_disabled_tools(tools, memconn) == tools


def test_filter_handles_none_and_empty(memconn):
    assert ai.filter_disabled_tools(None, memconn) == []
    assert ai.filter_disabled_tools([], memconn) == []


# ---------------------------------------------------------------------------
# Disabled tools are dropped
# ---------------------------------------------------------------------------
def test_filter_drops_disabled_named_tool(memconn):
    branding.set_composio_disabled_tools(memconn, ["GMAIL_SEND_EMAIL"])
    tools = [_NamedTool("GMAIL_SEND_EMAIL"), _NamedTool("SLACK_SEND_MESSAGE")]
    kept = ai.filter_disabled_tools(tools, memconn)
    assert len(kept) == 1
    assert kept[0].name == "SLACK_SEND_MESSAGE"


def test_filter_is_case_insensitive(memconn):
    branding.set_composio_disabled_tools(memconn, ["gmail_send_email"])  # lowercased
    tools = [_NamedTool("Gmail_Send_Email"), _NamedTool("SLACK_SEND_MESSAGE")]
    kept = ai.filter_disabled_tools(tools, memconn)
    assert {t.name for t in kept} == {"SLACK_SEND_MESSAGE"}


def test_filter_keeps_local_callables_without_extractable_name(memconn):
    """A callable like query_records should NEVER be filtered as a Composio slug."""
    branding.set_composio_disabled_tools(memconn, ["GMAIL_SEND_EMAIL"])
    tools = [_local_query_records, _NamedTool("GMAIL_SEND_EMAIL")]
    kept = ai.filter_disabled_tools(tools, memconn)
    # The bare callable's __name__ is 'local_query_records' — not in the disabled set.
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in kept]
    assert "_local_query_records" in names
    assert "GMAIL_SEND_EMAIL" not in names


def test_filter_drops_dict_style_tool_definitions(memconn):
    """OpenAI-style tool dicts use {'name': '...'} — those should also gate."""
    branding.set_composio_disabled_tools(memconn, ["GMAIL_FETCH_EMAILS"])
    tools = [
        {"name": "GMAIL_FETCH_EMAILS", "description": "fetch"},
        {"name": "GMAIL_SEND_EMAIL", "description": "send"},
    ]
    kept = ai.filter_disabled_tools(tools, memconn)
    assert {t["name"] for t in kept} == {"GMAIL_SEND_EMAIL"}


def test_filter_works_when_conn_is_none():
    """Defensive: callers without a DB connection should get the input back."""
    tools = [_NamedTool("X"), _NamedTool("Y")]
    assert ai.filter_disabled_tools(tools, None) == tools
