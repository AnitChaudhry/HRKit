"""Smoke test for hrkit.modules.exit_record.

Covers the happy path: create an active employee, create an exit record,
and assert that ``employee.status`` is flipped to ``'exited'`` in the same
transaction. Also exercises the ``UNIQUE(employee_id)`` guard.
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest

try:
    from hrkit.migration_runner import apply_all
except ImportError as exc:  # pragma: no cover - environment-dependent
    pytest.skip(
        f"hrkit.migration_runner unavailable ({exc})",
        allow_module_level=True,
    )


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    apply_all(c)
    yield c
    c.close()


def _make_employee(conn: sqlite3.Connection, code: str, name: str, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        (code, name, email),
    )
    conn.commit()
    return int(cur.lastrowid)


def _employee_status(conn: sqlite3.Connection, emp_id: int) -> str:
    row = conn.execute(
        "SELECT status FROM employee WHERE id = ?", (emp_id,)
    ).fetchone()
    assert row is not None
    return row["status"]


def test_exit_record_flips_employee_status(conn):
    exit_record = importlib.import_module("hrkit.modules.exit_record")

    emp_id = _make_employee(conn, "E100", "Vikram Bose", "vikram@example.com")
    assert _employee_status(conn, emp_id) == "active"

    rec_id = exit_record.create_row(conn, {
        "employee_id": emp_id,
        "last_working_day": "2026-05-31",
        "reason": "Higher studies",
        "exit_type": "resignation",
        "notice_period_days": 30,
        "knowledge_transfer_status": "in_progress",
        "asset_returned": True,
        "exit_interview_done": False,
    })
    assert rec_id > 0

    # Employee must now be exited.
    assert _employee_status(conn, emp_id) == "exited"

    rows = exit_record.list_rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["employee"] == "Vikram Bose"
    assert row["exit_type"] == "resignation"
    assert row["asset_returned"] == 1
    assert row["exit_interview_done"] == 0
    assert row["processed_at"], "processed_at should default to now (IST)"


def test_exit_record_duplicate_rejected(conn):
    exit_record = importlib.import_module("hrkit.modules.exit_record")

    emp_id = _make_employee(conn, "E101", "Maya Iyer", "maya@example.com")
    exit_record.create_row(conn, {
        "employee_id": emp_id,
        "last_working_day": "2026-06-15",
        "exit_type": "termination",
    })

    # Employee is no longer active, so a second attempt fails on the
    # active-check before even hitting the UNIQUE constraint. Either way,
    # the module must surface a clean ValueError.
    with pytest.raises(ValueError):
        exit_record.create_row(conn, {
            "employee_id": emp_id,
            "last_working_day": "2026-07-01",
            "exit_type": "resignation",
        })


def test_exit_record_module_shape():
    exit_record = importlib.import_module("hrkit.modules.exit_record")
    assert exit_record.MODULE["name"] == "exit_record"
    assert "ensure_schema" in exit_record.MODULE
    assert "routes" in exit_record.MODULE
    assert "cli" in exit_record.MODULE
