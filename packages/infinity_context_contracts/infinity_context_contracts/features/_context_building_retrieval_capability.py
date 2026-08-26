"""Canonical capability contract and fingerprint policy for Retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .._json import JsonObject
from ._context_building_retrieval_json import (
    _normalize_context_retrieval_unicode,
    decode_context_retrieval_json,
)
from ._context_building_retrieval_validation import canonical_string_sort_key

CAPABILITY_ENDPOINT = "/v1/context/retrieve"
CAPABILITY_ATTRIBUTE_SCHEMA = "document-retrieval-projection.v1"
CAPABILITY_COVERAGE = "top_k_only"
CAPABILITY_CONTRACT_VERSION = "context-retrieval.v2"
CAPABILITY_RANKING_POLICY = "weighted_rrf_canonical_preferences.v1"
CAPABILITY_HARD_FILTER_SIGNALS = (
    "actor_keys",
    "category",
    "document_keys",
    "excluded_source_keys",
    "kinds",
    "relative_time_interval",
    "source_generations",
    "tags_all",
    "tags_any",
    "tags_none",
    "time_interval",
)
CAPABILITY_SOFT_PREFERENCE_SIGNALS = (
    "actor_preferences",
    "relative_time_interval",
    "source_preferences",
    "time_interval",
)


@dataclass(frozen=True, slots=True)
class RetrievalCapabilityBoundsDto:
    query_variants: tuple[int, int] = (1, 6)
    query_characters: tuple[int, int] = (1, 512)
    provider_lanes: tuple[int, int] = (1, 4)
    provider_rank: tuple[int, int] = (1, 1_000)
    source_generations: tuple[int, int] = (1, 100)
    candidate_limit: tuple[int, int] = (1, 1_000)
    result_limit: tuple[int, int] = (1, 50)
    neighbor_radius: tuple[int, int] = (0, 2)
    response_byte_limit: tuple[int, int] = (16_384, 1_048_576)
    deadline_ms: tuple[int, int] = (1, 2_000)
    weight_micros: tuple[int, int] = (100_000, 10_000_000)

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if not isinstance(value, Sequence) or isinstance(value, str | bytes):
                raise ValueError(f"capability.bounds.{name} must be an array")
            detached = tuple(value)
            if not all(isinstance(item, int) and not isinstance(item, bool) for item in detached):
                raise ValueError(f"capability.bounds.{name} must contain integers")
            object.__setattr__(self, name, detached)
        actual = self.to_dict()
        canonical = {
            "query_variants": [1, 6],
            "query_characters": [1, 512],
            "provider_lanes": [1, 4],
            "provider_rank": [1, 1000],
            "source_generations": [1, 100],
            "candidate_limit": [1, 1000],
            "result_limit": [1, 50],
            "neighbor_radius": [0, 2],
            "response_byte_limit": [16384, 1048576],
            "deadline_ms": [1, 2000],
            "weight_micros": [100000, 10000000],
        }
        if actual != canonical:
            raise ValueError("capability.bounds does not match Retrieval")

    def to_dict(self) -> JsonObject:
        return {
            "query_variants": list(self.query_variants),
            "query_characters": list(self.query_characters),
            "provider_lanes": list(self.provider_lanes),
            "provider_rank": list(self.provider_rank),
            "source_generations": list(self.source_generations),
            "candidate_limit": list(self.candidate_limit),
            "result_limit": list(self.result_limit),
            "neighbor_radius": list(self.neighbor_radius),
            "response_byte_limit": list(self.response_byte_limit),
            "deadline_ms": list(self.deadline_ms),
            "weight_micros": list(self.weight_micros),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalCapabilityBoundsDto:
        expected = cls().to_dict()
        if set(payload) != set(expected) or any(
            not isinstance(payload[name], Sequence)
            or isinstance(payload[name], str | bytes)
            or len(payload[name]) != 2  # type: ignore[arg-type]
            or any(
                not isinstance(item, int) or isinstance(item, bool)
                for item in payload[name]  # type: ignore[union-attr]
            )
            for name in expected
        ):
            raise ValueError("capability.bounds does not match Retrieval")
        if dict(payload) != expected:
            raise ValueError("capability.bounds does not match Retrieval")
        return cls()


@dataclass(frozen=True, slots=True)
class RetrievalProviderLaneCapabilityDto:
    provider_id: str
    required: bool
    healthy: bool
    weight_micros: int
    profile_qualified: bool

    def __post_init__(self) -> None:
        _opaque(self.provider_id, "capability.provider_lanes.provider_id")
        for name in ("required", "healthy", "profile_qualified"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"capability.provider_lanes.{name} must be boolean")
        if not isinstance(self.weight_micros, int) or isinstance(self.weight_micros, bool):
            raise ValueError("capability.provider_lanes.weight_micros must be an integer")
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("capability.provider_lanes.weight_micros is out of bounds")

    def to_dict(self) -> JsonObject:
        return {
            "provider_id": self.provider_id,
            "required": self.required,
            "healthy": self.healthy,
            "weight_micros": self.weight_micros,
            "profile_qualified": self.profile_qualified,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalProviderLaneCapabilityDto:
        _exact_keys(
            payload,
            {"provider_id", "required", "healthy", "weight_micros", "profile_qualified"},
            "capability.provider_lanes",
        )
        return cls(
            provider_id=_required(payload, "provider_id", str),
            required=_required(payload, "required", bool),
            healthy=_required(payload, "healthy", bool),
            weight_micros=_required(payload, "weight_micros", int),
            profile_qualified=_required(payload, "profile_qualified", bool),
        )


@dataclass(frozen=True, slots=True)
class RetrievalRankingParametersDto:
    rank_constant: int = 60
    weight_scale_micros: int = 1_000_000
    score_scale_picos: int = 1_000_000_000_000
    preference_scale_micros: int = 1_000_000
    max_preference_boost_micros: int = 250_000
    contribution_rounding: str = "round_half_even"
    preference_rounding: str = "floor"
    canonical_signal_match_policy: str = "canonical_exact_key_interval_overlap.v1"

    def __post_init__(self) -> None:
        if self.to_dict() != RetrievalRankingParametersDto._canonical():
            raise ValueError("capability.ranking_parameters does not match Retrieval")

    @staticmethod
    def _canonical() -> JsonObject:
        return {
            "rank_constant": 60,
            "weight_scale_micros": 1_000_000,
            "score_scale_picos": 1_000_000_000_000,
            "preference_scale_micros": 1_000_000,
            "max_preference_boost_micros": 250_000,
            "contribution_rounding": "round_half_even",
            "preference_rounding": "floor",
            "canonical_signal_match_policy": "canonical_exact_key_interval_overlap.v1",
        }

    def to_dict(self) -> JsonObject:
        return {name: getattr(self, name) for name in self.__slots__}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalRankingParametersDto:
        if dict(payload) != cls._canonical():
            raise ValueError("capability.ranking_parameters does not match Retrieval")
        return cls()


@dataclass(frozen=True, slots=True)
class RetrievalCapabilityDto:
    capability_fingerprint: str
    profile_id: str
    service_revision: str
    index_profile_digest: str
    provider_lanes: Sequence[RetrievalProviderLaneCapabilityDto]
    endpoint: str = CAPABILITY_ENDPOINT
    contract_version: str = CAPABILITY_CONTRACT_VERSION
    ranking_policy: str = CAPABILITY_RANKING_POLICY
    ranking_parameters: RetrievalRankingParametersDto = RetrievalRankingParametersDto()
    attribute_schema: str = CAPABILITY_ATTRIBUTE_SCHEMA
    coverage: str = CAPABILITY_COVERAGE
    supports_neighbors: bool = True
    bounds: RetrievalCapabilityBoundsDto = RetrievalCapabilityBoundsDto()
    hard_filter_signals: Sequence[str] = CAPABILITY_HARD_FILTER_SIGNALS
    soft_preference_signals: Sequence[str] = CAPABILITY_SOFT_PREFERENCE_SIGNALS
    required_provider_lanes: Sequence[str] = ()
    sdk_revision: str | None = None

    def __post_init__(self) -> None:
        if self.sdk_revision is None:
            object.__setattr__(self, "sdk_revision", self.service_revision)
        for name in (
            "capability_fingerprint",
            "profile_id",
            "service_revision",
            "sdk_revision",
            "index_profile_digest",
        ):
            _opaque(getattr(self, name), f"capability.{name}")
        _lower_hex(self.capability_fingerprint, 64, "capability.capability_fingerprint")
        _lower_hex(self.service_revision, 40, "capability.service_revision")
        _lower_hex(self.sdk_revision, 40, "capability.sdk_revision")
        _lower_hex(self.index_profile_digest, 64, "capability.index_profile_digest")
        if self.endpoint != CAPABILITY_ENDPOINT:
            raise ValueError("capability.endpoint is unsupported")
        if self.contract_version != CAPABILITY_CONTRACT_VERSION:
            raise ValueError("capability.contract_version is unsupported")
        if self.ranking_policy != CAPABILITY_RANKING_POLICY:
            raise ValueError("capability.ranking_policy is unsupported")
        if not isinstance(self.ranking_parameters, RetrievalRankingParametersDto):
            raise ValueError("capability.ranking_parameters has an invalid type")
        ranking_parameters = RetrievalRankingParametersDto.from_dict(
            self.ranking_parameters.to_dict()
        )
        object.__setattr__(self, "ranking_parameters", ranking_parameters)
        if self.attribute_schema != CAPABILITY_ATTRIBUTE_SCHEMA:
            raise ValueError("capability.attribute_schema is unsupported")
        if self.coverage != CAPABILITY_COVERAGE or not isinstance(self.supports_neighbors, bool):
            raise ValueError("capability coverage or neighbor support is unsupported")
        if not isinstance(self.bounds, RetrievalCapabilityBoundsDto):
            raise ValueError("capability.bounds has an invalid type")
        bounds = RetrievalCapabilityBoundsDto.from_dict(self.bounds.to_dict())
        lanes = tuple(
            RetrievalProviderLaneCapabilityDto(
                lane.provider_id,
                lane.required,
                lane.healthy,
                lane.weight_micros,
                lane.profile_qualified,
            )
            for lane in self.provider_lanes
            if isinstance(lane, RetrievalProviderLaneCapabilityDto)
        )
        if len(lanes) != len(tuple(self.provider_lanes)) or not 1 <= len(lanes) <= 4:
            raise ValueError("capability.provider_lanes must contain 1..4 lanes")
        if tuple(lane.provider_id for lane in lanes) != tuple(
            sorted({lane.provider_id for lane in lanes}, key=canonical_string_sort_key)
        ):
            raise ValueError("capability.provider_lanes must be sorted and unique")
        hard = tuple(self.hard_filter_signals)
        soft = tuple(self.soft_preference_signals)
        required = tuple(self.required_provider_lanes)
        if hard != CAPABILITY_HARD_FILTER_SIGNALS:
            raise ValueError("capability.hard_filter_signals is unsupported")
        if soft != CAPABILITY_SOFT_PREFERENCE_SIGNALS:
            raise ValueError("capability.soft_preference_signals is unsupported")
        actual_required = tuple(lane.provider_id for lane in lanes if lane.required)
        if required != actual_required or required != tuple(
            sorted(set(required), key=canonical_string_sort_key)
        ):
            raise ValueError("capability.required_provider_lanes does not match lanes")
        object.__setattr__(self, "provider_lanes", lanes)
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(self, "hard_filter_signals", hard)
        object.__setattr__(self, "soft_preference_signals", soft)
        object.__setattr__(self, "required_provider_lanes", required)
        if self.capability_fingerprint != capability_fingerprint(self.to_dict()):
            raise ValueError("capability.capability_fingerprint does not match payload")

    def to_dict(self) -> JsonObject:
        return {
            "endpoint": self.endpoint,
            "contract_version": self.contract_version,
            "ranking_policy": self.ranking_policy,
            "ranking_parameters": self.ranking_parameters.to_dict(),
            "capability_fingerprint": self.capability_fingerprint,
            "profile_id": self.profile_id,
            "service_revision": self.service_revision,
            "sdk_revision": self.sdk_revision,
            "attribute_schema": self.attribute_schema,
            "index_profile_digest": self.index_profile_digest,
            "coverage": self.coverage,
            "supports_neighbors": self.supports_neighbors,
            "bounds": self.bounds.to_dict(),
            "hard_filter_signals": list(self.hard_filter_signals),
            "soft_preference_signals": list(self.soft_preference_signals),
            "required_provider_lanes": list(self.required_provider_lanes),
            "provider_lanes": [lane.to_dict() for lane in self.provider_lanes],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalCapabilityDto:
        _exact_keys(payload, set(_CAPABILITY_KEYS), "capability")
        lanes = _object_sequence(payload.get("provider_lanes"), "capability.provider_lanes")
        bounds = payload.get("bounds")
        if not isinstance(bounds, Mapping):
            raise ValueError("capability.bounds must be an object")
        ranking_parameters = payload.get("ranking_parameters")
        if not isinstance(ranking_parameters, Mapping):
            raise ValueError("capability.ranking_parameters must be an object")
        return cls(
            capability_fingerprint=_required(payload, "capability_fingerprint", str),
            profile_id=_required(payload, "profile_id", str),
            service_revision=_required(payload, "service_revision", str),
            sdk_revision=_required(payload, "sdk_revision", str),
            index_profile_digest=_required(payload, "index_profile_digest", str),
            provider_lanes=tuple(
                RetrievalProviderLaneCapabilityDto.from_dict(item) for item in lanes
            ),
            endpoint=_required(payload, "endpoint", str),
            contract_version=_required(payload, "contract_version", str),
            ranking_policy=_required(payload, "ranking_policy", str),
            ranking_parameters=RetrievalRankingParametersDto.from_dict(ranking_parameters),
            attribute_schema=_required(payload, "attribute_schema", str),
            coverage=_required(payload, "coverage", str),
            supports_neighbors=_required(payload, "supports_neighbors", bool),
            bounds=RetrievalCapabilityBoundsDto.from_dict(bounds),
            hard_filter_signals=_strings(payload, "hard_filter_signals"),
            soft_preference_signals=_strings(payload, "soft_preference_signals"),
            required_provider_lanes=_strings(payload, "required_provider_lanes"),
        )


_CAPABILITY_KEYS = (
    "endpoint",
    "contract_version",
    "ranking_policy",
    "ranking_parameters",
    "capability_fingerprint",
    "profile_id",
    "service_revision",
    "sdk_revision",
    "attribute_schema",
    "index_profile_digest",
    "coverage",
    "supports_neighbors",
    "bounds",
    "hard_filter_signals",
    "soft_preference_signals",
    "required_provider_lanes",
    "provider_lanes",
)


def capability_fingerprint(payload: Mapping[str, object]) -> str:
    normalized = _normalize_context_retrieval_unicode(payload)
    if not isinstance(normalized, Mapping):
        raise ValueError("capability fingerprint input must be an object")
    canonical = dict(normalized)
    canonical.pop("capability_fingerprint", None)
    _reject_noncanonical_numbers(canonical, "capability")
    encoded = json.dumps(
        _canonical_json_order(canonical),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def decode_retrieval_capability(raw: bytes) -> RetrievalCapabilityDto:
    return RetrievalCapabilityDto.from_dict(decode_context_retrieval_json(raw))


def _canonical_json_order(value: object) -> object:
    """Recursively order JSON object keys by their UTF-8 byte sequences."""

    if isinstance(value, Mapping):
        return {
            key: _canonical_json_order(value[key])
            for key in sorted(value, key=canonical_string_sort_key)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_canonical_json_order(item) for item in value]
    return value


def _reject_noncanonical_numbers(value: object, path: str) -> None:
    """Fingerprint wire permits integers only; fractional weights use fixed micros."""

    if isinstance(value, float):
        raise ValueError(f"{path} contains a noncanonical floating-point number")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_noncanonical_numbers(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, nested in enumerate(value):
            _reject_noncanonical_numbers(nested, f"{path}.{index}")


def _exact_keys(payload: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{path} fields do not match the canonical contract")


def _required(payload: Mapping[str, object], name: str, kind: type):
    value = payload.get(name)
    if not isinstance(value, kind):
        raise ValueError(f"capability.{name} has an invalid type")
    return value


def _number(value: object, path: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{path} must be numeric")
    return float(value)


def _strings(payload: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"capability.{name} must be an array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"capability.{name} contains an invalid value")
    return tuple(value)


def _object_sequence(value: object, path: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{path} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{path} contains an invalid value")
    return tuple(value)  # type: ignore[return-value]


def _opaque(value: object, path: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{path} must be a normalized non-blank string")
    if len(value) > 256:
        raise ValueError(f"{path} exceeds 256 characters")
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"{path} contains invalid Unicode or control characters")


def _lower_hex(value: str, length: int, path: str) -> None:
    if len(value) != length or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{path} must be {length} lowercase hexadecimal characters")


__all__ = (
    "CAPABILITY_ATTRIBUTE_SCHEMA",
    "CAPABILITY_CONTRACT_VERSION",
    "CAPABILITY_COVERAGE",
    "CAPABILITY_ENDPOINT",
    "CAPABILITY_HARD_FILTER_SIGNALS",
    "CAPABILITY_RANKING_POLICY",
    "CAPABILITY_SOFT_PREFERENCE_SIGNALS",
    "RetrievalCapabilityBoundsDto",
    "RetrievalCapabilityDto",
    "RetrievalProviderLaneCapabilityDto",
    "RetrievalRankingParametersDto",
    "capability_fingerprint",
    "decode_retrieval_capability",
)
