from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpError,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedDerivedPresenceObservation,
    ManagedGraphitiIdentitySnapshot,
    ManagedGraphitiPresenceObservation,
    ManagedIngestIdentityManifest,
    ManagedProjectionOutboxObservation,
    ManagedQdrantPointIdentity,
    ManagedQdrantPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    MANAGED_PROJECTION_MANIFEST_SCHEMA_VERSION,
    ManagedProjectionManifestError,
    build_managed_projection_manifest,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_RUN_ID = "managed-run-1"
_INFINITY_TARGET = "a" * 64
_MEM0_TARGET = "b" * 64
_QDRANT_TARGET = "c" * 64
_QDRANT_BINDING = "d" * 64
_GRAPHITI_TARGET = "e" * 64
_GRAPHITI_BINDING = "f" * 64
_SPACE_ID = "benchmark-space-1"


def _bindings() -> FullComparisonRunBindings:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return create_full_comparison_run_bindings(
        run_id=_RUN_ID,
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256="3" * 64,
        selection_fingerprint_sha256="4" * 64,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", _INFINITY_TARGET),
            FullComparisonBackendTarget("mem0", _MEM0_TARGET),
        ),
        scope="canary",
    )


def _registration(
    bindings: FullComparisonRunBindings,
) -> ManagedBenchmarkRunRegistration:
    return ManagedBenchmarkRunRegistration(
        schema_version="memory-comparison-run-registration-response.v1",
        authority="infinity_canonical",
        run_id_sha256=hashlib.sha256(bindings.run_id.encode()).hexdigest(),
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        infinity_target_identity_sha256=_INFINITY_TARGET,
        space_id=_SPACE_ID,
        space_slug="memory-comparison-managed-run-1",
        state="active",
        created=True,
    )


def _corpus(
    suffix: str,
    *,
    memory_scope_id: str | None = None,
    fact_id: str | None = None,
    graph_episode_id: str | None = None,
    qdrant_point_id: str | None = None,
) -> tuple[ManagedCorpusIngestIdentity, ManagedDerivedPresenceObservation]:
    scope = ManagedCanonicalProjectionScope(
        _SPACE_ID,
        memory_scope_id or f"scope-{suffix}",
        f"thread-{suffix}",
    )
    manifest = ManagedIngestIdentityManifest(
        corpus_id=f"corpus-{suffix}",
        infinity_fact_ids=(fact_id or f"fact-{suffix}",),
        infinity_document_ids=(f"document-{suffix}",),
        infinity_chunk_ids=(f"chunk-{suffix}-2", f"chunk-{suffix}-1"),
        infinity_source_ids=(f"source-{suffix}",),
        infinity_source_sha256=("5" * 64,),
        mem0_created_memory_ids=(f"memory-{suffix}",),
        mem0_source_ids=(f"source-{suffix}",),
        mem0_source_sha256=("5" * 64,),
        operation_count=3,
        complete=True,
        issues=(),
    )
    points = tuple(
        ManagedQdrantPointIdentity(
            chunk_id,
            (
                qdrant_point_id
                if index == 1 and qdrant_point_id is not None
                else f"point-{suffix}-{index}"
            ),
        )
        for index, chunk_id in enumerate(manifest.infinity_chunk_ids, start=1)
    )
    qdrant = ManagedQdrantPresenceObservation(
        "v1",
        _QDRANT_TARGET,
        _QDRANT_BINDING,
        points,
        points,
        tuple(item.point_id for item in points),
        len(points),
        True,
    )
    graph_snapshot = ManagedGraphitiIdentitySnapshot(
        (graph_episode_id or f"episode-{suffix}",),
        (f"entity-{suffix}",),
        (f"mentions-{suffix}",),
        (f"relates-{suffix}",),
    )
    graphiti = ManagedGraphitiPresenceObservation(
        scope,
        _GRAPHITI_TARGET,
        _GRAPHITI_BINDING,
        graph_snapshot,
        graph_snapshot.exact_identity_count,
        True,
    )
    bundle = ManagedCorpusIngestIdentity(
        case_id=f"case-{suffix}",
        corpus_id=manifest.corpus_id,
        infinity_target_identity_sha256=_INFINITY_TARGET,
        mem0_target_identity_sha256=_MEM0_TARGET,
        manifest=manifest,
        scope=scope,
    )
    presence = ManagedDerivedPresenceObservation(
        lifecycle_target_identity_sha256=_INFINITY_TARGET,
        ingest_manifest_sha256=managed_ingest_identity_manifest_sha256(manifest, scope),
        scope=scope,
        outbox=ManagedProjectionOutboxObservation(
            done_chunk_ids=manifest.infinity_chunk_ids,
            done_fact_ids=manifest.infinity_fact_ids,
            done_event_count=3,
            complete=True,
        ),
        qdrant=qdrant,
        graphiti=graphiti,
    )
    return bundle, presence


def _build(
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
    presence: tuple[ManagedDerivedPresenceObservation, ...],
    *,
    cases: tuple[ManagedRunCase, ...] | None = None,
):
    bindings = _bindings()
    return build_managed_projection_manifest(
        bindings=bindings,
        registration=_registration(bindings),
        cases=(
            tuple(ManagedRunCase(item.case_id, item.corpus_id, {}) for item in corpora)
            if cases is None
            else cases
        ),
        corpora=corpora,
        presence=presence,
    )


def test_builds_exact_sorted_core_manifest_and_defensive_projection() -> None:
    corpus_b, presence_b = _corpus("b", memory_scope_id="scope-z")
    corpus_a, presence_a = _corpus("a", memory_scope_id="scope-a")

    result = _build((corpus_b, corpus_a), (presence_b, presence_a))

    manifest = result.projection_manifest
    assert manifest["schema_version"] == MANAGED_PROJECTION_MANIFEST_SCHEMA_VERSION
    assert manifest["run_id_sha256"] == hashlib.sha256(_RUN_ID.encode()).hexdigest()
    assert manifest["binding_commitment_sha256"] == _bindings().binding_commitment_sha256
    assert manifest["infinity_target_identity_sha256"] == _INFINITY_TARGET
    assert manifest["space_id"] == _SPACE_ID
    scopes = manifest["scopes"]
    assert isinstance(scopes, list)
    assert [item["memory_scope_id"] for item in scopes] == ["scope-a", "scope-z"]
    first = scopes[0]
    assert first["chunk_ids"] == ["chunk-a-1", "chunk-a-2"]
    assert first["fact_ids"] == ["fact-a"]
    assert first["document_ids"] == ["document-a"]
    assert first["qdrant"] == {
        "target_commitment_sha256": _QDRANT_TARGET,
        "manifest_binding_sha256": _QDRANT_BINDING,
    }
    assert first["graphiti"] == {
        "target_commitment_sha256": _GRAPHITI_TARGET,
        "manifest_binding_sha256": _GRAPHITI_BINDING,
        "episode_ids": ["episode-a"],
        "entity_ids": ["entity-a"],
        "mentions_edge_ids": ["mentions-a"],
        "relates_to_edge_ids": ["relates-a"],
    }
    assert first["cognee"] == {
        "disposition": "not_projected",
        "policy_sha256": MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }
    expected_digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert result.projection_manifest_sha256 == expected_digest

    first["chunk_ids"].append("tampered")
    assert "tampered" not in result.projection_manifest["scopes"][0]["chunk_ids"]


@pytest.mark.parametrize(
    ("change", "code"),
    (
        (
            {"run_id_sha256": "9" * 64},
            "managed_projection_registration_mismatch",
        ),
        (
            {"binding_commitment_sha256": "9" * 64},
            "managed_projection_registration_mismatch",
        ),
        (
            {"infinity_target_identity_sha256": "9" * 64},
            "managed_projection_registration_mismatch",
        ),
    ),
)
def test_rejects_registration_binding_mismatch(
    change: dict[str, str],
    code: str,
) -> None:
    bindings = _bindings()
    corpus, presence = _corpus("a")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        build_managed_projection_manifest(
            bindings=bindings,
            registration=replace(_registration(bindings), **change),
            cases=(ManagedRunCase(corpus.case_id, corpus.corpus_id, {}),),
            corpora=(corpus,),
            presence=(presence,),
        )

    assert caught.value.code == code


def test_rejects_presence_manifest_mismatch() -> None:
    corpus, presence = _corpus("a")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), (replace(presence, ingest_manifest_sha256="9" * 64),))

    assert caught.value.code == "managed_projection_evidence_mismatch"


def test_rejects_missing_required_qdrant_lane() -> None:
    corpus, presence = _corpus("a")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), (replace(presence, qdrant=None),))

    assert caught.value.code == "managed_projection_qdrant_mismatch"


def test_rejects_missing_required_graphiti_lane() -> None:
    corpus, presence = _corpus("a")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), (replace(presence, graphiti=None),))

    assert caught.value.code == "managed_projection_graphiti_mismatch"


def test_rejects_duplicate_scope_or_corpus_coverage() -> None:
    corpus, presence = _corpus("a")
    cases = (ManagedRunCase(corpus.case_id, corpus.corpus_id, {}),)

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus, corpus), (presence, presence), cases=cases)

    assert caught.value.code == "managed_projection_coverage_invalid"


def test_rejects_globally_duplicate_canonical_identity() -> None:
    corpus_a, presence_a = _corpus("a", fact_id="fact-shared")
    corpus_b, presence_b = _corpus("b", fact_id="fact-shared")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus_a, corpus_b), (presence_a, presence_b))

    assert caught.value.code == "managed_projection_canonical_ids_ambiguous"


def test_rejects_globally_duplicate_graphiti_identity() -> None:
    corpus_a, presence_a = _corpus("a", graph_episode_id="episode-shared")
    corpus_b, presence_b = _corpus("b", graph_episode_id="episode-shared")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus_a, corpus_b), (presence_a, presence_b))

    assert caught.value.code == "managed_projection_graphiti_ids_ambiguous"


def test_rejects_globally_duplicate_qdrant_point_identity() -> None:
    corpus_a, presence_a = _corpus("a", qdrant_point_id="point-shared")
    corpus_b, presence_b = _corpus("b", qdrant_point_id="point-shared")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus_a, corpus_b), (presence_a, presence_b))

    assert caught.value.code == "managed_projection_qdrant_ids_ambiguous"


def test_rejects_incomplete_tuple_coverage() -> None:
    corpus, _ = _corpus("a")

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), ())

    assert caught.value.code == "managed_projection_coverage_invalid"


def test_rejects_omitted_admitted_corpus() -> None:
    corpus_a, presence_a = _corpus("a")
    corpus_b, _ = _corpus("b")
    cases = (
        ManagedRunCase(corpus_a.case_id, corpus_a.corpus_id, {}),
        ManagedRunCase(corpus_b.case_id, corpus_b.corpus_id, {}),
    )

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus_a,), (presence_a,), cases=cases)

    assert caught.value.code == "managed_projection_coverage_invalid"


def test_rejects_unadmitted_extra_corpus() -> None:
    corpus_a, presence_a = _corpus("a")
    corpus_b, presence_b = _corpus("b")
    cases = (ManagedRunCase(corpus_a.case_id, corpus_a.corpus_id, {}),)

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus_a, corpus_b), (presence_a, presence_b), cases=cases)

    assert caught.value.code == "managed_projection_coverage_invalid"


def test_rejects_case_corpus_pair_mismatch() -> None:
    corpus, presence = _corpus("a")
    cases = (ManagedRunCase("case-other", corpus.corpus_id, {}),)

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), (presence,), cases=cases)

    assert caught.value.code == "managed_projection_coverage_invalid"


def test_rejects_duplicate_expected_case_coverage() -> None:
    corpus, presence = _corpus("a")
    case = ManagedRunCase(corpus.case_id, corpus.corpus_id, {})

    with pytest.raises(ManagedProjectionManifestError) as caught:
        _build((corpus,), (presence,), cases=(case, case))

    assert caught.value.code == "managed_projection_expected_coverage_invalid"


def test_shared_corpus_binds_to_first_admitted_case() -> None:
    corpus, presence = _corpus("a")
    cases = (
        ManagedRunCase(corpus.case_id, corpus.corpus_id, {}),
        ManagedRunCase("case-a-second", corpus.corpus_id, {}),
    )

    result = _build((corpus,), (presence,), cases=cases)

    assert len(result.projection_manifest["scopes"]) == 1


def test_registration_value_rejects_noncanonical_response() -> None:
    bindings = _bindings()

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        replace(_registration(bindings), authority="other")

    assert caught.value.code == "managed_benchmark_registry_registration_response_invalid"
