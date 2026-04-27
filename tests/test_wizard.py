"""Tests for hrkit.wizard — needs_wizard detection and step handlers."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from hrkit import wizard


# Ensure a settings table exists (it's part of the legacy db.SCHEMA but the
# test conftest fallback only creates the HR module tables).
def _ensure_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Fake handler — tiny BaseHTTPRequestHandler stand-in
# ---------------------------------------------------------------------------
class _FakeServer:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.server = _FakeServer(conn)
        self.json_responses: list[tuple[int, Any]] = []

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))


# ---------------------------------------------------------------------------
# needs_wizard
# ---------------------------------------------------------------------------
def test_needs_wizard_true_on_empty_db(conn):
    _ensure_settings_table(conn)
    assert wizard.needs_wizard(conn) is True


def test_needs_wizard_false_after_employee(conn):
    _ensure_settings_table(conn)
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-1", "Already Set", "set@example.com"),
    )
    conn.commit()
    assert wizard.needs_wizard(conn) is False


def test_needs_wizard_false_after_setting(conn):
    _ensure_settings_table(conn)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        ("APP_NAME", "Already Configured"),
    )
    conn.commit()
    assert wizard.needs_wizard(conn) is False


# ---------------------------------------------------------------------------
# render_wizard_page
# ---------------------------------------------------------------------------
def test_render_wizard_page_includes_5_steps(conn):
    _ensure_settings_table(conn)
    html = wizard.render_wizard_page(conn)
    assert 'data-step="1"' in html
    assert 'data-step="2"' in html
    assert 'data-step="3"' in html
    assert 'data-step="4"' in html
    assert 'data-step="5"' in html
    # Modules step renders the picker grid with locked core rows.
    assert "wm-grid" in html
    assert 'data-slug="employee"' in html
    assert 'data-slug="recruitment"' in html
    # Final redirect target.
    assert "/m/employee" in html


# ---------------------------------------------------------------------------
# handle_wizard_step — each step writes the right table
# ---------------------------------------------------------------------------
def test_step1_sets_app_name(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {"step": 1, "data": {"app_name": "Acme HR"}})
    code, payload = h.json_responses[0]
    assert code == 200 and payload["ok"] is True
    assert payload["next_step"] == 2
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", ("APP_NAME",)
    ).fetchone()
    assert row is not None
    assert row["value"] == "Acme HR"


def test_step2_skips_when_requested(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {"step": 2, "data": {"skip": True}})
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload["next_step"] == 3
    # Nothing written to settings.
    rows = conn.execute(
        "SELECT key FROM settings WHERE key IN ('AI_PROVIDER','AI_API_KEY')"
    ).fetchall()
    assert rows == []


def test_step2_writes_provider_key_and_model(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 2,
        "data": {
            "ai_provider": "openrouter",
            "ai_api_key": "sk-or-test",
            "ai_model": "meta-llama/llama-3.3-70b-instruct:free",
        },
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload["next_step"] == 3
    rows = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM settings"
    ).fetchall()}
    assert rows.get("AI_PROVIDER") == "openrouter"
    assert rows.get("AI_API_KEY") == "sk-or-test"
    assert rows.get("AI_MODEL") == "meta-llama/llama-3.3-70b-instruct:free"


def test_step2_rejects_missing_model(conn):
    """Onboarding without picking a model used to silently use the OpenRouter
    free default — broken for Upfyn users. Now we require model on Next."""
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 2,
        "data": {"ai_provider": "openrouter", "ai_api_key": "sk-or-test"},
    })
    code, payload = h.json_responses[0]
    assert code == 400
    assert payload["ok"] is False
    assert "model" in payload["error"].lower()


def test_step2_rejects_missing_key(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 2,
        "data": {
            "ai_provider": "openrouter",
            "ai_model": "meta-llama/llama-3.3-70b-instruct:free",
        },
    })
    code, payload = h.json_responses[0]
    assert code == 400
    assert "API key" in payload["error"]


def test_step3_skip_leaves_modules_default(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {"step": 3, "data": {"skip": True}})
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload["next_step"] == 4
    # Skip should not write ENABLED_MODULES to the settings table.
    rows = conn.execute(
        "SELECT key FROM settings WHERE key = 'ENABLED_MODULES'"
    ).fetchall()
    assert rows == []


def test_step3_persists_module_selection(conn, tmp_path, monkeypatch):
    _ensure_settings_table(conn)
    # Point the workspace finder at an isolated dir so config.json doesn't
    # leak across tests.
    (tmp_path / "getset.md").write_text("type: workspace\n")
    monkeypatch.setenv("GETSET_ROOT", str(tmp_path))

    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 3,
        "data": {"enabled_modules": ["leave", "payroll"]},
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload["next_step"] == 4
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'ENABLED_MODULES'"
    ).fetchone()
    assert row is not None
    import json
    saved = json.loads(row["value"])
    # Always-on core gets forced in, plus the user's two extras.
    assert "department" in saved
    assert "employee" in saved
    assert "role" in saved
    assert "leave" in saved
    assert "payroll" in saved
    # Recruitment was not chosen, so it must NOT be in the list.
    assert "recruitment" not in saved


def test_step4_creates_department_and_returns_id(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 4, "data": {"name": "Engineering", "code": "ENG"},
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload["next_step"] == 5
    new_id = payload["department_id"]
    row = conn.execute(
        "SELECT name, code FROM department WHERE id = ?", (new_id,)
    ).fetchone()
    assert row["name"] == "Engineering"
    assert row["code"] == "ENG"


def test_step5_creates_employee_with_dept(conn):
    _ensure_settings_table(conn)
    dept_id = conn.execute(
        "INSERT INTO department (name) VALUES (?)", ("Sales",)
    ).lastrowid
    conn.commit()
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 5,
        "data": {
            "employee_code": "EMP-100",
            "full_name": "Sara Sales",
            "email": "sara@example.com",
            "department_id": dept_id,
        },
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True
    assert payload.get("done") is True
    row = conn.execute(
        "SELECT employee_code, full_name, email, department_id"
        " FROM employee WHERE id = ?", (payload["employee_id"],),
    ).fetchone()
    assert row["employee_code"] == "EMP-100"
    assert row["full_name"] == "Sara Sales"
    assert row["email"] == "sara@example.com"
    assert row["department_id"] == dept_id


def test_step1_rejects_blank_name(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {"step": 1, "data": {"app_name": "  "}})
    code, payload = h.json_responses[0]
    assert code == 400
    assert payload["ok"] is False


def test_handle_unknown_step(conn):
    _ensure_settings_table(conn)
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {"step": 99, "data": {}})
    code, payload = h.json_responses[0]
    assert code == 400
    assert "unknown" in payload["error"]
