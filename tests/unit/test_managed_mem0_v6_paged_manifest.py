from __future__ import annotations

import hashlib
import tracemalloc
from dataclasses import replace

import pytest
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    MANAGED_MEM0_V6_MAX_PAGE_COUNT,
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    ManagedMem0V6ManifestError,
    ManagedMem0V6ManifestPage,
    ManagedMem0V6PageStoreCommitReceipt,
    ManagedMem0V6UniquenessReceipt,
    build_managed_mem0_v6_manifest_context,
    domain_sha256,
    page_body,
    store_receipt_sha256,
    uniqueness_receipt_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_paged_manifest import (
    ManagedMem0V6ManifestStreamVerifier,
    build_managed_mem0_v6_paged_manifest,
)

LOCOMO = "mem0-locomo-top50-v1"
LONGMEMEVAL = "mem0-longmemeval-top50-v1"


def _digest(sequence: int) -> str:
    return hashlib.sha256(sequence.to_bytes(8, "big")).hexdigest()


def _context(profile_id: str = LOCOMO, *, salt: int = 0):
    return build_managed_mem0_v6_manifest_context(
        profile_id=profile_id,
        run_id_sha256=_digest(100 + salt),
        binding_commitment_sha256=_digest(101 + salt),
        publishable_profile_commitment_sha256=_digest(102 + salt),
        methodology_commitment_sha256=_digest(103 + salt),
        dataset_sha256=_digest(104 + salt),
        admission_commitment_sha256=_digest(105 + salt),
        ingestion_root_sha256=_digest(106 + salt),
    )


def _operations(count: int):
    for sequence in range(count):
        yield _digest(sequence)


class _UniqueSession:
    def __init__(self, context_sha256: str, expected: int, *, retain: bool = True) -> None:
        self.context_sha256 = context_sha256
        self.expected = expected
        self.retain = retain
        self.values: set[str] = set()
        self.next_sequence = 0
        self.state = "active"

    def claim(self, *, sequence: int, operation_sha256: str) -> None:
        if self.state != "active" or sequence != self.next_sequence:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_sequence_invalid")
        if self.retain and operation_sha256 in self.values:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_duplicate_operation")
        if self.retain:
            self.values.add(operation_sha256)
        self.next_sequence += 1

    def finalize(
        self, *, operation_count: int, ordered_operations_root_sha256: str
    ) -> ManagedMem0V6UniquenessReceipt:
        if (
            self.state != "active"
            or operation_count != self.expected
            or self.next_sequence != self.expected
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_finalize_invalid")
        self.state = "finalized"
        return ManagedMem0V6UniquenessReceipt(
            manifest_context_sha256=self.context_sha256,
            operation_count=operation_count,
            ordered_operations_root_sha256=ordered_operations_root_sha256,
            receipt_sha256=uniqueness_receipt_sha256(
                self.context_sha256,
                operation_count,
                ordered_operations_root_sha256,
            ),
        )

    def abort(self) -> None:
        self.state = "aborted"


class _UniqueFactory:
    def __init__(self, *, retain: bool = True) -> None:
        self.retain = retain
        self.sessions: list[_UniqueSession] = []
        self.active_contexts: set[str] = set()

    def begin(self, *, manifest_context_sha256: str, expected_operation_count: int):
        if manifest_context_sha256 in self.active_contexts:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_context_reused")
        self.active_contexts.add(manifest_context_sha256)
        session = _UniqueSession(
            manifest_context_sha256,
            expected_operation_count,
            retain=self.retain,
        )
        self.sessions.append(session)
        return session


class _Stage:
    def __init__(self, store, context_sha256: str, expected_pages: int) -> None:
        self.store = store
        self.context_sha256 = context_sha256
        self.expected_pages = expected_pages
        self.pages: list[ManagedMem0V6ManifestPage] = []
        self.state = "active"

    def append(self, page: ManagedMem0V6ManifestPage) -> None:
        if self.state != "active":
            raise ManagedMem0V6ManifestError("managed_mem0_v6_store_stage_invalid")
        if page.page_index < len(self.pages):
            if self.pages[page.page_index] != page:
                raise ManagedMem0V6ManifestError("managed_mem0_v6_store_append_conflict")
            return
        if page.page_index != len(self.pages):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_store_append_gap")
        self.pages.append(page)

    def commit(self, authority):
        if self.state != "active" or len(self.pages) != self.expected_pages:
            raise ManagedMem0V6ManifestError("managed_mem0_v6_store_commit_invalid")
        self.state = "committed"
        self.store.committed = tuple(self.pages)
        return ManagedMem0V6PageStoreCommitReceipt(
            manifest_context_sha256=self.context_sha256,
            authority_terminal_commitment_sha256=authority.terminal_commitment_sha256,
            page_count=len(self.pages),
            receipt_sha256=store_receipt_sha256(
                self.context_sha256,
                authority.terminal_commitment_sha256,
                len(self.pages),
            ),
        )

    def abort(self) -> None:
        self.state = "aborted"
        self.pages.clear()
        self.store.committed = ()


class _Store:
    def __init__(self) -> None:
        self.stages: list[_Stage] = []
        self.committed: tuple[ManagedMem0V6ManifestPage, ...] = ()

    def begin(self, *, manifest_context_sha256: str, expected_page_count: int):
        stage = _Stage(self, manifest_context_sha256, expected_page_count)
        self.stages.append(stage)
        return stage


def _build(profile_id: str = LOCOMO, *, salt: int = 0):
    context = _context(profile_id, salt=salt)
    store = _Store()
    result = build_managed_mem0_v6_paged_manifest(
        context=context,
        operation_sha256=_operations(5_882 if profile_id == LOCOMO else 124_344),
        page_store=store,
        uniqueness_factory=_UniqueFactory(),
    )
    return context, store, result


@pytest.mark.parametrize(
    ("profile_id", "operation_count", "page_count", "last_page_count"),
    ((LOCOMO, 5_882, 12, 250), (LONGMEMEVAL, 124_344, 243, 440)),
)
def test_builds_and_stream_verifies_exact_frozen_profile_coverage(
    profile_id: str,
    operation_count: int,
    page_count: int,
    last_page_count: int,
) -> None:
    context, store, result = _build(profile_id)
    authority = result.authority
    assert authority.operation_count == operation_count
    assert authority.page_count == page_count
    assert authority.limits_policy_sha256 == MANAGED_MEM0_V6_LIMITS_POLICY_SHA256
    assert len(store.committed) == page_count
    assert all(page.operation_count == MANAGED_MEM0_V6_PAGE_SIZE for page in store.committed[:-1])
    assert store.committed[-1].operation_count == last_page_count
    assert store.committed[-1].end_sequence_exclusive == operation_count
    verifier = ManagedMem0V6ManifestStreamVerifier(
        authority,
        context=context,
        uniqueness_factory=_UniqueFactory(),
    )
    for page in store.committed:
        verifier.verify_page(page)
    assert verifier.finalize() is authority


def test_commitments_are_deterministic_and_pinned() -> None:
    _context_left, store_left, left = _build()
    _context_right, store_right, right = _build()
    assert left == right
    assert store_left.committed == store_right.committed
    assert left.authority.pages_merkle_root_sha256 == (
        "8830c94fda679d74cc39312a729a8c2b01939c93e95170e9067dc00a3d8ba606"
    )
    assert left.authority.terminal_commitment_sha256 == (
        "dd1a02d4e311ca91241a4bf9dcf616c28aa1f6bcaad4d6276c651c9b818d0e84"
    )
    assert store_left.committed[0].page_commitment_sha256 == (
        "d2913c7d540b28058918d23af39272c761ce775e645699294afd140c63a61ee6"
    )


def test_context_binding_blocks_cross_run_page_replay() -> None:
    context, store, result = _build()
    other = _context(salt=1000)
    with pytest.raises(ManagedMem0V6ManifestError, match="verifier_invalid"):
        ManagedMem0V6ManifestStreamVerifier(
            result.authority,
            context=other,
            uniqueness_factory=_UniqueFactory(),
        )
    assert store.committed[0].manifest_context_sha256 == context.manifest_context_sha256


def test_late_duplicate_and_count_failures_abort_uncommitted_pages() -> None:
    values = list(_operations(5_882))
    values[-1] = values[0]
    for operations in (iter(values), _operations(5_881), _operations(5_883)):
        store = _Store()
        factory = _UniqueFactory()
        with pytest.raises(ManagedMem0V6ManifestError):
            build_managed_mem0_v6_paged_manifest(
                context=_context(),
                operation_sha256=operations,
                page_store=store,
                uniqueness_factory=factory,
            )
        assert store.committed == ()
        assert store.stages[0].state == "aborted"
        assert factory.sessions[0].state == "aborted"


def test_stream_rejects_reorder_repeat_gap_incomplete_and_tamper() -> None:
    context, store, result = _build()
    pages = store.committed
    for supplied in ((pages[1],), (pages[0], pages[0]), (pages[0], pages[2])):
        verifier = ManagedMem0V6ManifestStreamVerifier(
            result.authority,
            context=context,
            uniqueness_factory=_UniqueFactory(),
        )
        with pytest.raises(ManagedMem0V6ManifestError, match="page_sequence_invalid"):
            for page in supplied:
                verifier.verify_page(page)
    incomplete = ManagedMem0V6ManifestStreamVerifier(
        result.authority,
        context=context,
        uniqueness_factory=_UniqueFactory(),
    )
    for page in pages[:-1]:
        incomplete.verify_page(page)
    with pytest.raises(ManagedMem0V6ManifestError, match="coverage_incomplete"):
        incomplete.finalize()
    with pytest.raises(ManagedMem0V6ManifestError, match="page_invalid"):
        replace(pages[0], page_commitment_sha256="0" * 64)
    with pytest.raises(ManagedMem0V6ManifestError, match="authority_invalid"):
        replace(result.authority, pages_merkle_root_sha256="0" * 64)


def test_page_boundary_rejects_511_and_513_for_a_nonterminal_page() -> None:
    context, store, result = _build()
    operations_511 = store.committed[0].ordered_operation_sha256[:511]
    body = page_body(
        profile_id=LOCOMO,
        manifest_context_sha256=context.manifest_context_sha256,
        page_index=0,
        start_sequence=0,
        ordered_operation_sha256=operations_511,
    )
    short_page = ManagedMem0V6ManifestPage(
        profile_id=LOCOMO,
        manifest_context_sha256=context.manifest_context_sha256,
        page_index=0,
        start_sequence=0,
        end_sequence_exclusive=511,
        ordered_operation_sha256=operations_511,
        page_commitment_sha256=domain_sha256(PAGE_COMMITMENT_DOMAIN, body),
    )
    verifier = ManagedMem0V6ManifestStreamVerifier(
        result.authority,
        context=context,
        uniqueness_factory=_UniqueFactory(),
    )
    with pytest.raises(ManagedMem0V6ManifestError, match="page_sequence_invalid"):
        verifier.verify_page(short_page)
    with pytest.raises(ManagedMem0V6ManifestError, match="page_invalid"):
        replace(
            store.committed[0],
            end_sequence_exclusive=513,
            ordered_operation_sha256=(
                *store.committed[0].ordered_operation_sha256,
                _digest(99_999),
            ),
        )


def test_uniqueness_session_rejects_duplicate_sequence_and_reuse() -> None:
    context = _context()
    factory = _UniqueFactory()
    session = factory.begin(
        manifest_context_sha256=context.manifest_context_sha256,
        expected_operation_count=5_882,
    )
    session.claim(sequence=0, operation_sha256=_digest(0))
    with pytest.raises(ManagedMem0V6ManifestError, match="sequence_invalid"):
        session.claim(sequence=0, operation_sha256=_digest(1))
    session.abort()
    with pytest.raises(ManagedMem0V6ManifestError, match="context_reused"):
        factory.begin(
            manifest_context_sha256=context.manifest_context_sha256,
            expected_operation_count=5_882,
        )


class _BrokenStore:
    def begin(self, *, manifest_context_sha256: str, expected_page_count: int):
        del manifest_context_sha256, expected_page_count
        raise RuntimeError("store unavailable")


def test_store_begin_failure_aborts_uniqueness_session() -> None:
    factory = _UniqueFactory()
    with pytest.raises(RuntimeError, match="store unavailable"):
        build_managed_mem0_v6_paged_manifest(
            context=_context(),
            operation_sha256=_operations(5_882),
            page_store=_BrokenStore(),
            uniqueness_factory=factory,
        )
    assert factory.sessions[0].state == "aborted"


class _MalformedStage:
    def __init__(self) -> None:
        self.state = "active"

    def commit(self, _authority):
        raise AssertionError("malformed stage must never commit")

    def abort(self) -> None:
        self.state = "aborted"


class _MalformedStore:
    def __init__(self) -> None:
        self.stage = _MalformedStage()

    def begin(self, *, manifest_context_sha256: str, expected_page_count: int):
        del manifest_context_sha256, expected_page_count
        return self.stage


def test_malformed_store_stage_aborts_both_staging_sessions() -> None:
    store = _MalformedStore()
    factory = _UniqueFactory()
    with pytest.raises(ManagedMem0V6ManifestError, match="port_invalid"):
        build_managed_mem0_v6_paged_manifest(
            context=_context(),
            operation_sha256=_operations(5_882),
            page_store=store,
            uniqueness_factory=factory,
        )
    assert store.stage.state == "aborted"
    assert factory.sessions[0].state == "aborted"


class _MalformedUniqueSession:
    def __init__(self) -> None:
        self.state = "active"

    def finalize(self, **_kwargs: object) -> None:
        raise AssertionError("malformed uniqueness session must never finalize")

    def abort(self) -> None:
        self.state = "aborted"


class _MalformedUniqueFactory:
    def __init__(self) -> None:
        self.session = _MalformedUniqueSession()

    def begin(self, **_kwargs: object):
        return self.session


def test_verifier_constructor_aborts_malformed_uniqueness_session() -> None:
    context, _store, result = _build()
    factory = _MalformedUniqueFactory()
    with pytest.raises(ManagedMem0V6ManifestError, match="port_invalid"):
        ManagedMem0V6ManifestStreamVerifier(
            result.authority,
            context=context,
            uniqueness_factory=factory,
        )
    assert factory.session.state == "aborted"


class _CountingStage(_Stage):
    def append(self, page: ManagedMem0V6ManifestPage) -> None:
        self.store.count += 1
        self.store.max_operations = max(self.store.max_operations, page.operation_count)

    def commit(self, authority):
        self.state = "committed"
        return ManagedMem0V6PageStoreCommitReceipt(
            manifest_context_sha256=self.context_sha256,
            authority_terminal_commitment_sha256=authority.terminal_commitment_sha256,
            page_count=self.expected_pages,
            receipt_sha256=store_receipt_sha256(
                self.context_sha256,
                authority.terminal_commitment_sha256,
                self.expected_pages,
            ),
        )


class _CountingStore(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.max_operations = 0

    def begin(self, *, manifest_context_sha256: str, expected_page_count: int):
        stage = _CountingStage(self, manifest_context_sha256, expected_page_count)
        self.stages.append(stage)
        return stage


def test_large_builder_retention_is_page_bounded_with_external_index() -> None:
    store = _CountingStore()
    tracemalloc.start()
    try:
        result = build_managed_mem0_v6_paged_manifest(
            context=_context(LONGMEMEVAL),
            operation_sha256=_operations(124_344),
            page_store=store,
            uniqueness_factory=_UniqueFactory(retain=False),
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.authority.page_count == MANAGED_MEM0_V6_MAX_PAGE_COUNT
    assert store.count == MANAGED_MEM0_V6_MAX_PAGE_COUNT
    assert store.max_operations == MANAGED_MEM0_V6_PAGE_SIZE
    assert peak < 4 * 1024 * 1024
