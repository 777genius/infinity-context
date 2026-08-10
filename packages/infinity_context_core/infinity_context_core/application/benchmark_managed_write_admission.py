"""Application admission for exact managed benchmark fact/document writes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Protocol

from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.dto import IngestDocumentCommand
from infinity_context_core.application.normalize import content_hash
from infinity_context_core.domain.entities import LifecycleStatus
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.features.memory_facts.application.commands import (
    RememberFactCommand,
    RememberFactResult,
)
from infinity_context_core.ports.benchmark_cleanup_plan import (
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.benchmark_runs import is_managed_benchmark_space_id
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAuthorityPort,
    ManagedBenchmarkStrictV4DocumentClaim,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAuthorityPort,
    ManagedBenchmarkStrictV4CorpusClaim,
    ManagedBenchmarkStrictV4FactAuthorityPort,
    ManagedBenchmarkStrictV4FactClaim,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    fragment_commitments,
    source_ref_commitments,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort


class RememberFactExecutor(Protocol):
    async def execute(self, command: RememberFactCommand) -> RememberFactResult: ...


class MutationExecutor(Protocol):
    async def execute(self, command: object) -> object: ...


@dataclass(frozen=True, slots=True)
class ManagedBenchmarkRememberFactAdmission:
    """Fail closed before the canonical fact handler for managed namespaces."""

    uow_factory: UnitOfWorkFactoryPort
    inner: RememberFactExecutor
    strict_v4_authority: ManagedBenchmarkStrictV4FactAuthorityPort | None = None

    async def execute(self, command: RememberFactCommand) -> RememberFactResult:
        if is_managed_benchmark_space_id(command.scope.space_id):
            source_refs = [
                managed_benchmark_fact_source_ref_descriptor(
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
                for ref in command.source_refs
            ]
            if len(command.source_refs) != 1:
                _reject("fact source reference")
            source_id_sha = managed_benchmark_text_sha256(command.source_refs[0].source_id)
            classification = (
                command.quality.classification.value if command.quality is not None else "internal"
            )
            material = managed_benchmark_fact_operation_material(
                source_external_id_sha256=source_id_sha,
                content_sha256=managed_benchmark_text_sha256(command.text),
                kind=command.kind,
                classification=classification,
                source_refs=source_refs,
            )
            async with self.uow_factory() as uow:
                admission = await _managed_fact_admission(
                    uow,
                    command=command,
                    source_id_sha256=source_id_sha,
                    source_refs=source_refs,
                    material=material,
                    strict_v4_authority=self.strict_v4_authority,
                )
            command = replace(command, idempotency_key=admission.idempotency_key)
        return await self.inner.execute(command)


@dataclass(frozen=True, slots=True)
class ManagedBenchmarkFactMutationBlocker:
    """Reject every post-admission fact mutation in managed namespaces."""

    inner: MutationExecutor
    uow_factory: UnitOfWorkFactoryPort | None = None

    async def execute(self, command: object) -> object:
        if any(is_managed_benchmark_space_id(value) for value in _fact_mutation_spaces(command)):
            _reject("fact mutation")
        if self.uow_factory is not None:
            async with self.uow_factory() as uow:
                for fact_id in _fact_mutation_ids(command):
                    fact = await uow.facts.get_by_id(fact_id)
                    if fact is not None and is_managed_benchmark_space_id(str(fact.space_id)):
                        _reject("fact mutation")
                relation_id = getattr(command, "relation_id", None)
                if type(relation_id) is str:
                    relation = await uow.fact_relations.get_by_id(relation_id)
                    if relation is not None and is_managed_benchmark_space_id(
                        str(relation.space_id)
                    ):
                        _reject("fact mutation")
        return await self.inner.execute(command)


@dataclass(frozen=True, slots=True)
class ManagedBenchmarkDocumentMutationBlocker:
    """Resolve document ownership and reject managed process/delete mutations."""

    uow_factory: UnitOfWorkFactoryPort
    inner: MutationExecutor

    async def execute(self, command: object) -> object:
        document_id = getattr(command, "document_id", None)
        if type(document_id) is str:
            async with self.uow_factory() as uow:
                document = await uow.documents.get_by_id(document_id)
                if document is not None and is_managed_benchmark_space_id(str(document.space_id)):
                    _reject("document mutation")
        return await self.inner.execute(command)


@dataclass(frozen=True, slots=True)
class ManagedBenchmarkEnsureScopeAdmission:
    """Admit only the exact planned external scope/thread pair for managed runs."""

    uow_factory: UnitOfWorkFactoryPort
    inner: MutationExecutor
    strict_v4_authority: ManagedBenchmarkStrictV4CorpusAuthorityPort | None = None

    async def execute(self, command: object) -> object:
        space_slug = getattr(command, "space_slug", None)
        if type(space_slug) is str:
            async with self.uow_factory() as uow:
                record = await uow.benchmark_runs.get_by_space_slug(space_slug)
                if record is not None:
                    scope_ref = getattr(command, "memory_scope_external_ref", None)
                    thread_ref = getattr(command, "thread_external_ref", None)
                    if type(scope_ref) is not str or type(thread_ref) is not str:
                        _reject("scope creation")
                    if _is_strict_v4_record(record):
                        if self.strict_v4_authority is None:
                            _reject("strict-v4 authority")
                        self.strict_v4_authority.admit_corpus(
                            ManagedBenchmarkStrictV4CorpusClaim(
                                run_id_sha256=record.run_id_sha256,
                                binding_commitment_sha256=record.binding_commitment_sha256,
                                infinity_target_identity_sha256=(
                                    record.infinity_target_identity_sha256
                                ),
                                space_id=record.space_id,
                                space_slug=record.space_slug,
                                memory_scope_external_ref=scope_ref,
                                thread_external_ref=thread_ref,
                            )
                        )
                    else:
                        plan = _validated_active_plan(record)
                        scope_sha = managed_benchmark_text_sha256(scope_ref)
                        thread_sha = managed_benchmark_text_sha256(thread_ref)
                        matches = tuple(
                            item
                            for item in plan["corpora"]
                            if item["memory_scope_external_ref_sha256"] == scope_sha
                            and item["thread_external_ref_sha256"] == thread_sha
                        )
                        if len(matches) != 1:
                            _reject("scope creation")
        return await self.inner.execute(command)


@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCreateMemoryScopeAdmission:
    """Block foreign memory-scope creation inside a managed benchmark space."""

    uow_factory: UnitOfWorkFactoryPort
    inner: MutationExecutor

    async def execute(self, command: object) -> object:
        space_id = getattr(command, "space_id", None)
        if space_id is not None and is_managed_benchmark_space_id(str(space_id)):
            async with self.uow_factory() as uow:
                record = await uow.benchmark_runs.get_by_space_id(str(space_id))
                plan = _validated_active_plan(record)
                external_ref = getattr(command, "external_ref", None)
                if type(external_ref) is not str:
                    _reject("scope creation")
                scope_sha = managed_benchmark_text_sha256(external_ref)
                if not any(
                    item["memory_scope_external_ref_sha256"] == scope_sha
                    for item in plan["corpora"]
                ):
                    _reject("scope creation")
        return await self.inner.execute(command)


@dataclass(frozen=True, slots=True)
class _ManagedCorpusAdmission:
    value: dict[str, object]
    run_id_sha256: str
    cleanup_plan_sha256: str


@dataclass(frozen=True, slots=True)
class _ManagedFactAdmission:
    operation_sha256: str
    idempotency_key: str


def _validated_active_plan(record: object) -> dict[str, object]:
    if (
        record is None
        or record.state != "active"
        or record.projection_cleanup_state != "unsealed"
        or record.cleanup_plan_state != "sealed"
        or type(record.cleanup_plan_json) is not dict
        or type(record.cleanup_plan_sha256) is not str
    ):
        _reject("cleanup plan capability")
    return validate_managed_benchmark_cleanup_plan(
        record.cleanup_plan_json,
        record.cleanup_plan_sha256,
        run_id_sha256=record.run_id_sha256,
        binding_commitment_sha256=record.binding_commitment_sha256,
        infinity_target_identity_sha256=record.infinity_target_identity_sha256,
        space_slug=record.space_slug,
    ).value


async def _managed_fact_admission(
    uow: UnitOfWorkPort,
    *,
    command: RememberFactCommand,
    source_id_sha256: str,
    source_refs: list[dict[str, object]],
    material: dict[str, object],
    strict_v4_authority: ManagedBenchmarkStrictV4FactAuthorityPort | None,
) -> _ManagedFactAdmission:
    record = await uow.benchmark_runs.get_by_space_id(command.scope.space_id)
    if _is_strict_v4_record(record):
        if strict_v4_authority is None:
            _reject("strict-v4 authority")
        scope, thread = await _active_scope_thread(
            uow,
            space_id=command.scope.space_id,
            memory_scope_id=command.scope.memory_scope_id,
            thread_id=command.scope.thread_id,
        )
        source_refs_sha, ordered_source_refs, source_ref_root = source_ref_commitments(source_refs)
        claim = ManagedBenchmarkStrictV4FactClaim(
            run_id_sha256=record.run_id_sha256,
            binding_commitment_sha256=record.binding_commitment_sha256,
            infinity_target_identity_sha256=record.infinity_target_identity_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            memory_scope_external_ref=scope.external_ref,
            thread_external_ref=thread.external_ref,
            source_identity_sha256=source_id_sha256,
            source_content_sha256=str(material["content_sha256"]),
            operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
            source_refs_sha256=source_refs_sha,
            source_ref_root_sha256=source_ref_root,
            ordered_source_ref_descriptor_sha256=ordered_source_refs,
        )
        assert strict_v4_authority is not None
        admitted = strict_v4_authority.admit_fact(claim)
        return _ManagedFactAdmission(
            operation_sha256=admitted.operation_sha256,
            idempotency_key=admitted.idempotency_key,
        )
    corpus = await _managed_corpus(
        uow,
        space_id=command.scope.space_id,
        memory_scope_id=command.scope.memory_scope_id,
        thread_id=command.scope.thread_id,
        lane="fact",
    )
    operation_sha = _require_operation(corpus.value, source_id_sha256, material)
    return _ManagedFactAdmission(
        operation_sha256=operation_sha,
        idempotency_key=_managed_fact_idempotency_key(
            run_id_sha256=corpus.run_id_sha256,
            cleanup_plan_sha256=corpus.cleanup_plan_sha256,
            operation_sha256=operation_sha,
            source_id_sha256=source_id_sha256,
        ),
    )


def _is_strict_v4_record(record: object) -> bool:
    return bool(
        record is not None
        and getattr(record, "state", None) == "active"
        and getattr(record, "projection_cleanup_state", None) == "unsealed"
        and getattr(record, "cleanup_plan_state", None) == "recovery_blocked"
        and getattr(record, "cleanup_plan_json", None) is None
        and getattr(record, "cleanup_plan_sha256", None) is None
    )


async def require_managed_document_admission(
    *,
    uow: UnitOfWorkPort,
    command: IngestDocumentCommand,
    strict_v4_authority: ManagedBenchmarkStrictV4DocumentAuthorityPort | None = None,
) -> str | None:
    if not is_managed_benchmark_space_id(str(command.space_id)):
        return None
    metadata = command.chunk_metadata
    raw_refs = metadata.get("source_refs", []) if type(metadata) is dict else []
    if type(raw_refs) is not list or any(type(item) is not dict for item in raw_refs):
        _reject("document source references")
    fragments = [
        managed_benchmark_document_fragment_descriptor(
            sequence=item.sequence,
            char_start=item.char_start,
            char_end=item.char_end,
            kind=item.kind.value,
            text=item.text,
            node_kind=item.node_kind,
            heading=item.heading,
            ordinal_in_heading=item.ordinal_in_heading,
        )
        for item in fragment_document_text(command.text)
    ]
    source_id_sha = managed_benchmark_text_sha256(command.source_external_id)
    material = managed_benchmark_document_operation_material(
        source_external_id_sha256=source_id_sha,
        content_sha256=content_hash(command.text),
        title_sha256=managed_benchmark_text_sha256(command.title),
        source_type=command.source_type,
        classification=command.classification,
        source_refs=raw_refs,
        fragments=fragments,
    )
    record = await uow.benchmark_runs.get_by_space_id(str(command.space_id))
    if _is_strict_v4_record(record):
        if strict_v4_authority is None:
            _reject("strict-v4 document authority")
        scope, thread = await _active_scope_thread(
            uow,
            space_id=str(command.space_id),
            memory_scope_id=str(command.memory_scope_id),
            thread_id=str(command.thread_id) if command.thread_id is not None else None,
        )
        source_refs_sha, ordered_source_refs, source_ref_root = source_ref_commitments(raw_refs)
        fragments_sha, ordered_fragments, fragment_root = fragment_commitments(fragments)
        claim = ManagedBenchmarkStrictV4DocumentClaim(
            run_id_sha256=record.run_id_sha256,
            binding_commitment_sha256=record.binding_commitment_sha256,
            infinity_target_identity_sha256=record.infinity_target_identity_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            memory_scope_external_ref=scope.external_ref,
            thread_external_ref=thread.external_ref,
            source_identity_sha256=source_id_sha,
            source_content_sha256=str(material["content_sha256"]),
            operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
            source_refs_sha256=source_refs_sha,
            source_ref_root_sha256=source_ref_root,
            ordered_source_ref_descriptor_sha256=ordered_source_refs,
            fragments_sha256=fragments_sha,
            fragment_root_sha256=fragment_root,
            ordered_fragment_descriptor_sha256=ordered_fragments,
        )
        assert strict_v4_authority is not None
        return strict_v4_authority.admit_document(claim).idempotency_key
    corpus = await _managed_corpus(
        uow,
        space_id=str(command.space_id),
        memory_scope_id=str(command.memory_scope_id),
        thread_id=str(command.thread_id) if command.thread_id is not None else None,
        lane="document",
    )
    operation_sha = _require_operation(corpus.value, source_id_sha, material)
    return _managed_operation_idempotency_key(
        domain="document",
        run_id_sha256=corpus.run_id_sha256,
        cleanup_plan_sha256=corpus.cleanup_plan_sha256,
        operation_sha256=operation_sha,
        source_id_sha256=source_id_sha,
    )


async def _managed_corpus(
    uow: UnitOfWorkPort,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    lane: str,
) -> _ManagedCorpusAdmission:
    record = await uow.benchmark_runs.get_by_space_id(space_id)
    plan = _validated_active_plan(record)
    scope, thread = await _active_scope_thread(
        uow,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
    )
    scope_sha = managed_benchmark_text_sha256(scope.external_ref)
    thread_sha = managed_benchmark_text_sha256(thread.external_ref)
    matches = [
        item
        for item in plan["corpora"]
        if item["memory_scope_external_ref_sha256"] == scope_sha
        and item["thread_external_ref_sha256"] == thread_sha
        and item["infinity_lane"] == lane
    ]
    if len(matches) != 1:
        _reject("scope")
    return _ManagedCorpusAdmission(
        value=matches[0],
        run_id_sha256=record.run_id_sha256,
        cleanup_plan_sha256=record.cleanup_plan_sha256,
    )


async def _active_scope_thread(
    uow: UnitOfWorkPort, *, space_id: str, memory_scope_id: str, thread_id: str | None
) -> tuple[object, object]:
    scope = await uow.scope.get_memory_scope(memory_scope_id)
    thread = await uow.scope.get_thread(thread_id) if thread_id is not None else None
    if (
        scope is None
        or str(scope.space_id) != space_id
        or scope.status != LifecycleStatus.ACTIVE
        or thread is None
        or str(thread.memory_scope_id) != memory_scope_id
        or thread.status != LifecycleStatus.ACTIVE
    ):
        _reject("scope")
    return scope, thread


def _require_operation(
    corpus: dict[str, object], source_id_sha: str, material: dict[str, object]
) -> str:
    sources = corpus["ordered_infinity_source_external_id_sha256"]
    operations = corpus["ordered_infinity_operation_sha256"]
    content = corpus["ordered_infinity_content_sha256"]
    try:
        index = sources.index(source_id_sha)
    except ValueError:
        _reject("source")
    operation_sha = managed_benchmark_infinity_operation_sha256(material)
    if operations[index] != operation_sha or content[index] != material["content_sha256"]:
        _reject("operation")
    return operation_sha


def _managed_fact_idempotency_key(
    *,
    run_id_sha256: str,
    cleanup_plan_sha256: str,
    operation_sha256: str,
    source_id_sha256: str,
) -> str:
    return _managed_operation_idempotency_key(
        domain="fact",
        run_id_sha256=run_id_sha256,
        cleanup_plan_sha256=cleanup_plan_sha256,
        operation_sha256=operation_sha256,
        source_id_sha256=source_id_sha256,
    )


def _managed_operation_idempotency_key(
    *,
    domain: str,
    run_id_sha256: str,
    cleanup_plan_sha256: str,
    operation_sha256: str,
    source_id_sha256: str,
) -> str:
    material = "\n".join(
        (
            "memory-comparison-managed-operation-idempotency.v1",
            domain,
            run_id_sha256,
            cleanup_plan_sha256,
            operation_sha256,
            source_id_sha256,
        )
    ).encode("ascii")
    return f"managed-benchmark-{domain}-v1-{hashlib.sha256(material).hexdigest()}"


def _fact_mutation_spaces(command: object) -> tuple[str, ...]:
    spaces: list[str] = []
    direct_scope = getattr(command, "scope", None)
    direct_space = getattr(direct_scope, "space_id", None)
    if type(direct_space) is str:
        spaces.append(direct_space)
    command_space = getattr(command, "space_id", None)
    if command_space is not None:
        spaces.append(str(command_space))
    for field in (
        "identity",
        "successor_identity",
        "predecessor_identity",
        "challenger_identity",
        "challenged_identity",
    ):
        identity = getattr(command, field, None)
        scope = getattr(identity, "scope", None)
        space_id = getattr(scope, "space_id", None)
        if type(space_id) is str:
            spaces.append(space_id)
    return tuple(spaces)


def _fact_mutation_ids(command: object) -> tuple[str, ...]:
    values = (
        getattr(command, "fact_id", None),
        getattr(command, "source_fact_id", None),
        getattr(command, "target_fact_id", None),
    )
    return tuple(value for value in values if type(value) is str)


def _reject(label: str) -> None:
    raise MemoryConflictError(f"Managed benchmark {label} is not admitted")


__all__ = (
    "ManagedBenchmarkCreateMemoryScopeAdmission",
    "ManagedBenchmarkDocumentMutationBlocker",
    "ManagedBenchmarkEnsureScopeAdmission",
    "ManagedBenchmarkFactMutationBlocker",
    "ManagedBenchmarkRememberFactAdmission",
    "require_managed_document_admission",
)
