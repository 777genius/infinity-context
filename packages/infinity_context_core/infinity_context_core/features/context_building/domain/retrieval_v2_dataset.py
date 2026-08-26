"""Strict canonical fixture loading for generic Retrieval V2 evaluation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from infinity_context_core.features.context_building.domain.retrieval_v2_evaluation import (
    RETRIEVAL_V2_DATASET_SCHEMA,
    GoldLocator,
    JsonValue,
    RetrievalEvaluationCase,
    RetrievalEvaluationDataset,
)

_TOP_LEVEL = {"cases", "dataset_id", "neighbors", "records", "schema_version"}
_RECORD = {"attributes", "locator", "occurred_on", "scope_id", "source_id", "text"}
_NEIGHBOR = {"left_locator", "right_locator"}
_CASE = {
    "case_id",
    "filter_excluded_locators",
    "filters",
    "forbidden_scope_locators",
    "gold_locators",
    "neighbor_radius",
    "queries",
    "scenario_tags",
    "variation_family_id",
}
_QUERY = {"query_id", "text"}
_FILTER = {"field", "filter_id", "value"}
_GOLD = {"locator", "relevance"}


def load_retrieval_evaluation_dataset(path: Path) -> RetrievalEvaluationDataset:
    """Load exact UTF-8 JSON and reject any non-canonical fixture authority."""

    if not isinstance(path, Path):
        raise ValueError("dataset path must be a pathlib.Path")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("dataset fixture cannot be read as UTF-8") from error
    return parse_retrieval_evaluation_dataset(raw)


def parse_retrieval_evaluation_dataset(raw: str) -> RetrievalEvaluationDataset:
    if not isinstance(raw, str):
        raise ValueError("dataset fixture must be JSON text")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("dataset fixture is malformed JSON") from error
    root = _object("dataset", payload, _TOP_LEVEL)
    if root["schema_version"] != RETRIEVAL_V2_DATASET_SCHEMA:
        raise ValueError(f"schema_version must be {RETRIEVAL_V2_DATASET_SCHEMA}")
    dataset_id = _text("dataset_id", root["dataset_id"])
    records, record_payload = _load_records(root["records"])
    neighbors = _load_neighbors(root["neighbors"], set(records))
    cases = _load_cases(root["cases"])
    dataset = RetrievalEvaluationDataset(
        dataset_id=dataset_id,
        corpus_locators=tuple(records),
        cases=cases,
        schema_version=RETRIEVAL_V2_DATASET_SCHEMA,
        records_payload=record_payload,
        neighbor_pairs=neighbors,
    )
    validate_fixture_topology(dataset)
    return dataset


def validate_fixture_topology(dataset: RetrievalEvaluationDataset) -> None:
    """Prove expected sets obey canonical filters, scope and one-hop neighbors."""

    records = {locator: value for locator, value in dataset.records_payload}
    adjacency: dict[str, set[str]] = {locator: set() for locator in records}
    for left, right in dataset.neighbor_pairs:
        adjacency[left].add(right)
        adjacency[right].add(left)
    for case in dataset.cases:
        scope_filters = [spec for spec in case.filter_specs if spec[1] == "scope_id"]
        if len(scope_filters) != 1:
            raise ValueError(f"case {case.case_id} must have exactly one scope_id filter")
        requested_scope = scope_filters[0][2]
        explicitly_excluded = set(case.forbidden_scope_locators) | set(
            case.filter_excluded_locators
        )
        direct = {
            locator
            for locator, record in records.items()
            if locator not in explicitly_excluded and _matches_filters(record, case.filter_specs)
        }
        allowed = set(direct)
        if case.neighbor_radius == 1:
            allowed.update(
                neighbor
                for locator in direct
                for neighbor in adjacency[locator]
                if neighbor not in explicitly_excluded
                and _matches_filters(records[neighbor], case.filter_specs)
            )
        for gold in case.gold_locators:
            if gold.locator not in allowed:
                raise ValueError(
                    f"gold locator violates filters or neighbor semantics: {gold.locator}"
                )
            if records[gold.locator]["scope_id"] != requested_scope:
                raise ValueError(f"gold locator substitutes scope authority: {gold.locator}")
        for locator in case.forbidden_scope_locators:
            if records[locator]["scope_id"] == requested_scope:
                raise ValueError(f"forbidden-scope locator is not cross-scope: {locator}")
        non_scope = tuple(spec for spec in case.filter_specs if spec[1] != "scope_id")
        for locator in case.filter_excluded_locators:
            record = records[locator]
            if record["scope_id"] != requested_scope:
                raise ValueError(f"filter-excluded locator substitutes scope authority: {locator}")
            if not non_scope or _matches_filters(record, non_scope):
                raise ValueError(
                    f"filter-excluded locator is not excluded by a hard filter: {locator}"
                )


def _load_records(
    value: object,
) -> tuple[dict[str, dict[str, JsonValue]], tuple[tuple[str, JsonValue], ...]]:
    rows = _array("records", value, allow_empty=False)
    records: dict[str, dict[str, JsonValue]] = {}
    for index, value in enumerate(rows):
        row = _object(f"records[{index}]", value, _RECORD)
        locator = _text("record locator", row["locator"])
        if locator in records:
            raise ValueError(f"duplicate record locator: {locator}")
        attributes = _string_map("record attributes", row["attributes"])
        records[locator] = {
            "attributes": attributes,
            "locator": locator,
            "occurred_on": _text("record occurred_on", row["occurred_on"]),
            "scope_id": _text("record scope_id", row["scope_id"]),
            "source_id": _text("record source_id", row["source_id"]),
            "text": _text("record text", row["text"], maximum=2000),
        }
    ordered = dict(sorted(records.items()))
    return ordered, tuple((locator, payload) for locator, payload in ordered.items())


def _load_neighbors(value: object, known: set[str]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(_array("neighbors", value)):
        row = _object(f"neighbors[{index}]", item, _NEIGHBOR)
        left = _text("neighbor left_locator", row["left_locator"])
        right = _text("neighbor right_locator", row["right_locator"])
        if left not in known or right not in known:
            raise ValueError("neighbor references a nonexistent record")
        pair = tuple(sorted((left, right)))
        if left == right:
            raise ValueError("neighbor relation cannot be self-referential")
        pairs.append(pair)
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate neighbor relation")
    return tuple(sorted(pairs))


def _load_cases(value: object) -> tuple[RetrievalEvaluationCase, ...]:
    rows = _array("cases", value, allow_empty=False)
    cases: list[RetrievalEvaluationCase] = []
    case_ids: set[str] = set()
    query_ids: set[str] = set()
    filter_authority: dict[str, tuple[str, str]] = {}
    for index, value in enumerate(rows):
        row = _object(f"cases[{index}]", value, _CASE)
        case_id = _text("case_id", row["case_id"])
        if case_id in case_ids:
            raise ValueError(f"duplicate case ID: {case_id}")
        case_ids.add(case_id)
        queries: list[tuple[str, str]] = []
        for query_index, value in enumerate(_array("queries", row["queries"], allow_empty=False)):
            query = _object(f"queries[{query_index}]", value, _QUERY)
            query_id = _text("query_id", query["query_id"])
            if query_id in query_ids:
                raise ValueError(f"duplicate query ID: {query_id}")
            query_ids.add(query_id)
            queries.append((query_id, _text("natural query text", query["text"], maximum=1000)))
        filters: list[tuple[str, str, str]] = []
        for filter_index, value in enumerate(_array("filters", row["filters"], allow_empty=False)):
            item = _object(f"filters[{filter_index}]", value, _FILTER)
            spec = (
                _text("filter_id", item["filter_id"]),
                _text("filter field", item["field"]),
                _text("filter value", item["value"]),
            )
            if spec[1] not in {"scope_id", "source_id", "occurred_on"} and not spec[1].startswith(
                "attribute:"
            ):
                raise ValueError(f"unsupported filter field: {spec[1]}")
            previous = filter_authority.setdefault(spec[0], spec[1:])
            if previous != spec[1:]:
                raise ValueError(f"filter authority substitution: {spec[0]}")
            filters.append(spec)
        cases.append(
            RetrievalEvaluationCase(
                case_id=case_id,
                variation_family_id=_text("variation_family_id", row["variation_family_id"]),
                query_variant_ids=tuple(item[0] for item in queries),
                query_texts=tuple(item[1] for item in queries),
                gold_locators=tuple(_load_gold(row["gold_locators"])),
                forbidden_scope_locators=_text_array(
                    "forbidden_scope_locators", row["forbidden_scope_locators"]
                ),
                filter_excluded_locators=_text_array(
                    "filter_excluded_locators", row["filter_excluded_locators"]
                ),
                filter_ids=tuple(item[0] for item in filters),
                filter_specs=tuple(filters),
                neighbor_radius=_integer(
                    "neighbor_radius", row["neighbor_radius"], minimum=0, maximum=1
                ),
                scenario_tags=_text_array("scenario_tags", row["scenario_tags"], allow_empty=False),
            )
        )
    return tuple(cases)


def _load_gold(value: object) -> tuple[GoldLocator, ...]:
    gold: list[GoldLocator] = []
    for index, item in enumerate(_array("gold_locators", value)):
        row = _object(f"gold_locators[{index}]", item, _GOLD)
        gold.append(
            GoldLocator(
                _text("gold locator", row["locator"]),
                _integer("gold relevance", row["relevance"], minimum=1, maximum=30),
            )
        )
    return tuple(gold)


def _matches_filters(record: JsonValue, specs: tuple[tuple[str, str, str], ...]) -> bool:
    if not isinstance(record, Mapping):
        raise ValueError("canonical record payload is malformed")
    for _, field, expected in specs:
        if field.startswith("attribute:"):
            attributes = record["attributes"]
            actual = (
                attributes.get(field.removeprefix("attribute:"))
                if isinstance(attributes, Mapping)
                else None
            )
        else:
            actual = record.get(field)
        if actual != expected:
            return False
    return True


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> None:
    raise ValueError(f"floating-point values are forbidden: {value}")


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite numbers are forbidden: {value}")


def _object(name: str, value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ValueError(f"{name} fields mismatch; missing={missing}; unknown={unknown}")
    return value


def _array(name: str, value: object, *, allow_empty: bool = True) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _text(name: str, value: object, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be normalized non-blank text")
    return value


def _text_array(name: str, value: object, *, allow_empty: bool = True) -> tuple[str, ...]:
    result = tuple(_text(name, item) for item in _array(name, value, allow_empty=allow_empty))
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate IDs")
    return result


def _string_map(name: str, value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return {
        _text(f"{name} key", key): _text(f"{name} value", item)
        for key, item in sorted(value.items())
    }


def _integer(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer within {minimum}..{maximum}")
    return value


__all__ = (
    "load_retrieval_evaluation_dataset",
    "parse_retrieval_evaluation_dataset",
    "validate_fixture_topology",
)
