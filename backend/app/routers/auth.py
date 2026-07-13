"""Auth endpoints: login (+TOTP 2FA), logout, OIDC, profile, 2FA management."""

from __future__ import annotations

import base64
import io
import secrets
import time

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import auth, db, settings
from app.config import env
from app.utils import bad_request, ok

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=env.session_cookie_name,
        value=sid,
        max_age=env.session_max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login(payload: LoginRequest, response: Response):
    # Password verification happens in Postgres via CRYPT(), like the original.
    user = await db.fetchrow("login-user", payload.username.strip(), payload.password)
    if not user:
        raise HTTPException(status_code=403, detail="invalid credentials")

    if user["twofa_type"] == "totp":
        sid = secrets.token_urlsafe(32)
        await db.execute(
            "INSERT INTO sessions (id, data) VALUES ($1, $2)",
            sid,
            {"user_id": user["id"], "pre_2fa": True},
        )
        _set_session_cookie(response, sid)
        return ok({"twofa_required": True})

    sid = await auth.create_session(user["id"])
    _set_session_cookie(response, sid)
    return ok(await auth.get_user(user_id=user["id"]))


class TotpRequest(BaseModel):
    code: str


@router.post("/api/login/twofa")
async def login_twofa(
    payload: TotpRequest,
    response: Response,
    session_id: str | None = Cookie(default=None, alias=env.session_cookie_name),
):
    if not session_id:
        raise HTTPException(status_code=401, detail="not authenticated")
    row = await db.fetchrow("SELECT data FROM sessions WHERE id=$1", session_id)
    if not row or not row["data"].get("pre_2fa"):
        raise HTTPException(status_code=401, detail="no pending 2FA login")

    user = await db.fetchrow("get-user", row["data"]["user_id"], "", "")
    if not user or user["status"] != "enabled":
        raise HTTPException(status_code=401, detail="user not found or disabled")

    import pyotp

    if not user.get("twofa_key") or not pyotp.TOTP(user["twofa_key"]).verify(
        payload.code.strip(), valid_window=1
    ):
        raise HTTPException(status_code=403, detail="invalid 2FA code")

    await db.execute("DELETE FROM sessions WHERE id=$1", session_id)
    sid = await auth.create_session(user["id"])
    _set_session_cookie(response, sid)
    return ok(await auth.get_user(user_id=user["id"]))


@router.post("/api/logout")
async def logout(
    response: Response,
    user: auth.CurrentUser,
    session_id: str | None = Cookie(default=None, alias=env.session_cookie_name),
):
    if session_id:
        await auth.delete_session(session_id)
    response.delete_cookie(env.session_cookie_name, path="/")
    return ok(True)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/api/profile")
async def get_profile(user: auth.CurrentUser):
    return ok(user)


class ProfileUpdate(BaseModel):
    name: str
    email: str
    password: str | None = None
    password2: str | None = None


@router.put("/api/profile")
async def update_profile(
    payload: ProfileUpdate,
    user: auth.CurrentUser,
    session_id: str | None = Cookie(default=None, alias=env.session_cookie_name),
):
    if payload.password and payload.password != (payload.password2 or payload.password):
        raise bad_request("passwords do not match")
    await db.execute(
        "update-user-profile",
        user["id"],
        payload.name.strip(),
        payload.email.strip(),
        user["password_login"],
        payload.password or "",
    )
    # Changing the password invalidates all other sessions.
    if payload.password:
        await auth.delete_user_sessions(user["id"], session_id or "")
    return ok(await auth.get_user(user_id=user["id"]))


# ---------------------------------------------------------------------------
# TOTP 2FA management
# ---------------------------------------------------------------------------


def _check_self_or_admin(user: auth.User, target_id: int) -> None:
    if user["id"] != target_id and not auth.has_perm(user, "users:manage"):
        raise HTTPException(status_code=403, detail="permission denied")


@router.get("/api/users/{user_id}/twofa/totp")
async def get_twofa_totp(user_id: int, user: auth.CurrentUser):
    """Generate (but don't yet enable) a TOTP secret + QR for enrollment."""
    _check_self_or_admin(user, user_id)
    import pyotp
    import qrcode

    target = await db.fetchrow("get-user", user_id, "", "")
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=target["username"], issuer_name=settings.get("app.site_name", "listmonk")
    )
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return ok(
        {
            "secret": secret,
            "uri": uri,
            "qr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        }
    )


class TotpEnable(BaseModel):
    secret: str
    code: str


@router.put("/api/users/{user_id}/twofa")
async def enable_twofa(user_id: int, payload: TotpEnable, user: auth.CurrentUser):
    _check_self_or_admin(user, user_id)
    import pyotp

    if not pyotp.TOTP(payload.secret).verify(payload.code.strip(), valid_window=1):
        raise bad_request("invalid 2FA code")
    await db.execute("set-user-twofa", user_id, "totp", payload.secret)
    return ok(True)


@router.delete("/api/users/{user_id}/twofa")
async def disable_twofa(user_id: int, user: auth.CurrentUser):
    _check_self_or_admin(user, user_id)
    await db.execute("set-user-twofa", user_id, "none", None)
    return ok(True)


# ---------------------------------------------------------------------------
# OIDC (port of internal/auth OIDC flow)
# ---------------------------------------------------------------------------

# ponytail: in-memory OIDC state store — single process; move to the sessions
# table if the app ever runs multi-worker.
_oidc_states: dict[str, float] = {}


def _oidc_cfg() -> dict:
    cfg = settings.get("security.oidc") or {}
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="OIDC is not enabled")
    return cfg


async def _oidc_provider_meta(provider_url: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(provider_url.rstrip("/") + "/.well-known/openid-configuration")
        r.raise_for_status()
        return r.json()


@router.get("/auth/oidc")
@router.post("/auth/oidc")
async def oidc(request: Request):
    cfg = _oidc_cfg()
    root_url = settings.get("app.root_url", "").rstrip("/")
    redirect_uri = f"{root_url}/auth/oidc"
    meta = await _oidc_provider_meta(cfg["provider_url"])

    params = dict(request.query_params)
    code = params.get("code")

    if not code:
        # Initiate the flow.
        state = secrets.token_urlsafe(24)
        now = time.time()
        for k, exp in list(_oidc_states.items()):
            if exp < now:
                _oidc_states.pop(k, None)
        _oidc_states[state] = now + 600
        from urllib.parse import urlencode

        q = urlencode(
            {
                "response_type": "code",
                "client_id": cfg["client_id"],
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
                "state": state,
            }
        )
        return RedirectResponse(f"{meta['authorization_endpoint']}?{q}")

    # Callback.
    if params.get("state") not in _oidc_states:
        raise HTTPException(status_code=403, detail="invalid OIDC state")
    _oidc_states.pop(params["state"], None)

    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        tok = await client.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cfg["client_id"],
                "client_secret": cfg.get("client_secret", ""),
            },
        )
        tok.raise_for_status()
        access_token = tok.json()["access_token"]
        ui = await client.get(
            meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"}
        )
        ui.raise_for_status()
        claims = ui.json()

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=403, detail="OIDC provider returned no email")

    user = await auth.get_user(email=email)
    if not user and cfg.get("auto_create_users"):
        username = email
        await db.fetchval(
            "create-user",
            username,
            False,
            "",
            email,
            claims.get("name") or email,
            "user",
            cfg.get("default_user_role_id") or auth.SUPER_ADMIN_ROLE_ID,
            cfg.get("default_list_role_id"),
            "enabled",
        )
        user = await auth.get_user(email=email)
    if not user or user["status"] != "enabled":
        raise HTTPException(status_code=403, detail="user not found or disabled")

    await db.execute("update-user-login", user["id"], claims.get("picture") or "")
    sid = await auth.create_session(user["id"])
    resp = RedirectResponse(url="/admin", status_code=302)
    _set_session_cookie(resp, sid)
    return resp
