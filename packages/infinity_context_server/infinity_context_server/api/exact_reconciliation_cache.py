"""Request-local decoded JSON cache for exact reconciliation."""

from __future__ import annotations

from typing import Any

from fastapi import Request

_BODY_STATE_KEY = "exact_reconciliation_body"
_MISSING = object()


def cache_exact_reconciliation_json(request: Request, value: Any) -> None:
    """Cache decoded JSON, including valid non-object and null values."""

    setattr(request.state, _BODY_STATE_KEY, value)


def cached_exact_reconciliation_json(request: Request) -> tuple[bool, Any]:
    """Return whether the boundary cached JSON and the decoded value."""

    value = getattr(request.state, _BODY_STATE_KEY, _MISSING)
    return (False, None) if value is _MISSING else (True, value)


__all__ = (
    "cache_exact_reconciliation_json",
    "cached_exact_reconciliation_json",
)
