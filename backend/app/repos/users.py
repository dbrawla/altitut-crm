"""User repository — Postgres (current) and Firestore (migration target).

Role info (user_role_name/permissions, list_role_name/perms) used to come
from a same-database SQL JOIN against `roles`. Since Roles may now live in
Firestore (Phase 3b) while Users can be on either backend independently,
role resolution goes through app.repos.role_repo instead - this is exactly
what the Phase 0 abstraction layer was for: composing already-migrated
domains without re-coupling them to one database.

Same story for the "don't demote/disable/delete the last enabled
superadmin" guards: they used to be a same-database SQL subquery, now
implemented in Python so they work correctly regardless of backend.

Email uniqueness (Firestore only): a reservation document
`user_emails/{email_lower}` -> {user_id}, written in the same transaction
as the user doc - Firestore's transactional conflict behavior gives the
same guarantee Postgres's UNIQUE(email) index did.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, Protocol

from app import db
from app.repos._util import doc_dict


class UserRepo(Protocol):
    async def get_users(self) -> list[dict[str, Any]]: ...

    async def get_user(
        self, user_id: int = 0, username: str = "", email: str = ""
    ) -> dict[str, Any] | None: ...

    async def get_user_for_login(self, username: str) -> dict[str, Any] | None: ...

    async def get_api_tokens(self) -> list[dict[str, Any]]: ...

    async def create_user(self, fields: dict[str, Any]) -> int: ...

    async def update_user(self, user_id: int, fields: dict[str, Any]) -> bool:
        """Returns False if the last-superadmin guard blocked the edit."""
        ...

    async def delete_users(self, ids: list[int]) -> bool:
        """Returns False if the last-superadmin guard blocked the delete."""
        ...

    async def update_user_profile(
        self, user_id: int, name: str, email: str, password_login: bool, password: str
    ) -> None: ...

    async def update_user_login(self, user_id: int, avatar: str) -> None: ...

    async def set_user_twofa(
        self, user_id: int, twofa_type: str, twofa_key: str | None
    ) -> None: ...


async def _attach_role_info(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flattens role name/permissions onto each user row, matching the
    field names auth.py's _shape_user() expects."""
    from app.repos import role_repo  # deferred: avoids a circular import at module load

    user_roles = {r["id"]: r for r in await role_repo.get_roles("user")}
    list_roles = {r["id"]: r for r in await role_repo.get_roles("list")}
    for u in rows:
        ur = user_roles.get(u.get("user_role_id"))
        u["user_role_name"] = ur["name"] if ur else None
        u["user_role_permissions"] = ur["permissions"] if ur else []
        lr = list_roles.get(u["list_role_id"]) if u.get("list_role_id") else None
        u["list_role_name"] = lr["name"] if lr else None
        u["list_role_perms"] = lr["list_permissions"] if lr else None
    return rows


class PgUserRepo:
    async def get_users(self) -> list[dict[str, Any]]:
        rows = await db.fetch("get-users")
        return await _attach_role_info(rows)

    async def get_user(
        self, user_id: int = 0, username: str = "", email: str = ""
    ) -> dict[str, Any] | None:
        row = await db.fetchrow("get-user", user_id, username, email)
        if not row:
            return None
        return (await _attach_role_info([row]))[0]

    async def get_user_for_login(self, username: str) -> dict[str, Any] | None:
        return await db.fetchrow("get-user-for-login", username)

    async def get_api_tokens(self) -> list[dict[str, Any]]:
        return await db.fetch("get-api-tokens")

    async def _count_other_enabled_superadmins(self, exclude_ids: list[int]) -> int:
        value = await db.fetchval("count-other-enabled-superadmins", exclude_ids)
        return int(value)

    async def create_user(self, fields: dict[str, Any]) -> int:
        value = await db.fetchval(
            "create-user",
            fields["username"],
            fields["password_login"],
            fields["password"],
            fields["email"],
            fields["name"],
            fields["type"],
            fields["user_role_id"],
            fields["list_role_id"],
            fields["status"],
        )
        return int(value)

    async def update_user(self, user_id: int, fields: dict[str, Any]) -> bool:
        demoting = fields.get("user_role_id", 0) != 1 or fields.get("status", "") != "enabled"
        if demoting and await self._count_other_enabled_superadmins([user_id]) == 0:
            return False
        await db.execute(
            "update-user",
            user_id,
            fields["username"],
            fields["password_login"],
            fields["password"],
            fields["email"],
            fields["name"],
            fields["type"],
            fields["user_role_id"],
            fields["list_role_id"],
            fields["status"],
        )
        return True

    async def delete_users(self, ids: list[int]) -> bool:
        if await self._count_other_enabled_superadmins(ids) == 0:
            return False
        await db.execute("delete-users", ids)
        return True

    async def update_user_profile(
        self, user_id: int, name: str, email: str, password_login: bool, password: str
    ) -> None:
        await db.execute("update-user-profile", user_id, name, email, password_login, password)

    async def update_user_login(self, user_id: int, avatar: str) -> None:
        await db.execute("update-user-login", user_id, avatar)

    async def set_user_twofa(self, user_id: int, twofa_type: str, twofa_key: str | None) -> None:
        await db.execute("set-user-twofa", user_id, twofa_type, twofa_key)


class FirestoreUserRepo:
    _COLLECTION = "users"
    _EMAIL_COLLECTION = "user_emails"
    _COUNTER_DOC = "counters/users"

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

    async def get_users(self) -> list[dict[str, Any]]:
        import asyncio

        def _run() -> list[dict[str, Any]]:
            rows = [doc_dict(d) for d in self._db.collection(self._COLLECTION).stream()]
            rows.sort(key=lambda r: r.get("created_at") or "")
            return rows

        rows = await asyncio.to_thread(_run)
        return await _attach_role_info(rows)

    async def get_user(
        self, user_id: int = 0, username: str = "", email: str = ""
    ) -> dict[str, Any] | None:
        import asyncio

        def _run() -> dict[str, Any] | None:
            col = self._db.collection(self._COLLECTION)
            if user_id:
                snap = col.document(str(user_id)).get()
                return snap.to_dict() if snap.exists else None
            field, value = ("username", username) if username else ("email", email)
            docs = list(col.where(field, "==", value).limit(1).stream())
            return docs[0].to_dict() if docs else None

        row = await asyncio.to_thread(_run)
        if not row:
            return None
        return (await _attach_role_info([row]))[0]

    async def get_user_for_login(self, username: str) -> dict[str, Any] | None:
        import asyncio

        def _run() -> dict[str, Any] | None:
            docs = list(
                self._db.collection(self._COLLECTION)
                .where("username", "==", username)
                .where("password_login", "==", True)
                .limit(1)
                .stream()
            )
            if not docs:
                return None
            row = doc_dict(docs[0])
            return None if row.get("status") == "disabled" else row

        return await asyncio.to_thread(_run)

    async def get_api_tokens(self) -> list[dict[str, Any]]:
        import asyncio

        def _run() -> list[dict[str, Any]]:
            docs = (
                self._db.collection(self._COLLECTION)
                .where("status", "==", "enabled")
                .where("type", "==", "api")
                .stream()
            )
            return [
                {"username": doc_dict(d)["username"], "password": doc_dict(d).get("password")}
                for d in docs
            ]

        return await asyncio.to_thread(_run)

    async def _count_other_enabled_superadmins(self, exclude_ids: list[int]) -> int:
        import asyncio

        def _run() -> int:
            docs = (
                self._db.collection(self._COLLECTION)
                .where("user_role_id", "==", 1)
                .where("type", "==", "user")
                .where("status", "==", "enabled")
                .stream()
            )
            return sum(1 for d in docs if doc_dict(d)["id"] not in exclude_ids)

        return await asyncio.to_thread(_run)

    async def create_user(self, fields: dict[str, Any]) -> int:
        import asyncio
        from datetime import datetime

        from firebase_admin.firestore import transactional

        email_lower = fields["email"].strip().lower()
        user_id = await self._next_id()
        now = datetime.now(UTC).isoformat()
        doc = {
            "id": user_id,
            "username": fields["username"],
            "password_login": fields["password_login"],
            "password": fields["password"] or None,
            "email": fields["email"],
            "name": fields["name"],
            "type": fields["type"],
            "user_role_id": fields["user_role_id"],
            "list_role_id": fields["list_role_id"],
            "status": fields["status"],
            "avatar": None,
            "twofa_type": "none",
            "twofa_key": None,
            "loggedin_at": None,
            "created_at": now,
            "updated_at": now,
        }
        user_ref = self._db.collection(self._COLLECTION).document(str(user_id))
        email_ref = self._db.collection(self._EMAIL_COLLECTION).document(email_lower)

        @transactional
        def _txn(transaction: Any) -> None:
            existing = email_ref.get(transaction=transaction)
            if existing.exists:
                raise ValueError(f"email already in use: {fields['email']}")
            transaction.set(user_ref, doc)
            transaction.set(email_ref, {"user_id": user_id})

        await asyncio.to_thread(_txn, self._db.transaction())
        return user_id

    async def update_user(self, user_id: int, fields: dict[str, Any]) -> bool:
        import asyncio
        from datetime import datetime

        from firebase_admin.firestore import transactional

        demoting = fields.get("user_role_id", 0) != 1 or fields.get("status", "") != "enabled"
        if demoting and await self._count_other_enabled_superadmins([user_id]) == 0:
            return False

        ref = self._db.collection(self._COLLECTION).document(str(user_id))
        new_email_lower = fields["email"].strip().lower() if fields["email"] else ""

        @transactional
        def _txn(transaction: Any) -> None:
            cur = ref.get(transaction=transaction).to_dict() or {}
            update: dict[str, Any] = {"updated_at": datetime.now(UTC).isoformat()}
            if fields["username"]:
                update["username"] = fields["username"]
            update["password_login"] = fields["password_login"]
            if cur.get("type") == "api" and fields["type"] in ("", "api"):
                pass  # API token password never changes here
            elif fields["password_login"]:
                if fields["password"]:
                    update["password"] = fields["password"]
            else:
                update["password"] = None
            old_email_lower = (cur.get("email") or "").strip().lower()
            if new_email_lower and new_email_lower != old_email_lower:
                new_email_ref = self._db.collection(self._EMAIL_COLLECTION).document(
                    new_email_lower
                )
                existing = new_email_ref.get(transaction=transaction)
                if existing.exists:
                    raise ValueError(f"email already in use: {fields['email']}")
                update["email"] = fields["email"]
                transaction.set(new_email_ref, {"user_id": user_id})
                if old_email_lower:
                    transaction.delete(
                        self._db.collection(self._EMAIL_COLLECTION).document(old_email_lower)
                    )
            if fields["name"]:
                update["name"] = fields["name"]
            if fields["type"]:
                update["type"] = fields["type"]
            if fields["user_role_id"]:
                update["user_role_id"] = fields["user_role_id"]
            # -1 clears the list role, 0 leaves it untouched, >0 sets it
            # (same sentinel convention the router passes to the Postgres path).
            if fields["list_role_id"] < 0:
                update["list_role_id"] = None
            elif fields["list_role_id"] > 0:
                update["list_role_id"] = fields["list_role_id"]
            if fields["status"]:
                update["status"] = fields["status"]
            transaction.set(ref, update, merge=True)

        await asyncio.to_thread(_txn, self._db.transaction())
        return True

    async def delete_users(self, ids: list[int]) -> bool:
        import asyncio

        if await self._count_other_enabled_superadmins(ids) == 0:
            return False

        def _run() -> None:
            col = self._db.collection(self._COLLECTION)
            batch = self._db.batch()
            for uid in ids:
                ref = col.document(str(uid))
                snap = ref.get()
                if snap.exists:
                    email = (snap.to_dict() or {}).get("email", "").strip().lower()
                    if email:
                        batch.delete(self._db.collection(self._EMAIL_COLLECTION).document(email))
                    batch.delete(ref)
            batch.commit()

        await asyncio.to_thread(_run)
        return True

    async def update_user_profile(
        self, user_id: int, name: str, email: str, password_login: bool, password: str
    ) -> None:
        import asyncio

        def _run() -> None:
            ref = self._db.collection(self._COLLECTION).document(str(user_id))
            update: dict[str, Any] = {"name": name}
            if password_login:
                update["email"] = email
                if password:
                    update["password"] = password
            else:
                update["password"] = None
            ref.set(update, merge=True)

        await asyncio.to_thread(_run)

    async def update_user_login(self, user_id: int, avatar: str) -> None:
        import asyncio
        from datetime import datetime

        def _run() -> None:
            update: dict[str, Any] = {"loggedin_at": datetime.now(UTC).isoformat()}
            if avatar:
                update["avatar"] = avatar
            self._db.collection(self._COLLECTION).document(str(user_id)).set(update, merge=True)

        await asyncio.to_thread(_run)

    async def set_user_twofa(self, user_id: int, twofa_type: str, twofa_key: str | None) -> None:
        import asyncio
        from datetime import datetime

        def _run() -> None:
            self._db.collection(self._COLLECTION).document(str(user_id)).set(
                {
                    "twofa_type": twofa_type,
                    "twofa_key": twofa_key,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                merge=True,
            )

        await asyncio.to_thread(_run)
