"""Authenticated provider-free receipt for one strict-v4 full preparation."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.context_authority_registration import (
    ContextAuthorityRegistration,
    authenticate_context_authority_registration,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3StoreReceipt,
    commitment,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    ManagedMem0V6ManifestContext,
    ManagedMem0V6PagedManifestAuthority,
    ManagedMem0V6PageStoreCommitReceipt,
)

STRICT_V4_PREPARATION_SCHEMA = "memory-comparison-strict-v4-full-preparation.v1"


@dataclass(frozen=True, slots=True)
class StrictV4PreparationReceipt:
    profile_id: str
    dataset_sha256: str
    run_id_sha256: str
    binding_commitment_sha256: str
    methodology_commitment_sha256: str
    admission_commitment_sha256: str
    ingestion_root_sha256: str
    original_pair_path: str | None
    original_pair_terminal_sha256: str | None
    original_pair_key_id: str | None
    original_pair_key_commitment_sha256: str | None
    a1_path: str
    a1_key_id: str
    a1_key_commitment_sha256: str
    a1_context: ManagedMem0V6ManifestContext
    a1_authority: ManagedMem0V6PagedManifestAuthority
    a1_store_receipt: ManagedMem0V6PageStoreCommitReceipt
    a2_path: str
    a2_key_id: str
    a2_key_commitment_sha256: str
    a2_context: ManagedCleanupV3Context
    a2_authority: ManagedCleanupV3Authority
    a2_store_receipt: ManagedCleanupV3StoreReceipt
    expected_index_path: str
    expected_index_key_id: str
    expected_index_key_commitment_sha256: str
    expected_index_terminal_sha256: str
    registration_sha256: str
    registration_mac_sha256: str
    registered_at: datetime
    receipt_key_commitment_sha256: str
    provider_calls: int
    paid_go_ready: bool
    prepared_at: datetime
    receipt_sha256: str
    receipt_mac_sha256: str
    schema_version: str = STRICT_V4_PREPARATION_SCHEMA

    def payload(self, *, authenticated: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "dataset_sha256": self.dataset_sha256,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "original_pair_path": self.original_pair_path,
            "original_pair_terminal_sha256": self.original_pair_terminal_sha256,
            "original_pair_key_id": self.original_pair_key_id,
            "original_pair_key_commitment_sha256": (self.original_pair_key_commitment_sha256),
            "a1_path": self.a1_path,
            "a1_key_id": self.a1_key_id,
            "a1_key_commitment_sha256": self.a1_key_commitment_sha256,
            "a1_context": _dataclass_payload(self.a1_context),
            "a1_authority": _dataclass_payload(self.a1_authority),
            "a1_store_receipt": _dataclass_payload(self.a1_store_receipt),
            "a2_path": self.a2_path,
            "a2_key_id": self.a2_key_id,
            "a2_key_commitment_sha256": self.a2_key_commitment_sha256,
            "a2_context": self.a2_context.payload(),
            "a2_authority": self.a2_authority.payload(),
            "a2_store_receipt": _dataclass_payload(self.a2_store_receipt),
            "expected_index_path": self.expected_index_path,
            "expected_index_key_id": self.expected_index_key_id,
            "expected_index_key_commitment_sha256": (self.expected_index_key_commitment_sha256),
            "expected_index_terminal_sha256": self.expected_index_terminal_sha256,
            "registration_sha256": self.registration_sha256,
            "registration_mac_sha256": self.registration_mac_sha256,
            "registered_at": self.registered_at.isoformat(),
            "receipt_key_commitment_sha256": self.receipt_key_commitment_sha256,
            "provider_calls": self.provider_calls,
            "paid_go_ready": self.paid_go_ready,
            "prepared_at": self.prepared_at.isoformat(),
        }
        if authenticated:
            value.update(
                receipt_sha256=self.receipt_sha256,
                receipt_mac_sha256=self.receipt_mac_sha256,
            )
        return value


class StrictV4PreparationReceiptPort(Protocol):
    def write(self, receipt: StrictV4PreparationReceipt) -> None: ...
    def read(self) -> StrictV4PreparationReceipt: ...


class StrictV4PreparationKeyIdentityPort(Protocol):
    """Resolve opaque signed key IDs through a caller-owned secret capability."""

    def resolve(self, *, purpose: str, key_id: str) -> bytes: ...


def strict_v4_preparation_key_commitment(
    key: bytes, *, purpose: str, key_id: str, artifact_context: str
) -> str:
    if type(key) is not bytes or len(key) < 32:
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    material = commitment(
        "strict-v4-preparation-key-binding-material/v1",
        {"purpose": purpose, "key_id": key_id, "artifact_context": artifact_context},
    )
    return hmac.new(
        key,
        b"strict-v4-preparation-key-binding/v1\x00" + material.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def strict_v4_receipt_key_commitment(
    authenticator: ProjectionReceiptAuthenticator, *, artifact_context: str
) -> str:
    material = commitment(
        "strict-v4-preparation-receipt-key-binding-material/v1",
        {"purpose": "receipt", "artifact_context": artifact_context},
    )
    return authenticator.sign("strict-v4-preparation-receipt-key-binding", material)


def build_strict_v4_preparation_receipt(
    *,
    authenticator: ProjectionReceiptAuthenticator,
    registration: ContextAuthorityRegistration,
    prepared_at: datetime,
    **values: object,
) -> StrictV4PreparationReceipt:
    if prepared_at.tzinfo is None or prepared_at < registration.registered_at:
        raise ProjectionReceiptError("projection_receipt.preparation_time_invalid")
    base = StrictV4PreparationReceipt(
        **values,
        registration_sha256=registration.registration_sha256,
        registration_mac_sha256=registration.registration_mac_sha256,
        registered_at=registration.registered_at,
        provider_calls=0,
        paid_go_ready=False,
        prepared_at=prepared_at,
        receipt_sha256="0" * 64,
        receipt_mac_sha256="0" * 64,
    )
    digest = commitment("strict-v4-full-preparation/v1", base.payload(authenticated=False))
    return StrictV4PreparationReceipt(
        **{
            name: getattr(base, name)
            for name in base.__dataclass_fields__
            if name not in {"receipt_sha256", "receipt_mac_sha256"}
        },
        receipt_sha256=digest,
        receipt_mac_sha256=authenticator.sign("strict-v4-full-preparation", digest),
    )


def authenticate_strict_v4_preparation_receipt(
    receipt: StrictV4PreparationReceipt,
    *,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    if type(receipt) is not StrictV4PreparationReceipt:
        raise ProjectionReceiptError("projection_receipt.preparation_missing")
    for value in (
        receipt.a1_context,
        receipt.a1_authority,
        receipt.a1_store_receipt,
        receipt.a2_context,
        receipt.a2_authority,
        receipt.a2_store_receipt,
    ):
        value.__post_init__()
    registration = ContextAuthorityRegistration(
        context=receipt.a2_context,
        authority=receipt.a2_authority,
        registration_sha256=receipt.registration_sha256,
        registration_mac_sha256=receipt.registration_mac_sha256,
        registered_at=receipt.registered_at,
        created=False,
    )
    authenticate_context_authority_registration(
        registration,
        expected_context=receipt.a2_context,
        expected_authority=receipt.a2_authority,
        authenticator=authenticator,
    )
    pair = (
        receipt.original_pair_path,
        receipt.original_pair_terminal_sha256,
        receipt.original_pair_key_id,
        receipt.original_pair_key_commitment_sha256,
    )
    expected = commitment("strict-v4-full-preparation/v1", receipt.payload(authenticated=False))
    if (
        receipt.schema_version != STRICT_V4_PREPARATION_SCHEMA
        or type(receipt.provider_calls) is not int
        or receipt.provider_calls != 0
        or receipt.paid_go_ready is not False
        or receipt.prepared_at.tzinfo is None
        or receipt.prepared_at < receipt.registered_at
        or (receipt.profile_id.endswith("longmemeval-top50-v1") and any(x is None for x in pair))
        or (
            not receipt.profile_id.endswith("longmemeval-top50-v1")
            and any(x is not None for x in pair)
        )
        or receipt.profile_id != receipt.a1_context.profile_id
        or receipt.profile_id != receipt.a2_context.profile_id
        or receipt.dataset_sha256 != receipt.a1_context.dataset_sha256
        or receipt.dataset_sha256 != receipt.a2_context.dataset_sha256
        or receipt.run_id_sha256 != receipt.a1_context.run_id_sha256
        or receipt.run_id_sha256 != receipt.a2_context.run_id_sha256
        or receipt.binding_commitment_sha256 != receipt.a1_context.binding_commitment_sha256
        or receipt.binding_commitment_sha256 != receipt.a2_context.binding_commitment_sha256
        or receipt.methodology_commitment_sha256 != receipt.a1_context.methodology_commitment_sha256
        or receipt.methodology_commitment_sha256 != receipt.a2_context.methodology_commitment_sha256
        or receipt.admission_commitment_sha256 != receipt.a1_context.admission_commitment_sha256
        or receipt.admission_commitment_sha256 != receipt.a2_context.admission_commitment_sha256
        or receipt.ingestion_root_sha256 != receipt.a1_context.ingestion_root_sha256
        or receipt.ingestion_root_sha256 != receipt.a2_context.ingestion_root_sha256
        or receipt.a1_context.manifest_context_sha256 != receipt.a2_context.manifest_context_sha256
        or receipt.a1_authority.terminal_commitment_sha256
        != receipt.a2_context.a1_terminal_commitment_sha256
        or receipt.a1_store_receipt.authority_terminal_commitment_sha256
        != receipt.a1_authority.terminal_commitment_sha256
        or receipt.a2_store_receipt.terminal_commitment_sha256
        != receipt.a2_authority.terminal_commitment_sha256
        or receipt.expected_index_terminal_sha256 != receipt.a2_authority.terminal_commitment_sha256
        or receipt.receipt_sha256 != expected
        or not authenticator.verify(
            "strict-v4-full-preparation", expected, receipt.receipt_mac_sha256
        )
    ):
        raise ProjectionReceiptError("projection_receipt.preparation_invalid")


def _dataclass_payload(value: object) -> dict[str, object]:
    return {
        name: list(item) if isinstance(item, tuple) else item
        for name in value.__dataclass_fields__  # type: ignore[attr-defined]
        for item in (getattr(value, name),)
    }


__all__ = (
    "STRICT_V4_PREPARATION_SCHEMA",
    "StrictV4PreparationReceipt",
    "StrictV4PreparationKeyIdentityPort",
    "StrictV4PreparationReceiptPort",
    "authenticate_strict_v4_preparation_receipt",
    "build_strict_v4_preparation_receipt",
    "strict_v4_preparation_key_commitment",
    "strict_v4_receipt_key_commitment",
)
