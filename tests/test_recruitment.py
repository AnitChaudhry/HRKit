"""Smoke test for hrkit.modules.recruitment.

Happy path:
    insert candidate (status=applied) -> move to interview -> move to hired
    -> promote -> assert employee row exists with matching email.
"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so ``hrkit`` imports work
# regardless of how pytest is invoked.
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        from hrkit.migration_runner import apply_all
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"migration_runner unavailable ({exc})")
    apply_all(c)
    yield c
    c.close()


def _import_module():
    try:
        return importlib.import_module("hrkit.modules.recruitment")
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"recruitment module unavailable ({exc})")


def test_module_dict_shape(conn):
    mod = _import_module()
    assert isinstance(mod.MODULE, dict)
    assert mod.MODULE["name"] == "recruitment"
    assert mod.MODULE["label"]
    assert callable(mod.MODULE["ensure_schema"])
    assert "GET" in mod.MODULE["routes"]
    assert "POST" in mod.MODULE["routes"]
    assert isinstance(mod.MODULE["cli"], list)
    # ensure_schema must be a no-op (recruitment_candidate is in 001).
    mod.MODULE["ensure_schema"](conn)


def test_create_move_promote_happy_path(conn):
    mod = _import_module()

    candidate_id = mod.create_row(conn, {
        "name": "Asha Nair",
        "email": "asha@example.com",
        "phone": "+91-9000000000",
        "source": "linkedin",
        "applied_at": "2026-04-20",
    })
    assert isinstance(candidate_id, int) and candidate_id > 0

    # Status defaults to 'applied' when not supplied.
    row = mod.get_row(conn, candidate_id)
    assert row is not None
    assert row["status"] == "applied"
    assert row["name"] == "Asha Nair"
    assert row["email"] == "asha@example.com"
    assert row["applied_at"] == "2026-04-20"

    # Listing should include this candidate, and status filter should narrow.
    listed = mod.list_rows(conn)
    assert any(r["id"] == candidate_id for r in listed)
    listed_applied = mod.list_rows(conn, status="applied")
    assert any(r["id"] == candidate_id for r in listed_applied)
    listed_hired = mod.list_rows(conn, status="hired")
    assert all(r["id"] != candidate_id for r in listed_hired)

    # Move applied -> interview.
    moved = mod.move_status(conn, candidate_id, "interview")
    assert moved["status"] == "interview"

    # Cannot promote until hired.
    with pytest.raises(ValueError):
        mod.promote_to_employee(conn, candidate_id)

    # Move interview -> hired.
    moved = mod.move_status(conn, candidate_id, "hired")
    assert moved["status"] == "hired"

    # Invalid status transition raises.
    with pytest.raises(ValueError):
        mod.move_status(conn, candidate_id, "not-a-real-status")

    # Promote: a new employee row must exist with matching email + active status.
    new_employee_id = mod.promote_to_employee(conn, candidate_id)
    assert isinstance(new_employee_id, int) and new_employee_id > 0

    emp_row = conn.execute(
        "SELECT id, employee_code, full_name, email, status, hire_date "
        "FROM employee WHERE id = ?",
        (new_employee_id,),
    ).fetchone()
    assert emp_row is not None
    assert emp_row["email"] == "asha@example.com"
    assert emp_row["full_name"] == "Asha Nair"
    assert emp_row["status"] == "active"
    assert emp_row["hire_date"]  # set to today
    assert emp_row["employee_code"]  # auto-generated, non-empty


def test_create_validates_required_name(conn):
    mod = _import_module()
    with pytest.raises(ValueError):
        mod.create_row(conn, {"name": "", "email": "x@example.com"})


def test_create_rejects_unknown_status(conn):
    mod = _import_module()
    with pytest.raises(ValueError):
        mod.create_row(conn, {"name": "X", "status": "bogus"})


def test_promote_requires_existing_candidate(conn):
    mod = _import_module()
    with pytest.raises(LookupError):
        mod.promote_to_employee(conn, 99999)
