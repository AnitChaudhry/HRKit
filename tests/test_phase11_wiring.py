"""Tests for the v1.1 Tier B wiring into existing v1.0 flows.

Five integration paths exercised:

1. Payroll generates payslips and emits ``payroll_component`` rows for
   basic + computed income tax (via :mod:`tax_slab`).
2. Payroll deducts approved+disbursed salary advance EMIs and updates the
   advance ``repayment_schedule`` (flipping to ``repaid`` when remaining
   hits zero).
3. ``leave.create_leave_request`` seeds the ``approval`` queue using the
   employee's manager + an HR approver from settings.
4. ``leave.set_status('approved')`` reflects onto pending approval rows.
5. ``exit_record.create_row`` auto-runs F&F settlement and persists the
   gratuity / total / breakdown JSON onto the exit row.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest


def _apply_schema(conn: sqlite3.Connection) -> None:
    from hrkit.migration_runner import apply_all
    apply_all(conn)
    # ``settings`` lives in db.open_db(), not the migrations — create it
    # here so tests that read it (e.g. HR_APPROVER_ID) don't crash.
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS settings ("
        "  key   TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL DEFAULT ''"
        ")"
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    _apply_schema(c)
    yield c
    c.close()


def _seed_org(conn) -> dict[str, int]:
    """Create department + role + a manager employee + a regular employee."""
    conn.execute("INSERT INTO department (name) VALUES ('Engineering')")
    dept_id = conn.execute("SELECT id FROM department WHERE name = 'Engineering'").fetchone()["id"]
    conn.execute("INSERT INTO role (title, department_id) VALUES ('Engineer', ?)", (dept_id,))
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email, hire_date, salary_minor, "
        "department_id, role_id) VALUES ('M-001', 'Mgr', 'mgr@x.com', '2020-01-01', "
        "12000000, ?, ?)",
        (dept_id, role_id),
    )
    mgr_id = conn.execute("SELECT id FROM employee WHERE employee_code='M-001'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email, hire_date, salary_minor, "
        "manager_id, department_id, role_id) VALUES ('E-001', 'Alice', 'alice@x.com', "
        "'2022-04-01', 8000000, ?, ?, ?)",
        (mgr_id, dept_id, role_id),
    )
    emp_id = conn.execute("SELECT id FROM employee WHERE employee_code='E-001'").fetchone()["id"]
    conn.commit()
    return {"dept_id": dept_id, "role_id": role_id,
            "mgr_id": int(mgr_id), "emp_id": int(emp_id)}


# ---------------------------------------------------------------------------
# Payroll → tax_slab
# ---------------------------------------------------------------------------
def test_payroll_emits_components_with_tax(conn):
    payroll = importlib.import_module("hrkit.modules.payroll")
    tax_slab = importlib.import_module("hrkit.modules.tax_slab")

    org = _seed_org(conn)
    # Configure two FY26 slabs: 0–3L @ 0%, 3L+ @ 5%.
    tax_slab.create_row(conn, {
        "name": "FY26 0–3L 0%", "country": "IN", "regime": "new",
        "fy_start": "2026-04-01", "slab_min": 0, "slab_max": 300000, "rate_percent": 0,
    })
    tax_slab.create_row(conn, {
        "name": "FY26 3L+ 5%", "country": "IN", "regime": "new",
        "fy_start": "2026-04-01", "slab_min": 300000, "slab_max": 0, "rate_percent": 5,
    })

    run_id = payroll.create_run(conn, period="2026-04")
    inserted = payroll.generate_payslips(conn, run_id)
    assert inserted == 2  # mgr + alice

    # Pull alice's payslip + components.
    slip = conn.execute(
        "SELECT id, gross_minor, deductions_minor, net_minor "
        "FROM payslip WHERE employee_id = ? AND payroll_run_id = ?",
        (org["emp_id"], run_id)
    ).fetchone()
    assert slip is not None
    assert slip["gross_minor"] == 8_000_000

    # Annual income = 80,000 × 12 = 9,60,000. Above 3L slab: 5% × (9,60,000 − 3,00,000)
    # = 33,000/yr → monthly 2,750 = 2_75_000 paise.
    expected_monthly_tax_minor = round((660_000 * 5 / 100) / 12 * 100)  # 2750 rupees → 275000 paise
    assert slip["deductions_minor"] == expected_monthly_tax_minor
    assert slip["net_minor"] == 8_000_000 - expected_monthly_tax_minor

    # Components: one basic, one income_tax line.
    comps = conn.execute(
        "SELECT name, type, amount_minor FROM payroll_component "
        "WHERE payslip_id = ? ORDER BY id",
        (slip["id"],)
    ).fetchall()
    by_name = {c["name"]: c for c in comps}
    assert "basic" in by_name and by_name["basic"]["type"] == "earning"
    assert by_name["basic"]["amount_minor"] == 8_000_000
    assert "income_tax" in by_name and by_name["income_tax"]["type"] == "tax"
    assert by_name["income_tax"]["amount_minor"] == expected_monthly_tax_minor


def test_payroll_no_tax_when_no_slabs(conn):
    """Without any tax_slab rows, payroll falls back to zero tax."""
    payroll = importlib.import_module("hrkit.modules.payroll")
    org = _seed_org(conn)
    run_id = payroll.create_run(conn, period="2026-04")
    payroll.generate_payslips(conn, run_id)
    slip = conn.execute(
        "SELECT gross_minor, deductions_minor, net_minor FROM payslip "
        "WHERE employee_id = ? AND payroll_run_id = ?",
        (org["emp_id"], run_id)).fetchone()
    assert slip["deductions_minor"] == 0
    assert slip["net_minor"] == slip["gross_minor"]


# ---------------------------------------------------------------------------
# Payroll → salary_advance EMI deduction
# ---------------------------------------------------------------------------
def test_payroll_deducts_salary_advance_emi(conn):
    payroll = importlib.import_module("hrkit.modules.payroll")
    org = _seed_org(conn)

    # Insert an approved+disbursed advance with a 3-installment schedule:
    # principal 60_000 paise, EMI 20_000 paise (so it'd take 3 runs to clear).
    schedule = json.dumps({"emi_minor": 2_000_000, "remaining_minor": 6_000_000})
    conn.execute(
        "INSERT INTO salary_advance (employee_id, amount_minor, status, "
        "repayment_schedule) VALUES (?, ?, 'disbursed', ?)",
        (org["emp_id"], 6_000_000, schedule),
    )
    conn.commit()
    adv_id = conn.execute("SELECT id FROM salary_advance").fetchone()["id"]

    # Run 1: deduct first EMI.
    r1 = payroll.create_run(conn, period="2026-04")
    payroll.generate_payslips(conn, r1)
    slip1 = conn.execute(
        "SELECT id, gross_minor, deductions_minor, net_minor FROM payslip "
        "WHERE employee_id = ? AND payroll_run_id = ?",
        (org["emp_id"], r1)).fetchone()
    assert slip1["deductions_minor"] == 2_000_000  # one EMI, no tax
    assert slip1["net_minor"] == slip1["gross_minor"] - 2_000_000

    comp = conn.execute(
        "SELECT name, type, amount_minor FROM payroll_component "
        "WHERE payslip_id = ? AND name LIKE 'advance_repayment_%'",
        (slip1["id"],)).fetchone()
    assert comp is not None
    assert comp["type"] == "deduction"
    assert comp["amount_minor"] == 2_000_000

    # Schedule should now show remaining = 4_000_000.
    sched_after_r1 = json.loads(conn.execute(
        "SELECT repayment_schedule FROM salary_advance WHERE id = ?", (adv_id,)
    ).fetchone()["repayment_schedule"])
    assert sched_after_r1["remaining_minor"] == 4_000_000

    # Run 2 + 3 — clear the rest.
    r2 = payroll.create_run(conn, period="2026-05")
    payroll.generate_payslips(conn, r2)
    r3 = payroll.create_run(conn, period="2026-06")
    payroll.generate_payslips(conn, r3)

    # Final state: status = 'repaid', remaining = 0.
    final = conn.execute(
        "SELECT status, repayment_schedule FROM salary_advance WHERE id = ?", (adv_id,)
    ).fetchone()
    assert final["status"] == "repaid"
    assert json.loads(final["repayment_schedule"])["remaining_minor"] == 0

    # Run 4 — no EMI deducted (status is 'repaid' now).
    r4 = payroll.create_run(conn, period="2026-07")
    payroll.generate_payslips(conn, r4)
    slip4 = conn.execute(
        "SELECT deductions_minor FROM payslip WHERE employee_id=? AND payroll_run_id=?",
        (org["emp_id"], r4)).fetchone()
    assert slip4["deductions_minor"] == 0


# ---------------------------------------------------------------------------
# Leave → approval engine
# ---------------------------------------------------------------------------
def test_leave_seeds_and_resolves_approvals(conn):
    leave = importlib.import_module("hrkit.modules.leave")
    org = _seed_org(conn)

    # Configure HR approver = manager (re-using mgr_id is fine; the helper
    # de-dupes so we end up with just one approval row).
    conn.execute("INSERT INTO settings (key, value) VALUES ('HR_APPROVER_ID', ?)",
                 (str(org["mgr_id"]),))
    # Seed a leave_type so the FK on leave_request holds.
    conn.execute("INSERT INTO leave_type (name) VALUES ('PTO')")
    lt_id = conn.execute("SELECT id FROM leave_type WHERE name='PTO'").fetchone()["id"]
    conn.commit()

    req_id = leave.create_leave_request(
        conn, employee_id=org["emp_id"], leave_type_id=lt_id,
        start_date="2026-05-01", end_date="2026-05-03", reason="Holiday")

    # One approval row should exist (manager only — HR is the same id, deduped).
    rows = conn.execute(
        "SELECT level, approver_id, status FROM approval "
        "WHERE request_type='leave' AND request_id=? ORDER BY level",
        (req_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["approver_id"] == org["mgr_id"]
    assert rows[0]["status"] == "pending"

    # Approve the leave — pending approval rows should flip.
    leave.set_status(conn, req_id, status="approved", approver_id=org["mgr_id"])
    rows = conn.execute(
        "SELECT status, responded_at FROM approval "
        "WHERE request_type='leave' AND request_id=?",
        (req_id,)).fetchall()
    assert all(r["status"] == "approved" for r in rows)
    assert all(r["responded_at"] for r in rows)


# ---------------------------------------------------------------------------
# Exit → F&F auto-compute
# ---------------------------------------------------------------------------
def test_exit_record_auto_settles_fnf(conn):
    exit_record = importlib.import_module("hrkit.modules.exit_record")
    org = _seed_org(conn)

    # Alice: hire 2022-04-01, last working day 2026-04-30 → ~4 years tenure
    # → no statutory gratuity (< 5 yrs) but last salary + leave encashment
    # should still appear.
    rec_id = exit_record.create_row(conn, {
        "employee_id": org["emp_id"],
        "last_working_day": "2026-04-30",
        "exit_type": "resignation",
        "notice_period_days": 30,
    })

    row = conn.execute(
        "SELECT gratuity_minor, f_and_f_amount_minor, f_and_f_settled_at, "
        "f_and_f_breakdown_json FROM exit_record WHERE id = ?", (rec_id,)
    ).fetchone()

    # < 5 yrs of service → gratuity is 0, but the breakdown should still be
    # written and the total should at least include the last month's salary.
    assert row["f_and_f_settled_at"], "F&F should auto-settle on create"
    assert row["gratuity_minor"] == 0
    assert row["f_and_f_amount_minor"] >= 8_000_000  # at least last salary
    breakdown = json.loads(row["f_and_f_breakdown_json"])
    assert breakdown["last_month_salary_minor"] == 8_000_000
    assert breakdown["apply_gratuity"] is False
    assert 3.5 < breakdown["years_of_service"] < 4.5


def test_exit_record_auto_fnf_with_gratuity(conn):
    """≥ 5 years service triggers the gratuity calc."""
    exit_record = importlib.import_module("hrkit.modules.exit_record")
    org = _seed_org(conn)
    # Manager with 6+ yrs tenure — exit them.
    rec_id = exit_record.create_row(conn, {
        "employee_id": org["mgr_id"],
        "last_working_day": "2026-06-30",
        "exit_type": "resignation",
    })
    row = conn.execute(
        "SELECT gratuity_minor, f_and_f_breakdown_json FROM exit_record WHERE id = ?",
        (rec_id,)).fetchone()
    breakdown = json.loads(row["f_and_f_breakdown_json"])
    assert breakdown["apply_gratuity"] is True
    assert row["gratuity_minor"] > 0
    # Gratuity = salary × 15 × yrs / 26 → with salary 1.2L, ~6.5y →
    # 12_00_000 × 15 × 6.5 / 26 ≈ ~45L paise ⇒ >= 30L paise as a sanity floor.
    assert row["gratuity_minor"] >= 3_000_000


# ---------------------------------------------------------------------------
# Expense + advance → approval engine
# ---------------------------------------------------------------------------
def test_expense_and_advance_seed_approvals(conn):
    expense = importlib.import_module("hrkit.modules.expense")
    salary_advance = importlib.import_module("hrkit.modules.salary_advance")
    org = _seed_org(conn)

    exp_id = expense.create_row(conn, {
        "employee_id": org["emp_id"], "amount": 1500.0,
        "description": "Cab", "status": "submitted",
    })
    rows = conn.execute(
        "SELECT approver_id FROM approval "
        "WHERE request_type='expense' AND request_id=?", (exp_id,)).fetchall()
    assert any(r["approver_id"] == org["mgr_id"] for r in rows)

    # Approve via expense.update_row → mirrors onto approval rows.
    expense.update_row(conn, exp_id, {"status": "approved"})
    statuses = [r["status"] for r in conn.execute(
        "SELECT status FROM approval WHERE request_type='expense' AND request_id=?",
        (exp_id,)).fetchall()]
    assert all(s == "approved" for s in statuses)

    # salary_advance also seeds approvals.
    adv_id = salary_advance.create_row(conn, {
        "employee_id": org["emp_id"], "amount": 25000,
        "reason": "Medical",
    })
    rows = conn.execute(
        "SELECT approver_id, status FROM approval "
        "WHERE request_type='salary_advance' AND request_id=?", (adv_id,)).fetchall()
    assert len(rows) >= 1
    assert all(r["status"] == "pending" for r in rows)
