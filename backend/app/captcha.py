"""CAPTCHA verification — port of internal/captcha.

Altcha is a proof-of-work scheme: the server issues `challenge = SHA256(salt+n)`
for a secret random `n <= maxnumber`, plus an HMAC signature over the challenge.
The client brute-forces `n` and returns it. Verifying is just recomputing both
hashes, so this needs no dependency beyond hashlib/hmac.

hCaptcha is verified by calling their siteverify API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from app import settings, tmptokens

log = logging.getLogger("listmonk")

# Regenerated on each process start, exactly like the Go build. Solutions do not
# need to survive a restart — challenges expire in 5 minutes anyway.
_HMAC_KEY = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode()[:32]

_EXPIRY = 300  # seconds
_DEFAULT_COMPLEXITY = 300000


def _cfg() -> dict[str, Any]:
    return settings.get("security.captcha") or {}


def provider() -> str:
    cfg = _cfg()
    if (cfg.get("altcha") or {}).get("enabled"):
        return "altcha"
    if (cfg.get("hcaptcha") or {}).get("enabled"):
        return "hcaptcha"
    return "none"


def is_enabled() -> bool:
    return provider() != "none"


def _sign(challenge: str) -> str:
    return hmac.new(_HMAC_KEY.encode(), challenge.encode(), hashlib.sha256).hexdigest()


def generate_challenge() -> dict[str, Any]:
    """Issue an Altcha challenge. hCaptcha generates challenges client-side."""
    if provider() != "altcha":
        raise ValueError("altcha is not the active captcha provider")

    complexity = int((_cfg().get("altcha") or {}).get("complexity") or _DEFAULT_COMPLEXITY)
    # The salt carries the expiry so it is covered by the signature and cannot
    # be extended by the client.
    salt = f"{secrets.token_hex(12)}?expires={int(time.time()) + _EXPIRY}"
    number = secrets.randbelow(max(complexity, 1) + 1)
    challenge = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()

    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "salt": salt,
        "maxnumber": complexity,
        "signature": _sign(challenge),
    }


def _verify_altcha(payload: str) -> bool:
    try:
        data = json.loads(base64.b64decode(payload))
    except Exception:
        log.debug("malformed altcha payload", exc_info=True)
        return False

    salt = data.get("salt") or ""
    challenge = data.get("challenge") or ""
    number = data.get("number")
    signature = data.get("signature") or ""

    if data.get("algorithm") not in (None, "SHA-256"):
        return False
    if not isinstance(number, int):
        return False

    # Expiry is embedded in the salt as "?expires=<unix>".
    if "?expires=" in salt:
        try:
            if int(salt.split("?expires=", 1)[1].split("&", 1)[0]) < time.time():
                return False
        except ValueError:
            return False

    expected = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    if not hmac.compare_digest(expected, challenge):
        return False
    if not hmac.compare_digest(_sign(challenge), signature):
        return False

    # A valid solution must not be replayable.
    if tmptokens.get(payload) is not None:
        return False
    tmptokens.set(payload, _EXPIRY, True)
    return True


async def _verify_hcaptcha(token: str) -> bool:
    import httpx

    secret = (_cfg().get("hcaptcha") or {}).get("secret") or ""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                "https://hcaptcha.com/siteverify",
                data={"secret": secret, "response": token},
            )
            r.raise_for_status()
            return bool(r.json().get("success"))
    except Exception:
        log.exception("hCaptcha verification request failed")
        return False


async def verify(token: str) -> bool:
    """Verify a CAPTCHA response for whichever provider is enabled."""
    if not token:
        return False
    p = provider()
    if p == "altcha":
        return _verify_altcha(token)
    if p == "hcaptcha":
        return await _verify_hcaptcha(token)
    return False
