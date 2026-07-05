"""Adapter-neutral context candidate records."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.public import (
    ContextCandidateRequest,
    ContextEvidence,
    ContextItem,
    ContextSourceRef,
)

from infinity_context_adapters.features.context_building.query_request import (
    ContextCandidateAdapterQuery,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateRecord:
    """Storage/provider-neutral record that can become a core ContextItem."""

    item_id: str
    space_id: str
    memory_scope_id: str
    text: str
    source_refs: tuple[ContextSourceRef, ...]
    thread_id: str | None = None
    kind: str = "memory"
    role: str = "supporting_evidence"
    priority: int = 0
    score: float = 0.0
    estimated_tokens: int | None = None
    tags: tuple[str, ...] = ()
    evidence_id: str | None = None
    trust_level: str = "untrusted"
    confidence: str = "unknown"
    temporal_label: str | None = None

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("Context candidate record requires an item id")
        if not self.space_id.strip():
            raise ValueError("Context candidate record requires a space id")
        if not self.memory_scope_id.strip():
            raise ValueError("Context candidate record requires a memory scope id")
        if self.thread_id is not None and not self.thread_id.strip():
            raise ValueError("Context candidate record thread id cannot be blank")
        if not self.text.strip():
            raise ValueError("Context candidate record requires text")
        if not self.source_refs:
            raise ValueError("Context candidate record requires source refs")
        if self.estimated_tokens is not None and self.estimated_tokens < 1:
            raise ValueError("Context candidate record token estimate must be positive")

    def matches_request(
        self,
        request: ContextCandidateRequest | ContextCandidateAdapterQuery,
    ) -> bool:
        """Return whether this candidate is eligible for the requested scope."""

        adapter_query = (
            request
            if isinstance(request, ContextCandidateAdapterQuery)
            else ContextCandidateAdapterQuery.from_candidate_request(request)
        )
        scope = adapter_query.scope
        if self.space_id != scope.space_id:
            return False
        if self.memory_scope_id != scope.memory_scope_id:
            return False
        if scope.thread_id is not None and self.thread_id not in (None, scope.thread_id):
            return False
        if adapter_query.tags and not _has_tag_overlap(adapter_query.tags, self.tags):
            return False
        return True

    def to_context_item(self) -> ContextItem:
        """Convert the adapter record into the feature-owned port DTO."""

        evidence = ContextEvidence(
            text=self.text,
            source_refs=self.source_refs,
            evidence_id=self.evidence_id,
            trust_level=self.trust_level,
            confidence=self.confidence,
            temporal_label=self.temporal_label,
            relevance_score=self.score,
        )
        return ContextItem(
            item_id=self.item_id,
            text=self.text,
            evidence=(evidence,),
            kind=self.kind,
            role=self.role,
            priority=self.priority,
            score=self.score,
            estimated_tokens=self.estimated_tokens,
            tags=self.tags,
        )


def _has_tag_overlap(
    requested_tags: tuple[str, ...],
    record_tags: tuple[str, ...],
) -> bool:
    record_tag_set = {tag.casefold() for tag in record_tags}
    return any(tag.casefold() in record_tag_set for tag in requested_tags)


__all__ = ("ContextCandidateRecord",)
