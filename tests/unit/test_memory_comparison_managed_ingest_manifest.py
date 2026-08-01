from __future__ import annotations

from copy import deepcopy

import pytest
from infinity_context_server.memory_comparison_http_ingest_observation import (
    HttpIngestIdentityObservation,
    ingest_identity_manifest,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
    ManagedIngestManifestParseError,
    parse_managed_ingest_identity_manifests,
)
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    IngestionOperation,
)

_INFINITY_TARGET = "1" * 64
_MEM0_TARGET = "2" * 64
_SOURCE_HASH = "a" * 64


def _infinity_fact(*, suffix: str = "1") -> HttpIngestIdentityObservation:
    return HttpIngestIdentityObservation(
        backend="infinity",
        operation_type="fact",
        complete=True,
        issues=(),
        canonical_record_ids=(f"fact-{suffix}",),
        fact_ids=(f"fact-{suffix}",),
        space_id=f"space-{suffix}",
        memory_scope_id=f"scope-{suffix}",
        thread_id=f"thread-{suffix}",
        source_ids=(f"source-{suffix}",),
        source_sha256=(_SOURCE_HASH,),
        status="active",
        version=1,
        request_id=f"infinity-request-{suffix}",
    )


def _infinity_document(*, suffix: str = "1") -> HttpIngestIdentityObservation:
    return HttpIngestIdentityObservation(
        backend="infinity",
        operation_type="document",
        complete=True,
        issues=(),
        canonical_record_ids=(f"document-{suffix}",),
        document_ids=(f"document-{suffix}",),
        chunk_ids=(f"chunk-{suffix}-1", f"chunk-{suffix}-2"),
        space_id=f"space-{suffix}",
        memory_scope_id=f"scope-{suffix}",
        thread_id=f"thread-{suffix}",
        source_ids=(f"source-{suffix}",),
        source_sha256=(_SOURCE_HASH,),
        status="active",
        indexing_status="indexed",
        request_id=f"infinity-request-{suffix}",
    )


def _mem0(*, suffix: str = "1") -> HttpIngestIdentityObservation:
    return HttpIngestIdentityObservation(
        backend="mem0",
        operation_type="messages",
        complete=True,
        issues=(),
        observed_memory_ids=(f"memory-{suffix}",),
        created_memory_ids=(f"memory-{suffix}",),
        source_ids=(f"source-{suffix}",),
        source_sha256=(_SOURCE_HASH,),
        request_id=f"mem0-request-{suffix}",
        events=("ADD",),
    )


def _view(
    role: str,
    observation: HttpIngestIdentityObservation,
    *,
    case_id: str = "case-1",
    corpus_id: str = "corpus-1",
    target: str | None = None,
) -> ManagedHttpIngestEvidenceView:
    manifest = ingest_identity_manifest((observation,)).metadata()
    operation = IngestionOperation(
        step=1,
        operation_type=observation.operation_type,
        success=True,
        metadata={"ingest_identity_observation": observation.metadata()},
    )
    result = BackendIngestResult(
        items_processed=1,
        operations=(operation,),
        metadata={
            "corpus_key": corpus_id,
            "ingest_identity_manifest": manifest,
        },
    )
    return ManagedHttpIngestEvidenceView(
        role,
        target or (_INFINITY_TARGET if role == "infinity-context" else _MEM0_TARGET),
        case_id,
        corpus_id,
        object(),
        result,
        None,
        (),
    )


def _pair(
    infinity: HttpIngestIdentityObservation,
    *,
    suffix: str = "1",
) -> tuple[ManagedHttpIngestEvidenceView, ...]:
    return (
        _view("infinity-context", infinity),
        _view("mem0", _mem0(suffix=suffix)),
    )


def _replace_result(
    view: ManagedHttpIngestEvidenceView,
    result: BackendIngestResult,
    *,
    corpus_id: str | None = None,
    case_id: str | None = None,
    target: str | None = None,
) -> ManagedHttpIngestEvidenceView:
    return ManagedHttpIngestEvidenceView(
        view.backend_role,
        target or view.target_identity_sha256,
        case_id or view.case_id,
        corpus_id or view.corpus_id,
        view.clean_state_validation,
        result,
        view.locomo_timestamp_verifier,
        view.locomo_timestamp_evidence,
    )


def _mutate_manifest(
    view: ManagedHttpIngestEvidenceView,
    mutation,
) -> ManagedHttpIngestEvidenceView:
    metadata = deepcopy(dict(view.ingest_result.metadata))
    mutation(metadata["ingest_identity_manifest"])
    result = BackendIngestResult(
        items_processed=view.ingest_result.items_processed,
        items_failed=view.ingest_result.items_failed,
        operations=view.ingest_result.operations,
        metadata=metadata,
    )
    return _replace_result(view, result)


def test_parses_fact_only_locomo_pair_into_exact_bundle() -> None:
    (bundle,) = parse_managed_ingest_identity_manifests(_pair(_infinity_fact()))

    assert bundle.case_id == "case-1"
    assert bundle.corpus_id == "corpus-1"
    assert bundle.infinity_target_identity_sha256 == _INFINITY_TARGET
    assert bundle.mem0_target_identity_sha256 == _MEM0_TARGET
    assert bundle.scope.space_id == "space-1"
    assert bundle.scope.memory_scope_id == "scope-1"
    assert bundle.scope.thread_id == "thread-1"
    assert bundle.manifest.infinity_fact_ids == ("fact-1",)
    assert bundle.manifest.infinity_document_ids == ()
    assert bundle.manifest.infinity_chunk_ids == ()
    assert bundle.manifest.mem0_created_memory_ids == ("memory-1",)
    assert bundle.manifest.infinity_source_ids == ("source-1",)
    assert bundle.manifest.mem0_source_ids == ("source-1",)
    assert bundle.manifest.operation_count == 2
    assert bundle.manifest.complete is True


def test_parses_longmemeval_document_and_chunks() -> None:
    (bundle,) = parse_managed_ingest_identity_manifests(_pair(_infinity_document()))

    assert bundle.manifest.infinity_fact_ids == ()
    assert bundle.manifest.infinity_document_ids == ("document-1",)
    assert bundle.manifest.infinity_chunk_ids == ("chunk-1-1", "chunk-1-2")


def test_pairs_each_unique_corpus_while_preserving_first_seen_order() -> None:
    infinity_one, mem0_one = _pair(_infinity_fact())
    infinity_two = _view(
        "infinity-context",
        _infinity_document(suffix="2"),
        case_id="case-2",
        corpus_id="corpus-2",
    )
    mem0_two = _view(
        "mem0",
        _mem0(suffix="2"),
        case_id="case-2",
        corpus_id="corpus-2",
    )

    bundles = parse_managed_ingest_identity_manifests(
        (infinity_one, infinity_two, mem0_one, mem0_two)
    )

    assert tuple(item.corpus_id for item in bundles) == ("corpus-1", "corpus-2")


@pytest.mark.parametrize(
    "views,code",
    (
        ((), "managed_ingest_views_invalid"),
        ((_view("infinity-context", _infinity_fact()),), "managed_ingest_backend_coverage_invalid"),
        (
            (
                _view("infinity-context", _infinity_fact()),
                _view("infinity-context", _infinity_fact()),
                _view("mem0", _mem0()),
            ),
            "managed_ingest_duplicate_view",
        ),
        (
            (
                _view("infinity-context", _infinity_fact()),
                _view("mem0", _mem0(), case_id="other-case"),
            ),
            "managed_ingest_cross_corpus_mismatch",
        ),
    ),
)
def test_rejects_incomplete_duplicate_or_cross_case_pairing(views, code: str) -> None:
    with pytest.raises(ManagedIngestManifestParseError, match=f"^{code}$"):
        parse_managed_ingest_identity_manifests(views)


def test_rejects_cross_corpus_target_mismatch() -> None:
    first = _pair(_infinity_fact())
    second_infinity = _view(
        "infinity-context",
        _infinity_document(suffix="2"),
        case_id="case-2",
        corpus_id="corpus-2",
        target="3" * 64,
    )
    second_mem0 = _view("mem0", _mem0(suffix="2"), case_id="case-2", corpus_id="corpus-2")

    with pytest.raises(ManagedIngestManifestParseError, match="^managed_ingest_target_mismatch$"):
        parse_managed_ingest_identity_manifests((*first, second_infinity, second_mem0))


def test_rejects_manifest_flat_lane_corruption() -> None:
    infinity, mem0 = _pair(_infinity_fact())
    corrupted = _mutate_manifest(
        infinity,
        lambda manifest: manifest["fact_ids"].append("forged-fact"),
    )

    with pytest.raises(ManagedIngestManifestParseError, match="^managed_ingest_manifest_invalid$"):
        parse_managed_ingest_identity_manifests((corrupted, mem0))


def test_rejects_manifest_not_bound_to_result_operations() -> None:
    infinity, mem0 = _pair(_infinity_fact())
    operation = infinity.ingest_result.operations[0]
    result = BackendIngestResult(
        items_processed=1,
        operations=(
            IngestionOperation(
                step=operation.step,
                operation_type=operation.operation_type,
                success=True,
                metadata={"ingest_identity_observation": {"forged": True}},
            ),
        ),
        metadata=infinity.ingest_result.metadata,
    )

    with pytest.raises(
        ManagedIngestManifestParseError, match="^managed_ingest_result_binding_invalid$"
    ):
        parse_managed_ingest_identity_manifests((_replace_result(infinity, result), mem0))


def test_rejects_result_corpus_key_mismatch() -> None:
    infinity, mem0 = _pair(_infinity_fact())
    metadata = dict(infinity.ingest_result.metadata)
    metadata["corpus_key"] = "other-corpus"
    result = BackendIngestResult(
        items_processed=1,
        operations=infinity.ingest_result.operations,
        metadata=metadata,
    )

    with pytest.raises(
        ManagedIngestManifestParseError, match="^managed_ingest_cross_corpus_mismatch$"
    ):
        parse_managed_ingest_identity_manifests((_replace_result(infinity, result), mem0))


def test_rejects_mem0_scope_injection() -> None:
    infinity, mem0 = _pair(_infinity_fact())
    metadata = deepcopy(dict(mem0.ingest_result.metadata))
    manifest = metadata["ingest_identity_manifest"]
    manifest["space_id"] = "forged-space"
    manifest["memory_scope_id"] = "forged-scope"
    manifest["operations"][0]["space_id"] = "forged-space"
    manifest["operations"][0]["memory_scope_id"] = "forged-scope"
    result = BackendIngestResult(
        items_processed=1,
        operations=(
            IngestionOperation(
                step=1,
                operation_type="messages",
                success=True,
                metadata={"ingest_identity_observation": manifest["operations"][0]},
            ),
        ),
        metadata=metadata,
    )

    with pytest.raises(ManagedIngestManifestParseError, match="^managed_ingest_scope_mismatch$"):
        parse_managed_ingest_identity_manifests((infinity, _replace_result(mem0, result)))


def test_rejects_incomplete_and_duplicate_combined_manifests() -> None:
    infinity, mem0 = _pair(_infinity_fact())
    incomplete = _mutate_manifest(
        mem0,
        lambda manifest: (
            manifest.__setitem__("complete", False),
            manifest["issues"].append("source_ids_missing"),
        ),
    )
    with pytest.raises(ManagedIngestManifestParseError):
        parse_managed_ingest_identity_manifests((infinity, incomplete))

    duplicate = _mutate_manifest(
        mem0,
        lambda manifest: (
            manifest["created_memory_ids"].append("memory-1"),
            manifest["observed_memory_ids"].append("memory-1"),
        ),
    )
    with pytest.raises(ManagedIngestManifestParseError):
        parse_managed_ingest_identity_manifests((infinity, duplicate))


def test_rejects_cross_backend_source_pair_mismatch() -> None:
    with pytest.raises(
        ManagedIngestManifestParseError,
        match="^managed_ingest_source_pair_mismatch$",
    ):
        parse_managed_ingest_identity_manifests(_pair(_infinity_fact(), suffix="2"))


def test_bundle_rejects_forged_manifest_and_scope_with_stable_errors() -> None:
    with pytest.raises(
        ManagedIngestManifestParseError,
        match="^managed_ingest_manifest_type_invalid$",
    ):
        ManagedCorpusIngestIdentity(
            "case-1",
            "corpus-1",
            _INFINITY_TARGET,
            _MEM0_TARGET,
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )

    (valid,) = parse_managed_ingest_identity_manifests(_pair(_infinity_fact()))
    with pytest.raises(
        ManagedIngestManifestParseError,
        match="^managed_ingest_scope_type_invalid$",
    ):
        ManagedCorpusIngestIdentity(
            valid.case_id,
            valid.corpus_id,
            valid.infinity_target_identity_sha256,
            valid.mem0_target_identity_sha256,
            valid.manifest,
            object(),  # type: ignore[arg-type]
        )
