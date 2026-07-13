"""Opt-in confirmations and admin notification emails.

ponytail: stub — the SMTP/messenger subsystem isn't migrated yet, so these log
and skip sending instead of crashing the endpoints that call them. Implement
with aiosmtplib + tmpl.render_system_email + the `smtp` settings blocks when
email sending is ported.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("listmonk")


async def send_optin_confirmation_by_id(sub_id: int) -> bool:
    log.warning(
        "opt-in confirmation for subscriber %s not sent: SMTP subsystem not yet migrated", sub_id
    )
    return False


async def notify_admins(template: str, subject: str, data: dict[str, Any]) -> None:
    log.warning("admin notification %r (%s) not sent: SMTP subsystem not yet migrated", template, subject)
