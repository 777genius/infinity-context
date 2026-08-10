"""Atomic Postgres persistence for authenticated projection receipts."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from infinity_context_core.features.projection_receipts import (
    AuthenticatedProjectionIdentity,
    ProjectionJobBinding,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    ProjectionResultReceipt,
    ProjectionTargetIdentity,
    projection_outbox_event_commitment,
    verify_projection_result_receipt,
)
from infinity_context_core.features.projection_receipts.context_authority_registration import (
    ContextAuthorityRegistration,
    context_authority_registration_sha256,
    register_context_authority_and_readback,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    digest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.benchmark_run_models import (
    MemoryComparisonBenchmarkRunRow,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryFactRow
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.projection_receipt_claim_repository import (
    ProjectionReceiptClaimRepositoryMixin,
)
from infinity_context_adapters.postgres.projection_receipt_lineage_validation import (
    validate_canonical_rows as _validate_canonical_rows,
)
from infinity_context_adapters.postgres.projection_receipt_lineage_validation import (
    validate_identity_source_mapping as _validate_identity_source_mapping,
)
from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryCleanupV3ContextAuthorityRow,
    MemoryProjectionReceiptClaimRow,
    MemoryProjectionReceiptIdentityLinkRow,
    MemoryProjectionResultReceiptRow,
    MemoryProjectionTargetIdentityRow,
)
from infinity_context_adapters.postgres.projection_receipt_payload_validation import (
    validate_production_payload as _validate_production_payload,
)


class PostgresProjectionReceiptRepository(ProjectionReceiptClaimRepositoryMixin):
    """Own the receipt/dictionary/link exact-replay transaction."""

    def __init__(
        self,
        session: AsyncSession,
        authenticator: ProjectionReceiptAuthenticator,
    ) -> None:
        self._session = session
        self._authenticator = authenticator

    async def register_context_authority(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        registered_at: datetime,
    ) -> bool:
        """Register one immutable, authenticated A2 context; return False on exact replay."""

        result = await register_context_authority_and_readback(
            self,
            context=context,
            authority=authority,
            authenticator=self._authenticator,
            registered_at=registered_at,
        )
        return result.created

    async def register_and_readback(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        registration_sha256: str,
        registration_mac_sha256: str,
        registered_at: datetime,
    ) -> ContextAuthorityRegistration:
        """Implement the narrow use-case port without exposing another mutation path."""

        if registered_at.tzinfo is None:
            raise ProjectionReceiptError("projection_receipt.context_registered_time_invalid")
        try:
            context.__post_init__()
            authority.__post_init__()
            terminal = digest(authority.terminal_commitment_sha256)
        except ManagedCleanupV3Error as exc:
            raise ProjectionReceiptError("projection_receipt.context_authority_invalid") from exc
        registry = await self._locked_registry(context.run_id_sha256)
        _validate_context_registry_binding(context, authority, registry)
        expected_registration = _context_registration_sha256(context, authority)
        if registration_sha256 != expected_registration or not self._authenticator.verify(
            "projection-context-authority",
            registration_sha256,
            registration_mac_sha256,
        ):
            raise ProjectionReceiptError("projection_receipt.context_authority_invalid")
        existing = await self._locked_context_authority(context.context_sha256)
        if existing is not None:
            stored_context, stored_authority = _validate_context_authority_row(
                existing, self._authenticator
            )
            if (
                existing.run_id_sha256 != context.run_id_sha256
                or existing.authority_terminal_sha256 != terminal
                or existing.context_json != context.payload()
                or existing.authority_json != authority.payload()
                or existing.registration_sha256 != registration_sha256
                or existing.registration_mac_sha256 != registration_mac_sha256
            ):
                raise ProjectionReceiptError("projection_receipt.context_authority_collision")
            return ContextAuthorityRegistration(
                context=stored_context,
                authority=stored_authority,
                registration_sha256=existing.registration_sha256,
                registration_mac_sha256=existing.registration_mac_sha256,
                registered_at=_aware_datetime(existing.registered_at),
                created=False,
            )
        row = MemoryCleanupV3ContextAuthorityRow(
            run_id_sha256=context.run_id_sha256,
            context_sha256=context.context_sha256,
            authority_terminal_sha256=terminal,
            context_json=context.payload(),
            authority_json=authority.payload(),
            registration_sha256=registration_sha256,
            registration_mac_sha256=registration_mac_sha256,
            registered_at=registered_at,
        )
        self._session.add(row)
        await self._session.flush()
        stored_context, stored_authority = _validate_context_authority_row(row, self._authenticator)
        return ContextAuthorityRegistration(
            context=stored_context,
            authority=stored_authority,
            registration_sha256=row.registration_sha256,
            registration_mac_sha256=row.registration_mac_sha256,
            registered_at=_aware_datetime(row.registered_at),
            created=True,
        )

    async def load_authenticated_receipt(
        self,
        *,
        binding: ProjectionJobBinding,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt | None:
        """Return an exact durable replay before any provider mutation."""

        existing = (
            await self._session.execute(
                select(MemoryProjectionResultReceiptRow)
                .where(MemoryProjectionResultReceiptRow.outbox_id == binding.outbox_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        receipt = await self._receipt_from_row(existing, binding)
        if receipt.operation != operation:
            raise ProjectionReceiptError("projection_receipt.replay_operation_divergent")
        observed_identities = tuple(item.identity for item in receipt.identities)
        ordered_expected = tuple(
            sorted(expected_identities, key=lambda item: (item.kind, item.identity_sha256))
        )
        if observed_identities != ordered_expected:
            raise ProjectionReceiptError("projection_receipt.replay_expected_divergent")
        verify_projection_result_receipt(receipt, self._authenticator)
        outbox = await self._locked_outbox(binding.outbox_id)
        registry = await self._locked_registry(binding.run_id_sha256)
        context_authority = await self._locked_context_authority(binding.context_sha256)
        if context_authority is None:
            raise ProjectionReceiptError("projection_receipt.context_authority_missing")
        canonical = await self._locked_canonical_aggregate(receipt)
        self._validate_canonical_lineage(outbox, registry, context_authority, canonical, receipt)
        await self._require_exact_replay(existing, receipt)
        if outbox.status != "done":
            raise ProjectionReceiptError("projection_receipt.receipt_without_done")
        return receipt

    async def _receipt_from_row(
        self,
        row: MemoryProjectionResultReceiptRow,
        binding: ProjectionJobBinding,
    ) -> ProjectionResultReceipt:
        stored_binding = ProjectionJobBinding(
            outbox_id=row.outbox_id,
            run_id_sha256=row.run_id_sha256,
            context_sha256=row.context_sha256,
            lane=row.lane,
            space_id=row.space_id,
            memory_scope_id=row.memory_scope_id,
            thread_id=row.thread_id,
            aggregate_type=row.aggregate_type,
            aggregate_id=row.aggregate_id,
            aggregate_version=row.aggregate_version,
            target_authority_sha256=row.target_authority_sha256,
            worker_authority_sha256=row.worker_authority_sha256,
            lineage_root_sha256=row.lineage_root_sha256,
            outbox_event_commitment_sha256=row.outbox_event_commitment_sha256,
        )
        if stored_binding != binding:
            raise ProjectionReceiptError("projection_receipt.replay_binding_divergent")
        links = list(
            (
                await self._session.execute(
                    select(MemoryProjectionReceiptIdentityLinkRow)
                    .where(MemoryProjectionReceiptIdentityLinkRow.outbox_id == row.outbox_id)
                    .order_by(MemoryProjectionReceiptIdentityLinkRow.ordinal)
                )
            ).scalars()
        )
        identities: list[AuthenticatedProjectionIdentity] = []
        for link in links:
            target = await self._session.get(
                MemoryProjectionTargetIdentityRow,
                (link.run_id_sha256, link.kind, link.identity_sha256),
            )
            if target is None:
                raise ProjectionReceiptError("projection_receipt.replay_identity_missing")
            identities.append(
                AuthenticatedProjectionIdentity(
                    identity=ProjectionTargetIdentity(
                        kind=target.kind,
                        canonical_source_id=target.canonical_source_id,
                        physical_identity=target.physical_identity,
                        lineage_root_sha256=target.lineage_root_sha256,
                        target_authority_sha256=target.target_authority_sha256,
                    ),
                    identity_sha256=target.identity_sha256,
                    identity_commitment_sha256=link.identity_commitment_sha256,
                    identity_mac_sha256=target.identity_mac_sha256,
                )
            )
        return ProjectionResultReceipt(
            binding=stored_binding,
            operation=row.operation,
            result_state=row.result_state,
            identities=tuple(identities),
            ordered_identity_root_sha256=row.ordered_identity_root_sha256,
            provider_completed_at=_aware_datetime(row.provider_completed_at),
            persisted_at=_aware_datetime(row.persisted_at),
            receipt_sha256=row.receipt_sha256,
            receipt_mac_sha256=row.receipt_mac_sha256,
        )

    async def persist_and_mark_done(
        self,
        receipt: ProjectionResultReceipt,
        *,
        claim_token: bytes | None = None,
        reconciliation: bool = False,
    ) -> bool:
        """Persist once and complete the locked outbox row; return False on exact replay."""

        verify_projection_result_receipt(receipt, self._authenticator)
        binding = receipt.binding
        outbox = await self._locked_outbox(binding.outbox_id)
        claim = await self._locked_claim(binding.outbox_id)
        valid_owner = (
            claim is not None
            and claim_token is not None
            and claim.state == "dispatch_started"
            and hmac.compare_digest(
                claim.claim_token_sha256, hashlib.sha256(claim_token).hexdigest()
            )
        )
        valid_reconciliation = (
            reconciliation
            and claim_token is None
            and claim is not None
            and claim.state == "dispatch_started"
        )
        if claim is not None and not (valid_owner or valid_reconciliation):
            raise ProjectionReceiptError("projection_receipt.claim_lost")
        if claim is None and claim_token is not None:
            raise ProjectionReceiptError("projection_receipt.claim_lost")
        registry = await self._locked_registry(binding.run_id_sha256)
        context_authority = await self._locked_context_authority(binding.context_sha256)
        if context_authority is None:
            raise ProjectionReceiptError("projection_receipt.context_authority_missing")
        canonical = await self._locked_canonical_aggregate(receipt)
        self._validate_canonical_lineage(outbox, registry, context_authority, canonical, receipt)
        existing = await self._session.get(MemoryProjectionResultReceiptRow, binding.outbox_id)
        if existing is not None:
            await self._require_exact_replay(existing, receipt)
            self._mark_done(outbox, receipt.persisted_at)
            if claim is not None:
                await self._session.delete(claim)
            return False
        if outbox.status == "done":
            raise ProjectionReceiptError("projection_receipt.done_without_receipt")

        for item in receipt.identities:
            await self._insert_or_compare_identity(receipt, item)
        self._session.add(_receipt_row(receipt))
        await self._session.flush()
        for ordinal, item in enumerate(receipt.identities):
            self._session.add(
                MemoryProjectionReceiptIdentityLinkRow(
                    outbox_id=binding.outbox_id,
                    run_id_sha256=binding.run_id_sha256,
                    kind=item.identity.kind,
                    identity_sha256=item.identity_sha256,
                    identity_commitment_sha256=item.identity_commitment_sha256,
                    ordinal=ordinal,
                )
            )
        await self._session.flush()
        self._mark_done(outbox, receipt.persisted_at)
        if claim is not None:
            await self._session.delete(claim)
        return True

    async def _locked_outbox(self, outbox_id: int) -> MemoryOutboxRow:
        row = (
            await self._session.execute(
                select(MemoryOutboxRow).where(MemoryOutboxRow.id == outbox_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProjectionReceiptError("projection_receipt.outbox_missing")
        return row

    async def _locked_claim(self, outbox_id: int) -> MemoryProjectionReceiptClaimRow | None:
        return (
            await self._session.execute(
                select(MemoryProjectionReceiptClaimRow)
                .where(MemoryProjectionReceiptClaimRow.outbox_id == outbox_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def _locked_registry(self, run_id_sha256: str) -> MemoryComparisonBenchmarkRunRow:
        row = (
            await self._session.execute(
                select(MemoryComparisonBenchmarkRunRow)
                .where(MemoryComparisonBenchmarkRunRow.run_id_sha256 == run_id_sha256)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProjectionReceiptError("projection_receipt.run_missing")
        return row

    async def _locked_context_authority(
        self, context_sha256: str
    ) -> MemoryCleanupV3ContextAuthorityRow | None:
        return (
            await self._session.execute(
                select(MemoryCleanupV3ContextAuthorityRow)
                .where(MemoryCleanupV3ContextAuthorityRow.context_sha256 == context_sha256)
                .with_for_update()
            )
        ).scalar_one_or_none()

    def _validate_canonical_lineage(
        self,
        outbox: MemoryOutboxRow,
        registry: MemoryComparisonBenchmarkRunRow,
        context_authority: MemoryCleanupV3ContextAuthorityRow,
        canonical: tuple[MemoryChunkRow, ...] | MemoryChunkRow | MemoryFactRow,
        receipt: ProjectionResultReceipt,
    ) -> None:
        binding = receipt.binding
        context, authority = _validate_context_authority_row(context_authority, self._authenticator)
        _validate_context_registry_binding(context, authority, registry)
        if outbox.status not in {"running", "done"}:
            raise ProjectionReceiptError("projection_receipt.outbox_not_running")
        if (
            outbox.aggregate_type != binding.aggregate_type
            or outbox.aggregate_id != binding.aggregate_id
            or outbox.aggregate_version != binding.aggregate_version
        ):
            raise ProjectionReceiptError("projection_receipt.outbox_lineage_divergent")
        if (
            receipt.operation == "upsert"
            and (
                registry.state != "active"
                or registry.projection_cleanup_state not in {"unsealed", "sealed"}
            )
        ) or (
            receipt.operation == "delete"
            and (
                registry.state != "cleanup_pending"
                or registry.projection_cleanup_state != "pending"
            )
        ):
            raise ProjectionReceiptError("projection_receipt.registry_state_divergent")
        if (
            registry.space_id != binding.space_id
            or binding.target_authority_sha256
            != (
                context.qdrant_authority_sha256
                if binding.lane == "qdrant"
                else context.graphiti_authority_sha256
            )
            or context.context_sha256 != binding.context_sha256
            or context.ingestion_root_sha256 != binding.lineage_root_sha256
            or self._authenticator.authority_sha256 != binding.worker_authority_sha256
        ):
            raise ProjectionReceiptError("projection_receipt.registry_lineage_divergent")
        expected_event = _expected_event(receipt)
        if (outbox.event_type, outbox.aggregate_type) != expected_event:
            raise ProjectionReceiptError("projection_receipt.outbox_event_divergent")
        if _outbox_event_commitment(outbox) != binding.outbox_event_commitment_sha256:
            raise ProjectionReceiptError("projection_receipt.outbox_commitment_divergent")
        _validate_production_payload(outbox, receipt)
        _validate_canonical_rows(canonical, receipt)
        _validate_identity_source_mapping(canonical, receipt)

    async def _locked_canonical_aggregate(
        self, receipt: ProjectionResultReceipt
    ) -> tuple[MemoryChunkRow, ...] | MemoryChunkRow | MemoryFactRow:
        binding = receipt.binding
        if receipt.operation == "delete" and binding.lane == "qdrant":
            chunk_ids = tuple(item.identity.canonical_source_id for item in receipt.identities)
            rows = tuple(
                (
                    await self._session.execute(
                        select(MemoryChunkRow)
                        .where(MemoryChunkRow.id.in_(chunk_ids))
                        .order_by(MemoryChunkRow.id)
                        .with_for_update()
                    )
                ).scalars()
            )
            if {row.id for row in rows} != set(chunk_ids):
                raise ProjectionReceiptError("projection_receipt.canonical_aggregate_missing")
            return rows
        model = MemoryChunkRow if binding.lane == "qdrant" else MemoryFactRow
        row = (
            await self._session.execute(
                select(model).where(model.id == binding.aggregate_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProjectionReceiptError("projection_receipt.canonical_aggregate_missing")
        return row

    async def _insert_or_compare_identity(self, receipt, item) -> None:
        key = (receipt.binding.run_id_sha256, item.identity.kind, item.identity_sha256)
        existing = await self._session.get(MemoryProjectionTargetIdentityRow, key)
        expected = _identity_values(receipt, item)
        if existing is None:
            self._session.add(MemoryProjectionTargetIdentityRow(**expected))
            await self._session.flush()
            return
        if any(
            not _values_equal(getattr(existing, name), value) for name, value in expected.items()
        ):
            raise ProjectionReceiptError("projection_receipt.identity_collision")

    async def _require_exact_replay(
        self,
        existing: MemoryProjectionResultReceiptRow,
        receipt: ProjectionResultReceipt,
    ) -> None:
        expected_receipt = _receipt_values(receipt)
        if any(
            not _values_equal(getattr(existing, name), value)
            for name, value in expected_receipt.items()
        ):
            raise ProjectionReceiptError("projection_receipt.replay_divergent")
        links = list(
            (
                await self._session.execute(
                    select(MemoryProjectionReceiptIdentityLinkRow)
                    .where(
                        MemoryProjectionReceiptIdentityLinkRow.outbox_id
                        == receipt.binding.outbox_id
                    )
                    .order_by(MemoryProjectionReceiptIdentityLinkRow.ordinal)
                )
            ).scalars()
        )
        expected_links = [
            (
                receipt.binding.run_id_sha256,
                item.identity.kind,
                item.identity_sha256,
                item.identity_commitment_sha256,
                ordinal,
            )
            for ordinal, item in enumerate(receipt.identities)
        ]
        observed_links = [
            (
                row.run_id_sha256,
                row.kind,
                row.identity_sha256,
                row.identity_commitment_sha256,
                row.ordinal,
            )
            for row in links
        ]
        if observed_links != expected_links:
            raise ProjectionReceiptError("projection_receipt.link_replay_divergent")
        for item in receipt.identities:
            await self._insert_or_compare_identity(receipt, item)

    @staticmethod
    def _mark_done(outbox: MemoryOutboxRow, completed_at: datetime) -> None:
        outbox.status = "done"
        outbox.last_safe_error = None
        outbox.last_safe_diagnostic_code = None
        outbox.updated_at = completed_at


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _outbox_event_commitment(outbox: MemoryOutboxRow) -> str:
    created_at = outbox.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return projection_outbox_event_commitment(
        message_key=outbox.message_key,
        event_type=outbox.event_type,
        aggregate_type=outbox.aggregate_type,
        aggregate_id=outbox.aggregate_id,
        aggregate_version=outbox.aggregate_version,
        payload=outbox.payload_json,
        created_at=created_at.isoformat(),
    )


def _receipt_values(receipt: ProjectionResultReceipt) -> dict[str, object]:
    binding = receipt.binding
    return {
        "outbox_id": binding.outbox_id,
        "run_id_sha256": binding.run_id_sha256,
        "context_sha256": binding.context_sha256,
        "lane": binding.lane,
        "operation": receipt.operation,
        "result_state": receipt.result_state,
        "space_id": binding.space_id,
        "memory_scope_id": binding.memory_scope_id,
        "thread_id": binding.thread_id,
        "aggregate_type": binding.aggregate_type,
        "aggregate_id": binding.aggregate_id,
        "aggregate_version": binding.aggregate_version,
        "target_authority_sha256": binding.target_authority_sha256,
        "worker_authority_sha256": binding.worker_authority_sha256,
        "outbox_event_commitment_sha256": binding.outbox_event_commitment_sha256,
        "identity_count": len(receipt.identities),
        "ordered_identity_root_sha256": receipt.ordered_identity_root_sha256,
        "lineage_root_sha256": binding.lineage_root_sha256,
        "provider_completed_at": receipt.provider_completed_at,
        "persisted_at": receipt.persisted_at,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_mac_sha256": receipt.receipt_mac_sha256,
    }


def _receipt_row(receipt: ProjectionResultReceipt) -> MemoryProjectionResultReceiptRow:
    return MemoryProjectionResultReceiptRow(**_receipt_values(receipt))


def _identity_values(receipt, item) -> dict[str, object]:
    identity = item.identity
    return {
        "run_id_sha256": receipt.binding.run_id_sha256,
        "kind": identity.kind,
        "identity_sha256": item.identity_sha256,
        "identity_commitment_sha256": item.identity_commitment_sha256,
        "canonical_source_id": identity.canonical_source_id,
        "physical_identity": identity.physical_identity,
        "lineage_root_sha256": identity.lineage_root_sha256,
        "target_authority_sha256": identity.target_authority_sha256,
        "identity_mac_sha256": item.identity_mac_sha256,
        "created_at": receipt.persisted_at,
    }


def _values_equal(left: object, right: object) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        normalized_left = left if left.tzinfo is not None else left.replace(tzinfo=UTC)
        normalized_right = right if right.tzinfo is not None else right.replace(tzinfo=UTC)
        return normalized_left == normalized_right
    return left == right


def _expected_event(receipt: ProjectionResultReceipt) -> tuple[str, str]:
    return {
        ("upsert", "qdrant"): ("vector.upsert_chunk", "chunk"),
        ("upsert", "graphiti"): ("graph.upsert_fact", "fact"),
        ("delete", "qdrant"): ("vector.delete_chunks", "benchmark_run"),
        ("delete", "graphiti"): ("graph.delete_fact", "benchmark_run"),
    }[(receipt.operation, receipt.binding.lane)]


def _context_registration_sha256(
    context: ManagedCleanupV3Context, authority: ManagedCleanupV3Authority
) -> str:
    return context_authority_registration_sha256(context, authority)


def _validate_context_authority_row(
    row: MemoryCleanupV3ContextAuthorityRow,
    authenticator: ProjectionReceiptAuthenticator,
) -> tuple[ManagedCleanupV3Context, ManagedCleanupV3Authority]:
    try:
        context = ManagedCleanupV3Context(**row.context_json)
        authority_values = dict(row.authority_json)
        authority_values["ordered_page_sha256"] = tuple(authority_values["ordered_page_sha256"])
        authority = ManagedCleanupV3Authority(**authority_values)
        context.__post_init__()
        authority.__post_init__()
    except (ManagedCleanupV3Error, TypeError, KeyError) as exc:
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid") from exc
    expected_sha256 = _context_registration_sha256(context, authority)
    if (
        row.run_id_sha256 != context.run_id_sha256
        or row.context_sha256 != context.context_sha256
        or row.authority_terminal_sha256 != authority.terminal_commitment_sha256
        or row.registration_sha256 != expected_sha256
        or not authenticator.verify(
            "projection-context-authority", expected_sha256, row.registration_mac_sha256
        )
    ):
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid")
    return context, authority


def _validate_context_registry_binding(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    registry: MemoryComparisonBenchmarkRunRow,
) -> None:
    if (
        authority.profile_id != context.profile_id
        or authority.context_sha256 != context.context_sha256
        or authority.a1_terminal_commitment_sha256 != context.a1_terminal_commitment_sha256
        or authority.cleanup_operation_stream_root_sha256
        != context.cleanup_operation_stream_root_sha256
        or authority.omitted_source_identity_root_sha256
        != context.omitted_source_identity_root_sha256
        or context.run_id_sha256 != registry.run_id_sha256
        or context.binding_commitment_sha256 != registry.binding_commitment_sha256
        or context.infinity_target_identity_sha256 != registry.infinity_target_identity_sha256
        or context.space_id != registry.space_id
        or context.space_slug != registry.space_slug
    ):
        raise ProjectionReceiptError("projection_receipt.context_registry_divergent")


__all__ = ("PostgresProjectionReceiptRepository",)
