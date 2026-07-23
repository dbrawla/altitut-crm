"""In-memory one-time tokens with TTL — port of internal/tmptokens.

Used for password reset links and for rejecting replayed CAPTCHA solutions.
Tokens are consumed on `pop()`, expire on their TTL, and are dropped after
`MAX_TRIES` failed verification attempts so a token cannot be brute-forced.

ponytail: process-local, like the Go original. Multi-process deployments need
this in Postgres — the `sessions` table is the obvious home.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

# Verification attempts allowed before a token is discarded.
MAX_TRIES = 15


@dataclass
class _Token:
    expires_at: float
    data: Any
    count: int = 0


_tokens: dict[str, _Token] = {}
_lock = threading.Lock()


def set(id: str, ttl_seconds: float, data: Any = None) -> None:  # noqa: A001
    """Store a token, overwriting any existing one with the same id."""
    with _lock:
        _tokens[id] = _Token(expires_at=time.monotonic() + ttl_seconds, data=data)


def get(id: str) -> Any | None:  # noqa: A001
    """Return a token's data without consuming it, or None if absent/expired.

    Counts the attempt; after MAX_TRIES the token is dropped.
    """
    with _lock:
        tok = _tokens.get(id)
        if tok is None:
            return None
        if time.monotonic() > tok.expires_at:
            _tokens.pop(id, None)
            return None

        tok.count += 1
        if tok.count > MAX_TRIES:
            _tokens.pop(id, None)
            return None
        return tok.data if tok.data is not None else True


def pop(id: str) -> Any | None:  # noqa: A001
    """Return a token's data and consume it. None if absent or expired."""
    with _lock:
        tok = _tokens.pop(id, None)
        if tok is None or time.monotonic() > tok.expires_at:
            return None
        return tok.data if tok.data is not None else True


def delete(id: str) -> None:  # noqa: A001
    with _lock:
        _tokens.pop(id, None)


def clean() -> int:
    """Drop expired tokens. Returns the number removed."""
    now = time.monotonic()
    with _lock:
        stale = [k for k, v in _tokens.items() if now > v.expires_at]
        for k in stale:
            del _tokens[k]
        return len(stale)
