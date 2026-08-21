"""Provider-free artifact inputs for strict-v4 cleanup derivation E2E."""

from __future__ import annotations

from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    StrictV4FullPreparationInputs,
)

ARTIFACT_KEY = b"strict-v4-cleanup-derivation-artifact-key" * 2
PREPARATION_AUTH = ProjectionReceiptAuthenticator(
    b"strict-v4-cleanup-derivation-preparation-key" * 2
)


class ArtifactKeys:
    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        expected = {
            "a1": "a1-key",
            "a2": "a2-key",
            "expected-index": "index-key",
            "original-pair": "pair-key",
        }
        if expected.get(purpose) != key_id:
            raise ValueError("unexpected strict-v4 artifact key binding")
        return ARTIFACT_KEY


def preparation_inputs(tmp_path, projection, manifest, run_id: str):
    q_target, q_policy = "a" * 64, "b" * 64
    g_target, g_policy = "c" * 64, "d" * 64
    return StrictV4FullPreparationInputs(
        run_id_sha256=run_id,
        publishable_profile_commitment_sha256=projection.publishable_profile_commitment_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        case_manifest_sha256=projection.case_manifest_sha256,
        infinity_target_identity_sha256="a" * 64,
        space_id=f"benchmark-space-{'3' * 48}",
        space_slug="strict-v4-cleanup-derivation",
        cleanup_target_authority_sha256="6" * 64,
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256="7" * 64,
        namespace_policy_sha256="8" * 64,
        original_pair_path=None,
        original_pair_key_id=None,
        a1_path=str(tmp_path / "a1.sqlite3"),
        a1_key_id="a1-key",
        a2_path=str(tmp_path / "a2.sqlite3"),
        a2_key_id="a2-key",
        expected_index_path=str(tmp_path / "index.sqlite3"),
        expected_index_key_id="index-key",
    )


__all__ = ("ArtifactKeys", "PREPARATION_AUTH", "preparation_inputs")
