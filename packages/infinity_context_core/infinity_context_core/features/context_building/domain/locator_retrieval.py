"""Deterministic, locator-only domain contract for Retrieval."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.context_building.domain.locator_retrieval_filters import (
    MAX_PREFERENCE_BOOST_MICROS,
    PREFERENCE_SCORE_SCALE,
    LocatorHardFilters,
    LocatorRelativeTimeInterval,
    LocatorSoftPreferences,
    LocatorSourceGeneration,
    LocatorTimeInterval,
    LocatorWeightedKey,
    preference_evidence,
)
from infinity_context_core.features.context_building.domain.retrieval_capability import (
    LOCATOR_RETRIEVAL_RANK_CONSTANT as _LOCATOR_RETRIEVAL_RANK_CONSTANT,
)
from infinity_context_core.features.context_building.domain.retrieval_capability import (
    LOCATOR_RETRIEVAL_RANKING_POLICY,
    LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS,
    LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS,
    LocatorProviderLaneCapability,
    LocatorRetrievalCapability,
    LocatorRetrievalCapabilityBounds,
    canonical_string_sort_key,
)

LOCATOR_RETRIEVAL_CONTRACT_VERSION = "context-retrieval.v2"
LOCATOR_RETRIEVAL_RANK_CONSTANT = _LOCATOR_RETRIEVAL_RANK_CONSTANT
MAX_QUERY_VARIANTS = 6
MAX_PROVIDER_REGISTRATIONS = 4
MAX_PROVIDER_RANK = 1_000
MAX_RESULT_LIMIT = 50
MAX_CANDIDATE_LIMIT = 1_000
MAX_NEIGHBOR_RADIUS = 2
MAX_DEADLINE_MS = 2_000
MAX_RESPONSE_BYTES = 1_048_576
MIN_RESPONSE_BYTES = 16_384

_RAW_SCORE_KINDS = frozenset({"similarity", "distance", "relevance", "bm25"})
_LIFECYCLE_STATUSES = frozenset({"active", "deleted", "expired", "restricted"})
_PROVIDER_STATUSES = frozenset({"available", "unavailable", "unqualified"})
_PROVIDER_REASON_CODES = frozenset(
    {"provider_error", "provider_unavailable", "provider_unqualified", "provider_truncated"}
)
_RESPONSE_STATUSES = frozenset({"available", "unavailable", "unqualified"})
_DEGRADATION_REASON_CODES = frozenset(
    {
        "optional_provider_failed",
        "optional_provider_unavailable",
        "optional_provider_unqualified",
        "capability_profile_mismatch",
        "neighbor_capability_unavailable",
        "response_byte_limit_exceeded",
    }
)


class CanonicalHydrationInvariantError(RuntimeError):
    """Canonical adapter violated the declared single-snapshot hydration contract."""


@dataclass(frozen=True, slots=True)
class LocatorRetrievalScope:
    """One canonical scope; external scope resolution stays downstream."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_opaque("space_id", self.space_id)
        _require_opaque("memory_scope_id", self.memory_scope_id)
        if self.thread_id is not None:
            _require_opaque("thread_id", self.thread_id)


@dataclass(frozen=True, slots=True)
class LocatorQueryVariant:
    query_id: str
    query: str
    weight_micros: int = LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS

    def __post_init__(self) -> None:
        _require_opaque("query_id", self.query_id, maximum=64)
        if not isinstance(self.query, str):
            raise ValueError("Locator query must be a string")
        normalized = " ".join(self.query.split())
        if normalized != self.query or not 1 <= len(normalized) <= 512:
            raise ValueError("Locator query must be normalized and contain 1..512 characters")
        _require_valid_unicode("query", self.query)
        _require_int("query weight_micros", self.weight_micros)
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("Locator query weight_micros must be within 100000..10000000")

    @property
    def weight(self) -> float:
        """Informational compatibility mirror; integer micros are authoritative."""

        return self.weight_micros / LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS


@dataclass(frozen=True, slots=True)
class LocatorRetrievalBounds:
    candidate_limit: int = 150
    result_limit: int = 20
    neighbor_radius: int = 0
    response_byte_limit: int = MAX_RESPONSE_BYTES
    deadline_ms: int = MAX_DEADLINE_MS

    def __post_init__(self) -> None:
        for name in (
            "candidate_limit",
            "result_limit",
            "neighbor_radius",
            "response_byte_limit",
            "deadline_ms",
        ):
            _require_int(name, getattr(self, name))
        if not 1 <= self.candidate_limit <= MAX_CANDIDATE_LIMIT:
            raise ValueError("Locator candidate_limit must be within 1..1000")
        if not 1 <= self.result_limit <= MAX_RESULT_LIMIT:
            raise ValueError("Locator result_limit must be within 1..50")
        if self.result_limit > self.candidate_limit:
            raise ValueError("Locator result_limit cannot exceed candidate_limit")
        if not 0 <= self.neighbor_radius <= MAX_NEIGHBOR_RADIUS:
            raise ValueError("Locator neighbor_radius must be within 0..2")
        if not MIN_RESPONSE_BYTES <= self.response_byte_limit <= MAX_RESPONSE_BYTES:
            raise ValueError("Locator response_byte_limit must be within 16384..1048576")
        if not 1 <= self.deadline_ms <= MAX_DEADLINE_MS:
            raise ValueError("Locator deadline_ms must be within 1..2000")


@dataclass(frozen=True, slots=True)
class LocatorRetrievalRequest:
    contract_version: str
    capability_fingerprint: str
    profile_id: str
    scope: LocatorRetrievalScope
    queries: tuple[LocatorQueryVariant, ...]
    hard_filters: LocatorHardFilters
    soft_preferences: LocatorSoftPreferences
    bounds: LocatorRetrievalBounds

    def __post_init__(self) -> None:
        if self.contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION:
            raise ValueError("Unsupported locator retrieval contract_version")
        _require_sha256("capability_fingerprint", self.capability_fingerprint)
        _require_opaque("profile_id", self.profile_id)
        if not isinstance(self.scope, LocatorRetrievalScope):
            raise ValueError("Locator retrieval scope has an invalid runtime type")
        raw_queries = _immutable_tuple(self.queries, LocatorQueryVariant, "queries")
        queries = tuple(
            LocatorQueryVariant(item.query_id, item.query, item.weight_micros)
            for item in raw_queries
        )
        object.__setattr__(self, "queries", queries)
        if not isinstance(self.hard_filters, LocatorHardFilters):
            raise ValueError("Locator hard_filters has an invalid runtime type")
        if not isinstance(self.soft_preferences, LocatorSoftPreferences):
            raise ValueError("Locator soft_preferences has an invalid runtime type")
        if not isinstance(self.bounds, LocatorRetrievalBounds):
            raise ValueError("Locator bounds has an invalid runtime type")
        if not 1 <= len(queries) <= MAX_QUERY_VARIANTS:
            raise ValueError("Locator retrieval requires 1..6 query variants")
        query_ids = tuple(item.query_id for item in self.queries)
        if query_ids != tuple(sorted(set(query_ids), key=canonical_string_sort_key)):
            raise ValueError("Locator retrieval query ids must be UTF-8 sorted and unique")


@dataclass(frozen=True, slots=True)
class LocatorProviderHit:
    canonical_identity: str
    canonical_version: int
    provider_id: str
    query_id: str
    provider_rank: int
    raw_score_kind: str | None = None
    raw_score_value: float | None = None

    def __post_init__(self) -> None:
        _require_opaque("canonical_identity", self.canonical_identity)
        _require_opaque("provider_id", self.provider_id)
        _require_opaque("query_id", self.query_id, maximum=64)
        _require_int("canonical_version", self.canonical_version)
        _require_int("provider_rank", self.provider_rank)
        if not 1 <= self.canonical_version <= 9_007_199_254_740_991:
            raise ValueError("Locator provider canonical_version must be positive")
        if not 1 <= self.provider_rank <= MAX_PROVIDER_RANK:
            raise ValueError("Locator provider_rank must be within 1..1000")
        if (self.raw_score_kind is None) != (self.raw_score_value is None):
            raise ValueError("Locator raw score kind and value must be supplied together")
        if self.raw_score_kind is not None and self.raw_score_kind not in _RAW_SCORE_KINDS:
            raise ValueError("Unknown locator raw score kind")
        if self.raw_score_value is not None:
            _require_number("raw score value", self.raw_score_value)


@dataclass(frozen=True, slots=True)
class LocatorProviderResult:
    hits: tuple[LocatorProviderHit, ...] = ()
    status: str = "available"
    reason_code: str | None = None

    def __post_init__(self) -> None:
        raw_hits = _immutable_tuple(self.hits, LocatorProviderHit, "provider hits")
        hits = tuple(
            LocatorProviderHit(
                item.canonical_identity,
                item.canonical_version,
                item.provider_id,
                item.query_id,
                item.provider_rank,
                item.raw_score_kind,
                item.raw_score_value,
            )
            for item in raw_hits
        )
        object.__setattr__(self, "hits", hits)
        if self.status not in _PROVIDER_STATUSES:
            raise ValueError("Unknown locator provider status")
        if self.reason_code is not None and self.reason_code not in _PROVIDER_REASON_CODES:
            raise ValueError("Unknown locator provider reason code")
        if self.status == "available" and self.reason_code not in {None, "provider_truncated"}:
            raise ValueError("Available locator provider has an invalid reason code")
        if self.status == "unavailable" and self.reason_code not in {
            "provider_error",
            "provider_unavailable",
        }:
            raise ValueError("Unavailable locator provider has an invalid reason code")
        if self.status == "unqualified" and self.reason_code != "provider_unqualified":
            raise ValueError("Unqualified locator provider has an invalid reason code")
        if self.status != "available" and self.hits:
            raise ValueError("Unavailable locator provider cannot return hits")


@dataclass(frozen=True, slots=True)
class CanonicalLocatorCandidate:
    """Canonical hydration shape; it deliberately has no provider-owned payload."""

    locator: str
    canonical_identity: str
    canonical_version: int
    lifecycle_status: str
    space_id: str
    memory_scope_id: str
    source_key: str
    document_key: str
    chunk_key: str
    projection_generation: str
    kind: str
    category: str
    read_snapshot: str
    tags: tuple[str, ...] = ()
    actor_keys: tuple[str, ...] = ()
    start_at: datetime | None = None
    end_at: datetime | None = None
    sequence_ordinal: int | None = None
    thread_id: str | None = None
    relative_start_ms: int | None = None
    relative_end_ms: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "locator",
            "canonical_identity",
            "space_id",
            "memory_scope_id",
            "source_key",
            "document_key",
            "chunk_key",
            "projection_generation",
            "kind",
            "category",
        ):
            _require_opaque(name, getattr(self, name))
        if self.thread_id is not None:
            _require_opaque("thread_id", self.thread_id)
        _require_opaque("read_snapshot", self.read_snapshot)
        _require_int("canonical_version", self.canonical_version)
        if not 1 <= self.canonical_version <= 9_007_199_254_740_991:
            raise ValueError("Canonical locator version must be positive")
        if self.lifecycle_status not in _LIFECYCLE_STATUSES:
            raise ValueError("Unknown canonical locator lifecycle status")
        tags = _immutable_tuple(self.tags, str, "tags")
        actors = _immutable_tuple(self.actor_keys, str, "actor_keys")
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "actor_keys", actors)
        _require_unique_opaque("tags", tags)
        _require_unique_opaque("actor_keys", actors)
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("Canonical locator time requires both start_at and end_at")
        if self.start_at is not None and self.end_at is not None:
            LocatorTimeInterval(self.start_at, self.end_at)
        if (self.relative_start_ms is None) != (self.relative_end_ms is None):
            raise ValueError("Canonical locator relative time requires both endpoints")
        if self.relative_start_ms is not None and self.relative_end_ms is not None:
            LocatorRelativeTimeInterval(self.relative_start_ms, self.relative_end_ms)
        if self.sequence_ordinal is not None:
            _require_int("sequence_ordinal", self.sequence_ordinal)
            if not 0 <= self.sequence_ordinal <= 2_147_483_647:
                raise ValueError("Canonical locator sequence_ordinal is out of bounds")


@dataclass(frozen=True, slots=True)
class CanonicalLocatorRead:
    """Seeds and neighbors hydrated in one canonical read transaction/snapshot."""

    seeds: tuple[CanonicalLocatorCandidate, ...]
    neighbors: tuple[CanonicalLocatorCandidate, ...] = ()

    def __post_init__(self) -> None:
        raw_seeds = _immutable_tuple(self.seeds, CanonicalLocatorCandidate, "read seeds")
        raw_neighbors = _immutable_tuple(
            self.neighbors, CanonicalLocatorCandidate, "read neighbors"
        )
        object.__setattr__(self, "seeds", tuple(_copy_canonical(item) for item in raw_seeds))
        object.__setattr__(
            self,
            "neighbors",
            tuple(_copy_canonical(item) for item in raw_neighbors),
        )


@dataclass(frozen=True, slots=True)
class LocatorScoreContribution:
    provider_id: str
    query_id: str
    provider_rank: int
    provider_weight_micros: int
    query_weight_micros: int
    contribution_score_picos: int
    raw_score_kind: str | None = None
    raw_score_value: float | None = None

    def __post_init__(self) -> None:
        _require_opaque("contribution provider_id", self.provider_id)
        _require_opaque("contribution query_id", self.query_id, maximum=64)
        _require_int("contribution provider_rank", self.provider_rank)
        if not 1 <= self.provider_rank <= MAX_PROVIDER_RANK:
            raise ValueError("Locator contribution provider_rank is out of bounds")
        for name in (
            "provider_weight_micros",
            "query_weight_micros",
            "contribution_score_picos",
        ):
            _require_int(f"contribution {name}", getattr(self, name))
        if not 100_000 <= self.provider_weight_micros <= 10_000_000:
            raise ValueError("Locator contribution provider_weight_micros is out of bounds")
        if not 100_000 <= self.query_weight_micros <= 10_000_000:
            raise ValueError("Locator contribution query_weight_micros is out of bounds")
        if not 1 <= self.contribution_score_picos <= 9_007_199_254_740_991:
            raise ValueError("Locator contribution_score_picos must be positive")
        if (self.raw_score_kind is None) != (self.raw_score_value is None):
            raise ValueError("Locator contribution raw score is incomplete")
        if self.raw_score_kind is not None and self.raw_score_kind not in _RAW_SCORE_KINDS:
            raise ValueError("Unknown locator contribution raw score kind")
        if self.raw_score_value is not None:
            _require_number("contribution raw score", self.raw_score_value)

    @property
    def provider_weight(self) -> float:
        return self.provider_weight_micros / LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS

    @property
    def query_weight(self) -> float:
        return self.query_weight_micros / LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS

    @property
    def contribution(self) -> float:
        return self.contribution_score_picos / LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS


@dataclass(frozen=True, slots=True)
class LocatorNeighbor:
    locator: str
    source_key: str
    document_key: str
    chunk_key: str
    canonical_identity: str
    canonical_version: int
    lifecycle_status: str
    relation: str
    distance: int

    def __post_init__(self) -> None:
        for name in (
            "locator",
            "source_key",
            "document_key",
            "chunk_key",
            "canonical_identity",
        ):
            _require_opaque(f"neighbor {name}", getattr(self, name))
        _require_int("neighbor canonical_version", self.canonical_version)
        _require_int("neighbor distance", self.distance)
        if not 1 <= self.canonical_version <= 9_007_199_254_740_991:
            raise ValueError("Locator neighbor canonical_version must be positive")
        if self.relation != "neighbor" or not 1 <= abs(self.distance) <= 2:
            raise ValueError("Locator neighbor requires relation=neighbor and distance 1..2")
        if self.lifecycle_status != "active":
            raise ValueError("Locator neighbor must be canonically active")


@dataclass(frozen=True, slots=True)
class LocatorResultCandidate:
    locator: str
    source_key: str
    document_key: str
    chunk_key: str
    canonical_identity: str
    canonical_version: int
    lifecycle_status: str
    provider_rank: int
    fused_score: float
    matched_query_ids: tuple[str, ...]
    contributions: tuple[LocatorScoreContribution, ...]
    base_score_picos: int
    neighbors: tuple[LocatorNeighbor, ...] = ()
    relation: str = "direct"
    distance: int = 0
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
        matched = _immutable_tuple(self.matched_query_ids, str, "matched_query_ids")
        raw_contributions = _immutable_tuple(
            self.contributions, LocatorScoreContribution, "contributions"
        )
        contributions = tuple(
            LocatorScoreContribution(
                item.provider_id,
                item.query_id,
                item.provider_rank,
                item.provider_weight_micros,
                item.query_weight_micros,
                item.contribution_score_picos,
                item.raw_score_kind,
                item.raw_score_value,
            )
            for item in raw_contributions
        )
        raw_neighbors = _immutable_tuple(self.neighbors, LocatorNeighbor, "neighbors")
        neighbors = tuple(
            LocatorNeighbor(
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
            _require_opaque(f"candidate {name}", getattr(self, name))
        _require_int("candidate canonical_version", self.canonical_version)
        _require_int("candidate provider_rank", self.provider_rank)
        _require_int("candidate distance", self.distance)
        if not 1 <= self.canonical_version <= 9_007_199_254_740_991:
            raise ValueError("Ranked locator canonical_version must be positive")
        if not 1 <= self.provider_rank <= MAX_PROVIDER_RANK:
            raise ValueError("Ranked locator provider_rank is out of bounds")
        if self.relation != "direct" or self.distance != 0:
            raise ValueError("Ranked locator candidate must be a direct seed")
        if self.lifecycle_status != "active":
            raise ValueError("Ranked locator candidate must be canonically active")
        _require_number("fused_score", self.fused_score)
        if self.fused_score <= 0:
            raise ValueError("Ranked locator fused_score must be finite and positive")
        if not self.contributions:
            raise ValueError("Ranked locator requires score contributions")
        if not self.matched_query_ids:
            raise ValueError("Ranked locator requires matched_query_ids")
        if self.provider_rank != min(item.provider_rank for item in self.contributions):
            raise ValueError("Ranked locator provider_rank must match contribution minimum")
        _require_int("base_score_picos", self.base_score_picos)
        if self.base_score_picos != sum(
            item.contribution_score_picos for item in self.contributions
        ):
            raise ValueError("Ranked locator base_score_picos must reconstruct")
        if not 1 <= self.base_score_picos <= 9_007_199_254_740_991:
            raise ValueError("Ranked locator base_score_picos is out of bounds")
        if self.fused_score != self.base_score_picos / LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS:
            raise ValueError("Ranked locator fused_score must mirror base_score_picos")
        base_score_picos = self.base_score_picos
        evidence_fields = (
            "source_requested_weight_micros",
            "source_matched_weight_micros",
            "actor_requested_weight_micros",
            "actor_matched_weight_micros",
            "time_requested_weight_micros",
            "time_matched_weight_micros",
        )
        for name in evidence_fields:
            _require_int(name, getattr(self, name))
            if getattr(self, name) < 0:
                raise ValueError(f"Ranked locator {name} is out of bounds")
        requested = sum(getattr(self, name) for name in evidence_fields[::2])
        matched_weight = sum(getattr(self, name) for name in evidence_fields[1::2])
        expected_preference = (
            0 if requested == 0 else matched_weight * PREFERENCE_SCORE_SCALE // requested
        )
        if self.preference_score_micros != expected_preference:
            raise ValueError("Ranked locator preference_score_micros must reconstruct")
        for name in ("preference_score_micros", "preference_boost_micros"):
            _require_int(name, getattr(self, name))
        if not 0 <= self.preference_score_micros <= PREFERENCE_SCORE_SCALE:
            raise ValueError("Ranked locator preference_score_micros is out of bounds")
        expected_boost = (
            self.preference_score_micros * MAX_PREFERENCE_BOOST_MICROS // PREFERENCE_SCORE_SCALE
        )
        if self.preference_boost_micros != expected_boost:
            raise ValueError("Ranked locator preference_boost_micros must reconstruct")
        expected_rerank = (
            base_score_picos
            * (PREFERENCE_SCORE_SCALE + self.preference_boost_micros)
            // PREFERENCE_SCORE_SCALE
        )
        if expected_rerank > 9_007_199_254_740_991:
            raise ValueError("Ranked locator rerank_score_picos is out of bounds")
        if self.rerank_score_picos is None:
            object.__setattr__(self, "rerank_score_picos", expected_rerank)
        else:
            _require_int("rerank_score_picos", self.rerank_score_picos)
            if self.rerank_score_picos != expected_rerank:
                raise ValueError("Ranked locator rerank_score_picos must reconstruct")
        if self.matched_query_ids != tuple(
            sorted(set(self.matched_query_ids), key=canonical_string_sort_key)
        ):
            raise ValueError("Ranked locator matched_query_ids must be sorted and unique")
        contribution_keys = tuple((item.provider_id, item.query_id) for item in self.contributions)
        if len(set(contribution_keys)) != len(contribution_keys):
            raise ValueError("Ranked locator contributions must be unique per provider/query")
        if contribution_keys != tuple(
            sorted(
                contribution_keys,
                key=lambda item: (
                    canonical_string_sort_key(item[0]),
                    canonical_string_sort_key(item[1]),
                ),
            )
        ):
            raise ValueError("Ranked locator contributions must be canonically sorted")
        if self.matched_query_ids != tuple(
            sorted(
                {item.query_id for item in self.contributions},
                key=canonical_string_sort_key,
            )
        ):
            raise ValueError("Ranked locator matched queries must match contributions")
        if any(neighbor.source_key != self.source_key for neighbor in self.neighbors):
            raise ValueError("Locator neighbor cannot cross source")


@dataclass(frozen=True, slots=True)
class LocatorProviderOutcome:
    provider_id: str
    status: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_opaque("outcome provider_id", self.provider_id)
        if self.status not in _PROVIDER_STATUSES:
            raise ValueError("Unknown locator provider outcome status")
        if self.reason_code is not None and self.reason_code not in _PROVIDER_REASON_CODES:
            raise ValueError("Unknown locator provider outcome reason code")
        if self.status == "available" and self.reason_code not in {None, "provider_truncated"}:
            raise ValueError("Available locator provider outcome has an invalid reason code")
        if self.status == "unavailable" and self.reason_code not in {
            "provider_error",
            "provider_unavailable",
        }:
            raise ValueError("Unavailable locator provider outcome has an invalid reason code")
        if self.status == "unqualified" and self.reason_code != "provider_unqualified":
            raise ValueError("Unqualified locator provider outcome has an invalid reason code")


@dataclass(frozen=True, slots=True)
class LocatorAppliedBounds:
    candidate_limit: int
    result_limit: int
    neighbor_radius: int
    response_byte_limit: int
    deadline_ms: int
    returned_seeds: int
    returned_neighbors: int

    def __post_init__(self) -> None:
        _require_int("returned_seeds", self.returned_seeds)
        _require_int("returned_neighbors", self.returned_neighbors)
        LocatorRetrievalBounds(
            candidate_limit=self.candidate_limit,
            result_limit=self.result_limit,
            neighbor_radius=self.neighbor_radius,
            response_byte_limit=self.response_byte_limit,
            deadline_ms=self.deadline_ms,
        )
        if not 0 <= self.returned_seeds <= self.result_limit:
            raise ValueError("Locator returned_seeds exceeds result bound")
        if not 0 <= self.returned_neighbors <= self.returned_seeds * self.neighbor_radius * 2:
            raise ValueError("Locator returned_neighbors exceeds neighbor bound")


@dataclass(frozen=True, slots=True)
class LocatorRetrievalResponse:
    status: str
    capability_fingerprint: str
    profile_id: str
    applied_bounds: LocatorAppliedBounds
    candidates: tuple[LocatorResultCandidate, ...]
    provider_outcomes: tuple[LocatorProviderOutcome, ...]
    degradation_reason_codes: tuple[str, ...] = ()
    contract_version: str = LOCATOR_RETRIEVAL_CONTRACT_VERSION
    ranking_policy: str = LOCATOR_RETRIEVAL_RANKING_POLICY
    coverage: str = "top_k_only"

    def __post_init__(self) -> None:
        if not isinstance(self.applied_bounds, LocatorAppliedBounds):
            raise ValueError("Locator applied_bounds has an invalid runtime type")
        applied = self.applied_bounds
        object.__setattr__(
            self,
            "applied_bounds",
            LocatorAppliedBounds(
                applied.candidate_limit,
                applied.result_limit,
                applied.neighbor_radius,
                applied.response_byte_limit,
                applied.deadline_ms,
                applied.returned_seeds,
                applied.returned_neighbors,
            ),
        )
        raw_candidates = _immutable_tuple(
            self.candidates, LocatorResultCandidate, "response candidates"
        )
        candidates = tuple(
            LocatorResultCandidate(
                locator=item.locator,
                source_key=item.source_key,
                document_key=item.document_key,
                chunk_key=item.chunk_key,
                canonical_identity=item.canonical_identity,
                canonical_version=item.canonical_version,
                lifecycle_status=item.lifecycle_status,
                provider_rank=item.provider_rank,
                fused_score=item.fused_score,
                matched_query_ids=item.matched_query_ids,
                contributions=item.contributions,
                base_score_picos=item.base_score_picos,
                neighbors=item.neighbors,
                relation=item.relation,
                distance=item.distance,
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
        raw_outcomes = _immutable_tuple(
            self.provider_outcomes, LocatorProviderOutcome, "provider outcomes"
        )
        outcomes = tuple(
            LocatorProviderOutcome(item.provider_id, item.status, item.reason_code)
            for item in raw_outcomes
        )
        reasons = _immutable_tuple(self.degradation_reason_codes, str, "degradation reason codes")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "provider_outcomes", outcomes)
        object.__setattr__(self, "degradation_reason_codes", reasons)
        _require_sha256("response capability_fingerprint", self.capability_fingerprint)
        _require_opaque("response profile_id", self.profile_id)
        if self.status not in _RESPONSE_STATUSES:
            raise ValueError("Unknown locator retrieval response status")
        if self.contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION:
            raise ValueError("Unsupported locator retrieval response contract")
        if self.ranking_policy != LOCATOR_RETRIEVAL_RANKING_POLICY:
            raise ValueError("Unsupported locator retrieval ranking policy")
        if self.coverage != "top_k_only":
            raise ValueError("Locator retrieval coverage must be top_k_only")
        if len(self.provider_outcomes) > MAX_PROVIDER_REGISTRATIONS:
            raise ValueError("Locator provider outcomes exceed bound")
        if any(code not in _DEGRADATION_REASON_CODES for code in self.degradation_reason_codes):
            raise ValueError("Unknown locator degradation reason code")
        if len(self.degradation_reason_codes) > len(_DEGRADATION_REASON_CODES):
            raise ValueError("Locator degradation reason codes exceed bound")
        if self.degradation_reason_codes != tuple(
            sorted(set(self.degradation_reason_codes), key=canonical_string_sort_key)
        ):
            raise ValueError("Locator degradation reason codes must be sorted and unique")
        if len(self.candidates) != self.applied_bounds.returned_seeds:
            raise ValueError("Locator candidates must match applied seed count")
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
        if sum(len(item.neighbors) for item in self.candidates) != (
            self.applied_bounds.returned_neighbors
        ):
            raise ValueError("Locator neighbors must match applied neighbor count")
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


def candidate_matches_request(
    candidate: CanonicalLocatorCandidate,
    request: LocatorRetrievalRequest,
) -> bool:
    """Reapply scope, lifecycle and every registered hard filter canonically."""

    scope = request.scope
    filters = request.hard_filters
    if candidate.lifecycle_status != "active":
        return False
    if candidate.space_id != scope.space_id or candidate.memory_scope_id != scope.memory_scope_id:
        return False
    if candidate.thread_id != scope.thread_id:
        return False
    if (candidate.source_key, candidate.projection_generation) not in {
        (item.source_key, item.projection_generation) for item in filters.source_generations
    }:
        return False
    if candidate.source_key in filters.excluded_source_keys:
        return False
    if filters.document_keys and candidate.document_key not in filters.document_keys:
        return False
    if filters.kinds and candidate.kind not in filters.kinds:
        return False
    if filters.category is not None and candidate.category != filters.category:
        return False
    candidate_tags = set(candidate.tags)
    if filters.tags_any and not candidate_tags.intersection(filters.tags_any):
        return False
    if not set(filters.tags_all).issubset(candidate_tags):
        return False
    if candidate_tags.intersection(filters.tags_none):
        return False
    if filters.actor_keys and not set(candidate.actor_keys).intersection(filters.actor_keys):
        return False
    if filters.time_interval is not None and not filters.time_interval.overlaps(
        candidate.start_at, candidate.end_at
    ):
        return False
    return filters.relative_time_interval is None or filters.relative_time_interval.overlaps(
        candidate.relative_start_ms, candidate.relative_end_ms
    )


def _require_opaque(name: str, value: str, *, maximum: int = 256) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"Locator {name} must be a non-blank normalized string")
    if len(value) > maximum:
        raise ValueError(f"Locator {name} exceeds {maximum} characters")
    _require_valid_unicode(name, value)


def _require_valid_unicode(name: str, value: str) -> None:
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"Locator {name} contains invalid Unicode or controls")


def _require_sha256(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Locator {name} must be 64 lowercase hexadecimal characters")


def _require_unique_opaque(name: str, values: tuple[str, ...]) -> None:
    for value in values:
        _require_opaque(name, value)
    if len(values) > 100 or values != tuple(sorted(set(values), key=canonical_string_sort_key)):
        raise ValueError(f"Locator {name} values must be UTF-8 sorted and unique")


def _require_weight(name: str, value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Locator {name} must be numeric")
    if not math.isfinite(value) or not 0.1 <= value <= 10.0:
        raise ValueError(f"Locator {name} must be finite and within 0.1..10")


def _require_number(name: str, value: object) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Locator {name} must be numeric")
    if not math.isfinite(value):
        raise ValueError(f"Locator {name} must be finite")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Locator {name} must be timezone-aware")


def _require_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Locator {name} must be an integer")


def _immutable_tuple(values: object, item_type: type, name: str) -> tuple:
    if isinstance(values, str | bytes):
        raise ValueError(f"Locator {name} must be a collection")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"Locator {name} must be a collection") from error
    if not all(isinstance(item, item_type) for item in result):
        raise ValueError(f"Locator {name} contains an invalid runtime type")
    return result


def _copy_canonical(item: CanonicalLocatorCandidate) -> CanonicalLocatorCandidate:
    return CanonicalLocatorCandidate(
        item.locator,
        item.canonical_identity,
        item.canonical_version,
        item.lifecycle_status,
        item.space_id,
        item.memory_scope_id,
        item.source_key,
        item.document_key,
        item.chunk_key,
        item.projection_generation,
        item.kind,
        item.category,
        item.read_snapshot,
        tuple(item.tags),
        tuple(item.actor_keys),
        item.start_at,
        item.end_at,
        item.sequence_ordinal,
        item.thread_id,
        item.relative_start_ms,
        item.relative_end_ms,
    )


__all__ = (
    "LOCATOR_RETRIEVAL_CONTRACT_VERSION",
    "LOCATOR_RETRIEVAL_RANKING_POLICY",
    "CanonicalLocatorCandidate",
    "CanonicalLocatorRead",
    "CanonicalHydrationInvariantError",
    "LocatorAppliedBounds",
    "LocatorHardFilters",
    "LocatorNeighbor",
    "LocatorProviderHit",
    "LocatorProviderOutcome",
    "LocatorProviderResult",
    "LocatorProviderLaneCapability",
    "LocatorQueryVariant",
    "LocatorRelativeTimeInterval",
    "LocatorResultCandidate",
    "LocatorRetrievalBounds",
    "LocatorRetrievalCapabilityBounds",
    "LocatorRetrievalCapability",
    "LocatorRetrievalRequest",
    "LocatorRetrievalResponse",
    "LocatorRetrievalScope",
    "LocatorScoreContribution",
    "LocatorSoftPreferences",
    "LocatorSourceGeneration",
    "LocatorTimeInterval",
    "LocatorWeightedKey",
    "candidate_matches_request",
    "preference_evidence",
)
