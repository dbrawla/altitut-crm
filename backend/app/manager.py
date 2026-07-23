"""Campaign send engine — port of internal/manager + internal/messenger.

Two pieces:

  * `send()` — the SMTP messenger. Picks an enabled `smtp` settings block by
    messenger name, builds a MIME message and delivers it.
  * `_scan()` — the campaign worker. Polls `next-campaigns`, then walks each
    campaign's subscribers in batches via `next-campaign-subscribers`, renders
    per-subscriber with tmpl.render_message and sends.

The SQL is the original listmonk queries, so the checkpointing semantics
(last_subscriber_id / max_subscriber_id / to_send / sent) are unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

import aiosmtplib

from app import db, settings, tmpl

log = logging.getLogger("listmonk")

# campaign_id -> messages sent in the last 60s (read by /api/campaigns/running/stats).
send_rates: dict[int, int] = {}

# campaign_id -> [timestamps of recent sends], trimmed to a 60s window.
_sent_marks: dict[int, list[float]] = {}

# Campaigns currently being processed, and sent counts not yet flushed to the DB.
_active: dict[int, asyncio.Task] = {}
_pending_sent: dict[int, int] = {}

_scanner: asyncio.Task | None = None
_rate_lock = asyncio.Lock()
_last_send_at = 0.0


# ---------------------------------------------------------------------------
# SMTP messenger
# ---------------------------------------------------------------------------


def _smtp_block(messenger: str) -> dict[str, Any] | None:
    """Resolve a campaign's `messenger` name to an enabled `smtp` settings block."""
    blocks = [b for b in (settings.get("smtp") or []) if b.get("enabled")]
    if not blocks:
        return None
    # "email" (the default) means the first enabled block; named blocks are
    # stored as "email-<name>" by the settings validator.
    if messenger and messenger != "email":
        for b in blocks:
            if b.get("name") == messenger:
                return b
    return blocks[0]


def _build(
    to: str,
    subject: str,
    html: str,
    text: str,
    from_email: str,
    headers: list[dict[str, str]] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    name, addr = parseaddr(from_email)
    msg["From"] = formataddr((name, addr)) if name else addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()

    for h in headers or []:
        for k, v in h.items():
            if k.lower() in ("from", "to", "subject", "message-id"):
                continue  # never let campaign headers override the envelope
            msg[k] = v

    # text/plain first so it is the fallback part of the multipart/alternative.
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


async def _throttle() -> None:
    """Global send-rate limiter (app.message_rate = messages per second)."""
    rate = float(settings.get("app.message_rate") or 0)
    if rate <= 0:
        return
    interval = 1.0 / rate
    global _last_send_at
    async with _rate_lock:
        wait = _last_send_at + interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_send_at = time.monotonic()


async def send(
    to: str,
    subject: str,
    html: str,
    text: str = "",
    from_email: str = "",
    messenger: str = "email",
    headers: list[dict[str, str]] | None = None,
) -> None:
    """Deliver one message. Raises on failure so callers can count errors."""
    block = _smtp_block(messenger)
    if not block:
        raise RuntimeError("no enabled SMTP block configured")

    from_email = from_email or settings.get("app.from_email") or ""
    msg = _build(to, subject, html, text, from_email, headers)

    await _throttle()

    tls = (block.get("tls_type") or "none").upper()
    kwargs: dict[str, Any] = {
        "hostname": block.get("host"),
        "port": int(block.get("port") or 25),
        "timeout": max(5.0, float(block.get("wait_timeout_seconds") or 15)),
        "use_tls": tls == "TLS",
        "start_tls": True if tls == "STARTTLS" else None,
        "validate_certs": not block.get("tls_skip_verify", False),
    }
    if block.get("hello_hostname"):
        kwargs["local_hostname"] = block["hello_hostname"]
    if (block.get("auth_protocol") or "none") != "none" and block.get("username"):
        kwargs["username"] = block["username"]
        kwargs["password"] = block.get("password") or ""

    retries = int(block.get("max_msg_retries") or 2)
    for attempt in range(retries + 1):
        try:
            await aiosmtplib.send(msg, **kwargs)
            return
        except Exception:
            if attempt == retries:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


async def send_test_message(camp: dict[str, Any], sub: dict[str, Any]) -> None:
    """Render a campaign for one subscriber and send it immediately (test send)."""
    subject, html, text = await tmpl.render_message(camp, sub)
    await send(
        to=sub["email"],
        subject=subject,
        html=html,
        text=text,
        from_email=camp.get("from_email") or "",
        messenger=camp.get("messenger") or "email",
        headers=camp.get("headers") or [],
    )


# ---------------------------------------------------------------------------
# Campaign worker
# ---------------------------------------------------------------------------


def _mark_sent(camp_id: int) -> None:
    now = time.monotonic()
    marks = _sent_marks.setdefault(camp_id, [])
    marks.append(now)
    cutoff = now - 60
    while marks and marks[0] < cutoff:
        marks.pop(0)
    send_rates[camp_id] = len(marks)
    _pending_sent[camp_id] = _pending_sent.get(camp_id, 0) + 1


async def _flush_sent(camp_id: int) -> None:
    """Write buffered sent counts for one campaign to the DB.

    _scan() flushes counts for campaigns still in _active via next-campaigns;
    a campaign that starts and finishes inside a single scan interval would
    never be seen there, so its final count has to be flushed directly.
    """
    n = _pending_sent.pop(camp_id, 0)
    if n:
        await db.execute("update-campaign-counts", camp_id, 0, n, 0)


async def _run_campaign(camp: dict[str, Any]) -> None:
    camp_id = camp["id"]
    name = camp.get("name")
    try:
        batch = int(settings.get("app.batch_size") or 1000)
        concurrency = max(1, int(settings.get("app.concurrency") or 10))
        max_errors = int(settings.get("app.max_send_errors") or 0)
        sem = asyncio.Semaphore(concurrency)
        errors = 0

        log.info("campaign %s (%s): starting", camp_id, name)

        while True:
            # Re-read the checkpoint every batch. next-campaigns returns the
            # campaign row from a CTE snapshot taken *before* it updates
            # to_send/max_subscriber_id, so those fields are stale (0) there.
            # This query also filters on status='running', which doubles as the
            # stop check when the campaign is paused or cancelled mid-run, and
            # returns one row per campaign list.
            meta = await db.fetch("get-running-campaign", camp_id)
            if not meta:
                log.info("campaign %s (%s): no longer running, stopping", camp_id, name)
                return

            list_ids = [m["list_id"] for m in meta]
            subs = await db.fetch(
                "next-campaign-subscribers",
                camp_id,
                meta[0]["campaign_type"],
                meta[0]["last_subscriber_id"],
                meta[0]["max_subscriber_id"],
                list_ids,
                batch,
            )
            if not subs:
                break

            async def _one(sub: dict[str, Any]) -> bool:
                async with sem:
                    try:
                        subject, html, text = await tmpl.render_message(camp, sub)
                        await send(
                            to=sub["email"],
                            subject=subject,
                            html=html,
                            text=text,
                            from_email=camp.get("from_email") or "",
                            messenger=camp.get("messenger") or "email",
                            headers=camp.get("headers") or [],
                        )
                        _mark_sent(camp_id)
                        return True
                    except Exception as e:
                        log.error("campaign %s: send to %s failed: %s", camp_id, sub["email"], e)
                        return False

            # next-campaign-subscribers advances last_subscriber_id itself, so
            # the next iteration's get-running-campaign picks up the new
            # checkpoint — no manual cursor to track here.
            results = await asyncio.gather(*(_one(s) for s in subs))
            errors += sum(1 for r in results if not r)

            if max_errors > 0 and errors >= max_errors:
                log.error("campaign %s (%s): %s send errors, pausing", camp_id, name, errors)
                await db.execute("update-campaign-status", camp_id, "paused")
                return

        await db.execute("update-campaign-status", camp_id, "finished")
        log.info("campaign %s (%s): finished", camp_id, name)

    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("campaign %s (%s): worker crashed", camp_id, name)
    finally:
        try:
            await _flush_sent(camp_id)
        except Exception:
            log.exception("campaign %s: failed flushing sent count", camp_id)
        _active.pop(camp_id, None)
        send_rates.pop(camp_id, None)
        _sent_marks.pop(camp_id, None)


async def _scan() -> None:
    """Poll for runnable campaigns and flush sent counts for in-flight ones."""
    while True:
        try:
            # next-campaigns excludes $1 (already running here) while using
            # unnest($1,$2) to add the buffered sent counts to campaigns.sent.
            ids = list(_active.keys())
            sent = [_pending_sent.pop(i, 0) for i in ids]
            rows = await db.fetch("next-campaigns", ids, sent)
            for camp in rows:
                if camp["id"] not in _active:
                    _active[camp["id"]] = asyncio.create_task(_run_campaign(camp))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("campaign scanner error")
        await asyncio.sleep(5)


async def start() -> None:
    global _scanner
    if _scanner is None:
        _scanner = asyncio.create_task(_scan())
        log.info("campaign manager started")


async def stop() -> None:
    global _scanner
    if _scanner:
        _scanner.cancel()
        _scanner = None
    for t in list(_active.values()):
        t.cancel()
    if _active:
        await asyncio.gather(*_active.values(), return_exceptions=True)
    _active.clear()
