"""List endpoints — port of cmd/lists.go."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import auth
from app.repos import list_repo
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
    permitted_ids = None if all_ok else permitted

    if minimal:
        rows = await list_repo.get_lists_minimal(permitted_ids)
        return ok({"results": rows})

    field = order_by if order_by in _ORDER_FIELDS else "id"
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    rows, total = await list_repo.query_lists(
        query, type, optin, status, tag, permitted_ids, field, direction, pg.offset, pg.limit
    )
    return ok(pg.results(rows, total, query))


@router.get("/api/lists/{list_id}", dependencies=[auth.require("lists:get_all", "list:get")])
async def get_list(list_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "get")
    if not all_ok and list_id not in permitted:
        raise not_found("list not found")
    row = await list_repo.get_list(list_id)
    if not row:
        raise not_found("list not found")
    return ok(row)


@router.post("/api/lists", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def create_list(payload: ListPayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise bad_request("invalid list name")
    list_id = await list_repo.create_list(
        payload.name.strip(), payload.type, payload.optin, payload.status,
        payload.tags, payload.description,
    )
    return await get_list_unscoped(list_id)


async def get_list_unscoped(list_id: int) -> dict[str, Any]:
    row = await list_repo.get_list(list_id)
    if not row:
        raise not_found("list not found")
    return ok(row)


@router.put("/api/lists/{list_id}", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def update_list(list_id: int, payload: ListPayload, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    if not all_ok and list_id not in permitted:
        raise not_found("list not found")
    await list_repo.update_list(
        list_id, payload.name.strip(), payload.type, payload.optin, payload.status,
        payload.tags, payload.description,
    )
    return await get_list_unscoped(list_id)


@router.delete(
    "/api/lists/{list_id}", dependencies=[auth.require("lists:manage_all", "list:manage")]
)
async def delete_list(list_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    await list_repo.delete_lists([list_id], None if all_ok else permitted)
    return ok(True)


@router.delete("/api/lists", dependencies=[auth.require("lists:manage_all", "list:manage")])
async def delete_lists(user: auth.CurrentUser, id: list[int] = Query(default=[])) -> dict[str, Any]:
    if not id:
        raise bad_request("no IDs given")
    permitted, all_ok = auth.permitted_list_ids(user, "manage")
    await list_repo.delete_lists(id, None if all_ok else permitted)
    return ok(True)
