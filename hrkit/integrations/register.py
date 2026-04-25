"""Wire the default Composio handlers onto the hook bus.

Called once during app startup (Wave 4 B will invoke this from the CLI /
server bootstrap). Re-registering after :func:`hooks.clear` is safe.
"""
from __future__ import annotations

from . import composio_actions, hooks


def register_default_hooks() -> None:
    """Register the three default Composio integrations.

    - ``recruitment.hired``           -> send offer email via Gmail
    - ``leave.approved``              -> block Google Calendar
    - ``payroll.payslip_generated``   -> upload payslip PDF to Drive
    """
    hooks.on("recruitment.hired", composio_actions.send_offer_email)
    hooks.on("leave.approved", composio_actions.block_calendar_for_leave)
    hooks.on("payroll.payslip_generated", composio_actions.upload_payslip_to_drive)
