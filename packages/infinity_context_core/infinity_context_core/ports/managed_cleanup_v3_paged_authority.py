"""Streaming construction for the standalone future cleanup v3 authority."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    CHUNKER_POLICY_SHA256,
    LIMITS_POLICY_SHA256,
    PAGE_CANONICAL_BYTES_CAP,
    PAGE_OPERATION_CAP,
    PROJECTOR_POLICY_SHA256,
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    ManagedCleanupV3Operation,
    ManagedCleanupV3Page,
    ManagedCleanupV3StoreReceipt,
    canonical_bytes,
    commitment,
    digest,
    merkle_root,
    profile_oracle,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    ManagedMem0V6PagedManifestAuthority,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    domain_sha256 as a1_domain_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    merkle_root as a1_merkle_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    page_body as a1_page_body,
)

_CLEANUP_STREAM_PAGE_SIZE = 512


class ManagedCleanupV3TransactionPort(Protocol):
    """One context-scoped coordinator; only committed pages are externally readable.

    ``claim`` and ``append`` are exact-idempotent. ``commit`` is exact-idempotent
    for one authority and ``readback`` makes an ambiguous commit recoverable.
    A committed session rejects divergent replay; abort never removes a commit.
    """

    def claim(self, *, sequence: int, operation_sha256: str) -> None: ...

    def append(self, page: ManagedCleanupV3Page) -> None: ...

    def commit(self, authority: ManagedCleanupV3Authority) -> ManagedCleanupV3StoreReceipt: ...

    def readback(self) -> ManagedCleanupV3StoreReceipt | None: ...

    def abort(self) -> None: ...


class ManagedCleanupV3StorePort(Protocol):
    def begin(
        self, *, context_sha256: str, expected_operation_count: int
    ) -> ManagedCleanupV3TransactionPort: ...


def _callable(value: object, name: str) -> None:
    if not callable(getattr(value, name, None)):
        raise ManagedCleanupV3Error("managed_cleanup_v3_port_invalid")


def _abort(stage: object) -> None:
    abort = getattr(stage, "abort", None)
    if not callable(abort):
        raise ManagedCleanupV3Error("managed_cleanup_v3_abort_failed")
    try:
        abort()
    except BaseException as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_abort_failed") from exc


def _page(
    context_sha256: str,
    page_index: int,
    start_sequence: int,
    operations: tuple[ManagedCleanupV3Operation, ...],
) -> ManagedCleanupV3Page:
    body = {
        "schema_version": "memory-comparison-paged-cleanup-page.v4",
        "context_sha256": context_sha256,
        "page_index": page_index,
        "start_sequence": start_sequence,
        "end_sequence_exclusive": start_sequence + len(operations),
        "operations": [item.payload() for item in operations],
    }
    return ManagedCleanupV3Page(
        context_sha256=context_sha256,
        page_index=page_index,
        start_sequence=start_sequence,
        end_sequence_exclusive=start_sequence + len(operations),
        operations=operations,
        page_sha256=commitment("page/v4", body),
    )


def _fits(
    context_sha256: str,
    page_index: int,
    start_sequence: int,
    operations: tuple[ManagedCleanupV3Operation, ...],
    operation_payload_sizes: tuple[int, ...],
) -> bool:
    if len(operations) > PAGE_OPERATION_CAP:
        return False
    empty_payload = {
        "schema_version": "memory-comparison-paged-cleanup-page.v4",
        "context_sha256": context_sha256,
        "page_index": page_index,
        "start_sequence": start_sequence,
        "end_sequence_exclusive": start_sequence + len(operations),
        "operations": [],
        "page_sha256": "0" * 64,
    }
    empty_size = len(canonical_bytes(empty_payload))
    operation_size = sum(operation_payload_sizes) + max(0, len(operations) - 1)
    return empty_size + operation_size <= PAGE_CANONICAL_BYTES_CAP


def _a1_page_commitment(
    context: ManagedCleanupV3Context, page_index: int, operations: tuple[str, ...]
) -> str:
    body = a1_page_body(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        page_index=page_index,
        start_sequence=page_index * MANAGED_MEM0_V6_PAGE_SIZE,
        ordered_operation_sha256=operations,
    )
    return a1_domain_sha256(PAGE_COMMITMENT_DOMAIN, body)


def cleanup_operation_stream_root(*, profile_id: str, operation_sha256: Iterable[str]) -> str:
    """Return the fixed-page ordered root independently bound into the context."""

    expected = int(profile_oracle(profile_id)["operation_count"])
    pages: list[str] = []
    current: list[str] = []
    count = 0
    for value in operation_sha256:
        if count >= expected:
            raise ManagedCleanupV3Error("managed_cleanup_v3_count_invalid")
        current.append(digest(value))
        count += 1
        if len(current) == _CLEANUP_STREAM_PAGE_SIZE:
            pages.append(
                commitment(
                    "operation-stream-page/v4",
                    {"page_index": len(pages), "ordered_operation_sha256": current},
                )
            )
            current = []
    if count != expected:
        raise ManagedCleanupV3Error("managed_cleanup_v3_count_invalid")
    if current:
        pages.append(
            commitment(
                "operation-stream-page/v4",
                {"page_index": len(pages), "ordered_operation_sha256": current},
            )
        )
    return merkle_root(tuple(pages))


def _authority(
    context: ManagedCleanupV3Context,
    page_sha256: tuple[str, ...],
    *,
    valid_messages: int,
    fragments: int,
    corpus_thread_identities: tuple[str, ...],
    document_source_ref_count: int,
    document_source_ref_root_sha256: str,
    a1_root: str,
    cleanup_root: str,
) -> ManagedCleanupV3Authority:
    oracle = profile_oracle(context.profile_id)
    body = {
        "schema_version": "memory-comparison-paged-cleanup-authority.v4",
        "profile_id": context.profile_id,
        "context_sha256": context.context_sha256,
        "a1_terminal_commitment_sha256": context.a1_terminal_commitment_sha256,
        "operation_count": oracle["operation_count"],
        "valid_message_count": valid_messages,
        "original_pair_slot_count": oracle["original_pair_slot_count"],
        "fully_invalid_pair_slot_count": oracle["fully_invalid_pair_slot_count"],
        "fragment_count": fragments,
        "corpus_thread_identity_count": len(corpus_thread_identities),
        "corpus_thread_identity_root_sha256": commitment(
            "corpus-scope-thread-identity-root/v4", list(corpus_thread_identities)
        ),
        "document_source_ref_count": document_source_ref_count,
        "document_source_ref_root_sha256": document_source_ref_root_sha256,
        "page_count": len(page_sha256),
        "ordered_page_sha256": list(page_sha256),
        "pages_merkle_root_sha256": merkle_root(page_sha256),
        "a1_operation_stream_root_sha256": a1_root,
        "cleanup_operation_stream_root_sha256": cleanup_root,
        "omitted_source_identity_root_sha256": context.omitted_source_identity_root_sha256,
        "projector_policy_sha256": PROJECTOR_POLICY_SHA256,
        "chunker_policy_sha256": CHUNKER_POLICY_SHA256,
        "limits_policy_sha256": LIMITS_POLICY_SHA256,
    }
    return ManagedCleanupV3Authority(
        **{
            key: tuple(value) if key == "ordered_page_sha256" else value
            for key, value in body.items()
            if key != "schema_version"
        },
        terminal_commitment_sha256=commitment("authority/v4", body),
    )  # type: ignore[arg-type]


def build_managed_cleanup_v3_authority(
    *,
    context: ManagedCleanupV3Context,
    operations: Iterable[ManagedCleanupV3Operation],
    a1_authority: ManagedMem0V6PagedManifestAuthority,
    store: ManagedCleanupV3StorePort,
) -> tuple[ManagedCleanupV3Authority, ManagedCleanupV3StoreReceipt]:
    """Validate a full ordered stream and atomically publish bounded pages."""

    if type(context) is not ManagedCleanupV3Context:
        raise ManagedCleanupV3Error("managed_cleanup_v3_context_invalid")
    context.__post_init__()
    if type(a1_authority) is not ManagedMem0V6PagedManifestAuthority:
        raise ManagedCleanupV3Error("managed_cleanup_v3_a1_authority_invalid")
    a1_authority.__post_init__()
    _callable(store, "begin")
    oracle = profile_oracle(context.profile_id)
    expected = int(oracle["operation_count"])
    if (
        a1_authority.profile_id != context.profile_id
        or a1_authority.manifest_context_sha256 != context.manifest_context_sha256
        or a1_authority.terminal_commitment_sha256 != context.a1_terminal_commitment_sha256
        or a1_authority.operation_count != expected
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_a1_authority_invalid")
    try:
        iterator = iter(operations)
    except TypeError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_operations_invalid") from exc
    stage = store.begin(context_sha256=context.context_sha256, expected_operation_count=expected)
    try:
        for name in ("claim", "append", "commit", "readback", "abort"):
            _callable(stage, name)
        page_items: list[ManagedCleanupV3Operation] = []
        page_item_sizes: list[int] = []
        pages: list[str] = []
        a1_items: list[str] = []
        a1_pages: list[str] = []
        cleanup_items: list[str] = []
        cleanup_pages: list[str] = []
        corpus_thread_identities: list[str] = []
        document_source_ref_items: list[str] = []
        document_source_ref_pages: list[str] = []
        current_corpus: str | None = None
        current_lane: str | None = None
        current_memory_scope_external_ref_sha256: str | None = None
        current_thread_external_ref_sha256: str | None = None
        closed_corpora: set[str] = set()
        document_source_ref_count = 0
        sequence = valid_messages = fragments = 0

        def flush_page() -> None:
            nonlocal page_item_sizes, page_items
            if not page_items:
                return
            start = page_items[0].sequence
            page = _page(context.context_sha256, len(pages), start, tuple(page_items))
            stage.append(page)
            pages.append(page.page_sha256)
            page_items = []
            page_item_sizes = []

        def flush_a1() -> None:
            nonlocal a1_items
            if not a1_items:
                return
            a1_pages.append(_a1_page_commitment(context, len(a1_pages), tuple(a1_items)))
            a1_items = []

        def flush_cleanup() -> None:
            nonlocal cleanup_items
            if not cleanup_items:
                return
            cleanup_pages.append(
                commitment(
                    "operation-stream-page/v4",
                    {
                        "page_index": len(cleanup_pages),
                        "ordered_operation_sha256": cleanup_items,
                    },
                )
            )
            cleanup_items = []

        def flush_document_source_refs() -> None:
            nonlocal document_source_ref_items
            if not document_source_ref_items:
                return
            document_source_ref_pages.append(
                commitment(
                    "document-source-ref-page/v4",
                    {
                        "page_index": len(document_source_ref_pages),
                        "ordered_identity_sha256": document_source_ref_items,
                    },
                )
            )
            document_source_ref_items = []

        for operation in iterator:
            if type(operation) is not ManagedCleanupV3Operation:
                raise ManagedCleanupV3Error("managed_cleanup_v3_operation_invalid")
            operation.__post_init__()
            if sequence >= expected or operation.sequence != sequence:
                raise ManagedCleanupV3Error("managed_cleanup_v3_sequence_invalid")
            if operation.corpus_identity_sha256 != current_corpus:
                if operation.corpus_identity_sha256 in closed_corpora:
                    raise ManagedCleanupV3Error("managed_cleanup_v3_corpus_order_invalid")
                if current_corpus is not None:
                    closed_corpora.add(current_corpus)
                current_corpus = operation.corpus_identity_sha256
                current_lane = operation.lane
                current_memory_scope_external_ref_sha256 = (
                    operation.memory_scope_external_ref_sha256
                )
                current_thread_external_ref_sha256 = operation.thread_external_ref_sha256
                corpus_thread_identities.append(
                    commitment(
                        "corpus-scope-thread-identity/v4",
                        {
                            "lane": current_lane,
                            "corpus_identity_sha256": current_corpus,
                            "memory_scope_external_ref_sha256": (
                                current_memory_scope_external_ref_sha256
                            ),
                            "thread_external_ref_sha256": (current_thread_external_ref_sha256),
                        },
                    )
                )
            elif (
                operation.lane != current_lane
                or operation.memory_scope_external_ref_sha256
                != current_memory_scope_external_ref_sha256
                or operation.thread_external_ref_sha256 != current_thread_external_ref_sha256
            ):
                raise ManagedCleanupV3Error("managed_cleanup_v3_thread_identity_invalid")
            if operation.lane == "document":
                document_source_ref_count += len(operation.ordered_source_ref_descriptor_sha256)
                document_source_ref_items.append(
                    commitment(
                        "document-source-ref-identity/v4",
                        {
                            "source_identity_sha256": operation.source_identity_sha256,
                            "source_ref_count": len(operation.ordered_source_ref_descriptor_sha256),
                            "source_refs_sha256": operation.source_refs_sha256,
                        },
                    )
                )
                if len(document_source_ref_items) == _CLEANUP_STREAM_PAGE_SIZE:
                    flush_document_source_refs()
            candidate = (*page_items, operation)
            operation_size = len(canonical_bytes(operation.payload()))
            candidate_sizes = (*page_item_sizes, operation_size)
            if page_items and not _fits(
                context.context_sha256,
                len(pages),
                page_items[0].sequence,
                candidate,
                candidate_sizes,
            ):
                flush_page()
                candidate = (operation,)
                candidate_sizes = (operation_size,)
            if not _fits(
                context.context_sha256,
                len(pages),
                operation.sequence if not page_items else page_items[0].sequence,
                candidate,
                candidate_sizes,
            ):
                raise ManagedCleanupV3Error("managed_cleanup_v3_page_size_invalid")
            stage.claim(sequence=sequence, operation_sha256=operation.operation_sha256)
            page_items.append(operation)
            page_item_sizes.append(operation_size)
            a1_items.append(operation.a1_operation_sha256)
            cleanup_items.append(operation.operation_sha256)
            valid_messages += operation.valid_message_count
            fragments += len(operation.ordered_fragment_descriptor_sha256)
            sequence += 1
            if len(a1_items) == MANAGED_MEM0_V6_PAGE_SIZE:
                flush_a1()
            if len(cleanup_items) == _CLEANUP_STREAM_PAGE_SIZE:
                flush_cleanup()
        if sequence != expected:
            raise ManagedCleanupV3Error("managed_cleanup_v3_count_invalid")
        flush_page()
        flush_a1()
        flush_cleanup()
        flush_document_source_refs()
        a1_root = a1_merkle_root(tuple(a1_pages))
        if a1_root != a1_authority.pages_merkle_root_sha256:
            raise ManagedCleanupV3Error("managed_cleanup_v3_a1_stream_mismatch")
        cleanup_root = merkle_root(tuple(cleanup_pages))
        if cleanup_root != context.cleanup_operation_stream_root_sha256:
            raise ManagedCleanupV3Error("managed_cleanup_v3_operation_stream_mismatch")
        authority = _authority(
            context,
            tuple(pages),
            valid_messages=valid_messages,
            fragments=fragments,
            corpus_thread_identities=tuple(corpus_thread_identities),
            document_source_ref_count=document_source_ref_count,
            document_source_ref_root_sha256=(
                merkle_root(tuple(document_source_ref_pages))
                if document_source_ref_pages
                else commitment("document-source-ref-empty/v4", [])
            ),
            a1_root=a1_root,
            cleanup_root=cleanup_root,
        )
        try:
            receipt = stage.commit(authority)
        except BaseException as commit_error:
            receipt = stage.readback()
            if receipt is None:
                raise ManagedCleanupV3Error(
                    "managed_cleanup_v3_commit_outcome_unknown"
                ) from commit_error
        observed = stage.readback()
        if type(receipt) is not ManagedCleanupV3StoreReceipt or observed != receipt:
            raise ManagedCleanupV3Error("managed_cleanup_v3_store_receipt_invalid")
        receipt.__post_init__()
        if (
            receipt.context_sha256 != context.context_sha256
            or receipt.terminal_commitment_sha256 != authority.terminal_commitment_sha256
            or receipt.page_count != authority.page_count
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_store_receipt_invalid")
        return authority, receipt
    except BaseException:
        _abort(stage)
        raise


__all__ = (
    "ManagedCleanupV3StorePort",
    "ManagedCleanupV3TransactionPort",
    "build_managed_cleanup_v3_authority",
    "cleanup_operation_stream_root",
)
