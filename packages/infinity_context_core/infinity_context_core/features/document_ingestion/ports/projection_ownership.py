"""Consumer-owned canonical ownership seam for projected document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.document_ingestion.domain import (
    DocumentIngestionScope,
    DocumentRetrievalProjectionV1,
)
from infinity_context_core.features.document_ingestion.domain.retrieval_projection import (
    copy_document_retrieval_projection,
)


@dataclass(frozen=True, slots=True)
class DocumentProjectionOwnershipClaimV1:
    scope: DocumentIngestionScope
    projection: DocumentRetrievalProjectionV1
    content_hash: str
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, DocumentIngestionScope):
            raise ValueError("projection ownership scope has an invalid type")
        if not isinstance(self.projection, DocumentRetrievalProjectionV1):
            raise ValueError("projection ownership descriptor has an invalid type")
        if not isinstance(self.content_hash, str) or not self.content_hash.strip():
            raise ValueError("projection ownership content_hash is required")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("projection ownership content_hash must be lowercase SHA-256")
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key.strip()
            or self.idempotency_key != self.idempotency_key.strip()
        ):
            raise ValueError("projection ownership idempotency_key is invalid")
        if self.idempotency_key is not None and any(
            0xD800 <= ord(character) <= 0xDFFF
            or ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            for character in self.idempotency_key
        ):
            raise ValueError("projection ownership idempotency_key contains invalid text")
        object.__setattr__(
            self,
            "scope",
            DocumentIngestionScope(
                self.scope.space_id, self.scope.memory_scope_id, self.scope.thread_id
            ),
        )
        object.__setattr__(self, "projection", copy_document_retrieval_projection(self.projection))


@dataclass(frozen=True, slots=True)
class DocumentProjectionOwnershipDecisionV1:
    status: str
    document_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"acquired", "idempotent"}:
            raise ValueError("projection ownership status is unsupported")
        if self.status == "acquired" and self.document_id is not None:
            raise ValueError("new projection ownership cannot name a document")
        if self.status == "idempotent" and (
            not isinstance(self.document_id, str) or not self.document_id.strip()
        ):
            raise ValueError("idempotent projection ownership requires document_id")


class DocumentRetrievalProjectionOwnershipPortV1(Protocol):
    async def claim_document_projection(
        self, claim: DocumentProjectionOwnershipClaimV1
    ) -> DocumentProjectionOwnershipDecisionV1:
        """Atomically enforce locator, ordinal, and idempotency ownership."""


__all__ = (
    "DocumentProjectionOwnershipClaimV1",
    "DocumentProjectionOwnershipDecisionV1",
    "DocumentRetrievalProjectionOwnershipPortV1",
)
