"""
Runtime settings service — port of internal/core settings + cmd/settings.go.

Settings live in the `settings` DB table as a flat map of dotted keys to JSON
values (exactly the original schema). They are cached here in-process and
hot-reloaded when updated — where the Go app restarts its binary, this port
re-initializes the affected subsystems via registered reload hooks.
"""

from __future__ import annotations

import copy
import logging
import re
import uuid as uuidlib
from collections.abc import Awaitable, Callable
from typing import Any

from app.repos import settings_repo
from app.utils import bad_request, parse_duration

log = logging.getLogger("listmonk")

VERSION = "v5.1.0-py"
PWD_MASK = "•"

# In-process cache of the flat settings map.
cache: dict[str, Any] = {}

# Subsystems (SMTP pool, bounce scanner, …) register async callbacks that run
# after settings change or /api/admin/reload is called.
reload_hooks: list[Callable[[], Awaitable[None]]] = []

_re_smtp_name = re.compile(r"[^a-z0-9\-]")

# (settings key, path within the value). "" = the value itself is the secret;
# "*.field" = list of dicts, each with a secret field (matched by "uuid" on update).
_SECRETS: list[tuple[str, str]] = [
    ("smtp", "*.password"),
    ("bounce.mailboxes", "*.password"),
    ("messengers", "*.password"),
    ("upload.s3.aws_secret_access_key", ""),
    ("bounce.sendgrid_key", ""),
    ("bounce.azure", "shared_secret"),
    ("bounce.postmark", "password"),
    ("bounce.forwardemail", "key"),
    ("bounce.lettermint", "key"),
    ("security.captcha", "hcaptcha.secret"),
    ("security.oidc", "client_secret"),
]


async def load() -> None:
    row = await settings_repo.get_all()
    cache.clear()
    cache.update(row or {})


def get(key: str, default: Any = None) -> Any:
    return cache.get(key, default)


async def reload_app() -> None:
    await load()
    for hook in reload_hooks:
        try:
            await hook()
        except Exception:
            log.exception("error running reload hook")


# ---------------------------------------------------------------------------
# Masking / unmasking of secrets for the settings API
# ---------------------------------------------------------------------------


def _get_path(obj: Any, path: list[str]) -> Any:
    for p in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def _set_path(obj: Any, path: list[str], value: Any) -> None:
    for p in path[:-1]:
        if not isinstance(obj, dict):
            return
        obj = obj.setdefault(p, {})
    if isinstance(obj, dict):
        obj[path[-1]] = value


def _is_masked(v: Any) -> bool:
    return not v or (isinstance(v, str) and set(v) == {PWD_MASK})


def masked(settings: dict[str, Any]) -> dict[str, Any]:
    """Deep copy with every secret replaced by mask characters of equal length."""
    out = copy.deepcopy(settings)
    for key, path in _SECRETS:
        val = out.get(key)
        if val is None:
            continue
        if path.startswith("*."):
            field = path[2:]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get(field):
                        item[field] = PWD_MASK * len(str(item[field]))
        elif path == "":
            if val:
                out[key] = PWD_MASK * len(str(val))
        else:
            parts = path.split(".")
            secret = _get_path(val, parts)
            if secret:
                _set_path(val, parts, PWD_MASK * len(str(secret)))
    return out


def _restore_secrets(new: dict[str, Any], cur: dict[str, Any]) -> None:
    """Copy existing secrets into the incoming payload where they were left
    empty/masked — the UI only sends a secret when the user changes it."""
    for key, path in _SECRETS:
        nval, cval = new.get(key), cur.get(key)
        if path.startswith("*."):
            field = path[2:]
            by_uuid = {i.get("uuid"): i for i in (cval or []) if isinstance(i, dict)}
            for item in nval or []:
                if not isinstance(item, dict):
                    continue
                if not item.get("uuid"):
                    item["uuid"] = str(uuidlib.uuid4())
                if _is_masked(item.get(field)):
                    old = by_uuid.get(item.get("uuid"))
                    item[field] = old.get(field, "") if old else ""
        elif path == "":
            if _is_masked(nval):
                new[key] = cval or ""
        else:
            parts = path.split(".")
            if _is_masked(_get_path(nval, parts)):
                _set_path(nval, parts, _get_path(cval, parts) or "")


# ---------------------------------------------------------------------------
# Update (port of cmd/settings.go UpdateSettings)
# ---------------------------------------------------------------------------


async def update(payload: dict[str, Any]) -> None:
    cur = dict(cache)

    # Only accept known keys.
    new = {k: payload[k] for k in payload if k in cur or k == "migrations"}

    # Validate/sanitize SMTP blocks. "email" is reserved; at least one enabled.
    names: dict[str, bool] = {"email": True}
    has_enabled = False
    for s in new.get("smtp", []):
        if s.get("enabled"):
            has_enabled = True
        name = _re_smtp_name.sub("-", (s.get("name") or "").strip().lower())
        if name:
            if not name.startswith("email-"):
                name = "email-" + name
            if name in names:
                raise bad_request(f"duplicate messenger name: {name}")
            names[name] = True
        s["name"] = name
        s["host"] = (s.get("host") or "").strip()
    if "smtp" in new and not has_enabled:
        raise bad_request("at least one SMTP block should be enabled")

    # Normalize from_addresses.
    for s in new.get("smtp", []):
        if s.get("enabled"):
            s["from_addresses"] = [a.strip() for a in s.get("from_addresses", []) if a.strip()]

    if isinstance(new.get("app.root_url"), str):
        new["app.root_url"] = new["app.root_url"].rstrip("/")

    for b in new.get("bounce.mailboxes", []):
        b["host"] = (b.get("host") or "").strip()
        if b.get("enabled") and parse_duration(b.get("scan_interval", "")) < 60:
            raise bad_request("invalid bounce scan interval (minimum 1m)")

    for m in new.get("messengers", []):
        name = re.sub(r"[^a-z0-9]", "", (m.get("name") or "").lower())
        if not name:
            raise bad_request("invalid messenger name")
        if name in names:
            raise bad_request(f"duplicate messenger name: {name}")
        names[name] = True
        m["name"] = name

    oidc = new.get("security.oidc") or {}
    if oidc.get("enabled") and not (oidc.get("provider_url") and oidc.get("client_id")):
        raise bad_request("invalid OIDC provider settings")

    _restore_secrets(new, cur)

    await settings_repo.update_many(new, set(cur.keys()))
    await reload_app()
