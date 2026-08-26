"""Exact standalone contracts for a future paged managed cleanup authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, final

from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_sequence_sha256,
)

CONTEXT_SCHEMA: Final = "memory-comparison-paged-cleanup-context.v4"
OPERATION_SCHEMA: Final = "memory-comparison-paged-cleanup-operation.v4"
PAGE_SCHEMA: Final = "memory-comparison-paged-cleanup-page.v4"
AUTHORITY_SCHEMA: Final = "memory-comparison-paged-cleanup-authority.v4"
STORE_RECEIPT_SCHEMA: Final = "memory-comparison-paged-cleanup-store-receipt.v4"
LOCOMO_PROFILE: Final = "mem0-locomo-top50-v1"
LONGMEMEVAL_PROFILE: Final = "mem0-longmemeval-top50-v1"
PAGE_OPERATION_CAP: Final = 256
PAGE_CANONICAL_BYTES_CAP: Final = 256 * 1024

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_D = b"managed-cleanup-v4/"


class ManagedCleanupV3Error(MemoryValidationError):
    """Stable fail-closed rejection of invalid future cleanup material."""


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_json_invalid") from exc


def commitment(label: str, value: object) -> str:
    if type(label) is not str or not label:
        raise ManagedCleanupV3Error("managed_cleanup_v3_commitment_invalid")
    return hashlib.sha256(_D + label.encode("ascii") + b"\0" + canonical_bytes(value)).hexdigest()


def digest(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ManagedCleanupV3Error("managed_cleanup_v3_digest_invalid")
    return value


def exact_int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ManagedCleanupV3Error("managed_cleanup_v3_count_invalid")
    return value


_PROFILE_ORACLES = {
    LOCOMO_PROFILE: {
        "dataset_sha256": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
        "case_count": 1540,
        "corpus_count": 10,
        "lane": "fact",
        "operation_count": 5882,
        "valid_message_count": 5882,
        "original_pair_slot_count": 0,
        "fully_invalid_pair_slot_count": 0,
        "omitted_source_identity_count": 0,
        "omitted_source_identity_root_sha256": commitment("omitted-source/v1", []),
        "fragment_count": 0,
        "document_source_ref_count": 0,
    },
    LONGMEMEVAL_PROFILE: {
        "dataset_sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
        "case_count": 500,
        "corpus_count": 500,
        "lane": "document",
        "operation_count": 124344,
        "valid_message_count": 246738,
        "original_pair_slot_count": 124345,
        "fully_invalid_pair_slot_count": 1,
        "omitted_source_identity_count": 1,
        "omitted_source_identity_root_sha256": (
            "f4106215d618a016b4d18bdb734437a64d6329ff49db8a4eb5661e359d3408a9"
        ),
        "fragment_count": 366440,
        "document_source_ref_count": 495426,
    },
}
PROFILE_ORACLES: Final = MappingProxyType(
    {key: MappingProxyType(value) for key, value in _PROFILE_ORACLES.items()}
)

CHUNKER_POLICY_SHA256: Final = commitment(
    "chunker-policy/v1",
    {
        "document_renderer": "canonical conversation header then ordered role: content lines",
        "fragmenter": "fragment_document_text",
        "fallback": "chunk_text(target_chars=1200,overlap_chars=120)",
        "descriptor": ["ordinal", "text_sha256", "char_start", "char_end", "kind", "node_kind"],
        "physical_identity": (
            "resolve canonical chunk IDs from DB lineage; never derive IDs from plan"
        ),
    },
)
PROJECTOR_POLICY_SHA256: Final = commitment(
    "projector-policy/v2",
    {
        "source": "pinned official dataset -> managed corpus projection",
        "locomo": "one exact admitted fact per official turn",
        "longmemeval": "one document per nonempty original pair slot",
        "longmemeval_message_rule": "retain 1 or 2 valid messages; skip only fully invalid slot",
        "fragment_policy_sha256": CHUNKER_POLICY_SHA256,
        "thread_external_ref": "exact per-corpus sha256 identity",
        "source_refs": "ordered exact descriptor sha256 sequence and aggregate sha256",
        "oracles": _PROFILE_ORACLES,
    },
)
LIMITS_POLICY_SHA256: Final = commitment(
    "limits/v2",
    {
        "profiles": _PROFILE_ORACLES,
        "page_operation_cap": PAGE_OPERATION_CAP,
        "page_canonical_bytes_cap": PAGE_CANONICAL_BYTES_CAP,
        "inventory_page_size": 512,
    },
)


def profile_oracle(profile_id: object) -> MappingProxyType[str, object]:
    if type(profile_id) is not str or profile_id not in PROFILE_ORACLES:
        raise ManagedCleanupV3Error("managed_cleanup_v3_profile_invalid")
    return PROFILE_ORACLES[profile_id]


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3Context:
    profile_id: str
    manifest_context_sha256: str
    a1_terminal_commitment_sha256: str
    run_id_sha256: str
    binding_commitment_sha256: str
    publishable_profile_commitment_sha256: str
    methodology_commitment_sha256: str
    dataset_sha256: str
    admission_commitment_sha256: str
    ingestion_root_sha256: str
    case_manifest_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    cleanup_target_authority_sha256: str
    qdrant_authority_sha256: str
    qdrant_target_commitment_sha256: str
    qdrant_policy_commitment_sha256: str
    graphiti_authority_sha256: str
    graphiti_target_commitment_sha256: str
    graphiti_policy_commitment_sha256: str
    cognee_policy_sha256: str
    namespace_policy_sha256: str
    cleanup_operation_stream_root_sha256: str
    omitted_source_identity_root_sha256: str
    context_sha256: str
    schema_version: str = CONTEXT_SCHEMA

    def __post_init__(self) -> None:
        oracle = profile_oracle(self.profile_id)
        values = self.payload(include_commitment=False)
        for key, value in values.items():
            if key.endswith("_sha256"):
                digest(value)
        if (
            self.schema_version != CONTEXT_SCHEMA
            or self.dataset_sha256 != oracle["dataset_sha256"]
            or self.omitted_source_identity_root_sha256
            != oracle["omitted_source_identity_root_sha256"]
            or type(self.space_id) is not str
            or _ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _ID.fullmatch(self.space_slug) is None
            or self.context_sha256 != commitment("context/v4", values)
            or self.qdrant_authority_sha256
            != commitment(
                "lane-authority/v4",
                {
                    "lane": "qdrant",
                    "target_commitment_sha256": self.qdrant_target_commitment_sha256,
                    "policy_commitment_sha256": self.qdrant_policy_commitment_sha256,
                },
            )
            or self.graphiti_authority_sha256
            != commitment(
                "lane-authority/v4",
                {
                    "lane": "graphiti",
                    "target_commitment_sha256": self.graphiti_target_commitment_sha256,
                    "policy_commitment_sha256": self.graphiti_policy_commitment_sha256,
                },
            )
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_context_invalid")

    def payload(self, *, include_commitment: bool = True) -> dict[str, object]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        if not include_commitment:
            value.pop("context_sha256")
        return value


def build_context(**values: object) -> ManagedCleanupV3Context:
    body = {"schema_version": CONTEXT_SCHEMA, **values}
    return ManagedCleanupV3Context(**values, context_sha256=commitment("context/v4", body))  # type: ignore[arg-type]


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3Operation:
    sequence: int
    lane: str
    corpus_identity_sha256: str
    memory_scope_external_ref_sha256: str
    thread_external_ref_sha256: str
    source_identity_sha256: str
    source_content_sha256: str
    operation_commitment_sha256: str
    a1_operation_sha256: str
    original_pair_identity_sha256: str | None
    valid_message_count: int
    source_refs_sha256: str
    ordered_source_ref_descriptor_sha256: tuple[str, ...]
    source_ref_root_sha256: str
    fragments_sha256: str
    ordered_fragment_descriptor_sha256: tuple[str, ...]
    fragment_root_sha256: str
    operation_sha256: str
    schema_version: str = OPERATION_SCHEMA

    def __post_init__(self) -> None:
        exact_int(self.sequence)
        exact_int(self.valid_message_count, minimum=1)
        for value in (
            self.corpus_identity_sha256,
            self.memory_scope_external_ref_sha256,
            self.thread_external_ref_sha256,
            self.source_identity_sha256,
            self.source_content_sha256,
            self.operation_commitment_sha256,
            self.a1_operation_sha256,
            self.source_refs_sha256,
            self.source_ref_root_sha256,
            self.fragments_sha256,
            self.fragment_root_sha256,
        ):
            digest(value)
        source_ref_descriptors = self.ordered_source_ref_descriptor_sha256
        fragments = self.ordered_fragment_descriptor_sha256
        if self.original_pair_identity_sha256 is not None:
            digest(self.original_pair_identity_sha256)
        if (
            self.schema_version != OPERATION_SCHEMA
            or self.lane not in {"fact", "document"}
            or self.corpus_identity_sha256
            != corpus_identity_sha256(
                lane=self.lane,
                memory_scope_external_ref_sha256=self.memory_scope_external_ref_sha256,
                thread_external_ref_sha256=self.thread_external_ref_sha256,
            )
            or type(source_ref_descriptors) is not tuple
            or any(
                type(item) is not str or _SHA.fullmatch(item) is None
                for item in source_ref_descriptors
            )
            or self.source_ref_root_sha256
            != commitment("source-ref-root/v4", list(source_ref_descriptors))
            or type(fragments) is not tuple
            or any(type(item) is not str or _SHA.fullmatch(item) is None for item in fragments)
            or len(set(fragments)) != len(fragments)
            or self.fragment_root_sha256 != commitment("fragment-root/v4", list(fragments))
            or (
                self.lane == "fact"
                and (
                    self.original_pair_identity_sha256 is not None
                    or self.valid_message_count != 1
                    or len(source_ref_descriptors) != 1
                    or fragments
                )
            )
            or (
                self.lane == "document"
                and (
                    self.original_pair_identity_sha256 is None
                    or self.valid_message_count not in {1, 2}
                    or len(source_ref_descriptors) != self.valid_message_count + 2
                    or not fragments
                )
            )
            or self.operation_sha256 != commitment("operation/v4", self.payload(False))
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_operation_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        value["ordered_source_ref_descriptor_sha256"] = list(
            self.ordered_source_ref_descriptor_sha256
        )
        value["ordered_fragment_descriptor_sha256"] = list(self.ordered_fragment_descriptor_sha256)
        if not include_commitment:
            value.pop("operation_sha256")
        return value


def thread_external_ref_sha256(value: object) -> str:
    """Commit the exact non-empty external thread reference, not a database id."""

    if type(value) is not str or not value:
        raise ManagedCleanupV3Error("managed_cleanup_v3_thread_external_ref_invalid")
    return commitment("thread-external-ref/v4", {"thread_external_ref": value})


def source_ref_descriptor_sha256(value: object) -> str:
    if type(value) is not dict or not value or any(type(key) is not str for key in value):
        raise ManagedCleanupV3Error("managed_cleanup_v3_source_ref_invalid")
    return commitment("source-ref-descriptor/v4", value)


def source_ref_commitments(
    value: object,
) -> tuple[str, tuple[str, ...], str]:
    """Build the exact managed aggregate plus ordered hash-only descriptors."""

    if type(value) not in {tuple, list} or any(type(item) is not dict for item in value):
        raise ManagedCleanupV3Error("managed_cleanup_v3_source_ref_invalid")
    descriptors = tuple(source_ref_descriptor_sha256(item) for item in value)
    return (
        managed_benchmark_sequence_sha256(value),  # type: ignore[arg-type]
        descriptors,
        commitment("source-ref-root/v4", list(descriptors)),
    )


def fragment_descriptor_sha256(value: object) -> str:
    if type(value) is not dict or not value or any(type(key) is not str for key in value):
        raise ManagedCleanupV3Error("managed_cleanup_v3_fragment_invalid")
    return commitment("fragment-descriptor/v4", value)


def fragment_commitments(
    value: object,
) -> tuple[str, tuple[str, ...], str]:
    """Build the managed aggregate and exact ordered fragment commitments."""

    if type(value) not in {tuple, list} or any(type(item) is not dict for item in value):
        raise ManagedCleanupV3Error("managed_cleanup_v3_fragment_invalid")
    descriptors = tuple(fragment_descriptor_sha256(item) for item in value)
    return (
        managed_benchmark_sequence_sha256(value),  # type: ignore[arg-type]
        descriptors,
        commitment("fragment-root/v4", list(descriptors)),
    )


def memory_scope_external_ref_sha256(value: object) -> str:
    """Commit the exact non-empty memory-scope external reference."""

    if type(value) is not str or not value:
        raise ManagedCleanupV3Error("managed_cleanup_v3_corpus_external_ref_invalid")
    return commitment("memory-scope-external-ref/v4", {"memory_scope_external_ref": value})


def corpus_identity_sha256(
    *,
    lane: object,
    memory_scope_external_ref_sha256: object,
    thread_external_ref_sha256: object,
) -> str:
    if lane not in {"fact", "document"}:
        raise ManagedCleanupV3Error("managed_cleanup_v3_corpus_identity_invalid")
    scope = digest(memory_scope_external_ref_sha256)
    thread = digest(thread_external_ref_sha256)
    return commitment(
        "corpus-identity/v4",
        {
            "lane": lane,
            "memory_scope_external_ref_sha256": scope,
            "thread_external_ref_sha256": thread,
        },
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3Page:
    context_sha256: str
    page_index: int
    start_sequence: int
    end_sequence_exclusive: int
    operations: tuple[ManagedCleanupV3Operation, ...]
    page_sha256: str
    schema_version: str = PAGE_SCHEMA

    def __post_init__(self) -> None:
        digest(self.context_sha256)
        exact_int(self.page_index)
        exact_int(self.start_sequence)
        exact_int(self.end_sequence_exclusive, minimum=1)
        if (
            self.schema_version != PAGE_SCHEMA
            or type(self.operations) is not tuple
            or not 1 <= len(self.operations) <= PAGE_OPERATION_CAP
            or any(type(item) is not ManagedCleanupV3Operation for item in self.operations)
            or tuple(item.sequence for item in self.operations)
            != tuple(range(self.start_sequence, self.end_sequence_exclusive))
            or self.end_sequence_exclusive != self.start_sequence + len(self.operations)
            or self.page_sha256 != commitment("page/v4", self.payload(False))
            or len(canonical_bytes(self.payload())) > PAGE_CANONICAL_BYTES_CAP
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_page_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "context_sha256": self.context_sha256,
            "page_index": self.page_index,
            "start_sequence": self.start_sequence,
            "end_sequence_exclusive": self.end_sequence_exclusive,
            "operations": [item.payload() for item in self.operations],
        }
        if include_commitment:
            value["page_sha256"] = self.page_sha256
        return value


def merkle_root(values: tuple[str, ...]) -> str:
    if not values:
        raise ManagedCleanupV3Error("managed_cleanup_v3_merkle_invalid")
    level = [
        hashlib.sha256(_D + b"leaf\0" + bytes.fromhex(digest(item))).digest() for item in values
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(_D + b"node\0" + level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    return level[0].hex()


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3Authority:
    profile_id: str
    context_sha256: str
    a1_terminal_commitment_sha256: str
    operation_count: int
    valid_message_count: int
    original_pair_slot_count: int
    fully_invalid_pair_slot_count: int
    fragment_count: int
    corpus_thread_identity_count: int
    corpus_thread_identity_root_sha256: str
    document_source_ref_count: int
    document_source_ref_root_sha256: str
    page_count: int
    ordered_page_sha256: tuple[str, ...]
    pages_merkle_root_sha256: str
    a1_operation_stream_root_sha256: str
    cleanup_operation_stream_root_sha256: str
    omitted_source_identity_root_sha256: str
    projector_policy_sha256: str
    chunker_policy_sha256: str
    limits_policy_sha256: str
    terminal_commitment_sha256: str
    schema_version: str = AUTHORITY_SCHEMA

    def __post_init__(self) -> None:
        oracle = profile_oracle(self.profile_id)
        exact_int(self.operation_count, minimum=1)
        exact_int(self.valid_message_count, minimum=1)
        exact_int(self.original_pair_slot_count)
        exact_int(self.fully_invalid_pair_slot_count)
        exact_int(self.fragment_count)
        exact_int(self.corpus_thread_identity_count, minimum=1)
        exact_int(self.document_source_ref_count)
        exact_int(self.page_count, minimum=1)
        pages = self.ordered_page_sha256
        for value in (
            self.context_sha256,
            self.a1_terminal_commitment_sha256,
            self.a1_operation_stream_root_sha256,
            self.cleanup_operation_stream_root_sha256,
            self.omitted_source_identity_root_sha256,
            self.corpus_thread_identity_root_sha256,
            self.document_source_ref_root_sha256,
        ):
            digest(value)
        if (
            self.schema_version != AUTHORITY_SCHEMA
            or type(pages) is not tuple
            or not pages
            or any(type(x) is not str or _SHA.fullmatch(x) is None for x in pages)
            or self.page_count != len(pages)
            or self.corpus_thread_identity_count != oracle["corpus_count"]
            or self.document_source_ref_count != oracle["document_source_ref_count"]
            or self.pages_merkle_root_sha256 != merkle_root(pages)
            or any(
                getattr(self, key) != oracle[key]
                for key in (
                    "operation_count",
                    "valid_message_count",
                    "original_pair_slot_count",
                    "fully_invalid_pair_slot_count",
                    "fragment_count",
                )
            )
            or self.projector_policy_sha256 != PROJECTOR_POLICY_SHA256
            or self.chunker_policy_sha256 != CHUNKER_POLICY_SHA256
            or self.limits_policy_sha256 != LIMITS_POLICY_SHA256
            or self.terminal_commitment_sha256 != commitment("authority/v4", self.payload(False))
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_authority_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        value["ordered_page_sha256"] = list(self.ordered_page_sha256)
        if not include_commitment:
            value.pop("terminal_commitment_sha256")
        return value


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3StoreReceipt:
    context_sha256: str
    terminal_commitment_sha256: str
    page_count: int
    committed: bool
    receipt_sha256: str
    schema_version: str = STORE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        digest(self.context_sha256)
        digest(self.terminal_commitment_sha256)
        exact_int(self.page_count, minimum=1)
        body = {
            "schema_version": self.schema_version,
            "context_sha256": self.context_sha256,
            "terminal_commitment_sha256": self.terminal_commitment_sha256,
            "page_count": self.page_count,
            "committed": self.committed,
        }
        if (
            self.schema_version != STORE_RECEIPT_SCHEMA
            or self.committed is not True
            or self.receipt_sha256 != commitment("store-receipt/v4", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_store_receipt_invalid")


__all__ = tuple(
    name
    for name in globals()
    if name.startswith("ManagedCleanupV3")
    or name.endswith("_SHA256")
    or name
    in {
        "build_context",
        "canonical_bytes",
        "corpus_identity_sha256",
        "fragment_commitments",
        "fragment_descriptor_sha256",
        "commitment",
        "merkle_root",
        "memory_scope_external_ref_sha256",
        "profile_oracle",
        "PAGE_OPERATION_CAP",
        "PAGE_CANONICAL_BYTES_CAP",
        "LOCOMO_PROFILE",
        "LONGMEMEVAL_PROFILE",
        "PROFILE_ORACLES",
        "source_ref_descriptor_sha256",
        "source_ref_commitments",
        "thread_external_ref_sha256",
    }
)
