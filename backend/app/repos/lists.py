"""List repository — Postgres (current) and Firestore (migration target).

Subscriber counts (today's mat_list_subscriber_stats materialized view)
become a distributed-counter subcollection per the migration plan:
lists/{id}/counter_shards/{shardId}, summed on read.

Where counts actually come from is keyed on where *Subscribers* lives
(env.repo_backend_subscribers), independent of where Lists itself lives -
these can be, and during the migration transition typically are, on
different backends. If Lists stays Postgres-backed after Subscribers cuts
over to Firestore, the mat_list_subscriber_stats materialized view stops
being the source of truth (it only reflects Postgres's own subscriber_lists
table) and would silently go stale - discovered and fixed during Phase 4b
testing, not a hypothetical: signing up a real subscriber after the
Subscribers cutover left the Lists page one count behind reality. See
_list_subscriber_stats() below, which both repo classes use.

Search/filter: Postgres does full-text search (TO_TSVECTOR/ILIKE) and tag
array containment (<@) in SQL. Firestore has neither, so equality filters
(type/optin/status) run as real queries and search/tags/sort/paginate run
in-memory over that bounded result - reasonable at list-table volumes
(admin-configured, not high-cardinality), same pattern as Media's search.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from app import db
from app.config import env


async def _firestore_counter_stats(list_id: int) -> tuple[dict[str, int], int]:
    """Sums lists/{id}/counter_shards/* directly against Firestore,
    regardless of which backend Lists itself is on."""
    from app.firestore_client import client

    def _run() -> tuple[dict[str, int], int]:
        shards = (
            client()
            .collection("lists")
            .document(str(list_id))
            .collection("counter_shards")
            .stream()
        )
        statuses: dict[str, int] = {}
        for s in shards:
            for status, count in (s.to_dict() or {}).items():
                statuses[status] = statuses.get(status, 0) + count
        return statuses, sum(statuses.values())

    return await asyncio.to_thread(_run)


async def _postgres_counter_stats(list_id: int) -> tuple[dict[str, int], int]:
    rows = await db.fetch(
        "SELECT status, subscriber_count FROM mat_list_subscriber_stats WHERE list_id = $1",
        list_id,
    )
    statuses = {r["status"]: r["subscriber_count"] for r in rows if r["status"]}
    return statuses, sum(statuses.values())


async def _list_subscriber_stats(list_id: int) -> tuple[dict[str, int], int] | None:
    """Returns (statuses, total) from wherever subscriber membership
    actually lives, or None if that's Postgres AND the caller is
    PgListRepo (whose own query already has correct counts baked in via
    mat_list_subscriber_stats in that case - nothing to override)."""
    if env.repo_backend_subscribers == "firestore":
        return await _firestore_counter_stats(list_id)
    return None


class ListRepo(Protocol):
    async def query_lists(
        self,
        search: str,
        list_type: str,
        optin: str,
        status: str,
        tags: list[str],
        permitted_ids: list[int] | None,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """permitted_ids=None means unrestricted (all_ok=True)."""
        ...

    async def get_list(
        self, list_id: int, permitted_ids: list[int] | None = None
    ) -> dict[str, Any] | None: ...

    async def get_lists_minimal(self, permitted_ids: list[int] | None) -> list[dict[str, Any]]: ...

    async def get_lists_by_optin(
        self, optin: str, ids: list[int] | None, uuids: list[str] | None
    ) -> list[dict[str, Any]]: ...

    async def create_list(
        self, name: str, type_: str, optin: str, status: str, tags: list[str], description: str
    ) -> int: ...

    async def update_list(
        self,
        list_id: int,
        name: str,
        type_: str,
        optin: str,
        status: str,
        tags: list[str],
        description: str,
    ) -> None: ...

    async def delete_lists(self, ids: list[int], permitted_ids: list[int] | None) -> None: ...


def _matches(row: dict[str, Any], search: str, tags: list[str]) -> bool:
    if search and search.lower() not in (row.get("name") or "").lower():
        return False
    if tags and not set(tags).issubset(set(row.get("tags") or [])):
        return False
    return True


class PgListRepo:
    async def query_lists(
        self,
        search: str,
        list_type: str,
        optin: str,
        status: str,
        tags: list[str],
        permitted_ids: list[int] | None,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        sql = db.q("query-lists").replace("%order%", f"{order_by} {order}")
        rows = await db.fetch(
            sql,
            0,
            "",
            search,
            list_type,
            optin,
            status,
            tags,
            permitted_ids is None,
            permitted_ids or [],
            offset,
            limit,
        )
        total = rows[0]["total"] if rows else 0
        for r in rows:
            r.pop("total", None)
            stats = await _list_subscriber_stats(r["id"])
            if stats is not None:
                r["subscriber_statuses"], r["subscriber_count"] = stats
        return rows, total

    async def get_list(
        self, list_id: int, permitted_ids: list[int] | None = None
    ) -> dict[str, Any] | None:
        sql = db.q("query-lists").replace("%order%", "id ASC")
        rows = await db.fetch(
            sql, list_id, "", "", "", "", "", [], permitted_ids is None, permitted_ids or [], 0, 1
        )
        if not rows:
            return None
        rows[0].pop("total", None)
        stats = await _list_subscriber_stats(list_id)
        if stats is not None:
            rows[0]["subscriber_statuses"], rows[0]["subscriber_count"] = stats
        return rows[0]

    async def get_lists_minimal(self, permitted_ids: list[int] | None) -> list[dict[str, Any]]:
        return await db.fetch(
            "get-lists", "", "", "name", permitted_ids is None, permitted_ids or []
        )

    async def get_lists_by_optin(
        self, optin: str, ids: list[int] | None, uuids: list[str] | None
    ) -> list[dict[str, Any]]:
        return await db.fetch("get-lists-by-optin", optin, ids, uuids)

    async def create_list(
        self, name: str, type_: str, optin: str, status: str, tags: list[str], description: str
    ) -> int:
        import uuid as uuidlib

        return await db.fetchval(
            "create-list", str(uuidlib.uuid4()), name, type_, optin, status, tags, description
        )

    async def update_list(
        self,
        list_id: int,
        name: str,
        type_: str,
        optin: str,
        status: str,
        tags: list[str],
        description: str,
    ) -> None:
        await db.execute("update-list", list_id, name, type_, optin, status, tags, description)

    async def delete_lists(self, ids: list[int], permitted_ids: list[int] | None) -> None:
        await db.execute("delete-lists", ids, "", permitted_ids is None, permitted_ids or [])


class FirestoreListRepo:
    _COLLECTION = "lists"
    _COUNTER_DOC = "counters/lists"

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

    async def _subscriber_stats(self, list_id: int) -> tuple[dict[str, int], int]:
        """Reads from wherever subscriber membership actually lives - the
        counter shards under this same Firestore collection only have
        correct data if Subscribers is also Firestore-backed; otherwise
        membership (and truth) is still in Postgres's
        mat_list_subscriber_stats. Mirrors PgListRepo's symmetric handling
        in _list_subscriber_stats() for the reverse backend split."""
        if env.repo_backend_subscribers == "firestore":
            return await _firestore_counter_stats(list_id)
        return await _postgres_counter_stats(list_id)

    async def _all_rows(self, list_type: str, optin: str, status: str) -> list[dict[str, Any]]:
        import asyncio

        def _run() -> list[dict[str, Any]]:
            q = self._db.collection(self._COLLECTION)
            if list_type:
                q = q.where("type", "==", list_type)
            if optin:
                q = q.where("optin", "==", optin)
            if status:
                q = q.where("status", "==", status)
            return [d.to_dict() for d in q.stream()]

        return await asyncio.to_thread(_run)

    async def query_lists(
        self,
        search: str,
        list_type: str,
        optin: str,
        status: str,
        tags: list[str],
        permitted_ids: list[int] | None,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = await self._all_rows(list_type, optin, status)
        rows = [r for r in rows if _matches(r, search, tags)]
        if permitted_ids is not None:
            rows = [r for r in rows if r["id"] in permitted_ids]
        for r in rows:
            statuses, total = await self._subscriber_stats(r["id"])
            r["subscriber_statuses"] = statuses
            r["subscriber_count"] = total
        reverse = order.upper() == "DESC"
        rows.sort(key=lambda r: r.get(order_by) if r.get(order_by) is not None else "", reverse=reverse)
        total = len(rows)
        return rows[offset : offset + limit] if limit else rows[offset:], total

    async def get_list(
        self, list_id: int, permitted_ids: list[int] | None = None
    ) -> dict[str, Any] | None:
        import asyncio

        def _run() -> dict[str, Any] | None:
            snap = self._db.collection(self._COLLECTION).document(str(list_id)).get()
            return snap.to_dict() if snap.exists else None

        row = await asyncio.to_thread(_run)
        if not row:
            return None
        if permitted_ids is not None and list_id not in permitted_ids:
            return None
        statuses, total = await self._subscriber_stats(list_id)
        row["subscriber_statuses"] = statuses
        row["subscriber_count"] = total
        return row

    async def get_lists_minimal(self, permitted_ids: list[int] | None) -> list[dict[str, Any]]:
        rows = await self._all_rows("", "", "")
        if permitted_ids is not None:
            rows = [r for r in rows if r["id"] in permitted_ids]
        rows.sort(key=lambda r: r.get("name") or "")
        return rows

    async def get_lists_by_optin(
        self, optin: str, ids: list[int] | None, uuids: list[str] | None
    ) -> list[dict[str, Any]]:
        rows = await self._all_rows("", optin, "")
        if ids is not None:
            rows = [r for r in rows if r["id"] in ids]
        elif uuids is not None:
            rows = [r for r in rows if r["uuid"] in uuids]
        rows.sort(key=lambda r: r.get("name") or "")
        return rows

    async def create_list(
        self, name: str, type_: str, optin: str, status: str, tags: list[str], description: str
    ) -> int:
        import asyncio
        import uuid as uuidlib
        from datetime import datetime, timezone

        list_id = await self._next_id()
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": list_id,
            "uuid": str(uuidlib.uuid4()),
            "name": name,
            "type": type_,
            "optin": optin,
            "status": status,
            "tags": tags,
            "description": description,
            "created_at": now,
            "updated_at": now,
        }

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(str(list_id)).set(doc)

        await asyncio.to_thread(_run)
        return list_id

    async def update_list(
        self,
        list_id: int,
        name: str,
        type_: str,
        optin: str,
        status: str,
        tags: list[str],
        description: str,
    ) -> None:
        import asyncio
        from datetime import datetime, timezone

        def _run() -> None:
            ref = self._db.collection(self._COLLECTION).document(str(list_id))
            cur = ref.get().to_dict() or {}
            update: dict[str, Any] = {
                "tags": tags,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if name:
                update["name"] = name
            if type_:
                update["type"] = type_
            if optin:
                update["optin"] = optin
            if status:
                update["status"] = status
            if description:
                update["description"] = description
            ref.set(update, merge=True)

        await asyncio.to_thread(_run)

        # Campaigns hasn't ported yet (Phase 5) - campaign_lists.list_name is
        # still a Postgres-only denormalized copy. Keep it in sync during the
        # transition, same direction as Phase 3b's temporary Postgres lookup
        # for role list_permissions, just mirrored.
        if name:
            await db.execute(
                "UPDATE campaign_lists SET list_name = $2 WHERE list_id = $1", list_id, name
            )

    async def delete_lists(self, ids: list[int], permitted_ids: list[int] | None) -> None:
        import asyncio

        allowed = ids if permitted_ids is None else [i for i in ids if i in permitted_ids]

        def _run() -> None:
            col = self._db.collection(self._COLLECTION)
            batch = self._db.batch()
            for i in allowed:
                batch.delete(col.document(str(i)))
            if allowed:
                batch.commit()

        await asyncio.to_thread(_run)
