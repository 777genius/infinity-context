"""Strict JSON parser for the canonical Retrieval response envelope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._context_building_retrieval import (
    RetrievalAppliedBoundsDto,
    RetrievalCandidateDto,
    RetrievalContributionDto,
    RetrievalNeighborDto,
    RetrievalProviderOutcomeDto,
    RetrieveContextResponseDto,
)


def parse_retrieve_context_response(
    payload: Mapping[str, object],
) -> RetrieveContextResponseDto:
    _keys(
        payload,
        {
            "contract_version",
            "ranking_policy",
            "status",
            "capability_fingerprint",
            "profile_id",
            "coverage",
            "applied_bounds",
            "candidates",
            "provider_outcomes",
            "degradation_reason_codes",
        },
        "response",
    )
    bounds = _mapping(payload.get("applied_bounds"), "applied_bounds")
    _keys(
        bounds,
        {
            "candidate_limit",
            "result_limit",
            "neighbor_radius",
            "response_byte_limit",
            "deadline_ms",
            "returned_seeds",
            "returned_neighbors",
        },
        "applied_bounds",
    )
    return RetrieveContextResponseDto(
        status=_string(payload, "status"),
        capability_fingerprint=_string(payload, "capability_fingerprint"),
        profile_id=_string(payload, "profile_id"),
        applied_bounds=RetrievalAppliedBoundsDto(
            candidate_limit=_integer(bounds, "candidate_limit", "applied_bounds"),
            result_limit=_integer(bounds, "result_limit", "applied_bounds"),
            neighbor_radius=_integer(bounds, "neighbor_radius", "applied_bounds"),
            response_byte_limit=_integer(bounds, "response_byte_limit", "applied_bounds"),
            deadline_ms=_integer(bounds, "deadline_ms", "applied_bounds"),
            returned_seeds=_integer(bounds, "returned_seeds", "applied_bounds"),
            returned_neighbors=_integer(bounds, "returned_neighbors", "applied_bounds"),
        ),
        candidates=tuple(
            _candidate(item, index) for index, item in enumerate(_objects(payload, "candidates"))
        ),
        provider_outcomes=tuple(
            _outcome(item, index)
            for index, item in enumerate(_objects(payload, "provider_outcomes"))
        ),
        degradation_reason_codes=_strings(payload, "degradation_reason_codes"),
        contract_version=_string(payload, "contract_version"),
        ranking_policy=_string(payload, "ranking_policy"),
        coverage=_string(payload, "coverage"),
    )


def _candidate(payload: Mapping[str, object], index: int) -> RetrievalCandidateDto:
    path = f"candidates.{index}"
    _keys(
        payload,
        {
            "locator",
            "source_key",
            "document_key",
            "chunk_key",
            "canonical_identity",
            "canonical_version",
            "lifecycle_status",
            "relation",
            "distance",
            "provider_rank",
            "fused_score",
            "base_score_picos",
            "source_requested_weight_micros",
            "source_matched_weight_micros",
            "actor_requested_weight_micros",
            "actor_matched_weight_micros",
            "time_requested_weight_micros",
            "time_matched_weight_micros",
            "preference_score_micros",
            "preference_boost_micros",
            "rerank_score_picos",
            "matched_query_ids",
            "contributions",
            "neighbors",
        },
        path,
    )
    return RetrievalCandidateDto(
        locator=_string(payload, "locator", path),
        source_key=_string(payload, "source_key", path),
        document_key=_string(payload, "document_key", path),
        chunk_key=_string(payload, "chunk_key", path),
        canonical_identity=_string(payload, "canonical_identity", path),
        canonical_version=_integer(payload, "canonical_version", path),
        lifecycle_status=_string(payload, "lifecycle_status", path),
        relation=_string(payload, "relation", path),
        distance=_integer(payload, "distance", path),
        provider_rank=_integer(payload, "provider_rank", path),
        fused_score=_number(payload, "fused_score", path),
        base_score_picos=_integer(payload, "base_score_picos", path),
        source_requested_weight_micros=_integer(payload, "source_requested_weight_micros", path),
        source_matched_weight_micros=_integer(payload, "source_matched_weight_micros", path),
        actor_requested_weight_micros=_integer(payload, "actor_requested_weight_micros", path),
        actor_matched_weight_micros=_integer(payload, "actor_matched_weight_micros", path),
        time_requested_weight_micros=_integer(payload, "time_requested_weight_micros", path),
        time_matched_weight_micros=_integer(payload, "time_matched_weight_micros", path),
        preference_score_micros=_integer(payload, "preference_score_micros", path),
        preference_boost_micros=_integer(payload, "preference_boost_micros", path),
        rerank_score_picos=_integer(payload, "rerank_score_picos", path),
        matched_query_ids=_strings(payload, "matched_query_ids", path),
        contributions=tuple(
            _contribution(item, path, nested)
            for nested, item in enumerate(_objects(payload, "contributions", path))
        ),
        neighbors=tuple(
            _neighbor(item, path, nested)
            for nested, item in enumerate(_objects(payload, "neighbors", path))
        ),
    )


def _contribution(
    payload: Mapping[str, object], candidate_path: str, index: int
) -> RetrievalContributionDto:
    path = f"{candidate_path}.contributions.{index}"
    _keys(
        payload,
        {
            "provider_id",
            "query_id",
            "provider_rank",
            "provider_weight_micros",
            "query_weight_micros",
            "contribution_score_picos",
            "provider_weight",
            "query_weight",
            "contribution",
            "raw_score_kind",
            "raw_score_value",
        },
        path,
    )
    raw_kind = payload.get("raw_score_kind")
    raw_value = payload.get("raw_score_value")
    return RetrievalContributionDto(
        provider_id=_string(payload, "provider_id", path),
        query_id=_string(payload, "query_id", path),
        provider_rank=_integer(payload, "provider_rank", path),
        provider_weight_micros=_integer(payload, "provider_weight_micros", path),
        query_weight_micros=_integer(payload, "query_weight_micros", path),
        contribution_score_picos=_integer(payload, "contribution_score_picos", path),
        provider_weight=_number(payload, "provider_weight", path),
        query_weight=_number(payload, "query_weight", path),
        contribution=_number(payload, "contribution", path),
        raw_score_kind=(None if raw_kind is None else _string(payload, "raw_score_kind", path)),
        raw_score_value=(None if raw_value is None else _number(payload, "raw_score_value", path)),
    )


def _neighbor(
    payload: Mapping[str, object], candidate_path: str, index: int
) -> RetrievalNeighborDto:
    path = f"{candidate_path}.neighbors.{index}"
    _keys(
        payload,
        {
            "locator",
            "source_key",
            "document_key",
            "chunk_key",
            "canonical_identity",
            "canonical_version",
            "lifecycle_status",
            "relation",
            "distance",
        },
        path,
    )
    return RetrievalNeighborDto(
        locator=_string(payload, "locator", path),
        source_key=_string(payload, "source_key", path),
        document_key=_string(payload, "document_key", path),
        chunk_key=_string(payload, "chunk_key", path),
        canonical_identity=_string(payload, "canonical_identity", path),
        canonical_version=_integer(payload, "canonical_version", path),
        lifecycle_status=_string(payload, "lifecycle_status", path),
        relation=_string(payload, "relation", path),
        distance=_integer(payload, "distance", path),
    )


def _outcome(payload: Mapping[str, object], index: int) -> RetrievalProviderOutcomeDto:
    path = f"provider_outcomes.{index}"
    _keys(payload, {"provider_id", "status", "reason_code"}, path)
    reason = payload.get("reason_code")
    return RetrievalProviderOutcomeDto(
        provider_id=_string(payload, "provider_id", path),
        status=_string(payload, "status", path),
        reason_code=None if reason is None else _string(payload, "reason_code", path),
    )


def _keys(payload: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{path} fields do not match the canonical contract")


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _objects(
    payload: Mapping[str, object], name: str, path: str = ""
) -> tuple[Mapping[str, object], ...]:
    values = _sequence(payload.get(name), f"{path}.{name}" if path else name)
    if not all(isinstance(item, Mapping) for item in values):
        raise ValueError(f"{path}.{name} contains an invalid value")
    return tuple(values)  # type: ignore[return-value]


def _strings(payload: Mapping[str, object], name: str, path: str = "") -> tuple[str, ...]:
    values = _sequence(payload.get(name), f"{path}.{name}" if path else name)
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{path}.{name} contains an invalid value")
    return tuple(values)


def _sequence(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{path} must be an array")
    return value


def _string(payload: Mapping[str, object], name: str, path: str = "") -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str, path: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{name} must be an integer")
    return value


def _number(payload: Mapping[str, object], name: str, path: str) -> float:
    value = payload.get(name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{path}.{name} must be numeric")
    return float(value)


__all__ = ("parse_retrieve_context_response",)
