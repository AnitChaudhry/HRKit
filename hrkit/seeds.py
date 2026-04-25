"""Sample-data seed for first-time HR-Kit users.

Inserts a canonical, hand-crafted demo dataset spanning all 11 modules so
that a fresh workspace has something to look at immediately. Every insert
is idempotent on the natural key (employee_code, email, period, etc.) so
calling :func:`load_sample_data` twice does not duplicate rows.

Composition (rough counts):
    * 3 departments       (Engineering, Sales, Operations)
    * 5 roles
    * 8 employees with manager hierarchy
    * 2 leave types       (Annual, Sick)
    * 3 leave requests    (approved, pending, rejected)
    * 4 onboarding tasks  (mixed states, all on the newest employee)
    * 1 payroll run + 8 payslips
    * 3 recruitment candidates (applied, interview, offer)

Stdlib only. No imports from ``hrkit.modules`` so this is safe to call
during the first-run wizard before module routes are wired up.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# ---------------------------------------------------------------------------
# Canonical sample rows
# ---------------------------------------------------------------------------

# (name, code)
SAMPLE_DEPARTMENTS: list[tuple[str, str]] = [
    ("Engineering", "ENG"),
    ("Sales",       "SAL"),
    ("Operations",  "OPS"),
]

# (title, dept_name, level)
SAMPLE_ROLES: list[tuple[str, str, str]] = [
    ("Software Engineer",  "Engineering", "Mid"),
    ("Senior Engineer",    "Engineering", "Senior"),
    ("Account Executive",  "Sales",       "Mid"),
    ("Operations Manager", "Operations",  "Lead"),
    ("HR Manager",         "Operations",  "Lead"),
]

# (code, full_name, email, dept_name, role_title, hire_date, salary_minor, manager_code)
SAMPLE_EMPLOYEES: list[tuple[str, str, str, str, str, str, int, str | None]] = [
    ("EMP-S001", "Aarav Sharma",  "aarav.sample@example.com",  "Operations",  "HR Manager",         "2022-04-01", 1200000, None),
    ("EMP-S002", "Priya Patel",   "priya.sample@example.com",  "Operations",  "Operations Manager", "2022-06-15", 1500000, None),
    ("EMP-S003", "Rohan Mehta",   "rohan.sample@example.com",  "Engineering", "Senior Engineer",    "2023-02-10", 1800000, None),
    ("EMP-S004", "Anika Iyer",    "anika.sample@example.com",  "Engineering", "Software Engineer",  "2024-08-01",  900000, "EMP-S003"),
    ("EMP-S005", "Karan Verma",   "karan.sample@example.com",  "Engineering", "Software Engineer",  "2025-01-20",  850000, "EMP-S003"),
    ("EMP-S006", "Sneha Reddy",   "sneha.sample@example.com",  "Sales",       "Account Executive",  "2024-11-05",  950000, "EMP-S002"),
    ("EMP-S007", "Vikram Singh",  "vikram.sample@example.com", "Sales",       "Account Executive",  "2023-09-12", 1000000, "EMP-S002"),
    ("EMP-S008", "Maya Krishnan", "maya.sample@example.com",   "Engineering", "Software Engineer",  "2026-03-01",  800000, "EMP-S003"),
]

# (name, code, max_days_per_year, paid)
SAMPLE_LEAVE_TYPES: list[tuple[str, str, int, int]] = [
    ("Annual Leave", "AL", 24, 1),
    ("Sick Leave",   "SL", 12, 1),
]

# (employee_code, type_code, start_date, end_date, days, status, reason)
SAMPLE_LEAVE_REQUESTS: list[tuple[str, str, str, str, int, str, str]] = [
    ("EMP-S004", "AL", "2026-05-04", "2026-05-08", 5, "approved", "Family wedding"),
    ("EMP-S006", "SL", "2026-04-22", "2026-04-23", 2, "pending",  "Fever, will share medical certificate"),
    ("EMP-S005", "AL", "2026-04-01", "2026-04-02", 2, "rejected", "Short notice; please reschedule"),
]

# (employee_code, title, owner_code, due_date, status)
SAMPLE_ONBOARDING_TASKS: list[tuple[str, str, str, str, str]] = [
    ("EMP-S008", "Sign IP and confidentiality agreement", "EMP-S001", "2026-03-08", "done"),
    ("EMP-S008", "Set up dev laptop and 2FA",             "EMP-S003", "2026-03-15", "in_progress"),
    ("EMP-S008", "Buddy intro coffee with team",          "EMP-S003", "2026-03-12", "done"),
    ("EMP-S008", "Complete first-week orientation plan",  "EMP-S001", "2026-03-22", "pending"),
]

# (name, email, source, status, score, recommendation)
SAMPLE_RECRUITMENT_CANDIDATES: list[tuple[str, str, str, str, float, str]] = [
    ("Anonymous Applicant", "anon.sample@example.com",    "linkedin", "applied",   0.0, ""),
    ("Tara Joshi",          "tara.sample@example.com",    "referral", "interview", 7.5, "Shortlist"),
    ("Devansh Kapoor",      "devansh.sample@example.com", "careers",  "offer",     8.5, "Strong hire"),
]

PAYROLL_PERIOD = "2026-03"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dept_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM department WHERE name = ?", (name,)
    ).fetchone()
    return int(row["id"]) if row else None


def _role_id(conn: sqlite3.Connection, title: str, dept_id: int | None) -> int | None:
    if dept_id is None:
        row = conn.execute(
            "SELECT id FROM role WHERE title = ? AND department_id IS NULL",
            (title,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM role WHERE title = ? AND department_id = ?",
            (title, dept_id),
        ).fetchone()
    return int(row["id"]) if row else None


def _emp_id(conn: sqlite3.Connection, code: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM employee WHERE employee_code = ?", (code,)
    ).fetchone()
    return int(row["id"]) if row else None


def _leave_type_id(conn: sqlite3.Connection, code: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM leave_type WHERE code = ?", (code,)
    ).fetchone()
    return int(row["id"]) if row else None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def load_sample_data(conn: sqlite3.Connection) -> dict[str, Any]:
    """Insert canonical sample HR data. Returns rows-inserted counts.

    Idempotent: re-running on a workspace that already has the sample data
    is a no-op (rows skip on duplicate natural keys). Wraps the entire
    operation in a single transaction; rolls back on any error.
    """
    counts: dict[str, int] = {
        "department": 0, "role": 0, "employee": 0,
        "leave_type": 0, "leave_request": 0,
        "onboarding_task": 0, "payroll_run": 0, "payslip": 0,
        "recruitment_candidate": 0,
    }

    conn.execute("BEGIN")
    try:
        # 1. Departments — natural key: name
        for name, code in SAMPLE_DEPARTMENTS:
            cur = conn.execute(
                "INSERT OR IGNORE INTO department (name, code) VALUES (?, ?)",
                (name, code),
            )
            if cur.rowcount:
                counts["department"] += 1

        # 2. Roles — natural key: (title, department_id)
        for title, dept_name, level in SAMPLE_ROLES:
            dept_id = _dept_id(conn, dept_name)
            if _role_id(conn, title, dept_id) is not None:
                continue
            conn.execute(
                "INSERT INTO role (title, department_id, level) VALUES (?, ?, ?)",
                (title, dept_id, level),
            )
            counts["role"] += 1

        # 3a. Employees (without manager_id — set in pass 3b)
        for code, full_name, email, dept_name, role_title, hire_date, salary, _mgr in SAMPLE_EMPLOYEES:
            if _emp_id(conn, code) is not None:
                continue
            dept_id = _dept_id(conn, dept_name)
            role_id = _role_id(conn, role_title, dept_id)
            cur = conn.execute(
                "INSERT INTO employee (employee_code, full_name, email,"
                " hire_date, employment_type, status,"
                " department_id, role_id, salary_minor, location)"
                " VALUES (?, ?, ?, ?, 'full_time', 'active', ?, ?, ?, ?)",
                (code, full_name, email, hire_date, dept_id, role_id, salary, "Bangalore"),
            )
            if cur.rowcount:
                counts["employee"] += 1

        # 3b. Manager hierarchy
        for code, _name, _email, _dept, _role, _hire, _salary, mgr_code in SAMPLE_EMPLOYEES:
            if not mgr_code:
                continue
            emp = _emp_id(conn, code)
            mgr = _emp_id(conn, mgr_code)
            if emp is None or mgr is None:
                continue
            conn.execute(
                "UPDATE employee SET manager_id = ?"
                " WHERE id = ? AND manager_id IS NULL",
                (mgr, emp),
            )

        # 4. Leave types — natural key: name
        for name, lt_code, max_days, paid in SAMPLE_LEAVE_TYPES:
            cur = conn.execute(
                "INSERT OR IGNORE INTO leave_type"
                " (name, code, max_days_per_year, paid) VALUES (?, ?, ?, ?)",
                (name, lt_code, max_days, paid),
            )
            if cur.rowcount:
                counts["leave_type"] += 1

        # 5. Leave requests — duplicate guard on (employee, dates)
        approver_id = _emp_id(conn, "EMP-S001")
        for emp_code, type_code, start, end, days, status, reason in SAMPLE_LEAVE_REQUESTS:
            emp_id = _emp_id(conn, emp_code)
            lt_id = _leave_type_id(conn, type_code)
            if emp_id is None or lt_id is None:
                continue
            existing = conn.execute(
                "SELECT 1 FROM leave_request"
                " WHERE employee_id = ? AND start_date = ? AND end_date = ?",
                (emp_id, start, end),
            ).fetchone()
            if existing:
                continue
            decided_at = "" if status == "pending" else "2026-04-15T10:00:00+05:30"
            conn.execute(
                "INSERT INTO leave_request (employee_id, leave_type_id,"
                " start_date, end_date, days, reason, status,"
                " approver_id, decided_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (emp_id, lt_id, start, end, days, reason, status,
                 approver_id, decided_at),
            )
            counts["leave_request"] += 1

        # 6. Onboarding tasks — duplicate guard on (employee, title)
        for emp_code, title, owner_code, due, status in SAMPLE_ONBOARDING_TASKS:
            emp_id = _emp_id(conn, emp_code)
            owner_id = _emp_id(conn, owner_code)
            if emp_id is None:
                continue
            existing = conn.execute(
                "SELECT 1 FROM onboarding_task WHERE employee_id = ? AND title = ?",
                (emp_id, title),
            ).fetchone()
            if existing:
                continue
            completed = "2026-04-20T12:00:00+05:30" if status == "done" else ""
            conn.execute(
                "INSERT INTO onboarding_task (employee_id, title, owner_id,"
                " due_date, status, completed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (emp_id, title, owner_id, due, status, completed),
            )
            counts["onboarding_task"] += 1

        # 7. Payroll run + payslips — natural key: period (UNIQUE)
        existing_run = conn.execute(
            "SELECT id FROM payroll_run WHERE period = ?", (PAYROLL_PERIOD,)
        ).fetchone()
        if existing_run is None:
            cur = conn.execute(
                "INSERT INTO payroll_run (period, status, processed_at,"
                " processed_by, notes) VALUES (?, 'paid', ?, ?, ?)",
                (PAYROLL_PERIOD, "2026-04-01T18:00:00+05:30",
                 approver_id, "Sample payroll run"),
            )
            run_id = int(cur.lastrowid)
            counts["payroll_run"] += 1
            for code, *_rest in SAMPLE_EMPLOYEES:
                emp_id = _emp_id(conn, code)
                if emp_id is None:
                    continue
                emp_row = conn.execute(
                    "SELECT salary_minor FROM employee WHERE id = ?", (emp_id,)
                ).fetchone()
                if not emp_row:
                    continue
                gross = int(emp_row["salary_minor"] or 0)
                deductions = gross // 10  # flat 10% withholding for the demo
                net = gross - deductions
                conn.execute(
                    "INSERT INTO payslip (payroll_run_id, employee_id,"
                    " gross_minor, deductions_minor, net_minor)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (run_id, emp_id, gross, deductions, net),
                )
                counts["payslip"] += 1

        # 8. Recruitment candidates — duplicate guard on email
        for name, email, source, status, score, rec in SAMPLE_RECRUITMENT_CANDIDATES:
            existing = conn.execute(
                "SELECT 1 FROM recruitment_candidate WHERE email = ?", (email,)
            ).fetchone()
            if existing:
                continue
            evaluated_at = "2026-04-18T15:00:00+05:30" if score > 0 else ""
            conn.execute(
                "INSERT INTO recruitment_candidate (name, email, source,"
                " status, score, recommendation, evaluated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, email, source, status, score, rec, evaluated_at),
            )
            counts["recruitment_candidate"] += 1

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return counts


__all__ = ["load_sample_data"]
