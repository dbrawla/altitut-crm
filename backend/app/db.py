"""
Database layer: asyncpg pool + the original listmonk SQL queries.

The Go app executes named queries from queries/*.sql (goyesql format) — this
module loads those same files verbatim so the Python port runs identical SQL.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import asyncpg
import orjson

from app.config import env

# Resolve the directory that holds schema.sql / queries/ / i18n/ / static/.
# Dev checkout: <repo root>. Docker: /app (Dockerfile copies them next to app/).
ROOT: Path = next(
    (p for p in Path(__file__).resolve().parents[1:3] if (p / "schema.sql").exists()),
    Path(__file__).resolve().parents[2],
)

_NAME_RE = re.compile(r"^\s*--\s*name:\s*(\S+)")

# name -> SQL text, loaded once at import.
queries: dict[str, str] = {}


def _load_queries() -> None:
    for f in sorted((ROOT / "queries").glob("*.sql")):
        name: str | None = None
        buf: list[str] = []
        for line in f.read_text(encoding="utf-8").splitlines():
            m = _NAME_RE.match(line)
            if m:
                if name:
                    queries[name] = "\n".join(buf).strip()
                name, buf = m.group(1), []
            elif name is not None:
                buf.append(line)
        if name:
            queries[name] = "\n".join(buf).strip()


_load_queries()

pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    # JSON/JSONB as Python objects via orjson (fast, matches Go's raw JSON handling).
    for t in ("json", "jsonb"):
        await conn.set_type_codec(
            t, encoder=lambda v: orjson.dumps(v).decode(), decoder=orjson.loads, schema="pg_catalog"
        )
    # UUIDs as plain strings — everything downstream (JSON APIs) wants strings.
    await conn.set_type_codec(
        "uuid", encoder=str, decoder=str, schema="pg_catalog", format="text"
    )


async def connect() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(
        host=env.db_host,
        port=env.db_port,
        user=env.db_user,
        password=env.db_password,
        database=env.db_name,
        ssl="require" if env.db_ssl_mode not in ("", "disable") else None,
        min_size=2,
        max_size=env.db_max_open_conns,
        max_inactive_connection_lifetime=env.db_conn_max_lifetime,
        init=_init_conn,
    )
    return pool


async def close() -> None:
    if pool:
        await pool.close()


def q(name: str) -> str:
    """Look up an original named query; raises KeyError on typos at call time."""
    return queries[name]


# --- Thin fetch helpers (records -> dicts for JSON responses) ---------------


async def fetch(name_or_sql: str, *args: Any) -> list[dict[str, Any]]:
    sql = queries.get(name_or_sql, name_or_sql)
    assert pool
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetchrow(name_or_sql: str, *args: Any) -> dict[str, Any] | None:
    sql = queries.get(name_or_sql, name_or_sql)
    assert pool
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def fetchval(name_or_sql: str, *args: Any) -> Any:
    sql = queries.get(name_or_sql, name_or_sql)
    assert pool
    return await pool.fetchval(sql, *args)


async def execute(name_or_sql: str, *args: Any) -> str:
    sql = queries.get(name_or_sql, name_or_sql)
    assert pool
    return await pool.execute(sql, *args)
