from __future__ import annotations

import json

from hrkit import branding, chat, composio_sdk


def _ensure_settings(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("COMPOSIO_API_KEY", "fake-composio-key"),
    )
    conn.commit()


def test_chat_builds_docs_style_composio_meta_tools(conn, monkeypatch):
    _ensure_settings(conn)
    monkeypatch.setattr(composio_sdk, "list_actions", lambda conn, **kw: [
        {
            "slug": "GMAIL_SEND_EMAIL",
            "name": "Send",
            "description": "Send email",
            "toolkit_slug": "gmail",
            "deprecated": False,
        },
        {
            "slug": "GMAIL_DELETE_EMAIL",
            "name": "Delete",
            "description": "Delete email",
            "toolkit_slug": "gmail",
            "deprecated": False,
        },
    ])
    branding.set_composio_disabled_tools(conn, ["GMAIL_DELETE_EMAIL"])

    tools = chat._build_composio_action_tools(conn)
    by_name = {tool.__name__: tool for tool in tools}

    assert "COMPOSIO_SEARCH_TOOLS" in by_name
    assert "COMPOSIO_GET_TOOL_SCHEMAS" in by_name
    assert "COMPOSIO_MULTI_EXECUTE_TOOL" in by_name
    assert "COMPOSIO_MANAGE_CONNECTIONS" in by_name

    found = json.loads(by_name["COMPOSIO_SEARCH_TOOLS"]("email", "gmail"))
    slugs = {item["slug"] for item in found}
    assert "GMAIL_SEND_EMAIL" in slugs
    assert "GMAIL_DELETE_EMAIL" not in slugs


def test_composio_execute_tool_honors_integrations_toggle(conn, monkeypatch):
    _ensure_settings(conn)
    branding.set_composio_disabled_tools(conn, ["GMAIL_SEND_EMAIL"])
    called = []
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *args, **kwargs: called.append(args) or {
        "successful": True,
        "data": {},
        "error": "",
    })

    tools = {tool.__name__: tool for tool in chat._build_composio_action_tools(conn)}
    out = tools["COMPOSIO_MULTI_EXECUTE_TOOL"](
        "GMAIL_SEND_EMAIL",
        {"recipient_email": "a@example.com"},
    )

    assert "disabled by HR" in out
    assert called == []


def test_composio_execute_tool_runs_enabled_action(conn, monkeypatch):
    _ensure_settings(conn)
    captured = {}

    def fake_execute(conn, slug, arguments):
        captured.update({"slug": slug, "arguments": arguments})
        return {"successful": True, "data": {"id": "msg-1"}, "error": ""}

    monkeypatch.setattr(composio_sdk, "execute_action", fake_execute)
    tools = {tool.__name__: tool for tool in chat._build_composio_action_tools(conn)}
    out = json.loads(tools["COMPOSIO_MULTI_EXECUTE_TOOL"](
        "gmail_send_email",
        {"recipient_email": "a@example.com"},
    ))

    assert out["successful"] is True
    assert captured["slug"] == "GMAIL_SEND_EMAIL"
    assert captured["arguments"]["recipient_email"] == "a@example.com"


def test_manage_connection_returns_connect_link(conn, monkeypatch):
    _ensure_settings(conn)
    monkeypatch.setattr(composio_sdk, "init_connection", lambda conn, slug: {
        "redirect_url": f"https://composio/connect/{slug}",
        "connected_account_id": f"ca-{slug}",
        "raw": {},
    })
    tools = {tool.__name__: tool for tool in chat._build_composio_action_tools(conn)}
    out = json.loads(tools["COMPOSIO_MANAGE_CONNECTIONS"]("gmail"))
    assert out["redirect_url"] == "https://composio/connect/gmail"
