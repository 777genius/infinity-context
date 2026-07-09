"""Typed answer-unit shape helpers for retrieval evidence ranking."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache

_NUMBER_VALUE = (
    r"\d+(?:\.\d+)?|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|a|an"
)
_NUMBER_VALUE_RE = rf"(?:{_NUMBER_VALUE})"

_AGE_QUERY_RE = re.compile(
    r"\bhow\s+old\b|"
    r"\bwhat\b.{0,48}\bage\b|"
    r"\bage\b.{0,48}\b(?:is|was|of)\b",
    re.IGNORECASE | re.DOTALL,
)
_DURATION_QUERY_RE = re.compile(
    r"\bhow\s+long\b|\bduration\b|\bfor\s+how\s+many\b|\bhow\s+many\b",
    re.IGNORECASE,
)
_DISTANCE_QUERY_RE = re.compile(
    r"\bhow\s+far\b|\bdistance\b|\bhow\s+many\b",
    re.IGNORECASE,
)
_QUANTITY_QUERY_RE = re.compile(
    r"\bhow\s+(?:many|much)\b|\bwhat\b.{0,64}\b"
    r"(?:amount|quantity|total|cost|price|value|fee|deposit|budget|"
    r"salary|rent|payment)\b",
    re.IGNORECASE | re.DOTALL,
)
_MONEY_VALUE_QUERY_RE = re.compile(
    r"\bhow\s+much\b.{0,80}\b(?:cost|costs|paid|pay|spent|spend|"
    r"charge|charged|fee|deposit|rent|salary|budget|payment)\b|"
    r"\bwhat\b.{0,80}\b(?:amount|cost|price|value|fee|deposit|budget|"
    r"salary|rent|payment)\b|"
    r"\b(?:amount|cost|price|value|fee|deposit|budget|salary|rent|payment)\b"
    r".{0,40}\b(?:dollar|dollars|usd|\$)\b",
    re.IGNORECASE | re.DOTALL,
)

_AGE_UNITS = (
    ("year", ("year", "years", "yr", "yrs")),
    ("month", ("month", "months", "mo", "mos")),
)
_DURATION_UNITS = (
    ("year", ("year", "years", "yr", "yrs")),
    ("month", ("month", "months", "mo", "mos")),
    ("week", ("week", "weeks", "wk", "wks")),
    ("day", ("day", "days")),
    ("hour", ("hour", "hours", "hr", "hrs")),
    ("minute", ("minute", "minutes", "min", "mins")),
)
_DISTANCE_UNITS = (
    ("mile", ("mile", "miles", "mi")),
    ("kilometer", ("kilometer", "kilometers", "kilometre", "kilometres", "km")),
    ("meter", ("meter", "meters", "metre", "metres", "m")),
    ("foot", ("foot", "feet", "ft")),
)
_QUANTITY_UNITS = (
    ("cup", ("cup", "cups")),
    ("ounce", ("ounce", "ounces", "oz")),
    ("pound", ("pound", "pounds", "lb", "lbs")),
    ("gram", ("gram", "grams", "g")),
    ("kilogram", ("kilogram", "kilograms", "kg")),
    ("liter", ("liter", "liters", "litre", "litres", "l")),
    ("milliliter", ("milliliter", "milliliters", "millilitre", "millilitres", "ml")),
    ("dollar", ("dollar", "dollars", "usd")),
)


def requested_answer_unit_shapes(query: str) -> tuple[str, ...]:
    """Return precise answer-unit shapes requested by the query."""

    shapes: list[str] = []
    if _AGE_QUERY_RE.search(query):
        shapes.append(f"age_{_first_unit_match(query, _AGE_UNITS) or 'year'}")
    elif _DURATION_QUERY_RE.search(query):
        shapes.extend(
            f"duration_{unit}" for unit in _unit_matches(query, _DURATION_UNITS)
        )
    if _DISTANCE_QUERY_RE.search(query):
        shapes.extend(f"distance_{unit}" for unit in _unit_matches(query, _DISTANCE_UNITS))
    if _QUANTITY_QUERY_RE.search(query):
        quantity_units = _unit_matches(query, _QUANTITY_UNITS)
        if not quantity_units and _MONEY_VALUE_QUERY_RE.search(query):
            quantity_units = ("dollar",)
        shapes.extend(f"quantity_{unit}" for unit in quantity_units)
    return _bounded_unique(shapes)


def covered_answer_unit_shapes(text: str) -> tuple[str, ...]:
    """Return precise answer-unit shapes stated by evidence text."""

    shapes: list[str] = []
    for unit, aliases in _AGE_UNITS:
        if _age_evidence_re(aliases, allow_unitless=unit == "year").search(text):
            shapes.append(f"age_{unit}")
    for unit, aliases in _DURATION_UNITS:
        if _duration_evidence_re(aliases).search(text):
            shapes.append(f"duration_{unit}")
    for unit, aliases in _DISTANCE_UNITS:
        if _numbered_unit_re(aliases).search(text):
            shapes.append(f"distance_{unit}")
    for unit, aliases in _QUANTITY_UNITS:
        if _quantity_evidence_re(unit=unit, aliases=aliases).search(text):
            shapes.append(f"quantity_{unit}")
    return _bounded_unique(shapes)


def is_typed_answer_unit_shape(shape: str) -> bool:
    return shape.startswith(("age_", "duration_", "distance_", "quantity_"))


def _first_unit_match(
    text: str,
    units: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    return next(iter(_unit_matches(text, units)), "")


def _unit_matches(
    text: str,
    units: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[str, ...]:
    return _bounded_unique(
        unit for unit, aliases in units if _unit_alias_re(aliases).search(text)
    )


@cache
def _age_evidence_re(
    aliases: tuple[str, ...],
    *,
    allow_unitless: bool,
) -> re.Pattern[str]:
    unit = _unit_alias_pattern(aliases)
    unitless = (
        rf"|\bage\s*(?:is|was|:)?\s*{_NUMBER_VALUE_RE}\b"
        rf"|\bturn(?:ed|s|ing)?\s+{_NUMBER_VALUE_RE}\b"
        if allow_unitless
        else ""
    )
    return re.compile(
        rf"\b{_NUMBER_VALUE_RE}\s+{unit}\s+old\b|"
        rf"\bage\s*(?:is|was|:)?\s*{_NUMBER_VALUE_RE}\s+{unit}\b"
        rf"{unitless}",
        re.IGNORECASE,
    )


@cache
def _duration_evidence_re(aliases: tuple[str, ...]) -> re.Pattern[str]:
    unit = _unit_alias_pattern(aliases)
    return re.compile(
        rf"\b(?:for|over|about|around|nearly|almost|approximately|approx\.?|"
        rf"lasted|lasting|duration(?:\s+of)?|spent|practiced|worked|known|"
        rf"married|dated|lived)\s+{_NUMBER_VALUE_RE}\s+{unit}\b|"
        rf"\b{_NUMBER_VALUE_RE}\s+{unit}\s+"
        rf"(?:long|duration|period|stretch|of|in|after|before|later|ago)\b",
        re.IGNORECASE,
    )


@cache
def _quantity_evidence_re(*, unit: str, aliases: tuple[str, ...]) -> re.Pattern[str]:
    unit_pattern = _unit_alias_pattern(aliases)
    currency_value = r"\$\s*\d+(?:\.\d+)?\b|" if unit == "dollar" else ""
    return re.compile(
        rf"{currency_value}"
        rf"\b{_NUMBER_VALUE_RE}\s+{unit_pattern}\b",
        re.IGNORECASE,
    )


@cache
def _numbered_unit_re(aliases: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        rf"\b{_NUMBER_VALUE_RE}\s+{_unit_alias_pattern(aliases)}\b",
        re.IGNORECASE,
    )


@cache
def _unit_alias_re(aliases: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(rf"\b{_unit_alias_pattern(aliases)}\b", re.IGNORECASE)


def _unit_alias_pattern(aliases: tuple[str, ...]) -> str:
    return r"(?:" + "|".join(re.escape(alias) for alias in aliases) + r")"


def _bounded_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
