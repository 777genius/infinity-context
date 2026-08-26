"""Durable strict-admin idempotency receipts for Retrieval profile operations."""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime

from infinity_context_core.features.context_building.public import CanonicalProjectionItem
from sqlalchemy import text

from infinity_context_adapters.postgres.locator_profile_mapping import (
    eligible_value as _eligible_value,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    projection_item as _projection_item,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    require_building as _require_building,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileOperatorOperationRow,
    MemoryLocatorProfileOperatorRebuildRow,
    MemoryLocatorProfileOperatorReceiptRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileRow,
)


class PostgresRetrievalProfileOperatorReceiptMixin:
    @asynccontextmanager
    async def operator_operation_lock(self, idempotency_key: str):
        """Serialize one idempotency key across processes until its receipt exists."""

        async with self.sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"retrieval-profile-operator:{idempotency_key}"},
            )
            yield

    async def operator_receipt(
        self, *, idempotency_key: str, request_fingerprint: str
    ) -> dict[str, object] | None:
        """Load an exact result or reject reuse of a key for different input."""

        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileOperatorReceiptRow, idempotency_key)
            if row is None:
                return None
            if row.request_fingerprint != request_fingerprint:
                raise RuntimeError("retrieval_profile_idempotency_conflict")
            return dict(row.result_json)

    async def reserve_operator_operation(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str,
        profile_id: str,
        now: datetime,
    ) -> None:
        """Persist key ownership across any number of in-progress responses."""

        async with self.sessions() as session, session.begin():
            row = await session.get(
                MemoryLocatorProfileOperatorOperationRow,
                idempotency_key,
                with_for_update=True,
            )
            if row is not None:
                if (
                    row.request_fingerprint != request_fingerprint
                    or row.operation != operation
                    or row.profile_id != profile_id
                ):
                    raise RuntimeError("retrieval_profile_idempotency_conflict")
                return
            session.add(
                MemoryLocatorProfileOperatorOperationRow(
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    operation=operation,
                    profile_id=profile_id,
                    created_at=now,
                )
            )

    async def record_operator_receipt(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str,
        profile_id: str,
        result: dict[str, object],
        now: datetime,
    ) -> dict[str, object]:
        """Append one durable exact-result snapshot, accepting an exact replay."""

        identity = _receipt_identity(result)
        async with self.sessions() as session, session.begin():
            row = await session.get(
                MemoryLocatorProfileOperatorReceiptRow,
                idempotency_key,
                with_for_update=True,
            )
            if row is not None:
                if row.request_fingerprint != request_fingerprint:
                    raise RuntimeError("retrieval_profile_idempotency_conflict")
                if dict(row.result_json) != result:
                    raise RuntimeError("retrieval_profile_idempotency_result_drift")
                return dict(row.result_json)
            operation_row = await session.get(
                MemoryLocatorProfileOperatorOperationRow,
                idempotency_key,
                with_for_update=True,
            )
            if (
                operation_row is not None
                and operation_row.request_fingerprint != request_fingerprint
            ):
                raise RuntimeError("retrieval_profile_idempotency_conflict")
            session.add(
                MemoryLocatorProfileOperatorReceiptRow(
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    operation=operation,
                    profile_id=profile_id,
                    result_json=dict(result),
                    runtime_instance_id=identity["runtime_instance_id"],
                    runtime_generation=identity["runtime_generation"],
                    launch_identity_sha256=identity["launch_identity_sha256"],
                    release_identity_sha256=identity["release_identity_sha256"],
                    lifecycle_identity_sha256=identity["lifecycle_identity_sha256"],
                    created_at=now,
                )
            )
            if operation_row is not None:
                await session.delete(operation_row)
        return dict(result)

    async def operator_rebuild_plan(
        self, *, idempotency_key: str, request_fingerprint: str
    ) -> dict[str, object] | None:
        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileOperatorRebuildRow, idempotency_key)
            if row is None:
                return None
            if row.request_fingerprint != request_fingerprint:
                raise RuntimeError("retrieval_profile_idempotency_conflict")
            return dict(row.plan_json)

    async def prepare_operator_rebuild(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        profile_id: str,
        plan: dict[str, object],
        now: datetime,
    ) -> dict[str, object]:
        async with self.sessions() as session, session.begin():
            row = await session.get(
                MemoryLocatorProfileOperatorRebuildRow,
                idempotency_key,
                with_for_update=True,
            )
            if row is not None:
                if row.request_fingerprint != request_fingerprint:
                    raise RuntimeError("retrieval_profile_idempotency_conflict")
                if dict(row.plan_json) != plan:
                    raise RuntimeError("retrieval_profile_idempotency_result_drift")
                return dict(row.plan_json)
            session.add(
                MemoryLocatorProfileOperatorRebuildRow(
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    profile_id=profile_id,
                    plan_json=dict(plan),
                    created_at=now,
                )
            )
        return dict(plan)

    async def commit_operator_rebuild(
        self,
        profile_id: str,
        items: tuple[CanonicalProjectionItem, ...],
        *,
        idempotency_key: str,
        request_fingerprint: str,
        previous_cursor: str | None,
        cursor: str | None,
        watermark: int,
        complete: bool,
        result: dict[str, object],
        now: datetime,
        crash_after_checkpoint=None,
    ) -> dict[str, object]:
        """Atomically commit page receipts/checkpoint and its exact API response."""

        identity = _receipt_identity(result)
        async with self.sessions() as session, session.begin():
            maintenance = await session.get(
                MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True
            )
            if maintenance is None or maintenance.active:
                raise RuntimeError("retrieval_profile_maintenance_active")
            await session.execute(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton = TRUE FOR UPDATE"
                )
            )
            journal = await session.get(
                MemoryLocatorProfileOperatorRebuildRow,
                idempotency_key,
                with_for_update=True,
            )
            if journal is None or journal.request_fingerprint != request_fingerprint:
                raise RuntimeError("retrieval_profile_rebuild_journal_missing")
            if dict(journal.plan_json).get("result") != result:
                raise RuntimeError("retrieval_profile_idempotency_result_drift")
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            _require_building(profile)
            if profile.backfill_cursor != previous_cursor:
                raise RuntimeError("retrieval_profile_backfill_cursor_raced")
            await self._record_operator_projection_rows(
                session, profile_id, items, projected_at=now
            )
            profile.backfill_cursor = cursor
            profile.canonical_watermark = max(profile.canonical_watermark, watermark)
            profile.backfill_complete = complete
            profile.backfill_updated_at = now
            if complete:
                await self._refresh_attestation(session, profile)
            if crash_after_checkpoint is not None:
                crash_after_checkpoint()
            session.add(
                MemoryLocatorProfileOperatorReceiptRow(
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    operation="rebuild",
                    profile_id=profile_id,
                    result_json=dict(result),
                    runtime_instance_id=identity["runtime_instance_id"],
                    runtime_generation=identity["runtime_generation"],
                    launch_identity_sha256=identity["launch_identity_sha256"],
                    release_identity_sha256=identity["release_identity_sha256"],
                    lifecycle_identity_sha256=identity["lifecycle_identity_sha256"],
                    created_at=now,
                )
            )
            operation_row = await session.get(
                MemoryLocatorProfileOperatorOperationRow,
                idempotency_key,
                with_for_update=True,
            )
            if operation_row is not None:
                if operation_row.request_fingerprint != request_fingerprint:
                    raise RuntimeError("retrieval_profile_idempotency_conflict")
                await session.delete(operation_row)
            await session.delete(journal)
        return dict(result)

    async def _record_operator_projection_rows(
        self, session, profile_id: str, items, *, projected_at: datetime
    ) -> None:
        for item in items:
            canonical = await session.get(
                MemoryChunkRow, item.canonical_identity, with_for_update=True
            )
            if canonical is None or not all(_eligible_value(canonical)):
                raise RuntimeError("retrieval_profile_stale_projection_write")
            current = _projection_item(canonical)
            if (
                current.canonical_version != item.canonical_version
                or current.canonical_watermark != item.canonical_watermark
                or current.payload_digest != item.payload_digest
            ):
                raise RuntimeError("retrieval_profile_stale_projection_write")
            receipt = await session.get(
                MemoryLocatorProfileProjectionReceiptRow,
                (profile_id, item.canonical_identity),
            )
            if receipt is None:
                session.add(
                    MemoryLocatorProfileProjectionReceiptRow(
                        profile_id=profile_id,
                        chunk_id=item.canonical_identity,
                        canonical_version=item.canonical_version,
                        canonical_watermark=item.canonical_watermark,
                        payload_digest=item.payload_digest,
                        projected_at=projected_at,
                    )
                )
            elif receipt.canonical_version > item.canonical_version:
                raise RuntimeError("retrieval_profile_stale_projection_write")
            elif (
                receipt.canonical_version == item.canonical_version
                and receipt.payload_digest != item.payload_digest
            ):
                raise RuntimeError("retrieval_profile_projection_digest_drift")
            else:
                receipt.canonical_version = item.canonical_version
                receipt.canonical_watermark = item.canonical_watermark
                receipt.payload_digest = item.payload_digest
                receipt.projected_at = projected_at


def _receipt_identity(result: dict[str, object]) -> dict[str, str]:
    value = result.get("runtime_trust_provenance")
    if not isinstance(value, dict) or value.get("schema_version") != (
        "retrieval-lifecycle-proof-identity.v1"
    ):
        raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_required")
    process = value.get("process_identity")
    release = value.get("installed_release_identity")
    required = {
        "runtime_instance_id": value.get("runtime_instance_id"),
        "runtime_generation": value.get("runtime_generation"),
        "launch_identity_sha256": value.get("launch_identity_sha256"),
        "release_identity_sha256": value.get("installed_release_identity_sha256"),
        "lifecycle_identity_sha256": value.get("receipt_identity_sha256"),
    }
    if not isinstance(process, dict) or not isinstance(release, dict):
        raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_invalid")
    for name, candidate in required.items():
        maximum = 120 if name in {"runtime_instance_id", "runtime_generation"} else 64
        if not isinstance(candidate, str) or not candidate or len(candidate) > maximum:
            raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_invalid")
        if maximum == 64 and (
            len(candidate) != 64
            or any(character not in "0123456789abcdef" for character in candidate)
        ):
            raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_invalid")
    canonical = dict(value)
    observed_identity_digest = canonical.pop("receipt_identity_sha256", None)
    recomputed = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if observed_identity_digest != recomputed:
        raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_invalid")
    release_digest = hashlib.sha256(
        json.dumps(
            {"release": release, "schema": "infinity-context.release-identity.v1"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if required["release_identity_sha256"] != release_digest:
        raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_invalid")
    return required  # type: ignore[return-value]


__all__ = ("PostgresRetrievalProfileOperatorReceiptMixin",)
