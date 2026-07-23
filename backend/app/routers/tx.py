"""Transactional message API — port of cmd/tx.go.

POST /api/tx sends a one-off message rendered through a `tx` template. Accepts
either JSON or multipart/form-data (a `data` JSON part plus `file` attachments).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import auth, db, manager, settings, tmpl
from app.utils import bad_request, ok

log = logging.getLogger("listmonk")

router = APIRouter(tags=["tx"])

# default : look the subscriber up in the DB, error if missing.
# fallback: look up, fall back to an ephemeral subscriber if missing.
# external: never touch the DB, always ephemeral.
_MODES = {"default", "fallback", "external"}


class TxPayload(BaseModel):
    subscriber_email: str = ""
    subscriber_emails: list[str] = Field(default_factory=list)
    subscriber_id: int = 0
    subscriber_ids: list[int] = Field(default_factory=list)
    subscriber_mode: str = "default"
    template_id: int
    from_email: str = ""
    subject: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    headers: list[dict[str, str]] = Field(default_factory=list)
    messenger: str = "email"
    content_type: str = "html"


def _validate(m: TxPayload) -> TxPayload:
    """Port of validateTxMessage."""
    if m.subscriber_emails and m.subscriber_email:
        raise bad_request("do not send both `subscriber_email` and `subscriber_emails`")
    if m.subscriber_ids and m.subscriber_id:
        raise bad_request("do not send both `subscriber_id` and `subscriber_ids`")

    if m.subscriber_email:
        m.subscriber_emails = [*m.subscriber_emails, m.subscriber_email]
    if m.subscriber_id:
        m.subscriber_ids = [*m.subscriber_ids, m.subscriber_id]

    m.subscriber_mode = m.subscriber_mode or "default"
    if m.subscriber_mode not in _MODES:
        raise bad_request("invalid `subscriber_mode`")

    if m.subscriber_mode == "default":
        # Exactly one of emails / ids.
        if bool(m.subscriber_emails) == bool(m.subscriber_ids):
            raise bad_request("send either `subscriber_emails` or `subscriber_ids`")
    else:
        if m.subscriber_ids:
            raise bad_request("`subscriber_ids` not allowed in fallback or external mode")
        if not m.subscriber_emails:
            raise bad_request("`subscriber_emails` is required")

    m.subscriber_emails = [e.strip().lower() for e in m.subscriber_emails if e.strip()]
    for e in m.subscriber_emails:
        if "@" not in e or len(e) > 320:
            raise bad_request(f"invalid email: {e}")

    if not m.from_email:
        m.from_email = settings.get("app.from_email") or ""
    if not m.messenger:
        m.messenger = "email"
    elif manager._smtp_block(m.messenger) is None:
        raise bad_request(f"unknown messenger: {m.messenger}")

    return m


async def _parse_request(request: Request) -> tuple[TxPayload, list[dict[str, Any]]]:
    """Read the payload from JSON or from a multipart form with attachments."""
    ctype = request.headers.get("content-type", "")
    attachments: list[dict[str, Any]] = []

    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        raw = form.get("data")
        if not raw or not isinstance(raw, str):
            raise bad_request("missing `data` field")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            raise bad_request(f"invalid `data` JSON: {e}") from None

        for f in form.getlist("file"):
            if isinstance(f, str):
                continue
            attachments.append(
                {
                    "name": f.filename or "attachment",
                    "content_type": f.content_type or "application/octet-stream",
                    "content": await f.read(),
                }
            )
    else:
        body = await request.json()

    return TxPayload(**body), attachments


@router.post("/api/tx", dependencies=[auth.require("tx:send")])
async def send_tx(request: Request):
    payload, attachments = await _parse_request(request)
    m = _validate(payload)

    rows = await db.fetch("get-templates", m.template_id, False, "")
    if not rows:
        raise bad_request(f"template {m.template_id} not found")
    template = rows[0]
    if template["type"] != "tx":
        raise bad_request(f"template {m.template_id} is not a transactional template")

    # Build the recipient list: either emails or IDs, per subscriber_mode.
    targets: list[tuple[int, str]] = (
        [(0, e) for e in m.subscriber_emails]
        if m.subscriber_emails
        else [(i, "") for i in m.subscriber_ids]
    )

    not_found: list[str] = []
    for sub_id, email in targets:
        if m.subscriber_mode == "external":
            sub: dict[str, Any] | None = {"email": email, "name": email, "attribs": {}}
        else:
            sub = await db.fetchrow("get-subscriber", sub_id, None, email)
            if not sub:
                if m.subscriber_mode == "fallback":
                    sub = {"email": email, "name": email, "attribs": {}}
                else:
                    not_found.append(email or f"id {sub_id}")
                    continue

        subject, html = tmpl.render_tx(
            template["body"], m.subject or template.get("subject") or "", sub, m.data
        )
        text = tmpl.html_to_text(html) if m.content_type != "plain" else html

        try:
            await manager.send(
                to=sub["email"],
                subject=subject,
                html="" if m.content_type == "plain" else html,
                text=text,
                from_email=m.from_email,
                messenger=m.messenger,
                headers=m.headers,
                attachments=attachments,
            )
        except Exception as e:
            log.error("tx send to %s failed: %s", sub["email"], e)
            raise bad_request(f"error sending message: {e}") from None

    if not_found:
        raise bad_request("subscribers not found: " + "; ".join(not_found))

    return ok(True)
