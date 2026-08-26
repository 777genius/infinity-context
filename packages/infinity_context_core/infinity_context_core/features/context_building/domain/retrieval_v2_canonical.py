"""Canonical serialization policy for Retrieval V2 evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from infinity_context_core.features.context_building.domain.retrieval_v2_evaluation import (
    JsonValue,
    RetrievalEvaluationDataset,
)


def canonical_json(value: JsonValue) -> str:
    plain = _plain_json(value)
    return json.dumps(plain, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(value: JsonValue) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def evaluation_dataset_digest(dataset: RetrievalEvaluationDataset) -> str:
    if not isinstance(dataset, RetrievalEvaluationDataset):
        raise ValueError("dataset has an invalid runtime type")
    return canonical_sha256(dataset_payload(dataset))


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def dataset_payload(dataset: RetrievalEvaluationDataset) -> dict[str, JsonValue]:
    return {
        "cases": [
            {
                "case_id": case.case_id,
                "filter_excluded_locators": list(case.filter_excluded_locators),
                "filters": [
                    {"field": field, "filter_id": filter_id, "value": value}
                    for filter_id, field, value in case.filter_specs
                ],
                "forbidden_scope_locators": list(case.forbidden_scope_locators),
                "gold_locators": [
                    {"locator": item.locator, "relevance": item.relevance}
                    for item in case.gold_locators
                ],
                "neighbor_radius": case.neighbor_radius,
                "queries": [
                    {"query_id": query_id, "text": text}
                    for query_id, text in zip(case.query_variant_ids, case.query_texts, strict=True)
                ],
                "scenario_tags": list(case.scenario_tags),
                "variation_family_id": case.variation_family_id,
            }
            for case in dataset.cases
        ],
        "dataset_id": dataset.dataset_id,
        "neighbors": [
            {"left_locator": left, "right_locator": right} for left, right in dataset.neighbor_pairs
        ],
        "records": [_plain_json(value) for _, value in dataset.records_payload],
        "schema_version": dataset.schema_version,
    }


def _plain_json(value: object) -> JsonValue:
    if isinstance(value, float):
        raise ValueError("floating-point values are forbidden in hashed evaluation evidence")
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, list | tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical evaluation JSON keys must be strings")
        return {key: _plain_json(item) for key, item in value.items()}
    raise ValueError("hashed evaluation evidence contains a non-JSON value")


__all__ = (
    "canonical_json",
    "canonical_sha256",
    "dataset_payload",
    "evaluation_dataset_digest",
    "sha256_bytes",
)
