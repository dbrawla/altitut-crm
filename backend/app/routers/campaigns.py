"""Campaign endpoints â€” port of cmd/campaigns.go."""

from __future__ import annotations

import re
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import auth, db, settings
from app.utils import Pagination, bad_request, not_found, ok

router = APIRouter(tags=["campaigns"])

_ORDER_FIELDS = {"name", "status", "created_at", "updated_at", "id"}

# Allowed status transitions (port of internal/core campaign status rules).
_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"draft"},
    "running": {"draft", "scheduled", "paused"},
    "paused": {"running"},
    "cancelled": {"running", "scheduled", "paused"},
    "draft": {"scheduled"},
}


class CampaignPayload(BaseModel):
    name: str
    subject: str = ""
    from_email: str = ""
    body: str = ""
    body_source: str | None = None
    altbody: str | None = None
    content_type: str = "richtext"
    send_at: datetime | None = None
    headers: list[dict[str, str]] = []
    attribs: dict[str, Any] = {}
    tags: list[str] = []
    type: str = "regular"
    messenger: str = "email"
    lists: list[int] = []
    media: list[int] = []
    template_id: int | None = None
    archive: bool = False
    archive_slug: str | None = None
    archive_template_id: int | None = None
    archive_meta: dict[str, Any] = {}


def _scope(user: auth.User, perm: str) -> tuple[bool, list[int]]:
    permitted, all_ok = auth.permitted_list_ids(user, perm)
    if auth.has_perm(user, f"campaigns:{'get_all' if perm == 'get' else 'manage_all'}"):
        return True, []
    return all_ok, permitted


async def _attach_stats(camps: list[dict[str, Any]]) -> None:
    if not camps:
        return
    ids = [c["id"] for c in camps]
    rows = await db.fetch("get-campaign-stats", ids)
    by_id = {r["campaign_id"]: r for r in rows}
    for c in camps:
        st = by_id.get(c["id"]) or {}
        c["views"] = st.get("views", 0)
        c["clicks"] = st.get("clicks", 0)
        c["bounces"] = st.get("bounces", 0)
        c["media"] = st.get("media") or []


@router.get("/api/campaigns", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def get_campaigns(
    user: auth.CurrentUser,
    pg: Pagination = Depends(),
    query: str = "",
    status: list[str] = Query(default=[]),
    tag: list[str] = Query(default=[]),
    order_by: str = "created_at",
    order: str = "DESC",
    no_body: bool = False,
):
    all_ok, permitted = _scope(user, "get")
    field = order_by if order_by in _ORDER_FIELDS else "created_at"
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    sql = db.q("query-campaigns").replace("%order%", f"c.{field} {direction}")

    search = f"%{query}%" if query else ""
    rows = await db.fetch(sql, 0, status, tag, search, all_ok, permitted, pg.offset, pg.limit)
    total = rows[0]["total"] if rows else 0
    for r in rows:
        r.pop("total", None)
        if no_body:
            r["body"] = ""
            r["body_source"] = None
    await _attach_stats(rows)
    return ok(pg.results(rows, total, query))


@router.get("/api/campaigns/running/stats", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def running_stats():
    rows = await db.fetch("get-campaign-status", "running")
    # rate: messages sent in the last minute per campaign (like upstream's stats).
    from app import manager

    for r in rows:
        r["rate"] = manager.send_rates.get(r["id"], 0)
    return ok(rows)


@router.get("/api/campaigns/{camp_id}", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def get_campaign(camp_id: int, no_body: bool = False):
    camp = await db.fetchrow("get-campaign", camp_id, None, "", "default")
    if not camp:
        raise not_found("campaign not found")
    await _attach_stats([camp])
    lists = await db.fetch(
        "SELECT COALESCE(list_id, 0) AS id, list_name AS name FROM campaign_lists WHERE campaign_id=$1",
        camp_id,
    )
    camp["lists"] = lists
    if no_body:
        camp["body"] = ""
    return ok(camp)


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    from slugify import slugify

    return slugify(text)[:200] or None


async def _validate(payload: CampaignPayload, user: auth.User) -> CampaignPayload:
    if not payload.name.strip():
        raise bad_request("invalid campaign name")
    if not payload.subject.strip() and payload.type != "optin":
        raise bad_request("invalid subject")
    if not payload.lists:
        raise bad_request("no lists selected")
    if payload.content_type not in ("richtext", "html", "plain", "markdown", "visual"):
        raise bad_request("invalid content_type")
    if payload.from_email and "@" not in payload.from_email:
        raise bad_request("invalid from_email")
    if not payload.from_email:
        payload.from_email = settings.get("app.from_email", "")
    if payload.send_at and payload.send_at < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise bad_request("send_at date is in the past")
    if payload.archive and not payload.archive_slug:
        payload.archive_slug = _slugify(payload.name)
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    if not all_ok:
        payload.lists = [i for i in payload.lists if i in set(permitted)] or payload.lists
    return payload


@router.post("/api/campaigns", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def create_campaign(payload: CampaignPayload, user: auth.CurrentUser):
    payload = await _validate(payload, user)
    camp_id = await db.fetchval(
        "create-campaign",
        str(uuidlib.uuid4()), payload.type, payload.name.strip(), payload.subject,
        payload.from_email, payload.body, payload.altbody, payload.content_type,
        payload.send_at, payload.headers, payload.attribs, payload.tags,
        payload.messenger, payload.template_id, payload.lists, payload.archive,
        payload.archive_slug or None, payload.archive_template_id, payload.archive_meta,
        payload.media, payload.body_source,
    )
    if not camp_id:
        raise bad_request("error creating campaign (check template)")
    return await get_campaign(camp_id)


@router.put("/api/campaigns/{camp_id}", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def update_campaign(camp_id: int, payload: CampaignPayload, user: auth.CurrentUser):
    cur = await db.fetchrow("get-campaign", camp_id, None, "", "default")
    if not cur:
        raise not_found("campaign not found")
    if cur["status"] == "running":
        raise bad_request("cannot update a running campaign; pause it first")
    payload = await _validate(payload, user)
    await db.execute(
        "update-campaign",
        camp_id, payload.name.strip(), payload.subject, payload.from_email,
        payload.body, payload.altbody or "", payload.content_type, payload.send_at,
        payload.headers, payload.attribs, payload.tags, payload.messenger,
        payload.template_id, payload.lists, payload.archive,
        payload.archive_slug or None, payload.archive_template_id, payload.archive_meta,
        payload.media, payload.body_source,
    )
    return await get_campaign(camp_id)


class StatusPayload(BaseModel):
    status: str


@router.put("/api/campaigns/{camp_id}/status", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all", "campaigns:send")])
async def update_campaign_status(camp_id: int, payload: StatusPayload):
    camp = await db.fetchrow("get-campaign", camp_id, None, "", "default")
    if not camp:
        raise not_found("campaign not found")
    new = payload.status
    if new not in _TRANSITIONS:
        raise bad_request("invalid status")
    if camp["status"] not in _TRANSITIONS[new]:
        raise bad_request(f"cannot change status from {camp['status']} to {new}")
    if new == "scheduled" and not camp["send_at"]:
        raise bad_request("campaign needs a send_at date to be scheduled")
    await db.execute("update-campaign-status", camp_id, new)
    return await get_campaign(camp_id)


class ArchivePayload(BaseModel):
    archive: bool
    archive_slug: str | None = None
    archive_template_id: int | None = None
    archive_meta: dict[str, Any] = {}


@router.put("/api/campaigns/{camp_id}/archive", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def update_campaign_archive(camp_id: int, payload: ArchivePayload):
    import orjson

    await db.execute(
        "update-campaign-archive",
        camp_id, payload.archive, payload.archive_slug or "",
        payload.archive_template_id or 0,
        orjson.dumps(payload.archive_meta).decode() if payload.archive_meta else "",
    )
    return ok(True)


@router.delete("/api/campaigns/{camp_id}", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def delete_campaign(camp_id: int, user: auth.CurrentUser):
    all_ok, permitted = _scope(user, "manage")
    await db.execute("delete-campaigns", [camp_id], "", all_ok, permitted)
    return ok(True)


@router.delete("/api/campaigns", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def delete_campaigns(user: auth.CurrentUser, id: list[int] = Query(default=[])):
    if not id:
        raise bad_request("no IDs given")
    all_ok, permitted = _scope(user, "manage")
    await db.execute("delete-campaigns", id, "", all_ok, permitted)
    return ok(True)


# ---------------------------------------------------------------------------
# Preview / test / content tools
# ---------------------------------------------------------------------------


class PreviewPayload(BaseModel):
    body: str = ""
    body_source: str | None = None
    content_type: str = ""
    template_id: int | None = None


async def _render_preview(
    camp_id: int, body: str = "", content_type: str = "", template_id: int | None = None,
    archive: bool = False,
) -> str:
    from app import tmpl

    camp = await db.fetchrow("get-campaign-for-preview", camp_id, template_id or 0)
    if not camp:
        raise not_found("campaign not found")
    if body:
        camp["body"] = body
    if content_type:
        camp["content_type"] = content_type
    if archive:
        arch = await db.fetchrow("get-campaign", camp_id, None, "", "archive")
        camp["template_body"] = arch["template_body"] if arch else camp["template_body"]

    sub = await db.fetchrow("get-one-campaign-subscriber", camp_id)
    return await tmpl.render_campaign_preview(camp, sub)


@router.get("/api/campaigns/{camp_id}/preview", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def preview_campaign(camp_id: int):
    return HTMLResponse(await _render_preview(camp_id))


@router.post("/api/campaigns/{camp_id}/preview", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def preview_campaign_body(camp_id: int, payload: PreviewPayload):
    return HTMLResponse(
        await _render_preview(camp_id, payload.body, payload.content_type, payload.template_id)
    )


@router.post("/api/campaigns/{camp_id}/preview/archive", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def preview_campaign_archive(camp_id: int, payload: PreviewPayload):
    return HTMLResponse(
        await _render_preview(
            camp_id, payload.body, payload.content_type, payload.template_id, archive=True
        )
    )


@router.post("/api/campaigns/{camp_id}/text", dependencies=[auth.require("campaigns:get", "campaigns:get_all")])
async def campaign_text(camp_id: int, payload: PreviewPayload):
    from app import tmpl

    html = await _render_preview(camp_id, payload.body, payload.content_type, payload.template_id)
    return ok(tmpl.html_to_text(html))


class TestPayload(CampaignPayload):
    subscribers: list[str] = []


@router.post("/api/campaigns/{camp_id}/test", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def test_campaign(camp_id: int, payload: TestPayload, user: auth.CurrentUser):
    if not payload.subscribers:
        raise bad_request("no test subscriber emails given")
    from app import manager

    emails = [e.strip().lower() for e in payload.subscribers if e.strip()]
    subs = await db.fetch("get-subscribers-by-emails", emails)
    if not subs:
        raise bad_request("no matching subscribers found for the given emails")

    # Save the incoming changes first (same as upstream), then send tests.
    await update_campaign(camp_id, payload, user)
    camp = await db.fetchrow("get-campaign-for-preview", camp_id, 0)
    for sub in subs:
        await manager.send_test_message(camp, sub)
    return ok(True)


class ContentPayload(BaseModel):
    content_type: str  # target
    body: str


@router.post("/api/campaigns/{camp_id}/content", dependencies=[auth.require("campaigns:manage", "campaigns:manage_all")])
async def convert_campaign_content(camp_id: int, payload: ContentPayload):
    """Convert campaign body between richtext/html/markdown/plain."""
    from app import tmpl

    src = payload.body
    to = payload.content_type
    if to in ("richtext", "html"):
        # markdown/plain -> html
        if _looks_like_html(src):
            out = src
        else:
            import markdown as md

            out = md.markdown(src, extensions=["tables", "fenced_code"])
    elif to == "markdown":
        out = tmpl.html_to_markdown(src)
    elif to == "plain":
        out = tmpl.html_to_text(src)
    else:
        raise bad_request("invalid target content_type")
    return ok(out)


def _looks_like_html(s: str) -> bool:
    return bool(re.search(r"<\s*(p|div|br|table|h\d|a|span|img|html)\b", s, re.I))


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@router.get("/api/campaigns/analytics/{atype}", dependencies=[auth.require("campaigns:get_analytics")])
async def campaign_analytics(
    atype: str,
    id: list[int] = Query(default=[]),
    from_: str = Query(default="", alias="from"),
    to: str = Query(default=""),
):
    if not id:
        raise bad_request("no campaign IDs given")
    try:
        frm = datetime.fromisoformat(from_) if from_ else datetime.now(timezone.utc) - timedelta(days=7)
        until = datetime.fromisoformat(to) if to else datetime.now(timezone.utc)
    except ValueError:
        raise bad_request("invalid from/to dates")
    # asyncpg wants naive timestamps for ::TIMESTAMP params.
    frm, until = frm.replace(tzinfo=None), until.replace(tzinfo=None)

    individual = settings.get("privacy.individual_tracking", False)

    if atype in ("views", "clicks"):
        table = "campaign_views" if atype == "views" else "link_clicks"
        name = "get-campaign-analytics-unique-counts" if individual else "get-campaign-analytics-counts"
        sql = db.q(name).replace("%s", table)
        return ok(await db.fetch(sql, id, frm, until))
    if atype == "bounces":
        return ok(await db.fetch("get-campaign-bounce-counts", id, frm, until))
    if atype == "links":
        expr = "DISTINCT subscriber_id" if individual else "*"
        sql = db.q("get-campaign-link-counts").replace("%s", expr)
        return ok(await db.fetch(sql, id, frm, until))
    raise bad_request("invalid analytics type")
