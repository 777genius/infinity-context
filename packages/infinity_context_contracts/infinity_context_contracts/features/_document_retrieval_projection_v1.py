"""Strict public DTO for the generic document Retrieval V2 projection seam."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .._json import JsonObject
from ._context_building_retrieval_v2_json import decode_context_retrieval_v2_json

DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1 = "document-retrieval-projection.v1"
_PROJECTION_FIELDS = {
    "schema_version",
    "locator",
    "source_key",
    "projection_generation",
    "sequence_ordinal",
    "actor_keys",
    "time_interval",
    "relative_time_interval",
    "kind",
    "category",
    "tags",
}


def _utf8_sort_key(value: str) -> bytes:
    return value.encode("utf-8")


def decode_document_retrieval_projection_v1(
    raw: bytes,
) -> DocumentRetrievalProjectionV1Dto:
    return DocumentRetrievalProjectionV1Dto.from_dict(decode_context_retrieval_v2_json(raw))


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionTimeIntervalV1Dto:
    start_at: str
    end_at: str

    def __post_init__(self) -> None:
        start = _utc(self.start_at, "retrieval_projection.time_interval.start_at")
        end = _utc(self.end_at, "retrieval_projection.time_interval.end_at")
        if start > end:
            raise ValueError("retrieval_projection.time_interval must be ordered")

    def to_dict(self) -> JsonObject:
        return {"start_at": self.start_at, "end_at": self.end_at}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> DocumentRetrievalProjectionTimeIntervalV1Dto:
        if set(payload) != {"start_at", "end_at"}:
            raise ValueError("retrieval_projection.time_interval fields are invalid")
        return cls(
            _string(payload, "start_at", "retrieval_projection.time_interval"),
            _string(payload, "end_at", "retrieval_projection.time_interval"),
        )


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionRelativeTimeIntervalV1Dto:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    f"retrieval_projection.relative_time_interval.{name} must be an integer"
                )
            if not 0 <= value <= 9_007_199_254_740_991:
                raise ValueError(
                    f"retrieval_projection.relative_time_interval.{name} is out of bounds"
                )
        if self.start_ms > self.end_ms:
            raise ValueError("retrieval_projection.relative_time_interval must be ordered")

    def to_dict(self) -> JsonObject:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> DocumentRetrievalProjectionRelativeTimeIntervalV1Dto:
        if set(payload) != {"start_ms", "end_ms"}:
            raise ValueError("retrieval_projection.relative_time_interval fields are invalid")
        return cls(_integer(payload, "start_ms"), _integer(payload, "end_ms"))


@dataclass(frozen=True, slots=True)
class DocumentRetrievalProjectionV1Dto:
    locator: str
    source_key: str
    projection_generation: str
    sequence_ordinal: int
    actor_keys: Sequence[str]
    time_interval: DocumentRetrievalProjectionTimeIntervalV1Dto | None
    kind: str
    category: str
    tags: Sequence[str]
    relative_time_interval: DocumentRetrievalProjectionRelativeTimeIntervalV1Dto | None = None
    schema_version: str = DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema_version != DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1:
            raise ValueError("retrieval_projection.schema_version is caller-invalid")
        for name in ("locator", "source_key", "projection_generation", "kind", "category"):
            _opaque(getattr(self, name), f"retrieval_projection.{name}")
        if not isinstance(self.sequence_ordinal, int) or isinstance(self.sequence_ordinal, bool):
            raise ValueError("retrieval_projection.sequence_ordinal must be an integer")
        if not 0 <= self.sequence_ordinal <= 2_147_483_647:
            raise ValueError("retrieval_projection.sequence_ordinal is out of bounds")
        actors = _sorted_unique(self.actor_keys, "retrieval_projection.actor_keys")
        tags = _sorted_unique(self.tags, "retrieval_projection.tags")
        if self.time_interval is not None and not isinstance(
            self.time_interval, DocumentRetrievalProjectionTimeIntervalV1Dto
        ):
            raise ValueError("retrieval_projection.time_interval has an invalid type")
        if self.relative_time_interval is not None and not isinstance(
            self.relative_time_interval,
            DocumentRetrievalProjectionRelativeTimeIntervalV1Dto,
        ):
            raise ValueError("retrieval_projection.relative_time_interval has an invalid type")
        interval = (
            None
            if self.time_interval is None
            else DocumentRetrievalProjectionTimeIntervalV1Dto(
                self.time_interval.start_at, self.time_interval.end_at
            )
        )
        object.__setattr__(self, "actor_keys", actors)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "time_interval", interval)
        relative = (
            None
            if self.relative_time_interval is None
            else DocumentRetrievalProjectionRelativeTimeIntervalV1Dto(
                self.relative_time_interval.start_ms, self.relative_time_interval.end_ms
            )
        )
        object.__setattr__(self, "relative_time_interval", relative)

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "locator": self.locator,
            "source_key": self.source_key,
            "projection_generation": self.projection_generation,
            "sequence_ordinal": self.sequence_ordinal,
            "actor_keys": list(self.actor_keys),
            "time_interval": (None if self.time_interval is None else self.time_interval.to_dict()),
            "relative_time_interval": (
                None
                if self.relative_time_interval is None
                else self.relative_time_interval.to_dict()
            ),
            "kind": self.kind,
            "category": self.category,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DocumentRetrievalProjectionV1Dto:
        if set(payload) != _PROJECTION_FIELDS:
            raise ValueError("retrieval_projection must contain exactly the canonical fields")
        schema_version = _string(payload, "schema_version", "retrieval_projection")
        if schema_version != DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1:
            raise ValueError("retrieval_projection.schema_version is caller-invalid")
        interval_payload = payload.get("time_interval")
        if interval_payload is not None and not isinstance(interval_payload, Mapping):
            raise ValueError("retrieval_projection.time_interval must be an object or null")
        relative_payload = payload.get("relative_time_interval")
        if relative_payload is not None and not isinstance(relative_payload, Mapping):
            raise ValueError(
                "retrieval_projection.relative_time_interval must be an object or null"
            )
        return cls(
            locator=_string(payload, "locator", "retrieval_projection"),
            source_key=_string(payload, "source_key", "retrieval_projection"),
            projection_generation=_string(payload, "projection_generation", "retrieval_projection"),
            sequence_ordinal=_integer(payload, "sequence_ordinal"),
            actor_keys=_strings(payload, "actor_keys"),
            time_interval=(
                None
                if interval_payload is None
                else DocumentRetrievalProjectionTimeIntervalV1Dto.from_dict(interval_payload)
            ),
            relative_time_interval=(
                None
                if relative_payload is None
                else DocumentRetrievalProjectionRelativeTimeIntervalV1Dto.from_dict(
                    relative_payload
                )
            ),
            kind=_string(payload, "kind", "retrieval_projection"),
            category=_string(payload, "category", "retrieval_projection"),
            tags=_strings(payload, "tags"),
            schema_version=schema_version,
        )


def _opaque(value: object, path: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{path} must be a normalized non-blank string")
    if len(value) > 256:
        raise ValueError(f"{path} exceeds 256 code points")
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"{path} contains invalid Unicode or control characters")


def _string(payload: Mapping[str, object], name: str, path: str) -> str:
    value = payload.get(name)
    _opaque(value, f"{path}.{name}")
    return value  # type: ignore[return-value]


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"retrieval_projection.{name} must be an integer")
    return value


def _strings(payload: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"retrieval_projection.{name} must be an array")
    return _sorted_unique(value, f"retrieval_projection.{name}")


def _sorted_unique(values: object, path: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        raise ValueError(f"{path} must be an array")
    result = tuple(values)
    if not all(isinstance(item, str) for item in result):
        raise ValueError(f"{path} contains an invalid value")
    for item in result:
        _opaque(item, path)
    if len(result) > 100 or result != tuple(sorted(set(result), key=_utf8_sort_key)):
        raise ValueError(f"{path} must be sorted, unique, and contain at most 100 entries")
    return result


def _utc(value: str, path: str) -> datetime:
    _opaque(value, path)
    if (
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
            value,
        )
        is None
    ):
        raise ValueError(f"{path} must be RFC3339 UTC using Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise ValueError(f"{path} must be RFC3339 UTC using Z") from error
    if parsed.tzinfo != UTC:
        raise ValueError(f"{path} must be RFC3339 UTC using Z")
    return parsed


__all__ = (
    "DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1",
    "DocumentRetrievalProjectionTimeIntervalV1Dto",
    "DocumentRetrievalProjectionRelativeTimeIntervalV1Dto",
    "DocumentRetrievalProjectionV1Dto",
    "decode_document_retrieval_projection_v1",
)
