"""Streaming construction and verification for managed Mem0 v6 manifests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    TERMINAL_COMMITMENT_DOMAIN,
    ManagedMem0V6ManifestContext,
    ManagedMem0V6ManifestError,
    ManagedMem0V6ManifestPage,
    ManagedMem0V6PagedManifestAuthority,
    ManagedMem0V6PageStoreCommitReceipt,
    ManagedMem0V6UniquenessReceipt,
    authority_body,
    domain_sha256,
    merkle_root,
    page_body,
    profile_operation_count,
    require_sha256,
)


class ManagedMem0V6UniquenessSessionPort(Protocol):
    """Fresh context-bound staging lifecycle, abortable until page-store commit."""

    def claim(self, *, sequence: int, operation_sha256: str) -> None: ...

    def finalize(
        self, *, operation_count: int, ordered_operations_root_sha256: str
    ) -> ManagedMem0V6UniquenessReceipt: ...

    def abort(self) -> None: ...


class ManagedMem0V6UniquenessFactoryPort(Protocol):
    def begin(
        self, *, manifest_context_sha256: str, expected_operation_count: int
    ) -> ManagedMem0V6UniquenessSessionPort: ...


class ManagedMem0V6PageStoreStagePort(Protocol):
    """Exact-idempotent staging; uncommitted pages remain unreachable."""

    def append(self, page: ManagedMem0V6ManifestPage) -> None: ...

    def commit(
        self, authority: ManagedMem0V6PagedManifestAuthority
    ) -> ManagedMem0V6PageStoreCommitReceipt: ...

    def abort(self) -> None: ...


class ManagedMem0V6PageStorePort(Protocol):
    def begin(
        self, *, manifest_context_sha256: str, expected_page_count: int
    ) -> ManagedMem0V6PageStoreStagePort: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6PagedManifestBuildResult:
    authority: ManagedMem0V6PagedManifestAuthority
    store_receipt: ManagedMem0V6PageStoreCommitReceipt

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not ManagedMem0V6PagedManifestAuthority
            or type(self.store_receipt) is not ManagedMem0V6PageStoreCommitReceipt
            or self.store_receipt.manifest_context_sha256 != self.authority.manifest_context_sha256
            or self.store_receipt.authority_terminal_commitment_sha256
            != self.authority.terminal_commitment_sha256
            or self.store_receipt.page_count != self.authority.page_count
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_build_result_invalid")


def _require_callable(value: object, method: str) -> None:
    if not callable(getattr(value, method, None)):
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_port_invalid")


def _abort_staging(*targets: object) -> bool:
    failed = False
    for target in targets:
        abort = getattr(target, "abort", None)
        if not callable(abort):
            failed = True
            continue
        try:
            abort()
        except BaseException:
            failed = True
    return failed


def _page(
    context: ManagedMem0V6ManifestContext,
    page_index: int,
    operations: tuple[str, ...],
) -> ManagedMem0V6ManifestPage:
    start = page_index * MANAGED_MEM0_V6_PAGE_SIZE
    body = page_body(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        page_index=page_index,
        start_sequence=start,
        ordered_operation_sha256=operations,
    )
    return ManagedMem0V6ManifestPage(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        page_index=page_index,
        start_sequence=start,
        end_sequence_exclusive=start + len(operations),
        ordered_operation_sha256=operations,
        page_commitment_sha256=domain_sha256(PAGE_COMMITMENT_DOMAIN, body),
    )


def _authority(
    context: ManagedMem0V6ManifestContext,
    commitments: tuple[str, ...],
    uniqueness_receipt: ManagedMem0V6UniquenessReceipt,
) -> ManagedMem0V6PagedManifestAuthority:
    count = profile_operation_count(context.profile_id)
    root = merkle_root(commitments)
    if (
        type(uniqueness_receipt) is not ManagedMem0V6UniquenessReceipt
        or uniqueness_receipt.manifest_context_sha256 != context.manifest_context_sha256
        or uniqueness_receipt.operation_count != count
        or uniqueness_receipt.ordered_operations_root_sha256 != root
    ):
        raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_receipt_invalid")
    uniqueness_receipt.__post_init__()
    body = authority_body(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        operation_count=count,
        ordered_page_commitment_sha256=commitments,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256_value=uniqueness_receipt.receipt_sha256,
    )
    return ManagedMem0V6PagedManifestAuthority(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        operation_count=count,
        page_size=MANAGED_MEM0_V6_PAGE_SIZE,
        page_count=len(commitments),
        ordered_page_commitment_sha256=commitments,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256=uniqueness_receipt.receipt_sha256,
        limits_policy_sha256=MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
        terminal_commitment_sha256=domain_sha256(TERMINAL_COMMITMENT_DOMAIN, body),
    )


def build_managed_mem0_v6_paged_manifest(
    *,
    context: ManagedMem0V6ManifestContext,
    operation_sha256: Iterable[str],
    page_store: ManagedMem0V6PageStorePort,
    uniqueness_factory: ManagedMem0V6UniquenessFactoryPort,
) -> ManagedMem0V6PagedManifestBuildResult:
    """Stage bounded pages and publish them atomically with terminal authority."""

    if type(context) is not ManagedMem0V6ManifestContext:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_context_invalid")
    context.__post_init__()
    expected = profile_operation_count(context.profile_id)
    expected_pages = (expected + MANAGED_MEM0_V6_PAGE_SIZE - 1) // MANAGED_MEM0_V6_PAGE_SIZE
    _require_callable(page_store, "begin")
    _require_callable(uniqueness_factory, "begin")
    try:
        iterator = iter(operation_sha256)
    except TypeError as exc:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_operations_invalid") from exc
    uniqueness = uniqueness_factory.begin(
        manifest_context_sha256=context.manifest_context_sha256,
        expected_operation_count=expected,
    )
    stage: ManagedMem0V6PageStoreStagePort | None = None
    try:
        for method in ("claim", "finalize", "abort"):
            _require_callable(uniqueness, method)
        stage = page_store.begin(
            manifest_context_sha256=context.manifest_context_sha256,
            expected_page_count=expected_pages,
        )
        for method in ("append", "commit", "abort"):
            _require_callable(stage, method)
    except BaseException as exc:
        targets = (uniqueness,) if stage is None else (stage, uniqueness)
        if _abort_staging(*targets):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed") from exc
        raise
    try:
        page_operations: list[str] = []
        commitments: list[str] = []
        count = 0
        for raw_digest in iterator:
            digest = require_sha256(raw_digest)
            if count >= expected:
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_count_invalid")
            uniqueness.claim(sequence=count, operation_sha256=digest)
            page_operations.append(digest)
            count += 1
            if len(page_operations) == MANAGED_MEM0_V6_PAGE_SIZE:
                page = _page(context, len(commitments), tuple(page_operations))
                stage.append(page)
                commitments.append(page.page_commitment_sha256)
                page_operations.clear()
        if count != expected:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_count_invalid")
        if page_operations:
            page = _page(context, len(commitments), tuple(page_operations))
            stage.append(page)
            commitments.append(page.page_commitment_sha256)
        ordered = tuple(commitments)
        root = merkle_root(ordered)
        receipt = uniqueness.finalize(
            operation_count=count,
            ordered_operations_root_sha256=root,
        )
        authority = _authority(context, ordered, receipt)
        store_receipt = stage.commit(authority)
        if (
            type(store_receipt) is not ManagedMem0V6PageStoreCommitReceipt
            or store_receipt.manifest_context_sha256 != context.manifest_context_sha256
            or store_receipt.authority_terminal_commitment_sha256
            != authority.terminal_commitment_sha256
            or store_receipt.page_count != authority.page_count
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_store_receipt_invalid")
        store_receipt.__post_init__()
        return ManagedMem0V6PagedManifestBuildResult(authority, store_receipt)
    except BaseException as exc:
        if _abort_staging(stage, uniqueness):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed") from exc
        raise


@final
class ManagedMem0V6ManifestStreamVerifier:
    __slots__ = ("_authority", "_context", "_finalized", "_next_page", "_seen", "_unique")

    def __init__(
        self,
        authority: ManagedMem0V6PagedManifestAuthority,
        *,
        context: ManagedMem0V6ManifestContext,
        uniqueness_factory: ManagedMem0V6UniquenessFactoryPort,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V6PagedManifestAuthority
            or type(context) is not ManagedMem0V6ManifestContext
            or authority.manifest_context_sha256 != context.manifest_context_sha256
            or authority.profile_id != context.profile_id
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_verifier_invalid")
        authority.__post_init__()
        context.__post_init__()
        _require_callable(uniqueness_factory, "begin")
        unique = uniqueness_factory.begin(
            manifest_context_sha256=context.manifest_context_sha256,
            expected_operation_count=authority.operation_count,
        )
        _require_callable(unique, "abort")
        try:
            for method in ("claim", "finalize"):
                _require_callable(unique, method)
        except BaseException as exc:
            if _abort_staging(unique):
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed") from exc
            raise
        self._authority = authority
        self._context = context
        self._unique = unique
        self._next_page = 0
        self._seen = 0
        self._finalized = False

    def verify_page(self, page: ManagedMem0V6ManifestPage) -> None:
        try:
            self._verify_page(page)
        except BaseException as exc:
            self._finalized = True
            if _abort_staging(self._unique):
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed") from exc
            raise

    def _verify_page(self, page: ManagedMem0V6ManifestPage) -> None:
        if self._finalized or type(page) is not ManagedMem0V6ManifestPage:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_page_sequence_invalid")
        page.__post_init__()
        expected_count = min(
            MANAGED_MEM0_V6_PAGE_SIZE, self._authority.operation_count - self._seen
        )
        if (
            page.profile_id != self._context.profile_id
            or page.manifest_context_sha256 != self._context.manifest_context_sha256
            or page.page_index != self._next_page
            or page.start_sequence != self._seen
            or page.operation_count != expected_count
            or self._next_page >= self._authority.page_count
            or page.page_commitment_sha256
            != self._authority.ordered_page_commitment_sha256[self._next_page]
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_page_sequence_invalid")
        for offset, digest in enumerate(page.ordered_operation_sha256):
            self._unique.claim(sequence=self._seen + offset, operation_sha256=digest)
        self._seen += page.operation_count
        self._next_page += 1

    def abort(self) -> None:
        if self._finalized:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_verifier_finalized")
        self._finalized = True
        if _abort_staging(self._unique):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed")

    def finalize(self) -> ManagedMem0V6PagedManifestAuthority:
        if (
            self._finalized
            or self._next_page != self._authority.page_count
            or self._seen != self._authority.operation_count
        ):
            self._finalized = True
            if _abort_staging(self._unique):
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed")
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_coverage_incomplete")
        try:
            receipt = self._unique.finalize(
                operation_count=self._seen,
                ordered_operations_root_sha256=self._authority.pages_merkle_root_sha256,
            )
        except BaseException as exc:
            self._finalized = True
            if _abort_staging(self._unique):
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed") from exc
            raise
        if (
            type(receipt) is not ManagedMem0V6UniquenessReceipt
            or receipt.receipt_sha256 != self._authority.uniqueness_receipt_sha256
        ):
            self._finalized = True
            if _abort_staging(self._unique):
                raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_abort_failed")
            raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_receipt_invalid")
        receipt.__post_init__()
        self._finalized = True
        return self._authority


__all__ = (
    "ManagedMem0V6ManifestStreamVerifier",
    "ManagedMem0V6PageStorePort",
    "ManagedMem0V6PageStoreStagePort",
    "ManagedMem0V6PagedManifestBuildResult",
    "ManagedMem0V6UniquenessFactoryPort",
    "ManagedMem0V6UniquenessSessionPort",
    "build_managed_mem0_v6_paged_manifest",
)
