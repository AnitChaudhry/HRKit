"""Tests for hrkit.seeds — canonical sample-data loader."""

from __future__ import annotations

import sqlite3

from hrkit import seeds, wizard


# ---------------------------------------------------------------------------
# Counts on a fresh DB
# ---------------------------------------------------------------------------
def test_load_sample_data_inserts_expected_counts(conn):
    counts = seeds.load_sample_data(conn)

    assert counts["department"] == 3
    assert counts["role"] == 5
    assert counts["employee"] == 8
    assert counts["leave_type"] == 2
    assert counts["leave_request"] == 3
    assert counts["onboarding_task"] == 4
    assert counts["payroll_run"] == 1
    assert counts["payslip"] == 8
    assert counts["recruitment_candidate"] == 3


def test_load_sample_data_writes_rows(conn):
    seeds.load_sample_data(conn)

    assert conn.execute("SELECT COUNT(*) FROM department").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM role").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM employee").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM leave_type").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM leave_request").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM onboarding_task").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM payroll_run").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM payslip").fetchone()[0] == 8
    assert conn.execute(
        "SELECT COUNT(*) FROM recruitment_candidate"
    ).fetchone()[0] == 3


# ---------------------------------------------------------------------------
# Idempotence — second call inserts nothing
# ---------------------------------------------------------------------------
def test_load_sample_data_is_idempotent(conn):
    seeds.load_sample_data(conn)
    second = seeds.load_sample_data(conn)

    for table, n in second.items():
        assert n == 0, f"second seed inserted into {table}"

    # Row counts unchanged.
    assert conn.execute("SELECT COUNT(*) FROM employee").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM payslip").fetchone()[0] == 8


# ---------------------------------------------------------------------------
# Manager hierarchy + leave-request mix
# ---------------------------------------------------------------------------
def test_manager_hierarchy_is_set(conn):
    seeds.load_sample_data(conn)
    # EMP-S004 reports to EMP-S003.
    row = conn.execute(
        "SELECT m.employee_code AS mgr_code"
        " FROM employee e JOIN employee m ON m.id = e.manager_id"
        " WHERE e.employee_code = ?",
        ("EMP-S004",),
    ).fetchone()
    assert row is not None
    assert row["mgr_code"] == "EMP-S003"


def test_leave_requests_cover_all_states(conn):
    seeds.load_sample_data(conn)
    statuses = {
        r["status"]
        for r in conn.execute("SELECT status FROM leave_request").fetchall()
    }
    assert statuses == {"approved", "pending", "rejected"}


def test_recruitment_candidates_cover_pipeline(conn):
    seeds.load_sample_data(conn)
    statuses = {
        r["status"]
        for r in conn.execute(
            "SELECT status FROM recruitment_candidate"
        ).fetchall()
    }
    assert statuses == {"applied", "interview", "offer"}


# ---------------------------------------------------------------------------
# Wizard step 4 honors seed_sample_data checkbox
# ---------------------------------------------------------------------------
class _FakeServer:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.server = _FakeServer(conn)
        self.json_responses: list[tuple[int, dict]] = []

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))


def _ensure_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def test_wizard_step4_with_seed_checkbox_loads_sample_data(conn):
    _ensure_settings_table(conn)
    dept_id = conn.execute(
        "INSERT INTO department (name) VALUES (?)", ("Engineering",)
    ).lastrowid
    conn.commit()
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 4,
        "data": {
            "employee_code": "EMP-100",
            "full_name": "First Person",
            "email": "first@example.com",
            "department_id": dept_id,
            "seed_sample_data": "1",
        },
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True and payload.get("done") is True
    # Sample data was loaded on top of the wizard's first employee.
    assert payload.get("seeded", {}).get("employee") == 8
    assert conn.execute(
        "SELECT COUNT(*) FROM employee"
    ).fetchone()[0] == 9  # 1 wizard + 8 sample


def test_wizard_step4_without_seed_checkbox_skips_sample_data(conn):
    _ensure_settings_table(conn)
    dept_id = conn.execute(
        "INSERT INTO department (name) VALUES (?)", ("Engineering",)
    ).lastrowid
    conn.commit()
    h = _FakeHandler(conn)
    wizard.handle_wizard_step(h, {
        "step": 4,
        "data": {
            "employee_code": "EMP-100",
            "full_name": "First Person",
            "email": "first@example.com",
            "department_id": dept_id,
        },
    })
    code, payload = h.json_responses[0]
    assert payload["ok"] is True and payload.get("done") is True
    assert "seeded" not in payload
    assert conn.execute(
        "SELECT COUNT(*) FROM employee"
    ).fetchone()[0] == 1
