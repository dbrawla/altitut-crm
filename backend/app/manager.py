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
import contextlib
import email.policy
import logging
import time
from collections.abc import AsyncIterator
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

import aiosmtplib

from app import db, settings, tmpl

log = logging.getLogger("listmonk")

# RFC 5322 allows 998-char lines. The default 78-char limit makes Python fall
# back to RFC 2047 encoded-words for long unfoldable values (a URL has no
# spaces to fold at), which mangles List-Unsubscribe into something no mail
# client can parse. Non-ASCII subjects are still encoded correctly.
_POLICY = email.policy.SMTP.clone(max_line_length=998)

# campaign_id -> messages sent in the last 60s (read by /api/campaigns/running/stats).
send_rates: dict[int, int] = {}

# campaign_id -> [timestamps of recent sends], trimmed to a 60s window.
_sent_marks: dict[int, list[float]] = {}

# Campaigns currently being processed, and sent counts not yet flushed to the DB.
_active: dict[int, asyncio.Task[None]] = {}
_pending_sent: dict[int, int] = {}

_scanner: asyncio.Task[None] | None = None
_rate_lock = asyncio.Lock()
_last_send_at = 0.0


# ---------------------------------------------------------------------------
# SMTP messenger
# ---------------------------------------------------------------------------


def _smtp_block(messenger: str) -> dict[str, Any] | None:
    """Resolve a campaign's `messenger` name to an enabled `smtp` settings block."""
    blocks: list[dict[str, Any]] = [
        b for b in (settings.get("smtp") or []) if b.get("enabled")
    ]
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
    attachments: list[dict[str, Any]] | None = None,
) -> EmailMessage:
    msg = EmailMessage(policy=_POLICY)
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

    for att in attachments or []:
        ctype = att.get("content_type") or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(
            att["content"],
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.get("name") or "attachment",
        )
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
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Deliver one message. Raises on failure so callers can count errors."""
    block = _smtp_block(messenger)
    if not block:
        raise RuntimeError("no enabled SMTP block configured")

    from_email = from_email or settings.get("app.from_email") or ""
    msg = _build(to, subject, html, text, from_email, headers, attachments)

    await _throttle()
    await _deliver(msg, block)


def _client_kwargs(block: dict[str, Any]) -> dict[str, Any]:
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
    return kwargs


def _pool_key(block: dict[str, Any]) -> str:
    """Identity of the server a connection is bound to. Deliberately excludes
    the block's uuid so that renaming a block does not orphan live connections,
    and includes the credentials so a password change forces reconnection."""
    return "|".join(
        str(block.get(k) or "")
        for k in ("host", "port", "tls_type", "auth_protocol", "username", "password")
    )


class _SmtpPool:
    """Keeps authenticated SMTP connections alive between messages.

    Without this, every message paid a fresh TCP + TLS handshake and AUTH — for
    a 10k-subscriber campaign that is 10k handshakes, which providers throttle
    or treat as abuse. `max_conns` and `idle_timeout` come from the SMTP block
    the settings UI already exposes.
    """

    def __init__(self) -> None:
        # pool key -> (client, released_at) stack of idle connections
        self._idle: dict[str, list[tuple[aiosmtplib.SMTP, float]]] = {}
        # pool key -> semaphore capping total concurrent connections
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def _slot(self, key: str, max_conns: int) -> asyncio.Semaphore:
        async with self._lock:
            sem = self._slots.get(key)
            if sem is None or getattr(sem, "_altitut_size", None) != max_conns:
                sem = asyncio.Semaphore(max_conns)
                sem._altitut_size = max_conns  # type: ignore[attr-defined]
                self._slots[key] = sem
            return sem

    async def _take_idle(self, key: str, idle_timeout: float) -> aiosmtplib.SMTP | None:
        now = time.monotonic()
        async with self._lock:
            stack = self._idle.get(key) or []
            while stack:
                client, released_at = stack.pop()
                if now - released_at > idle_timeout:
                    await _quiet_close(client)
                    continue
                if client.is_connected:
                    return client
                await _quiet_close(client)
            return None

    async def _put_idle(self, key: str, client: aiosmtplib.SMTP) -> None:
        async with self._lock:
            self._idle.setdefault(key, []).append((client, time.monotonic()))

    @contextlib.asynccontextmanager
    async def acquire(self, block: dict[str, Any]) -> AsyncIterator[aiosmtplib.SMTP]:
        key = _pool_key(block)
        max_conns = max(1, int(block.get("max_conns") or 10))
        idle_timeout = _duration_seconds(block.get("idle_timeout"), 15.0)

        sem = await self._slot(key, max_conns)
        await sem.acquire()
        client = await self._take_idle(key, idle_timeout)
        reusable = True
        try:
            if client is None:
                client = aiosmtplib.SMTP(**_client_kwargs(block))
                await client.connect()
            yield client
        except Exception:
            # Never hand a connection back after an error — its protocol state
            # is unknown, and a half-open socket poisons the next message.
            reusable = False
            raise
        finally:
            if client is not None:
                if reusable and client.is_connected:
                    await self._put_idle(key, client)
                else:
                    await _quiet_close(client)
            sem.release()

    async def close(self) -> None:
        async with self._lock:
            stacks = list(self._idle.values())
            self._idle.clear()
            self._slots.clear()
        for stack in stacks:
            for client, _ in stack:
                await _quiet_close(client)


async def _quiet_close(client: aiosmtplib.SMTP) -> None:
    # Best-effort teardown; the socket is going away regardless.
    try:
        with contextlib.suppress(Exception):
            if client.is_connected:
                await client.quit()
    finally:
        with contextlib.suppress(Exception):
            client.close()


def _duration_seconds(value: Any, default: float) -> float:
    """Parse the Go-style durations the settings UI stores ("15s", "10ms")."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    if not text:
        return default
    for suffix, mult in (("ms", 0.001), ("s", 1.0), ("m", 60.0), ("h", 3600.0)):
        if text.endswith(suffix):
            try:
                return float(text[: -len(suffix)]) * mult
            except ValueError:
                return default
    try:
        return float(text)
    except ValueError:
        return default


_pool = _SmtpPool()


async def _deliver(msg: EmailMessage, block: dict[str, Any]) -> None:
    """Hand one built message to an SMTP server described by `block`."""
    # aiosmtplib.flatten_message() hardcodes email.policy.SMTP (78-char lines)
    # and ignores msg.policy, which would re-encode List-Unsubscribe as an
    # RFC 2047 encoded-word. Serialise here with _POLICY and hand over bytes,
    # which bypasses its flattening entirely.
    raw = msg.as_bytes()
    sender = parseaddr(msg["From"])[1]
    recipients = [parseaddr(a)[1] for a in (msg.get_all("To") or [])]

    retries = int(block.get("max_msg_retries") or 2)
    for attempt in range(retries + 1):
        try:
            async with _pool.acquire(block) as client:
                await client.sendmail(sender, recipients, raw)
            return
        except Exception:
            if attempt == retries:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


async def send_smtp_test(block: dict[str, Any], to: str) -> None:
    """Send a test email through an SMTP block straight from the settings form.

    The block is the one being edited in the UI, which may not be saved yet, so
    it is used directly instead of going through _smtp_block().
    """
    from app import tmpl as _tmpl

    # GET /api/settings masks secrets, so a block that came back from a page load
    # carries `••••…` in `password` rather than the real one. PUT /api/settings
    # un-masks via _restore_secrets(); this path has to do the same or every test
    # on a saved server authenticates with the mask and fails 535. Matches on uuid.
    settings._restore_secrets({"smtp": [block]}, settings.cache)

    html = _tmpl.render_system_email(
        "smtp-test", {"Settings": block, "Email": to}
    )
    msg = _build(
        to=to,
        subject=f"{settings.get('app.site_name') or 'listmonk'} SMTP test",
        html=html,
        text=_tmpl.html_to_text(html),
        from_email=(block.get("from_addresses") or [None])[0]
        or settings.get("app.from_email")
        or "",
    )
    await _deliver(msg, block)


def campaign_headers(camp: dict[str, Any], sub: dict[str, Any]) -> list[dict[str, str]]:
    """Per-message headers for a campaign send.

    X-Listmonk-Campaign/-Subscriber are what the bounce mailbox scanner reads to
    attribute a bounce back to a campaign and subscriber, so they must be on
    every outgoing campaign message.
    """
    hdrs: list[dict[str, str]] = list(camp.get("headers") or [])
    hdrs.append(
        {
            "X-Listmonk-Campaign": str(camp.get("uuid") or ""),
            "X-Listmonk-Subscriber": str(sub.get("uuid") or ""),
        }
    )

    # One-click unsubscribe (RFC 8058) — required by bulk senders like Gmail.
    if settings.get("privacy.unsubscribe_header", False):
        root = (settings.get("app.root_url") or "").rstrip("/")
        unsub = f"{root}/subscription/{camp.get('uuid')}/{sub.get('uuid')}"
        hdrs.append(
            {
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": f"<{unsub}>",
            }
        )
    return hdrs


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
        headers=campaign_headers(camp, sub),
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
                            headers=campaign_headers(camp, sub),
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
        # Pooled connections hold the old host/credentials, so drop them when
        # the SMTP settings change rather than sending through a stale server.
        settings.reload_hooks.append(_pool.close)
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
    await _pool.close()
