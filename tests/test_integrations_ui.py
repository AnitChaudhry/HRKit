"""Tests for hrkit.integrations_ui — page state + JSON API handlers."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from hrkit import branding, composio_sdk, integrations_ui


# ---------------------------------------------------------------------------
# Fixtures + fakes
# ---------------------------------------------------------------------------
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


class _FakeServer:
    def __init__(self, conn) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn) -> None:
        self.server = _FakeServer(conn)
        self.responses: list[tuple[int, Any]] = []

    def _json(self, payload, code: int = 200) -> None:
        self.responses.append((code, payload))


def _set_key(conn, key="fake-key"):
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("COMPOSIO_API_KEY", key),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get_state — empty state when no key
# ---------------------------------------------------------------------------
def test_state_returns_empty_when_no_key(memconn):
    state = integrations_ui.get_state(memconn)
    assert state["ok"] is True
    assert state["configured"] is False
    assert state["connected"] == []
    # Curated catalog still shown so the user can browse what they could connect.
    assert len(state["available"]) >= 4
    assert any(a["slug"] == "gmail" for a in state["available"])


# ---------------------------------------------------------------------------
# get_state — connected + available split when key present
# ---------------------------------------------------------------------------
def test_state_separates_connected_from_available(memconn, monkeypatch):
    _set_key(memconn)
    monkeypatch.setattr(composio_sdk, "list_connections", lambda conn: [
        {"id": "c1", "toolkit_slug": "gmail", "status": "ACTIVE", "created_at": "now"},
    ])
    monkeypatch.setattr(composio_sdk, "list_actions", lambda conn, app_slug=None, **kw: [
        {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "send",
         "toolkit_slug": "gmail", "deprecated": False},
        {"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "fetch",
         "toolkit_slug": "gmail", "deprecated": False},
    ])
    state = integrations_ui.get_state(memconn)
    assert state["configured"] is True
    assert len(state["connected"]) == 1
    gmail = state["connected"][0]
    assert gmail["slug"] == "gmail"
    assert gmail["name"] == "Gmail"
    assert {a["slug"] for a in gmail["actions"]} == {"GMAIL_SEND_EMAIL", "GMAIL_FETCH_EMAILS"}
    # Default = enabled.
    assert all(a["enabled"] for a in gmail["actions"])
    # Gmail no longer appears in available cards.
    assert not any(a["slug"] == "gmail" for a in state["available"])
    assert "mcp" in state
    assert state["mcp"]["configured"] is False


def test_state_reflects_disabled_tools(memconn, monkeypatch):
    _set_key(memconn)
    branding.set_composio_disabled_tools(memconn, ["GMAIL_FETCH_EMAILS"])
    monkeypatch.setattr(composio_sdk, "list_connections", lambda conn: [
        {"id": "c1", "toolkit_slug": "gmail", "status": "ACTIVE", "created_at": "now"},
    ])
    monkeypatch.setattr(composio_sdk, "list_actions", lambda conn, app_slug=None, **kw: [
        {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "",
         "toolkit_slug": "gmail", "deprecated": False},
        {"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "",
         "toolkit_slug": "gmail", "deprecated": False},
    ])
    state = integrations_ui.get_state(memconn)
    by_slug = {a["slug"]: a for a in state["connected"][0]["actions"]}
    assert by_slug["GMAIL_SEND_EMAIL"]["enabled"] is True
    assert by_slug["GMAIL_FETCH_EMAILS"]["enabled"] is False


def test_state_skips_deprecated_actions(memconn, monkeypatch):
    _set_key(memconn)
    monkeypatch.setattr(composio_sdk, "list_connections", lambda conn: [
        {"id": "c1", "toolkit_slug": "gmail", "status": "ACTIVE", "created_at": "now"},
    ])
    monkeypatch.setattr(composio_sdk, "list_actions", lambda conn, app_slug=None, **kw: [
        {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "",
         "toolkit_slug": "gmail", "deprecated": False},
        {"slug": "GMAIL_OLD_API", "name": "Old", "description": "",
         "toolkit_slug": "gmail", "deprecated": True},
    ])
    state = integrations_ui.get_state(memconn)
    slugs = {a["slug"] for a in state["connected"][0]["actions"]}
    assert "GMAIL_SEND_EMAIL" in slugs
    assert "GMAIL_OLD_API" not in slugs


# ---------------------------------------------------------------------------
# handle_connect
# ---------------------------------------------------------------------------
def test_handle_connect_returns_redirect_url(memconn, monkeypatch):
    _set_key(memconn)
    monkeypatch.setattr(composio_sdk, "init_connection", lambda conn, slug: {
        "redirect_url": f"https://composio/auth/{slug}",
        "connected_account_id": "acc-1",
        "raw": {},
    })
    h = _FakeHandler(memconn)
    integrations_ui.handle_connect(h, {"app_slug": "gmail"})
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    assert payload["redirect_url"] == "https://composio/auth/gmail"
    assert payload["connected_account_id"] == "acc-1"


def test_handle_connect_requires_slug(memconn):
    h = _FakeHandler(memconn)
    integrations_ui.handle_connect(h, {})
    code, payload = h.responses[0]
    assert code == 400 and payload["ok"] is False


def test_handle_connect_surfaces_init_error(memconn, monkeypatch):
    _set_key(memconn)
    monkeypatch.setattr(composio_sdk, "init_connection", lambda conn, slug: {
        "redirect_url": "", "connected_account_id": "", "raw": {},
        "error": "bad gateway",
    })
    h = _FakeHandler(memconn)
    integrations_ui.handle_connect(h, {"app_slug": "gmail"})
    code, payload = h.responses[0]
    assert code == 400
    assert "bad gateway" in payload["error"]


# ---------------------------------------------------------------------------
# handle_tool_toggle
# ---------------------------------------------------------------------------
def test_toggle_disables_then_enables(memconn):
    h = _FakeHandler(memconn)
    integrations_ui.handle_tool_toggle(h, {"slug": "GMAIL_SEND_EMAIL", "enabled": False})
    assert h.responses[0][1]["ok"] is True
    assert "GMAIL_SEND_EMAIL" in branding.composio_disabled_tools(memconn)

    integrations_ui.handle_tool_toggle(h, {"slug": "GMAIL_SEND_EMAIL", "enabled": True})
    assert "GMAIL_SEND_EMAIL" not in branding.composio_disabled_tools(memconn)


def test_toggle_normalizes_slug_casing(memconn):
    h = _FakeHandler(memconn)
    integrations_ui.handle_tool_toggle(h, {"slug": "gmail_send_email", "enabled": False})
    # Stored upper-cased.
    assert "GMAIL_SEND_EMAIL" in branding.composio_disabled_tools(memconn)


def test_toggle_requires_slug(memconn):
    h = _FakeHandler(memconn)
    integrations_ui.handle_tool_toggle(h, {"enabled": False})
    code, payload = h.responses[0]
    assert code == 400 and payload["ok"] is False


# ---------------------------------------------------------------------------
# handle_tool_test
# ---------------------------------------------------------------------------
def test_handle_tool_test_runs_action(memconn, monkeypatch):
    _set_key(memconn)
    captured: list[Any] = []

    def fake_exec(conn, slug, payload):
        captured.append((slug, payload))
        return {"successful": True, "data": {"id": "x"}, "error": ""}

    monkeypatch.setattr(composio_sdk, "execute_action", fake_exec)
    h = _FakeHandler(memconn)
    integrations_ui.handle_tool_test(h, {"slug": "GMAIL_SEND_EMAIL", "payload": {"to": "a@b.c"}})
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    assert payload["successful"] is True
    assert captured[0] == ("GMAIL_SEND_EMAIL", {"to": "a@b.c"})


def test_handle_tool_test_requires_slug(memconn):
    h = _FakeHandler(memconn)
    integrations_ui.handle_tool_test(h, {})
    assert h.responses[0][0] == 400


def test_handle_mcp_sync_uses_connected_enabled_tools(memconn, monkeypatch):
    _set_key(memconn)
    branding.set_composio_disabled_tools(memconn, ["GMAIL_FETCH_EMAILS"])
    monkeypatch.setattr(composio_sdk, "list_connections", lambda conn: [
        {"id": "c1", "toolkit_slug": "gmail", "status": "ACTIVE", "created_at": "now"},
    ])
    monkeypatch.setattr(composio_sdk, "list_actions", lambda conn, app_slug=None, **kw: [
        {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "",
         "toolkit_slug": "gmail", "deprecated": False},
        {"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "",
         "toolkit_slug": "gmail", "deprecated": False},
    ])
    captured = {}

    def fake_sync(conn, *, toolkits, allowed_tools):
        captured.update({"toolkits": toolkits, "allowed_tools": allowed_tools})
        return {
            "ok": True,
            "server_id": "mcp-1",
            "server_url": "https://mcp/1",
            "toolkits": toolkits,
            "allowed_tools": allowed_tools,
        }

    monkeypatch.setattr(composio_sdk, "sync_mcp_server", fake_sync)
    h = _FakeHandler(memconn)
    integrations_ui.handle_mcp_sync(h, {})
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    assert captured["toolkits"] == ["gmail"]
    assert captured["allowed_tools"] == ["GMAIL_SEND_EMAIL"]


# ---------------------------------------------------------------------------
# Page render smoke-test
# ---------------------------------------------------------------------------
def test_render_integrations_page_returns_html(memconn):
    html = integrations_ui.render_integrations_page(memconn)
    assert "<html" in html.lower() or "<!doctype" in html.lower()
    assert "Integrations" in html
    assert "/api/integrations/state" in html
    assert "/api/integrations/mcp/sync" in html
    assert "Composio MCP tool access" in html
    # Curated catalog is referenced from JS — page itself just bootstraps.
    assert "loadState" in html
