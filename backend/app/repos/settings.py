"""Settings repository — Postgres (current) and Firestore (migration target).

Postgres today: a flat `settings` table (key TEXT UNIQUE, value JSONB),
aggregated into one dict by `get-settings` and updated key-by-key by
`update-settings` (only keys that already exist as rows get touched — see
queries/misc.sql). Firestore mirrors this as one `settings/{key}` doc per
key, each holding `{value: <json>}`.
"""

from __future__ import annotations

from typing import Any, Protocol

from app import db


class SettingsRepo(Protocol):
    async def get_all(self) -> dict[str, Any]:
        """The full flat settings map, key -> value."""
        ...

    async def update_many(self, payload: dict[str, Any], known_keys: set[str]) -> None:
        """Update only keys that already exist in known_keys (matches today's
        Postgres behavior: unknown keys are silently ignored, never created)."""
        ...

    async def update_one(self, key: str, value: Any) -> None: ...


class PgSettingsRepo:
    async def get_all(self) -> dict[str, Any]:
        return await db.fetchval("get-settings") or {}

    async def update_many(self, payload: dict[str, Any], known_keys: set[str]) -> None:
        await db.execute("update-settings", payload)

    async def update_one(self, key: str, value: Any) -> None:
        await db.execute("update-settings-by-key", key, value)


class FirestoreSettingsRepo:
    _COLLECTION = "settings"

    def __init__(self) -> None:
        from app.firestore_client import client

        self._db = client()

    async def get_all(self) -> dict[str, Any]:
        import asyncio

        def _run() -> dict[str, Any]:
            out: dict[str, Any] = {}
            for doc in self._db.collection(self._COLLECTION).stream():
                out[doc.id] = (doc.to_dict() or {}).get("value")
            return out

        return await asyncio.to_thread(_run)

    async def update_many(self, payload: dict[str, Any], known_keys: set[str]) -> None:
        import asyncio

        # Mirrors update-settings: only touch keys that already exist.
        to_write = {k: v for k, v in payload.items() if k in known_keys}

        def _run() -> None:
            batch = self._db.batch()
            for key, value in to_write.items():
                ref = self._db.collection(self._COLLECTION).document(key)
                batch.set(ref, {"value": value})
            if to_write:
                batch.commit()

        await asyncio.to_thread(_run)

    async def update_one(self, key: str, value: Any) -> None:
        import asyncio

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(key).set({"value": value})

        await asyncio.to_thread(_run)
