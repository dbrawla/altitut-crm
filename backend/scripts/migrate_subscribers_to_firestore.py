"""One-off migration: copy Postgres `subscribers` + `subscriber_lists` into
Firestore, preserving exact integer subscriber IDs and seeding the
per-list distributed counter shards from the real membership data.

Run this BEFORE flipping REPO_BACKEND_SUBSCRIBERS=firestore, and only after
REPO_BACKEND_LISTS=firestore has also been flipped and Lists migrated
(list_repo composition needs list data to resolve list names/details) - or
while Lists is still Postgres-backed, which also works fine since
list_repo transparently reads whichever backend Lists is on.

Usage (from backend/, with the venv active and .env pointing at both DBs):
    python scripts/migrate_subscribers_to_firestore.py
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from app import db
    from app.firestore_client import client

    await db.connect()
    subs = await db.fetch("SELECT * FROM subscribers ORDER BY id")
    memberships = await db.fetch("SELECT * FROM subscriber_lists ORDER BY subscriber_id, list_id")
    await db.close()

    fs = client()

    # Subscribers + email reservations, batched (Firestore batches cap at 500 writes).
    max_id = 0
    batch = fs.batch()
    n = 0
    for r in subs:
        doc = dict(r)
        for field in ("created_at", "updated_at"):
            if doc.get(field):
                doc[field] = doc[field].isoformat()
        batch.set(fs.collection("subscribers").document(str(r["id"])), doc)
        email_lower = r["email"].strip().lower()
        batch.set(fs.collection("subscriber_emails").document(email_lower), {"subscriber_id": r["id"]})
        max_id = max(max_id, r["id"])
        n += 2
        if n >= 400:
            batch.commit()
            batch = fs.batch()
            n = 0
    if n:
        batch.commit()
    fs.document("counters/subscribers").set({"next": max_id})
    print(f"Copied {len(subs)} subscribers.")

    # Membership docs + counter shards, batched.
    shard_counts: dict[tuple[int, str, str], int] = {}  # (list_id, shard, status) -> delta
    batch = fs.batch()
    n = 0
    for m in memberships:
        doc = dict(m)
        for field in ("created_at", "updated_at"):
            if doc.get(field):
                doc[field] = doc[field].isoformat()
        ref = fs.collection("subscriber_lists").document(f"{m['subscriber_id']}_{m['list_id']}")
        batch.set(ref, doc)
        n += 1
        shard = str(m["subscriber_id"] % 10)
        key = (m["list_id"], shard, m["status"])
        shard_counts[key] = shard_counts.get(key, 0) + 1
        if n >= 400:
            batch.commit()
            batch = fs.batch()
            n = 0
    if n:
        batch.commit()
    print(f"Copied {len(memberships)} list memberships.")

    # Seed counter shards from the aggregated membership data.
    by_list_shard: dict[tuple[int, str], dict[str, int]] = {}
    for (list_id, shard, status), count in shard_counts.items():
        by_list_shard.setdefault((list_id, shard), {})[status] = count
    batch = fs.batch()
    n = 0
    for (list_id, shard), statuses in by_list_shard.items():
        ref = (
            fs.collection("lists")
            .document(str(list_id))
            .collection("counter_shards")
            .document(shard)
        )
        batch.set(ref, statuses)
        n += 1
        if n >= 400:
            batch.commit()
            batch = fs.batch()
            n = 0
    if n:
        batch.commit()
    print(f"Seeded counter shards for {len(by_list_shard)} (list, shard) pairs.")


if __name__ == "__main__":
    asyncio.run(main())
