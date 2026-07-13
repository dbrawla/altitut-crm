"""
Admin/misc endpoints: health, server config, i18n, settings, about, dashboard.
Port of cmd/admin.go + cmd/settings.go handlers.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException

from app import auth, db, settings
from app.utils import not_found, ok

router = APIRouter(tags=["admin"])


@router.get("/api/health")
async def health():
    return ok(True)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------


def _lang_file(code: str) -> Path:
    # Sanitize: language codes are [a-zA-Z_-] only.
    safe = "".join(c for c in code if c.isalnum() or c in "-_")
    return db.ROOT / "i18n" / f"{safe}.json"


def lang_list() -> list[dict[str, str]]:
    out = []
    for f in sorted((db.ROOT / "i18n").glob("*.json")):
        try:
            data = orjson.loads(f.read_bytes())
            out.append({"code": data.get("_.code", f.stem), "name": data.get("_.name", f.stem)})
        except Exception:
            continue
    return out


def load_lang(code: str) -> dict[str, str]:
    """English is the base; the selected language overlays it (original behavior)."""
    base = orjson.loads(_lang_file("en").read_bytes())
    if code and code != "en":
        f = _lang_file(code)
        if not f.exists():
            raise not_found(f"unknown language: {code}")
        base.update(orjson.loads(f.read_bytes()))
    return base


@router.get("/api/lang/{lang}")
async def get_lang(lang: str):
    return ok(load_lang(lang))


# ---------------------------------------------------------------------------
# Server config
# ---------------------------------------------------------------------------


@router.get("/api/config")
async def server_config(user: auth.CurrentUser):
    captcha = settings.get("security.captcha") or {}
    altcha = captcha.get("altcha") or {}
    hcaptcha = captcha.get("hcaptcha") or {}

    messengers = ["email"] + [
        m["name"] for m in (settings.get("messengers") or []) if m.get("enabled")
    ]

    out: dict[str, Any] = {
        "root_url": settings.get("app.root_url", ""),
        "from_email": settings.get("app.from_email", ""),
        "public_subscription": {
            "enabled": settings.get("app.enable_public_subscription_page", True),
            "captcha_enabled": bool(altcha.get("enabled") or hcaptcha.get("enabled")),
            "captcha_provider": (
                "altcha" if altcha.get("enabled") else "hcaptcha" if hcaptcha.get("enabled") else None
            ),
            "captcha_key": hcaptcha.get("key") if hcaptcha.get("enabled") else None,
            "altcha_complexity": altcha.get("complexity", 0),
            "redirect_urls": [u for u in (settings.get("security.trusted_urls") or []) if u != "*"],
        },
        "privacy": {
            "disable_tracking": settings.get("privacy.disable_tracking", False),
            "individual_tracking": settings.get("privacy.individual_tracking", False),
        },
        "media_provider": settings.get("upload.provider", "filesystem"),
        "messengers": messengers,
        "langs": lang_list(),
        "lang": settings.get("app.lang", "en"),
        "permissions": orjson.loads((db.ROOT / "permissions.json").read_bytes()),
        "update": None,
        "needs_restart": False,
        "has_legacy_user": False,
        "version": settings.VERSION,
    }
    return ok(out)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/api/settings", dependencies=[auth.require("settings:get")])
async def get_settings():
    return ok(settings.masked(settings.cache))


@router.put("/api/settings", dependencies=[auth.require("settings:manage")])
async def update_settings(payload: dict[str, Any]):
    await settings.update(payload)
    return ok(True)


@router.put("/api/settings/{key}", dependencies=[auth.require("settings:manage")])
async def update_setting_by_key(key: str, value: Any):
    if key not in settings.cache:
        raise not_found(f"unknown setting: {key}")
    await db.execute("update-settings-by-key", key, value)
    await settings.reload_app()
    return ok(True)


@router.post("/api/settings/smtp/test", dependencies=[auth.require("settings:manage")])
async def test_smtp(payload: dict[str, Any]):
    from app import messenger

    to = (payload.get("email") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="missing recipient email")
    await messenger.send_smtp_test(payload, to)
    return ok(True)


@router.post("/api/admin/reload", dependencies=[auth.require("settings:manage")])
async def reload_app():
    await settings.reload_app()
    return ok(True)


# ---------------------------------------------------------------------------
# About
# ---------------------------------------------------------------------------


@router.get("/api/about")
async def about(user: auth.CurrentUser):
    dbinfo = await db.fetchval("get-db-info")
    return ok(
        {
            "version": settings.VERSION,
            "build": "python-fastapi",
            "go_version": f"python {platform.python_version()}",
            "go_arch": platform.machine(),
            "database": dbinfo,
            "system": {"num_cpu": None, "aloc_mb": None, "memory_from_os_mb": None},
            "host": {"os": platform.system().lower(), "machine": platform.machine(), "hostname": platform.node()},
        }
    )


# ---------------------------------------------------------------------------
# Dashboard (reads the original materialized views, refreshing when stale)
# ---------------------------------------------------------------------------


async def _refresh_matviews_if_stale(max_age_secs: int = 300) -> None:
    stale = await db.fetchval(
        "SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - MAX(updated_at))), 1e9) FROM mat_dashboard_counts"
    )
    if stale and float(stale) > max_age_secs:
        for v in ("mat_dashboard_counts", "mat_dashboard_charts", "mat_list_subscriber_stats"):
            await db.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {v}")


@router.get("/api/dashboard/counts")
async def dashboard_counts(user: auth.CurrentUser):
    await _refresh_matviews_if_stale()
    return ok(await db.fetchval("get-dashboard-counts"))


@router.get("/api/dashboard/charts")
async def dashboard_charts(user: auth.CurrentUser):
    await _refresh_matviews_if_stale()
    return ok(await db.fetchval("get-dashboard-charts"))
