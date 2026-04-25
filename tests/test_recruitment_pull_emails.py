"""Tests for recruitment.pull_emails_api — Gmail → candidate flow."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from hrkit import branding, composio_sdk
from hrkit.modules import recruitment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
class _FakeServer:
    def __init__(self, conn, workspace_root) -> None:
        self.conn = conn
        self.workspace_root = workspace_root


class _FakeHandler:
    def __init__(self, conn, workspace_root, body=None) -> None:
        self.server = _FakeServer(conn, workspace_root)
        self._body = body or {}
        self.responses: list[tuple[int, Any]] = []

    def _read_json(self):
        return self._body

    def _json(self, payload, code: int = 200) -> None:
        self.responses.append((code, payload))


def _set_key(conn):
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("COMPOSIO_API_KEY", "fake-key"),
    )
    conn.commit()


@pytest.fixture
def env(conn, tmp_path):
    """Conn (with settings + recruitment_candidate tables) + tmp workspace."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    return conn, tmp_path


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------
def test_pull_emails_requires_composio_key(env):
    conn, tmp = env
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 400
    assert "Composio API key not configured" in payload["error"]


def test_pull_emails_blocked_when_tool_disabled(env, monkeypatch):
    conn, tmp = env
    _set_key(conn)
    branding.set_composio_disabled_tools(conn, [recruitment.GMAIL_FETCH_ACTION])
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 400
    assert "disabled" in payload["error"].lower()


def test_pull_emails_surfaces_composio_failure(env, monkeypatch):
    conn, tmp = env
    _set_key(conn)
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *a, **kw: {
        "successful": False, "data": {}, "error": "Low Credits",
    })
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 502
    assert "Low Credits" in payload["error"]


# ---------------------------------------------------------------------------
# Happy path — emails become candidates + mirror files
# ---------------------------------------------------------------------------
def _fake_gmail_response(messages: list[dict]) -> dict:
    return {"successful": True, "data": {"messages": messages}, "error": ""}


def test_pull_emails_creates_candidate_and_mirrors(env, monkeypatch):
    conn, tmp = env
    _set_key(conn)
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *a, **kw: _fake_gmail_response([
        {
            "id": "gmail-msg-1",
            "threadId": "thread-1",
            "subject": "Application: Senior Engineer",
            "from": "Asha Iyer <asha@example.com>",
            "to": "hr@thinqmesh.com",
            "date": "Mon, 20 Apr 2026 14:32:00 +0530",
            "body": "Hi team,\n\nPlease find my application attached.",
        },
    ]))
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    assert payload["fetched"] == 1
    assert len(payload["created_candidate_ids"]) == 1
    assert payload["mirrored"] == 1

    # The candidate row was created with the parsed name + email + source.
    cand = conn.execute(
        "SELECT name, email, source FROM recruitment_candidate"
        " WHERE id = ?", (payload["created_candidate_ids"][0],),
    ).fetchone()
    assert cand["name"] == "Asha Iyer"
    assert cand["email"] == "asha@example.com"
    assert cand["source"] == "gmail"

    # Mirror files exist on disk.
    md = tmp / "integrations" / "gmail" / "messages" / "gmail-msg-1.md"
    js = tmp / "integrations" / "gmail" / "messages" / "gmail-msg-1.json"
    assert md.exists() and js.exists()
    text = md.read_text(encoding="utf-8")
    assert "Senior Engineer" in text
    assert "asha@example.com" in text


def test_pull_emails_skips_existing_candidate_by_email(env, monkeypatch):
    conn, tmp = env
    _set_key(conn)
    # Pre-create a candidate with the same email.
    recruitment.create_row(conn, {"name": "Old", "email": "asha@example.com", "source": "manual"})
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *a, **kw: _fake_gmail_response([
        {"id": "gmail-msg-2", "from": "asha@example.com", "subject": "Re: hi",
         "body": "ping"},
    ]))
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    assert payload["fetched"] == 1
    assert payload["created_candidate_ids"] == []
    assert "asha@example.com" in payload["skipped_existing"]
    # Still mirrored to disk for the human archive.
    assert payload["mirrored"] == 1


def test_pull_emails_handles_gmail_payload_headers(env, monkeypatch):
    """Composio sometimes returns the raw Gmail API shape with payload.headers."""
    conn, tmp = env
    _set_key(conn)
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *a, **kw: _fake_gmail_response([
        {
            "id": "raw-msg-1",
            "threadId": "th-1",
            "snippet": "Looking for the senior role",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Senior role"},
                    {"name": "From", "value": '"Tara J" <tara@example.com>'},
                    {"name": "To", "value": "hr@thinqmesh.com"},
                    {"name": "Date", "value": "Mon, 21 Apr 2026 10:00:00 +0530"},
                ],
            },
        },
    ]))
    h = _FakeHandler(conn, tmp)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert payload["ok"] is True
    cand = conn.execute(
        "SELECT name, email FROM recruitment_candidate WHERE id = ?",
        (payload["created_candidate_ids"][0],),
    ).fetchone()
    assert cand["name"] == "Tara J"
    assert cand["email"] == "tara@example.com"


def test_pull_emails_warns_when_no_workspace_root(env, monkeypatch):
    conn, _ = env
    _set_key(conn)
    monkeypatch.setattr(composio_sdk, "execute_action", lambda *a, **kw: _fake_gmail_response([
        {"id": "m1", "from": "p@example.com", "subject": "Hi", "body": "x"},
    ]))
    # Pass workspace_root=None — and ensure server module also has no ROOT.
    monkeypatch.setattr("hrkit.server.ROOT", None, raising=False)
    h = _FakeHandler(conn, None)
    recruitment.pull_emails_api(h)
    code, payload = h.responses[0]
    assert code == 200 and payload["ok"] is True
    # Candidate still created from the email even though disk mirror was skipped.
    assert len(payload["created_candidate_ids"]) == 1
    assert payload["mirrored"] == 0
    assert "mirror_warning" in payload


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_parse_email_address_handles_named_form():
    name, email = recruitment._parse_email_address("Asha Iyer <asha@example.com>")
    assert name == "Asha Iyer"
    assert email == "asha@example.com"


def test_parse_email_address_handles_bare_addr():
    name, email = recruitment._parse_email_address("solo@example.com")
    assert email == "solo@example.com"


def test_extract_messages_normalizes_three_shapes():
    nested = {"data": {"messages": [{"id": "a"}, {"id": "b"}]}}
    flat_data = {"data": [{"id": "c"}]}
    bare = [{"id": "d"}]
    assert [m["id"] for m in recruitment._extract_gmail_messages(nested)] == ["a", "b"]
    assert [m["id"] for m in recruitment._extract_gmail_messages(flat_data)] == ["c"]
    assert [m["id"] for m in recruitment._extract_gmail_messages(bare)] == ["d"]
