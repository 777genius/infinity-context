"""Clock port owned by the memory_scopes feature."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class MemoryScopeClockPort(Protocol):
    def now(self) -> datetime:
        """Return the current canonical write time."""


__all__ = ("MemoryScopeClockPort",)
