"""Chunking value objects and policy for source documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from infinity_context_core.features.document_ingestion.domain.errors import (
    DocumentIngestionValidationError,
)
from infinity_context_core.features.document_ingestion.domain.source_document import (
    DocumentIngestionScope,
    content_hash_for_text,
    normalize_document_text,
)

DocumentChunkKind: TypeAlias = str
DocumentChunkStatus: TypeAlias = str
CHUNKING_POLICY_VERSION: Final = "text-window-v1"


@dataclass(frozen=True, slots=True)
class DocumentTextRange:
    """Character range for a chunk within normalized source text."""

    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start < 0:
            raise DocumentIngestionValidationError("DocumentTextRange.char_start is invalid")
        if self.char_end <= self.char_start:
            raise DocumentIngestionValidationError("DocumentTextRange.char_end is invalid")


@dataclass(frozen=True, slots=True)
class DocumentChunkDraft:
    """Chunk candidate produced before canonical ids are assigned."""

    sequence: int
    text: str
    text_range: DocumentTextRange
    token_estimate: int
    content_hash: str
    kind: DocumentChunkKind = "document_text"

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise DocumentIngestionValidationError("DocumentChunkDraft.sequence is invalid")
        object.__setattr__(self, "text", _required_text(self.text, "text"))
        if self.token_estimate <= 0:
            raise DocumentIngestionValidationError(
                "DocumentChunkDraft.token_estimate is invalid"
            )
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, "content_hash"),
        )
        object.__setattr__(self, "kind", _required_text(self.kind, "kind"))


@dataclass(frozen=True, slots=True)
class DocumentChunkIdentity:
    """Stable canonical chunk identity plus its parent document and scope."""

    chunk_id: str
    document_id: str
    scope: DocumentIngestionScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_id", _required_text(self.chunk_id, "chunk_id"))
        object.__setattr__(
            self,
            "document_id",
            _required_text(self.document_id, "document_id"),
        )


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """Canonical document chunk snapshot."""

    identity: DocumentChunkIdentity
    sequence: int
    text: str
    text_range: DocumentTextRange
    token_estimate: int
    content_hash: str
    source_hash: str
    kind: DocumentChunkKind = "document_text"
    status: DocumentChunkStatus = "active"

    @classmethod
    def from_draft(
        cls,
        *,
        chunk_id: str,
        document_id: str,
        scope: DocumentIngestionScope,
        draft: DocumentChunkDraft,
    ) -> DocumentChunk:
        return cls(
            identity=DocumentChunkIdentity(
                chunk_id=chunk_id,
                document_id=document_id,
                scope=scope,
            ),
            sequence=draft.sequence,
            text=draft.text,
            text_range=draft.text_range,
            token_estimate=draft.token_estimate,
            content_hash=draft.content_hash,
            source_hash=content_hash_for_text(f"{document_id}:{draft.sequence}:{draft.text}"),
            kind=draft.kind,
        )

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise DocumentIngestionValidationError("DocumentChunk.sequence is invalid")
        object.__setattr__(self, "text", _required_text(self.text, "text"))
        if self.token_estimate <= 0:
            raise DocumentIngestionValidationError("DocumentChunk.token_estimate is invalid")
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, "content_hash"),
        )
        object.__setattr__(self, "source_hash", _required_text(self.source_hash, "source_hash"))
        object.__setattr__(self, "kind", _required_text(self.kind, "kind"))
        object.__setattr__(self, "status", _required_text(self.status, "status"))


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    """Deterministic text-window chunking policy for source documents."""

    target_chars: int = 1200
    overlap_chars: int = 120
    min_chars: int = 160
    boundary_scan_chars: int = 240
    version: str = CHUNKING_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.target_chars <= 0:
            raise DocumentIngestionValidationError("ChunkingPolicy.target_chars is invalid")
        if self.overlap_chars < 0:
            raise DocumentIngestionValidationError("ChunkingPolicy.overlap_chars is invalid")
        if self.overlap_chars >= self.target_chars:
            raise DocumentIngestionValidationError(
                "ChunkingPolicy.overlap_chars must be smaller than target_chars"
            )
        if self.min_chars <= 0 or self.min_chars > self.target_chars:
            raise DocumentIngestionValidationError("ChunkingPolicy.min_chars is invalid")
        if self.boundary_scan_chars < 0:
            raise DocumentIngestionValidationError(
                "ChunkingPolicy.boundary_scan_chars is invalid"
            )
        object.__setattr__(self, "version", _required_text(self.version, "version"))

    def plan_chunks(self, text: str) -> tuple[DocumentChunkDraft, ...]:
        """Split normalized text into stable chunk drafts."""

        normalized = normalize_document_text(text)
        if not normalized:
            return ()
        if len(normalized) <= self.target_chars:
            return (
                _chunk_draft(
                    text=normalized,
                    char_start=0,
                    char_end=len(normalized),
                    sequence=0,
                ),
            )

        chunks: list[DocumentChunkDraft] = []
        start = 0
        sequence = 0
        while start < len(normalized):
            hard_end = min(len(normalized), start + self.target_chars)
            end = _best_boundary(
                normalized,
                start=start,
                hard_end=hard_end,
                min_chars=self.min_chars,
            )
            raw_chunk = normalized[start:end]
            chunk_text = raw_chunk.strip()
            if chunk_text:
                actual_start = start + len(raw_chunk) - len(raw_chunk.lstrip())
                chunks.append(
                    _chunk_draft(
                        text=chunk_text,
                        char_start=actual_start,
                        char_end=end,
                        sequence=sequence,
                    )
                )
                sequence += 1
            if end >= len(normalized):
                break
            proposed_start = max(end - self.overlap_chars, start + 1)
            start = _best_start_boundary(
                normalized,
                current_start=start,
                proposed_start=proposed_start,
                scan_chars=self.boundary_scan_chars,
            )
        return tuple(chunks)


def estimate_token_count(text: str) -> int:
    """Return a small, deterministic token estimate without provider dependencies."""

    cleaned = normalize_document_text(text)
    if not cleaned:
        return 0
    by_chars = max(1, (len(cleaned) + 3) // 4)
    by_words = max(1, len(cleaned.split()))
    return max(by_chars, by_words)


def _chunk_draft(
    *,
    text: str,
    char_start: int,
    char_end: int,
    sequence: int,
) -> DocumentChunkDraft:
    return DocumentChunkDraft(
        sequence=sequence,
        text=text,
        text_range=DocumentTextRange(char_start=char_start, char_end=char_end),
        token_estimate=estimate_token_count(text),
        content_hash=content_hash_for_text(text),
    )


def _best_boundary(
    text: str,
    *,
    start: int,
    hard_end: int,
    min_chars: int,
) -> int:
    if hard_end >= len(text):
        return len(text)
    lower_bound = min(hard_end, start + min_chars)
    window = text[lower_bound:hard_end]
    for marker in ("\n\n", "\n", ". ", "? ", "! ", "; "):
        index = window.rfind(marker)
        if index >= 0:
            return lower_bound + index + len(marker)
    return hard_end


def _best_start_boundary(
    text: str,
    *,
    current_start: int,
    proposed_start: int,
    scan_chars: int,
) -> int:
    cursor = min(max(proposed_start, current_start + 1), len(text))
    if scan_chars <= 0 or cursor <= current_start + 1:
        return cursor

    lower_bound = max(current_start + 1, cursor - scan_chars)
    line_start = text.rfind("\n", lower_bound, cursor)
    if line_start < 0:
        return cursor

    adjusted_start = line_start + 1
    if adjusted_start <= current_start:
        return cursor
    return adjusted_start


def _required_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise DocumentIngestionValidationError(f"{field_name} is required")
    return cleaned


__all__ = (
    "CHUNKING_POLICY_VERSION",
    "ChunkingPolicy",
    "DocumentChunk",
    "DocumentChunkDraft",
    "DocumentChunkIdentity",
    "DocumentChunkKind",
    "DocumentChunkStatus",
    "DocumentTextRange",
    "estimate_token_count",
)
