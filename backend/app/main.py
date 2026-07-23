"""
Listmonk FastAPI application entry point — port of cmd/main.go.

Startup: connect the asyncpg pool, run the idempotent first-run installer
(schema.sql + seed data + super admin), then load runtime settings from the
`settings` table.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import db, install, manager, settings
from app.routers import (
    admin,
    auth,
    bounces,
    campaigns,
    import_,
    lists,
    media,
    public,
    subscribers,
    templates,
    users,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await db.connect()
    await install.install(pool)
    await settings.load()
    await manager.start()
    yield
    await manager.stop()
    await db.close()


app = FastAPI(
    title="listmonk",
    version=settings.VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ponytail: no CORS middleware — the app serves its own frontend (same origin)
# and dev uses the Vite proxy; add CORSMiddleware if a separate origin appears.

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(subscribers.router)
app.include_router(lists.router)
app.include_router(campaigns.router)
app.include_router(templates.router)
app.include_router(import_.router)
app.include_router(users.router)
app.include_router(media.router)
app.include_router(bounces.router)
# Public/subscriber-facing routes. Must be registered before the SPA catch-all
# below, which would otherwise swallow /campaign/*, /link/* and /subscription/*.
app.include_router(public.router)


# Media uploads. The directory is a runtime setting (editable in the UI), so
# serve via a route instead of a StaticFiles mount fixed at startup.
@app.get("/uploads/{name:path}", include_in_schema=False)
async def serve_upload(name: str) -> FileResponse:
    base = Path(settings.get("upload.filesystem.upload_path") or "uploads").resolve()
    file = (base / name).resolve()
    if file.is_file() and file.is_relative_to(base):
        return FileResponse(file)
    raise HTTPException(status_code=404)


# Built frontend (dist/) with an SPA fallback so /admin/* deep links work.
# db.ROOT is the repo root locally and /app in Docker.
dist_path = db.ROOT / "frontend" / "dist"
if dist_path.exists():

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str) -> FileResponse:
        # Unknown /api/* URLs stay JSON 404s instead of returning index.html.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (dist_path / path).resolve()
        if file.is_file() and file.is_relative_to(dist_path):
            return FileResponse(file)
        return FileResponse(dist_path / "index.html")
