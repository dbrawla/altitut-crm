"""
Subscriber endpoints — port of cmd/subscribers.go + internal/core subscribers.

Includes the original's arbitrary-SQL segmentation queries (%query% blocks),
gated by the subscribers:sql_query permission exactly like upstream.
"""

from __future__ import annotations

import csv
import io
import re
import uuid as uuidlib
from collections.abc import AsyncIterator
from typing import Any

import orjson
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app import auth, db
from app.repos import subscriber_repo
from app.utils import Pagination, bad_request, not_found, ok

router = APIRouter(tags=["subscribers"])

# Sortable fields (port of the Go handler's allowlist).
_ORDER_FIELDS = {"email", "name", "created_at", "updated_at", "id", "status"}


def _order_clause(order_by: str, order: str) -> str:
    field = order_by if order_by in _ORDER_FIELDS else "id"
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    return f"subscribers.{field} {direction}"


# Statement terminators and comment openers. The segmentation condition is
# interpolated into a WHERE clause, so any of these let a caller close the
# expression and append their own statement (`') OR TRUE; DROP TABLE ...--`).
# The permission gate alone is not enough: it is meant to grant *filtering*,
# not arbitrary statement execution.
_SQL_BREAKOUT = re.compile(r";|--|/\*|\*/")


def _query_cond(user: auth.User, query: str) -> str:
    """The arbitrary SQL segmentation condition. Only users with the
    subscribers:sql_query permission may use it (original behavior)."""
    query = (query or "").strip()
    if not query:
        return "TRUE"
    if not auth.has_perm(user, "subscribers:sql_query"):
        raise bad_request("missing permission: subscribers:sql_query")
    if _SQL_BREAKOUT.search(query):
        raise bad_request("query may not contain ';' or SQL comment markers")
    # Prefix balance, not a total count: `1=1) OR (TRUE` counts even but still
    # closes the wrapper parenthesis early and appends its own clause.
    depth = 0
    for ch in query:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise bad_request("unbalanced parentheses in query")
    if depth != 0:
        raise bad_request("unbalanced parentheses in query")
    return f"({query})"


def _scope_lists(user: auth.User, list_ids: list[int], perm: str) -> list[int]:
    """Filter requested list IDs down to what the user may access."""
    permitted, all_ok = auth.permitted_list_ids(user, perm)
    if all_ok:
        return list_ids
    if not list_ids:
        return permitted or [-1]  # no permitted lists -> match nothing
    allowed = set(permitted)
    scoped = [i for i in list_ids if i in allowed]
    return scoped or [-1]


async def _attach_lists(subs: list[dict[str, Any]]) -> None:
    if not subs:
        return
    ids = [s["id"] for s in subs]
    by_id = await subscriber_repo.get_subscriber_lists_lazy(ids)
    for s in subs:
        s["lists"] = by_id.get(s["id"]) or []


# ---------------------------------------------------------------------------
# Query / list
# ---------------------------------------------------------------------------


@router.get(
    "/api/subscribers", dependencies=[auth.require("subscribers:get", "subscribers:get_all")]
)
async def get_subscribers(
    user: auth.CurrentUser,
    pg: Pagination = Depends(),
    query: str = "",
    list_id: list[int] = Query(default=[]),
    subscription_status: str = "",
    search: str = "",
    order_by: str = "id",
    order: str = "DESC",
) -> dict[str, Any]:
    lists = _scope_lists(user, list_id, "get")

    if not query:
        # Structured browse (list/status/search/sort) - works on either
        # backend. The arbitrary-SQL path below only ever runs against
        # Postgres directly, so it can't be used once subscribers live in
        # Firestore - there'd be nothing there to query against.
        field = order_by if order_by in _ORDER_FIELDS else "id"
        direction = "ASC" if order.upper() == "ASC" else "DESC"
        results, total = await subscriber_repo.query_subscribers(
            lists, subscription_status, search, field, direction, pg.offset, pg.limit
        )
        await _attach_lists(results)
        return ok(pg.results(results, total, query))

    from app.config import env

    if env.repo_backend_subscribers == "firestore":
        raise bad_request(
            "advanced query segmentation is not available while subscribers are Firestore-backed"
        )

    cond = _query_cond(user, query)
    sql = db.q("query-subscribers").replace("%query%", cond).replace(
        "%order%", _order_clause(order_by, order)
    )
    results = await db.fetch(sql, lists, subscription_status, search, pg.offset, pg.limit)
    await _attach_lists(results)
    count_sql = db.q("query-subscribers-count").replace("%query%", cond)
    total = await db.fetchval(count_sql, lists, subscription_status, search)

    return ok(pg.results(results, int(total or 0), query))


@router.get("/api/subscribers/export", dependencies=[auth.require("subscribers:get_all")])
async def export_subscribers(
    user: auth.CurrentUser,
    query: str = "",
    list_id: list[int] = Query(default=[]),
    subscriber_id: list[int] = Query(default=[], alias="id"),
) -> Response:
    lists = _scope_lists(user, list_id, "get")
    cond = _query_cond(user, query)
    sql = db.q("query-subscribers-for-export").replace("%query%", cond)

    async def generate() -> AsyncIterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["uuid", "email", "name", "attributes", "status", "created_at", "updated_at"])
        yield buf.getvalue()
        last_id, batch = 0, 500
        while True:
            rows = await db.fetch(sql, lists, last_id, subscriber_id, "", "", batch)
            if not rows:
                break
            buf = io.StringIO()
            w = csv.writer(buf)
            for r in rows:
                w.writerow(
                    [
                        r["uuid"], r["email"], r["name"], orjson.dumps(r["attribs"]).decode(),
                        r["status"], r["created_at"], r["updated_at"],
                    ]
                )
                last_id = r["id"]
            yield buf.getvalue()
            if len(rows) < batch:
                break

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="subscribers.csv"'},
    )


@router.get(
    "/api/subscribers/{sub_id}",
    dependencies=[auth.require("subscribers:get", "subscribers:get_all")],
)
async def get_subscriber(sub_id: int) -> dict[str, Any]:
    sub = await subscriber_repo.get_subscriber(sub_id)
    if not sub:
        raise not_found("subscriber not found")
    await _attach_lists([sub])
    return ok(sub)


@router.get(
    "/api/subscribers/{sub_id}/export",
    dependencies=[auth.require("subscribers:get", "subscribers:get_all")],
)
async def export_subscriber_data(sub_id: int) -> dict[str, Any]:
    # $2 is typed UUID by Postgres; "" fails at bind time, so it must be NULL.
    data = await db.fetchval("export-subscriber-data", sub_id, None)
    if not data:
        raise not_found("subscriber not found")
    return ok(data)


@router.get(
    "/api/subscribers/{sub_id}/activity",
    dependencies=[auth.require("subscribers:get", "subscribers:get_all")],
)
async def get_subscriber_activity(sub_id: int) -> dict[str, Any]:
    row = await db.fetchrow("get-subscriber-activity", sub_id)
    return ok(row or {"views": [], "clicks": []})


@router.get("/api/subscribers/{sub_id}/bounces", dependencies=[auth.require("bounces:get")])
async def get_subscriber_bounces(sub_id: int) -> dict[str, Any]:
    # The query is named query-bounces and needs its %order% placeholder filled.
    sql = db.q("query-bounces").replace("%order%", "created_at DESC")
    rows = await db.fetch(sql, 0, 0, sub_id, "", 0, 1000)
    for r in rows:
        r.pop("total", None)
    return ok(rows)


@router.delete("/api/subscribers/{sub_id}/bounces", dependencies=[auth.require("bounces:manage")])
async def delete_subscriber_bounces(sub_id: int) -> dict[str, Any]:
    # $2 is typed UUID; pass NULL rather than "" when looking up by id.
    await db.execute("delete-bounces-by-subscriber", sub_id, None)
    return ok(True)


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------


class SubscriberPayload(BaseModel):
    email: str
    name: str = ""
    status: str = "enabled"
    lists: list[int] = []
    attribs: dict[str, Any] = {}
    preconfirm_subscriptions: bool = False


@router.post("/api/subscribers", dependencies=[auth.require("subscribers:manage")])
async def create_subscriber(payload: SubscriberPayload, user: auth.CurrentUser) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise bad_request("invalid email")
    lists = _scope_lists(user, payload.lists, "manage") if payload.lists else []
    sub_status = "confirmed" if payload.preconfirm_subscriptions else "unconfirmed"
    try:
        sub_id = await subscriber_repo.insert_subscriber(
            str(uuidlib.uuid4()), email, payload.name.strip(), payload.status,
            payload.attribs, lists, [], sub_status,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise bad_request("email already exists") from e
        raise

    # Send opt-in confirmation for double opt-in lists (original behavior).
    if not payload.preconfirm_subscriptions:
        from app import notifs

        await notifs.send_optin_confirmation_by_id(sub_id)

    sub = await subscriber_repo.get_subscriber(sub_id)
    if not sub:
        raise not_found("subscriber not found")
    await _attach_lists([sub])
    return ok(sub)


@router.delete("/api/subscribers/{sub_id}", dependencies=[auth.require("subscribers:manage")])
async def delete_subscriber(sub_id: int) -> dict[str, Any]:
    await subscriber_repo.delete_subscribers([sub_id], [])
    return ok(True)


@router.delete("/api/subscribers", dependencies=[auth.require("subscribers:manage")])
async def delete_subscribers(
    subscriber_id: list[int] = Query(default=[], alias="id")
) -> dict[str, Any]:
    if not subscriber_id:
        raise bad_request("no IDs given")
    await subscriber_repo.delete_subscribers(subscriber_id, [])
    return ok(True)


@router.put(
    "/api/subscribers/{sub_id}/blocklist", dependencies=[auth.require("subscribers:manage")]
)
async def blocklist_subscriber(sub_id: int) -> dict[str, Any]:
    await subscriber_repo.blocklist_subscribers([sub_id])
    return ok(True)


@router.put("/api/subscribers/blocklist", dependencies=[auth.require("subscribers:manage")])
async def blocklist_subscribers(
    subscriber_id: list[int] = Query(default=[], alias="id")
) -> dict[str, Any]:
    if not subscriber_id:
        raise bad_request("no IDs given")
    await subscriber_repo.blocklist_subscribers(subscriber_id)
    return ok(True)


@router.post("/api/subscribers/{sub_id}/optin", dependencies=[auth.require("subscribers:manage")])
async def resend_optin(sub_id: int) -> dict[str, Any]:
    from app import notifs

    sent = await notifs.send_optin_confirmation_by_id(sub_id)
    if not sent:
        raise bad_request("no unconfirmed double opt-in lists to confirm")
    return ok(True)


# ---------------------------------------------------------------------------
# Bulk list management (by explicit IDs and by arbitrary query)
# ---------------------------------------------------------------------------


class ListsPayload(BaseModel):
    ids: list[int] = []
    action: str  # add | remove | unsubscribe
    target_list_ids: list[int] = []
    status: str = ""  # unconfirmed | confirmed | unsubscribed (for add)
    query: str = ""
    list_ids: list[int] = []  # optional list filter for query ops


async def _manage_lists_by_ids(payload: ListsPayload) -> None:
    if payload.action == "add":
        await subscriber_repo.add_subscribers_to_lists(
            payload.ids, payload.target_list_ids, payload.status
        )
    elif payload.action == "remove":
        await subscriber_repo.delete_subscriptions(payload.ids, payload.target_list_ids)
    elif payload.action == "unsubscribe":
        await subscriber_repo.unsubscribe_subscribers_from_lists(
            payload.ids, payload.target_list_ids, []
        )
    else:
        raise bad_request("invalid action")


@router.put("/api/subscribers/lists", dependencies=[auth.require("subscribers:manage")])
async def manage_subscriber_lists(payload: ListsPayload, user: auth.CurrentUser) -> dict[str, Any]:
    if not payload.ids:
        raise bad_request("no IDs given")
    if not payload.target_list_ids:
        raise bad_request("no target lists given")
    payload.target_list_ids = _scope_lists(user, payload.target_list_ids, "manage")
    await _manage_lists_by_ids(payload)
    return ok(True)


@router.put("/api/subscribers/lists/{sub_id}", dependencies=[auth.require("subscribers:manage")])
async def manage_single_subscriber_lists(
    sub_id: int, payload: ListsPayload, user: auth.CurrentUser
) -> dict[str, Any]:
    payload.ids = [sub_id]
    payload.target_list_ids = _scope_lists(user, payload.target_list_ids, "manage")
    await _manage_lists_by_ids(payload)
    return ok(True)


# Declared after the static PUT /api/subscribers/lists and /blocklist paths —
# FastAPI matches routes in declaration order, so {sub_id} would shadow them.
@router.put("/api/subscribers/{sub_id}", dependencies=[auth.require("subscribers:manage")])
async def update_subscriber(
    sub_id: int, payload: SubscriberPayload, user: auth.CurrentUser
) -> dict[str, Any]:
    email = payload.email.strip().lower()
    lists = _scope_lists(user, payload.lists, "manage") if payload.lists else []
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    sub_status = "confirmed" if payload.preconfirm_subscriptions else "unconfirmed"
    await subscriber_repo.update_subscriber_with_lists(
        sub_id, email, payload.name.strip(), payload.status, payload.attribs,
        lists, [], sub_status,
        True,  # delete subscriptions not in the list
        [] if all_ok else (permitted or [-1]),
        False,
    )
    sub = await subscriber_repo.get_subscriber(sub_id)
    if not sub:
        raise not_found("subscriber not found")
    await _attach_lists([sub])
    return ok(sub)


class SubscriberPatch(BaseModel):
    """Every field optional — unset fields keep their current value."""

    email: str | None = None
    name: str | None = None
    status: str | None = None
    lists: list[int] | None = None
    attribs: dict[str, Any] | None = None
    preconfirm_subscriptions: bool = False


@router.patch("/api/subscribers/{sub_id}", dependencies=[auth.require("subscribers:manage")])
async def patch_subscriber(
    sub_id: int, payload: SubscriberPatch, user: auth.CurrentUser
) -> dict[str, Any]:
    """Partial update — port of cmd/subscribers.go PatchSubscriber.

    Prefills the update with the subscriber's current values so only the fields
    actually sent are changed. `lists` being omitted (None) leaves existing
    subscriptions alone; sending [] clears them.
    """
    cur = await subscriber_repo.get_subscriber(sub_id)
    if not cur:
        raise not_found("subscriber not found")

    email = (payload.email or cur["email"]).strip().lower()
    if "@" not in email:
        raise bad_request("invalid email")
    name = (payload.name if payload.name is not None else cur["name"]).strip()
    status = payload.status or cur["status"]
    attribs = payload.attribs if payload.attribs is not None else (cur["attribs"] or {})

    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    sub_status = "confirmed" if payload.preconfirm_subscriptions else "unconfirmed"

    if payload.lists is None:
        # Keep current subscriptions: pass them through and don't prune.
        rows = await subscriber_repo.get_subscriber_lists(sub_id=sub_id)
        lists = [r["id"] for r in rows]
        delete_missing = False
    else:
        lists = _scope_lists(user, payload.lists, "manage")
        delete_missing = True

    await subscriber_repo.update_subscriber_with_lists(
        sub_id, email, name, status, attribs,
        lists, [], sub_status,
        delete_missing,
        [] if all_ok else (permitted or [-1]),
        False,
    )
    sub = await subscriber_repo.get_subscriber(sub_id)
    if not sub:
        raise not_found("subscriber not found")
    await _attach_lists([sub])
    return ok(sub)


def _query_template(user: auth.User, payload: ListsPayload) -> tuple[str, list[Any]]:
    """Build the shared %query% template used by the by-query bulk operations.
    Args: $1 dry_run(false), $2 list filter, $3 subscription status, $4 search."""
    cond = _query_cond(user, payload.query)
    tpl = db.q("query-subscribers-template").replace("%query%", cond)
    lists = _scope_lists(user, payload.list_ids, "manage")
    return tpl, [False, lists, "", ""]


@router.put("/api/subscribers/query/blocklist", dependencies=[auth.require("subscribers:manage")])
async def blocklist_by_query(payload: ListsPayload, user: auth.CurrentUser) -> dict[str, Any]:
    tpl, args = _query_template(user, payload)
    sql = db.q("blocklist-subscribers-by-query").replace("%query%", tpl)
    await db.execute(sql, *args)
    return ok(True)


@router.post("/api/subscribers/query/delete", dependencies=[auth.require("subscribers:manage")])
async def delete_by_query(payload: ListsPayload, user: auth.CurrentUser) -> dict[str, Any]:
    if payload.query.strip() == "" and not payload.list_ids:
        # Match-all deletes must be explicit in the UI; same guard as upstream.
        raise bad_request("refusing to delete with an empty query")
    tpl, args = _query_template(user, payload)
    sql = db.q("delete-subscribers-by-query").replace("%query%", tpl)
    await db.execute(sql, *args)
    return ok(True)


@router.put("/api/subscribers/query/lists", dependencies=[auth.require("subscribers:manage")])
async def manage_lists_by_query(payload: ListsPayload, user: auth.CurrentUser) -> dict[str, Any]:
    if not payload.target_list_ids:
        raise bad_request("no target lists given")
    payload.target_list_ids = _scope_lists(user, payload.target_list_ids, "manage")
    tpl, args = _query_template(user, payload)
    q_by_action = {
        "add": "add-subscribers-to-lists-by-query",
        "remove": "delete-subscriptions-by-query",
        "unsubscribe": "unsubscribe-subscribers-from-lists-by-query",
    }
    if payload.action not in q_by_action:
        raise bad_request("invalid action")
    sql = db.q(q_by_action[payload.action]).replace("%query%", tpl)
    extra: list[Any] = [payload.target_list_ids]
    if payload.action == "add":
        extra.append(payload.status)
    await db.execute(sql, *args, *extra)
    return ok(True)
