"""One-off migration: copy the live Postgres `lists` table into Firestore,
preserving exact integer IDs (campaign_lists.list_id, roles.list_id, and
subscriber_lists.list_id all reference lists by integer, and none of those
domains are Firestore-backed yet - so IDs must stay stable and non-
colliding across both databases).

DO NOT set REPO_BACKEND_LISTS=firestore right after running this script.
Subscribers (Phase 4b) and Campaigns (Phase 5) still directly JOIN
Postgres's `lists` table in a dozen+ places (subscriber-list membership,
list targeting, double opt-in flows, campaign targeting). Flipping Lists
alone would silently break all of that for any list touched after cutover.
Lists cuts over together with Subscribers, not before it - see the
migration plan.

Usage (from backend/, with the venv active and .env pointing at both DBs):
    python scripts/migrate_lists_to_firestore.py
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from app import db
    from app.firestore_client import client

    await db.connect()
    rows = await db.fetch("SELECT * FROM lists ORDER BY id")
    await db.close()

    fs = client()
    batch = fs.batch()
    max_id = 0
    for r in rows:
        doc = dict(r)
        for field in ("created_at", "updated_at"):
            if doc.get(field):
                doc[field] = doc[field].isoformat()
        batch.set(fs.collection("lists").document(str(r["id"])), doc)
        max_id = max(max_id, r["id"])
    if rows:
        batch.commit()

    fs.document("counters/lists").set({"next": max_id})

    print(f"Copied {len(rows)} lists from Postgres to Firestore. Counter seeded at {max_id}.")
    print("Reminder: do not flip REPO_BACKEND_LISTS=firestore until Phase 4b (Subscribers) lands.")


if __name__ == "__main__":
    asyncio.run(main())
