"""Media repository — Postgres (current) and Firestore (migration target)
implementations behind one interface. See the migration plan: Phase 0
(this abstraction) + Phase 1 (Media is the first domain ported).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, Protocol

from app import db
from app.repos._util import doc_dict


class MediaRepo(Protocol):
    async def query(
        self, search: str, provider: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated media list, newest first. Returns (rows, total)."""
        ...

    async def get(self, media_id: int) -> dict[str, Any] | None: ...

    async def insert(
        self,
        uid: str,
        filename: str,
        thumb: str,
        content_type: str,
        provider: str,
        meta: dict[str, Any],
    ) -> int:
        """Returns the new media row's ID."""
        ...

    async def delete(self, media_id: int) -> dict[str, Any] | None:
        """Deletes the row, returns the deleted row (for filesystem cleanup) or None."""
        ...


class PgMediaRepo:
    """Wraps the existing named queries verbatim — no behavior change from today."""

    async def query(
        self, search: str, provider: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        q = f"%{search}%" if search else ""
        rows = await db.fetch("query-media", q, provider, offset, limit)
        total = rows[0]["total"] if rows else 0
        for r in rows:
            r.pop("total", None)
        return rows, total

    async def get(self, media_id: int) -> dict[str, Any] | None:
        return await db.fetchrow("get-media", media_id, "", "")

    async def insert(
        self,
        uid: str,
        filename: str,
        thumb: str,
        content_type: str,
        provider: str,
        meta: dict[str, Any],
    ) -> int:
        value = await db.fetchval(
            "insert-media", uid, filename, thumb, content_type, provider, meta
        )
        return int(value)

    async def delete(self, media_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow("get-media", media_id, "", "")
        if not row:
            return None
        await db.fetchval("delete-media", media_id)
        return row


class FirestoreMediaRepo:
    """Firestore-backed media repo (migration plan Phase 1).

    Firestore has no SERIAL/auto-increment, but the router's public API
    (media_id: int in URLs) stays unchanged during the migration, so IDs are
    generated from a transactional counter doc and used as the Firestore
    document ID (str(id)). Search has no ILIKE equivalent — the media
    collection is expected to stay small, so `query()` filters/paginates
    in-memory over a provider-scoped read rather than adding a search index.
    """

    _COLLECTION = "media"
    _COUNTER_DOC = "counters/media"

    def __init__(self) -> None:
        from app.firestore_client import client

        self._db = client()

    async def _next_id(self) -> int:
        import asyncio

        from firebase_admin.firestore import transactional

        ref = self._db.document(self._COUNTER_DOC)

        @transactional
        def _txn(transaction: Any) -> int:
            snap = ref.get(transaction=transaction)
            current = (snap.to_dict() or {}).get("next", 0) if snap.exists else 0
            new_id = current + 1
            transaction.set(ref, {"next": new_id})
            return new_id

        return await asyncio.to_thread(_txn, self._db.transaction())

    async def query(
        self, search: str, provider: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        import asyncio

        def _run() -> tuple[list[dict[str, Any]], int]:
            col = self._db.collection(self._COLLECTION).where("provider", "==", provider)
            rows = [doc_dict(d) for d in col.stream()]
            if search:
                needle = search.lower()
                rows = [r for r in rows if needle in (r.get("filename") or "").lower()]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            total = len(rows)
            return rows[offset : offset + limit], total

        return await asyncio.to_thread(_run)

    async def get(self, media_id: int) -> dict[str, Any] | None:
        import asyncio

        def _run() -> dict[str, Any] | None:
            snap = self._db.collection(self._COLLECTION).document(str(media_id)).get()
            return snap.to_dict() if snap.exists else None

        return await asyncio.to_thread(_run)

    async def insert(
        self,
        uid: str,
        filename: str,
        thumb: str,
        content_type: str,
        provider: str,
        meta: dict[str, Any],
    ) -> int:
        import asyncio
        from datetime import datetime

        media_id = await self._next_id()
        row = {
            "id": media_id,
            "uuid": uid,
            "filename": filename,
            "thumb": thumb,
            "content_type": content_type,
            "provider": provider,
            "meta": meta,
            "created_at": datetime.now(UTC).isoformat(),
        }

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(str(media_id)).set(row)

        await asyncio.to_thread(_run)
        return media_id

    async def delete(self, media_id: int) -> dict[str, Any] | None:
        import asyncio

        row = await self.get(media_id)
        if not row:
            return None

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(str(media_id)).delete()

        await asyncio.to_thread(_run)
        return row
