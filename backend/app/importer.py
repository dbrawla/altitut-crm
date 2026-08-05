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
import itertools
import logging
import re
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
_task: asyncio.Task[None] | None = None


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
        except asyncio.CancelledError:
            pass  # expected: we just cancelled it
        except Exception:
            log.exception("import task raised while stopping")
    reset()


# --- Column detection ------------------------------------------------------
#
# Exported subscriber lists rarely use listmonk's own header names. Rather than
# rejecting anything without a literal `email` column, match the headers people
# actually export from Mailchimp, HubSpot, Google Contacts, Excel and so on.

_EMAIL_ALIASES = (
    "email", "e mail", "email address", "e mail address", "emailaddress",
    "mail", "primary email", "work email", "email 1", "email1",
)
_FIRST_ALIASES = (
    "first name", "firstname", "first", "fname", "given name", "givenname",
    "forename", "first name (required)",
)
_LAST_ALIASES = (
    "last name", "lastname", "last", "lname", "surname", "family name",
    "familyname", "second name",
)
_NAME_ALIASES = (
    "name", "full name", "fullname", "display name", "displayname",
    "subscriber name", "contact name",
)
_ATTRIB_ALIASES = ("attributes", "attribs", "attrs", "metadata", "meta")


def _norm_header(h: str) -> str:
    """`First_Name ` / `First-Name` / `FIRST NAME` all collapse to `first name`."""
    return re.sub(r"[\s_\-.]+", " ", (h or "").strip().lower()).strip()


def _pick(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    """First header matching an alias. Exact matches win over substring ones so
    a `name` alias can't swallow a column actually called `first name`."""
    norm = {h: _norm_header(h) for h in headers}
    for alias in aliases:
        for h in headers:
            if norm[h] == alias:
                return h
    for alias in aliases:
        for h in headers:
            if alias in norm[h]:
                return h
    return None


def _sniff_email_column(headers: list[str], rows: list[dict[str, str]]) -> str | None:
    """No recognisable email header — find the column whose values look like
    addresses. Beats failing the whole import over an unlabelled export."""
    for h in headers:
        values = [(r.get(h) or "").strip() for r in rows]
        values = [v for v in values if v]
        if values and all("@" in v and "." in v.split("@")[-1] for v in values):
            return h
    return None


def map_columns(
    headers: list[str], sample: list[dict[str, str]]
) -> dict[str, str | None]:
    """Work out which CSV columns hold the email, name and attributes."""
    email = _pick(headers, _EMAIL_ALIASES) or _sniff_email_column(headers, sample)
    first = _pick(headers, _FIRST_ALIASES)
    last = _pick(headers, _LAST_ALIASES)
    name = _pick(headers, _NAME_ALIASES)
    if name in (email, first, last):
        name = None

    # `Name, Surname` is a common export shape: with a surname column present, a
    # bare `name` is the given name, not the full one.
    if last and not first and name:
        first, name = name, None
    # Otherwise the full-name column is only a fallback for having neither half.
    if first or last:
        name = None
    return {"email": email, "first": first, "last": last, "name": name,
            "attribs": _pick(headers, _ATTRIB_ALIASES)}


def _row_name(row: dict[str, str], cols: dict[str, str | None]) -> str:
    """Full name from whichever of first/last/name columns the CSV provided.

    Joined with a space because tmpl.py derives {{ .Subscriber.FirstName }} and
    .LastName by partitioning `name` on the first space.
    """
    parts = [
        (row.get(cols["first"]) or "").strip() if cols["first"] else "",
        (row.get(cols["last"]) or "").strip() if cols["last"] else "",
    ]
    joined = " ".join(p for p in parts if p)
    if joined:
        return joined
    return (row.get(cols["name"]) or "").strip() if cols["name"] else ""


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
        headers = [h for h in (reader.fieldnames or []) if h]
        if not headers:
            raise ValueError("the CSV has no header row")

        # Peek at a few rows so an unlabelled email column can still be found.
        sample = [row for _, row in zip(range(20), reader, strict=False)]
        cols = map_columns(headers, sample)
        if not cols["email"]:
            raise ValueError(
                "could not find an email column. Name it 'email' (or 'e-mail', "
                f"'email address'). Columns seen: {', '.join(headers)}"
            )
        _log(f"detected email column: {cols['email']!r}")
        if cols["first"] or cols["last"]:
            _log(
                "detected name columns: "
                f"first={cols['first']!r} last={cols['last']!r}"
            )
        elif cols["name"]:
            _log(f"detected name column: {cols['name']!r}")
        else:
            _log("no name column found; falling back to the email address")

        imported = 0
        # itertools.chain replays the sampled rows ahead of the rest of the file.
        for i, row in enumerate(itertools.chain(sample, reader), start=1):
            if status["status"] == "stopping":
                break
            email = (row.get(cols["email"]) or "").strip().lower()
            if not email or "@" not in email:
                _log(f"row {i}: invalid email {email!r}")
                continue
            name = _row_name(row, cols) or email
            attribs: dict[str, Any] = {}
            attrib_col = cols["attribs"]
            if attrib_col and row.get(attrib_col):
                try:
                    attribs = orjson.loads(row[attrib_col])
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
