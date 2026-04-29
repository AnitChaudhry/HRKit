"""Tests for hrkit.composio_sdk — SDK-first facade with urllib fallback."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from hrkit import composio_client, composio_sdk


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def memconn_with_key(memconn):
    """A connection that has a Composio API key on file."""
    memconn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("COMPOSIO_API_KEY", "fake-key"),
    )
    memconn.commit()
    return memconn


# ---------------------------------------------------------------------------
# Tiny SDK doubles — duck-type the composio surface we touch
# ---------------------------------------------------------------------------
class _FakeToolkit:
    def __init__(self, slug: str, name: str = "", description: str = "") -> None:
        self.slug = slug
        self.name = name or slug.title()
        self.description = description or f"{slug} integration"
        self.logo = f"https://logo/{slug}.png"
        self.categories = ["productivity"]


class _FakeListResp:
    def __init__(self, items: list) -> None:
        self.items = items


class _FakeTool:
    def __init__(self, slug: str, toolkit_slug: str, name: str = "") -> None:
        self.slug = slug
        self.name = name or slug
        self.human_description = f"runs {slug}"
        self.deprecated = False

        class _T:
            pass

        self.toolkit = _T()
        self.toolkit.slug = toolkit_slug


class _FakeConn:
    def __init__(self, id_: str, toolkit_slug: str, status: str = "ACTIVE") -> None:
        self.id = id_
        self.toolkit_slug = toolkit_slug
        self.status = status
        self.created_at = "2026-04-25T10:00:00Z"


class _FakeReq:
    def __init__(self, id_: str, redirect_url: str) -> None:
        self.id = id_
        self.redirect_url = redirect_url
        self.status = "INITIATED"


class _FakeExec:
    def __init__(self, *, successful: bool = True, data: dict | None = None,
                 error: str = "") -> None:
        self.successful = successful
        self.data = data or {"id": "msg-1"}
        self.error = error


class _FakeToolkits:
    def __init__(self, items: list) -> None:
        self._items = items
        self.authorized: list[tuple[str, str]] = []

    def list(self, *, limit=None, **_) -> _FakeListResp:
        return _FakeListResp(self._items)

    def get(self, slug=None, *, query=None):
        if slug:
            return next((item for item in self._items if item.slug == slug), None)
        return _FakeListResp(self._items)

    def authorize(self, *, user_id: str, toolkit: str) -> _FakeReq:
        self.authorized.append((user_id, toolkit))
        return _FakeReq(id_=f"conn-{toolkit}", redirect_url=f"https://composio/auth/{toolkit}")


class _FakeTools:
    def __init__(self, tools: list) -> None:
        self._tools = tools
        self.executed: list[tuple[str, dict]] = []

    def get_raw_composio_tools(self, *, toolkits=None, search=None, limit=None) -> list:
        if toolkits:
            return [t for t in self._tools if t.toolkit.slug in toolkits]
        return list(self._tools)

    def get_raw_composio_tool_by_slug(self, slug: str):
        return next(t for t in self._tools if t.slug == slug)

    def execute(self, *, slug: str, arguments: dict, **_) -> _FakeExec:
        self.executed.append((slug, arguments))
        return _FakeExec(data={"echo": arguments})


class _FakeConnAccts:
    def __init__(self, items: list) -> None:
        self._items = items

    def list(self, **_) -> _FakeListResp:
        return _FakeListResp(self._items)


class _FakeComposio:
    def __init__(self, *, api_key: str = "", **_) -> None:
        self.api_key = api_key
        self.toolkits = _FakeToolkits([
            _FakeToolkit("gmail", "Gmail"),
            _FakeToolkit("slack", "Slack"),
        ])
        self.tools = _FakeTools([
            _FakeTool("GMAIL_SEND_EMAIL", "gmail"),
            _FakeTool("GMAIL_FETCH_EMAILS", "gmail"),
            _FakeTool("SLACK_SEND_MESSAGE", "slack"),
        ])
        self.connected_accounts = _FakeConnAccts([
            _FakeConn("conn-1", "gmail", "ACTIVE"),
        ])


def _patch_sdk(monkeypatch, *, available: bool = True) -> None:
    """Force composio_sdk._client to return a fake (or None to disable SDK)."""
    if available:
        monkeypatch.setattr(composio_sdk, "_client", lambda conn: _FakeComposio(api_key="x"))
    else:
        monkeypatch.setattr(composio_sdk, "_client", lambda conn: None)


# ---------------------------------------------------------------------------
# user_id is stable + persisted
# ---------------------------------------------------------------------------
def test_user_id_persists_across_calls(memconn):
    a = composio_sdk.user_id(memconn)
    b = composio_sdk.user_id(memconn)
    assert a == b
    assert a.startswith(composio_sdk.DEFAULT_USER_ID_PREFIX)
    # And the value is now in settings.
    row = memconn.execute(
        "SELECT value FROM settings WHERE key = ?", (composio_sdk.USER_ID_KEY,)
    ).fetchone()
    assert row["value"] == a


# ---------------------------------------------------------------------------
# SDK path
# ---------------------------------------------------------------------------
def test_list_apps_via_sdk(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    apps = composio_sdk.list_apps(memconn)
    slugs = {a["slug"] for a in apps}
    assert slugs == {"gmail", "slack"}
    assert all(a["name"] for a in apps)


def test_list_apps_supports_current_sdk_toolkits_get(memconn, monkeypatch):
    class _ToolkitsGetOnly:
        def get(self, slug=None, *, query=None):
            return _FakeListResp([_FakeToolkit("gmail", "Gmail")])

    class _SDK:
        toolkits = _ToolkitsGetOnly()

    monkeypatch.setattr(composio_sdk, "_client", lambda conn: _SDK())
    apps = composio_sdk.list_apps(memconn)
    assert apps[0]["slug"] == "gmail"


def test_list_actions_filters_by_toolkit(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    actions = composio_sdk.list_actions(memconn, app_slug="gmail")
    slugs = {a["slug"] for a in actions}
    assert slugs == {"GMAIL_SEND_EMAIL", "GMAIL_FETCH_EMAILS"}
    assert all(a["toolkit_slug"] == "gmail" for a in actions)


def test_list_connections_via_sdk(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    conns = composio_sdk.list_connections(memconn)
    assert len(conns) == 1
    assert conns[0]["toolkit_slug"] == "gmail"
    assert conns[0]["status"] == "ACTIVE"


def test_init_connection_returns_redirect_url(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    out = composio_sdk.init_connection(memconn, "gmail")
    assert out["redirect_url"] == "https://composio/auth/gmail"
    assert out["connected_account_id"] == "conn-gmail"


def test_execute_action_returns_normalized_envelope(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    out = composio_sdk.execute_action(memconn, "GMAIL_SEND_EMAIL", {"to": "x@y.z"})
    assert out["successful"] is True
    assert out["data"] == {"echo": {"to": "x@y.z"}}
    assert out["error"] == ""


def test_get_action_schema_via_sdk(memconn, monkeypatch):
    _patch_sdk(monkeypatch)
    schema = composio_sdk.get_action_schema(memconn, "gmail_send_email")
    assert schema["slug"] == "GMAIL_SEND_EMAIL"
    assert schema["toolkit_slug"] == "gmail"


# ---------------------------------------------------------------------------
# Fallback path — when SDK unavailable, urllib client is used
# ---------------------------------------------------------------------------
def test_list_apps_falls_back_to_urllib(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    monkeypatch.setattr(
        composio_client, "list_apps",
        lambda conn: [{"slug": "github", "name": "GitHub", "description": "code"}],
    )
    apps = composio_sdk.list_apps(memconn)
    assert apps == [{
        "slug": "github", "name": "GitHub", "description": "code",
        "logo": "", "categories": [],
    }]


def test_execute_action_falls_back_to_urllib(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    captured: list[Any] = []

    def fake_exec(conn, action_slug, params, **kw):
        captured.append((action_slug, params, kw))
        return {"data": {"id": "fallback-1"}, "successful": True}

    monkeypatch.setattr(composio_client, "execute_action", fake_exec)
    out = composio_sdk.execute_action(memconn, "GMAIL_SEND_EMAIL", {"to": "y@z"})
    assert out["successful"] is True
    assert out["data"] == {"id": "fallback-1"}
    assert captured and captured[0][0] == "GMAIL_SEND_EMAIL"


def test_get_action_schema_falls_back_to_v3_tool_endpoint(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    monkeypatch.setattr(composio_client, "get_tool", lambda conn, slug: {
        "slug": slug,
        "name": "Send",
        "description": "Send an email",
        "toolkit": {"slug": "gmail"},
        "input_parameters": {"recipient_email": {"type": "string"}},
    })
    schema = composio_sdk.get_action_schema(memconn, "GMAIL_SEND_EMAIL")
    assert schema["slug"] == "GMAIL_SEND_EMAIL"
    assert schema["input_parameters"]["recipient_email"]["type"] == "string"


def test_sync_mcp_server_creates_and_persists_state(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    captured = {}

    def fake_create(conn, *, name, toolkits, allowed_tools):
        captured.update({"name": name, "toolkits": toolkits, "allowed_tools": allowed_tools})
        return {
            "id": "mcp-1",
            "mcp_url": "https://backend.composio.dev/v3/mcp/mcp-1?user_id=u",
        }

    monkeypatch.setattr(composio_client, "create_mcp_server", fake_create)
    out = composio_sdk.sync_mcp_server(
        memconn,
        toolkits=["gmail"],
        allowed_tools=["GMAIL_SEND_EMAIL"],
    )
    assert out["ok"] is True
    assert captured["toolkits"] == ["gmail"]
    assert captured["allowed_tools"] == ["GMAIL_SEND_EMAIL"]
    state = composio_sdk.mcp_state(memconn)
    assert state["server_id"] == "mcp-1"
    assert state["allowed_tools"] == ["GMAIL_SEND_EMAIL"]


def test_sync_mcp_server_updates_existing_server(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    memconn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (composio_sdk.MCP_SERVER_ID_KEY, "mcp-old"),
    )
    captured = {}

    def fake_update(conn, server_id, **kwargs):
        captured.update({"server_id": server_id, **kwargs})
        return {"id": server_id, "mcp_url": "https://mcp/current"}

    monkeypatch.setattr(composio_client, "update_mcp_server", fake_update)
    out = composio_sdk.sync_mcp_server(
        memconn,
        toolkits=["slack"],
        allowed_tools=["SLACK_SEND_MESSAGE"],
    )
    assert out["server_id"] == "mcp-old"
    assert captured["server_id"] == "mcp-old"
    assert captured["allowed_tools"] == ["SLACK_SEND_MESSAGE"]


def test_init_connection_falls_back_to_urllib(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)
    monkeypatch.setattr(
        composio_client, "init_connection",
        lambda conn, slug: {"redirect_url": "https://urllib/auth", "connected_account_id": "c-1", "raw": {}},
    )
    out = composio_sdk.init_connection(memconn, "gmail")
    assert out["redirect_url"] == "https://urllib/auth"
    assert out["connected_account_id"] == "c-1"


# ---------------------------------------------------------------------------
# Error handling — never raise to callers
# ---------------------------------------------------------------------------
def test_list_apps_returns_empty_when_both_paths_fail(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)

    def boom(conn):
        raise composio_client.ComposioError("not configured", status=None)

    monkeypatch.setattr(composio_client, "list_apps", boom)
    assert composio_sdk.list_apps(memconn) == []


def test_init_connection_requires_slug(memconn):
    out = composio_sdk.init_connection(memconn, "")
    assert out["redirect_url"] == ""
    assert "app_slug" in out["error"]


def test_execute_action_wraps_urllib_error(memconn, monkeypatch):
    _patch_sdk(monkeypatch, available=False)

    def boom(conn, action_slug, params, **kw):
        raise composio_client.ComposioError("kaboom", status=502)

    monkeypatch.setattr(composio_client, "execute_action", boom)
    out = composio_sdk.execute_action(memconn, "X", {})
    assert out["successful"] is False
    assert "kaboom" in out["error"]
