"""Crash-safe paired ingestion coordinated solely by signed journals."""

from __future__ import annotations

import hmac
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from typing import Protocol, final

from infinity_context_server.memory_comparison_ingestion_contracts import IngestionUnit
from infinity_context_server.memory_comparison_paired_ingestion_authority import (
    IngestionManifestVerificationPort,
    PairedAdmissionVerificationPort,
    PairedIngestionAuthority,
    PairedIngestionLane,
    PairedLaneBinding,
)
from infinity_context_server.resumable_operation_journal import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationPhase,
    OperationReceipt,
    ResumableOperationJournalService,
    VerifiedOperationReceipt,
)
from infinity_context_server.resumable_operation_journal.domain import sha256_commitment
from infinity_context_server.resumable_operation_journal.ports import (
    OperationJournalSignerPort,
)


class PairedIngestionError(RuntimeError):
    """Fixed-message error that never reflects adapter or secret material."""


@final
@dataclass(frozen=True, slots=True)
class PairedLaneReceipt:
    lane: PairedIngestionLane
    run_id: str
    ingestion_manifest_sha256: str
    lane_binding_sha256: str
    scope_commitment_sha256: str
    ordinal: int
    corpus_id: str
    source_id: str
    unit_sha256: str
    request_commitment_sha256: str
    provider_receipt_sha256: str
    result_commitment_sha256: str
    scope_id: str
    episode_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.lane) is not PairedIngestionLane
            or type(self.episode_ids) is not tuple
            or type(self.chunk_ids) is not tuple
        ):
            raise PairedIngestionError("paired target receipt is invalid")
        infinity_inventory_valid = (
            self.lane is PairedIngestionLane.INFINITY
            and len(self.episode_ids) == 1
            and bool(self.chunk_ids)
        )
        mem0_inventory_valid = (
            self.lane is PairedIngestionLane.MEM0 and not self.episode_ids and not self.chunk_ids
        )
        if (
            not _safe_id(self.run_id)
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or any(not _safe_id(value) for value in (self.corpus_id, self.source_id, self.scope_id))
            or any(
                not _is_sha256(value)
                for value in (
                    self.ingestion_manifest_sha256,
                    self.lane_binding_sha256,
                    self.scope_commitment_sha256,
                    self.unit_sha256,
                    self.request_commitment_sha256,
                    self.provider_receipt_sha256,
                    self.result_commitment_sha256,
                )
            )
            or len(set(self.episode_ids)) != len(self.episode_ids)
            or len(set(self.chunk_ids)) != len(self.chunk_ids)
            or any(not _safe_id(value) for value in (*self.episode_ids, *self.chunk_ids))
            or not (infinity_inventory_valid or mem0_inventory_valid)
            or self.result_commitment_sha256 != paired_lane_result_commitment_sha256(self)
        ):
            raise PairedIngestionError("paired target receipt is invalid")


@final
@dataclass(frozen=True, slots=True)
class PairedLaneCleanupEvidence:
    lane: PairedIngestionLane
    run_id: str
    ingestion_manifest_sha256: str
    lane_binding_sha256: str
    scope_commitment_sha256: str
    deleted_record_count: int
    residual_record_count: int
    residual_root_sha256: str
    provider_absence_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.lane) is not PairedIngestionLane
            or not _safe_id(self.run_id)
            or any(
                not _is_sha256(value)
                for value in (
                    self.ingestion_manifest_sha256,
                    self.lane_binding_sha256,
                    self.scope_commitment_sha256,
                    self.residual_root_sha256,
                    self.provider_absence_receipt_sha256,
                )
            )
            or type(self.deleted_record_count) is not int
            or self.deleted_record_count < 0
            or type(self.residual_record_count) is not int
            or self.residual_record_count < 0
        ):
            raise PairedIngestionError("paired cleanup evidence is invalid")


@final
@dataclass(frozen=True, slots=True)
class VerifiedPairedLaneCleanup:
    evidence: PairedLaneCleanupEvidence
    verifier_key_id: str
    verification_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not PairedLaneCleanupEvidence
            or not _safe_id(self.verifier_key_id)
            or not _is_sha256(self.verification_commitment_sha256)
            or self.evidence.residual_record_count != 0
            or self.evidence.residual_root_sha256 != empty_inventory_sha256()
        ):
            raise PairedIngestionError("paired cleanup verification is invalid")


@final
@dataclass(frozen=True, slots=True)
class PairedIngestionResult:
    receipts: tuple[PairedLaneReceipt, ...]
    infinity_episode_ids: tuple[str, ...]
    infinity_chunk_ids: tuple[str, ...]
    infinity_episode_ids_by_corpus: tuple[tuple[str, str, tuple[str, ...]], ...]
    result_commitment_sha256: str


class PairedIngestionLanePort(Protocol):
    lane: PairedIngestionLane

    def request_commitment_sha256(
        self, unit: IngestionUnit, *, binding: PairedLaneBinding
    ) -> str: ...

    def dispatch(self, unit: IngestionUnit, *, binding: PairedLaneBinding) -> PairedLaneReceipt: ...

    def status_readback(
        self, unit: IngestionUnit, *, binding: PairedLaneBinding
    ) -> PairedLaneReceipt: ...

    def cleanup(self, *, binding: PairedLaneBinding) -> PairedLaneCleanupEvidence: ...


class PairedCleanupVerificationPort(Protocol):
    """Independent authenticated readback of lane-specific target absence."""

    def verify(
        self, *, binding: PairedLaneBinding, evidence: PairedLaneCleanupEvidence
    ) -> VerifiedPairedLaneCleanup: ...


class PairedLaneReceiptStorePort(Protocol):
    def load(
        self, *, lane: PairedIngestionLane, logical_operation_id: str
    ) -> PairedLaneReceipt | None: ...

    def save(
        self,
        *,
        lane: PairedIngestionLane,
        logical_operation_id: str,
        receipt: PairedLaneReceipt,
    ) -> None: ...


@final
class HmacPairedOperationReceiptVerifier:
    def __init__(self, signer: OperationJournalSignerPort) -> None:
        self._signer = signer

    def verify(
        self, *, identity: LogicalOperationIdentity, receipt: OperationReceipt
    ) -> VerifiedOperationReceipt:
        expected = _journal_receipt_id(self._signer, receipt)
        if (
            receipt.logical_operation_id != identity.logical_operation_id
            or type(receipt.receipt_id) is not str
            or not hmac.compare_digest(receipt.receipt_id, expected)
        ):
            raise OperationJournalError("paired_ingestion_receipt_authentication_failed")
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id=self._signer.key_id,
            verification_commitment_sha256=sha256_commitment(
                {"receipt": receipt.identity_payload(), "receipt_hmac": expected}
            ),
        )


@final
class PairedIngestionCoordinator:
    def __init__(
        self,
        *,
        authority: PairedIngestionAuthority,
        manifest_verifier: IngestionManifestVerificationPort,
        admission_verifier: PairedAdmissionVerificationPort,
        infinity_lane: PairedIngestionLanePort,
        mem0_lane: PairedIngestionLanePort,
        infinity_cleanup_verifier: PairedCleanupVerificationPort,
        mem0_cleanup_verifier: PairedCleanupVerificationPort,
        infinity_journal: ResumableOperationJournalService,
        mem0_journal: ResumableOperationJournalService,
        receipt_store: PairedLaneReceiptStorePort,
        signer: OperationJournalSignerPort,
        max_corpus_workers: int = 4,
    ) -> None:
        if (
            type(authority) is not PairedIngestionAuthority
            or infinity_lane is mem0_lane
            or infinity_journal is mem0_journal
            or infinity_cleanup_verifier is mem0_cleanup_verifier
            or infinity_lane.lane is not PairedIngestionLane.INFINITY
            or mem0_lane.lane is not PairedIngestionLane.MEM0
            or type(max_corpus_workers) is not int
            or not 1 <= max_corpus_workers <= 4
        ):
            raise PairedIngestionError("paired coordinator configuration is invalid")
        self._authority = authority
        self._manifest_verifier = manifest_verifier
        self._admission_verifier = admission_verifier
        self._lanes = {
            PairedIngestionLane.INFINITY: infinity_lane,
            PairedIngestionLane.MEM0: mem0_lane,
        }
        self._cleanup_verifiers = {
            PairedIngestionLane.INFINITY: infinity_cleanup_verifier,
            PairedIngestionLane.MEM0: mem0_cleanup_verifier,
        }
        self._journals = {
            PairedIngestionLane.INFINITY: infinity_journal,
            PairedIngestionLane.MEM0: mem0_journal,
        }
        self._lane_locks = {lane: RLock() for lane in PairedIngestionLane}
        self._store = receipt_store
        self._signer = signer
        self._workers = max_corpus_workers
        self._reconciliation_required = False
        self._verify_authority()

    def initialize(self) -> None:
        self._verify_authority()
        for binding in self._authority.lanes:
            try:
                self._journals[binding.lane].initialize(
                    binding.run_identity, binding.operation_manifest
                )
            except Exception:
                raise PairedIngestionError("paired journal initialization failed") from None

    def resume(self) -> None:
        self._verify_authority()
        reconciliation_required = False
        for binding in self._authority.lanes:
            try:
                result = self._journals[binding.lane].resume(binding.run_identity.run_id)
            except Exception:
                raise PairedIngestionError("paired journal resume failed") from None
            reconciliation_required = reconciliation_required or result.outcome_unknown_count > 0
        self._reconciliation_required = reconciliation_required

    def execute(self) -> PairedIngestionResult:
        units = self._execution_units()
        groups = _units_by_corpus(units)
        receipts: list[PairedLaneReceipt] = []
        workers = 1 if self._reconciliation_required else min(self._workers, len(groups))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_corpus, units) for units in groups]
            for future in futures:
                try:
                    receipts.extend(future.result())
                except Exception:
                    raise PairedIngestionError("paired corpus execution failed") from None
        ordered = tuple(sorted(receipts, key=lambda item: (item.ordinal, item.lane.value)))
        _validate_exact_receipt_matrix(ordered, units)
        result = _paired_result(ordered, units)
        for binding in self._authority.lanes:
            try:
                self._journals[binding.lane].seal(binding.run_identity.run_id)
            except Exception:
                raise PairedIngestionError("paired journal seal failed") from None
        self._reconciliation_required = False
        return result

    def cleanup(self) -> tuple[VerifiedPairedLaneCleanup, VerifiedPairedLaneCleanup]:
        self._verify_authority()
        verified: list[VerifiedPairedLaneCleanup] = []
        for binding in self._authority.lanes:
            try:
                evidence = self._lanes[binding.lane].cleanup(binding=binding)
            except Exception:
                raise PairedIngestionError("paired lane cleanup failed") from None
            _validate_cleanup_binding(evidence, binding, self._authority)
            try:
                proof = self._cleanup_verifiers[binding.lane].verify(
                    binding=binding, evidence=evidence
                )
            except Exception:
                raise PairedIngestionError("paired cleanup readback failed") from None
            if type(proof) is not VerifiedPairedLaneCleanup or proof.evidence != evidence:
                raise PairedIngestionError("paired cleanup proof is divergent")
            verified.append(proof)
        return tuple(verified)  # type: ignore[return-value]

    def _execute_corpus(self, units: tuple[IngestionUnit, ...]) -> tuple[PairedLaneReceipt, ...]:
        completed: list[PairedLaneReceipt] = []
        for unit in units:
            unit.validate()
            for lane in (PairedIngestionLane.INFINITY, PairedIngestionLane.MEM0):
                completed.append(self._execute_lane(unit, lane))
        return tuple(completed)

    def _execute_lane(self, unit: IngestionUnit, lane: PairedIngestionLane) -> PairedLaneReceipt:
        with self._lane_locks[lane]:
            return self._execute_lane_locked(unit, lane)

    def _execute_lane_locked(
        self, unit: IngestionUnit, lane: PairedIngestionLane
    ) -> PairedLaneReceipt:
        binding = self._authority.lane(lane)
        identity = binding.operation_manifest.operations[unit.ordinal]
        adapter = self._lanes[lane]
        try:
            request_sha = adapter.request_commitment_sha256(unit, binding=binding)
        except Exception:
            raise PairedIngestionError("paired lane request binding failed") from None
        if not _is_sha256(request_sha):
            raise PairedIngestionError("paired request commitment is invalid")
        stored = self._store_load(lane, identity.logical_operation_id)
        try:
            preparation = self._journals[lane].prepare_dispatch(identity, request_sha)
        except OperationJournalError as error:
            if (
                lane is PairedIngestionLane.MEM0
                and error.code == "operation_journal_outcome_unknown_quarantined"
            ):
                result = self._status(adapter, unit, binding)
                self._validate_receipt(result, unit, binding, request_sha)
                if stored is not None and stored != result:
                    raise PairedIngestionError("paired status receipt is divergent") from None
                self._store_save(lane, identity.logical_operation_id, result)
                self._commit(binding, identity, result)
                return result
            raise PairedIngestionError("paired dispatch preparation failed") from None
        except Exception:
            raise PairedIngestionError("paired dispatch preparation failed") from None
        if preparation.should_dispatch:
            result = self._dispatch(adapter, unit, binding)
            self._validate_receipt(result, unit, binding, request_sha)
            if stored is not None and stored != result:
                raise PairedIngestionError("paired replay receipt is divergent") from None
            self._store_save(lane, identity.logical_operation_id, result)
            self._commit(binding, identity, result)
            return result
        if preparation.state.phase is not OperationPhase.COMMITTED or stored is None:
            raise PairedIngestionError("paired committed result is missing")
        self._validate_receipt(stored, unit, binding, request_sha)
        self._commit(binding, identity, stored)
        return stored

    @staticmethod
    def _dispatch(adapter, unit, binding) -> PairedLaneReceipt:
        try:
            return adapter.dispatch(unit, binding=binding)
        except Exception:
            raise PairedIngestionError("paired lane dispatch failed") from None

    @staticmethod
    def _status(adapter, unit, binding) -> PairedLaneReceipt:
        try:
            return adapter.status_readback(unit, binding=binding)
        except Exception:
            raise PairedIngestionError("paired lane status readback failed") from None

    def _store_load(self, lane: PairedIngestionLane, operation_id: str) -> PairedLaneReceipt | None:
        try:
            return self._store.load(lane=lane, logical_operation_id=operation_id)
        except Exception:
            raise PairedIngestionError("paired receipt store read failed") from None

    def _store_save(
        self, lane: PairedIngestionLane, operation_id: str, receipt: PairedLaneReceipt
    ) -> None:
        try:
            self._store.save(lane=lane, logical_operation_id=operation_id, receipt=receipt)
        except Exception:
            raise PairedIngestionError("paired receipt store write failed") from None

    def _commit(
        self,
        binding: PairedLaneBinding,
        identity: LogicalOperationIdentity,
        result: PairedLaneReceipt,
    ) -> None:
        provisional = OperationReceipt(
            run_id=identity.run_id,
            logical_operation_id=identity.logical_operation_id,
            request_commitment_sha256=result.request_commitment_sha256,
            receipt_id="provisional",
            result_commitment_sha256=result.result_commitment_sha256,
        )
        receipt = OperationReceipt(
            run_id=provisional.run_id,
            logical_operation_id=provisional.logical_operation_id,
            request_commitment_sha256=provisional.request_commitment_sha256,
            receipt_id=_journal_receipt_id(self._signer, provisional),
            result_commitment_sha256=provisional.result_commitment_sha256,
        )
        try:
            state = self._journals[binding.lane].commit(identity, receipt)
        except Exception:
            raise PairedIngestionError("paired receipt commit failed") from None
        if state.phase is not OperationPhase.COMMITTED or state.receipt != receipt:
            raise PairedIngestionError("paired receipt commit is divergent")

    def _validate_receipt(
        self,
        result: PairedLaneReceipt,
        unit: IngestionUnit,
        binding: PairedLaneBinding,
        request_sha: str,
    ) -> None:
        if type(result) is not PairedLaneReceipt:
            raise PairedIngestionError("paired lane receipt is invalid")
        try:
            result.__post_init__()
        except Exception:
            raise PairedIngestionError("paired lane receipt is invalid") from None
        if (
            result.lane is not binding.lane
            or result.run_id != self._authority.run_id
            or result.ingestion_manifest_sha256 != self._authority.ingestion_manifest_sha256
            or result.lane_binding_sha256 != binding.binding_sha256
            or result.scope_commitment_sha256 != binding.scope_commitment_sha256
            or result.ordinal != unit.ordinal
            or result.corpus_id != unit.corpus_id
            or result.source_id != unit.metadata.source_id
            or result.unit_sha256 != unit.unit_sha256
            or result.request_commitment_sha256 != request_sha
        ):
            raise PairedIngestionError("paired lane receipt binding is divergent")

    def _verify_authority(self) -> None:
        try:
            self._authority.validate_execution(
                manifest_verifier=self._manifest_verifier,
                admission_verifier=self._admission_verifier,
            )
        except Exception:
            raise PairedIngestionError("paired execution authority is invalid") from None

    def _execution_units(self) -> tuple[IngestionUnit, ...]:
        try:
            return self._authority.execution_units(
                manifest_verifier=self._manifest_verifier,
                admission_verifier=self._admission_verifier,
            )
        except Exception:
            raise PairedIngestionError("paired execution authority is invalid") from None


def make_paired_lane_receipt(
    *,
    lane: PairedIngestionLane,
    run_id: str,
    ingestion_manifest_sha256: str,
    lane_binding_sha256: str,
    scope_commitment_sha256: str,
    ordinal: int,
    corpus_id: str,
    source_id: str,
    unit_sha256: str,
    request_commitment_sha256: str,
    provider_receipt_sha256: str,
    scope_id: str,
    episode_ids: tuple[str, ...] = (),
    chunk_ids: tuple[str, ...] = (),
) -> PairedLaneReceipt:
    values = locals()
    return PairedLaneReceipt(
        **values,
        result_commitment_sha256=_paired_lane_result_commitment(**values),
    )


def paired_lane_result_commitment_sha256(receipt: PairedLaneReceipt) -> str:
    return _paired_lane_result_commitment(
        **{
            key: getattr(receipt, key)
            for key in (
                "lane",
                "run_id",
                "ingestion_manifest_sha256",
                "lane_binding_sha256",
                "scope_commitment_sha256",
                "ordinal",
                "corpus_id",
                "source_id",
                "unit_sha256",
                "request_commitment_sha256",
                "provider_receipt_sha256",
                "scope_id",
                "episode_ids",
                "chunk_ids",
            )
        }
    )


def _paired_lane_result_commitment(**values: object) -> str:
    return sha256_commitment(
        {
            **values,
            "lane": values["lane"].value,  # type: ignore[union-attr]
            "episode_ids": list(values["episode_ids"]),  # type: ignore[arg-type]
            "chunk_ids": list(values["chunk_ids"]),  # type: ignore[arg-type]
        }
    )


def make_cleanup_evidence(
    *,
    binding: PairedLaneBinding,
    ingestion_manifest_sha256: str,
    deleted_record_count: int,
    residual_record_count: int,
    residual_root_sha256: str,
    provider_absence_receipt_sha256: str,
) -> PairedLaneCleanupEvidence:
    return PairedLaneCleanupEvidence(
        lane=binding.lane,
        run_id=binding.run_identity.run_id,
        ingestion_manifest_sha256=ingestion_manifest_sha256,
        lane_binding_sha256=binding.binding_sha256,
        scope_commitment_sha256=binding.scope_commitment_sha256,
        deleted_record_count=deleted_record_count,
        residual_record_count=residual_record_count,
        residual_root_sha256=residual_root_sha256,
        provider_absence_receipt_sha256=provider_absence_receipt_sha256,
    )


def empty_inventory_sha256() -> str:
    return sha256_commitment({"records": []})


def _units_by_corpus(units: tuple[IngestionUnit, ...]) -> tuple[tuple[IngestionUnit, ...], ...]:
    grouped: dict[str, list[IngestionUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.corpus_id, []).append(unit)
    return tuple(tuple(items) for items in grouped.values())


def _validate_exact_receipt_matrix(
    receipts: tuple[PairedLaneReceipt, ...], units: tuple[IngestionUnit, ...]
) -> None:
    expected = len(units) * 2
    if (
        len(receipts) != expected
        or len({(item.ordinal, item.lane) for item in receipts}) != expected
    ):
        raise PairedIngestionError("paired run does not contain exact target receipts")


def _paired_result(
    receipts: tuple[PairedLaneReceipt, ...], units: tuple[IngestionUnit, ...]
) -> PairedIngestionResult:
    infinity = tuple(item for item in receipts if item.lane is PairedIngestionLane.INFINITY)
    episodes = tuple(item.episode_ids[0] for item in infinity)
    chunks = tuple(chunk for item in infinity for chunk in item.chunk_ids)
    if len(episodes) != len(set(episodes)) or len(chunks) != len(set(chunks)):
        raise PairedIngestionError("Infinity projection inventory is not globally unique")
    expected_by_corpus: dict[str, int] = {}
    for unit in units:
        expected_by_corpus[unit.corpus_id] = expected_by_corpus.get(unit.corpus_id, 0) + 1
    projected: list[tuple[str, str, tuple[str, ...]]] = []
    for corpus_id, expected_count in sorted(expected_by_corpus.items()):
        items = tuple(item for item in infinity if item.corpus_id == corpus_id)
        scopes = {item.scope_id for item in items}
        corpus_episodes = tuple(item.episode_ids[0] for item in items)
        if (
            len(items) != expected_count
            or len(scopes) != 1
            or len(corpus_episodes) != expected_count
        ):
            raise PairedIngestionError("Infinity per-corpus inventory coverage is divergent")
        projected.append((corpus_id, next(iter(scopes)), corpus_episodes))
    for lane in PairedIngestionLane:
        for corpus_id in expected_by_corpus:
            scopes = {
                item.scope_id
                for item in receipts
                if item.lane is lane and item.corpus_id == corpus_id
            }
            if len(scopes) != 1:
                raise PairedIngestionError("paired lane scope coverage is divergent")
    commitment = sha256_commitment(
        {
            "infinity_chunk_ids": list(chunks),
            "infinity_episode_ids_by_corpus": [
                [corpus, scope, list(values)] for corpus, scope, values in projected
            ],
            "receipts": [
                {
                    "lane": item.lane.value,
                    "ordinal": item.ordinal,
                    "result_commitment_sha256": item.result_commitment_sha256,
                }
                for item in receipts
            ],
        }
    )
    return PairedIngestionResult(receipts, episodes, chunks, tuple(projected), commitment)


def _validate_cleanup_binding(
    evidence: PairedLaneCleanupEvidence,
    binding: PairedLaneBinding,
    authority: PairedIngestionAuthority,
) -> None:
    if type(evidence) is not PairedLaneCleanupEvidence:
        raise PairedIngestionError("paired cleanup evidence is invalid")
    try:
        evidence.__post_init__()
    except Exception:
        raise PairedIngestionError("paired cleanup evidence is invalid") from None
    if (
        evidence.lane is not binding.lane
        or evidence.run_id != authority.run_id
        or evidence.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
        or evidence.lane_binding_sha256 != binding.binding_sha256
        or evidence.scope_commitment_sha256 != binding.scope_commitment_sha256
    ):
        raise PairedIngestionError("paired cleanup binding is divergent")


def _journal_receipt_id(signer: OperationJournalSignerPort, receipt: OperationReceipt) -> str:
    payload = {
        "logical_operation_id": receipt.logical_operation_id,
        "request_commitment_sha256": receipt.request_commitment_sha256,
        "result_commitment_sha256": receipt.result_commitment_sha256,
        "run_id": receipt.run_id,
    }
    return "pair_" + signer.sign(sha256_commitment(payload).encode("ascii"))


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 240
        and all(character.isalnum() or character in "._:-" for character in value)
    )


__all__ = (
    "HmacPairedOperationReceiptVerifier",
    "PairedCleanupVerificationPort",
    "PairedIngestionCoordinator",
    "PairedIngestionError",
    "PairedIngestionLanePort",
    "PairedIngestionResult",
    "PairedLaneCleanupEvidence",
    "PairedLaneReceipt",
    "PairedLaneReceiptStorePort",
    "VerifiedPairedLaneCleanup",
    "empty_inventory_sha256",
    "make_cleanup_evidence",
    "make_paired_lane_receipt",
    "paired_lane_result_commitment_sha256",
)
