"""Smoke test for the employee module — happy path create/list/delete."""

from __future__ import annotations

import importlib


class _FakeServer:
    def __init__(self, conn) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn) -> None:
        self.server = _FakeServer(conn)
        self.html_responses: list[tuple[int, str]] = []

    def _html(self, code: int, body: str) -> None:
        self.html_responses.append((code, body))


def test_employee_detail_view_has_upload_dialog(conn):
    mod = importlib.import_module("hrkit.modules.employee")
    emp_id = mod.create_row(conn, {
        "full_name": "Up Loader",
        "email": "uploader@example.com",
        "employee_code": "EMP-UP1",
    })
    h = _FakeHandler(conn)
    mod.detail_view(h, emp_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "doc-upload-dlg" in body
    assert "Upload document" in body
    # employee_id is pre-filled so the upload binds to this employee.
    assert f'name="employee_id" value="{emp_id}"' in body
    assert "/api/m/document/upload" in body


def test_employee_create_list_delete(conn):
    mod = importlib.import_module("hrkit.modules.employee")

    # Need a department + role for FK columns.
    dept_id = conn.execute(
        "INSERT INTO department (name, code) VALUES (?, ?)",
        ("Engineering", "ENG"),
    ).lastrowid
    role_id = conn.execute(
        "INSERT INTO role (title, department_id, level) VALUES (?, ?, ?)",
        ("Software Engineer", dept_id, "IC2"),
    ).lastrowid
    conn.commit()

    new_id = mod.create_row(conn, {
        "full_name": "Asha Iyer",
        "email": "asha@example.com",
        "employee_code": "EMP-001",
        "phone": "+91-9876543210",
        "department_id": dept_id,
        "role_id": role_id,
        "hire_date": "2026-01-15",
        "employment_type": "full_time",
        "status": "active",
        "salary": 95000,  # rupees -> 9_500_000 paise
    })
    assert isinstance(new_id, int) and new_id > 0

    rows = mod.list_rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == new_id
    assert row["full_name"] == "Asha Iyer"
    assert row["email"] == "asha@example.com"
    assert row["employee_code"] == "EMP-001"
    assert row["department"] == "Engineering"
    assert row["role"] == "Software Engineer"
    assert row["status"] == "active"
    assert row["salary_minor"] == 9_500_000  # 95000 rupees * 100

    # Update happy path.
    mod.update_row(conn, new_id, {"status": "on_leave", "phone": "+91-1112223334"})
    refreshed = mod.get_row(conn, new_id)
    assert refreshed["status"] == "on_leave"
    assert refreshed["phone"] == "+91-1112223334"

    # Delete + empty.
    mod.delete_row(conn, new_id)
    assert mod.list_rows(conn) == []
    assert mod.get_row(conn, new_id) is None


def test_employee_validation_rejects_missing_fields(conn):
    import pytest
    mod = importlib.import_module("hrkit.modules.employee")

    with pytest.raises(ValueError):
        mod.create_row(conn, {"email": "x@example.com"})  # no full_name
    with pytest.raises(ValueError):
        mod.create_row(conn, {"full_name": "Nobody"})     # no email


def test_employee_module_contract(conn):
    mod = importlib.import_module("hrkit.modules.employee")
    assert mod.MODULE["name"] == "employee"
    assert mod.MODULE["label"] == "Employees"
    assert callable(mod.MODULE["ensure_schema"])
    assert "GET" in mod.MODULE["routes"]
    assert "POST" in mod.MODULE["routes"]
    assert "DELETE" in mod.MODULE["routes"]
    # ensure_schema is a no-op but must accept a connection.
    mod.MODULE["ensure_schema"](conn)
