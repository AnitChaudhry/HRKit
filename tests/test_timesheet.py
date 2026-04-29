from __future__ import annotations

import importlib


class _FakeServer:
    def __init__(self, conn) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn, payload=None) -> None:
        self.server = _FakeServer(conn)
        self.payload = payload or {}
        self.html_responses: list[tuple[int, str]] = []
        self.json_responses: list[tuple[int, dict]] = []

    def _html(self, code: int, body: str) -> None:
        self.html_responses.append((code, body))

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))

    def _read_json(self):
        return self.payload


def _seed(conn) -> dict[str, int]:
    conn.execute("INSERT INTO department (name, code) VALUES ('Engineering', 'ENG')")
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) "
        "VALUES ('EMP-TS1', 'Timer One', 'timer1@example.com')"
    )
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) "
        "VALUES ('EMP-TS2', 'Approver Two', 'approver2@example.com')"
    )
    conn.execute(
        "INSERT INTO project (name, code, status) VALUES ('Website', 'WEB', 'active')"
    )
    conn.commit()
    return {
        "employee_id": int(conn.execute(
            "SELECT id FROM employee WHERE employee_code='EMP-TS1'"
        ).fetchone()["id"]),
        "approver_id": int(conn.execute(
            "SELECT id FROM employee WHERE employee_code='EMP-TS2'"
        ).fetchone()["id"]),
        "project_id": int(conn.execute(
            "SELECT id FROM project WHERE code='WEB'"
        ).fetchone()["id"]),
    }


def test_timesheet_create_update_and_views(conn):
    mod = importlib.import_module("hrkit.modules.timesheet")
    ids = _seed(conn)

    entry_id = mod.create_entry(conn, {
        "employee_id": ids["employee_id"],
        "project_id": ids["project_id"],
        "date": "2026-04-29",
        "hours": "6.5",
        "billable": "1",
        "description": "Implementation",
    })
    assert entry_id > 0

    mod.update_entry(conn, entry_id, {"hours": "7.25", "billable": "0"})
    row = mod.get_row(conn, entry_id)
    assert row["hours"] == 7.25
    assert row["billable"] == 0

    h = _FakeHandler(conn)
    mod.list_view(h)
    code, body = h.html_responses[0]
    assert code == 200
    assert "+ Log time" in body
    assert f'/m/timesheet/{entry_id}' in body
    assert "approve-dlg" in body

    h = _FakeHandler(conn)
    mod.detail_view(h, entry_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "Approval controls" in body
    assert "openEditDialog" in body
    assert 'name="employee"' not in body
    assert 'name="project"' not in body
    assert 'name="hours"' in body
    assert 'name="billable"' in body


def test_timesheet_create_and_update_api(conn):
    mod = importlib.import_module("hrkit.modules.timesheet")
    ids = _seed(conn)

    h = _FakeHandler(conn, {
        "employee_id": ids["employee_id"],
        "project_id": ids["project_id"],
        "date": "2026-04-30",
        "hours": "5",
        "billable": "1",
    })
    mod.create_api(h)
    code, payload = h.json_responses[0]
    assert code == 201
    entry_id = payload["id"]

    h = _FakeHandler(conn, {"description": "Corrected", "approved": "1"})
    mod.update_api(h, entry_id)
    code, payload = h.json_responses[0]
    assert code == 200
    row = mod.get_row(conn, entry_id)
    assert row["description"] == "Corrected"
    assert row["approved"] == 1
