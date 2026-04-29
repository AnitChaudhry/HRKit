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


class _FakeHandler:
    def __init__(self, conn: sqlite3.Connection, path: str) -> None:
        self.conn = conn
        self.path = path
        self.html_responses: list[tuple[int, str]] = []

    def _html(self, code: int, body: str) -> None:
        self.html_responses.append((code, body))


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


def test_dashboard_rows_filter_and_csv(conn):
    perf = importlib.import_module("hrkit.modules.performance")
    employee_id = _add_employee(conn, code="E400", name="Helen",
                                email="helen@example.com")
    reviewer_id = _add_employee(conn, code="E401", name="Ishan",
                                email="ishan@example.com")

    april_review = perf.create_review(
        conn,
        employee_id=employee_id,
        cycle="2026-04",
        reviewer_id=reviewer_id,
        comments="Strong delivery",
        score=8.5,
    )
    perf.transition(conn, april_review, "submitted")
    conn.execute(
        "UPDATE performance_review SET submitted_at = ?, created = ? WHERE id = ?",
        ("2026-04-30T17:00:00+05:30", "2026-04-29T09:00:00+05:30", april_review),
    )

    may_review = perf.create_review(
        conn,
        employee_id=employee_id,
        cycle="2026-05",
        reviewer_id=reviewer_id,
        comments="Needs more coaching",
        score=6.0,
    )
    conn.execute(
        "UPDATE performance_review SET created = ? WHERE id = ?",
        ("2026-05-10T09:00:00+05:30", may_review),
    )
    conn.commit()

    rows = perf.list_dashboard_rows(
        conn,
        date_from="2026-04-01",
        date_to="2026-04-30",
        status="submitted",
    )
    assert [row["id"] for row in rows] == [april_review]
    assert rows[0]["review_date"] == "2026-04-30"

    summary = perf.summarize_dashboard(rows)
    assert summary["total_reviews"] == 1
    assert summary["employees_covered"] == 1
    assert summary["avg_score"] == pytest.approx(8.5)

    csv_text = perf.build_dashboard_csv(rows)
    assert "employee_code,employee_name,department" in csv_text
    assert "E400,Helen" in csv_text
    assert "2026-04-30" in csv_text


def test_dashboard_view_renders_export_link(conn):
    perf = importlib.import_module("hrkit.modules.performance")
    employee_id = _add_employee(conn, code="E500", name="Jaya",
                                email="jaya@example.com")
    review_id = perf.create_review(conn, employee_id=employee_id, cycle="2026-04", score=9)
    perf.transition(conn, review_id, "submitted")
    conn.execute(
        "UPDATE performance_review SET submitted_at = ?, created = ? WHERE id = ?",
        ("2026-04-25T17:00:00+05:30", "2026-04-24T09:00:00+05:30", review_id),
    )
    conn.commit()

    h = _FakeHandler(
        conn,
        "/m/performance/dashboard?date_from=2026-04-01&date_to=2026-04-30&status=submitted",
    )
    perf.dashboard_view(h)
    code, body = h.html_responses[0]
    assert code == 200
    assert "Performance dashboard" in body
    assert "/api/m/performance/dashboard/export.csv?" in body
    assert "Build dashboard" in body


def test_detail_view_only_edits_supported_fields_and_rubric(conn):
    perf = importlib.import_module("hrkit.modules.performance")
    employee_id = _add_employee(conn, code="E600", name="Kavya",
                                email="kavya@example.com")
    reviewer_id = _add_employee(conn, code="E601", name="Liam",
                                email="liam@example.com")
    review_id = perf.create_review(
        conn,
        employee_id=employee_id,
        cycle="2026-04",
        reviewer_id=reviewer_id,
        rubric_json=json.dumps({"delivery": 4}),
        comments="Good month",
        score=8,
    )

    h = _FakeHandler(conn, f"/m/performance/{review_id}")
    perf.detail_view(h, review_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "Save rubric" in body
    assert 'id="rubric-json"' in body
    assert 'name="cycle"' in body
    assert 'name="score"' in body
    assert 'name="comments"' in body
    assert 'name="employee"' not in body
    assert 'name="reviewer"' not in body
    assert 'name="status"' not in body
