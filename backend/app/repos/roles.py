"""Roles repository — Postgres (current) and Firestore (migration target).

The `roles` table is a shallow self-referencing tree: top-level rows
(parent_id IS NULL) are "user roles" or "list roles"; child rows
(parent_id = <top-level id>) hold per-list permission grants for a list
role, each with a list_id + permissions.

Cross-domain wrinkle: role IDs are plain integers referenced by
users.user_role_id/list_role_id (auth.SUPER_ADMIN_ROLE_ID = 1 is hardcoded),
and Users stays Postgres-backed until Phase 3c - those queries read the
`roles` table directly via SQL, not through this repo, so they're
unaffected by which backend this repo uses. Also, list_permissions needs
each list's *name*, but Lists isn't ported until Phase 4 - so
FirestoreRoleRepo looks list names up from Postgres directly for now. Swap
that lookup to wherever Lists lives once Phase 4 lands.
"""

from __future__ import annotations

from typing import Any, Protocol

from app import db


class RoleRepo(Protocol):
    async def get_roles(self, role_type: str, role_id: int = 0) -> list[dict[str, Any]]:
        """Top-level roles of role_type ('user'|'list'), each with a
        list_permissions array aggregated from child rows. role_id=0 means all."""
        ...

    async def create_role(
        self, name: str, role_type: str, permissions: list[str]
    ) -> dict[str, Any]: ...

    async def update_role(
        self, role_id: int, name: str, permissions: list[str]
    ) -> dict[str, Any] | None: ...

    async def delete_role(self, role_id: int) -> None: ...

    async def upsert_list_permissions(
        self, role_id: int, list_ids: list[int], perms: list[list[str]]
    ) -> None: ...


class PgRoleRepo:
    async def get_roles(self, role_type: str, role_id: int = 0) -> list[dict[str, Any]]:
        name = "get-user-roles" if role_type == "user" else "get-list-roles"
        args = (role_id,) if role_type == "user" else ()
        return await db.fetch(name, *args)

    async def create_role(
        self, name: str, role_type: str, permissions: list[str]
    ) -> dict[str, Any]:
        row = await db.fetchrow("create-role", name, role_type, permissions)
        assert row
        return row

    async def update_role(
        self, role_id: int, name: str, permissions: list[str]
    ) -> dict[str, Any] | None:
        return await db.fetchrow("update-role", role_id, name, permissions)

    async def delete_role(self, role_id: int) -> None:
        await db.execute("delete-role", role_id)

    async def upsert_list_permissions(
        self, role_id: int, list_ids: list[int], perms: list[list[str]]
    ) -> None:
        await db.execute("upsert-list-permissions", role_id, list_ids, perms)


class FirestoreRoleRepo:
    _COLLECTION = "roles"
    _COUNTER_DOC = "counters/roles"

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

    async def _list_names(self, list_ids: list[int]) -> dict[int, str]:
        """List names for list_permissions, via app.repos.list_repo (Phase 4a) -
        composes the two already-migrated domains regardless of which backend
        either is on, same pattern as Phase 3c's role/user composition."""
        if not list_ids:
            return {}
        from app.repos import list_repo  # deferred: avoids a circular import at module load

        rows = await list_repo.get_lists_minimal(permitted_ids=list_ids)
        return {r["id"]: r["name"] for r in rows}

    async def get_roles(self, role_type: str, role_id: int = 0) -> list[dict[str, Any]]:
        import asyncio

        def _run() -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
            col = self._db.collection(self._COLLECTION)
            q = col.where("type", "==", role_type).where("parent_id", "==", None)
            top = [d.to_dict() for d in q.stream()]
            if role_id:
                top = [r for r in top if r.get("id") == role_id]
            top.sort(key=lambda r: r.get("created_at") or "")

            children_by_parent: dict[int, list[dict[str, Any]]] = {}
            for parent in top:
                kids = [
                    d.to_dict()
                    for d in col.where("parent_id", "==", parent["id"]).stream()
                ]
                if kids:
                    children_by_parent[parent["id"]] = kids
            return top, children_by_parent

        top, children_by_parent = await asyncio.to_thread(_run)

        all_list_ids = [
            kid["list_id"] for kids in children_by_parent.values() for kid in kids
        ]
        names = await self._list_names(all_list_ids)

        out = []
        for parent in top:
            kids = children_by_parent.get(parent["id"], [])
            parent = dict(parent)
            parent["list_permissions"] = [
                {
                    "id": kid["list_id"],
                    "name": names.get(kid["list_id"]),
                    "permissions": kid["permissions"],
                }
                for kid in kids
            ]
            out.append(parent)
        return out

    async def create_role(
        self, name: str, role_type: str, permissions: list[str]
    ) -> dict[str, Any]:
        import asyncio
        from datetime import datetime, timezone

        role_id = await self._next_id()
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": role_id,
            "name": name,
            "type": role_type,
            "parent_id": None,
            "list_id": None,
            "permissions": permissions,
            "created_at": now,
            "updated_at": now,
        }

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(str(role_id)).set(doc)

        await asyncio.to_thread(_run)
        return doc

    async def update_role(
        self, role_id: int, name: str, permissions: list[str]
    ) -> dict[str, Any] | None:
        import asyncio
        from datetime import datetime, timezone

        def _run() -> dict[str, Any] | None:
            ref = self._db.collection(self._COLLECTION).document(str(role_id))
            snap = ref.get()
            if not snap.exists or (snap.to_dict() or {}).get("parent_id") is not None:
                return None
            update = {
                "name": name,
                "permissions": permissions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            ref.set(update, merge=True)
            return {**snap.to_dict(), **update}

        return await asyncio.to_thread(_run)

    async def delete_role(self, role_id: int) -> None:
        import asyncio

        def _run() -> None:
            col = self._db.collection(self._COLLECTION)
            batch = self._db.batch()
            batch.delete(col.document(str(role_id)))
            for kid in col.where("parent_id", "==", role_id).stream():
                batch.delete(kid.reference)
            batch.commit()

        await asyncio.to_thread(_run)

    async def upsert_list_permissions(
        self, role_id: int, list_ids: list[int], perms: list[list[str]]
    ) -> None:
        import asyncio

        def _run() -> None:
            col = self._db.collection(self._COLLECTION)
            existing = {
                d.to_dict()["list_id"]: d.reference
                for d in col.where("parent_id", "==", role_id).stream()
            }
            batch = self._db.batch()
            keep = set(list_ids)
            for list_id, ref in existing.items():
                if list_id not in keep:
                    batch.delete(ref)
            for list_id, p in zip(list_ids, perms, strict=True):
                clean_perms = [x for x in p if x]
                ref = existing.get(list_id) or col.document(
                    f"{role_id}_{list_id}_child"
                )
                batch.set(
                    ref,
                    {
                        "parent_id": role_id,
                        "list_id": list_id,
                        "type": "list",
                        "permissions": clean_perms,
                    },
                )
            batch.commit()

        await asyncio.to_thread(_run)
