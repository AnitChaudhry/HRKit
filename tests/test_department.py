"""Smoke test for the department module — happy path create/list/delete."""

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


def test_department_create_list_delete(conn):
    mod = importlib.import_module("hrkit.modules.department")

    parent_id = mod.create_row(conn, {"name": "People Ops", "code": "POPS"})
    child_id = mod.create_row(conn, {
        "name": "Recruitment",
        "code": "REC",
        "parent_department_id": parent_id,
        "notes": "owns hiring funnel",
    })

    rows = mod.list_rows(conn)
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["Recruitment"]["parent"] == "People Ops"
    assert by_name["Recruitment"]["code"] == "REC"
    assert by_name["People Ops"]["parent"] is None

    mod.update_row(conn, child_id, {"notes": "owns hiring + onboarding"})
    refreshed = mod.get_row(conn, child_id)
    assert refreshed["notes"] == "owns hiring + onboarding"

    # Delete child first (parent has FK reference).
    mod.delete_row(conn, child_id)
    mod.delete_row(conn, parent_id)
    assert mod.list_rows(conn) == []


def test_department_requires_name(conn):
    import pytest
    mod = importlib.import_module("hrkit.modules.department")
    with pytest.raises(ValueError):
        mod.create_row(conn, {"code": "X"})


def test_department_module_contract(conn):
    mod = importlib.import_module("hrkit.modules.department")
    assert mod.MODULE["name"] == "department"
    assert "GET" in mod.MODULE["routes"]
    mod.MODULE["ensure_schema"](conn)


def test_department_list_and_detail_have_real_edit_controls(conn):
    mod = importlib.import_module("hrkit.modules.department")
    parent_id = mod.create_row(conn, {"name": "People Ops", "code": "POPS"})
    child_id = mod.create_row(conn, {
        "name": "Recruitment",
        "code": "REC",
        "parent_department_id": parent_id,
    })

    h = _FakeHandler(conn)
    mod.list_view(h)
    code, body = h.html_responses[0]
    assert code == 200
    assert f'/m/department/{child_id}' in body
    assert ">Open<" in body

    h = _FakeHandler(conn)
    mod.detail_view(h, child_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "Department controls" in body
    assert "dept-parent-picker" in body
    assert 'name="name"' in body
    assert 'name="code"' in body
    assert 'name="head_employee"' not in body
    assert 'name="parent_department"' not in body
