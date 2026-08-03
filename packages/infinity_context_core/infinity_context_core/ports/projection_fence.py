"""Lifecycle fence for external derived projection writes."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProjectionFencePermit:
    """Decision held stable for the duration of a projection mutation."""

    allow_upsert: bool

    def __post_init__(self) -> None:
        if type(self.allow_upsert) is not bool:
            raise ValueError("allow_upsert must be bool")


class ProjectionFencePort(Protocol):
    """Serialize one space's projection upserts with canonical cleanup."""

    def hold(self, space_id: str) -> AbstractAsyncContextManager[ProjectionFencePermit]: ...


__all__ = ("ProjectionFencePermit", "ProjectionFencePort")
