"""Small helpers shared by the Firestore repos.

Deliberately free of heavy imports: the Firestore SDK is loaded lazily, only
when a domain's repo backend is switched to "firestore".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def doc_dict(snap: Any) -> dict[str, Any]:
    """A Firestore snapshot's data as a dict.

    `DocumentSnapshot.to_dict()` is typed Optional (None for a missing doc).
    Callers read docs they already know exist, so fall back to an empty dict.
    """
    return snap.to_dict() or {}


def order_key(order_by: str) -> Callable[[dict[str, Any]], Any]:
    """Sort key for `rows.sort(...)`: a missing/None value sorts as an empty string."""
    return lambda r: r.get(order_by) if r.get(order_by) is not None else ""
