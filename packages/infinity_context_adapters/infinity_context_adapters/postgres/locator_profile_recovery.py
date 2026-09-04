"""Exact, auditable operator recovery for abandoned Retrieval fences."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta

from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RuntimeFenceOwner,
)
from sqlalchemy import func, select, text

from infinity_context_adapters.postgres.locator_profile_tombstone_replay import (
    request_tombstone_replay,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileQueryRow,
    MemoryLocatorProfileRecoveryReceiptRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProviderReconciliationReceiptRow,
    MemoryLocatorRuntimeIncarnationRow,
)
from infinity_context_adapters.postgres.runtime_supervisor import RuntimeDeathProof


class PostgresRetrievalProfileRecoveryMixin:
    """Release one exact stale owner only while the durable service is quiescent."""

    async def begin_maintenance(self, *, reason: str) -> int:
        _normalized(reason, "reason", 10, 500)
        async with self.sessions() as session, session.begin():
            row = await session.get(
                MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True
            )
            if row is None:
                raise RuntimeError("retrieval_profile_maintenance_fence_missing")
            if row.active:
                return int(row.fence_generation)
            now = await _database_now(session)
            row.fence_generation += 1
            row.active = True
            row.reason = reason
            row.changed_at = now
            return int(row.fence_generation)

    async def maintenance_evidence_epoch(self, maintenance_generation: int) -> int:
        async with self.sessions() as session, session.begin():
            await _active_maintenance(session, maintenance_generation)
            value = await session.scalar(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton=TRUE"
                )
            )
            if value is None:
                raise RuntimeError("retrieval_profile_evidence_version_missing")
            return int(value)

    async def complete_maintenance(self, maintenance_generation: int) -> None:
        async with self.sessions() as session, session.begin():
            maintenance = await _active_maintenance(session, maintenance_generation)
            unacknowledged = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorRuntimeIncarnationRow)
                    .where(
                        MemoryLocatorRuntimeIncarnationRow.acknowledged_generation
                        < maintenance_generation,
                        MemoryLocatorRuntimeIncarnationRow.sealed_dead_generation.is_(None),
                        MemoryLocatorRuntimeIncarnationRow.retired_at.is_(None),
                    )
                )
                or 0
            )
            fences = int(
                await session.scalar(select(func.count()).select_from(MemoryLocatorProfileQueryRow))
                or 0
            ) + int(
                await session.scalar(
                    select(func.count()).select_from(MemoryLocatorProfileProviderMutationRow)
                )
                or 0
            )
            if unacknowledged or fences:
                raise RuntimeError("retrieval_profile_maintenance_not_drained")
            maintenance.active = False
            maintenance.reason = None
            maintenance.changed_at = await _database_now(session)

    async def acknowledge_maintenance(
        self, *, owner_instance_id: str, owner_generation: str, maintenance_generation: int
    ) -> None:
        async with self.sessions() as session, session.begin():
            maintenance = await _active_maintenance(session, maintenance_generation)
            incarnation = await session.get(
                MemoryLocatorRuntimeIncarnationRow,
                (owner_instance_id, owner_generation),
                with_for_update=True,
            )
            if incarnation is None:
                raise RuntimeError("retrieval_profile_runtime_incarnation_missing")
            if incarnation.retired_at is not None:
                raise RuntimeError("retrieval_profile_runtime_incarnation_retired")
            queries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileQueryRow)
                    .where(
                        MemoryLocatorProfileQueryRow.owner_instance_id == owner_instance_id,
                        MemoryLocatorProfileQueryRow.owner_generation == owner_generation,
                    )
                )
                or 0
            )
            mutations = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(
                        MemoryLocatorProfileProviderMutationRow.owner_instance_id
                        == owner_instance_id,
                        MemoryLocatorProfileProviderMutationRow.owner_generation
                        == owner_generation,
                    )
                )
                or 0
            )
            if queries or mutations:
                raise RuntimeError("retrieval_profile_runtime_not_drained")
            incarnation.acknowledged_generation = maintenance.fence_generation
            incarnation.last_seen_at = await _database_now(session)

    async def seal_dead_incarnation(
        self,
        *,
        proof: RuntimeDeathProof,
    ) -> str:
        if not isinstance(proof, RuntimeDeathProof):
            raise TypeError("Recovery requires a supervisor-produced RuntimeDeathProof")
        _validate_death_proof(proof)
        async with self.sessions() as session, session.begin():
            maintenance = await _active_maintenance(session, proof.maintenance_generation)
            incarnation = await session.get(
                MemoryLocatorRuntimeIncarnationRow,
                (proof.instance_id, proof.generation),
                with_for_update=True,
            )
            if incarnation is None:
                raise RuntimeError("retrieval_profile_runtime_incarnation_missing")
            if incarnation.retired_at is not None:
                raise RuntimeError("retrieval_profile_runtime_incarnation_retired")
            if (
                proof.supervisor_key_id != incarnation.supervisor_key_id
                or proof.trust_root_sha256 != incarnation.trust_root_sha256
                or proof.trust_registry_generation != incarnation.trust_registry_generation
                or proof.launch_token != incarnation.launch_token
                or proof.process_pid != incarnation.process_pid
                or proof.process_birth_identity != incarnation.process_birth_identity
                or proof.executable_identity != incarnation.executable_identity
                or proof.executable_sha256 != incarnation.executable_sha256
                or proof.installed_release.service_revision != incarnation.release_revision
                or proof.installed_release.source_tree_digest_sha256
                != incarnation.release_source_tree_sha256
                or proof.installed_release.installed_distribution_digest_sha256
                != incarnation.release_installed_distribution_sha256
                or proof.installed_release.runtime_modules_digest_sha256
                != incarnation.release_runtime_modules_sha256
                or proof.installed_release.digest() != incarnation.release_identity_sha256
                or proof.exited_at < incarnation.registered_at
            ):
                raise RuntimeError("retrieval_profile_dead_proof_scope_invalid")
            now = await _database_now(session)
            if proof.exited_at > now + timedelta(seconds=5):
                raise RuntimeError("retrieval_profile_dead_proof_scope_invalid")
            if self.supervisor_trust is None:
                raise RuntimeError("retrieval_profile_supervisor_trust_required")
            self.supervisor_trust.verify_death_proof(proof, now=now)
            try:
                signature = base64.b64decode(proof.signature, validate=True)
            except ValueError as exc:
                raise RuntimeError("retrieval_profile_dead_proof_invalid") from exc
            proof_digest = hashlib.sha256(proof.payload() + signature).hexdigest()
            if incarnation.sealed_dead_generation is not None:
                if (
                    incarnation.sealed_dead_generation != proof.maintenance_generation
                    or incarnation.sealed_dead_proof_id != proof.proof_id
                    or incarnation.sealed_dead_proof_sha256 != proof_digest
                ):
                    raise RuntimeError("retrieval_profile_dead_proof_conflict")
                return proof_digest
            incarnation.sealed_dead_generation = maintenance.fence_generation
            incarnation.sealed_dead_proof_id = proof.proof_id
            incarnation.sealed_dead_proof_sha256 = proof_digest
            incarnation.sealed_dead_authority = proof.supervisor_key_id
            incarnation.sealed_dead_at = now
            return proof_digest

    async def _record_provider_reconciliation_observation(
        self,
        *,
        receipt_id: str,
        profile_id: str,
        profile_generation: str,
        collection_name: str,
        maintenance_generation: int,
        evidence_epoch: int,
        operation_id: str,
        owner_instance_id: str,
        owner_generation: str,
        mutation_epoch: int,
        stale_deadline: datetime,
        observed_count: int,
        observed_digest: str,
        provider_state: str,
        observed_at: datetime,
    ) -> str:
        """Private sink invoked only by a concrete provider observation capability."""
        values = (
            receipt_id,
            profile_id,
            profile_generation,
            collection_name,
            operation_id,
            owner_instance_id,
            owner_generation,
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Provider reconciliation receipt identity is invalid")
        if provider_state not in {"present", "absent"} or observed_count < 0:
            raise ValueError("Provider reconciliation observed state is invalid")
        if (
            not isinstance(mutation_epoch, int)
            or isinstance(mutation_epoch, bool)
            or mutation_epoch < 1
            or not isinstance(maintenance_generation, int)
            or maintenance_generation < 1
            or not isinstance(evidence_epoch, int)
            or evidence_epoch < 0
            or stale_deadline.utcoffset() is None
            or observed_at.utcoffset() is None
        ):
            raise ValueError("Provider reconciliation receipt scope is invalid")
        if len(observed_digest) != 64 or any(c not in "0123456789abcdef" for c in observed_digest):
            raise ValueError("Provider reconciliation digest is invalid")
        if provider_state == "absent" and (
            observed_count != 0 or observed_digest != hashlib.sha256(b"").hexdigest()
        ):
            raise ValueError("Absent provider reconciliation evidence is invalid")
        payload = {
            "schema": "retrieval-provider-reconciliation.v3",
            "receipt_id": receipt_id,
            "profile_id": profile_id,
            "profile_generation": profile_generation,
            "collection_name": collection_name,
            "maintenance_generation": maintenance_generation,
            "evidence_epoch": evidence_epoch,
            "operation_id": operation_id,
            "owner_instance_id": owner_instance_id,
            "owner_generation": owner_generation,
            "mutation_epoch": mutation_epoch,
            "stale_deadline": stale_deadline.isoformat(),
            "observed_count": observed_count,
            "observed_digest": observed_digest,
            "provider_state": provider_state,
            "observed_at": observed_at.isoformat(),
        }
        async with self.sessions() as session, session.begin():
            await _active_maintenance(session, maintenance_generation)
            incarnation = await session.get(
                MemoryLocatorRuntimeIncarnationRow,
                (owner_instance_id, owner_generation),
            )
            if (
                incarnation is None
                or incarnation.sealed_dead_proof_id is None
                or incarnation.sealed_dead_proof_sha256 is None
            ):
                raise RuntimeError("retrieval_profile_recovery_dead_owner_proof_required")
            payload["lifecycle_identity_sha256"] = _sealed_lifecycle_identity_sha256(incarnation)
            payload["launch_identity_sha256"] = incarnation.launch_identity_sha256
            payload["release_identity_sha256"] = incarnation.release_identity_sha256
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            existing = await session.get(MemoryLocatorProviderReconciliationReceiptRow, receipt_id)
            if existing is not None:
                if existing.receipt_sha256 != digest:
                    raise RuntimeError("retrieval_profile_provider_receipt_conflict")
                return digest
            session.add(
                MemoryLocatorProviderReconciliationReceiptRow(
                    receipt_id=receipt_id,
                    profile_id=profile_id,
                    profile_generation=profile_generation,
                    collection_name=collection_name,
                    maintenance_generation=maintenance_generation,
                    evidence_epoch=evidence_epoch,
                    operation_id=operation_id,
                    owner_instance_id=owner_instance_id,
                    owner_generation=owner_generation,
                    mutation_epoch=mutation_epoch,
                    stale_deadline=stale_deadline,
                    observed_count=observed_count,
                    observed_digest=observed_digest,
                    provider_state=provider_state,
                    observed_at=observed_at,
                    receipt_sha256=digest,
                    launch_identity_sha256=incarnation.launch_identity_sha256,
                    release_identity_sha256=incarnation.release_identity_sha256,
                    lifecycle_identity_sha256=payload["lifecycle_identity_sha256"],
                )
            )
            return digest

    async def recover_abandoned_fence(
        self,
        *,
        fence_kind: str,
        profile_id: str,
        operation_id: str,
        owner_instance_id: str,
        owner_generation: str,
        stale_deadline: datetime,
        reason: str,
        idempotency_key: str,
        activation_lease_id: str | None = None,
        mutation_epoch: int | None = None,
        provider_receipt_id: str | None = None,
        maintenance_generation: int,
    ) -> dict[str, object]:
        request = _validated_request(
            fence_kind=fence_kind,
            profile_id=profile_id,
            operation_id=operation_id,
            owner_instance_id=owner_instance_id,
            owner_generation=owner_generation,
            stale_deadline=stale_deadline,
            reason=reason,
            idempotency_key=idempotency_key,
            activation_lease_id=activation_lease_id,
            mutation_epoch=mutation_epoch,
            provider_receipt_id=provider_receipt_id,
            maintenance_generation=maintenance_generation,
        )
        fingerprint = _fingerprint(request)
        async with self.sessions() as session, session.begin():
            maintenance = await session.get(
                MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True
            )
            if maintenance is None:
                raise RuntimeError("retrieval_profile_maintenance_fence_missing")
            existing = await session.get(
                MemoryLocatorProfileRecoveryReceiptRow,
                idempotency_key,
                with_for_update=True,
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise RuntimeError("retrieval_profile_recovery_idempotency_conflict")
                return _receipt(existing, replayed=True)
            if not maintenance.active or maintenance.fence_generation != maintenance_generation:
                raise RuntimeError("retrieval_profile_maintenance_generation_invalid")
            await session.execute(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton = TRUE FOR UPDATE"
                )
            )

            incarnation = await session.get(
                MemoryLocatorRuntimeIncarnationRow,
                (owner_instance_id, owner_generation),
                with_for_update=True,
            )
            if (
                incarnation is None
                or incarnation.sealed_dead_generation != maintenance_generation
                or incarnation.sealed_dead_proof_sha256 is None
            ):
                raise RuntimeError("retrieval_profile_recovery_dead_owner_proof_required")
            unacknowledged = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorRuntimeIncarnationRow)
                    .where(
                        MemoryLocatorRuntimeIncarnationRow.acknowledged_generation
                        < maintenance_generation,
                        MemoryLocatorRuntimeIncarnationRow.sealed_dead_generation.is_(None),
                        MemoryLocatorRuntimeIncarnationRow.retired_at.is_(None),
                    )
                )
                or 0
            )
            if unacknowledged:
                raise RuntimeError("retrieval_profile_recovery_not_quiescent")
            now = await _database_now(session)

            if fence_kind == "reader":
                row = await session.get(
                    MemoryLocatorProfileQueryRow,
                    (profile_id, operation_id),
                    with_for_update=True,
                )
                if row is None or not _owner_matches(row, request):
                    raise RuntimeError("retrieval_profile_recovery_target_changed")
                if (
                    row.expires_at != stale_deadline
                    or row.activation_lease_id != activation_lease_id
                ):
                    raise RuntimeError("retrieval_profile_recovery_target_changed")
                await session.delete(row)
            else:
                row = await session.get(
                    MemoryLocatorProfileProviderMutationRow,
                    (profile_id, operation_id),
                    with_for_update=True,
                )
                if row is None or not _owner_matches(row, request):
                    raise RuntimeError("retrieval_profile_recovery_target_changed")
                if row.expires_at != stale_deadline or row.started_epoch != mutation_epoch:
                    raise RuntimeError("retrieval_profile_recovery_target_changed")
                profile = await session.get(
                    MemoryLocatorProfileRow, profile_id, with_for_update=True
                )
                if profile is None or profile.provider_mutation_epoch < mutation_epoch:
                    raise RuntimeError("retrieval_profile_recovery_target_changed")
                provider_receipt = await session.get(
                    MemoryLocatorProviderReconciliationReceiptRow,
                    provider_receipt_id,
                    with_for_update=True,
                )
                evidence_epoch = await session.scalar(
                    text(
                        "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                        "WHERE singleton = TRUE"
                    )
                )
                if (
                    provider_receipt is None
                    or provider_receipt.profile_id != profile_id
                    or provider_receipt.profile_generation != profile.generation
                    or provider_receipt.collection_name != profile.collection_name
                    or provider_receipt.maintenance_generation != maintenance_generation
                    or provider_receipt.evidence_epoch != evidence_epoch
                    or provider_receipt.operation_id != operation_id
                    or provider_receipt.owner_instance_id != owner_instance_id
                    or provider_receipt.owner_generation != owner_generation
                    or provider_receipt.launch_identity_sha256 != incarnation.launch_identity_sha256
                    or provider_receipt.release_identity_sha256
                    != incarnation.release_identity_sha256
                    or provider_receipt.lifecycle_identity_sha256
                    != _sealed_lifecycle_identity_sha256(incarnation)
                    or provider_receipt.mutation_epoch != mutation_epoch
                    or provider_receipt.stale_deadline != stale_deadline
                    or provider_receipt.consumed_by_recovery_key is not None
                ):
                    raise RuntimeError("retrieval_profile_provider_receipt_invalid")
                # Operator reconciliation resolves ambiguity; it never records the
                # abandoned provider call as successful. A fresh attestation is required.
                profile.provider_mutation_epoch += 1
                profile.reconciliation_drifted = True
                if profile.activation_lease_issued_at is not None:
                    profile.activation_lease_expires_at = max(
                        now,
                        profile.activation_lease_issued_at + timedelta(microseconds=1),
                    )
                await session.delete(row)
                provider_receipt.consumed_by_recovery_key = idempotency_key
                provider_receipt.consumed_at = now
                await request_tombstone_replay(
                    session,
                    profile_id=profile_id,
                    provider_mutation_epoch=int(profile.provider_mutation_epoch),
                    now=now,
                )

            receipt = MemoryLocatorProfileRecoveryReceiptRow(
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                fence_kind=fence_kind,
                profile_id=profile_id,
                operation_id=operation_id,
                owner_instance_id=owner_instance_id,
                owner_generation=owner_generation,
                lease_id=activation_lease_id,
                mutation_epoch=mutation_epoch,
                stale_deadline=stale_deadline,
                reason=reason,
                reconciliation_digest=(
                    provider_receipt.receipt_sha256 if fence_kind == "provider_mutation" else None
                ),
                provider_receipt_id=(
                    provider_receipt.receipt_id if fence_kind == "provider_mutation" else None
                ),
                maintenance_generation=maintenance.fence_generation,
                launch_identity_sha256=incarnation.launch_identity_sha256,
                sealed_dead_proof_id=incarnation.sealed_dead_proof_id,
                sealed_dead_proof_sha256=incarnation.sealed_dead_proof_sha256,
                release_identity_sha256=incarnation.release_identity_sha256,
                lifecycle_identity_sha256=_sealed_lifecycle_identity_sha256(incarnation),
                recovered_at=now,
            )
            session.add(receipt)
            await session.flush()
            remaining = int(
                await session.scalar(select(func.count()).select_from(MemoryLocatorProfileQueryRow))
                or 0
            ) + int(
                await session.scalar(
                    select(func.count()).select_from(MemoryLocatorProfileProviderMutationRow)
                )
                or 0
            )
            if remaining == 0:
                maintenance.active = False
                maintenance.reason = None
                maintenance.changed_at = now
            return _receipt(receipt)


def _validated_request(**values) -> dict[str, object]:
    if values["fence_kind"] not in {"reader", "provider_mutation"}:
        raise ValueError("Recovery fence_kind is unsupported")
    for name in (
        "profile_id",
        "operation_id",
        "owner_instance_id",
        "owner_generation",
        "idempotency_key",
    ):
        value = values[name]
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 120:
            raise ValueError(f"Recovery {name} is invalid")
    reason = values["reason"]
    if not isinstance(reason, str) or reason != reason.strip() or not 10 <= len(reason) <= 500:
        raise ValueError("Recovery reason must contain 10..500 normalized characters")
    deadline = values["stale_deadline"]
    if not isinstance(deadline, datetime) or deadline.utcoffset() is None:
        raise ValueError("Recovery stale_deadline must be timezone-aware")
    if values["fence_kind"] == "reader":
        if not isinstance(values["activation_lease_id"], str):
            raise ValueError("Reader recovery requires the exact activation lease")
        if values["mutation_epoch"] is not None or values["provider_receipt_id"] is not None:
            raise ValueError("Reader recovery cannot carry provider reconciliation")
    else:
        epoch = values["mutation_epoch"]
        receipt_id = values["provider_receipt_id"]
        if (
            not isinstance(epoch, int)
            or isinstance(epoch, bool)
            or epoch < 1
            or not isinstance(receipt_id, str)
            or not receipt_id
        ):
            raise ValueError("Provider recovery requires an exact epoch and provider receipt")
        if values["activation_lease_id"] is not None:
            raise ValueError("Provider recovery cannot carry a reader lease")
    return values


def _validate_death_proof(proof: RuntimeDeathProof) -> None:
    for name in (
        "proof_id",
        "instance_id",
        "generation",
        "supervisor_key_id",
        "trust_root_sha256",
        "launch_token",
        "process_birth_identity",
        "executable_identity",
        "exit_observation_id",
    ):
        value = getattr(proof, name)
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 120:
            raise ValueError(f"Runtime death proof {name} is invalid")
    if (
        not isinstance(proof.installed_release, InstalledReleaseIdentity)
        or not isinstance(proof.maintenance_generation, int)
        or isinstance(proof.maintenance_generation, bool)
        or proof.maintenance_generation < 1
        or not isinstance(proof.process_pid, int)
        or isinstance(proof.process_pid, bool)
        or proof.process_pid < 1
        or not isinstance(proof.trust_registry_generation, int)
        or isinstance(proof.trust_registry_generation, bool)
        or proof.trust_registry_generation < 1
        or not isinstance(proof.exit_code, int)
        or isinstance(proof.exit_code, bool)
        or not -255 <= proof.exit_code <= 255
        or not isinstance(proof.exited_at, datetime)
        or proof.exited_at.utcoffset() is None
        or not isinstance(proof.signature, str)
        or len(proof.signature) > 120
        or len(proof.executable_sha256) != 64
        or any(character not in "0123456789abcdef" for character in proof.executable_sha256)
        or len(proof.trust_root_sha256) != 64
        or any(character not in "0123456789abcdef" for character in proof.trust_root_sha256)
    ):
        raise ValueError("Runtime death proof fields are invalid")


async def _database_now(session) -> datetime:
    now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime):
        raise RuntimeError("retrieval_profile_recovery_clock_unavailable")
    return now


async def _active_maintenance(session, generation: int):
    row = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True)
    if row is None or not row.active or row.fence_generation != generation:
        raise RuntimeError("retrieval_profile_maintenance_generation_invalid")
    return row


def _normalized(value: str, name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or value != value.strip() or not minimum <= len(value) <= maximum:
        raise ValueError(f"Recovery {name} is invalid")
    return value


def _fingerprint(request: dict[str, object]) -> str:
    payload = dict(request)
    payload["stale_deadline"] = request["stale_deadline"].isoformat()  # type: ignore[union-attr]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _owner_matches(row, request: dict[str, object]) -> bool:
    return (
        row.owner_instance_id == request["owner_instance_id"]
        and row.owner_generation == request["owner_generation"]
    )


def _receipt(
    row: MemoryLocatorProfileRecoveryReceiptRow, *, replayed: bool = False
) -> dict[str, object]:
    return {
        "idempotency_key": row.idempotency_key,
        "fence_kind": row.fence_kind,
        "profile_id": row.profile_id,
        "operation_id": row.operation_id,
        "owner_instance_id": row.owner_instance_id,
        "owner_generation": row.owner_generation,
        "maintenance_generation": int(row.maintenance_generation),
        "launch_identity_sha256": row.launch_identity_sha256,
        "sealed_dead_proof_id": row.sealed_dead_proof_id,
        "sealed_dead_proof_sha256": row.sealed_dead_proof_sha256,
        "release_identity_sha256": row.release_identity_sha256,
        "lifecycle_identity_sha256": row.lifecycle_identity_sha256,
        "outcome": "released_for_fresh_attestation",
        "write_outcome": "idempotent_replay" if replayed else "applied",
        "recovered_at": row.recovered_at.isoformat(),
    }


def _sealed_lifecycle_identity_sha256(row: MemoryLocatorRuntimeIncarnationRow) -> str:
    owner = RuntimeFenceOwner(
        instance_id=row.instance_id,
        generation=row.generation,
        supervisor_key_id=row.supervisor_key_id,
        supervisor_public_key=row.supervisor_public_key,
        trust_root_sha256=row.trust_root_sha256,
        trust_registry_generation=int(row.trust_registry_generation),
        launch_token=row.launch_token,
        process_pid=int(row.process_pid),
        process_birth_identity=row.process_birth_identity,
        executable_identity=row.executable_identity,
        executable_sha256=row.executable_sha256,
        installed_release=InstalledReleaseIdentity(
            row.release_revision,
            row.release_source_tree_sha256,
            row.release_installed_distribution_sha256,
            row.release_runtime_modules_sha256,
        ),
        launch_signature="",
    )
    return owner.lifecycle_identity_sha256(
        sealed_proof_id=row.sealed_dead_proof_id,
        sealed_proof_sha256=row.sealed_dead_proof_sha256,
    )


__all__ = ("PostgresRetrievalProfileRecoveryMixin",)
