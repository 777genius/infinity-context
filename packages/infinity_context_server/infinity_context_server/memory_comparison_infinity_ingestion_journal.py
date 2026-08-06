"""Generic signed-journal orchestration for Infinity episode ingestion."""

from __future__ import annotations

import hmac
from threading import Lock

from infinity_context_server.memory_comparison_infinity_ingestion_contracts import (
    InfinityIngestionError,
    InfinityIngestionReceipt,
    InfinityIngestionResultStorePort,
    infinity_ingestion_result_commitment,
)
from infinity_context_server.memory_comparison_infinity_ingestion_http import (
    InfinityEpisodeHttpAdapter,
)
from infinity_context_server.memory_comparison_ingestion_contracts import IngestionUnit
from infinity_context_server.resumable_operation_journal import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    ResumableOperationJournalService,
    RetryDisposition,
    VerifiedOperationReceipt,
)
from infinity_context_server.resumable_operation_journal.domain import (
    canonical_json,
    sha256_commitment,
)
from infinity_context_server.resumable_operation_journal.ports import (
    OperationJournalSignerPort,
)

_OPERATION_KIND = "infinity_episode_ingest"


def make_infinity_ingestion_operation_manifest(
    units: tuple[IngestionUnit, ...],
    *,
    run_id: str,
    ingestion_manifest_sha256: str,
) -> OperationManifest:
    """Bind every public unit to one exact idempotent journal operation."""

    if type(units) is not tuple or not units:
        raise InfinityIngestionError("Infinity operation manifest must be non-empty")
    operations = []
    for ordinal, unit in enumerate(units):
        if type(unit) is not IngestionUnit or unit.ordinal != ordinal:
            raise InfinityIngestionError("Infinity units must preserve manifest order")
        unit.validate()
        operations.append(
            _operation_identity(
                unit,
                run_id=run_id,
                ingestion_manifest_sha256=ingestion_manifest_sha256,
            )
        )
    try:
        return OperationManifest(tuple(operations))
    except OperationJournalError as exc:
        raise InfinityIngestionError("Infinity operation manifest is invalid") from exc


class HmacInfinityOperationReceiptVerifier:
    """Require a deterministic signer-bound ID on every generic receipt."""

    def __init__(self, signer: OperationJournalSignerPort) -> None:
        self._signer = signer

    def verify(
        self, *, identity: LogicalOperationIdentity, receipt: OperationReceipt
    ) -> VerifiedOperationReceipt:
        if receipt.logical_operation_id != identity.logical_operation_id:
            raise OperationJournalError("infinity_receipt_operation_mismatch")
        expected = _signed_receipt_id(self._signer, receipt)
        if type(receipt.receipt_id) is not str or not hmac.compare_digest(
            receipt.receipt_id, expected
        ):
            raise OperationJournalError("infinity_receipt_hmac_invalid")
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id=self._signer.key_id,
            verification_commitment_sha256=sha256_commitment(
                {"receipt": receipt.identity_payload(), "receipt_hmac": expected}
            ),
        )


class JournaledInfinityIngestionConsumer:
    """Crash-safe adapter preserving the legacy void consumer interface."""

    def __init__(
        self,
        *,
        adapter: InfinityEpisodeHttpAdapter,
        journal: ResumableOperationJournalService,
        operation_manifest: OperationManifest,
        results: InfinityIngestionResultStorePort,
        signer: OperationJournalSignerPort,
        ingestion_manifest_sha256: str,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._manifest = operation_manifest
        self._results = results
        self._signer = signer
        self._ingestion_manifest_sha256 = ingestion_manifest_sha256
        self._lock = Lock()
        try:
            snapshot = journal.snapshot(operation_manifest.run_id)
        except OperationJournalError as exc:
            raise InfinityIngestionError("Infinity journal is not initialized") from exc
        if snapshot.run.identity.manifest_commitment_sha256 != operation_manifest.commitment_sha256:
            raise InfinityIngestionError("Infinity journal manifest binding is divergent")
        self._next_ordinal = snapshot.committed_count

    def consume_with_receipt(
        self, unit: IngestionUnit, *, run_id: str, manifest_sha256: str
    ) -> InfinityIngestionReceipt:
        with self._lock:
            return self._consume_locked(unit, run_id=run_id, manifest_sha256=manifest_sha256)

    def consume(self, unit: IngestionUnit, *, run_id: str, manifest_sha256: str) -> None:
        self.consume_with_receipt(unit, run_id=run_id, manifest_sha256=manifest_sha256)

    def resume(self) -> None:
        """Authenticate journal replay and schedule incomplete idempotent work."""

        with self._lock:
            try:
                result = self._journal.resume(self._manifest.run_id)
                snapshot = self._journal.snapshot(self._manifest.run_id)
            except OperationJournalError as exc:
                raise InfinityIngestionError("Infinity journal resume failed") from exc
            if result.outcome_unknown_count:
                raise InfinityIngestionError("Infinity ingestion entered reconciliation")
            self._next_ordinal = snapshot.committed_count

    def _consume_locked(
        self, unit: IngestionUnit, *, run_id: str, manifest_sha256: str
    ) -> InfinityIngestionReceipt:
        identity = self._bound_identity(unit, run_id, manifest_sha256)
        stored = self._results.load(identity.logical_operation_id)
        if unit.ordinal < self._next_ordinal:
            return self._restore_committed(identity, unit, stored)
        if unit.ordinal != self._next_ordinal:
            raise InfinityIngestionError("Infinity ingestion violates manifest order")
        request_hash = self._adapter.request_commitment_sha256(unit, run_id=run_id)
        try:
            preparation = self._journal.prepare_dispatch(identity, request_hash)
        except OperationJournalError as exc:
            raise InfinityIngestionError("Infinity dispatch preparation failed") from exc
        if not preparation.should_dispatch:
            if preparation.state.phase is OperationPhase.COMMITTED:
                result = self._restore_committed(identity, unit, stored)
                self._next_ordinal += 1
                return result
            raise InfinityIngestionError("Infinity operation is already in progress")
        if stored is None:
            stored = self._adapter.ingest(unit, run_id=run_id, manifest_sha256=manifest_sha256)
            self._results.save(identity.logical_operation_id, stored)
        self._commit(identity, unit, stored)
        self._next_ordinal += 1
        return stored

    def _restore_committed(
        self,
        identity: LogicalOperationIdentity,
        unit: IngestionUnit,
        stored: InfinityIngestionReceipt | None,
    ) -> InfinityIngestionReceipt:
        if stored is None:
            raise InfinityIngestionError("committed Infinity result is missing")
        _validate_result_binding(
            stored,
            unit,
            run_id=identity.run_id,
            manifest_sha256=self._ingestion_manifest_sha256,
        )
        self._commit(identity, unit, stored)
        return stored

    def _commit(
        self,
        identity: LogicalOperationIdentity,
        unit: IngestionUnit,
        result: InfinityIngestionReceipt,
    ) -> None:
        _validate_result_binding(
            result,
            unit,
            run_id=identity.run_id,
            manifest_sha256=self._ingestion_manifest_sha256,
        )
        receipt = _operation_receipt(self._signer, identity, result)
        try:
            state = self._journal.commit(identity, receipt)
        except OperationJournalError as exc:
            raise InfinityIngestionError("Infinity result commit failed") from exc
        if state.phase is not OperationPhase.COMMITTED or state.receipt != receipt:
            raise InfinityIngestionError("Infinity journal did not commit exact evidence")

    def _bound_identity(
        self, unit: IngestionUnit, run_id: str, manifest_sha256: str
    ) -> LogicalOperationIdentity:
        if run_id != self._manifest.run_id or manifest_sha256 != self._ingestion_manifest_sha256:
            raise InfinityIngestionError("Infinity ingestion authority is divergent")
        if unit.ordinal >= len(self._manifest.operations):
            raise InfinityIngestionError("Infinity unit is outside the operation manifest")
        expected = _operation_identity(
            unit,
            run_id=run_id,
            ingestion_manifest_sha256=manifest_sha256,
        )
        identity = self._manifest.operations[unit.ordinal]
        if identity != expected:
            raise InfinityIngestionError("Infinity unit operation binding is divergent")
        return identity


def _operation_identity(
    unit: IngestionUnit, *, run_id: str, ingestion_manifest_sha256: str
) -> LogicalOperationIdentity:
    authority = sha256_commitment(
        {
            "corpus_id": unit.corpus_id,
            "ingestion_manifest_sha256": ingestion_manifest_sha256,
            "metadata_sha256": unit.metadata_sha256,
            "payload_sha256": unit.payload_sha256,
            "source_id": unit.metadata.source_id,
            "unit_input_sha256": unit.unit_input_sha256,
            "unit_sha256": unit.unit_sha256,
        }
    )
    try:
        return LogicalOperationIdentity(
            run_id=run_id,
            operation_key=unit.metadata.source_id,
            operation_kind=_OPERATION_KIND,
            ordinal=unit.ordinal,
            authority_commitment_sha256=authority,
            retry_disposition=RetryDisposition.IDEMPOTENT_REPLAY,
        )
    except OperationJournalError as exc:
        raise InfinityIngestionError("Infinity operation identity is invalid") from exc


def _operation_receipt(
    signer: OperationJournalSignerPort,
    identity: LogicalOperationIdentity,
    result: InfinityIngestionReceipt,
) -> OperationReceipt:
    provisional = OperationReceipt(
        run_id=identity.run_id,
        logical_operation_id=identity.logical_operation_id,
        request_commitment_sha256=result.request_sha256,
        receipt_id="provisional",
        result_commitment_sha256=infinity_ingestion_result_commitment(result),
    )
    return OperationReceipt(
        run_id=provisional.run_id,
        logical_operation_id=provisional.logical_operation_id,
        request_commitment_sha256=provisional.request_commitment_sha256,
        receipt_id=_signed_receipt_id(signer, provisional),
        result_commitment_sha256=provisional.result_commitment_sha256,
    )


def _signed_receipt_id(signer: OperationJournalSignerPort, receipt: OperationReceipt) -> str:
    payload = {
        "logical_operation_id": receipt.logical_operation_id,
        "request_commitment_sha256": receipt.request_commitment_sha256,
        "result_commitment_sha256": receipt.result_commitment_sha256,
        "run_id": receipt.run_id,
    }
    return "inf_" + signer.sign(canonical_json(payload).encode("utf-8"))


def _validate_result_binding(
    result: InfinityIngestionReceipt,
    unit: IngestionUnit,
    *,
    run_id: str,
    manifest_sha256: str,
) -> None:
    result.validate()
    if (
        result.run_id != run_id
        or result.manifest_sha256 != manifest_sha256
        or result.ordinal != unit.ordinal
        or result.corpus_id != unit.corpus_id
        or result.source_id != unit.metadata.source_id
        or result.payload_sha256 != unit.payload_sha256
        or result.metadata_sha256 != unit.metadata_sha256
        or result.unit_input_sha256 != unit.unit_input_sha256
        or result.unit_sha256 != unit.unit_sha256
    ):
        raise InfinityIngestionError("stored Infinity result binding is divergent")


__all__ = [
    "HmacInfinityOperationReceiptVerifier",
    "JournaledInfinityIngestionConsumer",
    "make_infinity_ingestion_operation_manifest",
]
