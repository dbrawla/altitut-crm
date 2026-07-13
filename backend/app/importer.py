"""
Bulk subscriber importer — port of internal/subimporter.

Accepts a CSV (or ZIP containing one), streams rows through the original
upsert-subscriber / upsert-blocklist-subscriber queries in batches, and keeps
an in-memory status + log ring the UI polls.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid as uuidlib
import zipfile
from typing import Any

import orjson

from app import db

log = logging.getLogger("listmonk")

MODE_SUBSCRIBE = "subscribe"
MODE_BLOCKLIST = "blocklist"

# none | importing | stopping | finished | failed
status: dict[str, Any] = {"name": "", "total": 0, "imported": 0, "status": "none"}
logs: list[str] = []
_task: asyncio.Task | None = None


def _log(msg: str) -> None:
    logs.append(msg)
    if len(logs) > 1000:
        del logs[: len(logs) - 1000]


def is_importing() -> bool:
    return status["status"] in ("importing", "stopping")


def reset() -> None:
    global _task
    status.update({"name": "", "total": 0, "imported": 0, "status": "none"})
    logs.clear()
    _task = None


async def stop() -> None:
    global _task
    if _task and not _task.done():
        status["status"] = "stopping"
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    reset()


def _extract_csv(filename: str, blob: bytes) -> tuple[str, bytes]:
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    return name, z.read(name)
        raise ValueError("no CSV file found in ZIP")
    return filename, blob


def start(
    filename: str,
    blob: bytes,
    mode: str,
    subscription_status: str,
    delim: str,
    list_ids: list[int],
    overwrite: bool,
) -> None:
    """Kick off the background import task."""
    global _task
    if is_importing():
        raise ValueError("an import is already running")

    name, data = _extract_csv(filename, blob)
    reset()
    status.update({"name": name, "status": "importing"})
    _task = asyncio.get_running_loop().create_task(
        _run(data, mode, subscription_status, delim or ",", list_ids, overwrite)
    )


async def _run(
    data: bytes,
    mode: str,
    subscription_status: str,
    delim: str,
    list_ids: list[int],
    overwrite: bool,
) -> None:
    try:
        text = data.decode("utf-8-sig", errors="replace")
        status["total"] = max(text.count("\n") - 1, 0)

        reader = csv.DictReader(io.StringIO(text), delimiter=delim[0])
        if not reader.fieldnames or "email" not in [f.strip().lower() for f in reader.fieldnames]:
            raise ValueError("missing 'email' column in CSV")
        reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]

        imported = 0
        for i, row in enumerate(reader, start=1):
            if status["status"] == "stopping":
                break
            email = (row.get("email") or "").strip().lower()
            name = (row.get("name") or email).strip()
            if not email or "@" not in email:
                _log(f"row {i}: invalid email {email!r}")
                continue
            attribs: dict = {}
            if row.get("attributes"):
                try:
                    attribs = orjson.loads(row["attributes"])
                except Exception:
                    _log(f"row {i}: invalid attributes JSON")
            try:
                if mode == MODE_BLOCKLIST:
                    await db.execute(
                        "upsert-blocklist-subscriber", str(uuidlib.uuid4()), email, name, attribs
                    )
                else:
                    await db.execute(
                        "upsert-subscriber",
                        str(uuidlib.uuid4()), email, name, attribs, list_ids,
                        subscription_status or "unconfirmed", overwrite, overwrite,
                    )
                imported += 1
                status["imported"] = imported
            except Exception as e:
                _log(f"row {i}: {email}: {e}")

        status["status"] = "finished"
        _log(f"import complete: {imported} record(s)")

        # Notify admins like the original (import-status email).
        try:
            from app import notifs

            await notifs.notify_admins(
                "import-status",
                f"Import complete: {status['name']}",
                {"name": status["name"], "records": imported, "status": "finished"},
            )
        except Exception:
            log.exception("error sending import notification")
    except asyncio.CancelledError:
        status["status"] = "none"
        raise
    except Exception as e:
        log.exception("import failed")
        _log(f"import failed: {e}")
        status["status"] = "failed"
