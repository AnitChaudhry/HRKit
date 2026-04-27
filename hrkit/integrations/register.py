"""Wire the default Composio handlers onto the hook bus.

Called once during app startup (Wave 4 B will invoke this from the CLI /
server bootstrap). Re-registering after :func:`hooks.clear` is safe.
"""
from __future__ import annotations

from . import composio_actions, hooks


def register_default_hooks() -> None:
    """Register the default Composio integrations.

    - ``recruitment.hired``                 -> send offer email via Gmail
    - ``leave.approved``                    -> block Google Calendar
    - ``payroll.payslip_generated``         -> upload payslip PDF to Drive
    - ``onboarding.task_created``           -> calendar event for due date
    - ``coaching.session_scheduled``        -> calendar event for the session
    - ``e_sign.request_created``            -> dispatch via DocuSign / HelloSign
    """
    hooks.on("recruitment.hired", composio_actions.send_offer_email)
    hooks.on("leave.approved", composio_actions.block_calendar_for_leave)
    hooks.on("payroll.payslip_generated", composio_actions.upload_payslip_to_drive)
    hooks.on("onboarding.task_created", composio_actions.create_calendar_event_for_onboarding)
    hooks.on("coaching.session_scheduled", composio_actions.create_calendar_event_for_coaching)
    hooks.on("e_sign.request_created", composio_actions.send_signature_request)
