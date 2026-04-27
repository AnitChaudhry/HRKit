"""File-upload helpers for the HR app.

Wave 4 Agent A5 deliverable. Provides:

* :func:`parse_multipart` — stdlib-only ``multipart/form-data`` parser.
* :func:`save_uploaded_file` — write bytes under ``.hrkit/uploads/employee/<id>/``.
* :func:`handle_document_upload` — POST handler for ``/api/m/document/upload``.
* :func:`serve_uploaded_file` — GET handler for ``/api/m/document/<id>/download``.

Stdlib only. The new HTTP routes are wired up by Wave 4 B; this module does not
import :mod:`hrkit.server`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB hard limit

_BAD_FILENAME_CHARS = set('<>:"|?*\\/\x00')

_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


# ---------------------------------------------------------------------------
# Multipart parsing
# ---------------------------------------------------------------------------
def _extract_boundary(content_type: str) -> bytes:
    """Pull the ``boundary=...`` token out of a Content-Type header."""
    if not content_type:
        raise ValueError("missing Content-Type header")
    parts = [p.strip() for p in content_type.split(";")]
    boundary = ""
    for part in parts:
        if part.lower().startswith("boundary="):
            boundary = part.split("=", 1)[1].strip()
            if boundary.startswith('"') and boundary.endswith('"'):
                boundary = boundary[1:-1]
            break
    if not boundary:
        raise ValueError("missing multipart boundary")
    return boundary.encode("ascii", errors="replace")


def _parse_disposition(line: str) -> dict[str, str]:
    """Parse a ``Content-Disposition: form-data; name="x"; filename="y"`` line."""
    out: dict[str, str] = {}
    for token in line.split(";"):
        token = token.strip()
        if "=" not in token:
            continue
        k, _, v = token.partition("=")
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out[k.strip().lower()] = v
    return out


def parse_multipart(handler) -> dict[str, Any]:
    """Parse a ``multipart/form-data`` request body off ``handler.rfile``.

    Returns ``{'fields': {name: value}, 'files': [{name, filename,
    content_type, data}]}``. Raises :class:`ValueError` on malformed input or
    if Content-Length exceeds ``MAX_UPLOAD_BYTES``.
    """
    content_type = handler.headers.get("content-type", "")
    boundary = _extract_boundary(content_type)
    try:
        length = int(handler.headers.get("content-length", "0") or "0")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0:
        raise ValueError("empty request body")
    if length > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"upload too large: {length} bytes (max {MAX_UPLOAD_BYTES})"
        )

    body = handler.rfile.read(length)
    delimiter = b"--" + boundary
    closing = delimiter + b"--"

    # Split on the boundary delimiter. Skip the preamble (chunk 0) and the
    # closing chunk after "--<boundary>--".
    chunks = body.split(delimiter)
    fields: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    for chunk in chunks[1:]:
        # Trim leading CRLF and stop at the closing marker.
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        # Trim trailing CRLF that precedes the next delimiter.
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        elif chunk.endswith(b"\n"):
            chunk = chunk[:-1]
        if not chunk:
            continue
        # Headers separated from body by blank line.
        sep = chunk.find(b"\r\n\r\n")
        if sep == -1:
            sep = chunk.find(b"\n\n")
            if sep == -1:
                continue
            head_bytes = chunk[:sep]
            data = chunk[sep + 2:]
        else:
            head_bytes = chunk[:sep]
            data = chunk[sep + 4:]
        head_text = head_bytes.decode("utf-8", errors="replace")
        disposition = ""
        ctype = "application/octet-stream"
        for line in head_text.splitlines():
            low = line.lower()
            if low.startswith("content-disposition:"):
                disposition = line.split(":", 1)[1].strip()
            elif low.startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        if not disposition:
            continue
        attrs = _parse_disposition(disposition)
        name = attrs.get("name", "")
        if not name:
            continue
        filename = attrs.get("filename")
        if filename:
            files.append({
                "name": name,
                "filename": filename,
                "content_type": ctype,
                "data": data,
            })
        else:
            fields[name] = data.decode("utf-8", errors="replace")
    # closing marker check is best-effort
    _ = closing
    return {"fields": fields, "files": files}


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------
def _sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base or base in (".", ".."):
        raise ValueError("invalid filename")
    cleaned = "".join("_" if c in _BAD_FILENAME_CHARS or ord(c) < 32 else c
                      for c in base)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise ValueError("invalid filename")
    return cleaned[:200]


def _legacy_uploads_root(workspace_root: Path, employee_id: int) -> Path:
    from .config import META_DIR
    return Path(workspace_root) / META_DIR / "uploads" / "employee" / str(int(employee_id))


def _employee_code_for(conn: Any, employee_id: int) -> str:
    """Best-effort employee_code lookup; '' if conn is missing or row not found."""
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT employee_code FROM employee WHERE id = ?", (int(employee_id),),
        ).fetchone()
    except Exception:  # noqa: BLE001
        return ""
    if not row:
        return ""
    return str(row["employee_code"] if hasattr(row, "keys") else row[0] or "").strip()


def save_uploaded_file(
    *,
    workspace_root: Path,
    employee_id: int,
    filename: str,
    data: bytes,
    conn: Any = None,
) -> str:
    """Write ``data`` into the employee's documents dir and return the relpath.

    New layout (preferred): ``<workspace>/employees/<EMP-CODE>/documents/<file>``
    (Phase 1.7 — see :mod:`hrkit.employee_fs`). When ``conn`` is supplied we
    look up the employee_code and write under the new layout. If the code
    can't be resolved we fall back to the legacy
    ``.hrkit/uploads/employee/<id>/<file>`` location so existing tests and
    pre-Phase-1.7 callers keep working.

    Handles name collisions by appending ``-2``, ``-3``, ... before the
    extension. The returned string is suitable for storing in the
    ``document.file_path`` column.
    """
    from .config import META_DIR
    safe = _sanitize_filename(filename)
    code = _employee_code_for(conn, employee_id)
    if code:
        from . import employee_fs
        target_dir = employee_fs.documents_dir(workspace_root, code)
        rel_prefix = (
            f"{employee_fs.EMPLOYEES_DIR}/{code}/{employee_fs.DOCUMENTS_SUBDIR}"
        )
    else:
        target_dir = _legacy_uploads_root(workspace_root, employee_id)
        rel_prefix = f"{META_DIR}/uploads/employee/{int(employee_id)}"

    target_dir.mkdir(parents=True, exist_ok=True)
    candidate = target_dir / safe
    if candidate.exists():
        stem, dot, ext = safe.rpartition(".")
        if not dot:
            stem, ext = safe, ""
        suffix = f".{ext}" if ext else ""
        n = 2
        while True:
            new_name = f"{stem}-{n}{suffix}"
            candidate = target_dir / new_name
            if not candidate.exists():
                safe = new_name
                break
            n += 1
    candidate.write_bytes(data)
    return f"{rel_prefix}/{safe}"


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------
def _workspace_root_for(handler) -> Path:
    """Resolve the workspace root from the running server (or a test override)."""
    server = getattr(handler, "server", None)
    root = getattr(server, "workspace_root", None) if server else None
    if root:
        return Path(root)
    try:
        from . import server as server_mod
        if server_mod.ROOT is not None:
            return Path(server_mod.ROOT)
    except Exception:
        pass
    raise RuntimeError("workspace root not configured")


def _conn_for(handler) -> sqlite3.Connection:
    server = getattr(handler, "server", None)
    conn = getattr(server, "conn", None) if server else None
    if conn is not None:
        return conn
    return getattr(handler, "conn", None)  # type: ignore[return-value]


def handle_document_upload(handler) -> None:
    """POST /api/m/document/upload — multipart with ``employee_id`` + 1 file."""
    try:
        parsed = parse_multipart(handler)
    except ValueError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    fields = parsed["fields"]
    files = parsed["files"]
    emp_raw = fields.get("employee_id", "").strip()
    if not emp_raw:
        handler._json({"ok": False, "error": "employee_id required"}, code=400)
        return
    try:
        employee_id = int(emp_raw)
    except ValueError:
        handler._json({"ok": False, "error": "invalid employee_id"}, code=400)
        return
    if not files:
        handler._json({"ok": False, "error": "no file in upload"}, code=400)
        return
    upload = files[0]
    filename = upload.get("filename") or "file"
    data = upload.get("data") or b""
    try:
        rel_path = save_uploaded_file(
            workspace_root=_workspace_root_for(handler),
            employee_id=employee_id,
            filename=filename,
            data=data,
            conn=_conn_for(handler),
        )
    except (ValueError, OSError) as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return

    doc_type = fields.get("doc_type", "").strip() or "file"
    notes = fields.get("notes", "").strip()
    expiry = fields.get("expiry_date", "").strip()
    safe_name = Path(rel_path).name
    conn = _conn_for(handler)
    cols = ["employee_id", "doc_type", "filename", "file_path"]
    vals: list[Any] = [employee_id, doc_type, safe_name, rel_path]
    if expiry:
        cols.append("expiry_date")
        vals.append(expiry)
    if notes:
        cols.append("notes")
        vals.append(notes)
    placeholders = ", ".join("?" for _ in cols)
    try:
        cur = conn.execute(
            f"INSERT INTO document ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    handler._json(
        {"ok": True, "document_id": int(cur.lastrowid), "file_path": rel_path},
        code=201,
    )


def _mime_for(name: str) -> str:
    return _MIME.get(Path(name).suffix.lower(), "application/octet-stream")


def serve_uploaded_file(handler, document_id: int) -> None:
    """GET /api/m/document/<id>/download — stream the stored upload."""
    conn = _conn_for(handler)
    row = conn.execute(
        "SELECT file_path, filename FROM document WHERE id = ?",
        (int(document_id),),
    ).fetchone()
    if not row:
        handler._send(404, b"document not found", "text/plain; charset=utf-8")
        return
    file_path = row["file_path"] if hasattr(row, "keys") else row[0]
    filename = row["filename"] if hasattr(row, "keys") else row[1]
    try:
        workspace_root = _workspace_root_for(handler)
    except RuntimeError as exc:
        handler._send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
        return
    target = (workspace_root / file_path).resolve()
    from .config import META_DIR
    from . import employee_fs
    legacy_root = (workspace_root / META_DIR / "uploads").resolve()
    new_root = (workspace_root / employee_fs.EMPLOYEES_DIR).resolve()
    allowed = False
    for root in (legacy_root, new_root):
        try:
            target.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    if not target.exists() or not target.is_file():
        handler._send(404, b"file missing on disk", "text/plain; charset=utf-8")
        return
    try:
        data = target.read_bytes()
    except OSError as exc:
        handler._send(500, f"read error: {exc}".encode("utf-8"),
                      "text/plain; charset=utf-8")
        return
    safe_disp = quote(filename or target.name)
    handler.send_response(200)
    handler.send_header("Content-Type", _mime_for(filename or target.name))
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header(
        "Content-Disposition",
        f"attachment; filename*=UTF-8''{safe_disp}",
    )
    handler.send_header("Cache-Control", "private, max-age=60")
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionError):
        pass


__all__ = [
    "MAX_UPLOAD_BYTES",
    "parse_multipart",
    "save_uploaded_file",
    "handle_document_upload",
    "serve_uploaded_file",
    "save_chat_attachment",
    "extract_text_for_ai",
    "handle_chat_upload",
]


# ---------------------------------------------------------------------------
# Chat attachments (Phase 1.6c)
# ---------------------------------------------------------------------------
_CHAT_ATTACH_DIR_NAME = "chat"
_TEXT_EXTRACT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".xml", ".html", ".htm", ".log", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".java", ".go", ".rs", ".rb", ".sh", ".sql", ".env",
}
_MAX_EXTRACT_CHARS = 20_000


def save_chat_attachment(
    *,
    workspace_root: Path,
    filename: str,
    data: bytes,
) -> dict[str, str | int]:
    """Save a chat-uploaded file to ``.hrkit/uploads/chat/<id>/<filename>``.

    Returns ``{"id": str, "filename": str, "rel_path": str, "size": int}``.
    The id is a short uuid so two uploads with the same filename don't clash.
    """
    import uuid
    from .config import META_DIR
    safe = _sanitize_filename(filename)
    upload_id = uuid.uuid4().hex[:10]
    target_dir = Path(workspace_root) / META_DIR / "uploads" / _CHAT_ATTACH_DIR_NAME / upload_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe
    target.write_bytes(data)
    rel = f"{META_DIR}/uploads/{_CHAT_ATTACH_DIR_NAME}/{upload_id}/{safe}"
    return {"id": upload_id, "filename": safe, "rel_path": rel, "size": len(data)}


def extract_text_for_ai(workspace_root: Path, rel_path: str) -> str:
    """Best-effort text extraction so the AI has something to read.

    For known text-ish extensions, returns the file content (capped). For
    binary types (PDFs, images, .docx, ...) returns a short placeholder
    note pointing at the path so the AI knows the file exists but cannot
    inline-read it without a vision/OCR model.
    """
    target = (Path(workspace_root) / rel_path).resolve()
    if not target.exists():
        return f"[attachment missing on disk: {rel_path}]"
    ext = target.suffix.lower()
    if ext in _TEXT_EXTRACT_EXTS:
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"[failed to read {rel_path}: {exc}]"
        if len(text) > _MAX_EXTRACT_CHARS:
            text = text[:_MAX_EXTRACT_CHARS] + (
                f"\n... [truncated; {len(text) - _MAX_EXTRACT_CHARS} more chars]"
            )
        return text
    return (
        f"[binary file at {rel_path} ({target.stat().st_size} bytes). "
        f"Reference by name; cannot inline-read without an OCR/vision tool.]"
    )


def handle_chat_upload(handler) -> None:
    """POST /api/chat/upload — accept one file, save under .hrkit/uploads/chat/."""
    try:
        parsed = parse_multipart(handler)
    except ValueError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    files = parsed.get("files") or []
    if not files:
        handler._json({"ok": False, "error": "no file in upload"}, code=400)
        return
    upload = files[0]
    filename = upload.get("filename") or "file"
    data = upload.get("data") or b""
    try:
        info = save_chat_attachment(
            workspace_root=_workspace_root_for(handler),
            filename=filename,
            data=data,
        )
    except (ValueError, OSError) as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    handler._json({"ok": True, **info}, code=201)
