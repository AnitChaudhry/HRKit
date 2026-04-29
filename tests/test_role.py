"""Smoke test for the role module — happy path create/list/delete."""

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


def test_role_create_list_delete(conn):
    mod = importlib.import_module("hrkit.modules.role")

    dept_id = conn.execute(
        "INSERT INTO department (name, code) VALUES (?, ?)",
        ("Engineering", "ENG"),
    ).lastrowid
    conn.commit()

    role_id = mod.create_row(conn, {
        "title": "Staff Engineer",
        "department_id": dept_id,
        "level": "IC5",
        "description": "Senior IC contributor.",
    })
    assert role_id > 0

    rows = mod.list_rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Staff Engineer"
    assert row["department"] == "Engineering"
    assert row["level"] == "IC5"

    mod.update_row(conn, role_id, {"level": "IC6"})
    assert mod.get_row(conn, role_id)["level"] == "IC6"

    mod.delete_row(conn, role_id)
    assert mod.list_rows(conn) == []


def test_role_requires_title(conn):
    import pytest
    mod = importlib.import_module("hrkit.modules.role")
    with pytest.raises(ValueError):
        mod.create_row(conn, {"level": "IC1"})


def test_role_module_contract(conn):
    mod = importlib.import_module("hrkit.modules.role")
    assert mod.MODULE["name"] == "role"
    assert "GET" in mod.MODULE["routes"]
    mod.MODULE["ensure_schema"](conn)


def test_role_list_and_detail_have_real_edit_controls(conn):
    mod = importlib.import_module("hrkit.modules.role")
    dept_id = conn.execute(
        "INSERT INTO department (name, code) VALUES (?, ?)",
        ("Engineering", "ENG"),
    ).lastrowid
    conn.commit()
    role_id = mod.create_row(conn, {
        "title": "People Partner",
        "department_id": dept_id,
        "level": "Manager",
    })

    h = _FakeHandler(conn)
    mod.list_view(h)
    code, body = h.html_responses[0]
    assert code == 200
    assert f'/m/role/{role_id}' in body
    assert ">Open<" in body

    h = _FakeHandler(conn)
    mod.detail_view(h, role_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "Department assignment" in body
    assert "role-dept-picker" in body
    assert 'name="title"' in body
    assert 'name="level"' in body
    assert 'name="department"' not in body
