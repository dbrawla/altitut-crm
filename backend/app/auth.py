"""
Authentication & authorization — port of internal/auth.

Sessions live in the `sessions` DB table (same as the original's
simplesessions Postgres store). API users authenticate per-request with
`Authorization: token username:token`. Permissions are role-based with
optional per-list grants, identical to the original model.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated, Any

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from app import db
from app.config import env

SUPER_ADMIN_ROLE_ID = 1

User = dict[str, Any]


# ---------------------------------------------------------------------------
# Sessions (DB-backed)
# ---------------------------------------------------------------------------


async def create_session(user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    await db.execute(
        "INSERT INTO sessions (id, data) VALUES ($1, $2)", sid, {"user_id": user_id}
    )
    # Opportunistically prune expired sessions.
    await db.execute(
        f"DELETE FROM sessions WHERE created_at < NOW() - INTERVAL '{env.session_max_age} seconds'"
    )
    return sid


async def get_session_user_id(sid: str) -> int | None:
    row = await db.fetchrow(
        f"""SELECT data FROM sessions WHERE id=$1
            AND created_at >= NOW() - INTERVAL '{env.session_max_age} seconds'""",
        sid,
    )
    return row["data"].get("user_id") if row else None


async def delete_session(sid: str) -> None:
    await db.execute("DELETE FROM sessions WHERE id=$1", sid)


async def delete_user_sessions(user_id: int, except_sid: str = "") -> None:
    await db.execute("delete-user-sessions", str(user_id), except_sid)


# ---------------------------------------------------------------------------
# User loading
# ---------------------------------------------------------------------------


def _shape_user(u: User) -> User:
    """Attach the user_role/list_role sub-objects the API/UI expects and drop
    sensitive fields — port of models.User post-retrieval shaping."""
    u = dict(u)
    u.pop("password", None)
    u.pop("twofa_key", None)
    u["user_role"] = {
        "id": u.get("user_role_id"),
        "name": u.pop("user_role_name", None),
        "permissions": u.pop("user_role_permissions", None) or [],
    }
    list_role_id = u.get("list_role_id")
    u["list_role"] = (
        {
            "id": list_role_id,
            "name": u.pop("list_role_name", None),
            "lists": u.pop("list_role_perms", None) or [],
        }
        if list_role_id
        else None
    )
    u.pop("list_role_name", None)
    u.pop("list_role_perms", None)
    return u


async def get_user(
    user_id: int = 0, username: str = "", email: str = "", shape: bool = True
) -> User | None:
    row = await db.fetchrow("get-user", user_id, username, email)
    if not row:
        return None
    return _shape_user(row) if shape else row


def is_super(user: User) -> bool:
    return user["user_role"]["id"] == SUPER_ADMIN_ROLE_ID


def has_perm(user: User, *perms: str) -> bool:
    if is_super(user):
        return True
    have = set(user["user_role"]["permissions"])
    return any(p in have for p in perms)


def permitted_list_ids(user: User, perm: str) -> tuple[list[int], bool]:
    """Returns (list IDs the user may `perm` ("get"/"manage"), all_lists?)."""
    if is_super(user) or f"lists:{perm}_all" in set(user["user_role"]["permissions"]):
        return [], True
    ids: list[int] = []
    if user.get("list_role"):
        for item in user["list_role"]["lists"]:
            if f"list:{perm}" in (item.get("permissions") or []):
                ids.append(item["id"])
    return ids, False


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session_id: str | None = Cookie(default=None, alias=env.session_cookie_name),
) -> User:
    # 1) API token: `Authorization: token username:token`.
    if authorization:
        scheme, _, rest = authorization.partition(" ")
        if scheme.lower() in ("token", "basic") and rest:
            if scheme.lower() == "basic":
                import base64

                try:
                    rest = base64.b64decode(rest).decode()
                except Exception:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
            api_user, _, token = rest.partition(":")
            u = await db.fetchrow("get-user", 0, api_user.strip(), "")
            if (
                u
                and u["type"] == "api"
                and u["status"] == "enabled"
                and u.get("password")
                and hmac.compare_digest(u["password"], token.strip())
            ):
                user = _shape_user(u)
                request.state.user = user
                return user
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API credentials")

    # 2) Session cookie.
    if not session_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    data = await db.fetchrow(
        f"""SELECT data FROM sessions WHERE id=$1
            AND created_at >= NOW() - INTERVAL '{env.session_max_age} seconds'""",
        session_id,
    )
    if not data or not data["data"].get("user_id") or data["data"].get("pre_2fa"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired or invalid")

    user = await get_user(user_id=data["data"]["user_id"])
    if not user or user["status"] != "enabled":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or disabled")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*perms: str):
    """Dependency factory: the user needs at least one of the permissions."""

    async def _check(user: CurrentUser) -> User:
        if not has_perm(user, *perms):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {' or '.join(perms)}"
            )
        return user

    return Depends(_check)
