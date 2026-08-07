"""Media upload endpoints — port of cmd/media.go.

Only the `filesystem` upload provider is implemented; the settings UI also
offers `s3`. ponytail: add an S3 branch in _store()/_delete() with aiobotocore
(already a dependency) if/when S3 uploads are actually used.
"""

from __future__ import annotations

import io
import logging
import uuid as uuidlib
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, File, UploadFile

from app import auth, settings
from app.repos import media_repo
from app.utils import Pagination, bad_request, not_found, ok

log = logging.getLogger("listmonk")
router = APIRouter(tags=["media"])

# Raster types we can safely generate a thumbnail for.
_THUMB_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_THUMB_PX = 250


def _upload_dir() -> Path:
    p = Path(settings.get("upload.filesystem.upload_path") or "uploads").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _uri(filename: str) -> str:
    base = (settings.get("upload.filesystem.upload_uri") or "/uploads").rstrip("/")
    return f"{base}/{filename}"


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.pop("total", None)
    row["url"] = _uri(row["filename"])
    row["thumb_url"] = _uri(row["thumb"]) if row.get("thumb") else row["url"]
    return row


def _safe_name(name: str) -> str:
    """Strip any path components — never trust a client-supplied filename."""
    stem = Path(name or "file").name.replace("\x00", "")
    return stem[:200] or "file"


@router.get("/api/media", dependencies=[auth.require("media:get")])
async def get_all_media(pg: Pagination = Depends(), query: str = "") -> dict[str, Any]:
    provider = settings.get("upload.provider") or "filesystem"
    rows, total = await media_repo.query(query, provider, pg.offset, pg.limit)
    return ok(pg.results([_shape(r) for r in rows], total, query))


@router.get("/api/media/{media_id}", dependencies=[auth.require("media:get")])
async def get_media(media_id: int) -> dict[str, Any]:
    row = await media_repo.get(media_id)
    if not row:
        raise not_found("media not found")
    return ok(_shape(row))


@router.post("/api/media", dependencies=[auth.require("media:manage")])
async def upload_media(file: UploadFile = File(...)) -> dict[str, Any]:
    exts = settings.get("upload.extensions") or []
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if exts and "*" not in exts and ext not in [e.lower().lstrip(".") for e in exts]:
        raise bad_request(f"unsupported file type: .{ext}")

    max_mb = int(settings.get("upload.max_file_size") or 5000)
    body = await file.read()
    if len(body) > max_mb * 1024:
        raise bad_request(f"file is larger than the {max_mb} KB limit")

    # Prefix with a UUID so uploads never overwrite each other.
    uid = str(uuidlib.uuid4())
    filename = f"{uid[:8]}-{_safe_name(file.filename or 'file')}"
    directory = _upload_dir()

    async with aiofiles.open(directory / filename, "wb") as f:
        await f.write(body)

    # Thumbnail for raster images; non-images just reuse the original.
    thumb = ""
    if (file.content_type or "") in _THUMB_TYPES:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(body))
            img.thumbnail((_THUMB_PX, _THUMB_PX))
            thumb = f"thumb_{filename}"
            img.save(directory / thumb)
        except Exception:
            # Not fatal — the upload still succeeds, just without a thumbnail.
            log.warning("could not thumbnail %s", filename, exc_info=True)
            thumb = ""

    media_id = await media_repo.insert(
        uid, filename, thumb, file.content_type or "",
        settings.get("upload.provider") or "filesystem", {},
    )
    row = await media_repo.get(media_id)
    return ok(_shape(row or {}))


@router.delete("/api/media/{media_id}", dependencies=[auth.require("media:manage")])
async def delete_media(media_id: int) -> dict[str, Any]:
    row = await media_repo.delete(media_id)
    if not row:
        raise not_found("media not found")

    directory = _upload_dir()
    for name in (row.get("filename"), row.get("thumb")):
        if not name:
            continue
        f = (directory / name).resolve()
        # Never follow a crafted filename outside the upload directory.
        if f.is_relative_to(directory) and f.is_file():
            f.unlink(missing_ok=True)

    return ok(True)
