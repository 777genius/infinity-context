"""Trusted provider-neutral capability values for locator Retrieval."""

from __future__ import annotations

from dataclasses import dataclass

LOCATOR_RETRIEVAL_ENDPOINT = "/v1/context/retrieve"
LOCATOR_RETRIEVAL_ATTRIBUTE_SCHEMA = "document-retrieval-projection.v1"
LOCATOR_RETRIEVAL_COVERAGE = "top_k_only"
LOCATOR_RETRIEVAL_RANKING_POLICY = "weighted_rrf_canonical_preferences.v1"
LOCATOR_RETRIEVAL_RANK_CONSTANT = 60
LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS = 1_000_000
LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS = 1_000_000_000_000
LOCATOR_RETRIEVAL_PREFERENCE_SCALE_MICROS = 1_000_000
LOCATOR_RETRIEVAL_MAX_PREFERENCE_BOOST_MICROS = 250_000
LOCATOR_RETRIEVAL_CONTRIBUTION_ROUNDING = "round_half_even"
LOCATOR_RETRIEVAL_PREFERENCE_ROUNDING = "floor"
LOCATOR_RETRIEVAL_SIGNAL_MATCH_POLICY = "canonical_exact_key_interval_overlap.v1"
LOCATOR_RETRIEVAL_HARD_FILTER_SIGNALS = (
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
LOCATOR_RETRIEVAL_SOFT_PREFERENCE_SIGNALS = (
    "actor_preferences",
    "relative_time_interval",
    "source_preferences",
    "time_interval",
)


@dataclass(frozen=True, slots=True)
class LocatorRetrievalCapabilityBounds:
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
        detached = []
        for name in self.__slots__:
            value = tuple(getattr(self, name))
            valid = all(isinstance(item, int) and not isinstance(item, bool) for item in value)
            if len(value) != 2 or not valid:
                raise ValueError(f"Locator capability bound {name} has invalid values")
            object.__setattr__(self, name, value)
            detached.append(value)
        actual = tuple(detached)
        canonical = (
            (1, 6),
            (1, 512),
            (1, 4),
            (1, 1_000),
            (1, 100),
            (1, 1_000),
            (1, 50),
            (0, 2),
            (16_384, 1_048_576),
            (1, 2_000),
            (100_000, 10_000_000),
        )
        if actual != canonical:
            raise ValueError("Locator capability bounds must match Retrieval")


@dataclass(frozen=True, slots=True)
class LocatorProviderLaneCapability:
    provider_id: str
    required: bool
    healthy: bool
    weight_micros: int
    profile_qualified: bool

    def __post_init__(self) -> None:
        _opaque("provider_id", self.provider_id)
        for name in ("required", "healthy", "profile_qualified"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"Locator capability {name} must be boolean")
        if not isinstance(self.weight_micros, int) or isinstance(self.weight_micros, bool):
            raise ValueError("Locator capability weight_micros must be an integer")
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("Locator capability weight_micros must be within 100000..10000000")


@dataclass(frozen=True, slots=True)
class LocatorRankingParameters:
    rank_constant: int = LOCATOR_RETRIEVAL_RANK_CONSTANT
    weight_scale_micros: int = LOCATOR_RETRIEVAL_WEIGHT_SCALE_MICROS
    score_scale_picos: int = LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS
    preference_scale_micros: int = LOCATOR_RETRIEVAL_PREFERENCE_SCALE_MICROS
    max_preference_boost_micros: int = LOCATOR_RETRIEVAL_MAX_PREFERENCE_BOOST_MICROS
    contribution_rounding: str = LOCATOR_RETRIEVAL_CONTRIBUTION_ROUNDING
    preference_rounding: str = LOCATOR_RETRIEVAL_PREFERENCE_ROUNDING
    canonical_signal_match_policy: str = LOCATOR_RETRIEVAL_SIGNAL_MATCH_POLICY

    def __post_init__(self) -> None:
        actual = tuple(getattr(self, name) for name in self.__slots__)
        expected = (
            60,
            1_000_000,
            1_000_000_000_000,
            1_000_000,
            250_000,
            "round_half_even",
            "floor",
            "canonical_exact_key_interval_overlap.v1",
        )
        if actual != expected:
            raise ValueError("Locator ranking parameters must match Retrieval")


@dataclass(frozen=True, slots=True)
class LocatorRetrievalCapability:
    """Full descriptor; the first three fields preserve the legacy constructor."""

    capability_fingerprint: str
    profile_id: str
    supports_neighbors: bool = False
    service_revision: str | None = None
    index_profile_digest: str | None = None
    provider_lanes: tuple[LocatorProviderLaneCapability, ...] = ()
    endpoint: str = LOCATOR_RETRIEVAL_ENDPOINT
    contract_version: str = "context-retrieval.v2"
    ranking_policy: str = LOCATOR_RETRIEVAL_RANKING_POLICY
    ranking_parameters: LocatorRankingParameters = LocatorRankingParameters()
    attribute_schema: str = LOCATOR_RETRIEVAL_ATTRIBUTE_SCHEMA
    coverage: str = LOCATOR_RETRIEVAL_COVERAGE
    bounds: LocatorRetrievalCapabilityBounds = LocatorRetrievalCapabilityBounds()
    hard_filter_signals: tuple[str, ...] = LOCATOR_RETRIEVAL_HARD_FILTER_SIGNALS
    soft_preference_signals: tuple[str, ...] = LOCATOR_RETRIEVAL_SOFT_PREFERENCE_SIGNALS
    required_provider_lanes: tuple[str, ...] = ()
    sdk_revision: str | None = None

    def __post_init__(self) -> None:
        _opaque("capability_fingerprint", self.capability_fingerprint)
        _lower_hex("capability_fingerprint", self.capability_fingerprint, 64)
        _opaque("profile_id", self.profile_id)
        if not isinstance(self.supports_neighbors, bool):
            raise ValueError("Locator supports_neighbors must be boolean")
        if self.endpoint != LOCATOR_RETRIEVAL_ENDPOINT:
            raise ValueError("Locator capability endpoint is unsupported")
        if self.contract_version != "context-retrieval.v2":
            raise ValueError("Locator capability contract_version is unsupported")
        if self.ranking_policy != LOCATOR_RETRIEVAL_RANKING_POLICY:
            raise ValueError("Locator capability ranking_policy is unsupported")
        if not isinstance(self.ranking_parameters, LocatorRankingParameters):
            raise ValueError("Locator capability ranking_parameters has an invalid type")
        object.__setattr__(self, "ranking_parameters", LocatorRankingParameters())
        if self.attribute_schema != LOCATOR_RETRIEVAL_ATTRIBUTE_SCHEMA:
            raise ValueError("Locator capability attribute_schema is unsupported")
        if self.coverage != LOCATOR_RETRIEVAL_COVERAGE:
            raise ValueError("Locator capability coverage is unsupported")
        if not isinstance(self.bounds, LocatorRetrievalCapabilityBounds):
            raise ValueError("Locator capability bounds have an invalid type")
        bounds = LocatorRetrievalCapabilityBounds(
            query_variants=tuple(self.bounds.query_variants),
            query_characters=tuple(self.bounds.query_characters),
            provider_lanes=tuple(self.bounds.provider_lanes),
            provider_rank=tuple(self.bounds.provider_rank),
            source_generations=tuple(self.bounds.source_generations),
            candidate_limit=tuple(self.bounds.candidate_limit),
            result_limit=tuple(self.bounds.result_limit),
            neighbor_radius=tuple(self.bounds.neighbor_radius),
            response_byte_limit=tuple(self.bounds.response_byte_limit),
            deadline_ms=tuple(self.bounds.deadline_ms),
            weight_micros=tuple(self.bounds.weight_micros),
        )
        lanes = tuple(
            LocatorProviderLaneCapability(
                item.provider_id,
                item.required,
                item.healthy,
                item.weight_micros,
                item.profile_qualified,
            )
            for item in self.provider_lanes
        )
        ids = tuple(item.provider_id for item in lanes)
        if ids != tuple(sorted(set(ids), key=canonical_string_sort_key)) or len(lanes) > 4:
            raise ValueError("Locator capability provider lanes must be sorted and unique")
        object.__setattr__(self, "provider_lanes", lanes)
        object.__setattr__(self, "bounds", bounds)
        hard = tuple(self.hard_filter_signals)
        soft = tuple(self.soft_preference_signals)
        if hard != LOCATOR_RETRIEVAL_HARD_FILTER_SIGNALS:
            raise ValueError("Locator capability hard filter signals are unsupported")
        if soft != LOCATOR_RETRIEVAL_SOFT_PREFERENCE_SIGNALS:
            raise ValueError("Locator capability soft preference signals are unsupported")
        required = tuple(self.required_provider_lanes)
        if required != tuple(item.provider_id for item in lanes if item.required):
            raise ValueError("Locator required provider lanes do not match provider lanes")
        object.__setattr__(self, "required_provider_lanes", required)
        object.__setattr__(self, "hard_filter_signals", hard)
        object.__setattr__(self, "soft_preference_signals", soft)
        is_full = (
            self.service_revision is not None
            or self.sdk_revision is not None
            or self.index_profile_digest is not None
            or bool(lanes)
        )
        if is_full:
            if self.sdk_revision is None:
                object.__setattr__(self, "sdk_revision", self.service_revision)
            _opaque("service_revision", self.service_revision)
            _opaque("sdk_revision", self.sdk_revision)
            _opaque("index_profile_digest", self.index_profile_digest)
            _lower_hex("service_revision", self.service_revision, 40)
            _lower_hex("sdk_revision", self.sdk_revision, 40)
            _lower_hex("index_profile_digest", self.index_profile_digest, 64)
            if not lanes:
                raise ValueError("Full locator capability requires provider lanes")

    @property
    def profile_qualified(self) -> bool:
        return bool(self.provider_lanes) and all(
            lane.healthy and lane.profile_qualified for lane in self.provider_lanes
        )

    @property
    def is_full_descriptor(self) -> bool:
        return bool(self.provider_lanes)


def _opaque(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"Locator {name} must be a normalized non-blank string")
    if len(value) > 256:
        raise ValueError(f"Locator {name} exceeds 256 characters")
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"Locator {name} contains invalid Unicode or controls")


def canonical_string_sort_key(value: str) -> bytes:
    """Order opaque strings lexicographically by their UTF-8 byte sequences."""

    return value.encode("utf-8")


def _lower_hex(name: str, value: object, length: int) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Locator {name} must be {length} lowercase hexadecimal characters")


__all__ = (
    "LOCATOR_RETRIEVAL_ATTRIBUTE_SCHEMA",
    "LOCATOR_RETRIEVAL_COVERAGE",
    "LOCATOR_RETRIEVAL_ENDPOINT",
    "LOCATOR_RETRIEVAL_HARD_FILTER_SIGNALS",
    "LOCATOR_RETRIEVAL_RANKING_POLICY",
    "LOCATOR_RETRIEVAL_SOFT_PREFERENCE_SIGNALS",
    "LocatorProviderLaneCapability",
    "LocatorRankingParameters",
    "LocatorRetrievalCapabilityBounds",
    "LocatorRetrievalCapability",
)
