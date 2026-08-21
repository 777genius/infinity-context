"""Small exact managed benchmark cleanup-plan fixture shared by focused tests."""

import hashlib
import json

from infinity_context_core.ports.benchmark_cleanup_plan import (
    CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    CLEANUP_PLAN_SCHEMA_VERSION,
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    INFINITY_NAMESPACE_POLICY_SHA256,
)


def cleanup_plan_pair(
    *, run_id: str, binding: str, target: str, space_slug: str
) -> tuple[dict[str, object], str]:
    def digest(character: str) -> str:
        return character * 64

    plan: dict[str, object] = {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "run_id_sha256": run_id,
        "binding_commitment_sha256": binding,
        "infinity_target_identity_sha256": target,
        "space_id": f"benchmark-space-{run_id[:48]}",
        "space_slug": space_slug,
        "profile_id": "repository-test",
        "ordered_case_sha256": [digest("1")],
        "corpora": [
            {
                "ordinal": 0,
                "corpus_id_sha256": digest("2"),
                "managed_corpus_projection_sha256": digest("3"),
                "memory_scope_external_ref_sha256": digest("4"),
                "thread_external_ref_sha256": digest("5"),
                "infinity_lane": "fact",
                "ordered_infinity_operation_sha256": [digest("a")],
                "ordered_infinity_source_external_id_sha256": [digest("b")],
                "ordered_infinity_content_sha256": [digest("c")],
                "ordered_document_fragment_count": [],
                "expected_fact_count": 1,
                "expected_document_count": 0,
                "expected_chunk_count": 0,
                "mem0_corpus_identity_sha256": digest("6"),
                "ordered_mem0_source_id_sha256": [digest("5")],
                "ordered_mem0_unit_identity_sha256": [digest("7")],
                "expected_ingest_unit_count": 1,
            }
        ],
        "mem0": {
            "admission_commitment_sha256": digest("8"),
            "ingestion_manifest_sha256": digest("9"),
            "ingestion_root_sha256": digest("d"),
            "expected_operation_count": 1,
        },
        "infinity_namespace_policy_sha256": INFINITY_NAMESPACE_POLICY_SHA256,
        "qdrant": {
            "target_commitment_sha256": digest("e"),
            "collection_projection_policy_sha256": digest("1"),
            "deterministic_scope_mapping_policy_sha256": digest("2"),
            "space_wide_scan_policy_sha256": digest("3"),
        },
        "graphiti": {
            "target_commitment_sha256": digest("4"),
            "group_mapping_policy_sha256": digest("5"),
            "space_prefix_scan_policy_sha256": digest("6"),
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
        "cardinality": {
            "case_count": 1,
            "corpus_count": 1,
            "mem0_source_identity_count": 1,
            "expected_ingest_unit_count": 1,
            "infinity_operation_count": 1,
            "expected_fact_count": 1,
            "expected_document_count": 0,
            "expected_chunk_count": 0,
        },
        "limits_policy_sha256": CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    }
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return plan, hashlib.sha256(encoded).hexdigest()


__all__ = ("cleanup_plan_pair",)
