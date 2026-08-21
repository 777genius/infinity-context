"""Streaming strict-v4 cleanup operations from the sealed managed-v5 projection."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    OPERATION_SCHEMA,
    PROFILE_ORACLES,
    ManagedCleanupV3Error,
    ManagedCleanupV3Operation,
    commitment,
    corpus_identity_sha256,
    fragment_commitments,
    memory_scope_external_ref_sha256,
    source_ref_commitments,
    thread_external_ref_sha256,
)
from infinity_context_core.ports.original_pair_identity_authority import (
    LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256,
    OriginalPairIdentityAuthorityPort,
)

from infinity_context_server.memory_comparison_canonical_source_hash import (
    document_source_hash,
    memory_source_hash,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
    sanitize_source_refs,
    valid_conversation_messages,
)
from infinity_context_server.memory_comparison_http_ingest_request import (
    source_reference_payload,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_v5_operation_material import (
    managed_v5_infinity_document_operation_material,
    managed_v5_infinity_fact_operation_material,
    managed_v5_infinity_fragment_descriptor,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)


class ManagedV5CleanupV4ProjectionError(ManagedCleanupV3Error):
    """Stable fail-closed rejection of non-canonical production projection."""


@final
@dataclass(frozen=True, slots=True)
class ManagedV5CleanupV4OperationProjector:
    """Re-iterable factory whose iterators retain at most one corpus of material.

    Each call to :meth:`iter_operations` creates a new one-shot iterator.  It
    validates every item against the sealed managed-v5 manifest before yielding
    it and never creates a full cleanup-operation collection.
    """

    projection: ManagedPublicRunProjection
    manifest_authority: ManagedMem0V5ManifestAuthority
    admission_commitment_sha256: str
    profile_id: str
    original_pair_authority: OriginalPairIdentityAuthorityPort | None = None

    def __post_init__(self) -> None:
        oracle = PROFILE_ORACLES.get(self.profile_id)
        bindings = getattr(self.projection, "bindings", None)
        pair_authority = self.original_pair_authority
        if (
            type(self.projection) is not ManagedPublicRunProjection
            or type(self.manifest_authority) is not ManagedMem0V5ManifestAuthority
            or oracle is None
            or not is_sha256(self.admission_commitment_sha256)
            or bindings is None
            or bindings.profile_id != self.profile_id
            or bindings.scope != "full"
            or bindings.dataset_sha256 != oracle["dataset_sha256"]
            or self.manifest_authority.operation_count != oracle["operation_count"]
            or self.manifest_authority.corpus_count != oracle["corpus_count"]
        ):
            _fail("managed_v5_cleanup_v4_projector_binding_invalid")
        if self.profile_id == "mem0-longmemeval-top50-v1":
            if not _pair_authority_valid(pair_authority, oracle):
                _fail("managed_v5_cleanup_v4_pair_authority_invalid")
        elif pair_authority is not None:
            _fail("managed_v5_cleanup_v4_pair_authority_invalid")
        self.manifest_authority.__post_init__()

    def iter_operations(self) -> Iterator[ManagedCleanupV3Operation]:
        return self._iterate()

    def iter_a1_operation_sha256(self) -> Iterator[str]:
        # A1 commits only the admitted ordered Mem0 source-unit identity. Building
        # the full Infinity operation here would redundantly re-fragment every
        # LongMemEval document and repeat original-pair lookups before A2.
        for sequence, unit in enumerate(self.manifest_authority.units):
            yield managed_v5_a1_operation_sha256(
                admission_commitment_sha256=self.admission_commitment_sha256,
                unit_index=sequence,
                unit_identity_sha256=unit.unit_identity_sha256,
            )

    def iter_reconstructed_corpora(self) -> Iterator[PublicBenchmarkCase]:
        """Yield each exact gold-blind corpus once for canonical execution."""

        for case in self._representatives():
            rebuilt = _reconstruct(case)
            if rebuilt.memory_scope_external_ref != case.corpus_id:
                _fail("managed_v5_cleanup_v4_scope_mismatch")
            yield rebuilt

    def _iterate(self) -> Iterator[ManagedCleanupV3Operation]:
        units = self.manifest_authority.units
        sequence = 0
        for case in self._representatives():
            rebuilt = _reconstruct(case)
            if rebuilt.memory_scope_external_ref != case.corpus_id:
                _fail("managed_v5_cleanup_v4_scope_mismatch")
            scope_sha = memory_scope_external_ref_sha256(case.corpus_id)
            thread_sha = thread_external_ref_sha256(rebuilt.thread_external_ref)
            if rebuilt.benchmark == "locomo":
                for memory in rebuilt.memories:
                    operation = _fact_operation(
                        sequence=sequence,
                        memory=memory,
                        unit=_require_unit(units, sequence, case.corpus_id),
                        scope_sha256=scope_sha,
                        thread_sha256=thread_sha,
                        admission_commitment_sha256=self.admission_commitment_sha256,
                    )
                    yield operation
                    sequence += 1
            elif rebuilt.benchmark == "longmemeval":
                documents = iter(conversation_documents(rebuilt))
                for conversation in rebuilt.conversations:
                    valid_messages = valid_conversation_messages(conversation)
                    if not valid_messages:
                        continue
                    try:
                        document = next(documents)
                    except StopIteration:
                        _fail("managed_v5_cleanup_v4_document_alignment_invalid")
                    operation = _document_operation(
                        sequence=sequence,
                        document=document,
                        unit=_require_unit(units, sequence, case.corpus_id),
                        valid_message_count=len(valid_messages),
                        scope_sha256=scope_sha,
                        thread_sha256=thread_sha,
                        admission_commitment_sha256=self.admission_commitment_sha256,
                        pair_authority=self.original_pair_authority,
                    )
                    yield operation
                    sequence += 1
                try:
                    next(documents)
                except StopIteration:
                    pass
                else:
                    _fail("managed_v5_cleanup_v4_document_alignment_invalid")
            else:
                _fail("managed_v5_cleanup_v4_benchmark_invalid")
        if sequence != len(units):
            _fail("managed_v5_cleanup_v4_operation_count_invalid")

    def _representatives(self) -> Iterator[ManagedRunCase]:
        representatives: dict[str, object] = {}
        for case in self.projection.cases:
            prior = representatives.get(case.corpus_id)
            if prior is not None:
                if prior != case.record:
                    _fail("managed_v5_cleanup_v4_corpus_conflict")
                continue
            representatives[case.corpus_id] = case.record
            yield case


def managed_v5_a1_operation_sha256(
    *, admission_commitment_sha256: str, unit_index: int, unit_identity_sha256: str
) -> str:
    """Return the exact operation identity used by managed-v5 progress/runtime."""

    if (
        not is_sha256(admission_commitment_sha256)
        or type(unit_index) is not int
        or unit_index < 0
        or not is_sha256(unit_identity_sha256)
    ):
        _fail("managed_v5_cleanup_v4_a1_identity_invalid")
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission_commitment_sha256,
            "unit_index": unit_index,
            "unit_identity_sha256": unit_identity_sha256,
        }
    )


def _fact_operation(
    *,
    sequence: int,
    memory: BenchmarkMemoryInput,
    unit: ManagedMem0V5SourceUnit,
    scope_sha256: str,
    thread_sha256: str,
    admission_commitment_sha256: str,
) -> ManagedCleanupV3Operation:
    identity = memory_source_hash(memory)
    _match_source(unit, identity.source_id, identity.source_sha256)
    ref = source_reference_payload(
        source_type="memory_comparison_benchmark",
        source_id=identity.source_id,
        quote_preview=memory.text,
    )
    descriptor = managed_benchmark_fact_source_ref_descriptor(
        source_type=str(ref["source_type"]),
        source_id=str(ref["source_id"]),
        quote_preview=str(ref["quote_preview"]),
    )
    material = managed_v5_infinity_fact_operation_material(memory)
    refs_sha, refs, refs_root = source_ref_commitments((descriptor,))
    fragments_sha, fragments, fragments_root = fragment_commitments(())
    if material["source_refs_sha256"] != refs_sha:
        _fail("managed_v5_cleanup_v4_fact_material_invalid")
    return _operation(
        sequence=sequence,
        lane="fact",
        scope_sha256=scope_sha256,
        thread_sha256=thread_sha256,
        source_identity_sha256=managed_benchmark_text_sha256(identity.source_id),
        source_content_sha256=identity.source_sha256,
        operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
        admission_commitment_sha256=admission_commitment_sha256,
        unit_identity_sha256=unit.unit_identity_sha256,
        original_pair_identity_sha256=None,
        valid_message_count=1,
        source_refs_sha256=refs_sha,
        source_refs=refs,
        source_ref_root_sha256=refs_root,
        fragments_sha256=fragments_sha,
        fragments=fragments,
        fragment_root_sha256=fragments_root,
    )


def _document_operation(
    *,
    sequence: int,
    document: BenchmarkDocumentInput,
    unit: ManagedMem0V5SourceUnit,
    valid_message_count: int,
    scope_sha256: str,
    thread_sha256: str,
    admission_commitment_sha256: str,
    pair_authority: OriginalPairIdentityAuthorityPort | None,
) -> ManagedCleanupV3Operation:
    identity = document_source_hash(document)
    _match_source(unit, identity.source_id, identity.source_sha256)
    source_identity = managed_benchmark_text_sha256(identity.source_id)
    if pair_authority is None:
        _fail("managed_v5_cleanup_v4_pair_authority_invalid")
    original_pair_identity = pair_authority.lookup(
        sequence=sequence,
        corpus_id=unit.corpus_id,
        normalized_source_id=identity.source_id,
    )
    if not is_sha256(original_pair_identity):
        _fail("managed_v5_cleanup_v4_original_pair_identity_invalid")
    source_refs = tuple(sanitize_source_refs(document.source_refs))
    fragments = fragment_document_text(document.text)
    fragment_descriptors = tuple(
        managed_v5_infinity_fragment_descriptor(item) for item in fragments
    )
    material = managed_v5_infinity_document_operation_material(document, fragments=fragments)
    refs_sha, refs, refs_root = source_ref_commitments(source_refs)
    fragments_sha, fragment_hashes, fragments_root = fragment_commitments(fragment_descriptors)
    if (
        material["source_refs_sha256"] != refs_sha
        or material["fragments_sha256"] != fragments_sha
        or material["fragment_count"] != len(fragment_hashes)
    ):
        _fail("managed_v5_cleanup_v4_document_material_invalid")
    return _operation(
        sequence=sequence,
        lane="document",
        scope_sha256=scope_sha256,
        thread_sha256=thread_sha256,
        source_identity_sha256=source_identity,
        source_content_sha256=identity.source_sha256,
        operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
        admission_commitment_sha256=admission_commitment_sha256,
        unit_identity_sha256=unit.unit_identity_sha256,
        original_pair_identity_sha256=original_pair_identity,
        valid_message_count=valid_message_count,
        source_refs_sha256=refs_sha,
        source_refs=refs,
        source_ref_root_sha256=refs_root,
        fragments_sha256=fragments_sha,
        fragments=fragment_hashes,
        fragment_root_sha256=fragments_root,
    )


def _operation(
    *,
    sequence: int,
    lane: str,
    scope_sha256: str,
    thread_sha256: str,
    source_identity_sha256: str,
    source_content_sha256: str,
    operation_commitment_sha256: str,
    admission_commitment_sha256: str,
    unit_identity_sha256: str,
    original_pair_identity_sha256: str | None,
    valid_message_count: int,
    source_refs_sha256: str,
    source_refs: tuple[str, ...],
    source_ref_root_sha256: str,
    fragments_sha256: str,
    fragments: tuple[str, ...],
    fragment_root_sha256: str,
) -> ManagedCleanupV3Operation:
    a1_operation = managed_v5_a1_operation_sha256(
        admission_commitment_sha256=admission_commitment_sha256,
        unit_index=sequence,
        unit_identity_sha256=unit_identity_sha256,
    )
    body: dict[str, object] = {
        "schema_version": OPERATION_SCHEMA,
        "sequence": sequence,
        "lane": lane,
        "corpus_identity_sha256": corpus_identity_sha256(
            lane=lane,
            memory_scope_external_ref_sha256=scope_sha256,
            thread_external_ref_sha256=thread_sha256,
        ),
        "memory_scope_external_ref_sha256": scope_sha256,
        "thread_external_ref_sha256": thread_sha256,
        "source_identity_sha256": source_identity_sha256,
        "source_content_sha256": source_content_sha256,
        "operation_commitment_sha256": operation_commitment_sha256,
        "a1_operation_sha256": a1_operation,
        "original_pair_identity_sha256": original_pair_identity_sha256,
        "valid_message_count": valid_message_count,
        "source_refs_sha256": source_refs_sha256,
        "ordered_source_ref_descriptor_sha256": list(source_refs),
        "source_ref_root_sha256": source_ref_root_sha256,
        "fragments_sha256": fragments_sha256,
        "ordered_fragment_descriptor_sha256": list(fragments),
        "fragment_root_sha256": fragment_root_sha256,
    }
    return ManagedCleanupV3Operation(
        **{
            key: tuple(value)
            if key
            in {
                "ordered_source_ref_descriptor_sha256",
                "ordered_fragment_descriptor_sha256",
            }
            else value
            for key, value in body.items()
            if key != "schema_version"
        },
        operation_sha256=commitment("operation/v4", body),
    )  # type: ignore[arg-type]


def _require_unit(
    units: tuple[ManagedMem0V5SourceUnit, ...],
    sequence: int,
    corpus_id: str,
) -> ManagedMem0V5SourceUnit:
    if sequence >= len(units):
        _fail("managed_v5_cleanup_v4_operation_count_invalid")
    unit = units[sequence]
    if unit.sequence != sequence or unit.corpus_id != corpus_id:
        _fail("managed_v5_cleanup_v4_manifest_alignment_invalid")
    return unit


def _match_source(unit: ManagedMem0V5SourceUnit, source_id: str, source_sha256: str) -> None:
    if unit.source_id != source_id or unit.source_sha256 != source_sha256:
        _fail("managed_v5_cleanup_v4_manifest_alignment_invalid")


def _pair_authority_valid(value: object, oracle: Mapping[str, object]) -> bool:
    try:
        profile_id = value.profile_id  # type: ignore[attr-defined]
        dataset_sha256 = value.dataset_sha256  # type: ignore[attr-defined]
        operation_count = value.operation_count  # type: ignore[attr-defined]
        slot_count = value.original_pair_slot_count  # type: ignore[attr-defined]
        omitted_count = value.omitted_source_identity_count  # type: ignore[attr-defined]
        omitted_source_root = value.omitted_source_identity_root_sha256  # type: ignore[attr-defined]
        omitted_pair_root = value.omitted_original_pair_identity_root_sha256  # type: ignore[attr-defined]
        slot_root = value.original_pair_slot_root_sha256  # type: ignore[attr-defined]
        mapping_root = value.ordered_mapping_root_sha256  # type: ignore[attr-defined]
        terminal = value.terminal_commitment_sha256  # type: ignore[attr-defined]
        lookup = value.lookup  # type: ignore[attr-defined]
        return (
            type(profile_id) is str
            and profile_id == "mem0-longmemeval-top50-v1"
            and type(dataset_sha256) is str
            and dataset_sha256 == oracle["dataset_sha256"]
            and type(operation_count) is int
            and operation_count == oracle["operation_count"]
            and type(slot_count) is int
            and slot_count == oracle["original_pair_slot_count"]
            and type(omitted_count) is int
            and omitted_count == oracle["omitted_source_identity_count"]
            and type(omitted_source_root) is str
            and omitted_source_root == oracle["omitted_source_identity_root_sha256"]
            and type(omitted_pair_root) is str
            and omitted_pair_root == LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256
            and type(slot_root) is str
            and is_sha256(slot_root)
            and type(mapping_root) is str
            and is_sha256(mapping_root)
            and type(terminal) is str
            and is_sha256(terminal)
            and callable(lookup)
        )
    except (AttributeError, KeyError, TypeError):
        return False


def _reconstruct(case: ManagedRunCase) -> PublicBenchmarkCase:
    try:
        return _reconstruct_managed_corpus_case(
            case.record,
            case_id=case.case_id,
            question="managed-cleanup-v4-gold-blind-projection",
            temporal_context={},
        )
    except Exception as exc:
        raise ManagedV5CleanupV4ProjectionError(
            "managed_v5_cleanup_v4_reconstruction_invalid"
        ) from exc


def _fail(code: str) -> None:
    raise ManagedV5CleanupV4ProjectionError(code)


__all__ = (
    "ManagedV5CleanupV4OperationProjector",
    "ManagedV5CleanupV4ProjectionError",
    "managed_v5_a1_operation_sha256",
)
