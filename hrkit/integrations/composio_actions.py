"""Default Composio-backed handlers for the three primary HR events.

Each function follows the same shape so they can be plugged into
``hooks.on(...)``:

    def handler(payload: dict, *, conn) -> dict

Return value contract:
    - ``{ok: True,  result: <composio response dict>}`` on success
    - ``{ok: False, skipped: 'not_configured'}`` when no Composio key is set
    - ``{ok: False, error: str(exc)}`` for any ComposioError raised below

These handlers must never raise; the hook bus already shields callers, but
defending here too keeps log spam low and the contract obvious.
"""
from __future__ import annotations

import logging
from typing import Any

from hrkit import composio_client
from hrkit.composio_client import ComposioError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _not_configured() -> dict:
    return {"ok": False, "skipped": "not_configured"}


def _execute(conn, action_slug: str, params: dict) -> dict:
    """Wrap composio_client.execute_action with the standard result envelope."""
    try:
        response = composio_client.execute_action(conn, action_slug, params)
    except ComposioError as exc:
        log.warning("composio action %s failed: %s", action_slug, exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": response}


# ---------------------------------------------------------------------------
# Public handlers
# ---------------------------------------------------------------------------

def send_offer_email(payload: dict, *, conn: Any) -> dict:
    """Send a templated offer email via Gmail when a candidate is hired.

    Expected payload keys: ``name`` (candidate full name), ``email``
    (recipient), ``position`` (role title, optional). Extra keys are ignored
    so module callers can pass the whole candidate row freely.
    """
    if not composio_client.is_configured(conn):
        return _not_configured()

    payload = payload or {}
    name = str(payload.get("name") or "").strip() or "Candidate"
    email = str(payload.get("email") or "").strip()
    position = str(payload.get("position") or "").strip()

    subject_position = f" — {position}" if position else ""
    subject = f"Offer Letter for {name}{subject_position}"
    body_lines = [
        f"Hi {name},",
        "",
        "We are delighted to extend an offer for the "
        f"{position or 'role'} you interviewed for. The formal offer letter "
        "is attached, and a member of our HR team will reach out shortly to "
        "walk you through the next steps.",
        "",
        "Welcome aboard!",
        "",
        "— HR Team",
    ]
    params = {
        "recipient_email": email,
        "subject": subject,
        "body": "\n".join(body_lines),
    }
    return _execute(conn, "GMAIL_SEND_EMAIL", params)


def block_calendar_for_leave(payload: dict, *, conn: Any) -> dict:
    """Create an all-day Google Calendar event covering an approved leave.

    Expected payload keys: ``employee_name``, ``leave_type`` (optional),
    ``start_date`` (YYYY-MM-DD), ``end_date`` (YYYY-MM-DD), ``calendar_id``
    (defaults to ``'primary'``).
    """
    if not composio_client.is_configured(conn):
        return _not_configured()

    payload = payload or {}
    employee_name = str(payload.get("employee_name") or "Employee").strip()
    leave_type = str(payload.get("leave_type") or "Leave").strip()
    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or start_date).strip()
    calendar_id = str(payload.get("calendar_id") or "primary").strip() or "primary"

    summary = f"{employee_name} — {leave_type}"
    description = str(payload.get("reason") or "").strip()

    params = {
        "calendar_id": calendar_id,
        "summary": summary,
        "description": description,
        "start_datetime": start_date,
        "end_datetime": end_date,
        "all_day": True,
    }
    return _execute(conn, "GOOGLECALENDAR_CREATE_EVENT", params)


def upload_payslip_to_drive(payload: dict, *, conn: Any) -> dict:
    """Upload a generated payslip PDF to Google Drive.

    Expected payload keys: ``file_path`` (absolute path on disk),
    ``filename`` (display name in Drive), ``folder_id`` (optional Drive
    folder), ``mime_type`` (defaults to ``'application/pdf'``).
    """
    if not composio_client.is_configured(conn):
        return _not_configured()

    payload = payload or {}
    file_path = str(payload.get("file_path") or "").strip()
    filename = str(payload.get("filename") or "").strip()
    if not filename and file_path:
        # Derive a reasonable default from the path tail.
        filename = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    folder_id = str(payload.get("folder_id") or "").strip()
    mime_type = str(payload.get("mime_type") or "application/pdf").strip()

    params: dict[str, Any] = {
        "file_path": file_path,
        "file_name": filename,
        "mime_type": mime_type,
    }
    if folder_id:
        params["folder_id"] = folder_id
    return _execute(conn, "GOOGLEDRIVE_UPLOAD_FILE", params)


def create_calendar_event_for_onboarding(payload: dict, *, conn: Any) -> dict:
    """Create a calendar event for an onboarding task due date.

    Expected payload keys: ``employee_name``, ``task_name``, ``due_date``
    (YYYY-MM-DD), ``calendar_id`` (defaults to ``'primary'``).
    """
    if not composio_client.is_configured(conn):
        return _not_configured()
    payload = payload or {}
    summary = (f"Onboarding: {payload.get('task_name') or 'task'} — "
               f"{payload.get('employee_name') or 'employee'}").strip()
    due = str(payload.get("due_date") or "").strip()
    if not due:
        return {"ok": False, "error": "due_date required"}
    return _execute(conn, "GOOGLECALENDAR_CREATE_EVENT", {
        "calendar_id": str(payload.get("calendar_id") or "primary"),
        "summary": summary,
        "description": str(payload.get("description") or ""),
        "start_datetime": due,
        "end_datetime": due,
        "all_day": True,
    })


def create_calendar_event_for_coaching(payload: dict, *, conn: Any) -> dict:
    """Create a calendar event for a scheduled coaching session.

    Expected payload keys: ``mentor_name``, ``mentee_name``, ``scheduled_at``
    (ISO datetime), ``duration_minutes`` (default 30), ``agenda``,
    ``calendar_id`` (defaults to ``'primary'``).
    """
    if not composio_client.is_configured(conn):
        return _not_configured()
    payload = payload or {}
    when = str(payload.get("scheduled_at") or "").strip()
    if not when:
        return {"ok": False, "error": "scheduled_at required"}
    duration = int(payload.get("duration_minutes") or 30)
    summary = (f"1:1 — {payload.get('mentor_name') or '?'} with "
               f"{payload.get('mentee_name') or '?'}").strip()
    return _execute(conn, "GOOGLECALENDAR_CREATE_EVENT", {
        "calendar_id": str(payload.get("calendar_id") or "primary"),
        "summary": summary,
        "description": str(payload.get("agenda") or ""),
        "start_datetime": when,
        "duration_minutes": duration,
        "all_day": False,
    })


def send_signature_request(payload: dict, *, conn: Any) -> dict:
    """Best-effort e-sign dispatch via Composio. Currently a thin stub —
    real DocuSign / HelloSign action slugs depend on customer setup.

    Expected payload keys: ``signature_request_id`` (id in our table),
    ``signer_email``, ``document_path``. Returns ``not_configured`` when
    no Composio key, or the standard envelope on success.
    """
    if not composio_client.is_configured(conn):
        return _not_configured()
    payload = payload or {}
    sig_id = payload.get("signature_request_id")
    if not sig_id:
        return {"ok": False, "error": "signature_request_id required"}
    # Look up the row so we can build the action params.
    row = conn.execute(
        "SELECT employee_id, document_path, document_type, expires_at "
        "FROM signature_request WHERE id = ?", (int(sig_id),)).fetchone()
    if not row:
        return {"ok": False, "error": f"signature_request {sig_id} not found"}
    emp = conn.execute(
        "SELECT full_name, email FROM employee WHERE id = ?",
        (row["employee_id"],)).fetchone()
    params = {
        "signer_email": (emp["email"] if emp else "") or payload.get("signer_email") or "",
        "signer_name": (emp["full_name"] if emp else "") or payload.get("signer_name") or "",
        "file_path": row["document_path"] or payload.get("document_path") or "",
        "title": row["document_type"] or "Document",
    }
    # Try a generic action slug; real wiring may differ per provider.
    result = _execute(conn, "DOCUSIGN_SEND_ENVELOPE", params)
    if result.get("ok"):
        provider_id = ""
        try:
            provider_id = (result.get("result") or {}).get("envelope_id") or ""
        except (AttributeError, TypeError):
            provider_id = ""
        conn.execute("""
            UPDATE signature_request SET status = 'sent', provider_request_id = ?
            WHERE id = ?
        """, (str(provider_id), int(sig_id)))
        conn.commit()
    return result
