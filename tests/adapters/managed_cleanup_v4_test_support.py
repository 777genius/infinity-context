"""Provider-free cleanup-v4 context-authority material for adapter tests."""

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    CHUNKER_POLICY_SHA256,
    LIMITS_POLICY_SHA256,
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    PROJECTOR_POLICY_SHA256,
    ManagedCleanupV3Authority,
    build_context,
    commitment,
    merkle_root,
)

RUN = "b" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"


def _context():
    qdrant_target = "e" * 64
    qdrant_policy = "7" * 64
    graphiti_target = "4" * 64
    graphiti_policy = "8" * 64
    return build_context(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256="0" * 64,
        a1_terminal_commitment_sha256="1" * 64,
        run_id_sha256=RUN,
        binding_commitment_sha256="2" * 64,
        publishable_profile_commitment_sha256="3" * 64,
        methodology_commitment_sha256="4" * 64,
        dataset_sha256=str(PROFILE_ORACLES[LOCOMO_PROFILE]["dataset_sha256"]),
        admission_commitment_sha256="5" * 64,
        ingestion_root_sha256="6" * 64,
        case_manifest_sha256="7" * 64,
        infinity_target_identity_sha256="a" * 64,
        space_id=SPACE_ID,
        space_slug=SPACE_ID,
        cleanup_target_authority_sha256="9" * 64,
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": qdrant_target,
                "policy_commitment_sha256": qdrant_policy,
            },
        ),
        qdrant_target_commitment_sha256=qdrant_target,
        qdrant_policy_commitment_sha256=qdrant_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": graphiti_target,
                "policy_commitment_sha256": graphiti_policy,
            },
        ),
        graphiti_target_commitment_sha256=graphiti_target,
        graphiti_policy_commitment_sha256=graphiti_policy,
        cognee_policy_sha256="a" * 64,
        namespace_policy_sha256="b" * 64,
        cleanup_operation_stream_root_sha256="c" * 64,
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[LOCOMO_PROFILE]["omitted_source_identity_root_sha256"]
        ),
    )


def _authority() -> ManagedCleanupV3Authority:
    oracle = PROFILE_ORACLES[LOCOMO_PROFILE]
    pages = ("e" * 64,)
    body = {
        "schema_version": "memory-comparison-paged-cleanup-authority.v4",
        "profile_id": LOCOMO_PROFILE,
        "context_sha256": V3_CONTEXT.context_sha256,
        "a1_terminal_commitment_sha256": V3_CONTEXT.a1_terminal_commitment_sha256,
        "operation_count": oracle["operation_count"],
        "valid_message_count": oracle["valid_message_count"],
        "original_pair_slot_count": oracle["original_pair_slot_count"],
        "fully_invalid_pair_slot_count": oracle["fully_invalid_pair_slot_count"],
        "fragment_count": oracle["fragment_count"],
        "corpus_thread_identity_count": oracle["corpus_count"],
        "corpus_thread_identity_root_sha256": "1" * 64,
        "document_source_ref_count": oracle["document_source_ref_count"],
        "document_source_ref_root_sha256": "2" * 64,
        "page_count": len(pages),
        "ordered_page_sha256": list(pages),
        "pages_merkle_root_sha256": merkle_root(pages),
        "a1_operation_stream_root_sha256": "f" * 64,
        "cleanup_operation_stream_root_sha256": (V3_CONTEXT.cleanup_operation_stream_root_sha256),
        "omitted_source_identity_root_sha256": V3_CONTEXT.omitted_source_identity_root_sha256,
        "projector_policy_sha256": PROJECTOR_POLICY_SHA256,
        "chunker_policy_sha256": CHUNKER_POLICY_SHA256,
        "limits_policy_sha256": LIMITS_POLICY_SHA256,
    }
    return ManagedCleanupV3Authority(
        **{
            key: tuple(value) if key == "ordered_page_sha256" else value
            for key, value in body.items()
            if key != "schema_version"
        },
        terminal_commitment_sha256=commitment("authority/v4", body),
    )


V3_CONTEXT = _context()
V3_AUTHORITY = _authority()

__all__ = ("V3_AUTHORITY", "V3_CONTEXT")
