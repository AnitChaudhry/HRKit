"""Smoke test for hrkit.modules.payroll.

Creates employees, a payroll_run, generates payslips, asserts the count
matches the active employee count, then processes the run.
"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Use migration_runner.apply_all when available, else load the SQL file."""
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


def _add_employee(
    conn: sqlite3.Connection,
    *,
    code: str,
    name: str,
    email: str,
    salary_minor: int,
    status: str = "active",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO employee(employee_code, full_name, email, status, salary_minor)
        VALUES (?, ?, ?, ?, ?)
        """,
        (code, name, email, status, salary_minor),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_payroll_module_exposes_module_dict():
    payroll = importlib.import_module("hrkit.modules.payroll")
    assert payroll.MODULE["name"] == "payroll"
    assert payroll.MODULE["label"] == "Payroll"
    assert callable(payroll.MODULE["ensure_schema"])
    assert "GET" in payroll.MODULE["routes"]
    assert "POST" in payroll.MODULE["routes"]


def test_payroll_full_flow(conn):
    payroll = importlib.import_module("hrkit.modules.payroll")

    # ---- arrange: 3 active + 1 exited employee -----------------------------
    _add_employee(conn, code="E001", name="Alice",
                  email="alice@example.com", salary_minor=5_000_000)
    _add_employee(conn, code="E002", name="Bob",
                  email="bob@example.com", salary_minor=4_500_000)
    _add_employee(conn, code="E003", name="Cara",
                  email="cara@example.com", salary_minor=6_200_000)
    _add_employee(conn, code="E004", name="Dan", email="dan@example.com",
                  salary_minor=3_000_000, status="exited")

    active = conn.execute(
        "SELECT COUNT(*) AS n FROM employee WHERE status = 'active'"
    ).fetchone()["n"]
    assert active == 3

    # ---- create a payroll_run ---------------------------------------------
    run_id = payroll.create_run(conn, period="2026-04", notes="April salaries")
    assert isinstance(run_id, int) and run_id > 0

    run = payroll.get_run(conn, run_id)
    assert run["period"] == "2026-04"
    assert run["status"] == "draft"

    # bad period rejected
    with pytest.raises(ValueError):
        payroll.create_run(conn, period="2026-13")

    # ---- generate payslips -------------------------------------------------
    inserted = payroll.generate_payslips(conn, run_id)
    assert inserted == active  # only active employees

    slips = payroll.list_payslips(conn, run_id)
    assert len(slips) == active

    by_name = {s["employee_name"]: s for s in slips}
    assert by_name["Alice"]["gross_minor"] == 5_000_000
    assert by_name["Alice"]["net_minor"] == 5_000_000
    assert by_name["Bob"]["gross_minor"] == 4_500_000
    assert "Dan" not in by_name  # exited

    # second generate is idempotent (UNIQUE constraint protects)
    inserted_again = payroll.generate_payslips(conn, run_id)
    assert inserted_again == 0
    assert len(payroll.list_payslips(conn, run_id)) == active

    # ---- process the run ---------------------------------------------------
    processed = payroll.process_run(conn, run_id)
    assert processed["status"] == "processed"
    assert processed["processed_at"]  # IST timestamp written

    runs = payroll.list_runs(conn)
    assert any(r["id"] == run_id and r["status"] == "processed"
               and r["employee_count"] == active for r in runs)

    # ---- payslip detail + components_json ----------------------------------
    one_slip_id = slips[0]["id"]
    detail = payroll.get_payslip(conn, one_slip_id)
    assert detail is not None
    assert detail["payroll_period"] == "2026-04"
    assert detail["payroll_status"] == "processed"

    # ---- delete the run cleans up payslips (FK CASCADE) --------------------
    payroll.delete_run(conn, run_id)
    leftover = conn.execute(
        "SELECT COUNT(*) AS n FROM payslip WHERE payroll_run_id = ?", (run_id,)
    ).fetchone()["n"]
    assert leftover == 0


def test_money_formatter():
    payroll = importlib.import_module("hrkit.modules.payroll")
    assert payroll._money(0) == "₹0.00"
    assert payroll._money(12345) == "₹123.45"
    assert payroll._money(5_000_000) == "₹50000.00"
