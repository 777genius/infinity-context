"""Conservative auto-memory admission and rule-based candidate extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from memo_stack_core.domain.entities import (
    Confidence,
    MemoryKind,
    SourceRef,
    TrustLevel,
)
from memo_stack_core.ports.auto_memory import (
    MemoryCandidate,
    MemoryClassifierPort,
    SourceProvenance,
)

_MAX_CANDIDATES = 5
_MAX_CANDIDATE_CHARS = 800
_ASSISTANT_SOURCES = {"ai_response", "assistant_answer", "assistant_summary"}
_PREFIXES: tuple[tuple[re.Pattern[str], MemoryKind, str, str | None, str | None], ...] = (
    (
        re.compile(r"^\s*(?:remember|remember this|запомни|запомнить)\s*[:：-]\s*(.+)$", re.I),
        MemoryKind.NOTE,
        "explicit_remember_marker",
        None,
        None,
    ),
    (
        re.compile(
            (
                r"^\s*(?:decision|architecture decision|решение|"
                r"архитектурное решение)\s*[:：-]\s*(.+)$"
            ),
            re.I,
        ),
        MemoryKind.ARCHITECTURE_DECISION,
        "explicit_decision_marker",
        None,
        None,
    ),
    (
        re.compile(r"^\s*(?:constraint|ограничение|важное ограничение)\s*[:：-]\s*(.+)$", re.I),
        MemoryKind.CONSTRAINT,
        "explicit_constraint_marker",
        None,
        None,
    ),
    (
        re.compile(r"^\s*(?:preference|user preference|предпочтение)\s*[:：-]\s*(.+)$", re.I),
        MemoryKind.USER_PREFERENCE,
        "explicit_preference_marker",
        None,
        None,
    ),
    (
        re.compile(
            r"^\s*(?:current task|task note|текущая задача|заметка задачи)\s*[:：-]\s*(.+)$",
            re.I,
        ),
        MemoryKind.NOTE,
        "explicit_current_task_marker",
        "current_task",
        "task",
    ),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions\b", re.I),
    re.compile(r"\b(system|developer)\s+prompt\b", re.I),
    re.compile(r"\breveal\s+(?:the\s+)?(?:system|developer)\s+(?:prompt|message)\b", re.I),
    re.compile(r"\bforget\s+(?:all\s+)?(?:rules|instructions)\b", re.I),
    re.compile(r"\bскрой\s+инструкц", re.I),
    re.compile(r"\bраскр(?:ой|ыть)\s+системн", re.I),
    re.compile(r"\bигнорируй\s+(?:все\s+)?(?:предыдущие|прошлые)\s+инструкц", re.I),
)


@dataclass(frozen=True)
class AdmissionDecision:
    outcome: str
    trust_level: TrustLevel
    confidence: Confidence
    reason: str


class MemoryAdmissionService:
    """Admission policy for unsafe auto-memory paths.

    Core Lite never auto-promotes classifier output. The decision is explicit so
    future policies can add auto-promote without changing ingest orchestration.
    """

    def decide(
        self,
        *,
        source: SourceProvenance,
        candidate: MemoryCandidate,
        allow_auto_promote: bool = False,
    ) -> AdmissionDecision:
        if not candidate.text.strip():
            return AdmissionDecision("ignore", TrustLevel.LOW, Confidence.LOW, "empty_candidate")
        if _looks_like_prompt_injection(candidate.text):
            return AdmissionDecision(
                "source_only",
                source.trust_level,
                Confidence.LOW,
                "prompt_injection_text",
            )
        if source.source_type in _ASSISTANT_SOURCES:
            return AdmissionDecision(
                "create_suggestion",
                TrustLevel.LOW,
                Confidence.LOW,
                "assistant_low_trust",
            )
        if allow_auto_promote and source.trust_level == TrustLevel.HIGH:
            return AdmissionDecision(
                "create_active_fact",
                TrustLevel.HIGH,
                candidate.confidence,
                "manual_source",
            )
        return AdmissionDecision(
            "create_suggestion",
            source.trust_level,
            candidate.confidence,
            candidate.safe_reason,
        )


class NoopMemoryClassifier:
    async def classify(self, *, text: str, source: SourceProvenance) -> tuple[MemoryCandidate, ...]:
        return ()


class RuleBasedMemoryClassifier(MemoryClassifierPort):
    """Small deterministic classifier for explicit memory markers.

    This is intentionally conservative. It only produces review suggestions when
    the transcript/document explicitly marks durable memory.
    """

    async def classify(self, *, text: str, source: SourceProvenance) -> tuple[MemoryCandidate, ...]:
        candidates: list[MemoryCandidate] = []
        for line in _candidate_lines(text):
            candidate = _candidate_from_line(line=line, source=source)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) >= _MAX_CANDIDATES:
                break
        return tuple(candidates)


def _candidate_from_line(
    *,
    line: str,
    source: SourceProvenance,
) -> MemoryCandidate | None:
    for pattern, kind, reason, category, ttl_policy in _PREFIXES:
        match = pattern.match(line)
        if not match:
            continue
        text = _clean_candidate_text(match.group(1))
        if not text:
            return None
        return MemoryCandidate(
            text=text,
            kind=kind,
            confidence=Confidence.MEDIUM,
            source_refs=(
                SourceRef(
                    source_type=source.source_type,
                    source_id=source.source_id,
                    chunk_id=source.chunk_id,
                    quote_preview=text[:240],
                ),
            ),
            safe_reason=reason,
            category=category,
            ttl_policy=ttl_policy,
        )
    return None


def _candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if line:
            lines.append(line)
    if len(lines) == 1 and not _has_memory_prefix(lines[0]):
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return lines


def _clean_candidate_text(text: str) -> str:
    return " ".join(text.strip().split())[:_MAX_CANDIDATE_CHARS].strip()


def _looks_like_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS)


def _has_memory_prefix(line: str) -> bool:
    return any(pattern.match(line) for pattern, _, _, _, _ in _PREFIXES)
