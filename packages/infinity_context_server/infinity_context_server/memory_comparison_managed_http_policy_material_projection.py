"""Pure commitment projection for managed HTTP policy evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import final

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedExactCleanupObservation,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedDerivedPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    ManagedHttpPolicyCleanupPassMaterial,
    ManagedHttpPolicyCorpusMaterial,
    ManagedHttpPolicyValidationMaterial,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyCleanupCommitments:
    cleanup_commitment_sha256: str
    corpus_absence_commitments: tuple[tuple[str, str], ...]
    exact_absence_commitment_sha256: str


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyExactCorpusBindings:
    manifest_sha256: tuple[str, ...]
    mem0_created_memory_ids: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]


def project_corpus_material(
    bundle: ManagedCorpusIngestIdentity,
    presence: ManagedDerivedPresenceObservation,
) -> ManagedHttpPolicyCorpusMaterial:
    manifest = bundle.manifest
    derived = tuple(
        (name, evidence_commitment(f"{name}-presence.v1", asdict(lane)))
        for name, lane in (("qdrant", presence.qdrant), ("graphiti", presence.graphiti))
        if lane is not None
    )
    return ManagedHttpPolicyCorpusMaterial(
        corpus_id=bundle.corpus_id,
        ingest_manifest_sha256=managed_ingest_identity_manifest_sha256(manifest, bundle.scope),
        source_pairs=tuple(zip(manifest.mem0_source_ids, manifest.mem0_source_sha256, strict=True)),
        presence_commitment_sha256=evidence_commitment("derived-presence.v1", asdict(presence)),
        derived_commitments=derived,
    )


def project_infinity_cleanup_commitments(
    observations: tuple[ManagedExactCleanupObservation, ...],
    *,
    target_identity_sha256: str,
    pass_index: int,
) -> ManagedHttpPolicyCleanupCommitments:
    corpus_absence = tuple(
        (
            item.corpus_id,
            evidence_commitment("infinity-corpus-absence.v1", asdict(item)),
        )
        for item in observations
    )
    return ManagedHttpPolicyCleanupCommitments(
        cleanup_commitment_sha256=evidence_commitment(
            "infinity-cleanup-pass.v1", [asdict(item) for item in observations]
        ),
        corpus_absence_commitments=corpus_absence,
        exact_absence_commitment_sha256=_absence_commitment(
            "infinity-context", target_identity_sha256, pass_index, corpus_absence
        ),
    )


def project_mem0_cleanup_commitments(
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
    *,
    run_id: str,
    target_identity_sha256: str,
    pass_index: int,
    acknowledgement: dict[str, object],
) -> ManagedHttpPolicyCleanupCommitments:
    corpus_absence = tuple(
        (
            bundle.corpus_id,
            evidence_commitment(
                "mem0-corpus-absence.v1",
                {
                    "manifest": managed_ingest_identity_manifest_sha256(
                        bundle.manifest, bundle.scope
                    ),
                    "created_memory_ids": bundle.manifest.mem0_created_memory_ids,
                    "source_pairs": tuple(
                        zip(
                            bundle.manifest.mem0_source_ids,
                            bundle.manifest.mem0_source_sha256,
                            strict=True,
                        )
                    ),
                    "pass_index": pass_index,
                    "target": target_identity_sha256,
                    "verified_absent": True,
                },
            ),
        )
        for bundle in corpora
    )
    return ManagedHttpPolicyCleanupCommitments(
        cleanup_commitment_sha256=evidence_commitment(
            "mem0-cleanup-pass.v1",
            {
                "run_id": run_id,
                "target": target_identity_sha256,
                "pass_index": pass_index,
                "corpus_absence": corpus_absence,
                "ack": acknowledgement,
            },
        ),
        corpus_absence_commitments=corpus_absence,
        exact_absence_commitment_sha256=_absence_commitment(
            "mem0", target_identity_sha256, pass_index, corpus_absence
        ),
    )


def project_cleanup_passes(
    rows: tuple[
        tuple[
            str,
            str,
            int,
            str,
            str,
            tuple[tuple[str, str], ...],
            bool,
        ],
        ...,
    ],
) -> tuple[ManagedHttpPolicyCleanupPassMaterial, ...]:
    first = {role: cleanup for role, _, index, cleanup, _, _, _ in rows if index == 1}
    return tuple(
        ManagedHttpPolicyCleanupPassMaterial(
            backend_role=role,
            target_identity_sha256=target,
            pass_index=index,
            cleanup_commitment_sha256=cleanup,
            exact_absence_commitment_sha256=absence,
            replay_of_cleanup_commitment_sha256=None if index == 1 else first[role],
            corpus_absence_commitments=corpora,
            verified_absent=verified,
        )
        for role, target, index, cleanup, absence, corpora, verified in rows
    )


def project_validation_material(
    *,
    bindings: FullComparisonRunBindings,
    managed_attestation_commitment_sha256: str,
    adapter_id: str,
    implementation_sha256: str,
    execution_case_manifest_sha256: str,
    cases: tuple[ManagedRunCase, ...],
    corpora: tuple[ManagedHttpPolicyCorpusMaterial, ...],
    cleanup_passes: tuple[ManagedHttpPolicyCleanupPassMaterial, ...],
) -> ManagedHttpPolicyValidationMaterial:
    targets = {item.backend_role: item.target_identity_sha256 for item in bindings.backend_targets}
    return ManagedHttpPolicyValidationMaterial(
        run_id=bindings.run_id,
        profile_id=bindings.profile_id,
        scope_id=bindings.scope,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        managed_attestation_commitment_sha256=managed_attestation_commitment_sha256,
        backend_targets=tuple((role, targets[role]) for role in ("infinity-context", "mem0")),
        adapter_id=adapter_id,
        implementation_sha256=implementation_sha256,
        execution_case_manifest_sha256=execution_case_manifest_sha256,
        case_corpus_mapping=tuple((case.case_id, case.corpus_id) for case in cases),
        corpora=corpora,
        cleanup_passes=cleanup_passes,
    )


def project_exact_corpus_bindings(
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
) -> ManagedHttpPolicyExactCorpusBindings:
    manifests = tuple(
        managed_ingest_identity_manifest_sha256(bundle.manifest, bundle.scope) for bundle in corpora
    )
    identities = tuple(
        identity for bundle in corpora for identity in bundle.manifest.mem0_created_memory_ids
    )
    pairs = tuple(
        pair
        for bundle in corpora
        for pair in zip(
            bundle.manifest.mem0_source_ids,
            bundle.manifest.mem0_source_sha256,
            strict=True,
        )
    )
    if not identities or len(set(identities)) != len(identities):
        raise ValueError("managed_http_policy_mem0_identity_binding_invalid")
    if not pairs:
        raise ValueError("managed_http_policy_mem0_source_binding_invalid")
    return ManagedHttpPolicyExactCorpusBindings(manifests, identities, pairs)


def validate_ingest_evidence(views: object) -> None:
    if (
        type(views) is not tuple
        or not views
        or any(type(view) is not ManagedHttpIngestEvidenceView for view in views)
    ):
        raise ValueError("managed_http_policy_ingest_evidence_invalid")
    for view in views:
        metadata = view.ingest_result.metadata
        managed = metadata.get("managed_http_execution") if isinstance(metadata, Mapping) else None
        if not isinstance(managed, Mapping):
            raise ValueError("managed_http_policy_ingest_provenance_missing")
        blockers = managed.get("composition_blockers")
        if managed.get("credential_continuity_proven") is not True or blockers not in ([], ()):
            raise ValueError("managed_http_policy_credential_continuity_unproven")


def lifecycle_implementation_sha256() -> str:
    return evidence_commitment(
        "managed-comparison-http-policy-fail-closed.v1",
        {
            "ingest": "exact-target-major-one-use",
            "canonical_source": "exact-http-evidence-bound",
            "delete": "two-pass-distinct-owned-transport",
            "aggregate": "immutable-one-shot-validation",
            "retries": 0,
        },
    )


def binding_snapshot(bindings: FullComparisonRunBindings) -> str:
    return evidence_commitment(
        "managed-http-policy-binding.v1",
        {
            "run_id": bindings.run_id,
            "profile_id": bindings.profile_id,
            "scope": bindings.scope,
            "binding": bindings.binding_commitment_sha256,
            "targets": [
                [target.backend_role, target.target_identity_sha256]
                for target in bindings.backend_targets
            ],
        },
    )


def evidence_commitment(schema: str, evidence: object) -> str:
    encoded = json.dumps(
        {"schema": schema, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _absence_commitment(
    role: str,
    target: str,
    pass_index: int,
    corpora: tuple[tuple[str, str], ...],
) -> str:
    return evidence_commitment(
        "exact-absence.v1",
        {"role": role, "target": target, "pass_index": pass_index, "corpora": corpora},
    )


__all__ = (
    "ManagedHttpPolicyCleanupCommitments",
    "ManagedHttpPolicyExactCorpusBindings",
    "binding_snapshot",
    "lifecycle_implementation_sha256",
    "project_cleanup_passes",
    "project_corpus_material",
    "project_exact_corpus_bindings",
    "project_infinity_cleanup_commitments",
    "project_mem0_cleanup_commitments",
    "project_validation_material",
    "validate_ingest_evidence",
)
