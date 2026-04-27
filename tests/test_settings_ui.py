"""Tests for hrkit.settings_ui — handle_save_settings validation rules.

Covers the cross-field rule introduced in Phase 2 of the AI-config fix:
when the user changes ``ai_provider`` from one provider to another, the
request must include ``ai_model`` too. Without this rule, the previously
saved model (e.g. an OpenRouter ``meta-llama/...:free`` slug) would silently
remain in the DB, then fail at chat time when used against Upfyn.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from hrkit import settings_ui


class _FakeServer:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.server = _FakeServer(conn)
        self.conn = conn
        self.json_responses: list[tuple[int, Any]] = []

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))


def _ensure_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def test_save_app_name_only(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    settings_ui.handle_save_settings(h, {"app_name": "Acme HR"})
    code, payload = h.json_responses[0]
    assert code == 200 and payload["ok"] is True
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'APP_NAME'"
    ).fetchone()
    assert row["value"] == "Acme HR"


def test_save_provider_change_requires_model(conn):
    """Changing ai_provider without supplying ai_model must be rejected."""
    _ensure_settings_table(conn)
    # Pre-existing config: openrouter + a model that won't work on upfyn.
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_PROVIDER", "openrouter"),
    )
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
    )
    h = _FakeHandler(conn)
    settings_ui.handle_save_settings(h, {
        "ai_provider": "upfyn",
        "ai_api_key": "upfyn-newkey",
        # ai_model deliberately omitted
    })
    code, payload = h.json_responses[0]
    assert code == 400
    assert payload["ok"] is False
    assert "ai_model" in payload["error"]
    # And critically: the provider must NOT have been silently swapped.
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'AI_PROVIDER'"
    ).fetchone()
    assert row["value"] == "openrouter"


def test_save_provider_change_with_model_succeeds(conn):
    _ensure_settings_table(conn)
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_PROVIDER", "openrouter"),
    )
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
    )
    h = _FakeHandler(conn)
    settings_ui.handle_save_settings(h, {
        "ai_provider": "upfyn",
        "ai_api_key": "upfyn-newkey",
        "ai_model": "gpt-4o-mini",
    })
    code, payload = h.json_responses[0]
    assert code == 200 and payload["ok"] is True
    rows = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM settings"
    ).fetchall()}
    assert rows["AI_PROVIDER"] == "upfyn"
    assert rows["AI_MODEL"] == "gpt-4o-mini"
    assert rows["AI_API_KEY"] == "upfyn-newkey"


def test_save_same_provider_allows_blank_model(conn):
    """Re-saving the same provider without a model must NOT trigger the
    new validation — the user is just updating other fields."""
    _ensure_settings_table(conn)
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_PROVIDER", "openrouter"),
    )
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("AI_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
    )
    h = _FakeHandler(conn)
    # Same provider, no model — should still save (model unchanged).
    settings_ui.handle_save_settings(h, {
        "ai_provider": "openrouter",
        "ai_api_key": "sk-or-rotated",
    })
    code, payload = h.json_responses[0]
    assert code == 200 and payload["ok"] is True


def test_save_initial_provider_no_prior_config(conn):
    """Setting a provider for the first time (no prior provider in DB)
    should not trigger the change-validation rule."""
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    settings_ui.handle_save_settings(h, {
        "ai_provider": "openrouter",
        "ai_api_key": "sk-or-test",
    })
    code, payload = h.json_responses[0]
    assert code == 200 and payload["ok"] is True
