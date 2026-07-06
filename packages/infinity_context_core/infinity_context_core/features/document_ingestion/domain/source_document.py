"""Source document domain model for the document_ingestion feature."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TypeAlias

from infinity_context_core.features.document_ingestion.domain.errors import (
    DocumentIngestionValidationError,
)

SourceDocumentStatus: TypeAlias = str
SourceDocumentClassification: TypeAlias = str


@dataclass(frozen=True, slots=True)
class DocumentIngestionScope:
    """Canonical ownership scope for an ingested document."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "space_id", _required_text(self.space_id, "space_id"))
        object.__setattr__(
            self,
            "memory_scope_id",
            _required_text(self.memory_scope_id, "memory_scope_id"),
        )
        object.__setattr__(self, "thread_id", _optional_text(self.thread_id))


@dataclass(frozen=True, slots=True)
class SourceDocumentOrigin:
    """External source handle supplied by the caller."""

    source_type: str
    source_external_id: str
    uri: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_type",
            _required_text(self.source_type, "source_type"),
        )
        object.__setattr__(
            self,
            "source_external_id",
            _required_text(self.source_external_id, "source_external_id"),
        )
        object.__setattr__(self, "uri", _optional_text(self.uri))


@dataclass(frozen=True, slots=True)
class SourceDocumentContent:
    """Normalized source text plus its canonical content hash."""

    text: str
    content_hash: str

    @classmethod
    def from_text(cls, text: str) -> SourceDocumentContent:
        normalized = normalize_document_text(text)
        if not normalized:
            raise DocumentIngestionValidationError("SourceDocumentContent.text is required")
        return cls(text=normalized, content_hash=content_hash_for_text(normalized))

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _required_text(self.text, "text"))
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, "content_hash"),
        )


@dataclass(frozen=True, slots=True)
class SourceDocumentDraft:
    """Validated source document before canonical ids are assigned."""

    scope: DocumentIngestionScope
    title: str
    origin: SourceDocumentOrigin
    content: SourceDocumentContent
    classification: SourceDocumentClassification = "unknown"

    @classmethod
    def create(
        cls,
        *,
        scope: DocumentIngestionScope,
        title: str,
        origin: SourceDocumentOrigin,
        text: str,
        classification: SourceDocumentClassification = "unknown",
    ) -> SourceDocumentDraft:
        return cls(
            scope=scope,
            title=title,
            origin=origin,
            content=SourceDocumentContent.from_text(text),
            classification=classification,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(
            self,
            "classification",
            _required_text(self.classification, "classification"),
        )


@dataclass(frozen=True, slots=True)
class SourceDocumentIdentity:
    """Stable canonical document identity plus its owning scope."""

    document_id: str
    scope: DocumentIngestionScope

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_id",
            _required_text(self.document_id, "document_id"),
        )


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Canonical source document snapshot."""

    identity: SourceDocumentIdentity
    title: str
    origin: SourceDocumentOrigin
    content_hash: str
    status: SourceDocumentStatus = "active"
    classification: SourceDocumentClassification = "unknown"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_draft(
        cls,
        *,
        document_id: str,
        draft: SourceDocumentDraft,
        now: datetime | None = None,
    ) -> SourceDocument:
        return cls(
            identity=SourceDocumentIdentity(
                document_id=document_id,
                scope=draft.scope,
            ),
            title=draft.title,
            origin=draft.origin,
            content_hash=draft.content.content_hash,
            classification=draft.classification,
            created_at=now,
            updated_at=now,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, "content_hash"),
        )
        object.__setattr__(self, "status", _required_text(self.status, "status"))
        object.__setattr__(
            self,
            "classification",
            _required_text(self.classification, "classification"),
        )


def normalize_document_text(text: str) -> str:
    """Normalize source text before hashing and chunking."""

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        char
        for char in normalized
        if char == "\n" or char == "\t" or ord(char) >= 32
    )
    return normalized.strip()


def content_hash_for_text(text: str) -> str:
    """Return the deterministic hash used for document/chunk dedupe contracts."""

    normalized = normalize_document_text(text)
    if not normalized:
        raise DocumentIngestionValidationError("text is required for content hashing")
    return sha256(normalized.encode("utf-8")).hexdigest()


def _required_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise DocumentIngestionValidationError(f"{field_name} is required")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


__all__ = (
    "DocumentIngestionScope",
    "SourceDocument",
    "SourceDocumentClassification",
    "SourceDocumentContent",
    "SourceDocumentDraft",
    "SourceDocumentIdentity",
    "SourceDocumentOrigin",
    "SourceDocumentStatus",
    "content_hash_for_text",
    "normalize_document_text",
)
