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
from app.repos.roles import FirestoreRoleRepo, PgRoleRepo, RoleRepo
from app.repos.sessions import FirestoreSessionRepo, PgSessionRepo, SessionRepo
from app.repos.settings import FirestoreSettingsRepo, PgSettingsRepo, SettingsRepo
from app.repos.users import FirestoreUserRepo, PgUserRepo, UserRepo

media_repo: MediaRepo = (
    FirestoreMediaRepo() if env.repo_backend_media == "firestore" else PgMediaRepo()
)

settings_repo: SettingsRepo = (
    FirestoreSettingsRepo() if env.repo_backend_settings == "firestore" else PgSettingsRepo()
)

session_repo: SessionRepo = (
    FirestoreSessionRepo() if env.repo_backend_sessions == "firestore" else PgSessionRepo()
)

role_repo: RoleRepo = (
    FirestoreRoleRepo() if env.repo_backend_roles == "firestore" else PgRoleRepo()
)

user_repo: UserRepo = (
    FirestoreUserRepo() if env.repo_backend_users == "firestore" else PgUserRepo()
)
