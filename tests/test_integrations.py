"""Tests for the Wave 4 hook bus + default Composio handlers."""
from __future__ import annotations

import sqlite3

import pytest

from hrkit import composio_client
from hrkit.integrations import composio_actions, hooks
from hrkit.integrations.register import register_default_hooks


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty hook registry."""
    hooks.clear()
    yield
    hooks.clear()


@pytest.fixture
def memconn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Hook bus
# ---------------------------------------------------------------------------

def test_on_and_emit_round_trip(memconn):
    received: list[dict] = []

    def handler(payload, *, conn):
        received.append({"payload": payload, "conn_is": conn})
        return {"ok": True, "echo": payload}

    hooks.on("demo.event", handler)
    results = hooks.emit("demo.event", {"hello": "world"}, conn=memconn)

    assert results == [{"ok": True, "echo": {"hello": "world"}}]
    assert received and received[0]["payload"] == {"hello": "world"}
    assert received[0]["conn_is"] is memconn


def test_emit_with_no_handlers_returns_empty_list(memconn):
    assert hooks.emit("nobody.listening", {"x": 1}, conn=memconn) == []


def test_emit_catches_handler_exceptions(memconn):
    def good(payload, *, conn):
        return {"ok": True, "src": "good"}

    def bad(payload, *, conn):
        raise RuntimeError("kaboom")

    def also_good(payload, *, conn):
        return {"ok": True, "src": "also_good"}

    hooks.on("mix", good)
    hooks.on("mix", bad)
    hooks.on("mix", also_good)

    results = hooks.emit("mix", {}, conn=memconn)
    assert len(results) == 3
    assert results[0] == {"ok": True, "src": "good"}
    assert results[1]["ok"] is False
    assert "kaboom" in results[1]["error"]
    assert results[2] == {"ok": True, "src": "also_good"}


def test_emit_rejects_non_dict_handler_return(memconn):
    hooks.on("bad.shape", lambda p, *, conn: "not a dict")
    results = hooks.emit("bad.shape", {}, conn=memconn)
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "dict" in results[0]["error"]


def test_on_validates_inputs():
    with pytest.raises(ValueError):
        hooks.on("", lambda p, *, conn: {"ok": True})
    with pytest.raises(TypeError):
        hooks.on("x", "not callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# register_default_hooks
# ---------------------------------------------------------------------------

def test_register_default_hooks_registers_three(memconn, monkeypatch):
    register_default_hooks()
    # Force the not-configured path so we don't talk to the network.
    monkeypatch.setattr(composio_client, "is_configured", lambda conn: False)

    r1 = hooks.emit("recruitment.hired", {"name": "A", "email": "a@a"}, conn=memconn)
    r2 = hooks.emit(
        "leave.approved",
        {"employee_name": "A", "start_date": "2026-05-01", "end_date": "2026-05-02"},
        conn=memconn,
    )
    r3 = hooks.emit(
        "payroll.payslip_generated",
        {"file_path": "/tmp/p.pdf", "filename": "p.pdf"},
        conn=memconn,
    )

    assert len(r1) == 1 and r1[0] == {"ok": False, "skipped": "not_configured"}
    assert len(r2) == 1 and r2[0] == {"ok": False, "skipped": "not_configured"}
    assert len(r3) == 1 and r3[0] == {"ok": False, "skipped": "not_configured"}

    assert len(hooks.registered("recruitment.hired")) == 1
    assert len(hooks.registered("leave.approved")) == 1
    assert len(hooks.registered("payroll.payslip_generated")) == 1


# ---------------------------------------------------------------------------
# composio_actions — happy path with execute_action monkey-patched
# ---------------------------------------------------------------------------

def _patch_composio(monkeypatch, *, configured: bool = True):
    calls: list[dict] = []

    def fake_execute(conn, action_slug, params):
        calls.append({"action": action_slug, "params": params})
        return {"data": {"id": "fake-id"}, "successful": True}

    monkeypatch.setattr(composio_client, "is_configured", lambda conn: configured)
    monkeypatch.setattr(composio_client, "execute_action", fake_execute)
    return calls


def test_send_offer_email_calls_gmail_action(memconn, monkeypatch):
    calls = _patch_composio(monkeypatch)
    payload = {"name": "Alex", "email": "alex@example.com", "position": "QA Lead"}
    result = composio_actions.send_offer_email(payload, conn=memconn)

    assert result["ok"] is True
    assert result["result"]["successful"] is True
    assert len(calls) == 1
    assert calls[0]["action"] == "GMAIL_SEND_EMAIL"
    assert calls[0]["params"]["recipient_email"] == "alex@example.com"
    assert "Alex" in calls[0]["params"]["subject"]
    assert "QA Lead" in calls[0]["params"]["subject"]
    assert "Alex" in calls[0]["params"]["body"]


def test_block_calendar_for_leave_calls_calendar_action(memconn, monkeypatch):
    calls = _patch_composio(monkeypatch)
    payload = {
        "employee_name": "Alex",
        "leave_type": "Casual Leave",
        "start_date": "2026-05-01",
        "end_date": "2026-05-03",
        "reason": "Family trip",
    }
    result = composio_actions.block_calendar_for_leave(payload, conn=memconn)

    assert result["ok"] is True
    assert calls[0]["action"] == "GOOGLECALENDAR_CREATE_EVENT"
    p = calls[0]["params"]
    assert p["summary"] == "Alex — Casual Leave"
    assert p["start_datetime"] == "2026-05-01"
    assert p["end_datetime"] == "2026-05-03"
    assert p["calendar_id"] == "primary"
    assert p["all_day"] is True
    assert p["description"] == "Family trip"


def test_upload_payslip_to_drive_calls_drive_action(memconn, monkeypatch):
    calls = _patch_composio(monkeypatch)
    payload = {
        "file_path": "/var/payslips/2026-04/alex.pdf",
        "folder_id": "drive-folder-123",
    }
    result = composio_actions.upload_payslip_to_drive(payload, conn=memconn)

    assert result["ok"] is True
    assert calls[0]["action"] == "GOOGLEDRIVE_UPLOAD_FILE"
    p = calls[0]["params"]
    assert p["file_path"] == "/var/payslips/2026-04/alex.pdf"
    assert p["file_name"] == "alex.pdf"  # derived from file_path tail
    assert p["folder_id"] == "drive-folder-123"
    assert p["mime_type"] == "application/pdf"


# ---------------------------------------------------------------------------
# composio_actions — not-configured + error envelopes
# ---------------------------------------------------------------------------

def test_actions_skip_when_not_configured(memconn, monkeypatch):
    calls: list[dict] = []

    def fake_execute(conn, action_slug, params):
        calls.append({"action": action_slug, "params": params})
        return {}

    monkeypatch.setattr(composio_client, "is_configured", lambda conn: False)
    monkeypatch.setattr(composio_client, "execute_action", fake_execute)

    expected = {"ok": False, "skipped": "not_configured"}
    assert composio_actions.send_offer_email({"name": "A", "email": "a@a"}, conn=memconn) == expected
    assert composio_actions.block_calendar_for_leave(
        {"employee_name": "A", "start_date": "2026-05-01", "end_date": "2026-05-01"},
        conn=memconn,
    ) == expected
    assert composio_actions.upload_payslip_to_drive(
        {"file_path": "/tmp/p.pdf"}, conn=memconn
    ) == expected
    # execute_action must NOT be called when not configured.
    assert calls == []


def test_actions_wrap_composio_errors(memconn, monkeypatch):
    monkeypatch.setattr(composio_client, "is_configured", lambda conn: True)

    def boom(conn, action_slug, params):
        raise composio_client.ComposioError("bad gateway", status=502)

    monkeypatch.setattr(composio_client, "execute_action", boom)

    out = composio_actions.send_offer_email(
        {"name": "X", "email": "x@x"}, conn=memconn
    )
    assert out["ok"] is False
    assert "bad gateway" in out["error"]
    # No 'skipped' key — this is a real error, not a skip.
    assert "skipped" not in out
