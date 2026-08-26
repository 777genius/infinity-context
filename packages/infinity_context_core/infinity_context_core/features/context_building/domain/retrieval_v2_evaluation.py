"""Provider-neutral, deterministic evaluation for locator-only Retrieval V2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import TypeAlias

RETRIEVAL_V2_DATASET_SCHEMA = "generic-retrieval-v2-dataset.v1"
MAX_EVALUATED_RANK = 10

# Frozen integer approximations of 1/log2(rank + 1), scaled by 10**12. The
# resulting nDCG policy is rational and reproducible without hashing floats.
NDCG_DISCOUNT_SCALE = 1_000_000_000_000
NDCG_DISCOUNTS = (
    1_000_000_000_000,
    630_929_753_571,
    500_000_000_000,
    430_676_558_073,
    386_852_807_235,
    356_207_187_108,
    333_333_333_333,
    315_464_876_786,
    301_029_995_664,
    289_064_826_318,
)

JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = (
    JsonScalar | list["JsonValue"] | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
)


def _bounded_opaque(name: str, value: object, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-blank normalized opaque string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its maximum length")
    return value


def _nonnegative_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _unique_opaque_tuple(name: str, values: object, *, allow_empty: bool = True) -> tuple[str, ...]:
    if isinstance(values, str | bytes):
        raise ValueError(f"{name} must be a collection")
    try:
        result = tuple(_bounded_opaque(name, item) for item in values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{name} must be a collection") from error
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class Rational:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        numerator = _nonnegative_int("rational numerator", self.numerator)
        denominator = _nonnegative_int("rational denominator", self.denominator)
        if denominator == 0 and numerator != 0:
            raise ValueError("a zero rational denominator requires a zero numerator")

    @classmethod
    def from_fraction(cls, value: Fraction) -> Rational:
        if value < 0:
            raise ValueError("metric rational cannot be negative")
        return cls(value.numerator, value.denominator)

    def at_least(self, minimum: Rational) -> bool:
        if self.denominator == 0 or minimum.denominator == 0:
            return False
        return self.numerator * minimum.denominator >= minimum.numerator * self.denominator

    def to_dict(self) -> dict[str, JsonValue]:
        return {"denominator": self.denominator, "numerator": self.numerator}


@dataclass(frozen=True, slots=True)
class RankedLocator:
    locator: str
    rank: int

    def __post_init__(self) -> None:
        _bounded_opaque("ranked locator", self.locator, maximum=512)
        rank = _nonnegative_int("rank", self.rank)
        if not 1 <= rank <= MAX_EVALUATED_RANK:
            raise ValueError("rank must be within 1..10")


@dataclass(frozen=True, slots=True)
class GoldLocator:
    locator: str
    relevance: int = 1

    def __post_init__(self) -> None:
        _bounded_opaque("gold locator", self.locator, maximum=512)
        relevance = _nonnegative_int("gold relevance", self.relevance)
        if not 1 <= relevance <= 30:
            raise ValueError("gold relevance must be within 1..30")


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    case_id: str
    variation_family_id: str
    query_variant_ids: tuple[str, ...]
    gold_locators: tuple[GoldLocator, ...] = ()
    forbidden_scope_locators: tuple[str, ...] = ()
    filter_excluded_locators: tuple[str, ...] = ()
    filter_ids: tuple[str, ...] = ()
    filter_specs: tuple[tuple[str, str, str], ...] = ()
    query_texts: tuple[str, ...] = ()
    neighbor_radius: int = 0
    scenario_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_opaque("case_id", self.case_id)
        _bounded_opaque("variation_family_id", self.variation_family_id)
        if isinstance(self.query_variant_ids, str | bytes):
            raise ValueError("query_variant_ids must be a collection")
        try:
            query_ids = tuple(
                _bounded_opaque("query_variant_ids", item) for item in self.query_variant_ids
            )
        except TypeError as error:
            raise ValueError("query_variant_ids must be a collection") from error
        if not query_ids or len(set(query_ids)) != len(query_ids):
            raise ValueError("query_variant_ids must be non-empty and unique")
        raw_texts = self.query_texts or query_ids
        if isinstance(raw_texts, str | bytes):
            raise ValueError("query_texts must be a collection")
        try:
            query_texts = tuple(_bounded_opaque("query_texts", item) for item in raw_texts)
        except TypeError as error:
            raise ValueError("query_texts must be a collection") from error
        if len(query_texts) != len(query_ids):
            raise ValueError("query_texts must correspond exactly to query_variant_ids")
        query_pairs = tuple(sorted(zip(query_ids, query_texts, strict=True)))
        object.__setattr__(self, "query_variant_ids", tuple(item[0] for item in query_pairs))
        object.__setattr__(self, "query_texts", tuple(item[1] for item in query_pairs))
        if isinstance(self.gold_locators, str | bytes):
            raise ValueError("gold_locators must be a collection")
        try:
            gold = tuple(
                GoldLocator(item.locator, item.relevance)
                if isinstance(item, GoldLocator)
                else _invalid_gold()
                for item in self.gold_locators
            )
        except TypeError as error:
            raise ValueError("gold_locators must be a collection") from error
        if len({item.locator for item in gold}) != len(gold):
            raise ValueError("gold_locators must not contain duplicates")
        gold = tuple(sorted(gold, key=lambda item: item.locator))
        forbidden = _unique_opaque_tuple("forbidden_scope_locators", self.forbidden_scope_locators)
        filter_excluded = _unique_opaque_tuple(
            "filter_excluded_locators", self.filter_excluded_locators
        )
        if {item.locator for item in gold}.intersection(forbidden):
            raise ValueError("gold and forbidden-scope locators must be disjoint")
        if ({item.locator for item in gold} | set(forbidden)).intersection(filter_excluded):
            raise ValueError("gold, forbidden-scope and filter-excluded locators must be disjoint")
        object.__setattr__(self, "gold_locators", gold)
        object.__setattr__(self, "forbidden_scope_locators", forbidden)
        object.__setattr__(self, "filter_excluded_locators", filter_excluded)
        filter_ids = _unique_opaque_tuple("filter_ids", self.filter_ids)
        specs = tuple(sorted(tuple(item) for item in self.filter_specs))
        if any(len(item) != 3 for item in specs):
            raise ValueError("filter_specs must contain filter ID, field and value triples")
        for filter_id, field, value in specs:
            _bounded_opaque("filter spec id", filter_id)
            _bounded_opaque("filter spec field", field)
            _bounded_opaque("filter spec value", value)
        if specs and tuple(item[0] for item in specs) != filter_ids:
            raise ValueError("filter_specs must match filter_ids exactly")
        if not specs:
            specs = tuple((filter_id, "opaque", filter_id) for filter_id in filter_ids)
        object.__setattr__(self, "filter_ids", filter_ids)
        object.__setattr__(self, "filter_specs", specs)
        radius = _nonnegative_int("neighbor_radius", self.neighbor_radius)
        if radius not in {0, 1}:
            raise ValueError("neighbor_radius must be 0 or 1")
        object.__setattr__(
            self, "scenario_tags", _unique_opaque_tuple("scenario_tags", self.scenario_tags)
        )


def _invalid_gold() -> GoldLocator:
    raise ValueError("gold_locators contains an invalid runtime type")


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationDataset:
    dataset_id: str
    corpus_locators: tuple[str, ...]
    cases: tuple[RetrievalEvaluationCase, ...]
    schema_version: str = RETRIEVAL_V2_DATASET_SCHEMA
    records_payload: tuple[tuple[str, JsonValue], ...] = ()
    neighbor_pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _bounded_opaque("dataset_id", self.dataset_id)
        if self.schema_version != RETRIEVAL_V2_DATASET_SCHEMA:
            raise ValueError(f"schema_version must be {RETRIEVAL_V2_DATASET_SCHEMA}")
        corpus = _unique_opaque_tuple("corpus_locators", self.corpus_locators, allow_empty=False)
        if isinstance(self.cases, str | bytes):
            raise ValueError("cases must be a collection")
        try:
            cases = tuple(
                item if isinstance(item, RetrievalEvaluationCase) else _invalid_case()
                for item in self.cases
            )
        except TypeError as error:
            raise ValueError("cases must be a collection") from error
        if not cases:
            raise ValueError("cases must not be empty")
        if len({item.case_id for item in cases}) != len(cases):
            raise ValueError("case ids must be unique")
        known = set(corpus)
        referenced = {
            locator
            for case in cases
            for locator in (
                *(item.locator for item in case.gold_locators),
                *case.forbidden_scope_locators,
                *case.filter_excluded_locators,
            )
        }
        if not referenced.issubset(known):
            raise ValueError("case locators must belong to the frozen corpus")
        object.__setattr__(self, "corpus_locators", corpus)
        object.__setattr__(self, "cases", tuple(sorted(cases, key=lambda item: item.case_id)))
        try:
            records = tuple(self.records_payload)
        except TypeError as error:
            raise ValueError("records_payload must be a collection") from error
        if any(not isinstance(item, tuple) or len(item) != 2 for item in records):
            raise ValueError("records_payload must contain locator and payload pairs")
        if len({item[0] for item in records}) != len(records):
            raise ValueError("records_payload locators must be unique")
        records = tuple(sorted(records, key=lambda item: item[0]))
        if not records:
            records = tuple(
                (
                    locator,
                    {
                        "attributes": {},
                        "locator": locator,
                        "occurred_on": "date:unspecified",
                        "scope_id": "scope:test",
                        "source_id": "source:test",
                        "text": f"Synthetic record {index}",
                    },
                )
                for index, locator in enumerate(corpus)
            )
        if tuple(locator for locator, _ in records) != corpus:
            raise ValueError("records_payload must match the canonical corpus locators exactly")
        object.__setattr__(
            self,
            "records_payload",
            tuple((locator, _freeze_json(payload)) for locator, payload in records),
        )
        neighbors = tuple(sorted(tuple(sorted(tuple(pair))) for pair in self.neighbor_pairs))
        if any(len(pair) != 2 or pair[0] == pair[1] for pair in neighbors):
            raise ValueError("neighbor pairs must contain two different locators")
        if len(set(neighbors)) != len(neighbors):
            raise ValueError("neighbor pairs must be unique")
        if any(left not in known or right not in known for left, right in neighbors):
            raise ValueError("neighbor pair locators must belong to the frozen corpus")
        object.__setattr__(self, "neighbor_pairs", neighbors)


def _invalid_case() -> RetrievalEvaluationCase:
    raise ValueError("cases contains an invalid runtime type")


def _freeze_json(value: object) -> JsonValue:
    """Detach recursively so frozen domain values retain no caller-owned aliases."""

    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("record payload keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in sorted(value.items())})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("record payload contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class RetrievalObservation:
    case_id: str
    status: str
    ranked_locators: tuple[RankedLocator, ...]
    latency_us: int
    request_bytes: int
    response_bytes: int

    def __post_init__(self) -> None:
        _bounded_opaque("observation case_id", self.case_id)
        if self.status not in {"success", "failure", "timeout"}:
            raise ValueError("observation status must be success, failure or timeout")
        if isinstance(self.ranked_locators, str | bytes):
            raise ValueError("ranked_locators must be a collection")
        try:
            ranked = tuple(
                RankedLocator(item.locator, item.rank)
                if isinstance(item, RankedLocator)
                else _invalid_ranked()
                for item in self.ranked_locators
            )
        except TypeError as error:
            raise ValueError("ranked_locators must be a collection") from error
        if len({item.locator for item in ranked}) != len(ranked):
            raise ValueError("ranked_locators must not contain duplicate locators")
        groups: dict[int, int] = {}
        for item in ranked:
            groups[item.rank] = groups.get(item.rank, 0) + 1
        occupied_until = 0
        for rank, count in sorted(groups.items()):
            if rank <= occupied_until:
                raise ValueError("rank ties must use non-overlapping competition ranks")
            occupied_until = rank + count - 1
            if occupied_until > MAX_EVALUATED_RANK:
                raise ValueError("rank tie extends beyond rank 10")
        if self.status != "success" and ranked:
            raise ValueError("failed or timed-out observations cannot contain ranked locators")
        object.__setattr__(
            self,
            "ranked_locators",
            tuple(sorted(ranked, key=lambda item: (item.rank, item.locator))),
        )
        _nonnegative_int("latency_us", self.latency_us)
        _nonnegative_int("request_bytes", self.request_bytes)
        _nonnegative_int("response_bytes", self.response_bytes)


def _invalid_ranked() -> RankedLocator:
    raise ValueError("ranked_locators contains an invalid runtime type")


@dataclass(frozen=True, slots=True)
class LatencyPercentiles:
    p50_us: int
    p95_us: int
    p99_us: int


@dataclass(frozen=True, slots=True)
class ByteAccounting:
    total_request_bytes: int
    total_response_bytes: int
    maximum_request_bytes: int
    maximum_response_bytes: int


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationMetrics:
    case_count: int
    ranked_gold_case_count: int
    no_gold_case_count: int
    no_gold_with_results_count: int
    success_count: int
    failure_count: int
    timeout_count: int
    recall_at_5: Rational
    recall_at_10: Rational
    mrr_at_10: Rational
    ndcg_at_10: Rational
    cross_scope_leakage_count: int
    topology_violation_count: int
    latency: LatencyPercentiles
    bytes: ByteAccounting


def evaluate_retrieval(
    dataset: RetrievalEvaluationDataset,
    observations: tuple[RetrievalObservation, ...],
) -> RetrievalEvaluationMetrics:
    """Score every case; failures and timeouts remain in ranking denominators."""

    observation_map = _observation_map(dataset, observations)
    recall_5_found = recall_10_found = gold_total = 0
    reciprocal_rank_sum = Fraction(0, 1)
    ndcg_sum = Fraction(0, 1)
    ranked_gold_cases = no_gold_cases = no_gold_with_results = leakage = topology = 0
    failures = timeouts = successes = 0

    for case in dataset.cases:
        observation = observation_map[case.case_id]
        successes += observation.status == "success"
        failures += observation.status == "failure"
        timeouts += observation.status == "timeout"
        returned = {item.locator: item.rank for item in observation.ranked_locators}
        allowed, requested_scope = _allowed_locators(dataset, case)
        topology += sum(locator not in allowed for locator in returned)
        records = dict(dataset.records_payload)
        leakage += sum(
            locator in case.forbidden_scope_locators
            or locator not in records
            or (requested_scope is not None and records[locator].get("scope_id") != requested_scope)
            for locator in returned
        )
        if not case.gold_locators:
            no_gold_cases += 1
            no_gold_with_results += bool(returned)
            continue
        ranked_gold_cases += 1
        gold_total += len(case.gold_locators)
        recall_5_found += sum(returned.get(item.locator, 11) <= 5 for item in case.gold_locators)
        recall_10_found += sum(returned.get(item.locator, 11) <= 10 for item in case.gold_locators)
        relevant_ranks = [
            returned[item.locator] for item in case.gold_locators if item.locator in returned
        ]
        if relevant_ranks:
            reciprocal_rank_sum += Fraction(1, min(relevant_ranks))
        ndcg_sum += _case_ndcg(case, returned)

    latencies = tuple(item.latency_us for item in observation_map.values())
    request_bytes = tuple(item.request_bytes for item in observation_map.values())
    response_bytes = tuple(item.response_bytes for item in observation_map.values())
    return RetrievalEvaluationMetrics(
        case_count=len(dataset.cases),
        ranked_gold_case_count=ranked_gold_cases,
        no_gold_case_count=no_gold_cases,
        no_gold_with_results_count=no_gold_with_results,
        success_count=successes,
        failure_count=failures,
        timeout_count=timeouts,
        recall_at_5=Rational(recall_5_found, gold_total),
        recall_at_10=Rational(recall_10_found, gold_total),
        mrr_at_10=(
            Rational.from_fraction(reciprocal_rank_sum / ranked_gold_cases)
            if ranked_gold_cases
            else Rational(0, 0)
        ),
        ndcg_at_10=(
            Rational.from_fraction(ndcg_sum / ranked_gold_cases)
            if ranked_gold_cases
            else Rational(0, 0)
        ),
        cross_scope_leakage_count=leakage,
        topology_violation_count=topology,
        latency=LatencyPercentiles(
            _nearest_rank_percentile(latencies, 50),
            _nearest_rank_percentile(latencies, 95),
            _nearest_rank_percentile(latencies, 99),
        ),
        bytes=ByteAccounting(
            sum(request_bytes),
            sum(response_bytes),
            max(request_bytes, default=0),
            max(response_bytes, default=0),
        ),
    )


def _allowed_locators(
    dataset: RetrievalEvaluationDataset,
    case: RetrievalEvaluationCase,
) -> tuple[frozenset[str], str | None]:
    records = dict(dataset.records_payload)
    scope_specs = tuple(spec for spec in case.filter_specs if spec[1] == "scope_id")
    requested_scope = scope_specs[0][2] if len(scope_specs) == 1 else None
    explicitly_excluded = set(case.forbidden_scope_locators) | set(case.filter_excluded_locators)
    direct = {
        locator
        for locator, record in records.items()
        if locator not in explicitly_excluded and _record_matches(record, case.filter_specs)
    }
    allowed = set(direct)
    if case.neighbor_radius == 1:
        for left, right in dataset.neighbor_pairs:
            if left in direct and _legal_neighbor(
                right, records, explicitly_excluded, case.filter_specs
            ):
                allowed.add(right)
            if right in direct and _legal_neighbor(
                left, records, explicitly_excluded, case.filter_specs
            ):
                allowed.add(left)
    if requested_scope is not None:
        allowed = {
            locator for locator in allowed if records[locator].get("scope_id") == requested_scope
        }
    return frozenset(allowed), requested_scope


def _legal_neighbor(
    locator: str,
    records: Mapping[str, JsonValue],
    explicitly_excluded: set[str],
    specs: tuple[tuple[str, str, str], ...],
) -> bool:
    """Require a neighbor to independently pass every seed hard filter."""

    record = records.get(locator)
    return (
        locator not in explicitly_excluded
        and isinstance(record, Mapping)
        and _record_matches(record, specs)
    )


def _record_matches(
    record: Mapping[str, JsonValue], specs: tuple[tuple[str, str, str], ...]
) -> bool:
    for _, field, expected in specs:
        if field == "opaque":
            continue
        if field.startswith("attribute:"):
            attributes = record.get("attributes")
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


def _observation_map(
    dataset: RetrievalEvaluationDataset,
    observations: tuple[RetrievalObservation, ...],
) -> dict[str, RetrievalObservation]:
    if isinstance(observations, str | bytes):
        raise ValueError("observations must be a collection")
    if any(not isinstance(item, RetrievalObservation) for item in observations):
        raise ValueError("observations contains an invalid runtime type")
    result = {item.case_id: item for item in observations}
    if len(result) != len(observations):
        raise ValueError("observation case ids must be unique")
    expected = {item.case_id for item in dataset.cases}
    if set(result) != expected:
        raise ValueError("observations must match dataset case ids exactly")
    return {case_id: result[case_id] for case_id in sorted(result)}


def _case_ndcg(case: RetrievalEvaluationCase, returned: dict[str, int]) -> Fraction:
    gains_by_locator = {item.locator: (1 << item.relevance) - 1 for item in case.gold_locators}
    ranked_groups: dict[int, list[str]] = {}
    for locator, rank in returned.items():
        ranked_groups.setdefault(rank, []).append(locator)
    dcg = Fraction(0, 1)
    for rank, locators in ranked_groups.items():
        tie_discount = Fraction(
            sum(NDCG_DISCOUNTS[index] for index in range(rank - 1, rank - 1 + len(locators))),
            len(locators),
        )
        dcg += sum(gains_by_locator.get(locator, 0) for locator in locators) * tie_discount
    ideal_gains = sorted(gains_by_locator.values(), reverse=True)[:MAX_EVALUATED_RANK]
    ideal = sum(gain * NDCG_DISCOUNTS[index] for index, gain in enumerate(ideal_gains))
    return dcg / ideal if ideal else Fraction(0, 1)


def _nearest_rank_percentile(values: tuple[int, ...], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = (percentile * len(ordered) + 99) // 100
    return ordered[max(1, index) - 1]


__all__ = (
    "ByteAccounting",
    "GoldLocator",
    "JsonValue",
    "LatencyPercentiles",
    "MAX_EVALUATED_RANK",
    "NDCG_DISCOUNTS",
    "NDCG_DISCOUNT_SCALE",
    "RETRIEVAL_V2_DATASET_SCHEMA",
    "RankedLocator",
    "Rational",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationDataset",
    "RetrievalEvaluationMetrics",
    "RetrievalObservation",
    "evaluate_retrieval",
)
