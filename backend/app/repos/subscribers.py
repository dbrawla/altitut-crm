"""Subscriber repository — Postgres (current) and Firestore (migration target).

Scope for this pass: subscriber CRUD, subscriber_lists membership, and the
distributed list-subscriber counters. Deliberately NOT included here (stay
as direct Postgres calls in the router for now, entangled with domains
that aren't ported yet):
- The arbitrary-SQL segmentation queries (query-subscribers and friends) -
  blocked pending a product decision on the Phase 7 filter-builder
  replacement (see the migration plan). PgSubscriberRepo doesn't wrap these
  either; they stay exactly as they were.
- export-subscriber-data / get-subscriber-activity - need campaign_views/
  link_clicks/campaigns, none of which are ported (Phase 5/8).
- unsubscribe-by-campaign - needs campaign_lists/campaigns (Phase 5).

Firestore data model (per the migration plan):
- subscribers/{id} - one doc per subscriber, attribs as a native map.
- subscriber_lists/{subscriberId}_{listId} - top-level collection,
  deterministic ID (free uniqueness), queried by collection-group-style
  .where("subscriber_id", ...) or .where("list_id", ...).
- subscriber_emails/{email_lower} - uniqueness reservation doc, same
  pattern as Users.
- lists/{id}/counter_shards/{0..9} - distributed counters, incremented
  transactionally alongside every membership write. Shard = subscriber_id
  % 10: deterministic (no random-shard read-after-write races) and spreads
  writes across shards for lists with many subscribers. 10 shards is
  already generous for this app's actual scale (a low-traffic CRM, not a
  high-QPS system) - the plan's "~10-20" is a ceiling, not a target.
"""

from __future__ import annotations

from typing import Any, Protocol

from app import db

_NUM_SHARDS = 10


class SubscriberRepo(Protocol):
    async def get_subscriber(
        self, sub_id: int = 0, uuid: str | None = "", email: str = ""
    ) -> dict[str, Any] | None: ...

    async def get_subscribers_by_emails(self, emails: list[str]) -> list[dict[str, Any]]: ...

    async def query_subscribers(
        self,
        list_ids: list[int],
        subscription_status: str,
        search: str,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Structured browse (list/status/search/sort/pagination) - no raw
        SQL. Used by the main Subscribers admin page. The arbitrary-SQL
        segmentation feature is a separate, still-Postgres-only code path in
        the router (blocked pending a product decision, see Phase 7)."""
        ...

    async def get_subscriber_lists(
        self,
        sub_id: int = 0,
        uuid: str = "",
        list_ids: list[int] | None = None,
        list_uuids: list[str] | None = None,
        status: str = "",
        optin: str = "",
    ) -> list[dict[str, Any]]: ...

    async def get_subscriber_lists_lazy(
        self, sub_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]: ...

    async def insert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
    ) -> int: ...

    async def upsert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        sub_status: str,
        update_name_attribs: bool,
        update_sub_status: bool,
    ) -> tuple[str, int] | None: ...

    async def upsert_blocklist_subscriber(
        self, uuid: str, email: str, name: str, attribs: dict[str, Any]
    ) -> None: ...

    async def update_subscriber_with_lists(
        self,
        sub_id: int,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any] | None,
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
        delete_missing: bool,
        permitted_ids: list[int],
        allow_resubscribe: bool,
    ) -> None: ...

    async def delete_subscribers(self, ids: list[int], uuids: list[str]) -> None: ...

    async def blocklist_subscribers(self, ids: list[int]) -> None: ...

    async def add_subscribers_to_lists(
        self, sub_ids: list[int], list_ids: list[int], status: str
    ) -> None: ...

    async def delete_subscriptions(self, sub_ids: list[int], list_ids: list[int]) -> None: ...

    async def confirm_subscription_optin(
        self, sub_uuid: str, list_uuids: list[str], meta: dict[str, Any]
    ) -> None: ...

    async def unsubscribe_subscribers_from_lists(
        self, sub_ids: list[int], list_ids: list[int], list_uuids: list[str]
    ) -> None: ...


class PgSubscriberRepo:
    async def query_subscribers(
        self,
        list_ids: list[int],
        subscription_status: str,
        search: str,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        sql = db.q("query-subscribers").replace("%query%", "TRUE").replace(
            "%order%", f"subscribers.{order_by} {order}"
        )
        rows = await db.fetch(sql, list_ids, subscription_status, search, offset, limit)
        if not list_ids and not search:
            total = await db.fetchval("query-subscribers-count-all", list_ids, subscription_status)
        else:
            count_sql = db.q("query-subscribers-count").replace("%query%", "TRUE")
            total = await db.fetchval(count_sql, list_ids, subscription_status, search)
        return rows, int(total or 0)

    async def get_subscriber(
        self, sub_id: int = 0, uuid: str | None = "", email: str = ""
    ) -> dict[str, Any] | None:
        return await db.fetchrow("get-subscriber", sub_id, uuid or "", email)

    async def get_subscribers_by_emails(self, emails: list[str]) -> list[dict[str, Any]]:
        return await db.fetch("get-subscribers-by-emails", emails)

    async def get_subscriber_lists(
        self,
        sub_id: int = 0,
        uuid: str = "",
        list_ids: list[int] | None = None,
        list_uuids: list[str] | None = None,
        status: str = "",
        optin: str = "",
    ) -> list[dict[str, Any]]:
        # $2 is bound directly against the UUID-typed `uuid` column (`uuid =
        # $2`, no `!= ''` text comparison first, unlike get-subscriber) - so
        # Postgres infers it as uuid-typed and "" fails at bind time; must be
        # NULL when looking up by sub_id instead.
        return await db.fetch(
            "get-subscriber-lists", sub_id, uuid or None, list_ids or [], list_uuids or [], status, optin
        )

    async def get_subscriber_lists_lazy(
        self, sub_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        rows = await db.fetch("get-subscriber-lists-lazy", sub_ids)
        return {r["subscriber_id"]: r["lists"] for r in rows}

    async def insert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
    ) -> int:
        return await db.fetchval(
            "insert-subscriber", uuid, email, name, status, attribs, list_ids, list_uuids, sub_status
        )

    async def upsert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        sub_status: str,
        update_name_attribs: bool,
        update_sub_status: bool,
    ) -> tuple[str, int] | None:
        row = await db.fetchrow(
            "upsert-subscriber",
            uuid, email, name, attribs, list_ids, sub_status, update_name_attribs, update_sub_status,
        )
        return (row["uuid"], row["id"]) if row else None

    async def upsert_blocklist_subscriber(
        self, uuid: str, email: str, name: str, attribs: dict[str, Any]
    ) -> None:
        await db.execute("upsert-blocklist-subscriber", uuid, email, name, attribs)

    async def update_subscriber_with_lists(
        self,
        sub_id: int,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any] | None,
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
        delete_missing: bool,
        permitted_ids: list[int],
        allow_resubscribe: bool,
    ) -> None:
        import orjson

        # $5 is compared against '' before its ::JSONB cast (`WHEN $5 != ''`),
        # which forces Postgres to type the parameter as text, not jsonb - so
        # it must be a JSON string, not a raw dict (unlike insert/upsert's
        # attribs param, which asyncpg's jsonb codec handles as a dict fine
        # since there's no competing text inference there).
        attribs_arg = orjson.dumps(attribs).decode() if attribs is not None else ""
        await db.execute(
            "update-subscriber-with-lists",
            sub_id, email, name, status, attribs_arg,
            list_ids, list_uuids, sub_status, delete_missing, permitted_ids, allow_resubscribe,
        )

    async def delete_subscribers(self, ids: list[int], uuids: list[str]) -> None:
        await db.execute("delete-subscribers", ids, uuids)

    async def blocklist_subscribers(self, ids: list[int]) -> None:
        await db.execute("blocklist-subscribers", ids)

    async def add_subscribers_to_lists(
        self, sub_ids: list[int], list_ids: list[int], status: str
    ) -> None:
        await db.execute("add-subscribers-to-lists", sub_ids, list_ids, status)

    async def delete_subscriptions(self, sub_ids: list[int], list_ids: list[int]) -> None:
        await db.execute("delete-subscriptions", sub_ids, list_ids)

    async def confirm_subscription_optin(
        self, sub_uuid: str, list_uuids: list[str], meta: dict[str, Any]
    ) -> None:
        await db.execute("confirm-subscription-optin", sub_uuid, list_uuids, meta)

    async def unsubscribe_subscribers_from_lists(
        self, sub_ids: list[int], list_ids: list[int], list_uuids: list[str]
    ) -> None:
        await db.execute("unsubscribe-subscribers-from-lists", sub_ids, list_ids, list_uuids)


def _shard_id(subscriber_id: int) -> str:
    return str(subscriber_id % _NUM_SHARDS)


class FirestoreSubscriberRepo:
    _COLLECTION = "subscribers"
    _MEMBERSHIP_COLLECTION = "subscriber_lists"
    _EMAIL_COLLECTION = "subscriber_emails"
    _COUNTER_DOC = "counters/subscribers"

    def __init__(self) -> None:
        from app.firestore_client import client

        self._db = client()

    # -- helpers --------------------------------------------------------

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

    def _adjust_shard(
        self, transaction: Any, list_id: int, subscriber_id: int, old_status: str | None, new_status: str | None
    ) -> None:
        """Increments/decrements the counter shard for one list. Call inside
        an active transaction alongside the membership doc write."""
        from firebase_admin.firestore import Increment

        if old_status == new_status:
            return
        shard_ref = (
            self._db.collection("lists")
            .document(str(list_id))
            .collection("counter_shards")
            .document(_shard_id(subscriber_id))
        )
        update: dict[str, Any] = {}
        if old_status:
            update[old_status] = Increment(-1)
        if new_status:
            update[new_status] = Increment(1)
        if update:
            transaction.set(shard_ref, update, merge=True)

    async def _resolve_list_ids(
        self, list_ids: list[int], list_uuids: list[str]
    ) -> list[int]:
        if list_ids:
            return list_ids
        if not list_uuids:
            return []
        from app.repos import list_repo  # deferred: avoids a circular import at module load

        rows = await list_repo.get_lists_by_optin("", None, list_uuids)
        return [r["id"] for r in rows]

    async def get_subscriber(
        self, sub_id: int = 0, uuid: str | None = "", email: str = ""
    ) -> dict[str, Any] | None:
        import asyncio

        def _run() -> dict[str, Any] | None:
            col = self._db.collection(self._COLLECTION)
            if sub_id:
                snap = col.document(str(sub_id)).get()
                return snap.to_dict() if snap.exists else None
            if uuid:
                docs = list(col.where("uuid", "==", uuid).limit(1).stream())
                return docs[0].to_dict() if docs else None
            if email:
                docs = list(col.where("email", "==", email).limit(1).stream())
                return docs[0].to_dict() if docs else None
            return None

        return await asyncio.to_thread(_run)

    async def query_subscribers(
        self,
        list_ids: list[int],
        subscription_status: str,
        search: str,
        order_by: str,
        order: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        import asyncio

        # Matches the original SQL's own quirk (preserved for behavior
        # parity): with no list filter, the LEFT JOIN predicate against
        # subscriber_lists never matches, so a status filter alone (no list
        # filter) yields zero rows rather than "any subscriber with that
        # status on any list".
        if not list_ids and subscription_status:
            return [], 0

        def _run() -> list[dict[str, Any]]:
            sub_col = self._db.collection(self._COLLECTION)
            if list_ids:
                member_ids: set[int] = set()
                for list_id in list_ids:
                    q = self._db.collection(self._MEMBERSHIP_COLLECTION).where(
                        "list_id", "==", list_id
                    )
                    if subscription_status:
                        q = q.where("status", "==", subscription_status)
                    member_ids.update(d.to_dict()["subscriber_id"] for d in q.stream())
                rows = []
                for i in range(0, len(list(member_ids)), 30):
                    chunk = list(member_ids)[i : i + 30]
                    if not chunk:
                        continue
                    rows.extend(
                        d.to_dict()
                        for d in sub_col.where("id", "in", chunk).stream()
                    )
            else:
                rows = [d.to_dict() for d in sub_col.stream()]
            return rows

        rows = await asyncio.to_thread(_run)
        if search:
            needle = search.lower()
            rows = [
                r
                for r in rows
                if needle in (r.get("name") or "").lower() or needle in (r.get("email") or "").lower()
            ]
        reverse = order.upper() == "DESC"
        rows.sort(key=lambda r: r.get(order_by) if r.get(order_by) is not None else "", reverse=reverse)
        total = len(rows)
        return (rows[offset : offset + limit] if limit else rows[offset:]), total

    async def get_subscribers_by_emails(self, emails: list[str]) -> list[dict[str, Any]]:
        import asyncio

        if not emails:
            return []

        def _run() -> list[dict[str, Any]]:
            col = self._db.collection(self._COLLECTION)
            out: list[dict[str, Any]] = []
            # Firestore 'in' queries cap at 30 values per query.
            for i in range(0, len(emails), 30):
                chunk = emails[i : i + 30]
                out.extend(d.to_dict() for d in col.where("email", "in", chunk).stream())
            return out

        return await asyncio.to_thread(_run)

    async def _memberships_for_subscriber(
        self, sub_id: int, status: str = ""
    ) -> list[dict[str, Any]]:
        import asyncio

        def _run() -> list[dict[str, Any]]:
            q = self._db.collection(self._MEMBERSHIP_COLLECTION).where("subscriber_id", "==", sub_id)
            if status:
                q = q.where("status", "==", status)
            return [d.to_dict() for d in q.stream()]

        return await asyncio.to_thread(_run)

    async def get_subscriber_lists(
        self,
        sub_id: int = 0,
        uuid: str = "",
        list_ids: list[int] | None = None,
        list_uuids: list[str] | None = None,
        status: str = "",
        optin: str = "",
    ) -> list[dict[str, Any]]:
        from app.repos import list_repo  # deferred: avoids a circular import at module load

        sub = await self.get_subscriber(sub_id, uuid)
        if not sub:
            return []
        memberships = await self._memberships_for_subscriber(sub["id"], status)
        if list_ids:
            memberships = [m for m in memberships if m["list_id"] in list_ids]

        all_lists = {r["id"]: r for r in await list_repo.get_lists_minimal(None)}
        out = []
        for m in memberships:
            list_row = all_lists.get(m["list_id"])
            if not list_row:
                continue
            if list_uuids and list_row["uuid"] not in list_uuids:
                continue
            if optin and list_row.get("optin") != optin:
                continue
            row = dict(list_row)
            row["status"] = m["status"]
            row["meta"] = m.get("meta") or {}
            out.append(row)
        out.sort(key=lambda r: r["id"])
        return out

    async def get_subscriber_lists_lazy(
        self, sub_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        import asyncio

        from app.repos import list_repo  # deferred: avoids a circular import at module load

        if not sub_ids:
            return {}

        def _run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for i in range(0, len(sub_ids), 30):
                chunk = sub_ids[i : i + 30]
                q = self._db.collection(self._MEMBERSHIP_COLLECTION).where(
                    "subscriber_id", "in", chunk
                )
                out.extend(d.to_dict() for d in q.stream())
            return out

        memberships = await asyncio.to_thread(_run)
        all_lists = {r["id"]: r for r in await list_repo.get_lists_minimal(None)}
        by_sub: dict[int, list[dict[str, Any]]] = {sid: [] for sid in sub_ids}
        for m in memberships:
            list_row = all_lists.get(m["list_id"])
            if not list_row:
                continue
            row = dict(list_row)
            row["subscription_status"] = m["status"]
            row["subscription_created_at"] = m.get("created_at")
            row["subscription_updated_at"] = m.get("updated_at")
            row["subscription_meta"] = m.get("meta") or {}
            by_sub.setdefault(m["subscriber_id"], []).append(row)
        return by_sub

    async def insert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
    ) -> int:
        import asyncio
        from datetime import datetime, timezone

        from firebase_admin.firestore import transactional

        email_lower = email.strip().lower()
        sub_id = await self._next_id()
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": sub_id,
            "uuid": uuid,
            "email": email,
            "name": name,
            "status": status,
            "attribs": attribs,
            "created_at": now,
            "updated_at": now,
        }
        sub_ref = self._db.collection(self._COLLECTION).document(str(sub_id))
        email_ref = self._db.collection(self._EMAIL_COLLECTION).document(email_lower)

        @transactional
        def _txn(transaction: Any) -> None:
            if email_ref.get(transaction=transaction).exists:
                raise ValueError(f"duplicate email: {email}")
            transaction.set(sub_ref, doc)
            transaction.set(email_ref, {"subscriber_id": sub_id})

        await asyncio.to_thread(_txn, self._db.transaction())

        resolved_list_ids = await self._resolve_list_ids(list_ids, list_uuids)
        member_status = "unsubscribed" if status == "blocklisted" else sub_status
        for list_id in resolved_list_ids:
            await self._set_membership(sub_id, list_id, member_status, {})
        return sub_id

    async def _set_membership(
        self, sub_id: int, list_id: int, new_status: str, meta: dict[str, Any]
    ) -> None:
        """Creates or updates one membership doc, adjusting the list's
        counter shard in the same transaction."""
        import asyncio
        from datetime import datetime, timezone

        from firebase_admin.firestore import transactional

        ref = self._db.collection(self._MEMBERSHIP_COLLECTION).document(f"{sub_id}_{list_id}")
        now = datetime.now(timezone.utc).isoformat()

        @transactional
        def _txn(transaction: Any) -> None:
            snap = ref.get(transaction=transaction)
            old_status = (snap.to_dict() or {}).get("status") if snap.exists else None
            doc = {
                "subscriber_id": sub_id,
                "list_id": list_id,
                "status": new_status,
                "meta": meta,
                "updated_at": now,
                "created_at": (snap.to_dict() or {}).get("created_at", now) if snap.exists else now,
            }
            transaction.set(ref, doc)
            self._adjust_shard(transaction, list_id, sub_id, old_status, new_status)

        await asyncio.to_thread(_txn, self._db.transaction())

    async def upsert_subscriber(
        self,
        uuid: str,
        email: str,
        name: str,
        attribs: dict[str, Any],
        list_ids: list[int],
        sub_status: str,
        update_name_attribs: bool,
        update_sub_status: bool,
    ) -> tuple[str, int] | None:
        import asyncio
        from datetime import datetime, timezone

        from firebase_admin.firestore import transactional

        email_lower = email.strip().lower()
        now = datetime.now(timezone.utc).isoformat()
        sub_col = self._db.collection(self._COLLECTION)
        email_ref = self._db.collection(self._EMAIL_COLLECTION).document(email_lower)

        new_id_holder: dict[str, int] = {}

        @transactional
        def _txn(transaction: Any) -> tuple[str, int, str]:
            reservation = email_ref.get(transaction=transaction)
            if reservation.exists:
                existing_id = reservation.to_dict()["subscriber_id"]
                ref = sub_col.document(str(existing_id))
                cur = ref.get(transaction=transaction).to_dict() or {}
                update: dict[str, Any] = {"updated_at": now}
                if update_name_attribs:
                    update["name"] = name
                    update["attribs"] = attribs
                transaction.set(ref, update, merge=True)
                return cur.get("uuid", uuid), existing_id, cur.get("status", "enabled")
            new_id = new_id_holder["id"]
            ref = sub_col.document(str(new_id))
            doc = {
                "id": new_id,
                "uuid": uuid,
                "email": email,
                "name": name,
                "attribs": attribs,
                "status": "enabled",
                "created_at": now,
                "updated_at": now,
            }
            transaction.set(ref, doc)
            transaction.set(email_ref, {"subscriber_id": new_id})
            return uuid, new_id, "enabled"

        # The transactional retry callback must be side-effect-free re: ID
        # allocation, so the counter is claimed once, up front, outside it -
        # a retry (on contention) would otherwise burn extra IDs. Cheap to
        # waste one on the rare retry; not cheap to make _next_id itself
        # transactional-safe to call from inside another transaction.
        new_id_holder["id"] = await self._next_id()
        result_uuid, sub_id, sub_status_cur = await asyncio.to_thread(_txn, self._db.transaction())

        member_status = "unsubscribed" if sub_status_cur == "blocklisted" else sub_status
        for list_id in list_ids:
            if update_sub_status:
                await self._set_membership(sub_id, list_id, member_status, {})
            else:
                member_ref = self._db.collection(self._MEMBERSHIP_COLLECTION).document(
                    f"{sub_id}_{list_id}"
                )
                existing = await asyncio.to_thread(member_ref.get)
                if existing.exists:
                    continue  # status update suppressed; leave as-is (touch not required)
                await self._set_membership(sub_id, list_id, member_status, {})

        return result_uuid, sub_id

    async def upsert_blocklist_subscriber(
        self, uuid: str, email: str, name: str, attribs: dict[str, Any]
    ) -> None:
        import asyncio
        from datetime import datetime, timezone

        from firebase_admin.firestore import transactional

        email_lower = email.strip().lower()
        now = datetime.now(timezone.utc).isoformat()
        sub_col = self._db.collection(self._COLLECTION)
        email_ref = self._db.collection(self._EMAIL_COLLECTION).document(email_lower)
        new_id = await self._next_id()

        @transactional
        def _txn(transaction: Any) -> int:
            reservation = email_ref.get(transaction=transaction)
            if reservation.exists:
                existing_id = reservation.to_dict()["subscriber_id"]
                ref = sub_col.document(str(existing_id))
                transaction.set(ref, {"status": "blocklisted", "updated_at": now}, merge=True)
                return existing_id
            ref = sub_col.document(str(new_id))
            transaction.set(
                ref,
                {
                    "id": new_id, "uuid": uuid, "email": email, "name": name,
                    "attribs": attribs, "status": "blocklisted",
                    "created_at": now, "updated_at": now,
                },
            )
            transaction.set(email_ref, {"subscriber_id": new_id})
            return new_id

        sub_id = await asyncio.to_thread(_txn, self._db.transaction())
        for m in await self._memberships_for_subscriber(sub_id):
            if m["status"] != "unsubscribed":
                await self._set_membership(sub_id, m["list_id"], "unsubscribed", m.get("meta") or {})

    async def update_subscriber_with_lists(
        self,
        sub_id: int,
        email: str,
        name: str,
        status: str,
        attribs: dict[str, Any] | None,
        list_ids: list[int],
        list_uuids: list[str],
        sub_status: str,
        delete_missing: bool,
        permitted_ids: list[int],
        allow_resubscribe: bool,
    ) -> None:
        import asyncio
        from datetime import datetime, timezone

        from firebase_admin.firestore import transactional

        ref = self._db.collection(self._COLLECTION).document(str(sub_id))
        email_lower = email.strip().lower() if email else ""
        now = datetime.now(timezone.utc).isoformat()

        @transactional
        def _txn(transaction: Any) -> None:
            cur = ref.get(transaction=transaction).to_dict() or {}
            update: dict[str, Any] = {"updated_at": now}
            old_email_lower = (cur.get("email") or "").strip().lower()
            if email and email_lower != old_email_lower:
                new_email_ref = self._db.collection(self._EMAIL_COLLECTION).document(email_lower)
                if new_email_ref.get(transaction=transaction).exists:
                    raise ValueError(f"duplicate email: {email}")
                update["email"] = email
                transaction.set(new_email_ref, {"subscriber_id": sub_id})
                if old_email_lower:
                    transaction.delete(
                        self._db.collection(self._EMAIL_COLLECTION).document(old_email_lower)
                    )
            if name:
                update["name"] = name
            if status:
                update["status"] = status
            if attribs is not None:
                update["attribs"] = attribs
            transaction.set(ref, update, merge=True)

        await asyncio.to_thread(_txn, self._db.transaction())

        resolved_list_ids = set(await self._resolve_list_ids(list_ids, list_uuids))
        effective_status = status or (await self.get_subscriber(sub_id) or {}).get("status", "")
        new_member_status = "unsubscribed" if effective_status == "blocklisted" else sub_status

        existing = {m["list_id"]: m for m in await self._memberships_for_subscriber(sub_id)}

        if delete_missing:
            scope = set(permitted_ids) if permitted_ids else None
            for list_id, m in list(existing.items()):
                if list_id in resolved_list_ids:
                    continue
                if scope is not None and list_id not in scope:
                    continue
                await self._delete_membership(sub_id, list_id, m["status"])
                del existing[list_id]

        for list_id in resolved_list_ids:
            m = existing.get(list_id)
            if m is None:
                await self._set_membership(sub_id, list_id, new_member_status, {})
                continue
            cur_status = m["status"]
            if effective_status == "blocklisted":
                final_status = "unsubscribed"
            elif cur_status == "confirmed":
                final_status = "confirmed"
            elif allow_resubscribe:
                final_status = sub_status
            elif cur_status == "unsubscribed":
                final_status = "unsubscribed"
            else:
                final_status = sub_status
            if final_status != cur_status:
                await self._set_membership(sub_id, list_id, final_status, m.get("meta") or {})

    async def _delete_membership(self, sub_id: int, list_id: int, old_status: str) -> None:
        import asyncio

        from firebase_admin.firestore import transactional

        ref = self._db.collection(self._MEMBERSHIP_COLLECTION).document(f"{sub_id}_{list_id}")

        @transactional
        def _txn(transaction: Any) -> None:
            transaction.delete(ref)
            self._adjust_shard(transaction, list_id, sub_id, old_status, None)

        await asyncio.to_thread(_txn, self._db.transaction())

    async def delete_subscribers(self, ids: list[int], uuids: list[str]) -> None:
        import asyncio

        target_ids = list(ids)
        if not target_ids and uuids:
            def _run_lookup() -> list[int]:
                col = self._db.collection(self._COLLECTION)
                out = []
                for i in range(0, len(uuids), 30):
                    chunk = uuids[i : i + 30]
                    out.extend(d.to_dict()["id"] for d in col.where("uuid", "in", chunk).stream())
                return out

            target_ids = await asyncio.to_thread(_run_lookup)

        for sub_id in target_ids:
            for m in await self._memberships_for_subscriber(sub_id):
                await self._delete_membership(sub_id, m["list_id"], m["status"])

        def _run_delete() -> None:
            col = self._db.collection(self._COLLECTION)
            batch = self._db.batch()
            for sub_id in target_ids:
                snap = col.document(str(sub_id)).get()
                if snap.exists:
                    email = (snap.to_dict() or {}).get("email", "").strip().lower()
                    if email:
                        batch.delete(self._db.collection(self._EMAIL_COLLECTION).document(email))
                    batch.delete(snap.reference)
            if target_ids:
                batch.commit()

        await asyncio.to_thread(_run_delete)

    async def blocklist_subscribers(self, ids: list[int]) -> None:
        import asyncio
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        def _run() -> None:
            col = self._db.collection(self._COLLECTION)
            batch = self._db.batch()
            for sub_id in ids:
                batch.set(col.document(str(sub_id)), {"status": "blocklisted", "updated_at": now}, merge=True)
            if ids:
                batch.commit()

        await asyncio.to_thread(_run)

        for sub_id in ids:
            for m in await self._memberships_for_subscriber(sub_id):
                if m["status"] != "unsubscribed":
                    await self._set_membership(sub_id, m["list_id"], "unsubscribed", m.get("meta") or {})

    async def add_subscribers_to_lists(
        self, sub_ids: list[int], list_ids: list[int], status: str
    ) -> None:
        for sub_id in sub_ids:
            existing = {m["list_id"]: m for m in await self._memberships_for_subscriber(sub_id)}
            for list_id in list_ids:
                m = existing.get(list_id)
                new_status = status if status else (m["status"] if m else "unconfirmed")
                await self._set_membership(sub_id, list_id, new_status, (m or {}).get("meta") or {})

    async def delete_subscriptions(self, sub_ids: list[int], list_ids: list[int]) -> None:
        for sub_id in sub_ids:
            existing = {m["list_id"]: m for m in await self._memberships_for_subscriber(sub_id)}
            for list_id in list_ids:
                m = existing.get(list_id)
                if m:
                    await self._delete_membership(sub_id, list_id, m["status"])

    async def confirm_subscription_optin(
        self, sub_uuid: str, list_uuids: list[str], meta: dict[str, Any]
    ) -> None:
        from app.repos import list_repo  # deferred: avoids a circular import at module load

        sub = await self.get_subscriber(uuid=sub_uuid)
        if not sub:
            return
        rows = await list_repo.get_lists_by_optin("", None, list_uuids)
        existing = {m["list_id"]: m for m in await self._memberships_for_subscriber(sub["id"])}
        for row in rows:
            m = existing.get(row["id"])
            if not m:
                continue
            merged_meta = {**(m.get("meta") or {}), **meta}
            await self._set_membership(sub["id"], row["id"], "confirmed", merged_meta)

    async def unsubscribe_subscribers_from_lists(
        self, sub_ids: list[int], list_ids: list[int], list_uuids: list[str]
    ) -> None:
        resolved = await self._resolve_list_ids(list_ids, list_uuids)
        for sub_id in sub_ids:
            existing = {m["list_id"]: m for m in await self._memberships_for_subscriber(sub_id)}
            for list_id in resolved:
                m = existing.get(list_id)
                if m and m["status"] != "unsubscribed":
                    await self._set_membership(sub_id, list_id, "unsubscribed", m.get("meta") or {})
