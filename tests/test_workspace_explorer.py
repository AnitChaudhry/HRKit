from io import BytesIO
from types import SimpleNamespace

import pytest

from hrkit import server, templates, uploads


class _FakeWorkspaceHandler:
    def __init__(self, body, conn=None, workspace_root=None):
        self._body = body
        self.server = SimpleNamespace(conn=conn, workspace_root=workspace_root)
        self.json_responses = []
        self.status_code = None
        self.headers = []
        self.wfile = BytesIO()

    def _read_json(self):
        return dict(self._body)

    def _json(self, obj, code: int = 200):
        self.json_responses.append((code, obj))

    def send_response(self, code: int):
        self.status_code = code

    def send_header(self, key: str, value: str):
        self.headers.append((key, value))

    def end_headers(self):
        pass


def test_workspace_create_folder_api_creates_child(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    handler = _FakeWorkspaceHandler({"path": "", "name": "Month End Exports"})

    server.Handler._api_workspace_create_folder(handler)

    code, payload = handler.json_responses[0]
    assert code == 200
    assert payload["ok"] is True
    assert payload["rel_path"] == "Month End Exports"
    assert (tmp_path / "Month End Exports").is_dir()


def test_workspace_create_folder_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    handler = _FakeWorkspaceHandler({"path": "..", "name": "Escape"})

    with pytest.raises(FileNotFoundError):
        server.Handler._api_workspace_create_folder(handler)
    assert not (tmp_path.parent / "Escape").exists()


def test_home_explorer_has_create_folder_controls():
    html = templates.render_home_page(
        root_name="HR Workspace",
        stats={},
        enabled=[],
    )

    assert "fsCreateFolder()" in html
    assert "/api/workspace/folder" in html
    assert "/workspace/file?path=" in html
    assert "New folder name" in html


def test_document_open_file_and_folder_actions_resolve_upload(conn, tmp_path, monkeypatch):
    emp_id = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email) VALUES (?, ?, ?)",
        ("EMP-OPEN", "Open File", "openfile@example.com"),
    ).lastrowid
    conn.commit()
    rel = uploads.save_uploaded_file(
        workspace_root=tmp_path,
        employee_id=int(emp_id),
        filename="policy.txt",
        data=b"policy",
        conn=conn,
    )
    doc_id = conn.execute(
        "INSERT INTO document (employee_id, doc_type, filename, file_path)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, "Policy", "policy.txt", rel),
    ).lastrowid
    conn.commit()

    opened_files = []
    opened_folders = []
    monkeypatch.setattr(server, "_open_file_os", lambda path: opened_files.append(path))
    monkeypatch.setattr(server, "_open_in_explorer", lambda path: opened_folders.append(path))

    handler = _FakeWorkspaceHandler({}, conn=conn, workspace_root=tmp_path)
    server.Handler._api_open_document_file(handler, int(doc_id), folder=False)
    server.Handler._api_open_document_file(handler, int(doc_id), folder=True)

    assert opened_files and opened_files[0].name == "policy.txt"
    assert opened_folders and opened_folders[0] == opened_files[0].parent
    assert handler.json_responses[0][1]["ok"] is True
    assert handler.json_responses[1][1]["ok"] is True


def test_workspace_file_view_serves_inline_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    (tmp_path / "ai-artifacts").mkdir()
    (tmp_path / "ai-artifacts" / "note.md").write_text("# Saved", encoding="utf-8")
    handler = _FakeWorkspaceHandler({})

    server.Handler._serve_workspace_file(handler, "ai-artifacts/note.md")

    assert handler.status_code == 200
    assert any(k == "Content-Type" and v.startswith("text/") for k, v in handler.headers)
    assert handler.wfile.getvalue() == b"# Saved"
