"""Smoke test for hrkit.modules.performance.

Walks a review through draft -> submitted -> acknowledged and asserts the
status flow + invalid-transition guards.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest


def _apply_schema(conn: sqlite3.Connection) -> None:
    try:
        from hrkit.migration_runner import apply_all
        apply_all(conn)
        return
    except ImportError:
        pass
    sql_path = (
        Path(__file__).resolve().parent.parent
        / "hrkit" / "migrations" / "001_full_hr_schema.sql"
    )
    conn.executescript(sql_path.read_text(encoding="utf-8"))


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        _apply_schema(c)
    except sqlite3.Error as exc:
        c.close()
        pytest.skip(f"schema unavailable: {exc}")
    yield c
    c.close()


def _add_employee(conn: sqlite3.Connection, *, code: str, name: str,
                  email: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO employee(employee_code, full_name, email, status)
        VALUES (?, ?, ?, 'active')
        """,
        (code, name, email),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_performance_module_exposes_module_dict():
    perf = importlib.import_module("hrkit.modules.performance")
    assert perf.MODULE["name"] == "performance"
    assert perf.MODULE["label"] == "Performance"
    assert callable(perf.MODULE["ensure_schema"])
    assert "GET" in perf.MODULE["routes"]
    assert "POST" in perf.MODULE["routes"]


def test_review_status_flow(conn):
    perf = importlib.import_module("hrkit.modules.performance")

    employee_id = _add_employee(conn, code="E100", name="Eve",
                                email="eve@example.com")
    reviewer_id = _add_employee(conn, code="E101", name="Mallory",
                                email="mallory@example.com")

    rubric = {"communication": 4, "delivery": 3, "ownership": 5}
    review_id = perf.create_review(
        conn,
        employee_id=employee_id,
        cycle="2026-Q1",
        reviewer_id=reviewer_id,
        rubric_json=json.dumps(rubric),
        comments="Strong quarter overall.",
        score=7.5,
    )
    assert isinstance(review_id, int) and review_id > 0

    review = perf.get_review(conn, review_id)
    assert review["status"] == "draft"
    assert review["employee_name"] == "Eve"
    assert review["reviewer_name"] == "Mallory"
    # rubric round-trips
    assert json.loads(review["rubric_json"]) == rubric

    # cannot acknowledge while still draft
    with pytest.raises(ValueError):
        perf.transition(conn, review_id, "acknowledged")

    # invalid status string
    with pytest.raises(ValueError):
        perf.transition(conn, review_id, "rejected")

    # draft -> submitted
    submitted = perf.transition(conn, review_id, "submitted")
    assert submitted["status"] == "submitted"
    assert submitted["submitted_at"]

    # cannot go back to submitted again
    with pytest.raises(ValueError):
        perf.transition(conn, review_id, "submitted")

    # submitted -> acknowledged
    ack = perf.transition(conn, review_id, "acknowledged")
    assert ack["status"] == "acknowledged"

    # cannot transition further
    with pytest.raises(ValueError):
        perf.transition(conn, review_id, "submitted")

    # list view sees the row
    listed = perf.list_reviews(conn)
    assert any(r["id"] == review_id and r["status"] == "acknowledged"
               for r in listed)


def test_create_validates_inputs(conn):
    perf = importlib.import_module("hrkit.modules.performance")
    employee_id = _add_employee(conn, code="E200", name="Frank",
                                email="frank@example.com")

    # missing cycle
    with pytest.raises(ValueError):
        perf.create_review(conn, employee_id=employee_id, cycle="")

    # missing employee_id
    with pytest.raises(ValueError):
        perf.create_review(conn, employee_id=0, cycle="2026-Q1")

    # invalid score range
    with pytest.raises(ValueError):
        perf.create_review(conn, employee_id=employee_id,
                           cycle="2026-Q1", score=11)

    # invalid rubric JSON
    with pytest.raises(ValueError):
        perf.create_review(conn, employee_id=employee_id,
                           cycle="2026-Q1", rubric_json="{not json")


def test_update_review_changes_score_and_comments(conn):
    perf = importlib.import_module("hrkit.modules.performance")
    employee_id = _add_employee(conn, code="E300", name="Grace",
                                email="grace@example.com")
    review_id = perf.create_review(conn, employee_id=employee_id,
                                   cycle="2026-Q2")
    updated = perf.update_review(conn, review_id, score=9.0,
                                 comments="Excellent work")
    assert float(updated["score"]) == pytest.approx(9.0)
    assert updated["comments"] == "Excellent work"

    perf.delete_review(conn, review_id)
    assert perf.get_review(conn, review_id) is None
