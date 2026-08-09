"""Immutable contracts and commitments for a future managed Mem0 v6 manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, final

from infinity_context_core.domain.errors import MemoryValidationError

MANAGED_MEM0_V6_CONTEXT_SCHEMA_VERSION: Final = (
    "memory-comparison-managed-mem0-v6-manifest-context.v1"
)
MANAGED_MEM0_V6_PAGE_SCHEMA_VERSION: Final = "memory-comparison-managed-mem0-v6-manifest-page.v1"
MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION: Final = (
    "memory-comparison-managed-mem0-v6-paged-manifest-authority.v1"
)
MANAGED_MEM0_V6_UNIQUENESS_RECEIPT_SCHEMA_VERSION: Final = (
    "memory-comparison-managed-mem0-v6-uniqueness-receipt.v1"
)
MANAGED_MEM0_V6_STORE_RECEIPT_SCHEMA_VERSION: Final = (
    "memory-comparison-managed-mem0-v6-page-store-commit-receipt.v1"
)
MANAGED_MEM0_V6_LIMITS_POLICY_SCHEMA_VERSION: Final = (
    "memory-comparison-managed-mem0-v6-manifest-limits-policy.v1"
)
MANAGED_MEM0_V6_PAGE_SIZE: Final = 512
MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS: Final = MappingProxyType(
    {
        "mem0-locomo-top50-v1": 5_882,
        "mem0-longmemeval-top50-v1": 124_344,
    }
)
MANAGED_MEM0_V6_MAX_OPERATION_COUNT: Final = max(MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS.values())
MANAGED_MEM0_V6_MAX_PAGE_COUNT: Final = (
    MANAGED_MEM0_V6_MAX_OPERATION_COUNT + MANAGED_MEM0_V6_PAGE_SIZE - 1
) // MANAGED_MEM0_V6_PAGE_SIZE

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_DOMAIN = b"managed-mem0-v6/context/v1\0"
_PAGE_DOMAIN = b"managed-mem0-v6/page/v1\0"
_LEAF_DOMAIN = b"managed-mem0-v6/leaf/v1\0"
_NODE_DOMAIN = b"managed-mem0-v6/node/v1\0"
_TERMINAL_DOMAIN = b"managed-mem0-v6/terminal/v1\0"
_LIMITS_DOMAIN = b"managed-mem0-v6/limits/v1\0"
_UNIQUE_DOMAIN = b"managed-mem0-v6/uniqueness/v1\0"
_STORE_DOMAIN = b"managed-mem0-v6/store/v1\0"


class ManagedMem0V6ManifestError(MemoryValidationError):
    """Stable fail-closed rejection of invalid v6 manifest material."""


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_json_invalid") from exc


def domain_sha256(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def require_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_digest_invalid")
    return value


def profile_operation_count(profile_id: object) -> int:
    if type(profile_id) is not str:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_profile_invalid")
    count = MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS.get(profile_id)
    if count is None:
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_profile_invalid")
    return count


def _limits_payload() -> dict[str, object]:
    return {
        "schema_version": MANAGED_MEM0_V6_LIMITS_POLICY_SCHEMA_VERSION,
        "page_size": MANAGED_MEM0_V6_PAGE_SIZE,
        "profile_operation_counts": dict(MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS),
    }


MANAGED_MEM0_V6_LIMITS_POLICY_SHA256: Final = domain_sha256(_LIMITS_DOMAIN, _limits_payload())


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6ManifestContext:
    """Independent exact binding for one run's full manifest authority."""

    profile_id: str
    run_id_sha256: str
    binding_commitment_sha256: str
    publishable_profile_commitment_sha256: str
    methodology_commitment_sha256: str
    dataset_sha256: str
    admission_commitment_sha256: str
    ingestion_root_sha256: str
    manifest_context_sha256: str
    schema_version: str = MANAGED_MEM0_V6_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        profile_operation_count(self.profile_id)
        digests = (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.publishable_profile_commitment_sha256,
            self.methodology_commitment_sha256,
            self.dataset_sha256,
            self.admission_commitment_sha256,
            self.ingestion_root_sha256,
        )
        for digest in digests:
            require_sha256(digest)
        body = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "publishable_profile_commitment_sha256": (self.publishable_profile_commitment_sha256),
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "dataset_sha256": self.dataset_sha256,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
        }
        if (
            self.schema_version != MANAGED_MEM0_V6_CONTEXT_SCHEMA_VERSION
            or self.manifest_context_sha256 != domain_sha256(_CONTEXT_DOMAIN, body)
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_context_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedMem0V6ManifestContext is final")


def build_managed_mem0_v6_manifest_context(
    *,
    profile_id: str,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    publishable_profile_commitment_sha256: str,
    methodology_commitment_sha256: str,
    dataset_sha256: str,
    admission_commitment_sha256: str,
    ingestion_root_sha256: str,
) -> ManagedMem0V6ManifestContext:
    body = {
        "schema_version": MANAGED_MEM0_V6_CONTEXT_SCHEMA_VERSION,
        "profile_id": profile_id,
        "run_id_sha256": run_id_sha256,
        "binding_commitment_sha256": binding_commitment_sha256,
        "publishable_profile_commitment_sha256": publishable_profile_commitment_sha256,
        "methodology_commitment_sha256": methodology_commitment_sha256,
        "dataset_sha256": dataset_sha256,
        "admission_commitment_sha256": admission_commitment_sha256,
        "ingestion_root_sha256": ingestion_root_sha256,
    }
    return ManagedMem0V6ManifestContext(
        **{key: value for key, value in body.items() if key != "schema_version"},
        manifest_context_sha256=domain_sha256(_CONTEXT_DOMAIN, body),
    )


def page_body(
    *,
    profile_id: str,
    manifest_context_sha256: str,
    page_index: int,
    start_sequence: int,
    ordered_operation_sha256: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": MANAGED_MEM0_V6_PAGE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "manifest_context_sha256": manifest_context_sha256,
        "page_index": page_index,
        "start_sequence": start_sequence,
        "end_sequence_exclusive": start_sequence + len(ordered_operation_sha256),
        "operation_count": len(ordered_operation_sha256),
        "ordered_operation_sha256": list(ordered_operation_sha256),
    }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6ManifestPage:
    profile_id: str
    manifest_context_sha256: str
    page_index: int
    start_sequence: int
    end_sequence_exclusive: int
    ordered_operation_sha256: tuple[str, ...]
    page_commitment_sha256: str
    schema_version: str = MANAGED_MEM0_V6_PAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected_total = profile_operation_count(self.profile_id)
        require_sha256(self.manifest_context_sha256)
        operations = self.ordered_operation_sha256
        if (
            self.schema_version != MANAGED_MEM0_V6_PAGE_SCHEMA_VERSION
            or type(self.page_index) is not int
            or type(self.start_sequence) is not int
            or type(self.end_sequence_exclusive) is not int
            or type(operations) is not tuple
            or not operations
            or len(operations) > MANAGED_MEM0_V6_PAGE_SIZE
            or self.page_index < 0
            or self.start_sequence != self.page_index * MANAGED_MEM0_V6_PAGE_SIZE
            or self.end_sequence_exclusive != self.start_sequence + len(operations)
            or self.end_sequence_exclusive > expected_total
            or any(type(item) is not str or _SHA256.fullmatch(item) is None for item in operations)
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_page_invalid")
        body = page_body(
            profile_id=self.profile_id,
            manifest_context_sha256=self.manifest_context_sha256,
            page_index=self.page_index,
            start_sequence=self.start_sequence,
            ordered_operation_sha256=operations,
        )
        if self.page_commitment_sha256 != domain_sha256(_PAGE_DOMAIN, body):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_page_invalid")

    @property
    def operation_count(self) -> int:
        return len(self.ordered_operation_sha256)


def merkle_root(page_commitments: tuple[str, ...]) -> str:
    if not page_commitments or any(
        type(item) is not str or _SHA256.fullmatch(item) is None for item in page_commitments
    ):
        raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_merkle_invalid")
    level = [
        hashlib.sha256(_LEAF_DOMAIN + bytes.fromhex(item)).digest() for item in page_commitments
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(_NODE_DOMAIN + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def uniqueness_receipt_sha256(
    context_sha256: str, operation_count: int, operations_root_sha256: str
) -> str:
    return domain_sha256(
        _UNIQUE_DOMAIN,
        {
            "schema_version": MANAGED_MEM0_V6_UNIQUENESS_RECEIPT_SCHEMA_VERSION,
            "manifest_context_sha256": context_sha256,
            "operation_count": operation_count,
            "ordered_operations_root_sha256": operations_root_sha256,
        },
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6UniquenessReceipt:
    manifest_context_sha256: str
    operation_count: int
    ordered_operations_root_sha256: str
    receipt_sha256: str
    schema_version: str = MANAGED_MEM0_V6_UNIQUENESS_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_sha256(self.manifest_context_sha256)
        require_sha256(self.ordered_operations_root_sha256)
        if (
            self.schema_version != MANAGED_MEM0_V6_UNIQUENESS_RECEIPT_SCHEMA_VERSION
            or type(self.operation_count) is not int
            or not 1 <= self.operation_count <= MANAGED_MEM0_V6_MAX_OPERATION_COUNT
            or self.receipt_sha256
            != uniqueness_receipt_sha256(
                self.manifest_context_sha256,
                self.operation_count,
                self.ordered_operations_root_sha256,
            )
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_uniqueness_receipt_invalid")


def authority_body(
    *,
    profile_id: str,
    manifest_context_sha256: str,
    operation_count: int,
    ordered_page_commitment_sha256: tuple[str, ...],
    pages_merkle_root_sha256: str,
    uniqueness_receipt_sha256_value: str,
) -> dict[str, object]:
    return {
        "schema_version": MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
        "profile_id": profile_id,
        "manifest_context_sha256": manifest_context_sha256,
        "operation_count": operation_count,
        "page_size": MANAGED_MEM0_V6_PAGE_SIZE,
        "page_count": len(ordered_page_commitment_sha256),
        "ordered_page_commitment_sha256": list(ordered_page_commitment_sha256),
        "pages_merkle_root_sha256": pages_merkle_root_sha256,
        "uniqueness_receipt_sha256": uniqueness_receipt_sha256_value,
        "limits_policy_sha256": MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6PagedManifestAuthority:
    profile_id: str
    manifest_context_sha256: str
    operation_count: int
    page_size: int
    page_count: int
    ordered_page_commitment_sha256: tuple[str, ...]
    pages_merkle_root_sha256: str
    uniqueness_receipt_sha256: str
    limits_policy_sha256: str
    terminal_commitment_sha256: str
    schema_version: str = MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = profile_operation_count(self.profile_id)
        require_sha256(self.manifest_context_sha256)
        require_sha256(self.uniqueness_receipt_sha256)
        commitments = self.ordered_page_commitment_sha256
        expected_pages = (expected + MANAGED_MEM0_V6_PAGE_SIZE - 1) // MANAGED_MEM0_V6_PAGE_SIZE
        if (
            self.schema_version != MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION
            or type(self.operation_count) is not int
            or self.operation_count != expected
            or type(self.page_size) is not int
            or self.page_size != MANAGED_MEM0_V6_PAGE_SIZE
            or type(self.page_count) is not int
            or self.page_count != expected_pages
            or type(commitments) is not tuple
            or len(commitments) != expected_pages
            or expected_pages > MANAGED_MEM0_V6_MAX_PAGE_COUNT
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_authority_invalid")
        root = merkle_root(commitments)
        if (
            self.pages_merkle_root_sha256 != root
            or self.limits_policy_sha256 != MANAGED_MEM0_V6_LIMITS_POLICY_SHA256
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_authority_invalid")
        body = authority_body(
            profile_id=self.profile_id,
            manifest_context_sha256=self.manifest_context_sha256,
            operation_count=self.operation_count,
            ordered_page_commitment_sha256=commitments,
            pages_merkle_root_sha256=root,
            uniqueness_receipt_sha256_value=self.uniqueness_receipt_sha256,
        )
        if self.terminal_commitment_sha256 != domain_sha256(_TERMINAL_DOMAIN, body):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_manifest_authority_invalid")


def store_receipt_sha256(context_sha256: str, terminal_sha256: str, page_count: int) -> str:
    return domain_sha256(
        _STORE_DOMAIN,
        {
            "schema_version": MANAGED_MEM0_V6_STORE_RECEIPT_SCHEMA_VERSION,
            "manifest_context_sha256": context_sha256,
            "authority_terminal_commitment_sha256": terminal_sha256,
            "page_count": page_count,
        },
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V6PageStoreCommitReceipt:
    manifest_context_sha256: str
    authority_terminal_commitment_sha256: str
    page_count: int
    receipt_sha256: str
    schema_version: str = MANAGED_MEM0_V6_STORE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_sha256(self.manifest_context_sha256)
        require_sha256(self.authority_terminal_commitment_sha256)
        if (
            self.schema_version != MANAGED_MEM0_V6_STORE_RECEIPT_SCHEMA_VERSION
            or type(self.page_count) is not int
            or not 1 <= self.page_count <= MANAGED_MEM0_V6_MAX_PAGE_COUNT
            or self.receipt_sha256
            != store_receipt_sha256(
                self.manifest_context_sha256,
                self.authority_terminal_commitment_sha256,
                self.page_count,
            )
        ):
            raise ManagedMem0V6ManifestError("managed_mem0_v6_store_receipt_invalid")


PAGE_COMMITMENT_DOMAIN: Final = _PAGE_DOMAIN
TERMINAL_COMMITMENT_DOMAIN: Final = _TERMINAL_DOMAIN
