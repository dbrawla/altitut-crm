"""Auth endpoints: login (+TOTP 2FA), logout, OIDC, profile, 2FA management."""

from __future__ import annotations

import base64
import io
import secrets
import time
from typing import Any

from fastapi import APIRouter, Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import auth, db, settings, tmptokens
from app.config import env
from app.utils import bad_request, ok

router = APIRouter(tags=["auth"])

# How long a password reset link stays valid.
PASSWORD_RESET_TTL = 30 * 60
MIN_PASSWORD_LEN = 8


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=env.session_cookie_name,
        value=sid,
        max_age=env.session_max_age,
        httponly=True,
        secure=env.session_cookie_secure,
        samesite=env.session_cookie_samesite,
        path="/",
    )


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    # Password verification happens in Postgres via CRYPT(), like the original.
    user = await db.fetchrow("login-user", payload.username.strip(), payload.password)
    if not user:
        raise HTTPException(status_code=403, detail="invalid credentials")

    if user["twofa_type"] == "totp":
        sid = await auth.create_session(user["id"], extra={"pre_2fa": True})
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
) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=401, detail="not authenticated")
    data = await auth.session_repo.get(session_id)
    if not data or not data.get("pre_2fa"):
        raise HTTPException(status_code=401, detail="no pending 2FA login")

    user = await db.fetchrow("get-user", data["user_id"], "", "")
    if not user or user["status"] != "enabled":
        raise HTTPException(status_code=401, detail="user not found or disabled")

    import pyotp

    if not user.get("twofa_key") or not pyotp.TOTP(user["twofa_key"]).verify(
        payload.code.strip(), valid_window=1
    ):
        raise HTTPException(status_code=403, detail="invalid 2FA code")

    await auth.delete_session(session_id)
    sid = await auth.create_session(user["id"])
    _set_session_cookie(response, sid)
    return ok(await auth.get_user(user_id=user["id"]))


@router.post("/api/logout")
async def logout(
    response: Response,
    user: auth.CurrentUser,
    session_id: str | None = Cookie(default=None, alias=env.session_cookie_name),
) -> dict[str, Any]:
    if session_id:
        await auth.delete_session(session_id)
    # Flags must match those used when setting it, or the browser keeps the cookie.
    response.delete_cookie(
        env.session_cookie_name,
        path="/",
        httponly=True,
        secure=env.session_cookie_secure,
        samesite=env.session_cookie_samesite,
    )
    return ok(True)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/api/profile")
async def get_profile(user: auth.CurrentUser) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
# Password reset (/admin/forgot, /admin/reset)
# ---------------------------------------------------------------------------


def _auth_page(title: str, body: str) -> HTMLResponse:
    from app.routers.public import _page

    return _page(title, body)


# Shown for every /admin/forgot POST regardless of whether the account exists,
# so the endpoint cannot be used to enumerate registered e-mail addresses.
_SENT_MSG = (
    "<p>If an account with that e-mail exists, a password reset link has been sent to it.</p>"
)


@router.get("/admin/forgot", include_in_schema=False)
async def forgot_page() -> HTMLResponse:
    return _auth_page(
        "Reset password",
        '<form method="post">'
        '<label>E-mail <input type="email" name="email" required style="width:100%"></label>'
        '<p><button type="submit">Send reset link</button></p></form>'
        '<p><a href="/admin/login">Back to login</a></p>',
    )


@router.post("/admin/forgot", include_in_schema=False)
async def forgot_submit(request: Request, email: str = Form(default="")) -> HTMLResponse:
    email = email.strip().lower()

    # Every failure path below returns the same message on purpose.
    if "@" in email and len(email) <= 320:
        user = await auth.get_user(email=email)
        if user and user["password_login"] and user["status"] == "enabled":
            token = secrets.token_urlsafe(32)
            tmptokens.set(email, PASSWORD_RESET_TTL, token)

            from urllib.parse import quote

            from app import notifs, tmpl

            root = (settings.get("app.root_url") or "").rstrip("/")
            reset_url = f"{root}/admin/reset?token={token}&email={quote(email)}"
            try:
                html = tmpl.render_system_email("forgot-password", {"ResetURL": reset_url})
                await notifs.send_email(email, "Reset your password", html)
            except Exception:
                # Don't leak delivery failures back to the form.
                import logging

                logging.getLogger("listmonk").exception("failed sending password reset email")

    return _auth_page("Reset password", _SENT_MSG)


async def _valid_reset(token: str, email: str) -> dict[str, Any] | None:
    """Return the user if (email, token) is a live reset request."""
    if not token or not email:
        return None
    stored = tmptokens.get(email)
    if not isinstance(stored, str) or not secrets.compare_digest(stored, token):
        return None
    user = await auth.get_user(email=email)
    if not user or not user["password_login"] or user["status"] != "enabled":
        return None
    return user


def _reset_form(token: str, email: str, error: str = "") -> HTMLResponse:
    from html import escape

    err = f'<div class="alert alert-error">{escape(error)}</div>' if error else ""
    return _auth_page(
        "Reset password",
        f"{err}<form method=\"post\">"
        f'<input type="hidden" name="token" value="{escape(token)}">'
        f'<input type="hidden" name="email" value="{escape(email)}">'
        '<label>New password <input type="password" name="password"'
        ' required style="width:100%"></label>'
        '<label>Repeat password <input type="password" name="password2"'
        ' required style="width:100%"></label>'
        '<p><button type="submit">Set password</button></p></form>',
    )


@router.get("/admin/reset", include_in_schema=False)
async def reset_page(token: str = "", email: str = "") -> HTMLResponse:
    email = email.strip().lower()
    if not await _valid_reset(token.strip(), email):
        return _auth_page("Reset password", "<p>This reset link is invalid or has expired.</p>")
    return _reset_form(token.strip(), email)


@router.post("/admin/reset", include_in_schema=False)
async def reset_submit(
    token: str = Form(default=""),
    email: str = Form(default=""),
    password: str = Form(default=""),
    password2: str = Form(default=""),
) -> HTMLResponse:
    token, email = token.strip(), email.strip().lower()

    user = await _valid_reset(token, email)
    if not user:
        return _auth_page("Reset password", "<p>This reset link is invalid or has expired.</p>")

    if len(password) < MIN_PASSWORD_LEN:
        return _reset_form(
        token, email, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    )
    if password != password2:
        return _reset_form(token, email, "The passwords do not match.")

    # Consume the token only once the new password is known-good, so a typo
    # doesn't force the user to request a fresh link.
    stored = tmptokens.pop(email)
    if not isinstance(stored, str) or not secrets.compare_digest(stored, token):
        return _auth_page("Reset password", "<p>This reset link is invalid or has expired.</p>")

    await db.execute(
        "update-user-profile", user["id"], user["name"], user["email"], True, password
    )
    # A password change invalidates every existing session for that user.
    await auth.delete_user_sessions(user["id"])

    return _auth_page(
        "Password changed",
        '<p>Your password has been updated.</p><p><a href="/admin/login">Log in</a></p>',
    )


# ---------------------------------------------------------------------------
# TOTP 2FA management
# ---------------------------------------------------------------------------


def _check_self_or_admin(user: auth.User, target_id: int) -> None:
    if user["id"] != target_id and not auth.has_perm(user, "users:manage"):
        raise HTTPException(status_code=403, detail="permission denied")


@router.get("/api/users/{user_id}/twofa/totp")
async def get_twofa_totp(user_id: int, user: auth.CurrentUser) -> dict[str, Any]:
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
    qrcode.make(uri).save(buf)  # PNG is the default image factory
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
async def enable_twofa(user_id: int, payload: TotpEnable, user: auth.CurrentUser) -> dict[str, Any]:
    _check_self_or_admin(user, user_id)
    import pyotp

    if not pyotp.TOTP(payload.secret).verify(payload.code.strip(), valid_window=1):
        raise bad_request("invalid 2FA code")
    await db.execute("set-user-twofa", user_id, "totp", payload.secret)
    return ok(True)


@router.delete("/api/users/{user_id}/twofa")
async def disable_twofa(user_id: int, user: auth.CurrentUser) -> dict[str, Any]:
    _check_self_or_admin(user, user_id)
    await db.execute("set-user-twofa", user_id, "none", None)
    return ok(True)


# ---------------------------------------------------------------------------
# OIDC (port of internal/auth OIDC flow)
# ---------------------------------------------------------------------------

# ponytail: in-memory OIDC state store — single process; move to the sessions
# table if the app ever runs multi-worker.
_oidc_states: dict[str, float] = {}


def _oidc_cfg() -> dict[str, Any]:
    cfg = settings.get("security.oidc") or {}
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="OIDC is not enabled")
    return cfg


async def _oidc_provider_meta(provider_url: str) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(provider_url.rstrip("/") + "/.well-known/openid-configuration")
        r.raise_for_status()
        meta: dict[str, Any] = r.json()
        return meta


@router.get("/auth/oidc")
@router.post("/auth/oidc")
async def oidc(request: Request) -> Response:
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
