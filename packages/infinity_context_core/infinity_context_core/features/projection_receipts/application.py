"""Exact provider readback and authenticated receipt construction."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from infinity_context_core.features.projection_receipts.contracts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReadbackPort,
    ProjectionReceiptError,
    ProjectionTargetIdentity,
)


@dataclass(frozen=True)
class AuthenticatedProjectionIdentity:
    identity: ProjectionTargetIdentity
    identity_sha256: str
    identity_commitment_sha256: str
    identity_mac_sha256: str


@dataclass(frozen=True)
class ProjectionResultReceipt:
    binding: ProjectionJobBinding
    operation: str
    result_state: str
    identities: tuple[AuthenticatedProjectionIdentity, ...]
    ordered_identity_root_sha256: str
    provider_completed_at: datetime
    persisted_at: datetime
    receipt_sha256: str
    receipt_mac_sha256: str


class ProjectionReceiptAuthenticator:
    """Dedicated in-memory HMAC capability; its secret is never serializable."""

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ProjectionReceiptError("projection_receipt.hmac_capability_invalid")
        self._secret = secret

    @property
    def authority_sha256(self) -> str:
        """Stable public commitment to the otherwise opaque worker capability."""

        return hashlib.sha256(
            b"infinity-context:projection-receipt-worker-authority:v1:" + self._secret
        ).hexdigest()

    def sign(self, domain: str, payload_sha256: str) -> str:
        message = f"infinity-context:{domain}:v1:{payload_sha256}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, domain: str, payload_sha256: str, mac_sha256: str) -> bool:
        return hmac.compare_digest(self.sign(domain, payload_sha256), mac_sha256)


async def ensure_projection_and_readback(
    provider: ProjectionReadbackPort,
    *,
    binding: ProjectionJobBinding,
    expected_identities: tuple[ProjectionTargetIdentity, ...],
) -> ProjectionMaterialization:
    """Return one exact materialization, performing at most one provider upsert."""

    _validate_expected_identities(binding, expected_identities)
    matches = await provider.read_exact(binding)
    if not matches:
        await provider.upsert_exact(binding, expected_identities)
        matches = await provider.read_exact(binding)
    if len(matches) != 1:
        code = (
            "projection_receipt.readback_absent"
            if not matches
            else "projection_receipt.readback_multiple"
        )
        raise ProjectionReceiptError(code)
    materialization = matches[0]
    if materialization.projection_key_sha256 != binding.projection_key_sha256:
        raise ProjectionReceiptError("projection_receipt.readback_foreign")
    _validate_observed_identities(binding, materialization.identities)
    if _ordered(materialization.identities) != _ordered(expected_identities):
        raise ProjectionReceiptError("projection_receipt.readback_divergent")
    if materialization.completed_at.tzinfo is None:
        raise ProjectionReceiptError("projection_receipt.readback_time_invalid")
    return materialization


async def ensure_projection_deleted_and_readback(
    provider: ProjectionReadbackPort,
    *,
    binding: ProjectionJobBinding,
    expected_identities: tuple[ProjectionTargetIdentity, ...],
    observed_at: datetime,
) -> ProjectionMaterialization:
    """Prove exact replayable absence, deleting one exact materialization at most once."""

    _validate_expected_identities(binding, expected_identities)
    matches = await provider.read_exact(binding)
    if len(matches) > 1:
        raise ProjectionReceiptError("projection_receipt.readback_multiple")
    completed_at = observed_at
    if matches:
        observed = matches[0]
        if observed.projection_key_sha256 != binding.projection_key_sha256 or _ordered(
            observed.identities
        ) != _ordered(expected_identities):
            raise ProjectionReceiptError("projection_receipt.readback_divergent")
        _validate_observed_identities(binding, observed.identities)
        completed_at = await provider.delete_exact(binding, expected_identities)
        if await provider.read_exact(binding):
            raise ProjectionReceiptError("projection_receipt.delete_readback_present")
    if completed_at.tzinfo is None:
        raise ProjectionReceiptError("projection_receipt.readback_time_invalid")
    return ProjectionMaterialization(
        projection_key_sha256=binding.projection_key_sha256,
        identities=_ordered(expected_identities),
        completed_at=completed_at,
    )


def build_projection_result_receipt(
    *,
    binding: ProjectionJobBinding,
    materialization: ProjectionMaterialization,
    authenticator: ProjectionReceiptAuthenticator,
    persisted_at: datetime | None = None,
    operation: str = "upsert",
    result_state: str = "present",
) -> ProjectionResultReceipt:
    if (operation, result_state) not in {("upsert", "present"), ("delete", "absent")}:
        raise ProjectionReceiptError("projection_receipt.result_state_invalid")
    _validate_expected_identities(binding, materialization.identities)
    effective_persisted_at = persisted_at or datetime.now(UTC)
    if effective_persisted_at.tzinfo is None:
        raise ProjectionReceiptError("projection_receipt.persisted_time_invalid")
    authenticated = tuple(
        AuthenticatedProjectionIdentity(
            identity=identity,
            identity_sha256=identity.identity_sha256,
            identity_commitment_sha256=identity.identity_commitment_sha256,
            identity_mac_sha256=authenticator.sign(
                "projection-identity", identity.identity_commitment_sha256
            ),
        )
        for identity in _ordered(materialization.identities)
    )
    root = _digest(
        [
            {
                "identity_commitment_sha256": item.identity_commitment_sha256,
                "identity_sha256": item.identity_sha256,
                "kind": item.identity.kind,
                "ordinal": ordinal,
            }
            for ordinal, item in enumerate(authenticated)
        ]
    )
    summary_payload = {
        "aggregate_id": binding.aggregate_id,
        "aggregate_type": binding.aggregate_type,
        "aggregate_version": binding.aggregate_version,
        "context_sha256": binding.context_sha256,
        "identity_count": len(authenticated),
        "lane": binding.lane,
        "lineage_root_sha256": binding.lineage_root_sha256,
        "memory_scope_id": binding.memory_scope_id,
        "ordered_identity_root_sha256": root,
        "operation": operation,
        "outbox_event_commitment_sha256": binding.outbox_event_commitment_sha256,
        "outbox_id": binding.outbox_id,
        "persisted_at": effective_persisted_at.isoformat(),
        "provider_completed_at": materialization.completed_at.isoformat(),
        "schema": "memory_projection_result_receipt/v1",
        "run_id_sha256": binding.run_id_sha256,
        "result_state": result_state,
        "space_id": binding.space_id,
        "target_authority_sha256": binding.target_authority_sha256,
        "thread_id": binding.thread_id,
        "worker_authority_sha256": binding.worker_authority_sha256,
    }
    receipt_sha256 = _digest(summary_payload)
    return ProjectionResultReceipt(
        binding=binding,
        operation=operation,
        result_state=result_state,
        identities=authenticated,
        ordered_identity_root_sha256=root,
        provider_completed_at=materialization.completed_at,
        persisted_at=effective_persisted_at,
        receipt_sha256=receipt_sha256,
        receipt_mac_sha256=authenticator.sign("projection-receipt", receipt_sha256),
    )


def verify_projection_result_receipt(
    receipt: ProjectionResultReceipt,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    materialization = ProjectionMaterialization(
        projection_key_sha256=receipt.binding.projection_key_sha256,
        identities=tuple(item.identity for item in receipt.identities),
        completed_at=receipt.provider_completed_at,
    )
    expected = build_projection_result_receipt(
        binding=receipt.binding,
        materialization=materialization,
        authenticator=authenticator,
        persisted_at=receipt.persisted_at,
        operation=receipt.operation,
        result_state=receipt.result_state,
    )
    if expected != receipt or not authenticator.verify(
        "projection-receipt", receipt.receipt_sha256, receipt.receipt_mac_sha256
    ):
        raise ProjectionReceiptError("projection_receipt.authentication_invalid")


def _validate_expected_identities(
    binding: ProjectionJobBinding,
    identities: tuple[ProjectionTargetIdentity, ...],
) -> None:
    if not identities:
        raise ProjectionReceiptError("projection_receipt.expected_identities_empty")
    if binding.lane == "qdrant" and any(
        identity.kind != "qdrant_point_id" for identity in identities
    ):
        raise ProjectionReceiptError("projection_receipt.identity_lane_invalid")
    if binding.lane == "graphiti" and any(
        not identity.kind.startswith("graphiti_") for identity in identities
    ):
        raise ProjectionReceiptError("projection_receipt.identity_lane_invalid")
    _validate_observed_identities(binding, identities)
    keys = tuple((item.kind, item.identity_sha256) for item in identities)
    if len(set(keys)) != len(keys):
        raise ProjectionReceiptError("projection_receipt.expected_identity_duplicate")


def _validate_observed_identities(
    binding: ProjectionJobBinding,
    identities: tuple[ProjectionTargetIdentity, ...],
) -> None:
    for identity in identities:
        if (
            identity.lineage_root_sha256 != binding.lineage_root_sha256
            or identity.target_authority_sha256 != binding.target_authority_sha256
        ):
            raise ProjectionReceiptError("projection_receipt.readback_foreign")


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _ordered(
    identities: tuple[ProjectionTargetIdentity, ...],
) -> tuple[ProjectionTargetIdentity, ...]:
    return tuple(sorted(identities, key=lambda value: (value.kind, value.identity_sha256)))


__all__ = (
    "AuthenticatedProjectionIdentity",
    "ProjectionReceiptAuthenticator",
    "ProjectionResultReceipt",
    "build_projection_result_receipt",
    "ensure_projection_and_readback",
    "ensure_projection_deleted_and_readback",
    "verify_projection_result_receipt",
)
