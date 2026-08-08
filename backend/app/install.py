"""
First-run installer — port of cmd/install.go.

Executes the original schema.sql on an empty database, then seeds the same
sample data the Go installer creates: default lists, sample subscribers,
default templates, a sample campaign, and the super admin role + user.
"""

from __future__ import annotations

import logging
import uuid

import asyncpg

from app import db
from app.config import env
from app.passwords import hash_password

log = logging.getLogger("listmonk")

MIGRATION_VERSION = "v5.1.0"

# Canonical permissions catalog — port of internal/auth/models.go.
PERMISSIONS: list[str] = [
    "lists:get_all", "lists:manage_all", "list:manage", "list:get",
    "subscribers:get", "subscribers:get_all", "subscribers:manage",
    "subscribers:import", "subscribers:sql_query",
    "tx:send",
    "campaigns:get", "campaigns:get_all", "campaigns:get_analytics",
    "campaigns:manage", "campaigns:manage_all", "campaigns:send",
    "bounces:get", "bounces:manage", "webhooks:post_bounce",
    "media:get", "media:manage",
    "templates:get", "templates:manage",
    "users:get", "users:manage",
    "roles:get", "roles:manage",
    "settings:get", "settings:manage", "settings:maintain",
]

SUPER_ADMIN_ROLE_ID = 1


async def is_installed(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass('public.settings') IS NOT NULL"))


async def install(pool: asyncpg.Pool) -> None:
    """Idempotent first-run install: no-op if the schema already exists."""
    async with pool.acquire() as conn:
        if await is_installed(conn):
            return
        log.info("** first time installation: setting up database **")

        await conn.execute((db.ROOT / "schema.sql").read_text(encoding="utf-8"))
        await conn.execute(
            """INSERT INTO settings (key, value) VALUES('migrations', $1::JSONB)
               ON CONFLICT (key) DO UPDATE SET value = settings.value || EXCLUDED.value""",
            [MIGRATION_VERSION],
        )

        # Default lists.
        def_list = await conn.fetchval(
            db.q("create-list"), str(uuid.uuid4()), "Default list", "private", "single",
            "active", ["test"], "",
        )
        optin_list = await conn.fetchval(
            db.q("create-list"), str(uuid.uuid4()), "Opt-in list", "public", "double",
            "active", ["test"], "",
        )

        # Sample subscribers.
        await conn.execute(
            db.q("upsert-subscriber"), str(uuid.uuid4()), "john@example.com", "John Doe",
            {"type": "known", "good": True, "city": "Bengaluru"},
            [def_list], "unconfirmed", True, True,
        )
        await conn.execute(
            db.q("upsert-subscriber"), str(uuid.uuid4()), "anon@example.com", "Anon Doe",
            {"type": "unknown", "good": True, "city": "Bengaluru"},
            [optin_list], "unconfirmed", True, True,
        )

        # Default templates (the original Go-template files, rendered by our
        # Go-template-compatible renderer in app/tmpl.py).
        tpl_dir = db.ROOT / "static" / "email-templates"
        camp_tpl = await conn.fetchval(
            db.q("create-template"), "Default campaign template", "campaign", "",
            (tpl_dir / "default.tpl").read_text(encoding="utf-8"), None,
        )
        await conn.execute(db.q("set-default-template"), camp_tpl)
        archive_tpl = await conn.fetchval(
            db.q("create-template"), "Default archive template", "campaign", "",
            (tpl_dir / "default-archive.tpl").read_text(encoding="utf-8"), None,
        )
        await conn.execute(
            db.q("create-template"), "Sample transactional template", "tx",
            "Welcome {{ .Subscriber.Name }}",
            (tpl_dir / "sample-tx.tpl").read_text(encoding="utf-8"), None,
        )
        await conn.execute(
            db.q("create-template"), "Sample visual template", "campaign_visual", "",
            (tpl_dir / "default-visual.tpl").read_text(encoding="utf-8"),
            (tpl_dir / "default-visual.json").read_text(encoding="utf-8"),
        )

        # Sample campaign (same content as the Go installer).
        await conn.fetchval(
            db.q("create-campaign"),
            str(uuid.uuid4()), "regular", "Test campaign", "Welcome to listmonk",
            "No Reply <noreply@yoursite.com>",
            "<h3>Hi {{ .Subscriber.FirstName }}!</h3>\n"
            "<p>This is a test e-mail campaign. Your second name is"
            " {{ .Subscriber.LastName }} and you are from"
            " {{ .Subscriber.Attribs.city }}.</p>\n"
            '<p>Here is a <a href="https://listmonk.app@TrackLink">tracked link</a>.</p>\n'
            "<p>Use the link icon in the editor toolbar or when writing raw HTML or"
            " Markdown, simply suffix @TrackLink to the end of a URL to turn it into a"
            " tracking link. Example:</p>\n"
            "<pre>&lt;a href=&quot;https:/&zwnj;/listmonk.app&#064;TrackLink&quot;"
            "&gt;&lt;/a&gt;</pre>\n"
            '<p>For help, refer to the <a href="https://listmonk.app/docs">documentation</a>.</p>',
            None, "richtext", None, [], {}, ["test-campaign"], "email", camp_tpl,
            [1], False, "welcome-to-listmonk", archive_tpl, {"name": "Subscriber"}, None, None,
        )

        # Super admin role + user.
        role = await conn.fetchrow(db.q("create-role"), "Super Admin", "user", PERMISSIONS)
        await conn.fetchval(
            db.q("create-user"), env.admin_username, True, hash_password(env.admin_password),
            f"{env.admin_username}@listmonk", env.admin_username, "user",
            role["id"], None, "enabled",
        )
        log.info("created superadmin user '%s'", env.admin_username)

        # The stats matviews were populated by schema.sql before the seed data
        # existed; refresh so dashboard/subscriber counts are correct at once.
        for v in ("mat_dashboard_counts", "mat_dashboard_charts", "mat_list_subscriber_stats"):
            await conn.execute(f"REFRESH MATERIALIZED VIEW {v}")
