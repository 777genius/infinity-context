"""Provider-free strict-v4 LongMemEval ingestion through canonical handlers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkEnsureScopeAdmission,
)
from infinity_context_core.application.dto import EnsureScopeCommand, IngestDocumentCommand
from infinity_context_core.application.use_cases.ensure_scope import EnsureScopeUseCase
from infinity_context_core.application.use_cases.ingest_document import IngestDocumentUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
    authenticate_strict_v4_preparation_receipt,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAuthorityPort,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAuthorityPort,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    PROFILE_ORACLES,
    commitment,
)

from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
    sanitize_source_refs,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)

STRICT_V4_DOCUMENT_INGEST_SCHEMA = "memory-comparison-strict-v4-document-ingest.v1"
_ROOT_DOMAIN = b"memory-comparison-strict-v4/document-ingest-root/v1\0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StrictV4DocumentExecutionAuthority(
    ManagedBenchmarkStrictV4CorpusAuthorityPort,
    ManagedBenchmarkStrictV4DocumentAuthorityPort,
    Protocol,
):
    """Minimum combined capability required by the document runtime."""


class StrictV4DocumentIngestError(RuntimeError):
    """Stable provider-free document execution failure."""


@final
@dataclass(frozen=True, slots=True)
class StrictV4DocumentIngestReceipt:
    profile_id: str
    run_id_sha256: str
    context_sha256: str
    authority_terminal_sha256: str
    preparation_receipt_sha256: str
    preparation_receipt_mac_sha256: str
    corpus_count: int
    document_count: int
    chunk_count: int
    replayed_count: int
    ordered_result_root_sha256: str
    provider_calls: int
    receipt_sha256: str
    receipt_mac_sha256: str
    schema_version: str = STRICT_V4_DOCUMENT_INGEST_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema_version != STRICT_V4_DOCUMENT_INGEST_SCHEMA
            or self.profile_id != LONGMEMEVAL_PROFILE
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.context_sha256,
                    self.authority_terminal_sha256,
                    self.preparation_receipt_sha256,
                    self.preparation_receipt_mac_sha256,
                    self.ordered_result_root_sha256,
                    self.receipt_sha256,
                    self.receipt_mac_sha256,
                )
            )
            or type(self.corpus_count) is not int
            or self.corpus_count <= 0
            or type(self.document_count) is not int
            or self.document_count <= 0
            or type(self.chunk_count) is not int
            or self.chunk_count < self.document_count
            or type(self.replayed_count) is not int
            or self.replayed_count < 0
            or self.replayed_count > self.document_count
            or type(self.provider_calls) is not int
            or self.provider_calls != 0
        ):
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_receipt_invalid")

    def payload(self, *, authenticated: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "run_id_sha256": self.run_id_sha256,
            "context_sha256": self.context_sha256,
            "authority_terminal_sha256": self.authority_terminal_sha256,
            "preparation_receipt_sha256": self.preparation_receipt_sha256,
            "preparation_receipt_mac_sha256": self.preparation_receipt_mac_sha256,
            "corpus_count": self.corpus_count,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "replayed_count": self.replayed_count,
            "ordered_result_root_sha256": self.ordered_result_root_sha256,
            "provider_calls": self.provider_calls,
        }
        if authenticated:
            value.update(
                receipt_sha256=self.receipt_sha256,
                receipt_mac_sha256=self.receipt_mac_sha256,
            )
        return value


@final
class StrictV4DocumentIngestRuntime:
    """Own the exact canonical DB composition used by one document pass."""

    def __init__(
        self,
        *,
        database_url: str,
        authority: StrictV4DocumentExecutionAuthority,
    ) -> None:
        if type(database_url) is not str or not database_url:
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_database_invalid")
        self._engine = build_async_engine(database_url)
        sessions = build_session_factory(self._engine)
        clock = SystemClock()
        ids = UuidIdGenerator()
        uow = PostgresUnitOfWorkFactory(session_factory=sessions, clock=clock)
        self._ensure_scope = ManagedBenchmarkEnsureScopeAdmission(
            uow_factory=uow,
            inner=EnsureScopeUseCase(uow_factory=uow, clock=clock),
            strict_v4_authority=authority,
        )
        self._ingest_document = IngestDocumentUseCase(
            uow_factory=uow,
            clock=clock,
            ids=ids,
            strict_v4_authority=authority,
        )
        self._closed = False

    async def execute(
        self,
        *,
        projector: ManagedV5CleanupV4OperationProjector,
        space_slug: str,
        preparation_receipt: StrictV4PreparationReceipt,
        authenticator: ProjectionReceiptAuthenticator,
    ) -> StrictV4DocumentIngestReceipt:
        if self._closed:
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_runtime_closed")
        if (
            type(projector) is not ManagedV5CleanupV4OperationProjector
            or projector.profile_id != LONGMEMEVAL_PROFILE
            or type(space_slug) is not str
            or not space_slug
        ):
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_input_invalid")
        authenticate_strict_v4_preparation_receipt(
            preparation_receipt,
            authenticator=authenticator,
        )
        if (
            preparation_receipt.profile_id != projector.profile_id
            or preparation_receipt.a2_context.space_slug != space_slug
            or preparation_receipt.a2_context.case_manifest_sha256
            != projector.projection.case_manifest_sha256
            or preparation_receipt.expected_index_terminal_sha256
            != preparation_receipt.a2_authority.terminal_commitment_sha256
        ):
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_binding_invalid")
        root = hashlib.sha256(_ROOT_DOMAIN).digest()
        corpus_count = document_count = chunk_count = replayed_count = 0
        for corpus in projector.iter_reconstructed_corpora():
            scope_ref = corpus.memory_scope_external_ref
            thread_ref = corpus.thread_external_ref
            if type(scope_ref) is not str or type(thread_ref) is not str:
                raise StrictV4DocumentIngestError("strict_v4_document_ingest_corpus_invalid")
            scope = await self._ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug=space_slug,
                    memory_scope_external_ref=scope_ref,
                    thread_external_ref=thread_ref,
                )
            )
            corpus_count += 1
            for document in conversation_documents(corpus):
                source_id = document.source_external_id
                if type(source_id) is not str or not source_id:
                    raise StrictV4DocumentIngestError("strict_v4_document_ingest_source_invalid")
                result = await self._ingest_document.execute(
                    IngestDocumentCommand(
                        space_id=SpaceId(str(scope.space_id)),
                        memory_scope_id=MemoryScopeId(str(scope.memory_scope_id)),
                        thread_id=(
                            ThreadId(str(scope.thread_id)) if scope.thread_id is not None else None
                        ),
                        title=document.title,
                        text=document.text,
                        source_type=document.source_type,
                        source_external_id=source_id,
                        classification=document.classification,
                        chunk_metadata={
                            "source_refs": list(sanitize_source_refs(document.source_refs))
                        },
                    )
                )
                document_count += 1
                chunk_count += len(result.chunks)
                replayed_count += int(result.indexing_status == "already_indexed_or_pending")
                root = _extend_root(
                    root,
                    document_count - 1,
                    source_id,
                    str(result.document.id),
                    tuple(str(chunk.id) for chunk in result.chunks),
                )
        oracle = PROFILE_ORACLES[LONGMEMEVAL_PROFILE]
        if (
            corpus_count != int(oracle["corpus_count"])
            or document_count != int(oracle["operation_count"])
            or chunk_count != int(oracle["fragment_count"])
        ):
            raise StrictV4DocumentIngestError("strict_v4_document_ingest_count_invalid")
        return build_strict_v4_document_ingest_receipt(
            preparation_receipt=preparation_receipt,
            authenticator=authenticator,
            corpus_count=corpus_count,
            document_count=document_count,
            chunk_count=chunk_count,
            replayed_count=replayed_count,
            ordered_result_root_sha256=root.hex(),
        )

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._engine.dispose()


def _extend_root(
    current: bytes,
    sequence: int,
    source_id: str,
    document_id: str,
    chunk_ids: tuple[str, ...],
) -> bytes:
    payload = json.dumps(
        {
            "sequence": sequence,
            "source_identity_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
            "document_id": document_id,
            "chunk_ids": list(chunk_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(_ROOT_DOMAIN + current + payload).digest()


def build_strict_v4_document_ingest_receipt(
    *,
    preparation_receipt: StrictV4PreparationReceipt,
    authenticator: ProjectionReceiptAuthenticator,
    corpus_count: int,
    document_count: int,
    chunk_count: int,
    replayed_count: int,
    ordered_result_root_sha256: str,
) -> StrictV4DocumentIngestReceipt:
    authenticate_strict_v4_preparation_receipt(
        preparation_receipt,
        authenticator=authenticator,
    )
    base = StrictV4DocumentIngestReceipt(
        profile_id=preparation_receipt.profile_id,
        run_id_sha256=preparation_receipt.run_id_sha256,
        context_sha256=preparation_receipt.a2_context.context_sha256,
        authority_terminal_sha256=preparation_receipt.expected_index_terminal_sha256,
        preparation_receipt_sha256=preparation_receipt.receipt_sha256,
        preparation_receipt_mac_sha256=preparation_receipt.receipt_mac_sha256,
        corpus_count=corpus_count,
        document_count=document_count,
        chunk_count=chunk_count,
        replayed_count=replayed_count,
        ordered_result_root_sha256=ordered_result_root_sha256,
        provider_calls=0,
        receipt_sha256="0" * 64,
        receipt_mac_sha256="0" * 64,
    )
    receipt_sha256 = commitment(
        "strict-v4-document-ingest/v1",
        base.payload(authenticated=False),
    )
    return StrictV4DocumentIngestReceipt(
        **{
            name: getattr(base, name)
            for name in base.__dataclass_fields__
            if name not in {"receipt_sha256", "receipt_mac_sha256"}
        },
        receipt_sha256=receipt_sha256,
        receipt_mac_sha256=authenticator.sign(
            "strict-v4-document-ingest",
            receipt_sha256,
        ),
    )


def authenticate_strict_v4_document_ingest_receipt(
    receipt: StrictV4DocumentIngestReceipt,
    *,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    if type(receipt) is not StrictV4DocumentIngestReceipt:
        raise StrictV4DocumentIngestError("strict_v4_document_ingest_receipt_invalid")
    receipt.__post_init__()
    expected = commitment(
        "strict-v4-document-ingest/v1",
        receipt.payload(authenticated=False),
    )
    if receipt.receipt_sha256 != expected or not authenticator.verify(
        "strict-v4-document-ingest",
        expected,
        receipt.receipt_mac_sha256,
    ):
        raise StrictV4DocumentIngestError("strict_v4_document_ingest_receipt_invalid")


__all__ = (
    "StrictV4DocumentIngestError",
    "StrictV4DocumentIngestReceipt",
    "StrictV4DocumentIngestRuntime",
    "authenticate_strict_v4_document_ingest_receipt",
    "build_strict_v4_document_ingest_receipt",
)
