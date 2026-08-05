"""Small shared helpers (response envelope, Go-style durations, paging)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Query


def ok(data: Any) -> dict[str, Any]:
    """The {data: ...} envelope every listmonk API response uses."""
    return {"data": data}


_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)")
_DUR_UNITS = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(s: str, default: float = 0.0) -> float:
    """Parse a Go duration string ("15m", "1h30m", "10ms") into seconds."""
    if not s:
        return default
    parts = _DUR_RE.findall(s)
    if not parts:
        return default
    return sum(float(n) * _DUR_UNITS[u] for n, u in parts)


class Pagination:
    """Query-param pagination matching the original (?page, ?per_page[=all])."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        per_page: str = Query(default="20"),
    ) -> None:
        self.page = page
        if per_page == "all":
            self.per_page = 0
        else:
            try:
                self.per_page = min(max(int(per_page), 1), 100)
            except ValueError:
                self.per_page = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        # 0 = no limit ("all"); queries use CASE WHEN $n=0 THEN NULL-style limits,
        # but for LIMIT params asyncpg wants None for no limit.
        return self.per_page

    def results(
        self, results: list[Any], total: int, query: str = ""
    ) -> dict[str, Any]:
        return {
            "results": results,
            "query": query,
            "total": total,
            "per_page": self.per_page if self.per_page else total,
            "page": self.page,
        }


def bad_request(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


def not_found(msg: str = "Not found") -> HTTPException:
    return HTTPException(status_code=404, detail=msg)
