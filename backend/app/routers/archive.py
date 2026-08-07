"""Public campaign archive — port of cmd/archive.go.

Archived campaigns are rendered against the dummy subscriber stored in the
campaign's `archive_meta`, so personalisation placeholders resolve to sample
values instead of leaking a real subscriber.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app import db, settings, tmpl
from app.utils import Pagination, not_found, ok

log = logging.getLogger("listmonk")

router = APIRouter(tags=["archive"], include_in_schema=False)


def _enabled() -> None:
    if not settings.get("app.enable_public_archive", True):
        raise HTTPException(status_code=404, detail="the public archive is disabled")


def _archive_url(camp: dict[str, Any]) -> str:
    root = (settings.get("app.root_url") or "").rstrip("/")
    return f"{root}/archive/{camp.get('archive_slug') or camp['uuid']}"


def _archive_sub(camp: dict[str, Any]) -> dict[str, Any] | None:
    """The dummy subscriber stored on the campaign for archive rendering."""
    meta = camp.get("archive_meta") or {}
    if not isinstance(meta, dict) or not meta:
        return None
    # archive_meta mirrors a subscriber record; fill in what render needs.
    return {
        "uuid": meta.get("uuid") or tmpl.DUMMY_UUID,
        "email": meta.get("email") or "subscriber@example.com",
        "name": meta.get("name") or "Subscriber",
        "attribs": meta.get("attribs") or {},
        "status": "enabled",
    }


async def _fetch_archives(pg: Pagination, render_body: bool) -> tuple[list[dict[str, Any]], int]:
    rows = await db.fetch("get-archived-campaigns", pg.offset, pg.limit, "archive")
    total = rows[0]["total"] if rows else 0

    out = []
    for camp in rows:
        item = {
            "uuid": camp["uuid"],
            "subject": camp["subject"],
            "created_at": camp["created_at"],
            "send_at": camp["send_at"],
            "url": _archive_url(camp),
            "content": "",
        }
        # The subject may itself be a template.
        try:
            subject, body, _ = await tmpl.render_message(
                camp, _archive_sub(camp), preview=True
            )
            item["subject"] = subject
            if render_body:
                item["content"] = body
        except Exception:
            log.exception("error rendering archived campaign %s", camp.get("id"))
        out.append(item)

    return out, total


@router.get("/api/public/archive")
async def api_archive(pg: Pagination = Depends()) -> dict[str, Any]:
    _enabled()
    results, total = await _fetch_archives(pg, render_body=False)
    return ok(pg.results(results, total))


@router.get("/archive")
async def archive_page(pg: Pagination = Depends()) -> Response:
    _enabled()
    results, total = await _fetch_archives(pg, render_body=False)
    site = settings.get("app.site_name") or "listmonk"

    if not results:
        items = "<p>No campaigns have been archived yet.</p>"
    else:
        items = "".join(
            f'<li><a href="{escape(c["url"])}">{escape(c["subject"])}</a>'
            f'<span class="date">'
            f'{(c["send_at"] or c["created_at"]).strftime("%d %b %Y")}'
            "</span></li>"
            for c in results
        )
        items = f"<ul class='archive'>{items}</ul>"

    pages = ""
    if pg.per_page and total > pg.per_page:
        last = (total + pg.per_page - 1) // pg.per_page
        links = " ".join(
            f'<a href="?page={i}"{" class=cur" if i == pg.page else ""}>{i}</a>'
            for i in range(1, last + 1)
        )
        pages = f'<p class="pages">{links}</p>'

    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive - {escape(site)}</title>
<link rel="alternate" type="application/rss+xml" href="/archive.xml">
<link rel="stylesheet" href="/public/custom.css">
<style>
 body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#f6f8f9;margin:0;
      padding:40px 20px;color:#1f2933}}
 .wrap{{max-width:640px;margin:0 auto;background:#fff;padding:36px;border-radius:12px;
        box-shadow:0 10px 30px rgba(0,0,0,.06)}}
 h1{{font-size:22px;margin:0 0 24px}}
 ul.archive{{list-style:none;padding:0;margin:0}}
 ul.archive li{{padding:12px 0;border-bottom:1px solid #eef1f3;display:flex;
                justify-content:space-between;gap:16px}}
 .date{{color:#8b98a5;font-size:13px;white-space:nowrap}}
 a{{color:#0055a4;text-decoration:none}} a:hover{{text-decoration:underline}}
 .pages a{{margin-right:8px}} .pages a.cur{{font-weight:700;color:#1f2933}}
</style></head><body><div class="wrap"><h1>{escape(site)} archive</h1>
{items}{pages}</div><script src="/public/custom.js"></script></body></html>"""
    )


@router.get("/archive.xml")
async def archive_feed(request: Request, pg: Pagination = Depends()) -> Response:
    _enabled()
    full = settings.get("app.enable_public_archive_rss_content", False)
    results, _ = await _fetch_archives(pg, render_body=bool(full))

    root = (settings.get("app.root_url") or "").rstrip("/")
    site = settings.get("app.site_name") or "listmonk"

    items = []
    for c in results:
        pub = c["send_at"] or c["created_at"] or datetime.now(UTC)
        body = f"<content:encoded><![CDATA[{c['content']}]]></content:encoded>" if full else ""
        items.append(
            f"<item><title>{escape(c['subject'])}</title>"
            f"<link>{escape(c['url'])}</link>"
            f"<guid isPermaLink=\"true\">{escape(c['url'])}</guid>"
            f"<pubDate>{format_datetime(pub)}</pubDate>{body}</item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        f"<channel><title>{escape(site)}</title><link>{escape(root)}</link>"
        f"<description>{escape(site)} archive</description>"
        + "".join(items)
        + "</channel></rss>"
    )
    return Response(xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/archive/latest")
async def archive_latest() -> Response:
    """Registered before /archive/{id} so 'latest' isn't treated as a slug."""
    _enabled()
    rows = await db.fetch("get-archived-campaigns", 0, 1, "archive")
    if not rows:
        raise not_found("no archived campaigns")
    camp = rows[0]
    _, body, _ = await tmpl.render_message(camp, _archive_sub(camp), preview=True)
    return HTMLResponse(body)


@router.get("/archive/{ident}")
async def archive_campaign(ident: str) -> Response:
    """`ident` is either the campaign UUID or its custom archive slug."""
    _enabled()
    from app.routers.public import _RE_UUID

    is_uuid = bool(_RE_UUID.match(ident))
    camp = await db.fetchrow(
        "get-campaign",
        0,
        ident if is_uuid else None,
        "" if is_uuid else ident,
        "archive",
    )
    if not camp or not camp.get("archive") or camp.get("type") != "regular":
        raise not_found("campaign not found")
    if camp.get("status") not in ("running", "paused", "finished"):
        raise not_found("campaign not found")

    _, body, _ = await tmpl.render_message(camp, _archive_sub(camp), preview=True)
    return HTMLResponse(body)
