"""Generic caller-owned projection descriptor for document Retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from infinity_context_core.features.document_ingestion.domain.errors import (
    DocumentProjectionInvalidError,
)

DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1 = "document-retrieval-projection.v1"


def _utf8_sort_key(value: str) -> bytes:
    return value.encode("utf-8")


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionTimeIntervalV1:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        for name in ("start_at", "end_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise DocumentProjectionInvalidError(f"{name} must be timezone-aware")
            if value.utcoffset() != UTC.utcoffset(value):
                raise DocumentProjectionInvalidError(f"{name} must be UTC")
        if self.start_at > self.end_at:
            raise DocumentProjectionInvalidError("projection time interval must be ordered")


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionRelativeTimeIntervalV1:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise DocumentProjectionInvalidError(f"{name} must be an integer")
            if not 0 <= value <= 9_007_199_254_740_991:
                raise DocumentProjectionInvalidError(f"{name} is out of bounds")
        if self.start_ms > self.end_ms:
            raise DocumentProjectionInvalidError("relative projection interval must be ordered")


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionV1:
    locator: str
    source_key: str
    projection_generation: str
    sequence_ordinal: int
    actor_keys: tuple[str, ...]
    time_interval: DocumentRetrievalProjectionTimeIntervalV1 | None
    kind: str
    category: str
    tags: tuple[str, ...]
    relative_time_interval: DocumentRetrievalProjectionRelativeTimeIntervalV1 | None = None
    schema_version: str = DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema_version != DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1:
            raise DocumentProjectionInvalidError("projection schema_version is unsupported")
        for name in ("locator", "source_key", "projection_generation", "kind", "category"):
            _opaque(getattr(self, name), name)
        if not isinstance(self.sequence_ordinal, int) or isinstance(self.sequence_ordinal, bool):
            raise DocumentProjectionInvalidError("sequence_ordinal must be an integer")
        if not 0 <= self.sequence_ordinal <= 2_147_483_647:
            raise DocumentProjectionInvalidError("sequence_ordinal is out of bounds")
        actors = _ordered_values(self.actor_keys, "actor_keys")
        tags = _ordered_values(self.tags, "tags")
        if self.time_interval is not None and not isinstance(
            self.time_interval, DocumentRetrievalProjectionTimeIntervalV1
        ):
            raise DocumentProjectionInvalidError("time_interval has an invalid type")
        if self.relative_time_interval is not None and not isinstance(
            self.relative_time_interval, DocumentRetrievalProjectionRelativeTimeIntervalV1
        ):
            raise DocumentProjectionInvalidError("relative_time_interval has an invalid type")
        interval = (
            None
            if self.time_interval is None
            else DocumentRetrievalProjectionTimeIntervalV1(
                self.time_interval.start_at, self.time_interval.end_at
            )
        )
        object.__setattr__(self, "actor_keys", actors)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "time_interval", interval)
        relative = (
            None
            if self.relative_time_interval is None
            else DocumentRetrievalProjectionRelativeTimeIntervalV1(
                self.relative_time_interval.start_ms, self.relative_time_interval.end_ms
            )
        )
        object.__setattr__(self, "relative_time_interval", relative)


def copy_document_retrieval_projection(
    value: DocumentRetrievalProjectionV1,
) -> DocumentRetrievalProjectionV1:
    if not isinstance(value, DocumentRetrievalProjectionV1):
        raise DocumentProjectionInvalidError("retrieval projection has an invalid type")
    return DocumentRetrievalProjectionV1(
        locator=value.locator,
        source_key=value.source_key,
        projection_generation=value.projection_generation,
        sequence_ordinal=value.sequence_ordinal,
        actor_keys=tuple(value.actor_keys),
        time_interval=(
            None
            if value.time_interval is None
            else DocumentRetrievalProjectionTimeIntervalV1(
                value.time_interval.start_at, value.time_interval.end_at
            )
        ),
        relative_time_interval=(
            None
            if value.relative_time_interval is None
            else DocumentRetrievalProjectionRelativeTimeIntervalV1(
                value.relative_time_interval.start_ms,
                value.relative_time_interval.end_ms,
            )
        ),
        kind=value.kind,
        category=value.category,
        tags=tuple(value.tags),
        schema_version=value.schema_version,
    )


def _opaque(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DocumentProjectionInvalidError(f"{name} must be normalized and non-blank")
    if len(value) > 256:
        raise DocumentProjectionInvalidError(f"{name} exceeds 256 code points")
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise DocumentProjectionInvalidError(f"{name} contains invalid Unicode or controls")


def _ordered_values(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, str | bytes):
        raise DocumentProjectionInvalidError(f"{name} must be a collection")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise DocumentProjectionInvalidError(f"{name} must be a collection") from error
    if len(result) > 100 or not all(isinstance(item, str) for item in result):
        raise DocumentProjectionInvalidError(f"{name} has invalid entries")
    for item in result:
        _opaque(item, name)
    if result != tuple(sorted(set(result), key=_utf8_sort_key)):
        raise DocumentProjectionInvalidError(f"{name} must be sorted and unique")
    return result


__all__ = (
    "DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1",
    "DocumentRetrievalProjectionTimeIntervalV1",
    "DocumentRetrievalProjectionRelativeTimeIntervalV1",
    "DocumentRetrievalProjectionV1",
    "copy_document_retrieval_projection",
)
