from __future__ import annotations

import hashlib
from dataclasses import replace
from functools import lru_cache

import pytest
from infinity_context_core.ports.managed_cleanup_v3_absence import (
    EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256,
    EMPTY_GLOBAL_READBACK_ROOT_SHA256,
    ManagedCleanupV3AbsencePass,
    ManagedCleanupV3DeletionReceipt,
    ManagedCleanupV3TerminalEvidence,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    CHUNKER_POLICY_SHA256,
    LIMITS_POLICY_SHA256,
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    PAGE_CANONICAL_BYTES_CAP,
    PROFILE_ORACLES,
    PROJECTOR_POLICY_SHA256,
    ManagedCleanupV3Error,
    ManagedCleanupV3Operation,
    ManagedCleanupV3StoreReceipt,
    build_context,
    canonical_bytes,
    commitment,
    corpus_identity_sha256,
    fragment_commitments,
    memory_scope_external_ref_sha256,
    source_ref_commitments,
    thread_external_ref_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_inventory_verifier import (
    ManagedCleanupV3InventoryStreamVerifier,
)
from infinity_context_core.ports.managed_cleanup_v3_paged_authority import (
    build_managed_cleanup_v3_authority,
    cleanup_operation_stream_root,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    ManagedCleanupV3InventoryCursor,
    ManagedCleanupV3InventoryKindReceipt,
    ManagedCleanupV3InventoryPage,
    ManagedCleanupV3InventoryTerminal,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    TERMINAL_COMMITMENT_DOMAIN,
    ManagedMem0V6PagedManifestAuthority,
    uniqueness_receipt_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    authority_body as a1_authority_body,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    domain_sha256 as a1_domain_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    merkle_root as a1_merkle_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    page_body as a1_page_body,
)


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _context(profile_id: str):
    dataset = str(PROFILE_ORACLES[profile_id]["dataset_sha256"])
    q_target = _sha("qdrant-target")
    q_policy = _sha("qdrant-policy")
    g_target = _sha("graphiti-target")
    g_policy = _sha("graphiti-policy")
    manifest_context = _sha("a1-context")
    a1 = _a1_material(profile_id, manifest_context)
    return build_context(
        profile_id=profile_id,
        manifest_context_sha256=manifest_context,
        a1_terminal_commitment_sha256=a1.terminal_commitment_sha256,
        run_id_sha256=_sha("run"),
        binding_commitment_sha256=_sha("binding"),
        publishable_profile_commitment_sha256=_sha("profile"),
        methodology_commitment_sha256=_sha("method"),
        dataset_sha256=dataset,
        admission_commitment_sha256=_sha("admission"),
        ingestion_root_sha256=_sha("ingestion"),
        case_manifest_sha256=_sha("cases"),
        infinity_target_identity_sha256=_sha("target"),
        space_id="benchmark-space-" + "a" * 48,
        space_slug="benchmark-space-" + "a" * 48,
        cleanup_target_authority_sha256=_sha("cleanup-target"),
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
        cognee_policy_sha256=_sha("cognee"),
        namespace_policy_sha256=_sha("namespace"),
        cleanup_operation_stream_root_sha256=_cleanup_root(profile_id),
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[profile_id]["omitted_source_identity_root_sha256"]
        ),
    )


def _operation(profile_id: str, sequence: int) -> ManagedCleanupV3Operation:
    operation_count = int(PROFILE_ORACLES[profile_id]["operation_count"])
    corpus_count = int(PROFILE_ORACLES[profile_id]["corpus_count"])
    corpus_index = sequence * corpus_count // operation_count
    if profile_id == LOCOMO_PROFILE:
        lane, messages, fragment_material, pair = "fact", 1, (), None
        source_refs = (
            {
                "source_type": "locomo",
                "source_id_sha256": _sha(("fact-source-ref", sequence)),
            },
        )
    else:
        lane = "document"
        messages = 2 if sequence < 122_394 else 1
        count = 3 if sequence < 117_752 else 2
        fragment_material = tuple(
            {
                "sequence": index,
                "text_sha256": _sha(("fragment", sequence, index)),
                "char_start": index * 10,
                "char_end": index * 10 + 10,
                "kind": "conversation",
                "node_kind": "paragraph",
            }
            for index in range(count)
        )
        pair = _sha(("original-pair", sequence))
        source_refs = tuple(
            {
                "source_type": "longmemeval",
                "source_id_sha256": _sha(("source-ref", sequence, index)),
                "ordinal": index,
            }
            for index in range(messages + 2)
        )
    source_refs_sha, source_ref_descriptors, source_ref_root = source_ref_commitments(source_refs)
    fragments_sha, fragments, fragment_root = fragment_commitments(fragment_material)
    scope_sha = memory_scope_external_ref_sha256(f"benchmark-corpus:{corpus_index}")
    thread_sha = thread_external_ref_sha256(f"benchmark-thread:{corpus_index}")
    body = {
        "schema_version": "memory-comparison-paged-cleanup-operation.v4",
        "sequence": sequence,
        "lane": lane,
        "corpus_identity_sha256": corpus_identity_sha256(
            lane=lane,
            memory_scope_external_ref_sha256=scope_sha,
            thread_external_ref_sha256=thread_sha,
        ),
        "memory_scope_external_ref_sha256": scope_sha,
        "thread_external_ref_sha256": thread_sha,
        "source_identity_sha256": _sha(("source", sequence)),
        "source_content_sha256": _sha(("content", sequence)),
        "operation_commitment_sha256": _sha(("infinity-operation", sequence)),
        "a1_operation_sha256": _sha(("a1-operation", sequence)),
        "original_pair_identity_sha256": pair,
        "valid_message_count": messages,
        "source_refs_sha256": source_refs_sha,
        "ordered_source_ref_descriptor_sha256": list(source_ref_descriptors),
        "source_ref_root_sha256": source_ref_root,
        "fragments_sha256": fragments_sha,
        "ordered_fragment_descriptor_sha256": list(fragments),
        "fragment_root_sha256": fragment_root,
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
    )


def _wrong_source_operation(profile_id: str, sequence: int) -> ManagedCleanupV3Operation:
    operation = _operation(profile_id, sequence)
    if sequence != 0:
        return operation
    body = operation.payload(False)
    body["source_content_sha256"] = _sha("wrong-source")
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
    )


def _a1_authority(context, count: int) -> ManagedMem0V6PagedManifestAuthority:
    assert count == int(PROFILE_ORACLES[context.profile_id]["operation_count"])
    return _a1_material(context.profile_id, context.manifest_context_sha256)


@lru_cache(maxsize=2)
def _a1_material(
    profile_id: str, manifest_context_sha256: str
) -> ManagedMem0V6PagedManifestAuthority:
    count = int(PROFILE_ORACLES[profile_id]["operation_count"])
    pages = []
    for page_index, start in enumerate(range(0, count, MANAGED_MEM0_V6_PAGE_SIZE)):
        operations = tuple(
            _sha(("a1-operation", sequence))
            for sequence in range(start, min(start + MANAGED_MEM0_V6_PAGE_SIZE, count))
        )
        body = a1_page_body(
            profile_id=profile_id,
            manifest_context_sha256=manifest_context_sha256,
            page_index=page_index,
            start_sequence=start,
            ordered_operation_sha256=operations,
        )
        pages.append(a1_domain_sha256(PAGE_COMMITMENT_DOMAIN, body))
    ordered = tuple(pages)
    root = a1_merkle_root(ordered)
    unique = uniqueness_receipt_sha256(manifest_context_sha256, count, root)
    body = a1_authority_body(
        profile_id=profile_id,
        manifest_context_sha256=manifest_context_sha256,
        operation_count=count,
        ordered_page_commitment_sha256=ordered,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256_value=unique,
    )
    return ManagedMem0V6PagedManifestAuthority(
        profile_id=profile_id,
        manifest_context_sha256=manifest_context_sha256,
        operation_count=count,
        page_size=MANAGED_MEM0_V6_PAGE_SIZE,
        page_count=len(ordered),
        ordered_page_commitment_sha256=ordered,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256=unique,
        limits_policy_sha256=MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
        terminal_commitment_sha256=a1_domain_sha256(TERMINAL_COMMITMENT_DOMAIN, body),
        schema_version=MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    )


@lru_cache(maxsize=2)
def _cleanup_root(profile_id: str) -> str:
    count = int(PROFILE_ORACLES[profile_id]["operation_count"])
    return cleanup_operation_stream_root(
        profile_id=profile_id,
        operation_sha256=(_operation(profile_id, index).operation_sha256 for index in range(count)),
    )


class _Stage:
    def __init__(self, context_sha256: str, expected: int, *, lose_commit_response: bool) -> None:
        self.context = context_sha256
        self.expected = expected
        self.claimed: set[str] = set()
        self.page_sha: list[str] = []
        self.max_page_bytes = 0
        self.published: tuple[str, ...] = ()
        self.receipt = None
        self.aborted = False
        self.lose_commit_response = lose_commit_response

    def claim(self, *, sequence: int, operation_sha256: str) -> None:
        assert sequence == len(self.claimed)
        if operation_sha256 in self.claimed:
            raise ManagedCleanupV3Error("duplicate")
        self.claimed.add(operation_sha256)

    def append(self, page) -> None:
        if page.page_index < len(self.page_sha):
            if self.page_sha[page.page_index] != page.page_sha256:
                raise ManagedCleanupV3Error("divergent page")
            return
        assert page.page_index == len(self.page_sha)
        self.max_page_bytes = max(self.max_page_bytes, len(canonical_bytes(page.payload())))
        self.page_sha.append(page.page_sha256)

    def commit(self, authority):
        assert len(self.claimed) == self.expected
        self.published = tuple(self.page_sha)
        body = {
            "schema_version": "memory-comparison-paged-cleanup-store-receipt.v4",
            "context_sha256": self.context,
            "terminal_commitment_sha256": authority.terminal_commitment_sha256,
            "page_count": authority.page_count,
            "committed": True,
        }
        self.receipt = ManagedCleanupV3StoreReceipt(
            context_sha256=self.context,
            terminal_commitment_sha256=authority.terminal_commitment_sha256,
            page_count=authority.page_count,
            committed=True,
            receipt_sha256=commitment("store-receipt/v4", body),
        )
        if self.lose_commit_response:
            self.lose_commit_response = False
            raise RuntimeError("lost commit response")
        return self.receipt

    def readback(self):
        return self.receipt

    def abort(self) -> None:
        if self.receipt is None:
            self.page_sha.clear()
            self.claimed.clear()
            self.aborted = True


class _Store:
    def __init__(self, *, lose_commit_response: bool = False) -> None:
        self.stage = None
        self.lose_commit_response = lose_commit_response

    def begin(self, *, context_sha256: str, expected_operation_count: int):
        self.stage = _Stage(
            context_sha256,
            expected_operation_count,
            lose_commit_response=self.lose_commit_response,
        )
        return self.stage


@pytest.mark.parametrize(
    ("profile_id", "count", "expected_pages"),
    ((LOCOMO_PROFILE, 5_882, 23), (LONGMEMEVAL_PROFILE, 124_344, 486)),
)
def test_full_profile_streams_are_exact_and_bounded(
    profile_id: str, count: int, expected_pages: int
) -> None:
    context = _context(profile_id)
    store = _Store()
    authority, receipt = build_managed_cleanup_v3_authority(
        context=context,
        operations=(_operation(profile_id, index) for index in range(count)),
        a1_authority=_a1_authority(context, count),
        store=store,
    )

    assert authority.operation_count == count
    assert authority.page_count >= expected_pages
    assert authority.fragment_count == int(PROFILE_ORACLES[profile_id]["fragment_count"])
    assert authority.corpus_thread_identity_count == int(
        PROFILE_ORACLES[profile_id]["corpus_count"]
    )
    assert authority.document_source_ref_count == int(
        PROFILE_ORACLES[profile_id]["document_source_ref_count"]
    )
    assert authority.valid_message_count == int(PROFILE_ORACLES[profile_id]["valid_message_count"])
    assert receipt.committed is True
    assert store.stage.published == authority.ordered_page_sha256
    assert store.stage.max_page_bytes <= PAGE_CANONICAL_BYTES_CAP
    with pytest.raises(ManagedCleanupV3Error, match="authority_invalid"):
        replace(
            authority,
            schema_version="memory-comparison-paged-cleanup-authority.v3",
        )


def test_thread_and_exact_document_source_ref_material_are_terminal_bound() -> None:
    operation = _operation(LONGMEMEVAL_PROFILE, 0)
    assert len(operation.ordered_source_ref_descriptor_sha256) == 4
    assert operation.source_ref_root_sha256 == commitment(
        "source-ref-root/v4", list(operation.ordered_source_ref_descriptor_sha256)
    )
    with pytest.raises(ManagedCleanupV3Error, match="operation_invalid"):
        replace(operation, ordered_source_ref_descriptor_sha256=(_sha("missing"),))
    with pytest.raises(ManagedCleanupV3Error, match="operation_invalid"):
        replace(operation, thread_external_ref_sha256=_sha("other-thread"))


def test_hash_only_source_ref_commitments_preserve_exact_order() -> None:
    first = {"source_type": "pair", "source_id_sha256": _sha("pair")}
    second = {"source_type": "session", "source_id_sha256": _sha("session")}
    forward = source_ref_commitments((first, second))
    reverse = source_ref_commitments((second, first))

    assert forward != reverse
    assert len(forward[1]) == 2
    assert "canonical_json" not in _operation(LONGMEMEVAL_PROFILE, 0).payload()


def test_operation_rejects_boolean_valid_message_count() -> None:
    operation = _operation(LOCOMO_PROFILE, 0)
    body = operation.payload(False)
    body["valid_message_count"] = True

    with pytest.raises(ManagedCleanupV3Error, match="count_invalid"):
        ManagedCleanupV3Operation(
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
        )


def test_corpus_identity_rejects_divergent_thread() -> None:
    context = _context(LOCOMO_PROFILE)

    def operations():
        for index in range(5_882):
            operation = _operation(LOCOMO_PROFILE, index)
            if index == 1:
                body = operation.payload(False)
                body["thread_external_ref_sha256"] = _sha("divergent-thread")
                yield ManagedCleanupV3Operation(
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
                )
            else:
                yield operation

    store = _Store()
    with pytest.raises(ManagedCleanupV3Error, match="operation_invalid"):
        build_managed_cleanup_v3_authority(
            context=context,
            operations=operations(),
            a1_authority=_a1_authority(context, 5_882),
            store=store,
        )
    assert store.stage.published == ()


def test_late_count_reorder_duplicate_and_a1_tamper_abort_unpublished() -> None:
    context = _context(LOCOMO_PROFILE)
    variants = (
        (_operation(LOCOMO_PROFILE, index) for index in range(5_881)),
        iter([_operation(LOCOMO_PROFILE, 1)]),
        (
            replace(_operation(LOCOMO_PROFILE, index), operation_sha256=_sha("same"))
            for index in range(5_882)
        ),
    )
    for operations in variants:
        store = _Store()
        with pytest.raises(ManagedCleanupV3Error):
            build_managed_cleanup_v3_authority(
                context=context,
                operations=operations,
                a1_authority=_a1_authority(context, 5_882),
                store=store,
            )
        assert store.stage.aborted is True
        assert store.stage.published == ()
    store = _Store()
    with pytest.raises(ManagedCleanupV3Error, match="a1_authority_invalid"):
        build_managed_cleanup_v3_authority(
            context=context,
            operations=(_operation(LOCOMO_PROFILE, i) for i in range(5_882)),
            a1_authority=_a1_material(LOCOMO_PROFILE, _sha("other-a1-context")),
            store=store,
        )
    assert store.stage is None
    store = _Store()
    with pytest.raises(ManagedCleanupV3Error, match="operation_stream_mismatch"):
        build_managed_cleanup_v3_authority(
            context=context,
            operations=(_wrong_source_operation(LOCOMO_PROFILE, i) for i in range(5_882)),
            a1_authority=_a1_authority(context, 5_882),
            store=store,
        )
    assert store.stage.published == ()


def test_ambiguous_commit_is_reconciled_by_exact_readback() -> None:
    context = _context(LOCOMO_PROFILE)
    store = _Store(lose_commit_response=True)
    authority, receipt = build_managed_cleanup_v3_authority(
        context=context,
        operations=(_operation(LOCOMO_PROFILE, index) for index in range(5_882)),
        a1_authority=_a1_authority(context, 5_882),
        store=store,
    )

    assert receipt.terminal_commitment_sha256 == authority.terminal_commitment_sha256
    assert store.stage.aborted is False


def test_oracles_pin_messages_operations_chunks_dataset_and_policies() -> None:
    oracle = PROFILE_ORACLES[LONGMEMEVAL_PROFILE]
    assert oracle["operation_count"] == 124_344
    assert oracle["valid_message_count"] == 246_738
    assert oracle["original_pair_slot_count"] == 124_345
    assert oracle["fully_invalid_pair_slot_count"] == 1
    assert oracle["fragment_count"] == 366_440
    assert oracle["dataset_sha256"] == (
        "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
    )
    assert len({PROJECTOR_POLICY_SHA256, CHUNKER_POLICY_SHA256, LIMITS_POLICY_SHA256}) == 3


def _inventory(context):
    counts = (10, 10, 5_882, 5_882, 0, 0, 0, 5_882, 5_882, 0, 0, 5_882, 5_882, 5_882, 0)
    receipts = tuple(
        ManagedCleanupV3InventoryKindReceipt(kind, count, 1, _sha((kind, "rows")))
        for kind, count in zip(INVENTORY_KINDS, counts, strict=True)
    )
    values = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-terminal.v4",
        "profile_id": context.profile_id,
        "context_sha256": context.context_sha256,
        "authority_terminal_sha256": _sha("authority"),
        "cleanup_receipt_sha256": _sha("cleanup"),
        "snapshot_sha256": _sha("snapshot"),
        "repeatable_read": True,
        "first_page_minimum_proven": True,
        "kind_receipts": [
            {name: getattr(item, name) for name in item.__dataclass_fields__} for item in receipts
        ],
        "expected_qdrant_identity_root_sha256": _sha("qdrant-root"),
        "expected_qdrant_identity_count": 0,
        "expected_graphiti_name_root_sha256": _sha("graphiti-name-root"),
        "expected_graphiti_uuid_root_sha256": _sha("graphiti-uuid-root"),
        "expected_graphiti_identity_count": 5_882,
    }
    return ManagedCleanupV3InventoryTerminal(
        **{
            key: value
            for key, value in values.items()
            if key not in {"schema_version", "kind_receipts"}
        },
        kind_receipts=receipts,
        terminal_sha256=commitment("inventory-terminal/v4", values),
    )


def _absence(
    lane: str, index: int, context, inventory, prior: str | None = None, *, drift: bool = False
):
    if lane == "qdrant":
        primary = secondary = inventory.expected_qdrant_identity_root_sha256
        count = inventory.expected_qdrant_identity_count
        lane_authority = context.qdrant_authority_sha256
        target = context.qdrant_target_commitment_sha256
        policy = context.qdrant_policy_commitment_sha256
    else:
        primary = inventory.expected_graphiti_name_root_sha256
        secondary = inventory.expected_graphiti_uuid_root_sha256
        count = inventory.expected_graphiti_identity_count
        lane_authority = context.graphiti_authority_sha256
        target = context.graphiti_target_commitment_sha256
        policy = context.graphiti_policy_commitment_sha256
    body = {
        "schema_version": "memory-comparison-paged-cleanup-absence-pass.v4",
        "lane": lane,
        "pass_index": index,
        "authority_terminal_sha256": _sha("authority"),
        "inventory_terminal_sha256": inventory.terminal_sha256,
        "cleanup_receipt_sha256": inventory.cleanup_receipt_sha256,
        "lane_authority_sha256": lane_authority,
        "target_commitment_sha256": _sha((lane, "drift")) if drift else target,
        "policy_commitment_sha256": policy,
        "fresh_snapshot_nonce_sha256": _sha((lane, index, "nonce")),
        "prior_pass_sha256": prior,
        "expected_identity_root_sha256": primary,
        "expected_secondary_identity_root_sha256": secondary,
        "expected_identity_count": count,
        "exhaustive_space_or_prefix_count": 0,
        "exhaustive_space_or_prefix_root_sha256": EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256,
        "global_expected_readback_count": 0,
        "global_expected_readback_root_sha256": EMPTY_GLOBAL_READBACK_ROOT_SHA256,
        "unknown_foreign_malformed_count": 0,
    }
    return ManagedCleanupV3AbsencePass(
        **{key: value for key, value in body.items() if key != "schema_version"},
        pass_sha256=commitment("absence-pass/v4", body),
    )


def _deletion(lane: str, inventory):
    if lane == "qdrant":
        primary = secondary = inventory.expected_qdrant_identity_root_sha256
        count = inventory.expected_qdrant_identity_count
    else:
        primary = inventory.expected_graphiti_name_root_sha256
        secondary = inventory.expected_graphiti_uuid_root_sha256
        count = inventory.expected_graphiti_identity_count
    body = {
        "schema_version": "memory-comparison-paged-cleanup-deletion-receipt.v4",
        "lane": lane,
        "authority_terminal_sha256": _sha("authority"),
        "inventory_terminal_sha256": inventory.terminal_sha256,
        "cleanup_receipt_sha256": inventory.cleanup_receipt_sha256,
        "expected_identity_root_sha256": primary,
        "expected_secondary_identity_root_sha256": secondary,
        "expected_identity_count": count,
        "deletion_operation_receipt_sha256": _sha((lane, "deletion-operation")),
    }
    return ManagedCleanupV3DeletionReceipt(
        **{key: value for key, value in body.items() if key != "schema_version"},
        receipt_sha256=commitment("deletion-receipt/v4", body),
    )


def test_inventory_cursor_and_two_fresh_pass_chain_are_exact() -> None:
    context = _context(LOCOMO_PROFILE)
    inventory = _inventory(context)
    cursor_body = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-cursor.v4",
        "snapshot_sha256": _sha("snapshot"),
        "kind": "chunks",
        "last_canonical_key_sha256": _sha("last"),
        "page_index": 1,
    }
    cursor = ManagedCleanupV3InventoryCursor(
        **{key: value for key, value in cursor_body.items() if key != "schema_version"},
        cursor_sha256=commitment("inventory-cursor/v4", cursor_body),
    )
    page_body = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-page.v4",
        "authority_terminal_sha256": _sha("authority"),
        "snapshot_sha256": _sha("snapshot"),
        "kind": "chunks",
        "page_index": 0,
        "input_cursor_sha256": None,
        "output_cursor_sha256": cursor.cursor_sha256,
        "ordered_canonical_key_sha256": [_sha("last")],
        "ordered_row_sha256": [_sha("row")],
        "ordered_primary_target_identity_sha256": [],
        "ordered_secondary_target_identity_sha256": [],
        "exhausted": False,
    }
    ManagedCleanupV3InventoryPage(
        authority_terminal_sha256=_sha("authority"),
        snapshot_sha256=_sha("snapshot"),
        kind="chunks",
        page_index=0,
        input_cursor_sha256=None,
        output_cursor=cursor,
        ordered_canonical_key_sha256=(_sha("last"),),
        ordered_row_sha256=(_sha("row"),),
        ordered_primary_target_identity_sha256=(),
        ordered_secondary_target_identity_sha256=(),
        exhausted=False,
        page_sha256=commitment("inventory-page/v4", page_body),
    )
    q1 = _absence("qdrant", 1, context, inventory)
    q2 = _absence("qdrant", 2, context, inventory, q1.pass_sha256)
    g1 = _absence("graphiti", 1, context, inventory)
    g2 = _absence("graphiti", 2, context, inventory, g1.pass_sha256)
    q_delete = _deletion("qdrant", inventory)
    g_delete = _deletion("graphiti", inventory)
    body = {
        "schema_version": "memory-comparison-paged-cleanup-terminal-evidence.v4",
        "authority_terminal_sha256": _sha("authority"),
        "context_sha256": context.context_sha256,
        "inventory_terminal_sha256": inventory.terminal_sha256,
        "cleanup_receipt_sha256": inventory.cleanup_receipt_sha256,
        "qdrant_deletion_receipt_sha256": q_delete.receipt_sha256,
        "graphiti_deletion_receipt_sha256": g_delete.receipt_sha256,
        "qdrant_pass_sha256": [q1.pass_sha256, q2.pass_sha256],
        "graphiti_pass_sha256": [g1.pass_sha256, g2.pass_sha256],
        "cognee_policy_sha256": context.cognee_policy_sha256,
    }
    ManagedCleanupV3TerminalEvidence(
        context=context,
        authority_terminal_sha256=_sha("authority"),
        inventory=inventory,
        qdrant_deletion=q_delete,
        graphiti_deletion=g_delete,
        qdrant_passes=(q1, q2),
        graphiti_passes=(g1, g2),
        terminal_sha256=commitment("terminal-evidence/v4", body),
    )
    with pytest.raises(ManagedCleanupV3Error):
        replace(q2, fresh_snapshot_nonce_sha256=q1.fresh_snapshot_nonce_sha256)
    divergent = _absence("qdrant", 2, context, inventory, q1.pass_sha256, drift=True)
    with pytest.raises(ManagedCleanupV3Error):
        ManagedCleanupV3TerminalEvidence(
            context=context,
            authority_terminal_sha256=_sha("authority"),
            inventory=inventory,
            qdrant_deletion=q_delete,
            graphiti_deletion=g_delete,
            qdrant_passes=(q1, divergent),
            graphiti_passes=(g1, g2),
            terminal_sha256=_sha("irrelevant"),
        )


def _inventory_pages(kind: str, count: int):
    pages = []
    row_page_sha = []
    primary_page_sha = []
    secondary_page_sha = []
    cursor = None
    for page_index, start in enumerate(range(0, max(1, count), 512)):
        stop = min(start + 512, count)
        keys = tuple(f"{index + 1:064x}" for index in range(start, stop))
        rows = (
            keys
            if kind
            in {
                "qdrant_target_identities",
                "graphiti_target_names",
                "graphiti_target_uuids",
            }
            else tuple(_sha((kind, "row", index)) for index in range(start, stop))
        )
        primary = ()
        secondary = ()
        exhausted = stop == count
        output = None
        if not exhausted:
            cursor_body = {
                "schema_version": "memory-comparison-paged-cleanup-inventory-cursor.v4",
                "snapshot_sha256": _sha("snapshot"),
                "kind": kind,
                "last_canonical_key_sha256": keys[-1],
                "page_index": page_index + 1,
            }
            output = ManagedCleanupV3InventoryCursor(
                **{k: v for k, v in cursor_body.items() if k != "schema_version"},
                cursor_sha256=commitment("inventory-cursor/v4", cursor_body),
            )
        body = {
            "schema_version": "memory-comparison-paged-cleanup-inventory-page.v4",
            "authority_terminal_sha256": _sha("authority"),
            "snapshot_sha256": _sha("snapshot"),
            "kind": kind,
            "page_index": page_index,
            "input_cursor_sha256": None if cursor is None else cursor.cursor_sha256,
            "output_cursor_sha256": None if output is None else output.cursor_sha256,
            "ordered_canonical_key_sha256": list(keys),
            "ordered_row_sha256": list(rows),
            "ordered_primary_target_identity_sha256": list(primary),
            "ordered_secondary_target_identity_sha256": list(secondary),
            "exhausted": exhausted,
        }
        pages.append(
            ManagedCleanupV3InventoryPage(
                authority_terminal_sha256=_sha("authority"),
                snapshot_sha256=_sha("snapshot"),
                kind=kind,
                page_index=page_index,
                input_cursor_sha256=body["input_cursor_sha256"],
                output_cursor=output,
                ordered_canonical_key_sha256=keys,
                ordered_row_sha256=rows,
                ordered_primary_target_identity_sha256=primary,
                ordered_secondary_target_identity_sha256=secondary,
                exhausted=exhausted,
                page_sha256=commitment("inventory-page/v4", body),
            )
        )
        row_page_sha.append(commitment("inventory-row-page/v4", list(rows)))
        if primary:
            primary_page_sha.append(commitment("inventory-primary-target-page/v4", list(primary)))
        if secondary:
            secondary_page_sha.append(
                commitment("inventory-secondary-target-page/v4", list(secondary))
            )
        cursor = output
    return pages, row_page_sha, primary_page_sha, secondary_page_sha


def _page_root(label: str, values: list[str]) -> str:
    from infinity_context_core.ports.managed_cleanup_v3_contracts import merkle_root

    return merkle_root(tuple(values)) if values else commitment(label, [])


def test_inventory_stream_verifier_enforces_full_cursor_coverage_and_roots() -> None:
    context = _context(LOCOMO_PROFILE)
    counts = (10, 10, 5_882, 5_882, 0, 0, 0, 5_882, 5_882, 0, 0, 5_882, 5_882, 5_882, 0)
    verifier = ManagedCleanupV3InventoryStreamVerifier(
        context=context,
        authority_terminal_sha256=_sha("authority"),
        cleanup_receipt_sha256=_sha("cleanup"),
        snapshot_sha256=_sha("snapshot"),
    )
    receipts = []
    qdrant = commitment("inventory-empty-qdrant/v4", [])
    graphiti_name = graphiti_uuid = ""
    for kind, count in zip(INVENTORY_KINDS, counts, strict=True):
        pages, row_pages, primary_pages, secondary_pages = _inventory_pages(kind, count)
        for page in pages:
            verifier.verify_page(page)
        receipts.append(
            ManagedCleanupV3InventoryKindReceipt(
                kind,
                count,
                len(pages),
                _page_root("inventory-empty-rows/v4", row_pages),
            )
        )
        if kind == "qdrant_target_identities":
            qdrant = _page_root("inventory-empty-qdrant/v4", row_pages)
        if kind == "graphiti_target_names":
            graphiti_name = _page_root("inventory-empty-graphiti-name/v4", row_pages)
        if kind == "graphiti_target_uuids":
            graphiti_uuid = _page_root("inventory-empty-graphiti-uuid/v4", row_pages)
    values = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-terminal.v4",
        "profile_id": context.profile_id,
        "context_sha256": context.context_sha256,
        "authority_terminal_sha256": _sha("authority"),
        "cleanup_receipt_sha256": _sha("cleanup"),
        "snapshot_sha256": _sha("snapshot"),
        "repeatable_read": True,
        "first_page_minimum_proven": True,
        "kind_receipts": [
            {name: getattr(item, name) for name in item.__dataclass_fields__} for item in receipts
        ],
        "expected_qdrant_identity_root_sha256": qdrant,
        "expected_qdrant_identity_count": 0,
        "expected_graphiti_name_root_sha256": graphiti_name,
        "expected_graphiti_uuid_root_sha256": graphiti_uuid,
        "expected_graphiti_identity_count": 5_882,
    }
    terminal = ManagedCleanupV3InventoryTerminal(
        **{
            key: value
            for key, value in values.items()
            if key not in {"schema_version", "kind_receipts"}
        },
        kind_receipts=tuple(receipts),
        terminal_sha256=commitment("inventory-terminal/v4", values),
    )
    assert verifier.finalize(terminal) is terminal


def test_inventory_rejects_early_overflow_and_duplicate_physical_identity() -> None:
    context = _context(LOCOMO_PROFILE)
    verifier = ManagedCleanupV3InventoryStreamVerifier(
        context=context,
        authority_terminal_sha256=_sha("authority"),
        cleanup_receipt_sha256=_sha("cleanup"),
        snapshot_sha256=_sha("snapshot"),
    )
    oversized, *_ = _inventory_pages("memory_scopes", 513)
    with pytest.raises(ManagedCleanupV3Error, match="inventory_sequence_invalid"):
        verifier.verify_page(oversized[0])
    targets, *_ = _inventory_pages("graphiti_target_uuids", 2)
    with pytest.raises(ManagedCleanupV3Error, match="inventory_page_invalid"):
        replace(
            targets[0],
            ordered_canonical_key_sha256=(
                targets[0].ordered_canonical_key_sha256[0],
                targets[0].ordered_canonical_key_sha256[0],
            ),
            ordered_row_sha256=(
                targets[0].ordered_canonical_key_sha256[0],
                targets[0].ordered_canonical_key_sha256[0],
            ),
        )


@pytest.mark.parametrize("bad", [True, 1, None, "A" * 64])
def test_strict_digest_types_reject_bool_int_none_and_uppercase(bad: object) -> None:
    with pytest.raises(ManagedCleanupV3Error):
        replace(_context(LOCOMO_PROFILE), run_id_sha256=bad)  # type: ignore[arg-type]
