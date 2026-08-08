"""One-off migration: copy the live Postgres `roles` table into Firestore,
preserving exact IDs (users.user_role_id/list_role_id and
auth.SUPER_ADMIN_ROLE_ID=1 reference these by integer, and Users stays
Postgres-backed until Phase 3c - so IDs must match across both backends
until Users cuts over too). Seeds the ID counter to continue above the
highest migrated ID so new roles never collide.

Usage (from backend/, with the venv active and .env pointing at both DBs):
    python scripts/migrate_roles_to_firestore.py
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from app import db
    from app.firestore_client import client

    await db.connect()
    rows = await db.fetch(
        "SELECT id, name, type, parent_id, list_id, permissions, created_at, updated_at "
        "FROM roles ORDER BY id"
    )
    await db.close()

    fs = client()
    batch = fs.batch()
    max_id = 0
    for r in rows:
        doc = {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "parent_id": r["parent_id"],
            "list_id": r["list_id"],
            "permissions": r["permissions"] or [],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        batch.set(fs.collection("roles").document(str(r["id"])), doc)
        max_id = max(max_id, r["id"])
    if rows:
        batch.commit()

    fs.document("counters/roles").set({"next": max_id})

    print(f"Copied {len(rows)} roles from Postgres to Firestore. Counter seeded at {max_id}.")


if __name__ == "__main__":
    asyncio.run(main())
