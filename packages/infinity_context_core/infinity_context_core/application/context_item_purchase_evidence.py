"""Item-purchase lexical evidence helpers."""

from __future__ import annotations

import re

_ITEM_PURCHASE_OBJECT_RE = re.compile(
    r"\b(?:figurines?|wooden\s+dolls?|shoes?|sneakers?|items?|belongings?|"
    r"objects?|possessions?)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_VERB_RE = re.compile(
    r"\b(?:buy|bought|purchase(?:d|s|ing)?|got|picked\s+up|ordered|acquired)\b",
    re.IGNORECASE,
)
_ITEM_PURCHASE_OBJECT_EVIDENCE_RE = re.compile(
    r"\b(?:buy|bought|purchase(?:d|s|ing)?|got|picked\s+up|ordered|acquired)\b"
    r"(?=.{0,140}\b(?:figurines?|wooden\s+dolls?|shoes?|sneakers?|items?|"
    r"belongings?|objects?|possessions?)\b)|"
    r"\b(?:figurines?|wooden\s+dolls?|shoes?|sneakers?|items?|belongings?|"
    r"objects?|possessions?)\b"
    r"(?=.{0,140}\b(?:buy|bought|purchase(?:d|s|ing)?|got|picked\s+up|"
    r"ordered|acquired)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_PURCHASE_TEMPORAL_OR_MEDIA_RE = re.compile(
    r"\b(?:today|yesterday|tomorrow|last\s+\w+|ago|date:|session_\d+\s+date|"
    r"image\s+caption|visual\s+query|caption)\b",
    re.IGNORECASE,
)


def has_item_purchase_object_marker(text: str) -> bool:
    return _ITEM_PURCHASE_OBJECT_RE.search(text) is not None


def has_item_purchase_verb_marker(text: str) -> bool:
    return _ITEM_PURCHASE_VERB_RE.search(text) is not None


def has_item_purchase_object_evidence(text: str) -> bool:
    return _ITEM_PURCHASE_OBJECT_EVIDENCE_RE.search(text) is not None


def has_item_purchase_temporal_or_media_marker(text: str) -> bool:
    return _ITEM_PURCHASE_TEMPORAL_OR_MEDIA_RE.search(text) is not None
