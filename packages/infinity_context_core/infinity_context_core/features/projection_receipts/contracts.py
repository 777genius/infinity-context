"""Provider-neutral contracts for exact projection-result readback."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

_SHA256 = re.compile(r"[0-9a-f]{64}")
PROJECTION_IDENTITY_KINDS = frozenset(
    {
        "qdrant_point_id",
        "graphiti_group_id",
        "graphiti_group_name",
        "graphiti_episode_uuid",
        "graphiti_episode_name",
        "graphiti_node_uuid",
        "graphiti_node_name",
        "graphiti_relation_uuid",
        "graphiti_relation_name",
    }
)


class ProjectionReceiptError(RuntimeError):
    """Fail-closed projection receipt error with a stable diagnostic code."""

    def __init__(self, diagnostic_code: str) -> None:
        super().__init__(diagnostic_code)
        self.diagnostic_code = diagnostic_code


@dataclass(frozen=True)
class ProjectionJobBinding:
    outbox_id: int
    run_id_sha256: str
    context_sha256: str
    lane: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int | None
    target_authority_sha256: str
    worker_authority_sha256: str
    lineage_root_sha256: str
    outbox_event_commitment_sha256: str

    def __post_init__(self) -> None:
        if self.outbox_id <= 0:
            raise ProjectionReceiptError("projection_receipt.outbox_id_invalid")
        for value in (
            self.run_id_sha256,
            self.context_sha256,
            self.target_authority_sha256,
            self.worker_authority_sha256,
            self.lineage_root_sha256,
            self.outbox_event_commitment_sha256,
        ):
            if _SHA256.fullmatch(value) is None:
                raise ProjectionReceiptError("projection_receipt.binding_digest_invalid")
        for value in (
            self.lane,
            self.space_id,
            self.memory_scope_id,
            self.aggregate_type,
            self.aggregate_id,
        ):
            if not value:
                raise ProjectionReceiptError("projection_receipt.binding_value_missing")
        if self.aggregate_version is not None and self.aggregate_version <= 0:
            raise ProjectionReceiptError("projection_receipt.aggregate_version_invalid")
        if self.lane not in {"qdrant", "graphiti"}:
            raise ProjectionReceiptError("projection_receipt.lane_invalid")

    @property
    def projection_key_sha256(self) -> str:
        return _digest(
            {
                "aggregate_id": self.aggregate_id,
                "aggregate_type": self.aggregate_type,
                "aggregate_version": self.aggregate_version,
                "context_sha256": self.context_sha256,
                "lane": self.lane,
                "lineage_root_sha256": self.lineage_root_sha256,
                "memory_scope_id": self.memory_scope_id,
                "outbox_event_commitment_sha256": self.outbox_event_commitment_sha256,
                "run_id_sha256": self.run_id_sha256,
                "space_id": self.space_id,
                "target_authority_sha256": self.target_authority_sha256,
                "thread_id": self.thread_id,
            }
        )


@dataclass(frozen=True)
class ProjectionTargetIdentity:
    kind: str
    canonical_source_id: str
    physical_identity: str
    lineage_root_sha256: str
    target_authority_sha256: str = ""

    def __post_init__(self) -> None:
        if self.kind not in PROJECTION_IDENTITY_KINDS:
            raise ProjectionReceiptError("projection_receipt.identity_kind_invalid")
        if not self.canonical_source_id or not self.physical_identity:
            raise ProjectionReceiptError("projection_receipt.identity_value_missing")
        if _SHA256.fullmatch(self.lineage_root_sha256) is None:
            raise ProjectionReceiptError("projection_receipt.identity_lineage_invalid")
        if _SHA256.fullmatch(self.target_authority_sha256) is None:
            raise ProjectionReceiptError("projection_receipt.identity_target_invalid")

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(
            f"memory_projection_physical_identity/v1\0{self.kind}\0{self.physical_identity}".encode()
        ).hexdigest()

    @property
    def identity_commitment_sha256(self) -> str:
        return _digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "canonical_source_id": self.canonical_source_id,
            "lineage_root_sha256": self.lineage_root_sha256,
            "physical_identity": self.physical_identity,
            "schema": "memory_projection_target_identity/v1",
            "target_authority_sha256": self.target_authority_sha256,
        }


@dataclass(frozen=True)
class ProjectionMaterialization:
    projection_key_sha256: str
    identities: tuple[ProjectionTargetIdentity, ...]
    completed_at: datetime


class ProjectionReadbackPort(Protocol):
    async def read_exact(
        self, binding: ProjectionJobBinding
    ) -> tuple[ProjectionMaterialization, ...]: ...

    async def upsert_exact(
        self,
        binding: ProjectionJobBinding,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> None: ...

    async def delete_exact(
        self,
        binding: ProjectionJobBinding,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> datetime: ...


def projection_outbox_event_commitment(
    *,
    message_key: str | None,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int | None,
    payload: dict[str, object],
    created_at: str,
) -> str:
    return _digest(
        {
            "schema": "memory_projection_outbox_event/v1",
            "message_key": message_key,
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "aggregate_version": aggregate_version,
            "payload": payload,
            "created_at": created_at,
        }
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "PROJECTION_IDENTITY_KINDS",
    "ProjectionJobBinding",
    "ProjectionMaterialization",
    "ProjectionReadbackPort",
    "ProjectionReceiptError",
    "ProjectionTargetIdentity",
    "projection_outbox_event_commitment",
)
