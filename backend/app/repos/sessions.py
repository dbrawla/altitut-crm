"""Session repository — Postgres (current) and Firestore (migration target).

Consolidates what were three separate raw-SQL touchpoints (app/auth.py's
create_session/get_session_user_id/delete_session/delete_user_sessions,
plus routers/auth.py's inline pre-2FA session insert/fetch/delete) behind
one interface. `get()` always applies the session_max_age expiry check —
today's code applied it inconsistently (routers/auth.py's 2FA-pending
lookup never checked age); unifying it is a deliberate small correctness
fix, not scope creep, since Firestore's TTL will expire sessions uniformly
regardless of which code path reads them.
"""

from __future__ import annotations

import secrets
from typing import Any, Protocol

from app import db
from app.config import env


class SessionRepo(Protocol):
    async def create(self, user_id: int, extra: dict[str, Any] | None = None) -> str:
        """Creates a session, returns its id."""
        ...

    async def get(self, sid: str) -> dict[str, Any] | None:
        """Session data if it exists and is within session_max_age, else None."""
        ...

    async def delete(self, sid: str) -> None: ...

    async def delete_for_user(self, user_id: int, except_sid: str = "") -> None: ...


class PgSessionRepo:
    async def create(self, user_id: int, extra: dict[str, Any] | None = None) -> str:
        sid = secrets.token_urlsafe(32)
        data = {"user_id": user_id, **(extra or {})}
        await db.execute("INSERT INTO sessions (id, data) VALUES ($1, $2)", sid, data)
        # Opportunistic prune of expired sessions on every create.
        await db.execute(
            "DELETE FROM sessions WHERE created_at < NOW() - ($1 * INTERVAL '1 second')",
            env.session_max_age,
        )
        return sid

    async def get(self, sid: str) -> dict[str, Any] | None:
        row = await db.fetchrow(
            """SELECT data FROM sessions WHERE id=$1
                AND created_at >= NOW() - ($2 * INTERVAL '1 second')""",
            sid,
            env.session_max_age,
        )
        return row["data"] if row else None

    async def delete(self, sid: str) -> None:
        await db.execute("DELETE FROM sessions WHERE id=$1", sid)

    async def delete_for_user(self, user_id: int, except_sid: str = "") -> None:
        await db.execute("delete-user-sessions", str(user_id), except_sid)


class FirestoreSessionRepo:
    """Sessions expire two ways: app-level check in get() (deterministic,
    works immediately) and a Firestore native TTL policy on `expire_at`
    (configured once via `gcloud firestore fields ttls update` — see the
    migration plan; TTL sweeps lag up to ~24h, so it's cleanup, not the
    source of truth for validity)."""

    _COLLECTION = "sessions"

    def __init__(self) -> None:
        from app.firestore_client import client

        self._db = client()

    async def create(self, user_id: int, extra: dict[str, Any] | None = None) -> str:
        import asyncio
        from datetime import datetime, timedelta, timezone

        sid = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            **(extra or {}),
            "created_at": now,
            "expire_at": now + timedelta(seconds=env.session_max_age),
        }

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(sid).set(doc)

        await asyncio.to_thread(_run)
        return sid

    async def get(self, sid: str) -> dict[str, Any] | None:
        import asyncio
        from datetime import datetime, timedelta, timezone

        def _run() -> dict[str, Any] | None:
            snap = self._db.collection(self._COLLECTION).document(sid).get()
            if not snap.exists:
                return None
            doc = snap.to_dict() or {}
            created_at = doc.get("created_at")
            if created_at is None:
                return None
            if datetime.now(timezone.utc) - created_at > timedelta(seconds=env.session_max_age):
                return None
            return {k: v for k, v in doc.items() if k not in ("created_at", "expire_at")}

        return await asyncio.to_thread(_run)

    async def delete(self, sid: str) -> None:
        import asyncio

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(sid).delete()

        await asyncio.to_thread(_run)

    async def delete_for_user(self, user_id: int, except_sid: str = "") -> None:
        import asyncio

        def _run() -> None:
            docs = self._db.collection(self._COLLECTION).where("user_id", "==", user_id).stream()
            batch = self._db.batch()
            n = 0
            for d in docs:
                if d.id == except_sid:
                    continue
                batch.delete(d.reference)
                n += 1
            if n:
                batch.commit()

        await asyncio.to_thread(_run)
