"""Bounce endpoints and webhooks — port of cmd/bounce.go.

Covers the admin bounce CRUD plus the webhook receivers. The IMAP/POP mailbox
scanner (internal/bounce's mailbox poller) is not implemented — ponytail: add a
polling task registered from manager.start() if mailbox-based bounce processing
is needed; webhooks cover the common SES/SendGrid/Postmark setups.
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app import auth, db, settings
from app.utils import Pagination, bad_request, not_found, ok

log = logging.getLogger("listmonk")

router = APIRouter(tags=["bounces"])

_ORDER_FIELDS = {"created_at", "id", "email"}
_TYPES = {"soft", "hard", "complaint"}


@router.get("/api/bounces", dependencies=[auth.require("bounces:get")])
async def get_bounces(
    pg: Pagination = Depends(),
    campaign_id: int = 0,
    subscriber_id: int = 0,
    source: str = "",
    order_by: str = "created_at",
    order: str = "DESC",
) -> dict[str, Any]:
    field = order_by if order_by in _ORDER_FIELDS else "created_at"
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    sql = db.q("query-bounces").replace("%order%", f"{field} {direction}")
    rows = await db.fetch(sql, 0, campaign_id, subscriber_id, source, pg.offset, pg.limit)
    total = rows[0]["total"] if rows else 0
    for r in rows:
        r.pop("total", None)
    return ok(pg.results(rows, total, ""))


@router.get("/api/bounces/{bounce_id}", dependencies=[auth.require("bounces:get")])
async def get_bounce(bounce_id: int) -> dict[str, Any]:
    sql = db.q("query-bounces").replace("%order%", "created_at DESC")
    rows = await db.fetch(sql, bounce_id, 0, 0, "", 0, 1)
    if not rows:
        raise not_found("bounce not found")
    rows[0].pop("total", None)
    return ok(rows[0])


@router.delete("/api/bounces", dependencies=[auth.require("bounces:manage")])
async def delete_bounces(id: list[int] = Query(default=[]), all: bool = False) -> dict[str, Any]:
    if not id and not all:
        raise bad_request("no bounce IDs given")
    await db.execute("delete-bounces", id, all)
    return ok(True)


@router.delete("/api/bounces/{bounce_id}", dependencies=[auth.require("bounces:manage")])
async def delete_bounce(bounce_id: int) -> dict[str, Any]:
    await db.execute("delete-bounces", [bounce_id], False)
    return ok(True)


@router.put("/api/bounces/blocklist", dependencies=[auth.require("bounces:manage")])
async def blocklist_bounced() -> dict[str, Any]:
    await db.execute("blocklist-bounced-subscribers")
    return ok(True)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


async def record(
    email: str = "",
    sub_uuid: str = "",
    camp_uuid: str = "",
    btype: str = "hard",
    source: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    """Record one bounce, applying the configured blocklist/delete action."""
    if btype not in _TYPES:
        btype = "hard"
    if not email and not sub_uuid:
        raise bad_request("bounce needs a subscriber email or UUID")

    actions = settings.get("bounce.actions") or {}
    cfg = actions.get(btype) or {}
    count = int(cfg.get("count") or 0)
    action = cfg.get("action") or "none"

    from datetime import datetime

    await db.execute(
        "record-bounce",
        sub_uuid,
        (email or "").strip().lower(),
        camp_uuid,
        btype,
        source,
        meta or {},
        datetime.now(UTC),
        count,
        action,
    )


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def _enabled() -> None:
    if not settings.get("bounce.enabled", False):
        raise bad_request("bounce processing is disabled")
    if not settings.get("bounce.webhooks_enabled", False):
        raise bad_request("bounce webhooks are disabled")


@router.post("/webhooks/bounce", dependencies=[auth.require("webhooks:post_bounce")])
async def bounce_webhook(request: Request) -> dict[str, Any]:
    """Authenticated generic bounce endpoint (listmonk's own JSON format)."""
    _enabled()
    body = await request.json()
    await record(
        email=body.get("email", ""),
        sub_uuid=body.get("subscriber_uuid", ""),
        camp_uuid=body.get("campaign_uuid", ""),
        btype=body.get("type", "hard"),
        source=body.get("source", "api"),
        meta=body.get("meta") or {},
    )
    return ok(True)


@router.post("/webhooks/service/{service}", include_in_schema=False)
async def bounce_service_webhook(service: str, request: Request) -> dict[str, Any]:
    """Public, provider-specific bounce webhooks (SES, SendGrid, Postmark)."""
    _enabled()
    service = service.lower()
    body = await request.json()

    if service == "ses":
        if not settings.get("bounce.ses_enabled", False):
            raise bad_request("SES bounce processing is disabled")
        # SNS wraps the payload as a JSON string in "Message".
        import json

        if body.get("Type") == "SubscriptionConfirmation":
            return ok(True)
        msg = body.get("Message")
        msg = json.loads(msg) if isinstance(msg, str) else (msg or body)
        kind = msg.get("notificationType") or msg.get("eventType")
        if kind == "Bounce":
            btype = "hard" if msg["bounce"].get("bounceType") == "Permanent" else "soft"
            recips = msg["bounce"].get("bouncedRecipients") or []
        elif kind == "Complaint":
            btype = "complaint"
            recips = msg["complaint"].get("complainedRecipients") or []
        else:
            return ok(True)
        for r in recips:
            await record(email=r.get("emailAddress", ""), btype=btype, source="ses", meta=msg)

    elif service == "sendgrid":
        if not settings.get("bounce.sendgrid_enabled", False):
            raise bad_request("SendGrid bounce processing is disabled")
        for ev in body if isinstance(body, list) else [body]:
            e = ev.get("event")
            if e in ("bounce", "dropped"):
                btype = "hard" if ev.get("type") == "blocked" else "soft"
            elif e == "spamreport":
                btype = "complaint"
            else:
                continue
            await record(email=ev.get("email", ""), btype=btype, source="sendgrid", meta=ev)

    elif service == "postmark":
        if not (settings.get("bounce.postmark") or {}).get("enabled"):
            raise bad_request("Postmark bounce processing is disabled")
        rt = (body.get("RecordType") or "").lower()
        if rt == "spamcomplaint":
            btype = "complaint"
        elif rt == "bounce":
            btype = "hard" if body.get("Type") == "HardBounce" else "soft"
        else:
            return ok(True)
        await record(email=body.get("Email", ""), btype=btype, source="postmark", meta=body)

    else:
        raise bad_request(f"unknown bounce service: {service}")

    return ok(True)
