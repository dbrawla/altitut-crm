"""Subscriber import endpoints — port of cmd/import.go."""

from __future__ import annotations

import orjson
from fastapi import APIRouter, File, Form, UploadFile

from app import auth, importer
from app.utils import bad_request, ok

router = APIRouter(tags=["import"])


@router.get("/api/import/subscribers", dependencies=[auth.require("subscribers:import")])
async def get_import_status():
    return ok(importer.status)


@router.get("/api/import/subscribers/logs", dependencies=[auth.require("subscribers:import")])
async def get_import_logs():
    return ok("\n".join(importer.logs))


@router.post("/api/import/subscribers", dependencies=[auth.require("subscribers:import")])
async def start_import(params: str = Form(...), file: UploadFile = File(...)):
    try:
        p = orjson.loads(params)
    except Exception:
        raise bad_request("invalid params JSON")

    mode = p.get("mode", importer.MODE_SUBSCRIBE)
    if mode not in (importer.MODE_SUBSCRIBE, importer.MODE_BLOCKLIST):
        raise bad_request("invalid mode")
    subscription_status = p.get("subscription_status", "unconfirmed")
    if mode == importer.MODE_SUBSCRIBE and subscription_status not in (
        "unconfirmed", "confirmed", "unsubscribed",
    ):
        raise bad_request("invalid subscription_status")
    if mode == importer.MODE_SUBSCRIBE and not p.get("lists"):
        raise bad_request("no lists given to import into")

    blob = await file.read()
    try:
        importer.start(
            file.filename or "import.csv",
            blob,
            mode,
            subscription_status,
            p.get("delim", ","),
            [int(i) for i in p.get("lists", [])],
            bool(p.get("overwrite", False)),
        )
    except ValueError as e:
        raise bad_request(str(e))
    return ok(importer.status)


@router.delete("/api/import/subscribers", dependencies=[auth.require("subscribers:import")])
async def stop_import():
    await importer.stop()
    return ok(importer.status)
