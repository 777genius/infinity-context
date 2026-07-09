"""Source reference value objects and de-duplication policy."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from infinity_context_core.domain.entity_types import MAX_SOURCE_REFS_PER_ITEM
from infinity_context_core.domain.errors import MemoryValidationError


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if not self.source_type:
            raise MemoryValidationError("SourceRef.source_type is required")
        if not self.source_id:
            raise MemoryValidationError("SourceRef.source_id is required")
        if self.char_start is not None and self.char_start < 0:
            raise MemoryValidationError("SourceRef.char_start must be non-negative")
        if self.char_end is not None and self.char_end < 0:
            raise MemoryValidationError("SourceRef.char_end must be non-negative")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise MemoryValidationError("SourceRef.char_end must be >= char_start")
        if self.page_number is not None and self.page_number < 1:
            raise MemoryValidationError("SourceRef.page_number must be positive")
        if self.time_start_ms is not None and self.time_start_ms < 0:
            raise MemoryValidationError("SourceRef.time_start_ms must be non-negative")
        if self.time_end_ms is not None and self.time_end_ms < 0:
            raise MemoryValidationError("SourceRef.time_end_ms must be non-negative")
        if (
            self.time_start_ms is not None
            and self.time_end_ms is not None
            and self.time_end_ms < self.time_start_ms
        ):
            raise MemoryValidationError("SourceRef.time_end_ms must be >= time_start_ms")
        if self.bbox is not None:
            if len(self.bbox) != 4 or not all(isfinite(float(value)) for value in self.bbox):
                raise MemoryValidationError("SourceRef.bbox must contain four finite numbers")
            if (
                any(float(value) < 0 for value in self.bbox)
                or float(self.bbox[2]) <= float(self.bbox[0])
                or float(self.bbox[3]) <= float(self.bbox[1])
            ):
                raise MemoryValidationError("SourceRef.bbox must be non-negative x1,y1,x2,y2")

def _source_ref_key(ref: SourceRef) -> tuple[object, ...]:
    return (
        ref.source_type,
        ref.source_id,
        ref.chunk_id,
        ref.char_start,
        ref.char_end,
        ref.quote_preview,
        ref.page_number,
        ref.time_start_ms,
        ref.time_end_ms,
        ref.bbox,
    )

def _unique_source_refs(
    values: tuple[SourceRef, ...],
    *,
    limit: int = MAX_SOURCE_REFS_PER_ITEM,
) -> tuple[SourceRef, ...]:
    seen: set[tuple[object, ...]] = set()
    refs: list[SourceRef] = []
    for ref in values:
        key = _source_ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
        if len(refs) >= limit:
            break
    return tuple(refs)
