"""In-memory log ring buffer and error event bus — port of internal/buflog
and internal/events.

A single logging.Handler feeds both:
  * `lines()` backs GET /api/logs (the admin Logs page).
  * error records are fanned out to SSE subscribers on GET /api/events.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections import deque
from typing import Any

MAX_LINES = 1000
# Bounded so a slow SSE client can never grow memory without limit.
SUB_QUEUE_SIZE = 100

_lines: deque[str] = deque(maxlen=MAX_LINES)
_lock = threading.Lock()

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_loop: asyncio.AbstractEventLoop | None = None


class _BufHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # pragma: no cover - formatting must never crash logging
            return

        with _lock:
            _lines.append(line)

        # Mirror errors to the live event stream, like events.ErrWriter().
        if record.levelno >= logging.ERROR:
            _publish({"type": "error", "message": line})


def _publish(event: dict[str, Any]) -> None:
    """Fan an event out to SSE subscribers. Safe to call from any thread."""
    if _loop is None or not _subscribers:
        return

    def deliver() -> None:
        for q in list(_subscribers):
            # Drop for this subscriber rather than blocking the logger.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    # RuntimeError = loop already closed (shutdown).
    with contextlib.suppress(RuntimeError):
        _loop.call_soon_threadsafe(deliver)


def lines() -> list[str]:
    with _lock:
        return list(_lines)


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUB_QUEUE_SIZE)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    _subscribers.discard(q)


def install() -> None:
    """Attach the buffer handler to the root logger. Idempotent."""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None

    root = logging.getLogger()
    if any(isinstance(h, _BufHandler) for h in root.handlers):
        return

    h = _BufHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
