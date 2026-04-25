"""Tests for Phase 1.11 — per-employee custom notes + custom fields + AI context."""

from __future__ import annotations

import json
import sqlite3

import pytest

from hrkit import employee_fs, frontmatter as fm


# ---------------------------------------------------------------------------
# Notes round-trip
# ---------------------------------------------------------------------------
def test_write_and_read_notes(tmp_path):
    employee_fs.write_notes(tmp_path, "EMP-007", "## Day-1\n\n- buddy: Alex\n- laptop ordered")
    body = employee_fs.read_notes(tmp_path, "EMP-007")
    assert "buddy: Alex" in body
    # File lives under memory/ as expected.
    note_file = tmp_path / "employees" / "EMP-007" / "memory" / "notes.md"
    assert note_file.exists()


def test_read_notes_returns_empty_for_missing(tmp_path):
    assert employee_fs.read_notes(tmp_path, "EMP-NONE") == ""


# ---------------------------------------------------------------------------
# Custom fields round-trip (DB)
# ---------------------------------------------------------------------------
def test_set_and_get_custom_fields(conn):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-CFX", "Custom Fan", "cfx@example.com"),
    ).lastrowid
    conn.commit()
    saved = employee_fs.set_custom_fields(conn, emp_id, {
        "tshirt_size": "L",
        "buddy": "Alex",
        "_skip me_": "should be dropped",  # whitespace-only key trimmed
    })
    assert saved == {
        "tshirt_size": "L",
        "buddy": "Alex",
        "_skip me_": "should be dropped",
    }
    # Round-trips.
    fetched = employee_fs.get_custom_fields(conn, emp_id)
    assert fetched["buddy"] == "Alex"
    # Stored under metadata_json.custom (so it co-exists with anything else).
    row = conn.execute("SELECT metadata_json FROM employee WHERE id = ?", (emp_id,)).fetchone()
    meta = json.loads(row["metadata_json"])
    assert meta["custom"]["tshirt_size"] == "L"


def test_set_custom_fields_raises_for_missing_employee(conn):
    with pytest.raises(LookupError):
        employee_fs.set_custom_fields(conn, 99999, {"x": "y"})


# ---------------------------------------------------------------------------
# employee.md mirror preserves user edits
# ---------------------------------------------------------------------------
def test_write_employee_md_preserves_user_added_frontmatter(tmp_path):
    # First write — canonical fields only.
    employee_fs.write_employee_md(tmp_path, {
        "employee_code": "EMP-PRESERVE",
        "full_name": "Preserve Me",
        "email": "p@example.com",
    })
    md = tmp_path / "employees" / "EMP-PRESERVE" / "employee.md"
    # Simulate a human hand-editing the file: add a custom frontmatter key
    # and a paragraph in the body.
    text = md.read_text(encoding="utf-8")
    fm_dict, body = fm.parse(text)
    fm_dict["favorite_color"] = "blue"
    md.write_text(fm.dump(fm_dict, body + "\n\n## Hand-typed note\nLikes filter coffee.\n"),
                  encoding="utf-8")

    # Second write (e.g., the row was updated) — both edits must survive.
    employee_fs.write_employee_md(tmp_path, {
        "employee_code": "EMP-PRESERVE",
        "full_name": "Preserve Me Now",   # changed
        "email": "p@example.com",
        "phone": "+91-9999999999",        # newly set
    })
    text2 = md.read_text(encoding="utf-8")
    fm2, body2 = fm.parse(text2)
    assert fm2["favorite_color"] == "blue"
    assert fm2["full_name"] == "Preserve Me Now"     # canonical field updated
    assert fm2["phone"] == "+91-9999999999"          # canonical field added
    assert "Hand-typed note" in body2
    assert "filter coffee" in body2


def test_write_employee_md_mirrors_custom_metadata_to_frontmatter(tmp_path):
    """metadata_json.custom keys appear as `custom_<key>` in the frontmatter."""
    employee_fs.write_employee_md(tmp_path, {
        "employee_code": "EMP-MIRR",
        "full_name": "Mirror Me",
        "email": "m@example.com",
        "metadata_json": json.dumps({"custom": {"tshirt_size": "L", "buddy": "Alex"}}),
    })
    md = tmp_path / "employees" / "EMP-MIRR" / "employee.md"
    fm_dict, _ = fm.parse(md.read_text(encoding="utf-8"))
    assert fm_dict.get("custom_tshirt_size") == "L"
    assert fm_dict.get("custom_buddy") == "Alex"


# ---------------------------------------------------------------------------
# build_ai_context — what the chat agent reads when scoped to an employee
# ---------------------------------------------------------------------------
def test_build_ai_context_includes_facts_and_notes(conn, tmp_path):
    dept_id = conn.execute(
        "INSERT INTO department (name) VALUES (?)", ("Engineering",),
    ).lastrowid
    role_id = conn.execute(
        "INSERT INTO role (title, department_id) VALUES (?, ?)",
        ("Senior Engineer", dept_id),
    ).lastrowid
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email,"
        " department_id, role_id, hire_date, status)"
        " VALUES (?, ?, ?, ?, ?, ?, 'active')",
        ("EMP-CTX", "Context User", "ctx@example.com", dept_id, role_id, "2024-01-01"),
    ).lastrowid
    conn.commit()
    # Add custom fields + notes so the context picks them up.
    employee_fs.set_custom_fields(conn, emp_id, {"tshirt_size": "L"})
    employee_fs.write_notes(tmp_path, "EMP-CTX", "Strong promotion candidate Q3 2026.")

    ctx = employee_fs.build_ai_context(conn, tmp_path, emp_id)
    assert "Context User" in ctx
    assert "EMP-CTX" in ctx
    assert "Engineering" in ctx
    assert "Senior Engineer" in ctx
    assert "tshirt_size: L" in ctx
    assert "Strong promotion candidate" in ctx


def test_build_ai_context_returns_empty_for_missing_employee(conn, tmp_path):
    assert employee_fs.build_ai_context(conn, tmp_path, 99999) == ""


def test_build_ai_context_truncates_to_max_chars(conn, tmp_path):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-LONG", "Long Notes", "long@example.com"),
    ).lastrowid
    conn.commit()
    employee_fs.write_notes(tmp_path, "EMP-LONG", "x" * 20000)
    ctx = employee_fs.build_ai_context(conn, tmp_path, emp_id, max_chars=500)
    assert len(ctx) <= 600  # 500 + truncation suffix
    assert "context truncated" in ctx
