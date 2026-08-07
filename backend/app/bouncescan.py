"""Bounce mailbox scanner — port of internal/bounce/mailbox.

Polls the POP3/IMAP mailboxes configured under `bounce.mailboxes`, parses each
message for the X-Listmonk-Campaign/-Subscriber headers listmonk stamps on
outgoing mail, classifies the bounce as hard or soft, records it, and deletes
the message from the server.

poplib/imaplib are blocking, so each scan runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import email.policy
import logging
import re
from typing import Any

from app import settings
from app.utils import parse_duration

log = logging.getLogger("listmonk")

# Never pull an unbounded mailbox in one pass.
MAX_PER_SCAN = 500

_H_CAMPAIGN = "X-Listmonk-Campaign"
_H_SUBSCRIBER = "X-Listmonk-Subscriber"

_UUID = r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}"

# Headers may sit on an attached original message rather than the outer
# envelope, so fall back to scanning the raw bytes.
_RE_CAMPAIGN = re.compile(rf"(?mi)^{_H_CAMPAIGN}:\s*({_UUID})")
_RE_SUBSCRIBER = re.compile(rf"(?mi)^{_H_SUBSCRIBER}:\s*({_UUID})")
_RE_FINAL_RCPT = re.compile(r"(?mi)^Final-Recipient:\s*rfc822;\s*(\S+)")
_RE_ORIG_RCPT = re.compile(r"(?mi)^Original-Recipient:\s*rfc822;\s*(\S+)")

# Enhanced SMTP status code: 5.x.x = permanent (hard), 4.x.x = transient (soft).
_RE_SMTP_STATUS = re.compile(r"(?mi)^(?:Status:\s*)?(?:\d{3}\s+)?([45]\.\d+\.\d+)")

_RE_HARD = re.compile(
    r"(?i)(NXDOMAIN|user unknown|address not found|mailbox not found|address.*reject"
    r"|does not exist|invalid recipient|no such user|recipient.*invalid|undeliverable"
    r"|permanent.*failure|permanent.*error|bad.*address|unknown.*user|account.*disabled"
    r"|address.*disabled)"
)

_RE_COMPLAINT = re.compile(r"(?i)(feedback-type:\s*abuse|this is an abuse report|complaint)")

_task: asyncio.Task[None] | None = None


def classify(raw: bytes) -> tuple[str, str]:
    """Return (bounce_type, reason). Soft is the safe default."""
    text = raw.decode("utf-8", "replace")

    if _RE_COMPLAINT.search(text):
        return "complaint", "complaint_report"

    for m in _RE_SMTP_STATUS.finditer(text):
        status = m.group(1)
        if status.startswith("5"):
            return "hard", f"smtp_status={status}"
        if status.startswith("4"):
            return "soft", f"smtp_status={status}"

    if hard := _RE_HARD.search(text):
        return "hard", f"body_match={hard.group(1)}"

    return "soft", "default"


def parse_message(raw: bytes) -> dict[str, Any] | None:
    """Extract the bounce details from one raw message, or None if unusable."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        log.debug("could not parse bounce message", exc_info=True)
        return None

    text = raw.decode("utf-8", "replace")

    def find(header: str, pattern: re.Pattern[str]) -> str:
        v = msg.get(header)
        if v:
            return str(v).strip()
        # Walk sub-parts (a DSN attaches the original message).
        for part in msg.walk():
            v = part.get(header)
            if v:
                return str(v).strip()
        m = pattern.search(text)
        return m.group(1).strip() if m else ""

    camp_uuid = find(_H_CAMPAIGN, _RE_CAMPAIGN)
    sub_uuid = find(_H_SUBSCRIBER, _RE_SUBSCRIBER)

    # Recipient: prefer the DSN's Final-Recipient, then Original-Recipient.
    email_addr = ""
    for pattern in (_RE_FINAL_RCPT, _RE_ORIG_RCPT):
        if m := pattern.search(text):
            email_addr = m.group(1).strip().strip("<>").lower()
            break
    if not email_addr:
        dt = msg.get("Delivered-To") or ""
        email_addr = str(dt).strip().lower()

    if not sub_uuid and not email_addr:
        # Nothing to attribute the bounce to.
        return None

    btype, reason = classify(raw)
    return {
        "email": email_addr,
        "sub_uuid": sub_uuid,
        "camp_uuid": camp_uuid,
        "btype": btype,
        "meta": {
            "from": str(msg.get("From") or ""),
            "subject": str(msg.get("Subject") or ""),
            "message_id": str(msg.get("Message-Id") or ""),
            "classify_reason": reason,
        },
    }


def _fetch_pop(box: dict[str, Any]) -> list[bytes]:
    """Download and delete messages over POP3. Blocking — run in a thread."""
    import poplib

    host, port = box.get("host") or "", int(box.get("port") or 995)
    cls = poplib.POP3_SSL if box.get("tls_enabled", True) else poplib.POP3

    kwargs: dict[str, Any] = {"host": host, "port": port, "timeout": 30}
    if box.get("tls_enabled", True) and box.get("tls_skip_verify"):
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["context"] = ctx

    conn = cls(**kwargs)
    try:
        if (box.get("auth_protocol") or "userpass") != "none":
            conn.user(box.get("username") or "")
            conn.pass_(box.get("password") or "")

        count = len(conn.list()[1])
        out: list[bytes] = []
        for i in range(1, min(count, MAX_PER_SCAN) + 1):
            try:
                raw = b"\n".join(conn.retr(i)[1])
                out.append(raw)
                conn.dele(i)
            except Exception:
                log.warning("error retrieving bounce message %d", i, exc_info=True)
        return out
    finally:
        # Best-effort teardown: the socket is going away either way.
        with contextlib.suppress(Exception):
            conn.quit()  # commits the DELEs


def _fetch_imap(box: dict[str, Any]) -> list[bytes]:
    """Download and delete messages over IMAP. Blocking — run in a thread."""
    import imaplib

    host, port = box.get("host") or "", int(box.get("port") or 993)
    cls = imaplib.IMAP4_SSL if box.get("tls_enabled", True) else imaplib.IMAP4
    conn = cls(host, port)
    try:
        if (box.get("auth_protocol") or "userpass") != "none":
            conn.login(box.get("username") or "", box.get("password") or "")
        conn.select(box.get("folder") or "INBOX")

        typ, data = conn.search(None, "ALL")
        if typ != "OK":
            return []
        ids = (data[0] or b"").split()[:MAX_PER_SCAN]

        out: list[bytes] = []
        for raw_id in ids:
            i = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            typ, msg_data = conn.fetch(i, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            out.append(msg_data[0][1])
            conn.store(i, "+FLAGS", "\\Deleted")
        conn.expunge()
        return out
    finally:
        # Best-effort teardown: the socket is going away either way.
        with contextlib.suppress(Exception):
            conn.logout()


async def scan_once(box: dict[str, Any]) -> int:
    """Scan one mailbox and record any bounces found. Returns the count."""
    from app.routers import bounces

    fetch = _fetch_imap if (box.get("type") or "pop").lower() == "imap" else _fetch_pop
    messages = await asyncio.to_thread(fetch, box)

    n = 0
    for raw in messages:
        parsed = parse_message(raw)
        if not parsed:
            continue
        try:
            await bounces.record(
                email=parsed["email"],
                sub_uuid=parsed["sub_uuid"],
                camp_uuid=parsed["camp_uuid"],
                btype=parsed["btype"],
                source=box.get("type") or "pop",
                meta=parsed["meta"],
            )
            n += 1
        except Exception:
            log.warning("could not record bounce for %s", parsed.get("email"), exc_info=True)
    return n


async def _loop() -> None:
    while True:
        interval = 900.0
        try:
            if settings.get("bounce.enabled", False):
                for box in settings.get("bounce.mailboxes") or []:
                    if not box.get("enabled"):
                        continue
                    interval = max(60.0, parse_duration(box.get("scan_interval") or "", 900.0))
                    try:
                        n = await scan_once(box)
                        if n:
                            log.info("recorded %d bounce(s) from %s", n, box.get("host"))
                    except Exception:
                        log.exception("error scanning bounce mailbox %s", box.get("host"))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("bounce scanner error")
        await asyncio.sleep(interval)


async def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_loop())
        log.info("bounce scanner started")


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass  # expected: we just cancelled it
        except Exception:
            log.exception("bounce scanner raised while stopping")
        _task = None
