"""User and role management endpoints — port of cmd/users.go and cmd/roles.go."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app import auth, db
from app.utils import bad_request, not_found, ok

router = APIRouter(tags=["users"])

_USER_TYPES = {"user", "api"}
_USER_STATUSES = {"enabled", "disabled"}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserPayload(BaseModel):
    username: str
    name: str = ""
    email: str = ""
    password: str | None = None
    password_login: bool = True
    type: str = "user"
    user_role_id: int = auth.SUPER_ADMIN_ROLE_ID
    list_role_id: int | None = None
    status: str = "enabled"


def _strip_password(u: dict[str, Any]) -> dict[str, Any]:
    u.pop("password", None)
    return u


@router.get("/api/users", dependencies=[auth.require("users:get")])
async def get_users() -> dict[str, Any]:
    rows = await db.fetch("get-users")
    return ok([_strip_password(r) for r in rows])


@router.get("/api/users/{user_id}", dependencies=[auth.require("users:get")])
async def get_user(user_id: int) -> dict[str, Any]:
    row = await db.fetchrow("get-user", user_id, "", "")
    if not row:
        raise not_found("user not found")
    return ok(_strip_password(row))


def _validate(p: UserPayload, creating: bool) -> None:
    if not p.username.strip():
        raise bad_request("invalid username")
    if p.type not in _USER_TYPES:
        raise bad_request("invalid user type")
    if p.status not in _USER_STATUSES:
        raise bad_request("invalid user status")
    if p.type == "user" and p.password_login:
        if creating and not p.password:
            raise bad_request("password is required")
        if p.password and len(p.password) < 8:
            raise bad_request("password must be at least 8 characters")


@router.post("/api/users", dependencies=[auth.require("users:manage")])
async def create_user(payload: UserPayload) -> dict[str, Any]:
    _validate(payload, creating=True)

    # API users authenticate with a generated token stored verbatim (no bcrypt).
    token = ""
    if payload.type == "api":
        token = secrets.token_hex(16)
        password, password_login = token, False
    else:
        password, password_login = payload.password or "", payload.password_login

    user_id = await db.fetchval(
        "create-user",
        payload.username.strip(),
        password_login,
        password,
        payload.email.strip() or f"{payload.username.strip()}@listmonk",
        payload.name.strip() or payload.username.strip(),
        payload.type,
        payload.user_role_id,
        payload.list_role_id,
        payload.status,
    )
    if not user_id:
        raise bad_request("could not create user")

    out = _strip_password(await db.fetchrow("get-user", user_id, "", "") or {})
    if token:
        # Only ever returned once, at creation.
        out["password"] = token
    return ok(out)


@router.put("/api/users/{user_id}", dependencies=[auth.require("users:manage")])
async def update_user(user_id: int, payload: UserPayload) -> dict[str, Any]:
    _validate(payload, creating=False)

    cur = await db.fetchrow("get-user", user_id, "", "")
    if not cur:
        raise not_found("user not found")

    # $9: <0 clears the list role, 0 leaves it untouched, >0 sets it.
    list_role = payload.list_role_id if payload.list_role_id else -1

    await db.execute(
        "update-user",
        user_id,
        payload.username.strip(),
        payload.password_login,
        payload.password or "",
        payload.email.strip(),
        payload.name.strip(),
        payload.type,
        payload.user_role_id,
        list_role,
        payload.status,
    )
    row = await db.fetchrow("get-user", user_id, "", "")
    if not row:
        raise not_found("user not found")

    # Changing the password or disabling the account invalidates live sessions.
    if payload.password or payload.status == "disabled":
        await auth.delete_user_sessions(user_id)

    return ok(_strip_password(row))


async def _delete_users(ids: list[int]) -> None:
    if not ids:
        raise bad_request("no user IDs given")
    await db.execute("delete-users", ids)
    for i in ids:
        await auth.delete_user_sessions(i)


@router.delete("/api/users/{user_id}", dependencies=[auth.require("users:manage")])
async def delete_user(user_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    if user_id == user["id"]:
        raise bad_request("cannot delete your own account")
    await _delete_users([user_id])
    return ok(True)


@router.delete("/api/users", dependencies=[auth.require("users:manage")])
async def delete_users(id: list[int], user: auth.CurrentUser) -> dict[str, Any]:
    if user["id"] in id:
        raise bad_request("cannot delete your own account")
    await _delete_users(id)
    return ok(True)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class ListPermission(BaseModel):
    id: int
    permissions: list[str] = []


class RolePayload(BaseModel):
    name: str
    permissions: list[str] = []
    lists: list[ListPermission] = []


@router.get("/api/roles/users", dependencies=[auth.require("roles:get")])
async def get_user_roles() -> dict[str, Any]:
    return ok(await db.fetch("get-user-roles", 0))


@router.get("/api/roles/lists", dependencies=[auth.require("roles:get")])
async def get_list_roles() -> dict[str, Any]:
    return ok(await db.fetch("get-list-roles"))


async def _upsert_list_perms(role_id: int, lists: list[ListPermission]) -> None:
    """Child `roles` rows (parent_id, list_id) hold the per-list permissions."""
    list_ids = [ln.id for ln in lists]
    # $3 is TEXT[][] — Postgres rejects ragged 2-D arrays, so pad every row to
    # the widest one with '' (the query ARRAY_REMOVEs the blanks).
    width = max((len(ln.permissions) for ln in lists), default=0)
    perms = [ln.permissions + [""] * (width - len(ln.permissions)) for ln in lists]
    await db.execute("upsert-list-permissions", role_id, list_ids, perms)


@router.post("/api/roles/users", dependencies=[auth.require("roles:manage")])
async def create_user_role(payload: RolePayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise bad_request("invalid role name")
    row = await db.fetchrow("create-role", payload.name.strip(), "user", payload.permissions)
    return ok(row)


@router.post("/api/roles/lists", dependencies=[auth.require("roles:manage")])
async def create_list_role(payload: RolePayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise bad_request("invalid role name")
    row = await db.fetchrow("create-role", payload.name.strip(), "list", [])
    if not row:
        raise bad_request("could not create role")
    await _upsert_list_perms(row["id"], payload.lists)
    rows = await db.fetch("get-list-roles")
    return ok(next((r for r in rows if r["id"] == row["id"]), row))


@router.put("/api/roles/users/{role_id}", dependencies=[auth.require("roles:manage")])
async def update_user_role(role_id: int, payload: RolePayload) -> dict[str, Any]:
    if role_id == auth.SUPER_ADMIN_ROLE_ID:
        raise bad_request("cannot modify the super admin role")
    row = await db.fetchrow("update-role", role_id, payload.name.strip(), payload.permissions)
    if not row:
        raise not_found("role not found")
    return ok(row)


@router.put("/api/roles/lists/{role_id}", dependencies=[auth.require("roles:manage")])
async def update_list_role(role_id: int, payload: RolePayload) -> dict[str, Any]:
    row = await db.fetchrow("update-role", role_id, payload.name.strip(), [])
    if not row:
        raise not_found("role not found")
    await _upsert_list_perms(role_id, payload.lists)
    rows = await db.fetch("get-list-roles")
    return ok(next((r for r in rows if r["id"] == role_id), row))


@router.delete("/api/roles/{role_id}", dependencies=[auth.require("roles:manage")])
async def delete_role(role_id: int) -> dict[str, Any]:
    if role_id == auth.SUPER_ADMIN_ROLE_ID:
        raise bad_request("cannot delete the super admin role")
    await db.execute("delete-role", role_id)
    return ok(True)
