"""Public, unauthenticated subscriber-facing endpoints — port of cmd/public.go.

These are the URLs baked into sent emails by tmpl._urls(): the tracking pixel,
click-tracking redirects, view-in-browser, unsubscribe/preferences and double
opt-in confirmation. Without them every delivered campaign has dead links, so
they ship alongside the send engine.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import db, settings, tmpl
from app.utils import bad_request, not_found, ok

log = logging.getLogger("listmonk")

router = APIRouter(tags=["public"], include_in_schema=False)

_RE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# 1x1 transparent GIF — the original serves a PNG named px.png, but a GIF is the
# smallest valid tracking pixel and every mail client renders it.
_PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")

_DUMMY = tmpl.DUMMY_UUID


def _check_uuids(*uuids: str) -> None:
    for u in uuids:
        if not _RE_UUID.match(u):
            raise bad_request("invalid UUID")


def _page(title: str, body: str) -> HTMLResponse:
    """Minimal styled shell for the subscriber-facing pages.

    ponytail: the Go build renders static/public/templates/*.html (Go template
    syntax, with the admin's custom CSS). This is a plain self-contained page —
    swap in tmpl.go2jinja over those files if the themed pages are needed.
    """
    site = settings.get("app.site_name") or "listmonk"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - {site}</title>
<link rel="stylesheet" href="/public/custom.css">
<style>
 body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#f6f8f9;margin:0;
      display:flex;min-height:100vh;align-items:center;justify-content:center;color:#1f2933}}
 .card{{background:#fff;padding:40px;border-radius:12px;max-width:520px;width:100%;
       box-shadow:0 10px 30px rgba(0,0,0,.08)}}
 h1{{font-size:20px;margin:0 0 16px}} p{{line-height:1.6;color:#52606d}}
 button{{background:#0055a4;color:#fff;border:0;padding:10px 18px;border-radius:6px;
        font-size:15px;cursor:pointer}}
 label{{display:block;margin:10px 0}}
</style></head><body><div class="card"><h1>{title}</h1>{body}</div>
<script src="/public/custom.js"></script></body></html>"""
    )


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------


@router.get("/campaign/{camp_uuid}/{sub_uuid}/px.png")
async def track_view(camp_uuid: str, sub_uuid: str) -> Response:
    """Open tracking. Always returns the pixel — never leak errors to mail clients."""
    if not settings.get("privacy.disable_tracking", False):
        try:
            _check_uuids(camp_uuid, sub_uuid)
            await db.execute(
                "register-campaign-view", camp_uuid, "" if sub_uuid == _DUMMY else sub_uuid
            )
        except Exception:
            log.debug("campaign view registration failed", exc_info=True)
    return Response(
        content=_PIXEL,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "X-Robots-Tag": "noindex"},
    )


@router.get("/link/{link_uuid}/{camp_uuid}/{sub_uuid}")
async def track_link(link_uuid: str, camp_uuid: str, sub_uuid: str) -> RedirectResponse:
    """Click tracking: record the click, then redirect to the real URL."""
    _check_uuids(link_uuid, camp_uuid, sub_uuid)

    url: str | None = None
    if not settings.get("privacy.disable_tracking", False):
        try:
            url = await db.fetchval(
                "register-link-click", link_uuid, camp_uuid,
                "" if sub_uuid == _DUMMY else sub_uuid,
            )
        except Exception:
            log.debug("link click registration failed", exc_info=True)

    # Tracking disabled, or the click insert failed — still resolve the target.
    if not url:
        url = await db.fetchval("get-link-url", link_uuid)
    if not url:
        raise not_found("link not found")

    return RedirectResponse(url, status_code=302, headers={"X-Robots-Tag": "noindex"})


@router.get("/campaign/{camp_uuid}/{sub_uuid}")
async def view_in_browser(camp_uuid: str, sub_uuid: str) -> HTMLResponse:
    """View-in-browser: re-render the campaign for this subscriber."""
    _check_uuids(camp_uuid, sub_uuid)

    camp = await db.fetchrow("get-campaign", 0, camp_uuid, "", "default")
    if not camp or camp["status"] not in ("running", "paused", "finished"):
        raise not_found("campaign not found")

    sub = None
    if sub_uuid != _DUMMY:
        sub = await db.fetchrow("get-subscriber", 0, sub_uuid, "")

    _, html, _ = await tmpl.render_message(camp, sub, preview=True)
    if not settings.get("privacy.disable_tracking", False):
        try:
            await db.execute(
                "register-campaign-view", camp_uuid, "" if sub_uuid == _DUMMY else sub_uuid
            )
        except Exception:
            log.debug("campaign view registration failed", exc_info=True)

    return HTMLResponse(html, headers={"X-Robots-Tag": "noindex"})


# ---------------------------------------------------------------------------
# Double opt-in confirmation
#
# These MUST stay above /subscription/{camp_uuid}/{sub_uuid}: FastAPI matches
# routes in registration order, so the two-param route would otherwise capture
# /subscription/optin/<uuid> with camp_uuid="optin" and reject it as a bad UUID.
# ---------------------------------------------------------------------------


@router.get("/subscription/optin/{sub_uuid}")
async def optin_page(sub_uuid: str) -> HTMLResponse:
    _check_uuids(sub_uuid)
    sub = await db.fetchrow("get-subscriber", 0, sub_uuid, "")
    if not sub:
        raise not_found("subscriber not found")

    lists = await db.fetch("get-subscriber-lists", 0, sub_uuid, [], [], "unconfirmed", "double")
    if not lists:
        return _page("Confirmed", "<p>There are no subscriptions to confirm.</p>")

    items = "".join(f"<li>{ln['name']}</li>" for ln in lists)
    return _page(
        "Confirm subscription",
        f"<p>Confirm subscription for <strong>{sub['email']}</strong> to:</p><ul>{items}</ul>"
        '<form method="post"><button type="submit">Confirm</button></form>',
    )


@router.post("/subscription/optin/{sub_uuid}")
async def optin_confirm(sub_uuid: str, request: Request) -> HTMLResponse:
    _check_uuids(sub_uuid)
    lists = await db.fetch("get-subscriber-lists", 0, sub_uuid, [], [], "unconfirmed", "double")
    if lists:
        meta: dict[str, Any] = {}
        if settings.get("privacy.record_optin_ip", False) and request.client:
            meta = {"optin_ip": request.client.host}
        await db.execute(
            "confirm-subscription-optin", sub_uuid, [ln["uuid"] for ln in lists], meta
        )
    return _page("Confirmed", "<p>Your subscription has been confirmed.</p>")


# ---------------------------------------------------------------------------
# Unsubscribe / preferences
# ---------------------------------------------------------------------------


@router.get("/subscription/{camp_uuid}/{sub_uuid}")
async def subscription_page(camp_uuid: str, sub_uuid: str, manage: bool = False) -> HTMLResponse:
    _check_uuids(camp_uuid, sub_uuid)
    sub = await db.fetchrow("get-subscriber", 0, sub_uuid, "")
    if not sub:
        raise not_found("subscriber not found")

    blocklist_box = ""
    if settings.get("privacy.allow_blocklist", True):
        blocklist_box = (
            '<label><input type="checkbox" name="blocklist" value="true"> '
            "Unsubscribe from all mailing lists</label>"
        )

    return _page(
        "Unsubscribe",
        f"<p>Do you want to unsubscribe <strong>{sub['email']}</strong> from this mailing list?</p>"
        f'<form method="post">{blocklist_box}'
        '<p><button type="submit">Unsubscribe</button></p></form>',
    )


@router.post("/subscription/{camp_uuid}/{sub_uuid}")
async def unsubscribe(
    camp_uuid: str, sub_uuid: str, blocklist: str = Form(default="")
) -> HTMLResponse:
    _check_uuids(camp_uuid, sub_uuid)
    block = blocklist.lower() in ("true", "on", "1", "yes")
    if block and not settings.get("privacy.allow_blocklist", True):
        block = False

    await db.execute("unsubscribe-by-campaign", camp_uuid, sub_uuid, block)
    return _page(
        "Unsubscribed",
        "<p>You have been unsubscribed"
        + (" from all mailing lists." if block else " from this mailing list.")
        + "</p>",
    )


# ---------------------------------------------------------------------------
# Public APIs
# ---------------------------------------------------------------------------


@router.get("/api/public/lists")
async def public_lists() -> dict[str, Any]:
    if not settings.get("app.enable_public_subscription_page", True):
        raise HTTPException(status_code=404, detail="public subscription page is disabled")
    sql = db.q("query-lists").replace("%order%", "name ASC")
    rows = await db.fetch(sql, 0, "", "", "public", "", "active", [], True, [], 0, 0)
    return ok(
        [
            {"uuid": r["uuid"], "name": r["name"], "optin": r["optin"],
             "description": r.get("description", "")}
            for r in rows
        ]
    )


@router.post("/api/public/subscription")
async def public_subscribe(
    email: str = Form(...),
    name: str = Form(default=""),
    l: list[str] = Form(default=[]),  # noqa: E741 — the original's param name
) -> dict[str, Any]:
    if not settings.get("app.enable_public_subscription_page", True):
        raise HTTPException(status_code=404, detail="public subscription page is disabled")

    email = email.strip().lower()
    if "@" not in email or len(email) > 320:
        raise bad_request("invalid email")
    if not l:
        raise bad_request("no lists selected")

    domain = email.rsplit("@", 1)[1]
    if domain in (settings.get("privacy.domain_blocklist") or []):
        raise bad_request("domain not allowed")
    allow = settings.get("privacy.domain_allowlist") or []
    if allow and domain not in allow:
        raise bad_request("domain not allowed")

    # The form posts list UUIDs; upsert-subscriber takes INT list IDs ($5).
    # $2 must be NULL (not []) — the query's CASE has no ELSE, so an empty
    # non-null INT[] would match `id = ANY('{}')` and return nothing.
    target = await db.fetch("get-lists-by-optin", "", None, l)
    if not target:
        raise bad_request("no such lists")
    list_ids = [r["id"] for r in target]

    import uuid as uuidlib

    sub_uuid = str(uuidlib.uuid4())
    row = await db.fetchrow(
        "upsert-subscriber",
        sub_uuid,                    # $1 uuid
        email,                       # $2 email
        name.strip() or email,       # $3 name
        {},                          # $4 attribs
        list_ids,                    # $5 list IDs
        "unconfirmed",               # $6 subscription status
        True,                        # $7 overwrite name/attribs
        False,                       # $8 don't downgrade an existing confirmed subscription
    )

    # Fire the double opt-in confirmation if any of the lists need it.
    if settings.get("app.send_optin_confirmation", True) and row:
        from app import notifs

        try:
            await notifs.send_optin_confirmation_by_id(row["id"])
        except Exception:
            log.exception("failed sending opt-in confirmation")

    return ok(True)


# ---------------------------------------------------------------------------
# Misc public routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def public_health() -> dict[str, Any]:
    return ok(True)


@router.get("/robots.txt")
async def robots() -> Response:
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")


def _appearance(key: str, mime: str):
    async def handler() -> Response:
        return Response(settings.get(key) or "", media_type=mime)

    return handler


router.add_api_route(
    "/public/custom.css", _appearance("appearance.public.custom_css", "text/css"), methods=["GET"]
)
router.add_api_route(
    "/public/custom.js",
    _appearance("appearance.public.custom_js", "application/javascript"),
    methods=["GET"],
)
router.add_api_route(
    "/admin/custom.css", _appearance("appearance.admin.custom_css", "text/css"), methods=["GET"]
)
router.add_api_route(
    "/admin/custom.js",
    _appearance("appearance.admin.custom_js", "application/javascript"),
    methods=["GET"],
)
