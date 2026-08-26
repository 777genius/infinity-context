"""Internal implementation of versioned locator-only Retrieval V2 DTOs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from .._json import JsonObject, json_compatible
from ._context_building_retrieval_v2_filters import (
    RetrievalV2HardFiltersDto,
    RetrievalV2RelativeTimeIntervalDto,
    RetrievalV2SoftPreferencesDto,
    RetrievalV2SourceGenerationDto,
    RetrievalV2TimeIntervalDto,
    RetrievalV2WeightedKeyDto,
)
from ._context_building_retrieval_v2_filters import (
    parse_filters as _parse_filters,
)
from ._context_building_retrieval_v2_filters import (
    parse_soft_preferences as _parse_soft_preferences,
)
from ._context_building_retrieval_v2_validation import (
    bounded_weight as _bounded_weight,
)
from ._context_building_retrieval_v2_validation import (
    canonical_string_sort_key,
)
from ._context_building_retrieval_v2_validation import (
    canonical_tuple as _canonical_tuple,
)
from ._context_building_retrieval_v2_validation import (
    integer as _integer,
)
from ._context_building_retrieval_v2_validation import (
    mapping as _mapping,
)
from ._context_building_retrieval_v2_validation import (
    optional_string as _optional_string,
)
from ._context_building_retrieval_v2_validation import (
    require_exact as _require_exact,
)
from ._context_building_retrieval_v2_validation import (
    sequence as _sequence,
)
from ._context_building_retrieval_v2_validation import (
    string as _string,
)
from ._context_building_retrieval_v2_validation import (
    validated_integer as _validated_integer,
)
from ._context_building_retrieval_v2_validation import (
    validated_number as _validated_number,
)
from ._context_building_retrieval_v2_validation import (
    validated_opaque as _validated_opaque,
)
from ._context_building_retrieval_v2_validation import (
    validated_sha256 as _validated_sha256,
)

LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2 = "context-retrieval.v2"
LOCATOR_RETRIEVAL_RANKING_POLICY_V2 = "weighted_rrf_canonical_preferences.v1"
MIN_LOCATOR_RETRIEVAL_RESPONSE_BYTES_V2 = 16_384
_DEGRADATION_REASON_CODES = frozenset(
    {
        "capability_profile_mismatch",
        "neighbor_capability_unavailable",
        "optional_provider_failed",
        "optional_provider_unavailable",
        "optional_provider_unqualified",
        "response_byte_limit_exceeded",
    }
)


@dataclass(frozen=True, slots=True)
class RetrievalV2ScopeDto:
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _validated_opaque(self.space_id, "scope.space_id")
        _validated_opaque(self.memory_scope_id, "scope.memory_scope_id")
        if self.thread_id is not None:
            _validated_opaque(self.thread_id, "scope.thread_id")

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2QueryDto:
    query_id: str
    query: str
    weight_micros: int = 1_000_000

    def __post_init__(self) -> None:
        _validated_opaque(self.query_id, "queries.query_id", maximum=64)
        if not isinstance(self.query, str):
            raise ValueError("queries.query must be a string")
        if self.query != " ".join(self.query.split()) or not 1 <= len(self.query) <= 512:
            raise ValueError("queries.query must be normalized and contain 1..512 characters")
        _validated_opaque(self.query, "queries.query", maximum=512)
        _validated_integer(self.weight_micros, "queries.weight_micros")
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("queries.weight_micros must be within 100000..10000000")

    def to_dict(self) -> JsonObject:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "weight_micros": self.weight_micros,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2BoundsDto:
    candidate_limit: int = 150
    result_limit: int = 20
    neighbor_radius: int = 0
    response_byte_limit: int = 1_048_576
    deadline_ms: int = 2_000

    def __post_init__(self) -> None:
        for name in (
            "candidate_limit",
            "result_limit",
            "neighbor_radius",
            "response_byte_limit",
            "deadline_ms",
        ):
            _validated_integer(getattr(self, name), f"bounds.{name}")
        if not 1 <= self.candidate_limit <= 1_000:
            raise ValueError("bounds.candidate_limit must be within 1..1000")
        if not 1 <= self.result_limit <= 50 or self.result_limit > self.candidate_limit:
            raise ValueError(
                "bounds.result_limit must be within 1..50 and not exceed candidate_limit"
            )
        if not 0 <= self.neighbor_radius <= 2:
            raise ValueError("bounds.neighbor_radius must be within 0..2")
        if not MIN_LOCATOR_RETRIEVAL_RESPONSE_BYTES_V2 <= self.response_byte_limit <= 1_048_576:
            raise ValueError("bounds.response_byte_limit must be within 16384..1048576")
        if not 1 <= self.deadline_ms <= 2_000:
            raise ValueError("bounds.deadline_ms must be within 1..2000")

    def to_dict(self) -> JsonObject:
        return {
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "neighbor_radius": self.neighbor_radius,
            "response_byte_limit": self.response_byte_limit,
            "deadline_ms": self.deadline_ms,
        }


@dataclass(frozen=True, slots=True)
class RetrieveContextV2RequestDto:
    contract_version: str
    capability_fingerprint: str
    profile_id: str
    scope: RetrievalV2ScopeDto
    queries: Sequence[RetrievalV2QueryDto]
    filters: RetrievalV2HardFiltersDto
    soft_preferences: RetrievalV2SoftPreferencesDto = field(
        default_factory=RetrievalV2SoftPreferencesDto
    )
    bounds: RetrievalV2BoundsDto = field(default_factory=RetrievalV2BoundsDto)

    def __post_init__(self) -> None:
        if self.contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2:
            raise ValueError("contract_version is unsupported")
        _validated_sha256(self.capability_fingerprint, "capability_fingerprint")
        _validated_opaque(self.profile_id, "profile_id")
        if not isinstance(self.scope, RetrievalV2ScopeDto):
            raise ValueError("scope has an invalid runtime type")
        scope = RetrievalV2ScopeDto(
            self.scope.space_id,
            self.scope.memory_scope_id,
            self.scope.thread_id,
        )
        raw_queries = _canonical_tuple(self.queries, RetrievalV2QueryDto, "queries")
        queries = tuple(
            RetrievalV2QueryDto(item.query_id, item.query, item.weight_micros)
            for item in raw_queries
        )
        if not isinstance(self.filters, RetrievalV2HardFiltersDto):
            raise ValueError("filters has an invalid runtime type")
        filters = RetrievalV2HardFiltersDto(
            source_generations=tuple(self.filters.source_generations),
            excluded_source_keys=tuple(self.filters.excluded_source_keys),
            document_keys=tuple(self.filters.document_keys),
            kinds=tuple(self.filters.kinds),
            category=self.filters.category,
            tags_any=tuple(self.filters.tags_any),
            tags_all=tuple(self.filters.tags_all),
            tags_none=tuple(self.filters.tags_none),
            actor_keys=tuple(self.filters.actor_keys),
            time_interval=_copy_time_interval(self.filters.time_interval, "filters.time_interval"),
            relative_time_interval=_copy_relative_time_interval(
                self.filters.relative_time_interval, "filters.relative_time_interval"
            ),
        )
        if not isinstance(self.soft_preferences, RetrievalV2SoftPreferencesDto):
            raise ValueError("soft_preferences has an invalid runtime type")
        soft_preferences = RetrievalV2SoftPreferencesDto(
            source_preferences=tuple(self.soft_preferences.source_preferences),
            actor_preferences=tuple(self.soft_preferences.actor_preferences),
            time_interval=_copy_time_interval(
                self.soft_preferences.time_interval, "soft_preferences.time_interval"
            ),
            relative_time_interval=_copy_relative_time_interval(
                self.soft_preferences.relative_time_interval,
                "soft_preferences.relative_time_interval",
            ),
            time_weight_micros=self.soft_preferences.time_weight_micros,
        )
        if not isinstance(self.bounds, RetrievalV2BoundsDto):
            raise ValueError("bounds has an invalid runtime type")
        bounds = RetrievalV2BoundsDto(
            self.bounds.candidate_limit,
            self.bounds.result_limit,
            self.bounds.neighbor_radius,
            self.bounds.response_byte_limit,
            self.bounds.deadline_ms,
        )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "queries", queries)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "soft_preferences", soft_preferences)
        object.__setattr__(self, "bounds", bounds)
        if not 1 <= len(queries) <= 6:
            raise ValueError("queries must contain 1..6 variants")
        query_ids = tuple(item.query_id for item in self.queries)
        if query_ids != tuple(sorted(set(query_ids), key=canonical_string_sort_key)):
            raise ValueError("queries.query_id values must be UTF-8 sorted and unique")

    def to_dict(self) -> JsonObject:
        return {
            "contract_version": self.contract_version,
            "capability_fingerprint": self.capability_fingerprint,
            "profile_id": self.profile_id,
            "scope": self.scope.to_dict(),
            "queries": [item.to_dict() for item in self.queries],
            "filters": self.filters.to_dict(),
            "soft_preferences": self.soft_preferences.to_dict(),
            "bounds": self.bounds.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrieveContextV2RequestDto:
        """Parse strict JSON-like input; unknown fields are never ignored."""

        _require_exact(
            payload,
            {
                "contract_version",
                "capability_fingerprint",
                "profile_id",
                "scope",
                "queries",
                "filters",
                "soft_preferences",
                "bounds",
            },
            "",
        )
        contract_version = _string(payload, "contract_version")
        if contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2:
            raise ValueError("contract_version is unsupported")
        scope_payload = _mapping(payload.get("scope"), "scope")
        _require_exact(scope_payload, {"space_id", "memory_scope_id", "thread_id"}, "scope")
        scope = RetrievalV2ScopeDto(
            space_id=_string(scope_payload, "space_id", "scope"),
            memory_scope_id=_string(scope_payload, "memory_scope_id", "scope"),
            thread_id=_optional_string(scope_payload, "thread_id", "scope"),
        )
        queries_payload = _sequence(payload.get("queries"), "queries")
        if not 1 <= len(queries_payload) <= 6:
            raise ValueError("queries must contain 1..6 variants")
        queries = tuple(
            _parse_query(_mapping(value, f"queries.{index}"), index)
            for index, value in enumerate(queries_payload)
        )
        filters = _parse_filters(_mapping(payload.get("filters", {}), "filters"))
        soft_preferences = _parse_soft_preferences(
            _mapping(payload.get("soft_preferences", {}), "soft_preferences")
        )
        bounds = _parse_bounds(_mapping(payload.get("bounds", {}), "bounds"))
        return cls(
            contract_version=contract_version,
            capability_fingerprint=_string(payload, "capability_fingerprint"),
            profile_id=_string(payload, "profile_id"),
            scope=scope,
            queries=queries,
            filters=filters,
            soft_preferences=soft_preferences,
            bounds=bounds,
        )


@dataclass(frozen=True, slots=True)
class RetrievalV2ContributionDto:
    provider_id: str
    query_id: str
    provider_rank: int
    provider_weight_micros: int
    query_weight_micros: int
    contribution_score_picos: int
    provider_weight: float
    query_weight: float
    contribution: float
    raw_score_kind: str | None = None
    raw_score_value: float | None = None

    def __post_init__(self) -> None:
        _validated_opaque(self.provider_id, "contribution.provider_id")
        _validated_opaque(self.query_id, "contribution.query_id", maximum=64)
        _validated_integer(self.provider_rank, "contribution.provider_rank")
        if not 1 <= self.provider_rank <= 1_000:
            raise ValueError("contribution.provider_rank must be within 1..1000")
        for name in (
            "provider_weight_micros",
            "query_weight_micros",
            "contribution_score_picos",
        ):
            _validated_integer(getattr(self, name), f"contribution.{name}")
        if not 100_000 <= self.provider_weight_micros <= 10_000_000:
            raise ValueError("contribution.provider_weight_micros is out of bounds")
        if not 100_000 <= self.query_weight_micros <= 10_000_000:
            raise ValueError("contribution.query_weight_micros is out of bounds")
        if not 1 <= self.contribution_score_picos <= 9_007_199_254_740_991:
            raise ValueError("contribution.contribution_score_picos must be positive")
        _bounded_weight(self.provider_weight, "contribution.provider_weight")
        _bounded_weight(self.query_weight, "contribution.query_weight")
        _validated_number(self.contribution, "contribution")
        if not math.isfinite(self.contribution) or self.contribution <= 0:
            raise ValueError("contribution must be finite and positive")
        if self.provider_weight != self.provider_weight_micros / 1_000_000:
            raise ValueError("contribution.provider_weight must mirror integer micros")
        if self.query_weight != self.query_weight_micros / 1_000_000:
            raise ValueError("contribution.query_weight must mirror integer micros")
        if self.contribution != self.contribution_score_picos / 1_000_000_000_000:
            raise ValueError("contribution must mirror contribution_score_picos")
        if (self.raw_score_kind is None) != (self.raw_score_value is None):
            raise ValueError("contribution raw score kind and value are both required")
        if self.raw_score_kind is not None and self.raw_score_kind not in {
            "similarity",
            "distance",
            "relevance",
            "bm25",
        }:
            raise ValueError("contribution.raw_score_kind is unsupported")
        if self.raw_score_value is not None:
            _validated_number(self.raw_score_value, "contribution.raw_score_value")

    def to_dict(self) -> JsonObject:
        return {
            "provider_id": self.provider_id,
            "query_id": self.query_id,
            "provider_rank": self.provider_rank,
            "provider_weight_micros": self.provider_weight_micros,
            "query_weight_micros": self.query_weight_micros,
            "contribution_score_picos": self.contribution_score_picos,
            "provider_weight": self.provider_weight,
            "query_weight": self.query_weight,
            "contribution": self.contribution,
            "raw_score_kind": self.raw_score_kind,
            "raw_score_value": self.raw_score_value,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2NeighborDto:
    locator: str
    source_key: str
    document_key: str
    chunk_key: str
    canonical_identity: str
    canonical_version: int
    lifecycle_status: str
    relation: str = "neighbor"
    distance: int = 1

    def __post_init__(self) -> None:
        for name in (
            "locator",
            "source_key",
            "document_key",
            "chunk_key",
            "canonical_identity",
        ):
            _validated_opaque(getattr(self, name), f"neighbor.{name}")
        _validated_integer(self.canonical_version, "neighbor.canonical_version")
        _validated_integer(self.distance, "neighbor.distance")
        if (
            not 1 <= self.canonical_version <= 9_007_199_254_740_991
            or self.lifecycle_status != "active"
        ):
            raise ValueError("Locator response neighbor must have active canonical identity")
        if self.relation != "neighbor" or not 1 <= abs(self.distance) <= 2:
            raise ValueError(
                "Locator response neighbor requires relation=neighbor and distance 1..2"
            )

    def to_dict(self) -> JsonObject:
        return {
            "locator": self.locator,
            "source_key": self.source_key,
            "document_key": self.document_key,
            "chunk_key": self.chunk_key,
            "canonical_identity": self.canonical_identity,
            "canonical_version": self.canonical_version,
            "lifecycle_status": self.lifecycle_status,
            "relation": self.relation,
            "distance": self.distance,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2CandidateDto:
    locator: str
    source_key: str
    document_key: str
    chunk_key: str
    canonical_identity: str
    canonical_version: int
    lifecycle_status: str
    relation: str = "direct"
    distance: int = 0
    provider_rank: int | None = None
    fused_score: float | None = None
    matched_query_ids: Sequence[str] = field(default_factory=tuple)
    contributions: Sequence[RetrievalV2ContributionDto] = field(default_factory=tuple)
    base_score_picos: int | None = None
    neighbors: Sequence[RetrievalV2NeighborDto] = field(default_factory=tuple)
    preference_score_micros: int = 0
    preference_boost_micros: int = 0
    rerank_score_picos: int | None = None
    source_requested_weight_micros: int = 0
    source_matched_weight_micros: int = 0
    actor_requested_weight_micros: int = 0
    actor_matched_weight_micros: int = 0
    time_requested_weight_micros: int = 0
    time_matched_weight_micros: int = 0

    def __post_init__(self) -> None:
        matched = _canonical_tuple(self.matched_query_ids, str, "candidate.matched_query_ids")
        raw_contributions = _canonical_tuple(
            self.contributions, RetrievalV2ContributionDto, "candidate.contributions"
        )
        contributions = tuple(
            RetrievalV2ContributionDto(
                item.provider_id,
                item.query_id,
                item.provider_rank,
                item.provider_weight_micros,
                item.query_weight_micros,
                item.contribution_score_picos,
                item.provider_weight,
                item.query_weight,
                item.contribution,
                item.raw_score_kind,
                item.raw_score_value,
            )
            for item in raw_contributions
        )
        raw_neighbors = _canonical_tuple(
            self.neighbors, RetrievalV2NeighborDto, "candidate.neighbors"
        )
        neighbors = tuple(
            RetrievalV2NeighborDto(
                item.locator,
                item.source_key,
                item.document_key,
                item.chunk_key,
                item.canonical_identity,
                item.canonical_version,
                item.lifecycle_status,
                item.relation,
                item.distance,
            )
            for item in raw_neighbors
        )
        object.__setattr__(self, "matched_query_ids", matched)
        object.__setattr__(self, "contributions", contributions)
        object.__setattr__(self, "neighbors", neighbors)
        for name in (
            "locator",
            "source_key",
            "document_key",
            "chunk_key",
            "canonical_identity",
        ):
            _validated_opaque(getattr(self, name), f"candidate.{name}")
        _validated_integer(self.canonical_version, "candidate.canonical_version")
        _validated_integer(self.distance, "candidate.distance")
        if (
            not 1 <= self.canonical_version <= 9_007_199_254_740_991
            or self.lifecycle_status != "active"
        ):
            raise ValueError("Locator response candidate must have active canonical identity")
        if self.relation != "direct" or self.distance != 0:
            raise ValueError("Locator response candidate must be a direct seed")
        if self.provider_rank is None:
            raise ValueError("Direct locator candidate requires bounded provider_rank")
        _validated_integer(self.provider_rank, "candidate.provider_rank")
        if not 1 <= self.provider_rank <= 1_000:
            raise ValueError("Direct locator candidate requires bounded provider_rank")
        if self.fused_score is None:
            raise ValueError("Direct locator candidate requires finite fused_score")
        _validated_number(self.fused_score, "candidate.fused_score")
        if not math.isfinite(self.fused_score) or self.fused_score <= 0:
            raise ValueError("Direct locator candidate requires positive finite fused_score")
        if not self.contributions:
            raise ValueError("Direct locator candidate requires contributions")
        if not self.matched_query_ids:
            raise ValueError("Direct locator candidate requires matched_query_ids")
        if self.provider_rank != min(item.provider_rank for item in self.contributions):
            raise ValueError("Direct locator provider_rank must match contribution minimum")
        if self.base_score_picos is None:
            raise ValueError("Direct locator candidate requires base_score_picos")
        _validated_integer(self.base_score_picos, "candidate.base_score_picos")
        if self.base_score_picos != sum(
            item.contribution_score_picos for item in self.contributions
        ):
            raise ValueError("Direct locator base_score_picos must reconstruct")
        if not 1 <= self.base_score_picos <= 9_007_199_254_740_991:
            raise ValueError("candidate.base_score_picos is out of bounds")
        if self.fused_score != self.base_score_picos / 1_000_000_000_000:
            raise ValueError("Direct locator fused_score must mirror base_score_picos")
        base_score_picos = self.base_score_picos
        evidence_names = (
            "source_requested_weight_micros",
            "source_matched_weight_micros",
            "actor_requested_weight_micros",
            "actor_matched_weight_micros",
            "time_requested_weight_micros",
            "time_matched_weight_micros",
        )
        for name in evidence_names:
            _validated_integer(getattr(self, name), f"candidate.{name}")
            if getattr(self, name) < 0:
                raise ValueError(f"candidate.{name} is out of bounds")
        if any(
            getattr(self, matched_name) > getattr(self, requested_name)
            for requested_name, matched_name in zip(
                evidence_names[::2], evidence_names[1::2], strict=True
            )
        ):
            raise ValueError("candidate preference dimension evidence is out of bounds")
        requested = sum(getattr(self, name) for name in evidence_names[::2])
        matched_weight = sum(getattr(self, name) for name in evidence_names[1::2])
        expected_preference = 0 if requested == 0 else matched_weight * 1_000_000 // requested
        if self.preference_score_micros != expected_preference:
            raise ValueError("candidate.preference_score_micros must reconstruct")
        for name in ("preference_score_micros", "preference_boost_micros"):
            _validated_integer(getattr(self, name), f"candidate.{name}")
        if not 0 <= self.preference_score_micros <= 1_000_000:
            raise ValueError("candidate.preference_score_micros is out of bounds")
        expected_boost = self.preference_score_micros * 250_000 // 1_000_000
        if self.preference_boost_micros != expected_boost:
            raise ValueError("candidate.preference_boost_micros must reconstruct")
        expected_rerank = base_score_picos * (1_000_000 + self.preference_boost_micros) // 1_000_000
        if expected_rerank > 9_007_199_254_740_991:
            raise ValueError("candidate.rerank_score_picos is out of bounds")
        if self.rerank_score_picos is None:
            object.__setattr__(self, "rerank_score_picos", expected_rerank)
        else:
            _validated_integer(self.rerank_score_picos, "candidate.rerank_score_picos")
            if self.rerank_score_picos != expected_rerank:
                raise ValueError("candidate.rerank_score_picos must reconstruct")
        if self.matched_query_ids != tuple(
            sorted(set(self.matched_query_ids), key=canonical_string_sort_key)
        ):
            raise ValueError("Direct locator matched_query_ids must be sorted and unique")
        contribution_keys = tuple((item.provider_id, item.query_id) for item in self.contributions)
        if len(set(contribution_keys)) != len(contribution_keys):
            raise ValueError("Direct locator contributions must be unique per provider/query")
        if contribution_keys != tuple(
            sorted(
                contribution_keys,
                key=lambda item: (
                    canonical_string_sort_key(item[0]),
                    canonical_string_sort_key(item[1]),
                ),
            )
        ):
            raise ValueError("Direct locator contributions must be canonically sorted")
        if self.matched_query_ids != tuple(
            sorted(
                {item.query_id for item in self.contributions},
                key=canonical_string_sort_key,
            )
        ):
            raise ValueError("Direct locator matched queries must match contributions")
        for neighbor in self.neighbors:
            if neighbor.source_key != self.source_key:
                raise ValueError("Locator neighbor cannot cross source")

    def to_dict(self) -> JsonObject:
        return {
            "locator": self.locator,
            "source_key": self.source_key,
            "document_key": self.document_key,
            "chunk_key": self.chunk_key,
            "canonical_identity": self.canonical_identity,
            "canonical_version": self.canonical_version,
            "lifecycle_status": self.lifecycle_status,
            "relation": self.relation,
            "distance": self.distance,
            "provider_rank": self.provider_rank,
            "fused_score": self.fused_score,
            "base_score_picos": self.base_score_picos,
            "source_requested_weight_micros": self.source_requested_weight_micros,
            "source_matched_weight_micros": self.source_matched_weight_micros,
            "actor_requested_weight_micros": self.actor_requested_weight_micros,
            "actor_matched_weight_micros": self.actor_matched_weight_micros,
            "time_requested_weight_micros": self.time_requested_weight_micros,
            "time_matched_weight_micros": self.time_matched_weight_micros,
            "preference_score_micros": self.preference_score_micros,
            "preference_boost_micros": self.preference_boost_micros,
            "rerank_score_picos": self.rerank_score_picos,
            "matched_query_ids": json_compatible(self.matched_query_ids),
            "contributions": [item.to_dict() for item in self.contributions],
            "neighbors": [item.to_dict() for item in self.neighbors],
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2ProviderOutcomeDto:
    provider_id: str
    status: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _validated_opaque(self.provider_id, "provider_outcome.provider_id")
        if self.status not in {"available", "unavailable", "unqualified"}:
            raise ValueError("provider_outcome.status is unsupported")
        if self.reason_code not in {
            None,
            "provider_error",
            "provider_unavailable",
            "provider_unqualified",
            "provider_truncated",
        }:
            raise ValueError("provider_outcome.reason_code is unsupported")
        if self.status == "available" and self.reason_code not in {None, "provider_truncated"}:
            raise ValueError("available provider outcome has an invalid reason_code")
        if self.status == "unavailable" and self.reason_code not in {
            "provider_error",
            "provider_unavailable",
        }:
            raise ValueError("unavailable provider outcome has an invalid reason_code")
        if self.status == "unqualified" and self.reason_code != "provider_unqualified":
            raise ValueError("unqualified provider outcome has an invalid reason_code")

    def to_dict(self) -> JsonObject:
        return {
            "provider_id": self.provider_id,
            "status": self.status,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class RetrievalV2AppliedBoundsDto:
    candidate_limit: int
    result_limit: int
    neighbor_radius: int
    response_byte_limit: int
    deadline_ms: int
    returned_seeds: int
    returned_neighbors: int

    def __post_init__(self) -> None:
        _validated_integer(self.returned_seeds, "applied_bounds.returned_seeds")
        _validated_integer(self.returned_neighbors, "applied_bounds.returned_neighbors")
        RetrievalV2BoundsDto(
            self.candidate_limit,
            self.result_limit,
            self.neighbor_radius,
            self.response_byte_limit,
            self.deadline_ms,
        )
        if not 0 <= self.returned_seeds <= self.result_limit:
            raise ValueError("applied_bounds.returned_seeds exceeds result_limit")
        maximum_neighbors = self.returned_seeds * self.neighbor_radius * 2
        if not 0 <= self.returned_neighbors <= maximum_neighbors:
            raise ValueError("applied_bounds.returned_neighbors exceeds neighbor bound")

    def to_dict(self) -> JsonObject:
        return {
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "neighbor_radius": self.neighbor_radius,
            "response_byte_limit": self.response_byte_limit,
            "deadline_ms": self.deadline_ms,
            "returned_seeds": self.returned_seeds,
            "returned_neighbors": self.returned_neighbors,
        }


@dataclass(frozen=True, slots=True)
class RetrieveContextV2ResponseDto:
    status: str
    capability_fingerprint: str
    profile_id: str
    applied_bounds: RetrievalV2AppliedBoundsDto
    candidates: Sequence[RetrievalV2CandidateDto]
    provider_outcomes: Sequence[RetrievalV2ProviderOutcomeDto]
    degradation_reason_codes: Sequence[str] = field(default_factory=tuple)
    contract_version: str = LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2
    ranking_policy: str = LOCATOR_RETRIEVAL_RANKING_POLICY_V2
    coverage: str = "top_k_only"

    def __post_init__(self) -> None:
        if not isinstance(self.applied_bounds, RetrievalV2AppliedBoundsDto):
            raise ValueError("applied_bounds has an invalid runtime type")
        applied = self.applied_bounds
        object.__setattr__(
            self,
            "applied_bounds",
            RetrievalV2AppliedBoundsDto(
                applied.candidate_limit,
                applied.result_limit,
                applied.neighbor_radius,
                applied.response_byte_limit,
                applied.deadline_ms,
                applied.returned_seeds,
                applied.returned_neighbors,
            ),
        )
        raw_candidates = _canonical_tuple(self.candidates, RetrievalV2CandidateDto, "candidates")
        candidates = tuple(
            RetrievalV2CandidateDto(
                locator=item.locator,
                source_key=item.source_key,
                document_key=item.document_key,
                chunk_key=item.chunk_key,
                canonical_identity=item.canonical_identity,
                canonical_version=item.canonical_version,
                lifecycle_status=item.lifecycle_status,
                relation=item.relation,
                distance=item.distance,
                provider_rank=item.provider_rank,
                fused_score=item.fused_score,
                matched_query_ids=item.matched_query_ids,
                contributions=item.contributions,
                base_score_picos=item.base_score_picos,
                neighbors=item.neighbors,
                preference_score_micros=item.preference_score_micros,
                preference_boost_micros=item.preference_boost_micros,
                rerank_score_picos=item.rerank_score_picos,
                source_requested_weight_micros=item.source_requested_weight_micros,
                source_matched_weight_micros=item.source_matched_weight_micros,
                actor_requested_weight_micros=item.actor_requested_weight_micros,
                actor_matched_weight_micros=item.actor_matched_weight_micros,
                time_requested_weight_micros=item.time_requested_weight_micros,
                time_matched_weight_micros=item.time_matched_weight_micros,
            )
            for item in raw_candidates
        )
        raw_outcomes = _canonical_tuple(
            self.provider_outcomes, RetrievalV2ProviderOutcomeDto, "provider_outcomes"
        )
        outcomes = tuple(
            RetrievalV2ProviderOutcomeDto(item.provider_id, item.status, item.reason_code)
            for item in raw_outcomes
        )
        reasons = _canonical_tuple(self.degradation_reason_codes, str, "degradation_reason_codes")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "provider_outcomes", outcomes)
        object.__setattr__(self, "degradation_reason_codes", reasons)
        if self.contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2:
            raise ValueError("Unsupported locator response contract_version")
        if self.status not in {"available", "unavailable", "unqualified"}:
            raise ValueError("Unknown locator response status")
        if self.ranking_policy != LOCATOR_RETRIEVAL_RANKING_POLICY_V2:
            raise ValueError("Unsupported locator response ranking_policy")
        if self.coverage != "top_k_only":
            raise ValueError("Locator coverage must be top_k_only")
        if len(self.provider_outcomes) > 4:
            raise ValueError("Locator provider outcomes exceed bound")
        _validated_sha256(self.capability_fingerprint, "capability_fingerprint")
        _validated_opaque(self.profile_id, "profile_id")
        if any(code not in _DEGRADATION_REASON_CODES for code in reasons):
            raise ValueError("Unknown locator degradation reason code")
        if len(reasons) > len(_DEGRADATION_REASON_CODES):
            raise ValueError("Locator degradation reason codes exceed bound")
        if reasons != tuple(sorted(set(reasons), key=canonical_string_sort_key)):
            raise ValueError("Locator degradation reason codes must be sorted and unique")
        if len(self.candidates) != self.applied_bounds.returned_seeds:
            raise ValueError("Locator candidate count must match applied bounds")
        if self.status != "available" and self.candidates:
            raise ValueError("Non-available locator response cannot return candidates")
        if self.status == "available" and not self.candidates:
            raise ValueError("Available locator response requires candidates")
        ranking_keys = tuple(
            (-item.rerank_score_picos, -item.base_score_picos, item.canonical_identity)
            for item in self.candidates
        )
        if ranking_keys != tuple(
            sorted(
                ranking_keys,
                key=lambda item: (item[0], item[1], canonical_string_sort_key(item[2])),
            )
        ):
            raise ValueError(
                "Locator candidates must use (-rerank_score_picos, -base_score_picos, "
                "canonical_identity) order"
            )
        neighbor_count = sum(len(item.neighbors) for item in self.candidates)
        if neighbor_count != self.applied_bounds.returned_neighbors:
            raise ValueError("Locator neighbor count must match applied bounds")
        provider_ids = tuple(item.provider_id for item in self.provider_outcomes)
        if provider_ids != tuple(sorted(set(provider_ids), key=canonical_string_sort_key)):
            raise ValueError("Locator provider outcomes must be sorted and unique")
        all_candidates = [
            nested for candidate in self.candidates for nested in (candidate, *candidate.neighbors)
        ]
        identities = tuple(item.canonical_identity for item in all_candidates)
        locators = tuple(item.locator for item in all_candidates)
        if len(set(identities)) != len(identities) or len(set(locators)) != len(locators):
            raise ValueError("Locator response candidates must be globally unique")

    def to_dict(self) -> JsonObject:
        return {
            "contract_version": self.contract_version,
            "ranking_policy": self.ranking_policy,
            "status": self.status,
            "capability_fingerprint": self.capability_fingerprint,
            "profile_id": self.profile_id,
            "coverage": self.coverage,
            "applied_bounds": self.applied_bounds.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "provider_outcomes": [item.to_dict() for item in self.provider_outcomes],
            "degradation_reason_codes": json_compatible(self.degradation_reason_codes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrieveContextV2ResponseDto:
        from ._context_building_retrieval_v2_response import (  # noqa: PLC0415
            parse_retrieve_context_v2_response,
        )

        return parse_retrieve_context_v2_response(payload)


def _parse_query(payload: Mapping[str, object], index: int) -> RetrievalV2QueryDto:
    path = f"queries.{index}"
    _require_exact(payload, {"query_id", "query", "weight_micros"}, path)
    query = _string(payload, "query", path)
    if query != " ".join(query.split()) or len(query) > 512:
        raise ValueError(f"{path}.query must be normalized and at most 512 characters")
    return RetrievalV2QueryDto(
        query_id=_string(payload, "query_id", path),
        query=query,
        weight_micros=_integer(payload.get("weight_micros"), f"{path}.weight_micros"),
    )


def _parse_bounds(payload: Mapping[str, object]) -> RetrievalV2BoundsDto:
    _require_exact(
        payload,
        {
            "candidate_limit",
            "result_limit",
            "neighbor_radius",
            "response_byte_limit",
            "deadline_ms",
        },
        "bounds",
    )
    candidate_limit = _integer(payload.get("candidate_limit", 150), "bounds.candidate_limit")
    result_limit = _integer(payload.get("result_limit", 20), "bounds.result_limit")
    neighbor_radius = _integer(payload.get("neighbor_radius", 0), "bounds.neighbor_radius")
    response_bytes = _integer(
        payload.get("response_byte_limit", 1_048_576), "bounds.response_byte_limit"
    )
    deadline_ms = _integer(payload.get("deadline_ms", 2_000), "bounds.deadline_ms")
    if not 1 <= candidate_limit <= 1_000:
        raise ValueError("bounds.candidate_limit must be within 1..1000")
    if not 1 <= result_limit <= 50 or result_limit > candidate_limit:
        raise ValueError("bounds.result_limit must be within 1..50 and not exceed candidate_limit")
    if not 0 <= neighbor_radius <= 2:
        raise ValueError("bounds.neighbor_radius must be within 0..2")
    if not MIN_LOCATOR_RETRIEVAL_RESPONSE_BYTES_V2 <= response_bytes <= 1_048_576:
        raise ValueError("bounds.response_byte_limit must be within 16384..1048576")
    if not 1 <= deadline_ms <= 2_000:
        raise ValueError("bounds.deadline_ms must be within 1..2000")
    return RetrievalV2BoundsDto(
        candidate_limit, result_limit, neighbor_radius, response_bytes, deadline_ms
    )


def _copy_time_interval(
    value: RetrievalV2TimeIntervalDto | None, path: str
) -> RetrievalV2TimeIntervalDto | None:
    if value is None:
        return None
    if not isinstance(value, RetrievalV2TimeIntervalDto):
        raise ValueError(f"{path} has an invalid runtime type")
    return RetrievalV2TimeIntervalDto(value.start_at, value.end_at)


def _copy_relative_time_interval(
    value: RetrievalV2RelativeTimeIntervalDto | None, path: str
) -> RetrievalV2RelativeTimeIntervalDto | None:
    if value is None:
        return None
    if not isinstance(value, RetrievalV2RelativeTimeIntervalDto):
        raise ValueError(f"{path} has an invalid runtime type")
    return RetrievalV2RelativeTimeIntervalDto(value.start_ms, value.end_ms)


def _score_picos(value: float) -> int:
    scaled = Decimal(str(value)) * Decimal(1_000_000_000_000)
    if scaled != scaled.to_integral_value():
        raise ValueError("candidate.fused_score must have at most twelve decimal places")
    result = int(scaled)
    if not 1 <= result <= 9_007_199_254_740_991:
        raise ValueError("candidate.fused_score pico representation is out of bounds")
    return result


__all__ = [
    "LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2",
    "LOCATOR_RETRIEVAL_RANKING_POLICY_V2",
    "MIN_LOCATOR_RETRIEVAL_RESPONSE_BYTES_V2",
    "RetrievalV2AppliedBoundsDto",
    "RetrievalV2BoundsDto",
    "RetrievalV2CandidateDto",
    "RetrievalV2ContributionDto",
    "RetrievalV2HardFiltersDto",
    "RetrievalV2NeighborDto",
    "RetrievalV2ProviderOutcomeDto",
    "RetrievalV2QueryDto",
    "RetrievalV2RelativeTimeIntervalDto",
    "RetrievalV2ScopeDto",
    "RetrievalV2SoftPreferencesDto",
    "RetrievalV2SourceGenerationDto",
    "RetrievalV2TimeIntervalDto",
    "RetrievalV2WeightedKeyDto",
    "RetrieveContextV2RequestDto",
    "RetrieveContextV2ResponseDto",
]
