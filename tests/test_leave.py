"""Smoke test for the leave module (Wave 1, Agent #8).

Happy path:
1. Apply schema (via Agent 4's migration runner if available, otherwise
   load the migration SQL directly from package data).
2. Insert a leave_type and a stub employee row.
3. Submit a leave_request.
4. Approve it.
5. Assert the listing returns one row with status='approved'.
"""
from __future__ import annotations

import importlib
import pkgutil
import sqlite3

import pytest


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the HR schema using whichever bootstrap path is available."""
    try:  # Preferred: Agent 4's runner.
        runner = importlib.import_module("hrkit.migration_runner")
    except ImportError:
        runner = None
    if runner is not None and hasattr(runner, "apply_all"):
        runner.apply_all(conn)
        return
    # Fallback: load the SQL file directly from the migrations package.
    sql_bytes = pkgutil.get_data(
        "hrkit.migrations", "001_full_hr_schema.sql"
    )
    if sql_bytes is None:
        pytest.skip("waits for Wave 2 integration: migration SQL not available")
    conn.executescript(sql_bytes.decode("utf-8"))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    _apply_schema(c)
    yield c
    c.close()


@pytest.fixture
def leave_mod():
    return importlib.import_module("hrkit.modules.leave")


def _insert_employee(conn: sqlite3.Connection, code: str = "E001",
                     name: str = "Alice Example",
                     email: str = "alice@example.com") -> int:
    cur = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        (code, name, email),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_leave_module_metadata(leave_mod):
    """MODULE dict shape per AGENTS_SPEC.md Section 1."""
    m = leave_mod.MODULE
    assert m["name"] == "leave"
    assert m["label"] == "Leave"
    assert callable(m["ensure_schema"])
    assert "GET" in m["routes"] and "POST" in m["routes"] and "DELETE" in m["routes"]
    # ensure_schema is a no-op (does not raise).
    leave_mod.ensure_schema(sqlite3.connect(":memory:"))


def test_leave_request_happy_path(conn, leave_mod):
    """Create leave_type + employee, submit a request, approve it, list it."""
    # 1. Leave type.
    lt_id = leave_mod.create_leave_type(
        conn, name="Casual", code="CL", max_days_per_year=12, paid=1,
    )
    assert lt_id > 0
    types = leave_mod.list_types(conn)
    assert len(types) == 1
    assert types[0]["name"] == "Casual"
    assert types[0]["code"] == "CL"
    assert int(types[0]["paid"]) == 1

    # 2. Employee (insert directly per spec).
    emp_id = _insert_employee(conn)

    # 3. Submit a leave_request.
    req_id = leave_mod.create_leave_request(
        conn,
        employee_id=emp_id,
        leave_type_id=lt_id,
        start_date="2026-05-01",
        end_date="2026-05-03",
        reason="Family wedding",
    )
    assert req_id > 0

    # Days auto-calculated as inclusive day count (3 days).
    row = conn.execute(
        "SELECT days, status, reason FROM leave_request WHERE id = ?",
        (req_id,),
    ).fetchone()
    assert row["days"] == 3
    assert row["status"] == "pending"
    assert row["reason"] == "Family wedding"

    # The pending request shows up in a filtered list.
    pending = leave_mod.list_requests(conn, status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] == req_id

    # 4. Approve it.
    assert leave_mod.set_status(conn, req_id, status="approved") is True

    # 5. Listing approved returns the same row.
    approved = leave_mod.list_requests(conn, status="approved")
    assert len(approved) == 1
    assert approved[0]["id"] == req_id
    assert approved[0]["status"] == "approved"
    assert approved[0]["employee_name"] == "Alice Example"
    assert approved[0]["leave_type_name"] == "Casual"

    # No pending rows remain.
    assert leave_mod.list_requests(conn, status="pending") == []


def test_leave_request_reject_and_delete(conn, leave_mod):
    """Reject + delete round-trip."""
    lt_id = leave_mod.create_leave_type(conn, name="Sick", code="SL")
    emp_id = _insert_employee(conn, code="E002", name="Bob",
                              email="bob@example.com")
    req_id = leave_mod.create_leave_request(
        conn, employee_id=emp_id, leave_type_id=lt_id,
        start_date="2026-06-10", end_date="2026-06-10",
        reason="Flu",
    )
    # Same-day request is 1 day.
    row = conn.execute(
        "SELECT days FROM leave_request WHERE id = ?", (req_id,),
    ).fetchone()
    assert row["days"] == 1

    assert leave_mod.set_status(conn, req_id, status="rejected") is True
    assert leave_mod.set_status(conn, req_id, status="bogus") is False

    assert leave_mod.delete_request(conn, req_id) is True
    assert leave_mod.list_requests(conn) == []


def test_invalid_date_range_yields_zero_days(leave_mod):
    """end_date < start_date should result in days=0, not a crash."""
    assert leave_mod._calc_days("2026-05-05", "2026-05-01") == 0
    assert leave_mod._calc_days("", "2026-05-01") == 0
    assert leave_mod._calc_days("2026-05-01", "2026-05-01") == 1
