"""Smoke test for hrkit.modules.onboarding.

Covers the happy path: create an employee, create an onboarding task for
that employee, transition it ``pending -> in_progress -> done``, and assert
``completed_at`` is populated when ``done`` is reached.
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


def test_onboarding_create_transition_done(conn):
    onboarding = importlib.import_module("hrkit.modules.onboarding")

    emp_id = _make_employee(conn, "E001", "Asha Nair", "asha@example.com")
    owner_id = _make_employee(conn, "M001", "Riya Manager", "riya@example.com")

    task_id = onboarding.create_row(conn, {
        "employee_id": emp_id,
        "title": "Issue laptop",
        "owner_id": owner_id,
        "due_date": "2026-05-01",
        "notes": "16GB MacBook",
    })
    assert task_id > 0

    rows = onboarding.list_rows(conn)
    assert len(rows) == 1
    assert rows[0]["title"] == "Issue laptop"
    assert rows[0]["status"] == "pending"
    assert rows[0]["employee"] == "Asha Nair"
    assert rows[0]["owner"] == "Riya Manager"
    assert rows[0]["completed_at"] == ""

    # pending -> in_progress
    started = onboarding.transition(conn, task_id, "in_progress")
    assert started["status"] == "in_progress"
    assert started["completed_at"] == ""

    # in_progress -> done sets completed_at
    finished = onboarding.transition(conn, task_id, "done")
    assert finished["status"] == "done"
    assert finished["completed_at"], "completed_at must be set on done transition"
    # IST timestamps end with +0530 (no colon when produced by strftime %z).
    assert finished["completed_at"].endswith("+0530")

    # delete and confirm empty list
    onboarding.delete_row(conn, task_id)
    assert onboarding.list_rows(conn) == []


def test_onboarding_module_shape():
    onboarding = importlib.import_module("hrkit.modules.onboarding")
    assert onboarding.MODULE["name"] == "onboarding"
    assert "ensure_schema" in onboarding.MODULE
    assert "routes" in onboarding.MODULE
    assert "cli" in onboarding.MODULE
