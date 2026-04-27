"""Tests for the AI agent's destructive-action gate + audit trail.

Two guardrails proved here:

1. ``query_records`` with ``op='delete'`` requires ``args.confirm=true``.
   First call returns a ``confirm required:`` reply; the underlying row is
   left intact. Second call with ``confirm=true`` actually deletes.
2. Every successful create / update / delete from the agent (and every
   workspace file write / Composio dispatch) is logged in ``audit_log``
   with ``actor='ai'`` so the user can audit the agent's work.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from hrkit import chat
from hrkit.migration_runner import apply_all
from hrkit.modules import audit_log


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    apply_all(c)
    # Seed one department + role + employee so we have something to mutate.
    c.execute("INSERT INTO department (name) VALUES ('Eng')")
    c.execute("INSERT INTO role (title, department_id) VALUES ('Engineer', 1)")
    c.execute(
        "INSERT INTO employee (employee_code, full_name, email, department_id, "
        "role_id) VALUES ('E-001', 'Alice', 'a@x.com', 1, 1)"
    )
    c.commit()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Destructive-action gate
# ---------------------------------------------------------------------------
def test_delete_without_confirm_raises_and_keeps_row(conn):
    """First-pass delete returns ConfirmationRequired and the row stays."""
    with pytest.raises(chat.ConfirmationRequired):
        chat._dispatch(conn, "employee", "delete", {"id": 1})
    row = conn.execute("SELECT id FROM employee WHERE id = 1").fetchone()
    assert row is not None, "employee should NOT have been deleted yet"


def test_delete_with_confirm_actually_deletes(conn):
    chat._dispatch(conn, "employee", "delete", {"id": 1, "confirm": True})
    row = conn.execute("SELECT id FROM employee WHERE id = 1").fetchone()
    assert row is None


def test_delete_confirm_accepts_truthy_strings(conn):
    """The agent might pass 'true' as a JSON string instead of a bool."""
    chat._dispatch(conn, "employee", "delete", {"id": 1, "confirm": "true"})
    row = conn.execute("SELECT id FROM employee WHERE id = 1").fetchone()
    assert row is None


def test_query_records_returns_confirm_message_not_exception(conn):
    """The tool wrapper catches ConfirmationRequired and returns a string."""
    tool = chat._build_query_tool(conn)
    out = tool("employee", "delete", {"id": 1})
    assert out.startswith("confirm required:")
    assert "args.confirm=true" in out


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_create_via_dispatch_records_audit_row(conn):
    new_id = chat._dispatch(conn, "department", "create",
                             {"data": {"name": "Sales"}})
    rows = audit_log.list_rows(conn, entity_type="department")
    actions = {r["action"]: r for r in rows}
    assert "department.create" in actions, actions
    entry = actions["department.create"]
    assert entry["actor"] == "ai"
    assert int(entry["entity_id"]) == int(new_id)
    body = json.loads(entry["changes_json"])
    assert body["data"]["name"] == "Sales"
    assert body["result"]["id"] == new_id


def test_update_via_dispatch_records_audit_row(conn):
    chat._dispatch(conn, "employee", "update",
                    {"id": 1, "data": {"full_name": "Alice Smith"}})
    rows = audit_log.list_rows(conn, entity_type="employee")
    assert any(r["action"] == "employee.update" and r["actor"] == "ai" for r in rows)


def test_delete_with_confirm_records_audit_row(conn):
    # We need a deletable child of employee since employee has FK fanout.
    chat._dispatch(conn, "department", "create",
                    {"data": {"name": "Marketing"}})
    new_id = conn.execute(
        "SELECT id FROM department WHERE name = 'Marketing'"
    ).fetchone()["id"]
    chat._dispatch(conn, "department", "delete",
                    {"id": new_id, "confirm": True})
    rows = audit_log.list_rows(conn, entity_type="department")
    deletes = [r for r in rows if r["action"] == "department.delete"]
    assert deletes and deletes[0]["actor"] == "ai"
    assert int(deletes[0]["entity_id"]) == int(new_id)


def test_workspace_fs_writes_record_audit_rows(conn, tmp_path):
    tools = chat._build_workspace_fs_tools(tmp_path, conn)
    by_name = {t.__name__: t for t in tools}
    by_name["write_file"]("reports/q3.html", "<h1>headcount</h1>")
    by_name["append_file"]("reports/q3.html", "\n<p>2026</p>")
    by_name["make_folder"]("exports/csvs")

    rows = audit_log.list_rows(conn, entity_type="workspace")
    actions = sorted({r["action"] for r in rows})
    assert "workspace.write_file" in actions
    assert "workspace.append_file" in actions
    assert "workspace.make_folder" in actions
    write_row = next(r for r in rows if r["action"] == "workspace.write_file")
    body = json.loads(write_row["changes_json"])
    assert body["rel_path"] == "reports/q3.html"
    assert body["bytes"] > 0


def test_failed_writes_do_not_audit(conn, tmp_path):
    """Path-traversal attempts produce error strings — no audit emitted."""
    tools = chat._build_workspace_fs_tools(tmp_path, conn)
    by_name = {t.__name__: t for t in tools}
    out = by_name["write_file"]("../escape.txt", "leak")
    assert out.startswith("error:")
    rows = audit_log.list_rows(conn, entity_type="workspace")
    assert not rows, "no audit entry should be recorded for a refused write"
