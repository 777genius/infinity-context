"""State lifecycle evidence markers for temporal retrieval decisions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_core.application.dto import ContextItem

_STATUS_KEYS = ("fact_status", "anchor_status", "relation_status", "state_status")
_ACTIVE_STATUSES = frozenset({"active", "current"})
_STALE_STATUSES = frozenset(
    {
        "deleted",
        "deprecated",
        "expired",
        "inactive",
        "obsolete",
        "stale",
        "superseded",
    }
)
_LIFECYCLE_STATUSES = frozenset((*_ACTIVE_STATUSES, *_STALE_STATUSES, "disputed"))
_STATE_NOUN = (
    r"provider|tool|model|option|engine|database|service|plan|policy|"
    r"decision|choice|source|endpoint|token|rule|setting|config|"
    r"requirement|scope|memory|note|fact|meeting|call|demo|event|date|time"
)
_RU_STATE_NOUN = (
    r"провайдер\w*|инструмент\w*|модел\w*|вариант\w*|движок\w*|"
    r"баз\w+\s+данн\w*|сервис\w*|план\w*|политик\w*|решени\w*|"
    r"выбор\w*|источник\w*|эндпоинт\w*|токен\w*|правил\w*|"
    r"настройк\w*|конфиг\w*|требовани\w*|скоуп\w*|памят\w*|"
    r"заметк\w*|факт\w*"
)
_ACTIVE_STATE_TEXT_RE = re.compile(
    r"\b(?:current|currently|active|recommended|preferred|selected|chosen|"
    r"settled|final|canonical|source\s+of\s+truth)\b|"
    r"\b(?:still|remain(?:s|ed)?|kept)\b"
    r"(?=.{0,80}\b(?:valid|active|current|recommended|preferred|use|using|"
    r"available|chosen|selected|option|plan|provider|tool|model|policy)\b)|"
    r"\b(?:актуальн\w*|текущ\w*|выбранн\w*|финальн\w*|окончательн\w*)\b|"
    r"\b(?:вс[её]\s+еще|вс[её]\s+ещ[её]|по-прежнему|остается|остался|"
    r"осталась|остались)\b"
    r"(?=.{0,80}\b(?:актуал|действует|валидн|использовать|выбран|"
    r"вариант|план|провайдер|инструмент|модель|политик)\w*)",
    re.IGNORECASE | re.DOTALL,
)
_STALE_STATE_TEXT_RE = re.compile(
    r"\b(?:no\s+longer|anymore|any\s+longer|not\s+current)\b"
    r"(?=.{0,80}\b(?:valid|active|current|recommended|preferred|use|using|"
    r"available|chosen|selected|option|plan|provider|tool|model|policy)\b)|"
    r"\b(?:stale|outdated|obsolete|deprecated|expired|superseded)\b|"
    rf"\b(?:previous|prior|old|former)\s+(?:\w+\s+){{0,3}}(?:{_STATE_NOUN})\b|"
    rf"\b(?:{_STATE_NOUN})\b(?=.{0,60}\b(?:previous|prior|old|former)\b)|"
    r"\bpreviously\s+valid\b|"
    r"\b(?:больше\s+не|уже\s+не|перестал\w*)\b"
    r"(?=.{0,80}\b(?:актуал|действует|валидн|использовать|выбран|"
    r"вариант|план|провайдер|инструмент|модель|политик)\w*)|"
    r"\bустаревш\w*\b|"
    rf"\b(?:стар\w*|предыдущ\w*)\s+(?:\w+\s+){{0,3}}(?:{_RU_STATE_NOUN})\b|"
    rf"\b(?:{_RU_STATE_NOUN})\b(?=.{0,60}\b(?:стар\w*|предыдущ\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRANSITION_STATE_TEXT_RE = re.compile(
    r"\bchanged?\b(?=.{0,80}\bfrom\b)(?=.{0,120}\bto\b)|"
    r"\b(?:provider|tool|model|plan|policy|decision|source|option|choice|"
    r"date|time|meeting|call|demo|event)\b(?=.{0,160}\bnot\b.{0,80}\bbut\b)|"
    r"\bnot\b(?=.{0,80}\bbut\b)(?=.{0,160}\b(?:provider|tool|model|plan|"
    r"policy|decision|source|option|choice|date|time|meeting|call|demo|event)\b)|"
    r"\b(?:switch(?:ed|ing)?|migrat(?:e|ed|ing)|transition(?:ed|ing)?)\b"
    r"(?=.{0,100}\b(?:from|to)\b)|"
    r"\breplac(?:e|ed|ing)\b(?=.{0,100}\b(?:by|with|from|to|instead\s+of)\b)|"
    r"\bsuperseded\b(?=.{0,100}\bby\b)|"
    r"\b(?:cancell?ed|rescheduled|postponed|moved|delayed)\b"
    r"(?=.{0,140}\b(?:to|for|until|from|after|instead|new|now|current|"
    r"latest|date|time|day|week|month|meeting|call|demo|event|plan)\b)|"
    r"\b(?:изменил\w*|изменилось|обновил\w*|заменил\w*|поменял\w*|"
    r"сменил\w*|переключил\w*|переш[её]л\w*|мигрировал\w*)\b"
    r"(?=.{0,100}\b(?:с|со|на|вместо)\b)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class StateEvidenceMarkers:
    """Bounded lifecycle markers derived from metadata and item text."""

    metadata_active: bool = False
    metadata_stale: bool = False
    metadata_lifecycle: bool = False
    review_only: bool = False
    text_active: bool = False
    text_stale: bool = False
    text_transition: bool = False

    @property
    def has_lifecycle(self) -> bool:
        return (
            self.metadata_lifecycle
            or self.text_active
            or self.text_stale
            or self.text_transition
        )

    @property
    def has_active_state(self) -> bool:
        return self.metadata_active or self.text_active

    @property
    def has_previous_state(self) -> bool:
        return self.review_only or self.metadata_stale or self.text_stale or self.text_transition

    @property
    def stale_only(self) -> bool:
        return (
            self.review_only or self.metadata_stale or self.text_stale
        ) and not self.has_active_state and not self.text_transition


def state_evidence_markers(item: ContextItem) -> StateEvidenceMarkers:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, Mapping) else {}
    provenance = _safe_mapping(diagnostics.get("provenance"))
    metadata_active, metadata_stale, metadata_lifecycle = _metadata_state_markers(
        diagnostics,
        provenance,
    )
    if str(diagnostics.get("retrieval_source") or "") == "superseded_review":
        metadata_stale = True
        metadata_lifecycle = True
    text_active, text_stale, text_transition = state_text_markers(item.text)
    return StateEvidenceMarkers(
        metadata_active=metadata_active,
        metadata_stale=metadata_stale,
        metadata_lifecycle=metadata_lifecycle,
        review_only=diagnostics.get("review_only") is True,
        text_active=text_active,
        text_stale=text_stale,
        text_transition=text_transition,
    )


def state_text_markers(text: str) -> tuple[bool, bool, bool]:
    """Return active/stale/transition markers without exposing raw regex details."""

    text_active = bool(_ACTIVE_STATE_TEXT_RE.search(text))
    text_stale = bool(_STALE_STATE_TEXT_RE.search(text))
    text_transition = bool(_TRANSITION_STATE_TEXT_RE.search(text))
    return text_active, text_stale, text_transition


def item_has_state_lifecycle_evidence(item: ContextItem) -> bool:
    return state_evidence_markers(item).has_lifecycle


def _metadata_state_markers(
    diagnostics: Mapping[str, object],
    provenance: Mapping[str, object],
) -> tuple[bool, bool, bool]:
    metadata_active = False
    metadata_stale = False
    metadata_lifecycle = False
    for value in (diagnostics, provenance):
        active, stale, lifecycle = _mapping_state_markers(value)
        metadata_active = metadata_active or active
        metadata_stale = metadata_stale or stale
        metadata_lifecycle = metadata_lifecycle or lifecycle
    return metadata_active, metadata_stale, metadata_lifecycle


def _safe_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_state_markers(value: Mapping[str, object]) -> tuple[bool, bool, bool]:
    metadata_active = False
    metadata_stale = False
    metadata_lifecycle = False
    for key in _STATUS_KEYS:
        status = str(value.get(key) or "").strip().casefold()
        if status in _ACTIVE_STATUSES:
            metadata_active = True
            metadata_lifecycle = True
        elif status in _STALE_STATUSES:
            metadata_stale = True
            metadata_lifecycle = True
        elif status in _LIFECYCLE_STATUSES:
            metadata_lifecycle = True
    if value.get("is_current") is True:
        metadata_active = True
        metadata_lifecycle = True
    elif value.get("is_current") is False:
        metadata_stale = True
        metadata_lifecycle = True
    return metadata_active, metadata_stale, metadata_lifecycle
