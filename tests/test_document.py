"""Smoke test for the document module — happy path create/list/delete."""

from __future__ import annotations

import importlib


def test_document_create_list_delete(conn):
    mod = importlib.import_module("hrkit.modules.document")

    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("EMP-007", "Bond James", "james@example.com"),
    ).lastrowid
    conn.commit()

    doc_id = mod.create_row(conn, {
        "employee_id": emp_id,
        "doc_type": "PAN",
        "filename": "pan-card.pdf",
        "file_path": "docs/EMP-007/pan-card.pdf",
        "expiry_date": "2030-12-31",
        "notes": "issued 2018",
    })
    assert doc_id > 0

    rows = mod.list_rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["employee"] == "Bond James"
    assert row["doc_type"] == "PAN"
    assert row["filename"] == "pan-card.pdf"
    assert row["expiry_date"] == "2030-12-31"

    mod.update_row(conn, doc_id, {"notes": "verified"})
    assert mod.get_row(conn, doc_id)["notes"] == "verified"

    mod.delete_row(conn, doc_id)
    assert mod.list_rows(conn) == []


def test_document_required_fields(conn):
    import pytest
    mod = importlib.import_module("hrkit.modules.document")

    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("EMP-SOLO", "Solo", "solo@example.com"),
    ).lastrowid
    conn.commit()

    with pytest.raises(ValueError):
        mod.create_row(conn, {"doc_type": "PAN", "filename": "x.pdf", "file_path": "p"})  # no employee_id
    with pytest.raises(ValueError):
        mod.create_row(conn, {"employee_id": emp_id, "filename": "x.pdf", "file_path": "p"})
    with pytest.raises(ValueError):
        mod.create_row(conn, {"employee_id": emp_id, "doc_type": "PAN", "file_path": "p"})
    with pytest.raises(ValueError):
        mod.create_row(conn, {"employee_id": emp_id, "doc_type": "PAN", "filename": "x.pdf"})


def test_document_cascade_on_employee_delete(conn):
    mod = importlib.import_module("hrkit.modules.document")
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("EMP-CASC", "Casc Ade", "casc@example.com"),
    ).lastrowid
    conn.commit()
    mod.create_row(conn, {
        "employee_id": emp_id,
        "doc_type": "Contract",
        "filename": "c.pdf",
        "file_path": "docs/c.pdf",
    })
    assert len(mod.list_rows(conn)) == 1
    conn.execute("DELETE FROM employee WHERE id = ?", (emp_id,))
    conn.commit()
    assert mod.list_rows(conn) == []  # ON DELETE CASCADE


def test_document_module_contract(conn):
    mod = importlib.import_module("hrkit.modules.document")
    assert mod.MODULE["name"] == "document"
    assert "DELETE" in mod.MODULE["routes"]
    mod.MODULE["ensure_schema"](conn)


class _FakeServer:
    def __init__(self, conn) -> None:
        self.conn = conn


class _FakeHandler:
    def __init__(self, conn) -> None:
        self.server = _FakeServer(conn)
        self.html_responses: list[tuple[int, str]] = []

    def _html(self, code: int, body: str) -> None:
        self.html_responses.append((code, body))


def test_document_detail_view_includes_download_link(conn):
    mod = importlib.import_module("hrkit.modules.document")
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("EMP-DL", "Dora Loadie", "dora@example.com"),
    ).lastrowid
    conn.commit()
    doc_id = mod.create_row(conn, {
        "employee_id": emp_id,
        "doc_type": "Contract",
        "filename": "offer-letter.pdf",
        "file_path": ".hrkit/uploads/employee/1/offer-letter.pdf",
    })
    h = _FakeHandler(conn)
    mod.detail_view(h, doc_id)
    code, body = h.html_responses[0]
    assert code == 200
    assert f"/api/m/document/{doc_id}/download" in body
    assert "Download" in body
