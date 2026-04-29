"""Tests for hrkit.uploads — multipart parsing, file save, path-escape guard."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from hrkit import uploads


# ---------------------------------------------------------------------------
# Helpers — fake handler that mimics BaseHTTPRequestHandler enough for tests.
# ---------------------------------------------------------------------------
class _FakeServer:
    def __init__(self, conn: sqlite3.Connection, root: Path) -> None:
        self.conn = conn
        self.workspace_root = root


class _FakeHeaders(dict):
    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key.lower(), default)


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler."""

    def __init__(self, *, body: bytes, headers: dict[str, str],
                 conn: sqlite3.Connection | None = None,
                 root: Path | None = None) -> None:
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        h = _FakeHeaders()
        for k, v in headers.items():
            h[k.lower()] = v
        self.headers = h
        self.json_responses: list[tuple[int, Any]] = []
        self.raw_responses: list[tuple[int, bytes, str]] = []
        self.status_code: int | None = None
        self.sent_headers: list[tuple[str, str]] = []
        self.server = _FakeServer(conn, root) if conn is not None else None

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))

    def _send(self, code: int, body: bytes, content_type: str = "text/plain") -> None:
        self.raw_responses.append((code, body, content_type))

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, k: str, v: str) -> None:
        self.sent_headers.append((k, v))

    def end_headers(self) -> None:
        pass


def _make_multipart(boundary: str, parts: list[dict[str, Any]]) -> bytes:
    """Build a multipart/form-data body. Each part: name[, filename, content_type, value]."""
    out = bytearray()
    for part in parts:
        out += b"--" + boundary.encode() + b"\r\n"
        disp = f'form-data; name="{part["name"]}"'
        if "filename" in part:
            disp += f'; filename="{part["filename"]}"'
        out += f"Content-Disposition: {disp}\r\n".encode()
        if "content_type" in part:
            out += f"Content-Type: {part['content_type']}\r\n".encode()
        out += b"\r\n"
        v = part["value"]
        out += v if isinstance(v, bytes) else v.encode("utf-8")
        out += b"\r\n"
    out += b"--" + boundary.encode() + b"--\r\n"
    return bytes(out)


# ---------------------------------------------------------------------------
# parse_multipart
# ---------------------------------------------------------------------------
def test_parse_multipart_extracts_field_and_file():
    boundary = "----TestBoundaryABC123"
    body = _make_multipart(boundary, [
        {"name": "employee_id", "value": "42"},
        {"name": "doc_type", "value": "PAN"},
        {"name": "file", "filename": "card.pdf",
         "content_type": "application/pdf",
         "value": b"%PDF-1.4 fake-bytes"},
    ])
    handler = _FakeHandler(body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    })
    parsed = uploads.parse_multipart(handler)
    assert parsed["fields"]["employee_id"] == "42"
    assert parsed["fields"]["doc_type"] == "PAN"
    assert len(parsed["files"]) == 1
    f = parsed["files"][0]
    assert f["name"] == "file"
    assert f["filename"] == "card.pdf"
    assert f["content_type"] == "application/pdf"
    assert f["data"] == b"%PDF-1.4 fake-bytes"


def test_parse_multipart_rejects_oversize():
    boundary = "----b"
    body = b"--" + boundary.encode() + b"--\r\n"
    handler = _FakeHandler(body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(uploads.MAX_UPLOAD_BYTES + 1),
    })
    with pytest.raises(ValueError, match="too large"):
        uploads.parse_multipart(handler)


def test_parse_multipart_requires_boundary():
    handler = _FakeHandler(body=b"x", headers={
        "Content-Type": "multipart/form-data",
        "Content-Length": "1",
    })
    with pytest.raises(ValueError, match="boundary"):
        uploads.parse_multipart(handler)


# ---------------------------------------------------------------------------
# save_uploaded_file — collisions, sanitization, escape rejection
# ---------------------------------------------------------------------------
def test_save_uploaded_file_collision_appends_suffix(tmp_path):
    rel1 = uploads.save_uploaded_file(
        workspace_root=tmp_path, employee_id=7, filename="resume.pdf",
        data=b"first",
    )
    rel2 = uploads.save_uploaded_file(
        workspace_root=tmp_path, employee_id=7, filename="resume.pdf",
        data=b"second",
    )
    rel3 = uploads.save_uploaded_file(
        workspace_root=tmp_path, employee_id=7, filename="resume.pdf",
        data=b"third",
    )
    assert rel1.endswith("/resume.pdf")
    assert rel2.endswith("/resume-2.pdf")
    assert rel3.endswith("/resume-3.pdf")
    # Verify each file has its own bytes intact.
    assert (tmp_path / rel1).read_bytes() == b"first"
    assert (tmp_path / rel2).read_bytes() == b"second"
    assert (tmp_path / rel3).read_bytes() == b"third"


def test_save_uploaded_file_strips_path_components(tmp_path):
    # Attempts to traverse up the tree should be reduced to bare basename.
    rel = uploads.save_uploaded_file(
        workspace_root=tmp_path, employee_id=3,
        filename="../../../etc/passwd",
        data=b"sneaky",
    )
    saved = tmp_path / rel
    assert saved.exists()
    assert saved.name == "passwd"
    # The saved path must stay under the workspace's uploads root.
    uploads_root = (tmp_path / ".hrkit" / "uploads").resolve()
    assert str(saved.resolve()).startswith(str(uploads_root))


def test_save_uploaded_file_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError):
        uploads.save_uploaded_file(
            workspace_root=tmp_path, employee_id=1, filename="   ",
            data=b"x",
        )


# ---------------------------------------------------------------------------
# serve_uploaded_file — path-escape rejection
# ---------------------------------------------------------------------------
def test_serve_rejects_path_outside_uploads(tmp_path, conn):
    # Plant a doc row pointing OUTSIDE .hrkit/uploads.
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-X", "Escape Artist", "esc@example.com"),
    ).lastrowid
    # Create a file outside the uploads root.
    bad = tmp_path / "outside.txt"
    bad.write_bytes(b"hidden")
    doc_id = conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "Other", "outside.txt", "../outside.txt"),
    ).lastrowid
    conn.commit()

    handler = _FakeHandler(body=b"", headers={}, conn=conn, root=tmp_path)
    uploads.serve_uploaded_file(handler, doc_id)
    # Expect a 403 forbidden raw response.
    assert handler.raw_responses, "expected an error response"
    code, body, _ = handler.raw_responses[0]
    assert code == 403, f"expected 403, got {code} {body!r}"


def test_handle_document_upload_inserts_row(tmp_path, conn):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-UP", "Up Loader", "up@example.com"),
    ).lastrowid
    conn.commit()

    boundary = "----HrkitUpload"
    body = _make_multipart(boundary, [
        {"name": "employee_id", "value": str(emp_id)},
        {"name": "doc_type", "value": "Contract"},
        {"name": "file", "filename": "agreement.pdf",
         "content_type": "application/pdf",
         "value": b"contract bytes here"},
    ])
    handler = _FakeHandler(body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }, conn=conn, root=tmp_path)
    uploads.handle_document_upload(handler)

    assert handler.json_responses, "expected JSON response"
    code, payload = handler.json_responses[0]
    assert code == 201, payload
    assert payload["ok"] is True
    assert payload["document_id"] > 0
    rel = payload["file_path"]
    saved = tmp_path / rel
    assert saved.exists()
    assert saved.read_bytes() == b"contract bytes here"
    # Row in DB matches.
    row = conn.execute(
        "SELECT employee_id, doc_type, file_path FROM document WHERE id = ?",
        (payload["document_id"],),
    ).fetchone()
    assert row["employee_id"] == emp_id
    assert row["doc_type"] == "Contract"
    assert row["file_path"] == rel


def test_handle_document_upload_honors_explicit_filename(tmp_path, conn):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-NAME", "Named Upload", "named@example.com"),
    ).lastrowid
    conn.commit()

    boundary = "----HrkitUploadRename"
    body = _make_multipart(boundary, [
        {"name": "employee_id", "value": str(emp_id)},
        {"name": "doc_type", "value": "Policy"},
        {"name": "filename", "value": "renamed-policy.txt"},
        {"name": "file", "filename": "original.txt",
         "content_type": "text/plain",
         "value": b"renamed bytes"},
    ])
    handler = _FakeHandler(body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }, conn=conn, root=tmp_path)
    uploads.handle_document_upload(handler)

    code, payload = handler.json_responses[0]
    assert code == 201
    assert payload["ok"] is True
    assert payload["file_path"].endswith("/renamed-policy.txt")
    assert (tmp_path / payload["file_path"]).read_bytes() == b"renamed bytes"


def test_handle_chat_upload_saves_attachment(tmp_path):
    conn = sqlite3.connect(":memory:")
    boundary = "----HrkitChatUpload"
    body = _make_multipart(boundary, [
        {"name": "file", "filename": "chat-note.txt",
         "content_type": "text/plain",
         "value": b"hello from chat attach"},
    ])
    handler = _FakeHandler(body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }, conn=conn, root=tmp_path)

    uploads.handle_chat_upload(handler)

    assert handler.json_responses, "expected JSON response"
    code, payload = handler.json_responses[0]
    assert code == 201, payload
    assert payload["ok"] is True
    assert payload["filename"] == "chat-note.txt"
    assert payload["rel_path"].endswith("/chat-note.txt")
    assert (tmp_path / payload["rel_path"]).read_bytes() == b"hello from chat attach"


def test_serve_uploaded_file_can_render_inline(tmp_path, conn):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email)"
        " VALUES (?, ?, ?)",
        ("EMP-VIEW", "Viewer", "viewer@example.com"),
    ).lastrowid
    conn.commit()
    rel = uploads.save_uploaded_file(
        workspace_root=tmp_path,
        employee_id=int(emp_id),
        filename="note.txt",
        data=b"hello viewer",
        conn=conn,
    )
    doc_id = conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "Note", "note.txt", rel),
    ).lastrowid
    conn.commit()

    handler = _FakeHandler(body=b"", headers={}, conn=conn, root=tmp_path)
    uploads.serve_uploaded_file(handler, int(doc_id), inline=True)

    assert handler.status_code == 200
    assert ("Content-Disposition", "inline; filename*=UTF-8''note.txt") in handler.sent_headers
    assert handler.wfile.getvalue() == b"hello viewer"
