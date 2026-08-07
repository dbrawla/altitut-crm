"""Maintenance endpoints — port of cmd/maintenance.go.

Garbage collection of subscribers/subscriptions/analytics, plus streaming CSV
exports of campaign view and click analytics.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Form, Query
from fastapi.responses import Response, StreamingResponse

from app import auth, db
from app.utils import bad_request, ok

router = APIRouter(tags=["maintenance"])

# Rows pulled per round-trip when streaming an analytics export.
_EXPORT_BATCH = 5000


def _parse_ts(value: str | None, field: str) -> datetime:
    """Parse an RFC3339 timestamp the way the Go handlers do."""
    if not value:
        raise bad_request(f"invalid {field}")
    try:
        # fromisoformat handles "...Z" from 3.11 onwards.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request(f"invalid {field}") from None


@router.delete(
    "/api/maintenance/subscribers/{gc_type}",
    dependencies=[auth.require("settings:maintain")],
)
async def gc_subscribers(gc_type: str) -> dict[str, Any]:
    """Delete blocklisted or orphaned (list-less) subscribers."""
    if gc_type == "blocklisted":
        tag = await db.execute("delete-blocklisted-subscribers")
    elif gc_type == "orphan":
        tag = await db.execute("delete-orphan-subscribers")
    else:
        raise bad_request("invalid type; expected 'blocklisted' or 'orphan'")

    # asyncpg returns the command tag, e.g. "DELETE 12".
    count = int(tag.rsplit(" ", 1)[-1]) if tag and tag[-1].isdigit() else 0
    return ok({"count": count})


@router.delete(
    "/api/maintenance/subscriptions/unconfirmed",
    dependencies=[auth.require("settings:maintain")],
)
async def gc_subscriptions(before_date: str = Form(default="")) -> dict[str, Any]:
    """Delete unconfirmed subscriptions to double opt-in lists before a date."""
    ts = _parse_ts(before_date, "before_date")
    tag = await db.execute("delete-unconfirmed-subscriptions", ts)
    count = int(tag.rsplit(" ", 1)[-1]) if tag and tag[-1].isdigit() else 0
    return ok({"count": count})


@router.delete(
    "/api/maintenance/analytics/{gc_type}",
    dependencies=[auth.require("settings:maintain")],
)
async def gc_analytics(gc_type: str, before_date: str = Form(default="")) -> dict[str, Any]:
    """Delete campaign view and/or link-click records before a date."""
    ts = _parse_ts(before_date, "before_date")
    if gc_type == "all":
        await db.execute("delete-campaign-views", ts)
        await db.execute("delete-campaign-link-clicks", ts)
    elif gc_type == "views":
        await db.execute("delete-campaign-views", ts)
    elif gc_type == "clicks":
        await db.execute("delete-campaign-link-clicks", ts)
    else:
        raise bad_request("invalid type; expected 'all', 'views' or 'clicks'")
    return ok(True)


_EXPORTS = {
    "views": (
        "export-campaign-views",
        ["campaign_id", "campaign_uuid", "campaign_name", "subscriber_id",
         "subscriber_uuid", "email", "subscriber_name", "created_at"],
    ),
    "clicks": (
        "export-campaign-link-clicks",
        ["campaign_id", "campaign_uuid", "campaign_name", "subscriber_id",
         "subscriber_uuid", "email", "subscriber_name", "url", "created_at"],
    ),
}


@router.get(
    "/api/maintenance/analytics/{export_type}/export",
    dependencies=[auth.require("settings:maintain")],
)
async def export_analytics(export_type: str, since: str = Query(default="")) -> Response:
    """Stream campaign analytics as CSV, paged so a big table never loads at once."""
    if export_type not in _EXPORTS:
        raise bad_request("invalid type; expected 'views' or 'clicks'")
    ts = _parse_ts(since, "since")
    query, header = _EXPORTS[export_type]

    async def rows() -> AsyncGenerator[str, None]:
        buf = io.StringIO()
        writer = csv.writer(buf)

        def flush() -> str:
            out = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return out

        writer.writerow(header)
        yield flush()

        offset = 0
        while True:
            batch = await db.fetch(query, ts, _EXPORT_BATCH, offset)
            if not batch:
                break
            for r in batch:
                writer.writerow(
                    [
                        r[c].isoformat() if isinstance(r[c], datetime) else r[c]
                        for c in header
                    ]
                )
            yield flush()
            if len(batch) < _EXPORT_BATCH:
                break
            offset += _EXPORT_BATCH

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=campaign_{export_type}.csv",
            "Cache-Control": "no-cache",
        },
    )
