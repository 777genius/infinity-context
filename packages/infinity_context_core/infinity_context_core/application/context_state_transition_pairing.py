"""Pure chronology policy for evidence-backed state transitions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from infinity_context_core.application.dto import ContextItem

_CANONICAL_DATE_KEYS = ("event_valid_from", "occurred_at", "event_date")
_CANONICAL_DATE_RE = re.compile(
    r"^\s*(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})(?:[Tt ].*)?\s*$"
)
_QUOTE_DATE_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z0-9][A-Za-z0-9._:-]*)\s+date\s*:\s*"
    r"(?P<value>\d{4}/\d{2}/\d{2})(?=\D|$)",
    re.IGNORECASE,
)
_RATIO_PAIR_RE = re.compile(
    r"\b(?P<left>[a-z][a-z0-9]*)\s*(?:-|/|\s)+to(?:-|/|\s)+"
    r"(?P<right>[a-z][a-z0-9]*)\s+ratio\b",
    re.IGNORECASE,
)
_PER_RELATION_RE = re.compile(
    r"\b(?:(?:more|less|higher|lower)\s+)?"
    r"(?P<numerator>[a-z][a-z0-9]*)\s+(?:per|for\s+(?:each|every))\s+"
    r"(?:(?:a|an|one|the)\s+)?[a-z][a-z0-9]*\s+(?:of\s+)?"
    r"(?P<denominator>[a-z][a-z0-9]*)\b",
    re.IGNORECASE,
)
_PER_UNIT_TOKEN_RE = re.compile(r"\b(?:per|for\s+(?:each|every))\b", re.IGNORECASE)
_RELATION_CONNECTOR_PATTERN = r"(?:per|for\s+(?:each|every))"
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
_MEASUREMENT_VALUE_PATTERN = (
    r"\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten"
)
_MEASUREMENT_UNIT_PATTERN = (
    r"(?:fluid\s+)?ounces?|oz|tablespoons?|tbsp|teaspoons?|tsp|"
    r"millilit(?:er|re)s?|ml|lit(?:er|re)s?|l|grams?|g|kilograms?|kg|"
    r"pounds?|lbs?|cups?|spoons?|scoops?"
)
_UNIT_ALIASES = {
    "fluid ounce": "ounce",
    "fluid ounces": "ounce",
    "ounce": "ounce",
    "ounces": "ounce",
    "oz": "ounce",
    "tablespoon": "tablespoon",
    "tablespoons": "tablespoon",
    "tbsp": "tablespoon",
    "teaspoon": "teaspoon",
    "teaspoons": "teaspoon",
    "tsp": "teaspoon",
    "milliliter": "milliliter",
    "milliliters": "milliliter",
    "millilitre": "milliliter",
    "millilitres": "milliliter",
    "ml": "milliliter",
    "liter": "liter",
    "liters": "liter",
    "litre": "liter",
    "litres": "liter",
    "l": "liter",
    "gram": "gram",
    "grams": "gram",
    "g": "gram",
    "kilogram": "kilogram",
    "kilograms": "kilogram",
    "kg": "kilogram",
    "pound": "pound",
    "pounds": "pound",
    "lb": "pound",
    "lbs": "pound",
    "cup": "cup",
    "cups": "cup",
    "spoon": "spoon",
    "spoons": "spoon",
    "scoop": "scoop",
    "scoops": "scoop",
}


@dataclass(frozen=True, slots=True)
class StateTransitionPairCandidate:
    """One eligible, direct measurement candidate supplied by the caller."""

    item_index: int
    item: ContextItem
    source_identity: str


@dataclass(frozen=True, slots=True)
class _StateObservation:
    candidate: StateTransitionPairCandidate
    source_identity: str
    measurement_value: tuple[tuple[str, str, str], ...]
    semantic_date: date


def infer_state_transition_roles(
    *,
    query: str,
    candidates: tuple[StateTransitionPairCandidate, ...],
) -> dict[int, str]:
    """Return chronological roles only when an evidence pair is unambiguous.

    The caller provides direct measurement candidates. This policy independently
    validates source identity, query relation, normalized values, and semantic
    chronology so downstream selection never infers a state change from ranking
    order, ingestion timestamps, or dates embedded in body text.
    """

    relation_terms = _query_relation_terms(query)
    if len(candidates) < 2 or not relation_terms:
        return {}
    if len({candidate.item_index for candidate in candidates}) != len(candidates):
        return {}
    if any(not _normalized_identity(candidate.source_identity) for candidate in candidates):
        return {}

    observations: list[_StateObservation] = []
    for candidate in candidates:
        if not _matches_query_relation(candidate.item.text, relation_terms):
            continue
        measurement_value = _relation_local_measurement_value(
            candidate.item.text,
            relation_terms,
        )
        semantic_date = _semantic_date(candidate.item)
        if not measurement_value or semantic_date is None:
            return {}
        observations.append(
            _StateObservation(
                candidate=candidate,
                source_identity=_normalized_identity(candidate.source_identity),
                measurement_value=measurement_value,
                semantic_date=semantic_date,
            )
        )

    collapsed_observations = _collapse_source_mirrors(observations)
    if collapsed_observations is None or len(collapsed_observations) < 2:
        return {}
    if len(
        {observation.source_identity for observation in collapsed_observations}
    ) != len(collapsed_observations):
        return {}
    if len(
        {observation.measurement_value for observation in collapsed_observations}
    ) != len(collapsed_observations):
        return {}
    if len(
        {observation.semantic_date for observation in collapsed_observations}
    ) != len(collapsed_observations):
        return {}

    latest_two = sorted(
        collapsed_observations,
        key=lambda observation: observation.semantic_date,
    )[-2:]
    previous, current = latest_two
    return {
        previous.candidate.item_index: "previous_state",
        current.candidate.item_index: "current_state",
    }


def _query_relation_terms(query: str) -> frozenset[str]:
    if not isinstance(query, str) or not _PER_UNIT_TOKEN_RE.search(query):
        return frozenset()

    pairs: list[frozenset[str]] = []
    for match in _RATIO_PAIR_RE.finditer(query):
        pair = _normalized_pair(match.group("left"), match.group("right"))
        if pair:
            pairs.append(pair)
    for match in _PER_RELATION_RE.finditer(query):
        pair = _normalized_pair(match.group("numerator"), match.group("denominator"))
        if pair:
            pairs.append(pair)
    if not pairs:
        return frozenset()

    first = pairs[0]
    return first if all(pair == first for pair in pairs) else frozenset()


def _normalized_pair(first: str, second: str) -> frozenset[str]:
    terms = frozenset(term for value in (first, second) if (term := _normalized_term(value)))
    return terms if len(terms) == 2 else frozenset()


def _normalized_term(value: str) -> str:
    normalized = value.casefold().strip()
    if len(normalized) > 3 and normalized.endswith("ies"):
        normalized = f"{normalized[:-3]}y"
    elif len(normalized) > 3 and normalized.endswith("s"):
        normalized = normalized[:-1]
    return normalized


def _matches_query_relation(text: str, relation_terms: frozenset[str]) -> bool:
    if not isinstance(text, str) or not _PER_UNIT_TOKEN_RE.search(text):
        return False
    return all(
        re.search(rf"\b{re.escape(term)}s?\b", text, re.IGNORECASE) for term in relation_terms
    )


def _relation_local_measurement_value(
    text: str,
    relation_terms: frozenset[str],
) -> tuple[tuple[str, str, str], ...]:
    """Return one relation-bound signature, excluding unrelated chunk amounts."""

    if len(relation_terms) != 2:
        return ()
    first_term, second_term = sorted(relation_terms)
    signatures: set[tuple[tuple[str, str, str], ...]] = set()
    for left_term, right_term in (
        (first_term, second_term),
        (second_term, first_term),
    ):
        pattern = _relation_measurement_pattern(left_term, right_term)
        for match in pattern.finditer(text):
            left_measurement = _normalized_measurement(
                value=match.group("left_value"),
                unit=match.group("left_unit"),
            )
            right_measurement = _normalized_measurement(
                value=match.group("right_value"),
                unit=match.group("right_unit"),
            )
            if left_measurement is None or right_measurement is None:
                continue
            signatures.add(
                tuple(
                    sorted(
                        (
                            (left_term, *left_measurement),
                            (right_term, *right_measurement),
                        )
                    )
                )
            )
    return next(iter(signatures)) if len(signatures) == 1 else ()


def _relation_measurement_pattern(left_term: str, right_term: str) -> re.Pattern[str]:
    return re.compile(
        rf"\b(?P<left_value>{_MEASUREMENT_VALUE_PATTERN})\s*"
        rf"(?P<left_unit>{_MEASUREMENT_UNIT_PATTERN})\s+(?:of\s+)?"
        rf"{_term_pattern(left_term)}\s+{_RELATION_CONNECTOR_PATTERN}\s+"
        rf"(?P<right_value>{_MEASUREMENT_VALUE_PATTERN})\s*"
        rf"(?P<right_unit>{_MEASUREMENT_UNIT_PATTERN})\s+(?:of\s+)?"
        rf"{_term_pattern(right_term)}\b",
        re.IGNORECASE,
    )


def _term_pattern(term: str) -> str:
    return rf"{re.escape(term)}s?"


def _normalized_measurement(*, value: str, unit: str) -> tuple[str, str] | None:
    normalized_value = _normalized_number(value)
    normalized_unit = _UNIT_ALIASES.get(unit.casefold())
    if normalized_value is None or normalized_unit is None:
        return None
    return normalized_value, normalized_unit


def _collapse_source_mirrors(
    observations: list[_StateObservation],
) -> tuple[_StateObservation, ...] | None:
    """Keep one exact source mirror and reject same-source disagreement."""

    by_source: dict[str, _StateObservation] = {}
    for observation in observations:
        existing = by_source.get(observation.source_identity)
        if existing is None:
            by_source[observation.source_identity] = observation
            continue
        if (
            existing.semantic_date != observation.semantic_date
            or existing.measurement_value != observation.measurement_value
        ):
            return None
    return tuple(by_source.values())


def _normalized_number(value: str) -> str | None:
    word_value = _NUMBER_WORDS.get(value.casefold())
    if word_value is not None:
        return word_value
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None
    return str(decimal_value.normalize())


def _semantic_date(item: ContextItem) -> date | None:
    canonical_dates = _canonical_dates(item)
    if canonical_dates is None:
        return None
    if canonical_dates:
        return next(iter(canonical_dates))
    return _anchored_quote_date(item)


def _canonical_dates(item: ContextItem) -> frozenset[date] | None:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, Mapping) else {}
    mappings = (diagnostics, _mapping_value(diagnostics.get("provenance")))
    values: set[date] = set()
    for mapping in mappings:
        for key in _CANONICAL_DATE_KEYS:
            raw_value = mapping.get(key)
            if raw_value is None or raw_value == "":
                continue
            parsed = _parse_canonical_date(raw_value)
            if parsed is None:
                return None
            values.add(parsed)
    return frozenset(values) if len(values) <= 1 else None


def _mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _parse_canonical_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    match = _CANONICAL_DATE_RE.fullmatch(value)
    if not match:
        return None
    return _date_from_parts(match.group("year"), match.group("month"), match.group("day"))


def _anchored_quote_date(item: ContextItem) -> date | None:
    quote_dates: list[date] = []
    for ref in item.source_refs:
        quote_preview = ref.quote_preview
        if not isinstance(quote_preview, str):
            continue
        match = _QUOTE_DATE_RE.match(quote_preview)
        if match is None or not _source_id_has_label_suffix(ref.source_id, match.group("label")):
            continue
        parsed = _date_from_parts(*match.group("value").split("/"))
        if parsed is None:
            return None
        quote_dates.append(parsed)
    return quote_dates[0] if len(quote_dates) == 1 else None


def _source_id_has_label_suffix(source_id: str, label: str) -> bool:
    normalized_source = str(source_id).strip().casefold()
    normalized_label = label.strip().casefold()
    if (
        not normalized_source
        or not normalized_label
        or not normalized_source.endswith(normalized_label)
    ):
        return False
    prefix = normalized_source[: -len(normalized_label)]
    return not prefix or prefix[-1] in ":/#._-"


def _date_from_parts(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _normalized_identity(value: str) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


__all__ = ("StateTransitionPairCandidate", "infer_state_transition_roles")
