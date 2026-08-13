"""Opt-in confirmations and admin notification emails — port of internal/notifs."""

from __future__ import annotations

import logging
from typing import Any

from app import manager, settings, tmpl
from app.repos import subscriber_repo

log = logging.getLogger("listmonk")


async def send_email(to: str, subject: str, html: str) -> None:
    """Send one system email (password reset, SMTP test, …). Raises on failure."""
    await manager.send(to=to, subject=subject, html=html, text=tmpl.html_to_text(html))


async def send_optin_confirmation_by_id(sub_id: int) -> bool:
    """Send the double opt-in confirmation for a subscriber's unconfirmed lists.

    Returns False when there is nothing to confirm (no double opt-in lists
    pending), matching the original's behaviour.
    """
    sub = await subscriber_repo.get_subscriber(sub_id)
    if not sub:
        return False

    lists = await subscriber_repo.get_subscriber_lists(
        sub_id=sub_id, status="unconfirmed", optin="double"
    )
    if not lists:
        return False

    root = (settings.get("app.root_url") or "").rstrip("/")
    html = tmpl.render_system_email(
        "subscriber-optin",
        {
            "Subscriber": tmpl.subscriber_ctx(sub),
            "Lists": lists,
            "OptinURL": f"{root}/subscription/optin/{sub['uuid']}",
            "OptinURLAttrib": f"{root}/subscription/optin/{sub['uuid']}",
        },
    )

    await manager.send(
        to=sub["email"],
        subject=f"Confirm subscription(s) - {settings.get('app.site_name') or 'listmonk'}",
        html=html,
        text=tmpl.html_to_text(html),
    )
    return True


async def notify_admins(template: str, subject: str, data: dict[str, Any]) -> None:
    """Email the addresses in `app.notify_emails` (best effort — never raises)."""
    to = [e.strip() for e in (settings.get("app.notify_emails") or []) if e.strip()]
    if not to:
        return

    try:
        html = tmpl.render_system_email(template, data)
        text = tmpl.html_to_text(html)
        for addr in to:
            await manager.send(to=addr, subject=subject, html=html, text=text)
    except Exception:
        # Notifications must never break the request that triggered them.
        log.exception("failed sending admin notification %r (%s)", template, subject)
