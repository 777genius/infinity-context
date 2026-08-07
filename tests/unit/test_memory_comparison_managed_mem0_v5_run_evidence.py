from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CleanCorpusScope,
    ManagedMem0V5CorpusEvidenceProjector,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    ManagedMem0V5StorageWitnessIssuerPort,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import Mem0OssRunSeal


def _sha(value: str) -> str:
    return canonical_sha256({"value": value})


def _scope() -> ManagedMem0V5CleanCorpusScope:
    return ManagedMem0V5CleanCorpusScope(
        corpus_identity_sha256=_sha("corpus"),
        scope_identity_sha256=_sha("scope"),
        source_scope_count=1,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
    )


def _authority() -> ManagedMem0V5ManifestAuthority:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": f"memory-{index:06d}",
                "speaker": "Alice",
                "session_date": f"2024-03-{10 + index:02d}",
                "text": f"Alice fact {index}.",
                "timestamp": index,
            }
            for index in (1, 2)
        ],
        "documents": [],
        "conversations": [],
    }
    return ManagedMem0V5ManifestProjector().project(
        (ManagedRunCase("case-1", corpus_id, record),), current_date="2026-08-07"
    )


def _seal(authority: ManagedMem0V5ManifestAuthority, admission: str) -> Mem0OssRunSeal:
    return Mem0OssRunSeal(
        admission_commitment_sha256=admission,
        operation_count=authority.operation_count,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        operation_root_sha256=_sha("operations"),
        provider_observed_extraction_calls=authority.operation_count,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
    )


def _storage_observations(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    issuer: ManagedMem0V5StorageWitnessIssuerPort,
) -> tuple[ManagedMem0V5AuthenticatedStorageWitness, ...]:
    return tuple(
        issuer.issue_authenticated_storage(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": admission,
                    "unit_index": index,
                    "unit_identity_sha256": source.unit_identity_sha256,
                }
            ),
            unit_identity_sha256=source.unit_identity_sha256,
            storage_commitment_sha256=_sha(f"storage-{index}"),
            created_record_ids=(f"record-{index}",),
            source_pairs=((source.source_id, source.source_sha256),),
        )
        for index, source in enumerate(authority.units)
    )


def test_clean_state_authority_rejects_public_forgery_and_mutation() -> None:
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority(hmac_key=b"k" * 32)
    issued = issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=_sha("admission"),
        run_id_sha256=_sha("run"),
        authority_commitment_sha256=_sha("authority"),
        scopes=(_scope(),),
    )
    assert verifier.authenticate_clean_state(issued) is issued

    forged = ManagedMem0V5AuthenticatedCleanStateWitness(
        issued.admission_commitment_sha256,
        issued.run_id_sha256,
        issued.authority_commitment_sha256,
        issued.scopes,
        issued.evidence_commitment_sha256,
    )
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        verifier.authenticate_clean_state(forged)

    object.__setattr__(issued, "authority_commitment_sha256", _sha("changed"))
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        verifier.authenticate_clean_state(issued)


def test_clean_state_authority_rejects_short_hmac_key() -> None:
    with pytest.raises(ManagedRunError, match="HMAC key is invalid"):
        create_managed_mem0_v5_clean_state_witness_authority(hmac_key=b"short")


def test_clean_scope_requires_independently_empty_residual() -> None:
    with pytest.raises(ManagedRunError, match="clean corpus scope is invalid"):
        replace(_scope(), residual_record_count=1, residual_root_sha256=_sha("residual"))


def test_corpus_evidence_binds_source_storage_seal_and_created_records() -> None:
    authority = _authority()
    admission = _sha("admission")
    issuer, verifier = create_managed_mem0_v5_storage_witness_authority()
    observations = _storage_observations(authority, admission, issuer)
    seal = _seal(authority, admission)
    evidence = ManagedMem0V5CorpusEvidenceProjector(
        authority=authority,
        admission_commitment_sha256=admission,
        storage_verifier=verifier,
    ).project(
        run_id="run-1",
        corpus_id=authority.units[0].corpus_id,
        seal=seal,
        expected_seal_commitment_sha256=seal.commitment_sha256,
        observations=observations,
    )

    assert tuple(item.created_record_ids for item in evidence.units) == (
        ("record-0",),
        ("record-1",),
    )
    evidence.__post_init__()


@pytest.mark.parametrize("mode", ("raw", "mutated", "foreign-authority"))
def test_corpus_evidence_reauthenticates_every_storage_witness(mode: str) -> None:
    authority = _authority()
    admission = _sha("admission")
    issuer, verifier = create_managed_mem0_v5_storage_witness_authority()
    observations = list(_storage_observations(authority, admission, issuer))
    if mode == "raw":
        observations[0] = replace(observations[0])
    elif mode == "mutated":
        object.__setattr__(observations[0], "created_record_ids", ("post-mutated",))
        object.__setattr__(
            observations[0],
            "evidence_commitment_sha256",
            canonical_sha256(observations[0].commitment_payload()),
        )
    else:
        _other_issuer, verifier = create_managed_mem0_v5_storage_witness_authority()
    seal = _seal(authority, admission)
    projector = ManagedMem0V5CorpusEvidenceProjector(
        authority=authority,
        admission_commitment_sha256=admission,
        storage_verifier=verifier,
    )

    with pytest.raises(ManagedRunError, match="unauthenticated"):
        projector.project(
            run_id="run-1",
            corpus_id=authority.units[0].corpus_id,
            seal=seal,
            expected_seal_commitment_sha256=seal.commitment_sha256,
            observations=tuple(observations),
        )


@pytest.mark.parametrize("mode", ("subset", "reordered", "seal-root"))
def test_corpus_evidence_rejects_coverage_order_count_or_root_divergence(mode: str) -> None:
    authority = _authority()
    admission = _sha("admission")
    issuer, verifier = create_managed_mem0_v5_storage_witness_authority()
    observations = _storage_observations(authority, admission, issuer)
    seal = _seal(authority, admission)
    expected_seal = seal.commitment_sha256
    if mode == "subset":
        observations = observations[:-1]
    elif mode == "reordered":
        observations = tuple(reversed(observations))
    else:
        seal = replace(seal, operation_root_sha256=_sha("divergent-root"))
    projector = ManagedMem0V5CorpusEvidenceProjector(
        authority=authority,
        admission_commitment_sha256=admission,
        storage_verifier=verifier,
    )

    with pytest.raises(ManagedRunError, match="gate differs|order differs"):
        projector.project(
            run_id="run-1",
            corpus_id=authority.units[0].corpus_id,
            seal=seal,
            expected_seal_commitment_sha256=expected_seal,
            observations=observations,
        )
