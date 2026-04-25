"""Smoke test for the department module — happy path create/list/delete."""

from __future__ import annotations

import importlib


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
