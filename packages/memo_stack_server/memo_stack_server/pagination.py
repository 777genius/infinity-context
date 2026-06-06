"""Opaque cursor helpers for public API pagination."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any

from memo_stack_core.domain.errors import MemoryValidationError


def encode_cursor(kind: str, **values: object) -> str:
    payload = {"v": 1, "kind": kind, **values}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, *, kind: str) -> dict[str, Any] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise MemoryValidationError("Invalid cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("kind") != kind:
        raise MemoryValidationError("Invalid cursor")
    return payload


def cursor_datetime(payload: dict[str, Any] | None, key: str) -> datetime | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not isinstance(value, str):
        raise MemoryValidationError("Invalid cursor")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise MemoryValidationError("Invalid cursor") from exc


def cursor_str(payload: dict[str, Any] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise MemoryValidationError("Invalid cursor")
    return value


def cursor_int(payload: dict[str, Any] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not isinstance(value, int):
        raise MemoryValidationError("Invalid cursor")
    return value
