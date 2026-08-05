"""List endpoints — port of cmd/lists.go."""

from __future__ import annotations

import uuid as uuidlib
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import auth, db
from app.utils import Pagination, bad_request, not_found, ok

router = APIRouter(tags=["lists"])

_ORDER_FIELDS = {"name", "status", "created_at", "updated_at", "subscriber_count", "id"}


class ListPayload(BaseModel):
    name: str
    type: str = "private"  # public | private
    optin: str = "single"  # single | double
    status: str = "active"  # active | archived
    tags: list[str] = []
    description: str = ""


@router.get("/api/lists", dependencies=[auth.require("lists:get_all", "list:get")])
async def get_lists(
    user: auth.CurrentUser,
    pg: Pagination = Depends(),
    query: str = "",
    status: str = "",
    type: str = "",
    optin: str = "",
    tag: list[str] = Query(default=[]),
    order_by: str = "id",
    order: str = "ASC",
    minimal: bool = False,
) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "get")

    if minimal:
        rows = await db.fetch("get-lists", "", "", "name", all_ok, permitted)
        return ok({"results": rows})

    field = order_by if order_by in _ORDER_FIELDS else "id"
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    sql = db.q("query-lists").replace("%order%", f"{field} {direction}")
    rows = await db.fetch(
        sql, 0, "", query, type, optin, status, tag, all_ok, permitted, pg.offset, pg.limit
    )
    total = rows[0]["total"] if rows else 0
    for r in rows:
        r.pop("total", None)
    return ok(pg.results(rows, total, query))


@router.get("/api/lists/{list_id}", dependencies=[auth.require("lists:get_all", "list:get")])
async def get_list(list_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "get")
    if not all_ok and list_id not in permitted:
        raise not_found("list not found")
    sql = db.q("query-lists").replace("%order%", "id ASC")
    rows = await db.fetch(sql, list_id, "", "", "", "", "", [], True, [], 0, 1)
    if not rows:
        raise not_found("list not found")
    rows[0].pop("total", None)
    return ok(rows[0])


@router.post("/api/lists", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def create_list(payload: ListPayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise bad_request("invalid list name")
    list_id = await db.fetchval(
        "create-list",
        str(uuidlib.uuid4()), payload.name.strip(), payload.type, payload.optin,
        payload.status, payload.tags, payload.description,
    )
    return await get_list_unscoped(list_id)


async def get_list_unscoped(list_id: int) -> dict[str, Any]:
    sql = db.q("query-lists").replace("%order%", "id ASC")
    rows = await db.fetch(sql, list_id, "", "", "", "", "", [], True, [], 0, 1)
    if not rows:
        raise not_found("list not found")
    rows[0].pop("total", None)
    return ok(rows[0])


@router.put("/api/lists/{list_id}", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def update_list(list_id: int, payload: ListPayload, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    if not all_ok and list_id not in permitted:
        raise not_found("list not found")
    await db.execute(
        "update-list",
        list_id, payload.name.strip(), payload.type, payload.optin, payload.status,
        payload.tags, payload.description,
    )
    return await get_list_unscoped(list_id)


@router.delete(
    "/api/lists/{list_id}", dependencies=[auth.require("lists:manage_all", "list:manage")]
)
async def delete_list(list_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    await db.execute("delete-lists", [list_id], "", all_ok, permitted)
    return ok(True)


@router.delete("/api/lists", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def delete_lists(user: auth.CurrentUser, id: list[int] = Query(default=[])) -> dict[str, Any]:
    if not id:
        raise bad_request("no IDs given")
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    await db.execute("delete-lists", id, "", all_ok, permitted)
    return ok(True)
