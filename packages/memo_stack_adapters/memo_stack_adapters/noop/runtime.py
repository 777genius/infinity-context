"""Small runtime adapters that satisfy core ports."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class UuidIdGenerator:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    def projection_id(self, adapter: str, aggregate_type: str, aggregate_id: str) -> str:
        raw = f"{adapter}:{aggregate_type}:{aggregate_id}"
        return "proj_" + sha256(raw.encode("utf-8")).hexdigest()[:24]
