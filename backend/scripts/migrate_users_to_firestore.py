"""One-off migration: copy the live Postgres `users` table into Firestore,
preserving exact integer IDs (nothing else references them directly today,
but keeping the convention consistent with roles/media). Also seeds the
user_emails/{email_lower} reservation-doc collection used for uniqueness
enforcement on the Firestore path.

Usage (from backend/, with the venv active and .env pointing at both DBs):
    python scripts/migrate_users_to_firestore.py
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from app import db
    from app.firestore_client import client

    await db.connect()
    rows = await db.fetch("SELECT * FROM users ORDER BY id")
    await db.close()

    fs = client()
    batch = fs.batch()
    max_id = 0
    for r in rows:
        doc = dict(r)
        for field in ("created_at", "updated_at", "loggedin_at"):
            if doc.get(field):
                doc[field] = doc[field].isoformat()
        batch.set(fs.collection("users").document(str(r["id"])), doc)
        email_lower = (r["email"] or "").strip().lower()
        if email_lower:
            batch.set(fs.collection("user_emails").document(email_lower), {"user_id": r["id"]})
        max_id = max(max_id, r["id"])
    if rows:
        batch.commit()

    fs.document("counters/users").set({"next": max_id})

    print(f"Copied {len(rows)} users from Postgres to Firestore. Counter seeded at {max_id}.")


if __name__ == "__main__":
    asyncio.run(main())
