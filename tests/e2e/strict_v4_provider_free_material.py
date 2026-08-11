"""Small authenticated strict-v4 receipt material with no provider or fixture calls."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistration,
    ProjectionReceiptAuthenticator,
    context_authority_registration_sha256,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
    build_strict_v4_preparation_receipt,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    StrictV4WriterAuthority,
    build_strict_v4_writer_authority,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    CHUNKER_POLICY_SHA256,
    LIMITS_POLICY_SHA256,
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    PROJECTOR_POLICY_SHA256,
    ManagedCleanupV3Authority,
    ManagedCleanupV3StoreReceipt,
    build_context,
    commitment,
    merkle_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    MANAGED_MEM0_V6_PAGE_SIZE,
    TERMINAL_COMMITMENT_DOMAIN,
    ManagedMem0V6PagedManifestAuthority,
    ManagedMem0V6PageStoreCommitReceipt,
    authority_body,
    build_managed_mem0_v6_manifest_context,
    domain_sha256,
    store_receipt_sha256,
    uniqueness_receipt_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    merkle_root as manifest_merkle_root,
)


@dataclass(frozen=True, slots=True)
class ProviderFreeStrictV4Material:
    receipt: StrictV4PreparationReceipt
    authority: StrictV4WriterAuthority


def _sha(label: str) -> str:
    return hashlib.sha256(f"strict-v4-provider-free:{label}".encode()).hexdigest()


def build_provider_free_strict_v4_material(
    *,
    run_id_sha256: str,
    space_id: str,
    space_slug: str,
    authenticator: ProjectionReceiptAuthenticator,
    registered_at: datetime,
    prepared_at: datetime,
    sealed_at: datetime,
) -> ProviderFreeStrictV4Material:
    """Build fully self-authenticating A1/A2 evidence without projecting data."""

    binding = _sha("binding")
    publishable = _sha("publishable")
    methodology = _sha("methodology")
    dataset = str(PROFILE_ORACLES[LOCOMO_PROFILE]["dataset_sha256"])
    admission = _sha("admission")
    ingestion = _sha("ingestion")
    a1_context = build_managed_mem0_v6_manifest_context(
        profile_id=LOCOMO_PROFILE,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding,
        publishable_profile_commitment_sha256=publishable,
        methodology_commitment_sha256=methodology,
        dataset_sha256=dataset,
        admission_commitment_sha256=admission,
        ingestion_root_sha256=ingestion,
    )
    operation_count = int(PROFILE_ORACLES[LOCOMO_PROFILE]["operation_count"])
    page_count = (operation_count + MANAGED_MEM0_V6_PAGE_SIZE - 1) // (MANAGED_MEM0_V6_PAGE_SIZE)
    a1_pages = tuple(_sha(f"a1-page-{index}") for index in range(page_count))
    a1_root = manifest_merkle_root(a1_pages)
    uniqueness = uniqueness_receipt_sha256(
        a1_context.manifest_context_sha256,
        operation_count,
        a1_root,
    )
    a1_body = authority_body(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256=a1_context.manifest_context_sha256,
        operation_count=operation_count,
        ordered_page_commitment_sha256=a1_pages,
        pages_merkle_root_sha256=a1_root,
        uniqueness_receipt_sha256_value=uniqueness,
    )
    a1_authority = ManagedMem0V6PagedManifestAuthority(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256=a1_context.manifest_context_sha256,
        operation_count=operation_count,
        page_size=MANAGED_MEM0_V6_PAGE_SIZE,
        page_count=page_count,
        ordered_page_commitment_sha256=a1_pages,
        pages_merkle_root_sha256=a1_root,
        uniqueness_receipt_sha256=uniqueness,
        limits_policy_sha256=MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
        terminal_commitment_sha256=domain_sha256(
            TERMINAL_COMMITMENT_DOMAIN,
            a1_body,
        ),
        schema_version=MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    )
    a1_store = ManagedMem0V6PageStoreCommitReceipt(
        manifest_context_sha256=a1_context.manifest_context_sha256,
        authority_terminal_commitment_sha256=a1_authority.terminal_commitment_sha256,
        page_count=page_count,
        receipt_sha256=store_receipt_sha256(
            a1_context.manifest_context_sha256,
            a1_authority.terminal_commitment_sha256,
            page_count,
        ),
    )

    qdrant_target, qdrant_policy = _sha("q-target"), _sha("q-policy")
    graphiti_target, graphiti_policy = _sha("g-target"), _sha("g-policy")
    context = build_context(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256=a1_context.manifest_context_sha256,
        a1_terminal_commitment_sha256=a1_authority.terminal_commitment_sha256,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding,
        publishable_profile_commitment_sha256=publishable,
        methodology_commitment_sha256=methodology,
        dataset_sha256=dataset,
        admission_commitment_sha256=admission,
        ingestion_root_sha256=ingestion,
        case_manifest_sha256=_sha("case-manifest"),
        infinity_target_identity_sha256=_sha("target"),
        space_id=space_id,
        space_slug=space_slug,
        cleanup_target_authority_sha256=_sha("cleanup-target"),
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
        cognee_policy_sha256=_sha("cognee-policy"),
        namespace_policy_sha256=_sha("namespace-policy"),
        cleanup_operation_stream_root_sha256=_sha("cleanup-stream"),
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[LOCOMO_PROFILE]["omitted_source_identity_root_sha256"]
        ),
    )
    oracle = PROFILE_ORACLES[LOCOMO_PROFILE]
    a2_pages = (_sha("a2-page"),)
    a2_body = {
        "schema_version": "memory-comparison-paged-cleanup-authority.v4",
        "profile_id": LOCOMO_PROFILE,
        "context_sha256": context.context_sha256,
        "a1_terminal_commitment_sha256": a1_authority.terminal_commitment_sha256,
        "operation_count": oracle["operation_count"],
        "valid_message_count": oracle["valid_message_count"],
        "original_pair_slot_count": oracle["original_pair_slot_count"],
        "fully_invalid_pair_slot_count": oracle["fully_invalid_pair_slot_count"],
        "fragment_count": oracle["fragment_count"],
        "corpus_thread_identity_count": oracle["corpus_count"],
        "corpus_thread_identity_root_sha256": _sha("corpus-root"),
        "document_source_ref_count": oracle["document_source_ref_count"],
        "document_source_ref_root_sha256": _sha("document-root"),
        "page_count": 1,
        "ordered_page_sha256": list(a2_pages),
        "pages_merkle_root_sha256": merkle_root(a2_pages),
        "a1_operation_stream_root_sha256": _sha("a1-stream"),
        "cleanup_operation_stream_root_sha256": context.cleanup_operation_stream_root_sha256,
        "omitted_source_identity_root_sha256": context.omitted_source_identity_root_sha256,
        "projector_policy_sha256": PROJECTOR_POLICY_SHA256,
        "chunker_policy_sha256": CHUNKER_POLICY_SHA256,
        "limits_policy_sha256": LIMITS_POLICY_SHA256,
    }
    a2_authority = ManagedCleanupV3Authority(
        **{
            key: tuple(value) if key == "ordered_page_sha256" else value
            for key, value in a2_body.items()
            if key != "schema_version"
        },
        terminal_commitment_sha256=commitment("authority/v4", a2_body),
    )
    a2_store_body = {
        "schema_version": "memory-comparison-paged-cleanup-store-receipt.v4",
        "context_sha256": context.context_sha256,
        "terminal_commitment_sha256": a2_authority.terminal_commitment_sha256,
        "page_count": 1,
        "committed": True,
    }
    a2_store = ManagedCleanupV3StoreReceipt(
        context_sha256=context.context_sha256,
        terminal_commitment_sha256=a2_authority.terminal_commitment_sha256,
        page_count=1,
        committed=True,
        receipt_sha256=commitment("store-receipt/v4", a2_store_body),
    )
    registration_sha = context_authority_registration_sha256(context, a2_authority)
    registration = ContextAuthorityRegistration(
        context=context,
        authority=a2_authority,
        registration_sha256=registration_sha,
        registration_mac_sha256=authenticator.sign(
            "projection-context-authority",
            registration_sha,
        ),
        registered_at=registered_at,
        created=True,
    )
    receipt = build_strict_v4_preparation_receipt(
        authenticator=authenticator,
        registration=registration,
        prepared_at=prepared_at,
        profile_id=LOCOMO_PROFILE,
        dataset_sha256=dataset,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding,
        methodology_commitment_sha256=methodology,
        admission_commitment_sha256=admission,
        ingestion_root_sha256=ingestion,
        original_pair_path=None,
        original_pair_terminal_sha256=None,
        original_pair_key_id=None,
        original_pair_key_commitment_sha256=None,
        a1_path="provider-free-a1.sqlite3",
        a1_key_id="provider-free-a1",
        a1_key_commitment_sha256=_sha("a1-key"),
        a1_context=a1_context,
        a1_authority=a1_authority,
        a1_store_receipt=a1_store,
        a2_path="provider-free-a2.sqlite3",
        a2_key_id="provider-free-a2",
        a2_key_commitment_sha256=_sha("a2-key"),
        a2_context=context,
        a2_authority=a2_authority,
        a2_store_receipt=a2_store,
        expected_index_path="provider-free-index.sqlite3",
        expected_index_key_id="provider-free-index",
        expected_index_key_commitment_sha256=_sha("index-key"),
        expected_index_terminal_sha256=a2_authority.terminal_commitment_sha256,
        receipt_key_commitment_sha256=_sha("receipt-key"),
    )
    return ProviderFreeStrictV4Material(
        receipt=receipt,
        authority=build_strict_v4_writer_authority(
            receipt=receipt,
            authenticator=authenticator,
            sealed_at=sealed_at,
        ),
    )


__all__ = (
    "ProviderFreeStrictV4Material",
    "build_provider_free_strict_v4_material",
)
