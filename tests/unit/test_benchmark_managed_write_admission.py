from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.application.benchmark_managed_write_admission import (
    ManagedBenchmarkCreateMemoryScopeAdmission,
    ManagedBenchmarkDocumentMutationBlocker,
    ManagedBenchmarkEnsureScopeAdmission,
    ManagedBenchmarkFactMutationBlocker,
    ManagedBenchmarkRememberFactAdmission,
    require_managed_document_admission,
)
from infinity_context_core.application.dto import EnsureScopeCommand, IngestDocumentCommand
from infinity_context_core.application.dto_workspace import CreateMemoryScopeCommand
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.features.memory_facts.application.commands import RememberFactCommand
from infinity_context_core.features.memory_facts.domain import (
    MemoryFactScope,
    MemoryFactSourceRef,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAdmission,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAdmission,
    ManagedBenchmarkStrictV4FactAdmission,
)

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE = f"benchmark-space-{RUN[:48]}"
SLUG = "memory-comparison-managed-fact-admission"


class _Inner:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, command: RememberFactCommand) -> object:
        self.calls += 1
        return command


class _StrictAuthority:
    def __init__(self) -> None:
        self.claims = []
        self.corpus_claims = []

    def admit_fact(self, claim):
        self.claims.append(claim)
        return ManagedBenchmarkStrictV4FactAdmission(
            operation_sha256="d" * 64,
            idempotency_key=f"managed-benchmark-fact-v4-{'e' * 64}",
        )

    def admit_corpus(self, claim):
        self.corpus_claims.append(claim)
        return ManagedBenchmarkStrictV4CorpusAdmission("f" * 64)


class _StrictDocumentAuthority:
    def __init__(self) -> None:
        self.claims = []

    def admit_document(self, claim):
        self.claims.append(claim)
        return ManagedBenchmarkStrictV4DocumentAdmission(
            operation_sha256="1" * 64,
            idempotency_key=f"managed-benchmark-document-v4-{'2' * 64}",
        )


class _DocumentUow:
    def __init__(self, space_id: str) -> None:
        self.documents = SimpleNamespace(
            get_by_id=lambda _value: _async(SimpleNamespace(space_id=space_id))
        )

    async def __aenter__(self) -> _DocumentUow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Uow:
    def __init__(self, record: object) -> None:
        self.benchmark_runs = SimpleNamespace(
            get_by_space_id=lambda _space: _async(record),
            get_by_space_slug=lambda _slug: _async(record),
        )
        self.scope = SimpleNamespace(
            get_memory_scope=lambda value: _async(
                SimpleNamespace(
                    space_id=SPACE,
                    external_ref="corpus-1",
                    status=LifecycleStatus.ACTIVE,
                )
                if value == "scope-1"
                else None
            ),
            get_thread=lambda value: _async(
                SimpleNamespace(
                    memory_scope_id="scope-1",
                    external_ref="thread-1",
                    status=LifecycleStatus.ACTIVE,
                )
                if value == "thread-1"
                else None
            ),
        )

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


async def _async(value: object) -> object:
    return value


def _command() -> RememberFactCommand:
    return RememberFactCommand(
        scope=MemoryFactScope(SPACE, "scope-1", "thread-1"),
        text="The benchmark requires exact cleanup.",
        source_refs=(
            MemoryFactSourceRef(
                source_type="memory_comparison_benchmark",
                source_id="source-1",
                quote_preview="The benchmark requires exact cleanup.",
            ),
        ),
        kind="requirement",
    )


def _record(command: RememberFactCommand) -> object:
    plan, _ = cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)
    ref = command.source_refs[0]
    descriptor = managed_benchmark_fact_source_ref_descriptor(
        source_type=ref.source_type,
        source_id=ref.source_id,
        chunk_id=ref.chunk_id,
        char_start=ref.char_start,
        char_end=ref.char_end,
        quote_preview=ref.quote_preview,
        page_number=ref.page_number,
        time_start_ms=ref.time_start_ms,
        time_end_ms=ref.time_end_ms,
        bbox=ref.bbox,
    )
    source_sha = managed_benchmark_text_sha256(ref.source_id)
    material = managed_benchmark_fact_operation_material(
        source_external_id_sha256=source_sha,
        content_sha256=managed_benchmark_text_sha256(command.text),
        kind=command.kind,
        classification="internal",
        source_refs=(descriptor,),
    )
    plan["corpora"][0].update(
        {
            "memory_scope_external_ref_sha256": managed_benchmark_text_sha256("corpus-1"),
            "thread_external_ref_sha256": managed_benchmark_text_sha256("thread-1"),
            "ordered_infinity_operation_sha256": [
                managed_benchmark_infinity_operation_sha256(material)
            ],
            "ordered_infinity_source_external_id_sha256": [source_sha],
            "ordered_infinity_content_sha256": [material["content_sha256"]],
        }
    )
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return SimpleNamespace(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        state="active",
        projection_cleanup_state="unsealed",
        cleanup_plan_state="sealed",
        cleanup_plan_json=plan,
        cleanup_plan_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _strict_record() -> object:
    return SimpleNamespace(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=SPACE,
        space_slug=SLUG,
        state="active",
        projection_cleanup_state="unsealed",
        cleanup_plan_state="recovery_blocked",
        cleanup_plan_json=None,
        cleanup_plan_sha256=None,
    )


def test_strict_v4_fact_admission_uses_narrow_authority_and_overrides_caller_key() -> None:
    asyncio.run(_strict_v4_fact_admission_contract())


async def _strict_v4_fact_admission_contract() -> None:
    command = _command()
    inner = _Inner()
    authority = _StrictAuthority()
    admission = ManagedBenchmarkRememberFactAdmission(
        lambda: _Uow(_strict_record()),
        inner,
        strict_v4_authority=authority,
    )

    result = await admission.execute(replace(command, idempotency_key="caller-drift"))
    assert result.idempotency_key == f"managed-benchmark-fact-v4-{'e' * 64}"
    assert inner.calls == 1
    assert len(authority.claims) == 1
    claim = authority.claims[0]
    assert claim.run_id_sha256 == RUN
    assert claim.binding_commitment_sha256 == BINDING
    assert claim.infinity_target_identity_sha256 == TARGET
    assert claim.space_id == SPACE
    assert claim.space_slug == SLUG
    assert claim.memory_scope_external_ref == "corpus-1"
    assert claim.thread_external_ref == "thread-1"
    assert claim.source_identity_sha256 == managed_benchmark_text_sha256("source-1")

    blocked = ManagedBenchmarkRememberFactAdmission(lambda: _Uow(_strict_record()), _Inner())
    with pytest.raises(MemoryConflictError, match="strict-v4 authority"):
        await blocked.execute(command)


def test_fact_admission_allows_exact_replay_and_rejects_drift_before_inner() -> None:
    asyncio.run(_fact_admission_contract())


async def _fact_admission_contract() -> None:
    command = _command()
    record = _record(command)
    inner = _Inner()
    admission = ManagedBenchmarkRememberFactAdmission(lambda: _Uow(record), inner)

    first = await admission.execute(command)
    second = await admission.execute(replace(command, idempotency_key="caller-drift"))
    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key.startswith("managed-benchmark-fact-v1-")
    assert first.idempotency_key != "caller-drift"
    assert inner.calls == 2

    for changed in (
        replace(command, text=command.text + " changed"),
        replace(command, scope=MemoryFactScope(SPACE, "scope-1", "foreign-thread")),
        replace(
            command,
            source_refs=(replace(command.source_refs[0], source_id="foreign-source"),),
        ),
    ):
        with pytest.raises(MemoryConflictError, match="is not admitted"):
            await admission.execute(changed)
    assert inner.calls == 2


def test_strict_v4_document_admission_uses_narrow_expected_index_authority() -> None:
    asyncio.run(_strict_v4_document_admission_contract())


async def _strict_v4_document_admission_contract() -> None:
    command = IngestDocumentCommand(
        space_id=SpaceId(SPACE),
        memory_scope_id=MemoryScopeId("scope-1"),
        thread_id=ThreadId("thread-1"),
        title="LongMemEval session",
        text="A durable LongMemEval session with enough content for one fragment.",
        source_type="longmemeval",
        source_external_id="longmemeval-source-1",
        classification="internal",
        chunk_metadata={
            "source_refs": [
                {
                    "source_type": "longmemeval",
                    "source_id_sha256": "3" * 64,
                }
            ]
        },
    )
    authority = _StrictDocumentAuthority()
    key = await require_managed_document_admission(
        uow=_Uow(_strict_record()),
        command=command,
        strict_v4_authority=authority,
    )

    assert key == f"managed-benchmark-document-v4-{'2' * 64}"
    assert len(authority.claims) == 1
    claim = authority.claims[0]
    assert claim.run_id_sha256 == RUN
    assert claim.space_id == SPACE
    assert claim.memory_scope_external_ref == "corpus-1"
    assert claim.thread_external_ref == "thread-1"
    assert claim.ordered_source_ref_descriptor_sha256
    assert claim.ordered_fragment_descriptor_sha256

    with pytest.raises(MemoryConflictError, match="strict-v4 document authority"):
        await require_managed_document_admission(
            uow=_Uow(_strict_record()),
            command=command,
        )


def test_managed_fact_and_document_mutations_reject_before_inner() -> None:
    asyncio.run(_managed_mutation_contract())


async def _managed_mutation_contract() -> None:
    fact_inner = _Inner()
    fact_guard = ManagedBenchmarkFactMutationBlocker(fact_inner)
    with pytest.raises(MemoryConflictError, match="fact mutation"):
        await fact_guard.execute(
            SimpleNamespace(identity=SimpleNamespace(scope=MemoryFactScope(SPACE, "s", "t")))
        )
    assert fact_inner.calls == 0

    document_inner = _Inner()
    document_guard = ManagedBenchmarkDocumentMutationBlocker(
        lambda: _DocumentUow(SPACE), document_inner
    )
    with pytest.raises(MemoryConflictError, match="document mutation"):
        await document_guard.execute(SimpleNamespace(document_id="document-1"))
    assert document_inner.calls == 0


def test_ordinary_fact_and_document_mutations_reach_inner() -> None:
    asyncio.run(_ordinary_mutation_contract())


async def _ordinary_mutation_contract() -> None:
    fact_inner = _Inner()
    fact_command = SimpleNamespace(
        identity=SimpleNamespace(scope=MemoryFactScope("ordinary-space", "s", "t"))
    )
    assert (
        await ManagedBenchmarkFactMutationBlocker(fact_inner).execute(fact_command) is fact_command
    )

    document_inner = _Inner()
    document_command = SimpleNamespace(document_id="document-1")
    guard = ManagedBenchmarkDocumentMutationBlocker(
        lambda: _DocumentUow("ordinary-space"), document_inner
    )
    assert await guard.execute(document_command) is document_command


def test_managed_scope_creation_requires_exact_plan_external_refs() -> None:
    asyncio.run(_managed_scope_creation_contract())


async def _managed_scope_creation_contract() -> None:
    record = _record(_command())
    ensure_inner = _Inner()
    ensure = ManagedBenchmarkEnsureScopeAdmission(lambda: _Uow(record), ensure_inner)
    exact = EnsureScopeCommand(
        space_slug=SLUG,
        memory_scope_external_ref="corpus-1",
        thread_external_ref="thread-1",
    )
    assert await ensure.execute(exact) is exact
    for changed in (
        replace(exact, memory_scope_external_ref="foreign-corpus"),
        replace(exact, thread_external_ref="foreign-thread"),
        replace(exact, thread_external_ref=None),
    ):
        with pytest.raises(MemoryConflictError, match="scope creation"):
            await ensure.execute(changed)
    assert ensure_inner.calls == 1

    create_inner = _Inner()
    create = ManagedBenchmarkCreateMemoryScopeAdmission(lambda: _Uow(record), create_inner)
    admitted = CreateMemoryScopeCommand(
        space_id=SpaceId(SPACE), external_ref="corpus-1", name="corpus"
    )
    assert await create.execute(admitted) is admitted
    with pytest.raises(MemoryConflictError, match="scope creation"):
        await create.execute(replace(admitted, external_ref="foreign-corpus"))
    assert create_inner.calls == 1


def test_strict_v4_scope_pair_uses_authenticated_corpus_authority() -> None:
    asyncio.run(_strict_v4_scope_pair_contract())


async def _strict_v4_scope_pair_contract() -> None:
    exact = EnsureScopeCommand(
        space_slug=SLUG,
        memory_scope_external_ref="corpus-1",
        thread_external_ref="thread-1",
    )
    inner = _Inner()
    authority = _StrictAuthority()
    guard = ManagedBenchmarkEnsureScopeAdmission(
        lambda: _Uow(_strict_record()),
        inner,
        strict_v4_authority=authority,
    )
    assert await guard.execute(exact) is exact
    assert inner.calls == 1
    assert len(authority.corpus_claims) == 1
    claim = authority.corpus_claims[0]
    assert claim.run_id_sha256 == RUN
    assert claim.binding_commitment_sha256 == BINDING
    assert claim.infinity_target_identity_sha256 == TARGET
    assert claim.space_id == SPACE
    assert claim.space_slug == SLUG
    assert claim.memory_scope_external_ref == "corpus-1"
    assert claim.thread_external_ref == "thread-1"

    blocked = ManagedBenchmarkEnsureScopeAdmission(lambda: _Uow(_strict_record()), _Inner())
    with pytest.raises(MemoryConflictError, match="strict-v4 authority"):
        await blocked.execute(exact)
