"""Canonical source-turn label parsing for temporal source identity."""

from __future__ import annotations

import re

_DIALOGUE_NOUN_PATTERN = (
    r"(?:locomo\s+)?(?:session|conversation|conv|dialogue|dialog|dia|d)"
)
_COMPOUND_NUMBER_SUFFIX_PATTERN = (
    r"one|two|three|four|five|six|seven|eight|nine|first|second|third|"
    r"fourth|fifth|sixth|seventh|eighth|ninth"
)
_TENS_NUMBER_PATTERN = (
    rf"twenty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"thirty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"forty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"fifty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"sixty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"seventy(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"eighty(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?|"
    rf"ninety(?:[\s-]+(?:{_COMPOUND_NUMBER_SUFFIX_PATTERN}))?"
)
_NUMBER_PATTERN = (
    r"D\d{1,4}|#?\d{1,4}(?:st|nd|rd|th)?|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|"
    r"eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    r"eighteenth|nineteenth|twentieth|thirtieth|fortieth|fiftieth|"
    rf"sixtieth|seventieth|eightieth|ninetieth|{_TENS_NUMBER_PATTERN}"
)
SOURCE_TURN_LABEL_NUMBER_PATTERN = _NUMBER_PATTERN
_NATURAL_SOURCE_TURN_RE = re.compile(
    r"\b(?:source\s+)?(?:"
    rf"(?:(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_first>{_NUMBER_PATTERN})"
    r"(?:[\s,;:_/-]*)?(?:source\s+)?(?:turn|t)[\s_:-]*#?\s*"
    rf"(?P<turn_after>{_NUMBER_PATTERN}))|"
    rf"(?:(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_before_turn_noun>{_NUMBER_PATTERN})"
    r"(?:[\s,;:_/-]*)?(?P<turn_after_dialogue_before_noun>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t))|"
    r"(?:(?P<dialogue_before_session_noun>"
    rf"{_NUMBER_PATTERN})\s+(?:{_DIALOGUE_NOUN_PATTERN})"
    r"(?:[\s,;:_/-]*)?(?P<turn_after_session_noun>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t))|"
    r"(?:(?:turn|source\s+turn|t)[\s_:-]*#?\s*"
    rf"(?P<turn_first>{_NUMBER_PATTERN})"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?(?:source\s+)?"
    rf"(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_after>{_NUMBER_PATTERN}))|"
    r"(?:(?:source\s+)?(?:turn|t)[\s_:-]*#?\s*"
    rf"(?P<turn_before_session_noun>{_NUMBER_PATTERN})"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?"
    rf"(?P<dialogue_after_turn_before_session_noun>{_NUMBER_PATTERN})\s+"
    rf"(?:{_DIALOGUE_NOUN_PATTERN}))|"
    r"(?:(?:the\s+)?(?P<turn_before_label_noun>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t)"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?(?:source\s+)?"
    rf"(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_after_label_noun>{_NUMBER_PATTERN}))|"
    r"(?:(?:source\s+)?(?:turn|t)[\s_:-]*#?\s*"
    rf"(?P<turn_before_dialogue_noun>{_NUMBER_PATTERN})"
    rf"(?:[\s,;:_/-]+)(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_after_turn_dialogue_noun>{_NUMBER_PATTERN}))|"
    r"(?:(?:the\s+)?(?P<turn_before_noun>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t)"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?"
    rf"(?P<dialogue_before_noun>{_NUMBER_PATTERN})\s+"
    rf"(?:{_DIALOGUE_NOUN_PATTERN}))"
    r"|(?:(?P<turn_before_noun_reversed>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t)"
    r"(?:[\s,;:_/-]+)(?P<dialogue_after_turn_noun_reversed>"
    rf"{_NUMBER_PATTERN})\s+"
    rf"(?:{_DIALOGUE_NOUN_PATTERN}))|"
    r"(?:(?P<turn_before_dialogue_label_reversed>"
    rf"{_NUMBER_PATTERN})\s+(?:source\s+)?(?:turn|t)"
    rf"(?:[\s,;:_/-]+)(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue_after_dialogue_label_reversed>{_NUMBER_PATTERN}))"
    r")\b",
    re.IGNORECASE,
)
_NATURAL_SOURCE_TURN_PAIR_RE = re.compile(
    r"\b(?:source\s+)?(?:turn|t)[\s_:-]*#?\s*"
    rf"(?P<first_turn>{_NUMBER_PATTERN})"
    r"\s+(?P<connector>and|to|through|until)\s+"
    r"(?:the\s+)?(?:source\s+)?(?:turn|t)[\s_:-]*#?\s*"
    rf"(?P<second_turn>{_NUMBER_PATTERN})"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?(?:source\s+)?"
    rf"(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue>{_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_NATURAL_SOURCE_TURN_PLURAL_PAIR_RE = re.compile(
    r"\b(?:source\s+)?turns[\s_:-]*#?\s*"
    rf"(?P<first_turn>{_NUMBER_PATTERN})"
    r"(?:\s+(?P<connector>and|to|through|until)\s+|"
    r"\s*(?P<range_connector>-)\s*)#?\s*"
    rf"(?P<second_turn>{_NUMBER_PATTERN})"
    r"\s+(?:in|from|of|for|within)\s+(?:the\s+)?(?:source\s+)?"
    rf"(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue>{_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_NATURAL_DIALOGUE_FIRST_TURN_RANGE_RE = re.compile(
    r"\b(?:(?P<dialogue_label>D\d{1,4})|"
    rf"(?:source\s+)?(?:{_DIALOGUE_NOUN_PATTERN})[\s_:-]*#?\s*"
    rf"(?P<dialogue>{_NUMBER_PATTERN}))"
    r"\s+(?:source\s+)?turns[\s_:-]*#?\s*"
    rf"(?P<first_turn>{_NUMBER_PATTERN})"
    r"(?:\s+(?P<connector>and|to|through|until)\s+|"
    r"\s*(?P<range_connector>-)\s*)#?\s*"
    rf"(?P<second_turn>{_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_NUMBER_LABEL_PREFIX_RE = re.compile(
    rf"\b(?P<label>{_DIALOGUE_NOUN_PATTERN}|source\s+turn|turn|t)"
    r"\s+(?:number|no\.?)\s+",
    re.IGNORECASE,
)
_WORD_VALUES = {
    "one": 1,
    "first": 1,
    "two": 2,
    "second": 2,
    "three": 3,
    "third": 3,
    "four": 4,
    "fourth": 4,
    "five": 5,
    "fifth": 5,
    "six": 6,
    "sixth": 6,
    "seven": 7,
    "seventh": 7,
    "eight": 8,
    "eighth": 8,
    "nine": 9,
    "ninth": 9,
    "ten": 10,
    "tenth": 10,
    "eleven": 11,
    "eleventh": 11,
    "twelve": 12,
    "twelfth": 12,
    "thirteen": 13,
    "thirteenth": 13,
    "fourteen": 14,
    "fourteenth": 14,
    "fifteen": 15,
    "fifteenth": 15,
    "sixteen": 16,
    "sixteenth": 16,
    "seventeen": 17,
    "seventeenth": 17,
    "eighteen": 18,
    "eighteenth": 18,
    "nineteen": 19,
    "nineteenth": 19,
    "twenty": 20,
    "twentieth": 20,
    "thirty": 30,
    "thirtieth": 30,
    "forty": 40,
    "fortieth": 40,
    "fifty": 50,
    "fiftieth": 50,
    "sixty": 60,
    "sixtieth": 60,
    "seventy": 70,
    "seventieth": 70,
    "eighty": 80,
    "eightieth": 80,
    "ninety": 90,
    "ninetieth": 90,
}
_COMPOUND_TENS = frozenset(
    {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
)


def canonicalize_natural_source_turn_labels(value: str) -> str:
    value = _NUMBER_LABEL_PREFIX_RE.sub(r"\g<label> ", value)
    value = _NATURAL_DIALOGUE_FIRST_TURN_RANGE_RE.sub(
        _natural_source_turn_pair_label,
        value,
    )
    value = _NATURAL_SOURCE_TURN_PLURAL_PAIR_RE.sub(
        _natural_source_turn_pair_label,
        value,
    )
    value = _NATURAL_SOURCE_TURN_PAIR_RE.sub(_natural_source_turn_pair_label, value)
    value = _NATURAL_SOURCE_TURN_RE.sub(_natural_source_turn_label, value)
    return re.sub(r"(?<!\w)#(?=D\d{1,4}[:-]\d{1,4}\b)", "", value)


def source_turn_label_number_value(value: str) -> int:
    return _number_value(value)


def _natural_source_turn_label(match: re.Match[str]) -> str:
    dialogue = (
        match.group("dialogue_first")
        or match.group("dialogue_after")
        or match.group("dialogue_before_noun")
        or match.group("dialogue_before_turn_noun")
        or match.group("dialogue_after_turn_before_session_noun")
        or match.group("dialogue_before_session_noun")
        or match.group("dialogue_after_label_noun")
        or match.group("dialogue_after_turn_dialogue_noun")
        or match.group("dialogue_after_turn_noun_reversed")
        or match.group("dialogue_after_dialogue_label_reversed")
    )
    turn = (
        match.group("turn_after")
        or match.group("turn_first")
        or match.group("turn_before_noun")
        or match.group("turn_after_dialogue_before_noun")
        or match.group("turn_before_session_noun")
        or match.group("turn_after_session_noun")
        or match.group("turn_before_label_noun")
        or match.group("turn_before_dialogue_noun")
        or match.group("turn_before_noun_reversed")
        or match.group("turn_before_dialogue_label_reversed")
    )
    if not dialogue or not turn:
        return match.group(0)
    dialogue_value = _number_value(dialogue)
    turn_value = _number_value(turn)
    if not dialogue_value or not turn_value:
        return match.group(0)
    return f"D{dialogue_value}:{turn_value}"


def _natural_source_turn_pair_label(match: re.Match[str]) -> str:
    dialogue = match.groupdict().get("dialogue") or match.groupdict().get(
        "dialogue_label",
    )
    dialogue_value = _number_value(dialogue or "")
    first_turn_value = _number_value(match.group("first_turn"))
    second_turn_value = _number_value(match.group("second_turn"))
    if not dialogue_value or not first_turn_value or not second_turn_value:
        return match.group(0)
    connector = match.group("connector") or "to"
    return f"D{dialogue_value}:{first_turn_value} {connector} D{dialogue_value}:{second_turn_value}"


def _number_value(value: str) -> int:
    text = re.sub(r"[\s-]+", " ", value.casefold()).strip()
    text = text.removeprefix("#").strip()
    if match := re.fullmatch(r"d(?P<number>\d{1,4})", text):
        return int(match.group("number"))
    if match := re.fullmatch(r"(?P<number>\d{1,4})(?:st|nd|rd|th)?", text):
        return int(match.group("number"))
    if text in _WORD_VALUES:
        return _WORD_VALUES[text]
    parts = text.split()
    if len(parts) != 2:
        return 0
    tens, unit = parts
    return _WORD_VALUES.get(tens, 0) + (
        _WORD_VALUES.get(unit, 0) if tens in _COMPOUND_TENS else 0
    )
