"""Smoke test for the attendance module (Wave 1, Agent #8).

Happy path:
1. Apply schema (via migration runner if available, else load SQL directly).
2. Insert an employee row.
3. Create an attendance row, list it, update check_out, delete it.
"""
from __future__ import annotations

import importlib
import pkgutil
import sqlite3

import pytest


def _apply_schema(conn: sqlite3.Connection) -> None:
    try:
        runner = importlib.import_module("hrkit.migration_runner")
    except ImportError:
        runner = None
    if runner is not None and hasattr(runner, "apply_all"):
        runner.apply_all(conn)
        return
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
def att_mod():
    return importlib.import_module("hrkit.modules.attendance")


def _insert_employee(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("E100", "Carol Test", "carol@example.com"),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_attendance_module_metadata(att_mod):
    """MODULE dict shape per AGENTS_SPEC.md Section 1."""
    m = att_mod.MODULE
    assert m["name"] == "attendance"
    assert m["label"] == "Attendance"
    assert callable(m["ensure_schema"])
    assert "GET" in m["routes"] and "POST" in m["routes"] and "DELETE" in m["routes"]
    att_mod.ensure_schema(sqlite3.connect(":memory:"))


def test_attendance_crud_happy_path(conn, att_mod):
    """Create + list + update check_out + delete."""
    emp_id = _insert_employee(conn)

    # 1. Create with both check_in / check_out -> hours_minor auto-calc.
    row_id = att_mod.create_attendance(
        conn,
        employee_id=emp_id,
        date="2026-04-25",
        check_in="09:00",
        check_out="17:30",
        status="present",
        notes="On site",
    )
    assert row_id > 0

    # hours_minor is stored in *minutes*: 09:00 -> 17:30 = 510 minutes.
    db_row = conn.execute(
        "SELECT hours_minor, status, check_in, check_out FROM attendance "
        "WHERE id = ?", (row_id,),
    ).fetchone()
    assert db_row["hours_minor"] == 510
    assert db_row["status"] == "present"

    # 2. List returns it (filtered by employee + month).
    rows = att_mod.list_attendance(
        conn, employee_id=emp_id, month="2026-04",
    )
    assert len(rows) == 1
    assert rows[0]["id"] == row_id
    assert rows[0]["employee_name"] == "Carol Test"
    assert rows[0]["hours_minor"] == 510

    # Filter by a different month returns nothing.
    assert att_mod.list_attendance(conn, month="2026-03") == []

    # 3. Update check_out -> hours_minor recomputes.
    changed = att_mod.update_attendance(conn, row_id, check_out="18:00")
    assert changed == 1
    db_row = conn.execute(
        "SELECT hours_minor, check_out FROM attendance WHERE id = ?", (row_id,),
    ).fetchone()
    assert db_row["check_out"] == "18:00"
    assert db_row["hours_minor"] == 540  # 09:00 -> 18:00 = 9h = 540 min

    # 4. Delete the row.
    assert att_mod.delete_attendance(conn, row_id) is True
    assert att_mod.list_attendance(conn) == []


def test_attendance_create_without_times_yields_zero_minutes(conn, att_mod):
    """Status-only rows (e.g. 'leave') have hours_minor = 0."""
    emp_id = _insert_employee(conn)
    row_id = att_mod.create_attendance(
        conn,
        employee_id=emp_id,
        date="2026-04-26",
        status="leave",
    )
    db_row = conn.execute(
        "SELECT hours_minor, status FROM attendance WHERE id = ?", (row_id,),
    ).fetchone()
    assert db_row["hours_minor"] == 0
    assert db_row["status"] == "leave"


def test_attendance_invalid_status_rejected(conn, att_mod):
    """The module-level validator rejects unknown statuses before SQLite does."""
    emp_id = _insert_employee(conn)
    with pytest.raises(ValueError):
        att_mod.create_attendance(
            conn,
            employee_id=emp_id,
            date="2026-04-27",
            status="not_a_real_status",
        )


def test_calc_minutes_handles_bad_input(att_mod):
    """Helper does not raise on missing / reversed inputs."""
    assert att_mod._calc_minutes("", "10:00") == 0
    assert att_mod._calc_minutes("10:00", "") == 0
    assert att_mod._calc_minutes("18:00", "09:00") == 0
    assert att_mod._calc_minutes("09:00", "10:30") == 90
