"""One-off migration: copy the live Postgres `settings` table into Firestore.

Run once before flipping REPO_BACKEND_SETTINGS=firestore for the first time
(or after Postgres-side settings changed, to re-sync). Safe to re-run — it's
a full overwrite of each key's Firestore doc from the current Postgres value.

Usage (from backend/, with the venv active and .env pointing at both DBs):
    python scripts/migrate_settings_to_firestore.py
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from app import db
    from app.firestore_client import client

    await db.connect()
    settings_map = await db.fetchval("get-settings") or {}
    await db.close()

    fs = client()
    batch = fs.batch()
    for key, value in settings_map.items():
        ref = fs.collection("settings").document(key)
        batch.set(ref, {"value": value})
    batch.commit()

    print(f"Copied {len(settings_map)} settings keys from Postgres to Firestore.")


if __name__ == "__main__":
    asyncio.run(main())
