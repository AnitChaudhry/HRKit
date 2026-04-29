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


def test_approval_detail_has_action_buttons(conn):
    mod = importlib.import_module("hrkit.modules.approval")
    conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) "
        "VALUES ('APR-1', 'Approver', 'approver@example.com')"
    )
    approver_id = conn.execute("SELECT id FROM employee").fetchone()["id"]
    approval_id = mod.request_approvals(
        conn,
        request_type="leave",
        request_id=42,
        approver_ids=[approver_id],
    )[0]

    h = _FakeHandler(conn)
    mod.detail_view(h, approval_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert "respondDetail" in body
    assert ">Approve<" in body
    assert ">Reject<" in body
