"""Local AI artifact persistence for HR Desk.

Anything the assistant creates should leave a human-browsable trail on disk:
chat replies, HTML dashboards, email drafts, web-search notes, and simple PDFs.
All paths stay inside the workspace root.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from hrkit import employee_fs, sandbox
from hrkit.config import IST

ARTIFACTS_DIR = "ai-artifacts"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HTML_FENCE_RE = re.compile(r"```(?:html|htm)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_GENERIC_FENCE_RE = re.compile(r"```([a-z0-9_-]*)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_BAD_CHARS = set('<>:"|?*\\/\x00')


def _now() -> datetime:
    return datetime.now(IST)


def _slugify(value: str, fallback: str = "artifact", limit: int = 64) -> str:
    slug = _SLUG_RE.sub("-", (value or "").lower()).strip("-")
    return (slug or fallback)[:limit].strip("-") or fallback


def _safe_filename(name: str, fallback: str = "artifact.md") -> str:
    raw = (name or "").strip() or fallback
    cleaned = "".join("_" if c in _BAD_CHARS or ord(c) < 32 else c for c in raw)
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned in (".", ".."):
        cleaned = fallback
    if "." not in cleaned and "." in fallback:
        cleaned += Path(fallback).suffix
    return cleaned[:140]


def _conversation_segment(conversation_id: str) -> str:
    return _safe_filename(conversation_id or "draft", fallback="draft").replace(".", "-")


def _base_dir(
    workspace_root: str | Path,
    *,
    conversation_id: str = "",
    employee_code: str | None = None,
    category: str = "",
) -> Path:
    root = Path(workspace_root)
    day = _now().strftime("%Y-%m-%d")
    category_slug = _slugify(category, "general")
    if employee_code:
        base = employee_fs.ensure_employee_layout(root, employee_code) / ARTIFACTS_DIR
    else:
        base = root / ARTIFACTS_DIR
    parts = [day, category_slug]
    if conversation_id:
        parts.append(_conversation_segment(conversation_id))
    target = base.joinpath(*parts).resolve()
    sandbox.assert_path_in_workspace(target, root)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / _safe_filename(filename)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for i in range(2, 1000):
        nxt = directory / f"{stem}-{i}{suffix}"
        if not nxt.exists():
            return nxt
    raise FileExistsError(f"could not allocate unique artifact name for {filename}")


def _rel(workspace_root: str | Path, path: Path) -> str:
    return path.resolve().relative_to(Path(workspace_root).resolve()).as_posix()


def _record(path: Path, workspace_root: str | Path, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "filename": path.name,
        "rel_path": _rel(workspace_root, path),
        "size": path.stat().st_size,
    }


def save_text_artifact(
    workspace_root: str | Path,
    *,
    conversation_id: str = "",
    employee_code: str | None = None,
    category: str = "general",
    filename: str,
    body: str,
    kind: str | None = None,
) -> dict[str, Any]:
    directory = _base_dir(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category=category,
    )
    path = _unique_path(directory, filename)
    path.write_text(str(body or ""), encoding="utf-8")
    return _record(path, workspace_root, kind or (path.suffix.lstrip(".") or "text"))


def _extract_email_headers(text: str) -> tuple[str, str, str]:
    to = ""
    subject = "AI draft"
    remaining: list[str] = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(to|subject)\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
        if m:
            key = m.group(1).lower()
            if key == "to":
                to = m.group(2)
            elif key == "subject":
                subject = m.group(2) or subject
            continue
        remaining.append(line)
    body = "\n".join(remaining).strip() or text
    return to, subject, body


def save_email_artifact(
    workspace_root: str | Path,
    *,
    conversation_id: str = "",
    employee_code: str | None = None,
    title: str = "AI email draft",
    body: str = "",
    html_body: str = "",
    filename: str = "",
) -> dict[str, Any]:
    to, subject, plain = _extract_email_headers(body or "")
    msg = EmailMessage()
    msg["Subject"] = subject or title or "AI email draft"
    msg["To"] = to
    msg["From"] = "local-hr-draft@hr-desk.local"
    msg["X-HR-Desk-Artifact"] = "true"
    msg.set_content(plain or body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    base_name = filename or f"{_slugify(subject or title, 'email-draft')}.eml"
    return save_text_artifact(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category="email",
        filename=base_name,
        body=msg.as_string(),
        kind="email",
    )


def _pdf_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str, width: int = 92) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.expandtabs(4)
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            if cut < 20:
                cut = width
            lines.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        lines.append(line)
    return lines or [""]


def build_simple_pdf(title: str, body: str) -> bytes:
    """Return a small valid text PDF using only stdlib primitives."""
    objects: list[bytes] = []
    lines = [title.strip() or "AI Artifact", ""] + _wrap_lines(body)
    y = 760
    commands = ["BT", "/F1 18 Tf", f"72 {y} Td", f"({_pdf_escape(lines[0])}) Tj"]
    y -= 28
    commands.extend(["/F1 10 Tf", f"0 -28 Td"])
    for line in lines[1:120]:
        commands.append(f"({_pdf_escape(line)}) Tj")
        commands.append("0 -14 Td")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def save_pdf_artifact(
    workspace_root: str | Path,
    *,
    conversation_id: str = "",
    employee_code: str | None = None,
    title: str,
    body: str,
    filename: str = "",
) -> dict[str, Any]:
    directory = _base_dir(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category="pdf",
    )
    path = _unique_path(directory, filename or f"{_slugify(title, 'ai-report')}.pdf")
    path.write_bytes(build_simple_pdf(title, body))
    return _record(path, workspace_root, "pdf")


def looks_like_email(text: str) -> bool:
    body = text or ""
    has_subject = re.search(r"(?im)^\s*subject\s*:", body) is not None
    has_to = re.search(r"(?im)^\s*to\s*:", body) is not None
    return has_subject or (has_to and re.search(r"(?im)^\s*(dear|hi|hello)\b", body) is not None)


def _html_blocks(text: str) -> list[str]:
    blocks = [m.group(1).strip() for m in _HTML_FENCE_RE.finditer(text or "") if m.group(1).strip()]
    stripped = (text or "").strip()
    if re.search(r"(?is)<html[\s>].*</html>", stripped) or stripped.lower().startswith("<!doctype html"):
        blocks.append(stripped)
    return blocks


def autosave_chat_reply(
    workspace_root: str | Path,
    *,
    conversation_id: str,
    employee_code: str | None,
    user_message: str,
    reply: str,
    turn_count: int,
) -> list[dict[str, Any]]:
    if not reply:
        return []
    stem = f"turn-{max(1, int(turn_count or 1)):04d}"
    saved: list[dict[str, Any]] = []
    md_body = (
        f"# Assistant reply\n\n"
        f"Saved: {_now().isoformat(timespec='seconds')}\n\n"
        f"User request: {user_message.strip() or '(attachment only)'}\n\n"
        f"---\n\n{reply.strip()}\n"
    )
    saved.append(save_text_artifact(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category="chat",
        filename=f"{stem}-assistant-reply.md",
        body=md_body,
        kind="markdown",
    ))

    for i, block in enumerate(_html_blocks(reply), start=1):
        saved.append(save_text_artifact(
            workspace_root,
            conversation_id=conversation_id,
            employee_code=employee_code,
            category="html",
            filename=f"{stem}-html-{i}.html",
            body=block,
            kind="html",
        ))

    if looks_like_email(reply):
        saved.append(save_email_artifact(
            workspace_root,
            conversation_id=conversation_id,
            employee_code=employee_code,
            title=user_message[:80] or "AI email draft",
            body=reply,
            filename=f"{stem}-email-draft.eml",
        ))
    return saved


def save_web_result(
    workspace_root: str | Path,
    *,
    query_or_url: str,
    result: str,
    source_type: str,
    conversation_id: str = "",
    employee_code: str | None = None,
) -> dict[str, Any]:
    title = f"{source_type}: {query_or_url}".strip()
    body = (
        f"# {title}\n\n"
        f"Saved: {_now().isoformat(timespec='seconds')}\n\n"
        f"```\n{result or ''}\n```\n"
    )
    return save_text_artifact(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category="web-search" if source_type == "web_search" else "web-fetch",
        filename=f"{_slugify(query_or_url, source_type)}.md",
        body=body,
        kind=source_type,
    )


def save_artifact_by_kind(
    workspace_root: str | Path,
    *,
    kind: str,
    title: str,
    body: str,
    filename: str = "",
    conversation_id: str = "",
    employee_code: str | None = None,
) -> dict[str, Any]:
    normalized = (kind or "markdown").strip().lower()
    title = title or "AI artifact"
    if normalized in {"pdf", "report-pdf"}:
        return save_pdf_artifact(
            workspace_root,
            conversation_id=conversation_id,
            employee_code=employee_code,
            title=title,
            body=body,
            filename=filename,
        )
    if normalized in {"email", "eml", "email-draft"}:
        return save_email_artifact(
            workspace_root,
            conversation_id=conversation_id,
            employee_code=employee_code,
            title=title,
            body=body,
            filename=filename,
        )
    suffix = {
        "html": ".html",
        "markdown": ".md",
        "md": ".md",
        "csv": ".csv",
        "json": ".json",
        "text": ".txt",
        "txt": ".txt",
    }.get(normalized, ".md")
    if not filename:
        filename = f"{_slugify(title)}{suffix}"
    if normalized == "html" and "<html" not in (body or "").lower():
        body = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title></head><body>{body}</body></html>"
        )
    if normalized == "json":
        try:
            body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    return save_text_artifact(
        workspace_root,
        conversation_id=conversation_id,
        employee_code=employee_code,
        category=normalized,
        filename=filename,
        body=body,
        kind=normalized,
    )

