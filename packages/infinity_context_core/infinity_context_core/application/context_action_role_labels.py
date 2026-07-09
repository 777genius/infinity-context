"""Label normalization helpers for action-role rerank policy."""

from __future__ import annotations

import re

LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
QUERY_LABEL_RE = r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]{1,39}"

_QUERY_LABEL_STOP_WORDS = frozenset(
    {
        "did",
        "has",
        "what",
        "who",
        "whom",
        "whose",
        "anybody",
        "anyone",
        "buy",
        "people",
        "person",
        "eat",
        "follow",
        "listen",
        "last",
        "latest",
        "make",
        "newest",
        "play",
        "read",
        "recent",
        "somebody",
        "someone",
        "start",
        "take",
        "try",
        "use",
        "visit",
        "watch",
        "что",
        "кто",
        "кого",
        "кому",
    }
)
_TEXT_LABEL_STOP_WORDS = _QUERY_LABEL_STOP_WORDS.union(
    {
        "project",
        "transcript",
    }
)
_DIRECT_RECIPIENT_OBJECT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "badge",
        "book",
        "camera",
        "car",
        "charger",
        "decision",
        "doc",
        "document",
        "email",
        "file",
        "image",
        "invoice",
        "link",
        "laptop",
        "message",
        "note",
        "notes",
        "photo",
        "plan",
        "report",
        "screenshot",
        "story",
        "task",
        "the",
        "ticket",
        "to",
        "update",
        "wallet",
    }
)


def label_pattern(label: str) -> str:
    return rf"(?<!\w){re.escape(label)}(?!\w)"


def role_label_pattern(label: str) -> str:
    if not re.search(r"[А-Яа-яЁё]", label):
        return label_pattern(label)
    stem = _russian_label_stem(label)
    if len(stem) < 3 or stem == label:
        return label_pattern(label)
    return rf"(?<!\w)(?:{re.escape(label)}|{re.escape(stem)}[А-Яа-яЁё]{{0,4}})(?!\w)"


def recipient_label_pattern(label: str, *, verb_key: str) -> str:
    if verb_key == "help":
        return role_label_pattern(label)
    return label_pattern(label)


def clean_label(value: str) -> str:
    label = (value or "").strip(" :,.!?;")
    if not label:
        return ""
    if normalized_label(label) in _TEXT_LABEL_STOP_WORDS:
        return ""
    return label


def looks_like_direct_recipient(label: str) -> bool:
    if not label:
        return False
    if label[:1].isupper():
        return True
    return normalized_label(label) not in _DIRECT_RECIPIENT_OBJECT_STOP_WORDS


def looks_like_text_recipient(label: str) -> bool:
    return bool(label) and label[:1].isupper() and looks_like_direct_recipient(label)


def recipient_in_tail(tail: str) -> str:
    match = re.search(
        rf"\b(?:to|for)\s+(?P<recipient>{QUERY_LABEL_RE})\b",
        tail,
        re.IGNORECASE,
    )
    if match is None:
        return ""
    return clean_label(match.group("recipient"))


def object_label_in_text(value: str) -> str:
    labels: list[str] = []
    for match in re.finditer(rf"\b(?P<label>{QUERY_LABEL_RE})\b", value):
        label = clean_label(match.group("label"))
        if label:
            labels.append(label)
    return labels[-1] if labels else ""


def normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _russian_label_stem(label: str) -> str:
    for suffix in (
        "иями",
        "ями",
        "ами",
        "ого",
        "ему",
        "ыми",
        "ими",
        "ом",
        "ем",
        "ой",
        "ей",
        "ую",
        "ю",
        "а",
        "я",
        "е",
        "ы",
        "и",
    ):
        if label.casefold().endswith(suffix) and len(label) > len(suffix) + 2:
            return label[: -len(suffix)]
    return label
