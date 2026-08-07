"""Composition root for the Postgres->Firestore migration.

Each domain's repo backend is picked once, at import time, from a config
flag (app/config.py's repo_backend_*). Routers import the domain's `repo`
singleton from here instead of calling app.db directly. Flipping a domain
from Postgres to Firestore — for a shadow-write period, then for real — is a
config change here, not a router rewrite. See the migration plan
(/Users/daisy/.claude/plans/modular-floating-eich.md) for phase ordering.
"""

from __future__ import annotations

from app.config import env
from app.repos.media import FirestoreMediaRepo, MediaRepo, PgMediaRepo

media_repo: MediaRepo = (
    FirestoreMediaRepo() if env.repo_backend_media == "firestore" else PgMediaRepo()
)
