"""Canonical filter, interval, and preference DTOs for Retrieval V2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, json_compatible
from ._context_building_retrieval_v2_validation import (
    canonical_string_sort_key,
    canonical_tuple,
    mapping,
    optional_string,
    parsed_datetime,
    reject_unknown,
    require_exact,
    sequence,
    string,
    string_sequence,
    validated_opaque,
    validated_string_values,
)

MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


@dataclass(frozen=True, slots=True)
class RetrievalV2TimeIntervalDto:
    start_at: str
    end_at: str

    def __post_init__(self) -> None:
        start = parsed_datetime(self.start_at, "time_interval.start_at")
        end = parsed_datetime(self.end_at, "time_interval.end_at")
        if start > end:
            raise ValueError("time_interval.start_at cannot follow end_at")

    def to_dict(self) -> JsonObject:
        return {"start_at": self.start_at, "end_at": self.end_at}


@dataclass(frozen=True, slots=True)
class RetrievalV2RelativeTimeIntervalDto:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"relative_time_interval.{name} must be an integer")
            if not 0 <= value <= MAX_SAFE_JSON_INTEGER:
                raise ValueError(f"relative_time_interval.{name} is out of bounds")
        if self.start_ms > self.end_ms:
            raise ValueError("relative_time_interval.start_ms cannot follow end_ms")

    def to_dict(self) -> JsonObject:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms}


@dataclass(frozen=True, slots=True, order=True)
class RetrievalV2SourceGenerationDto:
    source_key: str
    projection_generation: str

    def __post_init__(self) -> None:
        validated_opaque(self.source_key, "filters.source_generations.source_key")
        validated_opaque(
            self.projection_generation,
            "filters.source_generations.projection_generation",
        )

    def to_dict(self) -> JsonObject:
        return {
            "source_key": self.source_key,
            "projection_generation": self.projection_generation,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2WeightedKeyDto:
    key: str
    weight_micros: int = 1_000_000

    def __post_init__(self) -> None:
        validated_opaque(self.key, "preference.key")
        _bounded_weight_micros(self.weight_micros, "preference.weight_micros")

    def to_dict(self) -> JsonObject:
        return {"key": self.key, "weight_micros": self.weight_micros}


@dataclass(frozen=True, slots=True)
class RetrievalV2HardFiltersDto:
    source_generations: Sequence[RetrievalV2SourceGenerationDto]
    excluded_source_keys: Sequence[str] = field(default_factory=tuple)
    document_keys: Sequence[str] = field(default_factory=tuple)
    kinds: Sequence[str] = field(default_factory=tuple)
    category: str | None = None
    tags_any: Sequence[str] = field(default_factory=tuple)
    tags_all: Sequence[str] = field(default_factory=tuple)
    tags_none: Sequence[str] = field(default_factory=tuple)
    actor_keys: Sequence[str] = field(default_factory=tuple)
    time_interval: RetrievalV2TimeIntervalDto | None = None
    relative_time_interval: RetrievalV2RelativeTimeIntervalDto | None = None

    def __post_init__(self) -> None:
        raw_pairs = canonical_tuple(
            self.source_generations,
            RetrievalV2SourceGenerationDto,
            "filters.source_generations",
        )
        pairs = tuple(
            RetrievalV2SourceGenerationDto(item.source_key, item.projection_generation)
            for item in raw_pairs
        )
        if not 1 <= len(pairs) <= 100:
            raise ValueError("filters.source_generations must contain 1..100 entries")
        if pairs != tuple(
            sorted(
                pairs,
                key=lambda item: (
                    canonical_string_sort_key(item.source_key),
                    canonical_string_sort_key(item.projection_generation),
                ),
            )
        ):
            raise ValueError("filters.source_generations must be sorted ascending")
        sources = tuple(item.source_key for item in pairs)
        if len(set(sources)) != len(sources):
            raise ValueError("filters.source_generations must contain unique source keys")
        object.__setattr__(self, "source_generations", pairs)
        for name in (
            "excluded_source_keys",
            "document_keys",
            "kinds",
            "tags_any",
            "tags_all",
            "tags_none",
            "actor_keys",
        ):
            values = canonical_tuple(getattr(self, name), str, f"filters.{name}")
            validated_string_values(values, f"filters.{name}")
            object.__setattr__(self, name, values)
        if self.category is not None:
            validated_opaque(self.category, "filters.category")
        _validate_interval_types(self.time_interval, self.relative_time_interval, "filters")
        if self.time_interval is not None and self.relative_time_interval is not None:
            raise ValueError("filters may select at most one time coordinate")
        if set(sources) & set(self.excluded_source_keys):
            raise ValueError("filters source inclusion and exclusion overlap")
        if set(self.tags_all) & set(self.tags_none):
            raise ValueError("filters required and excluded tags overlap")

    def to_dict(self) -> JsonObject:
        return {
            "source_generations": [item.to_dict() for item in self.source_generations],
            "excluded_source_keys": json_compatible(self.excluded_source_keys),
            "document_keys": json_compatible(self.document_keys),
            "kinds": json_compatible(self.kinds),
            "category": self.category,
            "tags_any": json_compatible(self.tags_any),
            "tags_all": json_compatible(self.tags_all),
            "tags_none": json_compatible(self.tags_none),
            "actor_keys": json_compatible(self.actor_keys),
            "time_interval": json_compatible(self.time_interval),
            "relative_time_interval": json_compatible(self.relative_time_interval),
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2SoftPreferencesDto:
    source_preferences: Sequence[RetrievalV2WeightedKeyDto] = field(default_factory=tuple)
    actor_preferences: Sequence[RetrievalV2WeightedKeyDto] = field(default_factory=tuple)
    time_interval: RetrievalV2TimeIntervalDto | None = None
    relative_time_interval: RetrievalV2RelativeTimeIntervalDto | None = None
    time_weight_micros: int | None = None

    def __post_init__(self) -> None:
        for name in ("source_preferences", "actor_preferences"):
            raw = canonical_tuple(
                getattr(self, name), RetrievalV2WeightedKeyDto, f"soft_preferences.{name}"
            )
            values = tuple(RetrievalV2WeightedKeyDto(item.key, item.weight_micros) for item in raw)
            keys = tuple(item.key for item in values)
            if len(keys) > 100 or keys != tuple(sorted(set(keys), key=canonical_string_sort_key)):
                raise ValueError(
                    f"soft_preferences.{name} must contain at most 100 UTF-8 sorted unique keys"
                )
            object.__setattr__(self, name, values)
        _validate_interval_types(
            self.time_interval, self.relative_time_interval, "soft_preferences"
        )
        coordinates = sum(
            value is not None for value in (self.time_interval, self.relative_time_interval)
        )
        if (coordinates == 0) != (self.time_weight_micros is None) or coordinates > 1:
            raise ValueError(
                "soft_preferences requires time_weight_micros with exactly one time coordinate"
            )
        if self.time_weight_micros is not None:
            _bounded_weight_micros(self.time_weight_micros, "soft_preferences.time_weight_micros")

    def to_dict(self) -> JsonObject:
        return {
            "source_preferences": json_compatible(self.source_preferences),
            "actor_preferences": json_compatible(self.actor_preferences),
            "time_interval": json_compatible(self.time_interval),
            "relative_time_interval": json_compatible(self.relative_time_interval),
            "time_weight_micros": self.time_weight_micros,
        }


def parse_filters(payload: Mapping[str, object]) -> RetrievalV2HardFiltersDto:
    allowed = {
        "source_generations",
        "excluded_source_keys",
        "document_keys",
        "kinds",
        "category",
        "tags_any",
        "tags_all",
        "tags_none",
        "actor_keys",
        "time_interval",
        "relative_time_interval",
    }
    require_exact(payload, allowed, "filters")
    pairs_value = sequence(payload.get("source_generations"), "filters.source_generations")
    pairs = tuple(
        _parse_source_generation(mapping(value, f"filters.source_generations.{index}"), index)
        for index, value in enumerate(pairs_value)
    )
    return RetrievalV2HardFiltersDto(
        source_generations=pairs,
        excluded_source_keys=string_sequence(payload, "excluded_source_keys", "filters"),
        document_keys=string_sequence(payload, "document_keys", "filters"),
        kinds=string_sequence(payload, "kinds", "filters"),
        category=optional_string(payload, "category", "filters"),
        tags_any=string_sequence(payload, "tags_any", "filters"),
        tags_all=string_sequence(payload, "tags_all", "filters"),
        tags_none=string_sequence(payload, "tags_none", "filters"),
        actor_keys=string_sequence(payload, "actor_keys", "filters"),
        time_interval=parse_optional_time_interval(
            payload.get("time_interval"), "filters.time_interval"
        ),
        relative_time_interval=parse_optional_relative_interval(
            payload.get("relative_time_interval"), "filters.relative_time_interval"
        ),
    )


def parse_soft_preferences(payload: Mapping[str, object]) -> RetrievalV2SoftPreferencesDto:
    require_exact(
        payload,
        {
            "source_preferences",
            "actor_preferences",
            "time_interval",
            "relative_time_interval",
            "time_weight_micros",
        },
        "soft_preferences",
    )
    return RetrievalV2SoftPreferencesDto(
        source_preferences=_parse_weighted_keys(payload, "source_preferences"),
        actor_preferences=_parse_weighted_keys(payload, "actor_preferences"),
        time_interval=parse_optional_time_interval(
            payload.get("time_interval"), "soft_preferences.time_interval"
        ),
        relative_time_interval=parse_optional_relative_interval(
            payload.get("relative_time_interval"), "soft_preferences.relative_time_interval"
        ),
        time_weight_micros=_optional_integer(payload, "time_weight_micros", "soft_preferences"),
    )


def parse_optional_time_interval(value: object, path: str) -> RetrievalV2TimeIntervalDto | None:
    if value is None:
        return None
    payload = mapping(value, path)
    reject_unknown(payload, {"start_at", "end_at"}, path)
    if set(payload) != {"start_at", "end_at"}:
        raise ValueError(f"{path} requires start_at and end_at")
    return RetrievalV2TimeIntervalDto(
        string(payload, "start_at", path), string(payload, "end_at", path)
    )


def parse_optional_relative_interval(
    value: object, path: str
) -> RetrievalV2RelativeTimeIntervalDto | None:
    if value is None:
        return None
    payload = mapping(value, path)
    reject_unknown(payload, {"start_ms", "end_ms"}, path)
    if set(payload) != {"start_ms", "end_ms"}:
        raise ValueError(f"{path} requires start_ms and end_ms")
    return RetrievalV2RelativeTimeIntervalDto(
        _required_integer(payload, "start_ms", path),
        _required_integer(payload, "end_ms", path),
    )


def _parse_source_generation(
    payload: Mapping[str, object], index: int
) -> RetrievalV2SourceGenerationDto:
    path = f"filters.source_generations.{index}"
    if set(payload) != {"source_key", "projection_generation"}:
        raise ValueError(f"{path} fields do not match the canonical contract")
    return RetrievalV2SourceGenerationDto(
        string(payload, "source_key", path),
        string(payload, "projection_generation", path),
    )


def _parse_weighted_keys(
    payload: Mapping[str, object], name: str
) -> tuple[RetrievalV2WeightedKeyDto, ...]:
    values = sequence(payload.get(name, ()), f"soft_preferences.{name}")
    result = []
    for index, value in enumerate(values):
        path = f"soft_preferences.{name}.{index}"
        item = mapping(value, path)
        require_exact(item, {"key", "weight_micros"}, path)
        result.append(
            RetrievalV2WeightedKeyDto(
                string(item, "key", path),
                _required_integer(item, "weight_micros", path),
            )
        )
    return tuple(result)


def _required_integer(payload: Mapping[str, object], name: str, path: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{name} must be an integer")
    return value


def _optional_integer(payload: Mapping[str, object], name: str, path: str) -> int | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{name} must be an integer")
    return value


def _bounded_weight_micros(value: object, path: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path} must be an integer")
    if not 100_000 <= value <= 10_000_000:
        raise ValueError(f"{path} must be within 100000..10000000")


def _validate_interval_types(
    absolute: RetrievalV2TimeIntervalDto | None,
    relative: RetrievalV2RelativeTimeIntervalDto | None,
    path: str,
) -> None:
    if absolute is not None and not isinstance(absolute, RetrievalV2TimeIntervalDto):
        raise ValueError(f"{path}.time_interval has an invalid runtime type")
    if relative is not None and not isinstance(relative, RetrievalV2RelativeTimeIntervalDto):
        raise ValueError(f"{path}.relative_time_interval has an invalid runtime type")


__all__ = (
    "MAX_SAFE_JSON_INTEGER",
    "RetrievalV2HardFiltersDto",
    "RetrievalV2RelativeTimeIntervalDto",
    "RetrievalV2SoftPreferencesDto",
    "RetrievalV2SourceGenerationDto",
    "RetrievalV2TimeIntervalDto",
    "RetrievalV2WeightedKeyDto",
    "parse_filters",
    "parse_optional_relative_interval",
    "parse_optional_time_interval",
    "parse_soft_preferences",
)
