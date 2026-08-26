"""Feature-owned filter and time-coordinate policy for locator Retrieval V2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.context_building.domain.retrieval_v2_capability import (
    canonical_string_sort_key_v2,
)

MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
MIN_PREFERENCE_WEIGHT_MICROS_V2 = 100_000
MAX_PREFERENCE_WEIGHT_MICROS_V2 = 10_000_000
PREFERENCE_SCORE_SCALE_V2 = 1_000_000
MAX_PREFERENCE_BOOST_MICROS_V2 = 250_000


@dataclass(frozen=True, slots=True)
class LocatorTimeIntervalV2:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.start_at, datetime) or not isinstance(self.end_at, datetime):
            raise ValueError("Locator time interval values must be datetimes")
        for name, value in (("start_at", self.start_at), ("end_at", self.end_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Locator {name} must be timezone-aware")
        if self.start_at > self.end_at:
            raise ValueError("Locator time interval start_at cannot follow end_at")

    def overlaps(self, start_at: datetime | None, end_at: datetime | None) -> bool:
        return (
            start_at is not None
            and end_at is not None
            and start_at <= self.end_at
            and end_at >= self.start_at
        )


@dataclass(frozen=True, slots=True)
class LocatorRelativeTimeIntervalV2:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Locator relative {name} must be an integer")
            if not 0 <= value <= MAX_SAFE_JSON_INTEGER:
                raise ValueError(f"Locator relative {name} is out of bounds")
        if self.start_ms > self.end_ms:
            raise ValueError("Locator relative start_ms cannot follow end_ms")

    def overlaps(self, start_ms: int | None, end_ms: int | None) -> bool:
        return (
            start_ms is not None
            and end_ms is not None
            and start_ms <= self.end_ms
            and end_ms >= self.start_ms
        )


@dataclass(frozen=True, slots=True, order=True)
class LocatorSourceGenerationV2:
    source_key: str
    projection_generation: str

    def __post_init__(self) -> None:
        _opaque("source_key", self.source_key)
        _opaque("projection_generation", self.projection_generation)


@dataclass(frozen=True, slots=True)
class LocatorWeightedKeyV2:
    key: str
    weight_micros: int = 1_000_000

    def __post_init__(self) -> None:
        _opaque("preference key", self.key)
        _weight_micros("preference weight_micros", self.weight_micros)


@dataclass(frozen=True, slots=True)
class LocatorPreferenceEvidenceV2:
    """Exact bounded evidence computed only from canonically hydrated coordinates."""

    score_micros: int
    boost_micros: int
    source_requested_weight_micros: int = 0
    source_matched_weight_micros: int = 0
    actor_requested_weight_micros: int = 0
    actor_matched_weight_micros: int = 0
    time_requested_weight_micros: int = 0
    time_matched_weight_micros: int = 0

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Locator preference {name} must be an integer")
        if not 0 <= self.score_micros <= PREFERENCE_SCORE_SCALE_V2:
            raise ValueError("Locator preference score_micros is out of bounds")
        expected = self.score_micros * MAX_PREFERENCE_BOOST_MICROS_V2 // PREFERENCE_SCORE_SCALE_V2
        if self.boost_micros != expected:
            raise ValueError("Locator preference boost_micros must reconstruct")
        requested = (
            self.source_requested_weight_micros
            + self.actor_requested_weight_micros
            + self.time_requested_weight_micros
        )
        matched = (
            self.source_matched_weight_micros
            + self.actor_matched_weight_micros
            + self.time_matched_weight_micros
        )
        dimension_weights = self.__slots__[2:]
        dimension_swap = any(
            getattr(self, matched_name) > getattr(self, requested_name)
            for requested_name, matched_name in zip(
                dimension_weights[::2], dimension_weights[1::2], strict=True
            )
        )
        if (
            any(getattr(self, name) < 0 for name in dimension_weights)
            or matched > requested
            or dimension_swap
        ):
            raise ValueError("Locator preference dimension evidence is out of bounds")
        expected_score = 0 if requested == 0 else matched * PREFERENCE_SCORE_SCALE_V2 // requested
        if self.score_micros != expected_score:
            raise ValueError("Locator preference score_micros must reconstruct")


@dataclass(frozen=True, slots=True)
class LocatorHardFiltersV2:
    source_generations: tuple[LocatorSourceGenerationV2, ...]
    excluded_source_keys: tuple[str, ...] = ()
    document_keys: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    category: str | None = None
    tags_any: tuple[str, ...] = ()
    tags_all: tuple[str, ...] = ()
    tags_none: tuple[str, ...] = ()
    actor_keys: tuple[str, ...] = ()
    time_interval: LocatorTimeIntervalV2 | None = None
    relative_time_interval: LocatorRelativeTimeIntervalV2 | None = None

    def __post_init__(self) -> None:
        raw_pairs = _tuple(self.source_generations, LocatorSourceGenerationV2, "source_generations")
        pairs = tuple(
            LocatorSourceGenerationV2(item.source_key, item.projection_generation)
            for item in raw_pairs
        )
        if not 1 <= len(pairs) <= 100 or pairs != tuple(
            sorted(
                pairs,
                key=lambda item: (
                    canonical_string_sort_key_v2(item.source_key),
                    canonical_string_sort_key_v2(item.projection_generation),
                ),
            )
        ):
            raise ValueError("Locator source_generations must be sorted and contain 1..100 pairs")
        sources = tuple(item.source_key for item in pairs)
        if len(set(sources)) != len(sources):
            raise ValueError("Locator source_generations must use unique source keys")
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
            values = _tuple(getattr(self, name), str, name)
            _unique_opaque(name, values)
            object.__setattr__(self, name, values)
        _interval_types(self.time_interval, self.relative_time_interval, "filters")
        if self.time_interval is not None and self.relative_time_interval is not None:
            raise ValueError("Locator hard filters may select at most one time coordinate")
        if self.category is not None:
            _opaque("category", self.category)
        if set(sources) & set(self.excluded_source_keys):
            raise ValueError("Locator source filters cannot include and exclude a key")
        if set(self.tags_all) & set(self.tags_none):
            raise ValueError("Locator tag filters cannot require and exclude the same tag")


@dataclass(frozen=True, slots=True)
class LocatorSoftPreferencesV2:
    source_preferences: tuple[LocatorWeightedKeyV2, ...] = ()
    actor_preferences: tuple[LocatorWeightedKeyV2, ...] = ()
    time_interval: LocatorTimeIntervalV2 | None = None
    relative_time_interval: LocatorRelativeTimeIntervalV2 | None = None
    time_weight_micros: int | None = None

    def __post_init__(self) -> None:
        for name in ("source_preferences", "actor_preferences"):
            raw = _tuple(getattr(self, name), LocatorWeightedKeyV2, name)
            values = tuple(LocatorWeightedKeyV2(item.key, item.weight_micros) for item in raw)
            keys = tuple(item.key for item in values)
            if len(keys) > 100 or keys != tuple(
                sorted(set(keys), key=canonical_string_sort_key_v2)
            ):
                raise ValueError(
                    f"Locator {name} must contain at most 100 UTF-8 sorted unique keys"
                )
            object.__setattr__(self, name, values)
        _interval_types(self.time_interval, self.relative_time_interval, "preferences")
        coordinates = sum(
            item is not None for item in (self.time_interval, self.relative_time_interval)
        )
        if (coordinates == 0) != (self.time_weight_micros is None) or coordinates > 1:
            raise ValueError("Locator time preference requires weight and exactly one coordinate")
        if self.time_weight_micros is not None:
            _weight_micros("time preference weight_micros", self.time_weight_micros)


def preference_evidence_v2(
    preferences: LocatorSoftPreferencesV2,
    *,
    source_key: str,
    actor_keys: tuple[str, ...],
    start_at: datetime | None,
    end_at: datetime | None,
    relative_start_ms: int | None,
    relative_end_ms: int | None,
) -> LocatorPreferenceEvidenceV2:
    """Return floor-normalized match evidence and its exact 25% maximum boost."""

    source_total = sum(item.weight_micros for item in preferences.source_preferences)
    actor_total = sum(item.weight_micros for item in preferences.actor_preferences)
    time_total = preferences.time_weight_micros or 0
    source_matched = sum(
        item.weight_micros for item in preferences.source_preferences if item.key == source_key
    )
    candidate_actors = set(actor_keys)
    actor_matched = sum(
        item.weight_micros for item in preferences.actor_preferences if item.key in candidate_actors
    )
    if preferences.time_interval is not None and preferences.time_interval.overlaps(
        start_at, end_at
    ):
        time_matched = time_total
    else:
        time_matched = 0
    if (
        preferences.relative_time_interval is not None
        and preferences.relative_time_interval.overlaps(relative_start_ms, relative_end_ms)
    ):
        time_matched = time_total

    total = source_total + actor_total + time_total
    matched = source_matched + actor_matched + time_matched
    score_micros = 0 if total == 0 else matched * PREFERENCE_SCORE_SCALE_V2 // total
    return LocatorPreferenceEvidenceV2(
        score_micros,
        score_micros * MAX_PREFERENCE_BOOST_MICROS_V2 // PREFERENCE_SCORE_SCALE_V2,
        source_total,
        source_matched,
        actor_total,
        actor_matched,
        time_total,
        time_matched,
    )


def _interval_types(
    absolute: LocatorTimeIntervalV2 | None,
    relative: LocatorRelativeTimeIntervalV2 | None,
    path: str,
) -> None:
    if absolute is not None and not isinstance(absolute, LocatorTimeIntervalV2):
        raise ValueError(f"Locator {path} absolute interval has an invalid type")
    if relative is not None and not isinstance(relative, LocatorRelativeTimeIntervalV2):
        raise ValueError(f"Locator {path} relative interval has an invalid type")


def _opaque(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
    ):
        raise ValueError(f"Locator {name} must be a bounded normalized string")
    if any(
        0xD800 <= ord(char) <= 0xDFFF or ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F
        for char in value
    ):
        raise ValueError(f"Locator {name} contains invalid Unicode or controls")


def _unique_opaque(name: str, values: tuple[str, ...]) -> None:
    for value in values:
        _opaque(name, value)
    if len(values) > 100 or values != tuple(sorted(set(values), key=canonical_string_sort_key_v2)):
        raise ValueError(f"Locator {name} must contain at most 100 UTF-8 sorted unique values")


def _weight_micros(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Locator {name} must be an integer")
    if not MIN_PREFERENCE_WEIGHT_MICROS_V2 <= value <= MAX_PREFERENCE_WEIGHT_MICROS_V2:
        raise ValueError(f"Locator {name} must be within 100000..10000000")


def _tuple(values: object, item_type: type, name: str) -> tuple:
    if isinstance(values, str | bytes):
        raise ValueError(f"Locator {name} must be a collection")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"Locator {name} must be a collection") from error
    if not all(isinstance(item, item_type) for item in result):
        raise ValueError(f"Locator {name} contains an invalid runtime type")
    return result


__all__ = (
    "MAX_SAFE_JSON_INTEGER",
    "MAX_PREFERENCE_BOOST_MICROS_V2",
    "MAX_PREFERENCE_WEIGHT_MICROS_V2",
    "MIN_PREFERENCE_WEIGHT_MICROS_V2",
    "PREFERENCE_SCORE_SCALE_V2",
    "LocatorHardFiltersV2",
    "LocatorPreferenceEvidenceV2",
    "LocatorRelativeTimeIntervalV2",
    "LocatorSoftPreferencesV2",
    "LocatorSourceGenerationV2",
    "LocatorTimeIntervalV2",
    "LocatorWeightedKeyV2",
    "preference_evidence_v2",
)
