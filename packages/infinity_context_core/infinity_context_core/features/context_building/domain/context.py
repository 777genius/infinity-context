"""Prompt context domain shapes owned by the context_building feature."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

ContextItemKind: TypeAlias = str
ContextItemRole: TypeAlias = str
ContextTrustLevel: TypeAlias = str
ContextConfidence: TypeAlias = str
ContextDropReason: TypeAlias = str


@dataclass(frozen=True, slots=True)
class ContextScope:
    """Scope ownership for context assembly without storage concerns."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContextQuery:
    """User request and scope used to gather prompt evidence."""

    scope: ContextScope
    text: str
    intent: str = "answer"
    as_of: datetime | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextSourceRef:
    """Pointer to canonical evidence that supports a context item."""

    source_type: str
    source_id: str
    chunk_id: str | None = None
    fact_id: str | None = None
    document_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """Evidence text plus source labels kept separate from instructions."""

    text: str
    source_refs: tuple[ContextSourceRef, ...]
    evidence_id: str | None = None
    trust_level: ContextTrustLevel = "untrusted"
    confidence: ContextConfidence = "unknown"
    temporal_label: str | None = None
    relevance_score: float = 0.0

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Context evidence requires text")
        if not self.source_refs:
            raise ValueError("Context evidence requires at least one source ref")


@dataclass(frozen=True, slots=True)
class ContextItem:
    """Prompt-ready memory candidate with evidence and ranking metadata."""

    item_id: str
    text: str
    evidence: tuple[ContextEvidence, ...]
    kind: ContextItemKind = "memory"
    role: ContextItemRole = "supporting_evidence"
    priority: int = 0
    score: float = 0.0
    estimated_tokens: int | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("Context item requires an item id")
        if not self.text.strip():
            raise ValueError("Context item requires text")
        if not self.evidence:
            raise ValueError("Context item requires evidence")
        if self.estimated_tokens is not None and self.estimated_tokens < 1:
            raise ValueError("Context item token estimate must be positive")

    @property
    def token_cost(self) -> int:
        """Return the explicit estimate or a conservative stdlib-only fallback."""

        if self.estimated_tokens is not None:
            return self.estimated_tokens
        return estimate_token_count(self.text)


@dataclass(frozen=True, slots=True)
class ContextDroppedItem:
    """Context candidate excluded from the rendered bundle with a safe reason."""

    item_id: str
    reason: ContextDropReason
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """Prompt-ready evidence package produced by the context builder."""

    query: ContextQuery
    items: tuple[ContextItem, ...]
    dropped_items: tuple[ContextDroppedItem, ...] = ()
    rendered_evidence: str = ""
    max_prompt_tokens: int | None = None
    total_estimated_tokens: int = 0


def estimate_token_count(text: str) -> int:
    """Approximate token count without a provider tokenizer dependency."""

    normalized = " ".join(text.split())
    if not normalized:
        return 0
    return max(1, (len(normalized) + 3) // 4)


__all__ = (
    "ContextBundle",
    "ContextConfidence",
    "ContextDropReason",
    "ContextDroppedItem",
    "ContextEvidence",
    "ContextItem",
    "ContextItemKind",
    "ContextItemRole",
    "ContextQuery",
    "ContextScope",
    "ContextSourceRef",
    "ContextTrustLevel",
    "estimate_token_count",
)
