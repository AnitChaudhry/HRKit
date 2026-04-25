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
