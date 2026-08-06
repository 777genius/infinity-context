"""Application-level provider-free E2E scenario and public verdict."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .canonical import E2EVerificationError, canonical_sha256
from .contracts import ROUTE_SHA256, SYNTHETIC_OUTPUT, RunFixture
from .fake_runtime import AuthenticatedCallCounter
from .http_client import AdapterHttpClient, CleanupReceipt, RuntimeEnvelope
from .receipt import ReceiptVerifier
from .state_audit import IndependentStateAuditor
from .storage_audit import IndependentStorageAuditor, QdrantHttp, StorageScope


class AdapterLifecycle(Protocol):
    def crash_and_restart(self) -> None: ...


@dataclass(frozen=True, slots=True)
class E2EResult:
    verdict: str
    admission_commitment_sha256: str
    operation_id_sha256: str
    runtime_receipt_sha256: str
    storage_commitment_sha256: str
    seal_commitment_sha256: str
    cleanup_receipt_sha256: str
    fake_provider_calls: int


class ProviderFreeE2EScenario:
    def __init__(
        self,
        *,
        fixture: RunFixture,
        adapter: AdapterHttpClient,
        receipt_verifier: ReceiptVerifier,
        state_auditor: IndependentStateAuditor,
        storage_auditor: IndependentStorageAuditor,
        qdrant: QdrantHttp,
        counter: AuthenticatedCallCounter,
        lifecycle: AdapterLifecycle,
        operation_state_path: Path,
        durable_artifact_roots: tuple[Path, ...],
        forbidden_artifact_bytes: tuple[bytes, ...],
    ) -> None:
        self._fixture = fixture
        self._adapter = adapter
        self._receipt_verifier = receipt_verifier
        self._state = state_auditor
        self._storage = storage_auditor
        self._qdrant = qdrant
        self._counter = counter
        self._lifecycle = lifecycle
        self._operation_state_path = operation_state_path
        self._artifact_roots = durable_artifact_roots
        self._forbidden = forbidden_artifact_bytes

    def run(self) -> E2EResult:
        fixture = self._fixture
        admission_body = {
            "admission_commitment_sha256": fixture.admission_commitment_sha256,
            "ingestion_manifest_sha256": fixture.ingestion_manifest_sha256,
            "ingestion_root_sha256": fixture.ingestion_root_sha256,
            "expected_operation_count": 1,
            "route_sha256": ROUTE_SHA256,
        }
        admission = self._adapter.admit(admission_body, fixture.idempotency_key("admission"))
        if (
            admission.admission_commitment_sha256 != fixture.admission_commitment_sha256
            or admission.accepted is not True
        ):
            raise E2EVerificationError("e2e_admission_binding_invalid")

        first = self._adapter.dispatch(fixture.dispatch_body(), fixture.idempotency_key("dispatch"))
        self._verify_envelope(first)
        receipt_sha = self._receipt_verifier.verify(first.runtime_receipt)
        if self._counter.read() != 1:
            raise E2EVerificationError("e2e_provider_call_count_invalid")

        scope = StorageScope(
            user_id=fixture.unit.corpus_id,
            run_id=fixture.admission_commitment_sha256,
            source_id=fixture.unit.source_id,
            source_sha256=fixture.unit.unit_sha256,
        )
        storage = self._storage.verify_exact(scope=scope, expected_text="Alice likes tea.")
        committed = self._state.audit(
            expected_identity=fixture.unit.unit_identity_sha256,
            expected_request_sha256=fixture.request_body_sha256,
            expected_state="COMMITTED",
        )
        if (
            committed.runtime_receipt_sha256 != receipt_sha
            or committed.storage_commitment_sha256 != storage.commitment_sha256
        ):
            raise E2EVerificationError("e2e_outer_commitment_invalid")
        seal = self._seal(receipt_sha, storage.commitment_sha256)

        self._lifecycle.crash_and_restart()
        replay_admission = self._adapter.admit(
            admission_body, fixture.idempotency_key("admission-replay")
        )
        if replay_admission != admission:
            raise E2EVerificationError("e2e_admission_replay_divergent")
        status_body = {
            "admission_commitment_sha256": fixture.admission_commitment_sha256,
            "operation_id_sha256": fixture.operation_id_sha256,
        }
        status = self._adapter.status(status_body, fixture.idempotency_key("status"))
        dispatch_replay = self._adapter.dispatch(
            fixture.dispatch_body(), fixture.idempotency_key("dispatch-replay")
        )
        if status != first or dispatch_replay != first or self._counter.read() != 1:
            raise E2EVerificationError("e2e_restart_replay_invalid")
        self._assert_receipt_tamper_rejected(first.runtime_receipt)

        cleanup_body = {
            **seal,
            "admission_commitment_sha256": fixture.admission_commitment_sha256,
            "expected_operation_count": 1,
            "aborting": False,
        }
        cleanup = self._adapter.cleanup(cleanup_body, fixture.idempotency_key("cleanup"))
        self._verify_cleanup(cleanup, seal)
        cleaned = self._state.audit(
            expected_identity=fixture.unit.unit_identity_sha256,
            expected_request_sha256=fixture.request_body_sha256,
            expected_state="CLEANED",
        )
        if (
            cleaned.runtime_receipt_sha256 != receipt_sha
            or cleaned.storage_commitment_sha256 != storage.commitment_sha256
            or cleaned.tombstone_commitment_sha256 is None
        ):
            raise E2EVerificationError("e2e_cleanup_state_invalid")
        self._storage.verify_absent(scope=scope, sealed_provider_ids=storage.provider_memory_ids)
        replay = self._adapter.cleanup(cleanup_body, fixture.idempotency_key("cleanup-replay"))
        if replay != cleanup or self._counter.read() != 1:
            raise E2EVerificationError("e2e_cleanup_replay_invalid")
        replayed_cleaned = self._state.audit(
            expected_identity=fixture.unit.unit_identity_sha256,
            expected_request_sha256=fixture.request_body_sha256,
            expected_state="CLEANED",
        )
        if replayed_cleaned != cleaned:
            raise E2EVerificationError("e2e_cleanup_replay_state_invalid")
        self._storage.verify_absent(
            scope=scope,
            sealed_provider_ids=storage.provider_memory_ids,
        )

        self._assert_state_tamper_rejected()
        self._assert_storage_residue_rejected(
            scope,
            cleanup_body,
            expected_cleaned=cleaned,
            sealed_provider_ids=storage.provider_memory_ids,
        )
        self._storage.verify_absent(scope=scope, sealed_provider_ids=storage.provider_memory_ids)
        self._assert_no_private_durable_artifacts()
        return E2EResult(
            verdict="PASS",
            admission_commitment_sha256=fixture.admission_commitment_sha256,
            operation_id_sha256=fixture.operation_id_sha256,
            runtime_receipt_sha256=receipt_sha,
            storage_commitment_sha256=storage.commitment_sha256,
            seal_commitment_sha256=str(seal["seal_commitment_sha256"]),
            cleanup_receipt_sha256=canonical_sha256(asdict(cleanup)),
            fake_provider_calls=self._counter.read(),
        )

    def _verify_envelope(self, envelope: RuntimeEnvelope) -> None:
        if (
            envelope.admission_commitment_sha256 != self._fixture.admission_commitment_sha256
            or envelope.operation_id_sha256 != self._fixture.operation_id_sha256
        ):
            raise E2EVerificationError("e2e_runtime_envelope_binding_invalid")

    def _seal(self, receipt_sha: str, storage_sha: str) -> dict[str, str]:
        fixture = self._fixture
        base = {
            "operation_id_sha256": fixture.operation_id_sha256,
            "unit_index": 0,
            "unit_identity_sha256": fixture.unit.unit_identity_sha256,
            "unit_sha256": fixture.unit.unit_sha256,
            "scope_sha256": fixture.unit.scope_sha256,
            "provider_receipt_sha256": receipt_sha,
            "disposition": "completed",
            "extraction_calls": 1,
            "retry_count": 0,
            "request_tokens": 0,
            "response_tokens": 0,
            "stored_identity_sha256": storage_sha,
            "stored_record_count": 1,
        }
        operation = {**base, "state": "committed", "commitment_sha256": canonical_sha256(base)}
        operation_root = canonical_sha256(
            {"operation_commitments": [operation["commitment_sha256"]]}
        )
        inventory_root = canonical_sha256({"operations": [operation]})
        seal = canonical_sha256(
            {
                "admission_commitment_sha256": fixture.admission_commitment_sha256,
                "operation_count": 1,
                "ingestion_root_sha256": fixture.ingestion_root_sha256,
                "operation_root_sha256": operation_root,
                "provider_observed_extraction_calls": 1,
                "provider_observed_request_tokens": 0,
                "provider_observed_response_tokens": 0,
            }
        )
        return {
            "seal_commitment_sha256": seal,
            "operation_root_sha256": operation_root,
            "operation_inventory_root_sha256": inventory_root,
        }

    def _verify_cleanup(self, receipt: CleanupReceipt, seal: dict[str, str]) -> None:
        if (
            receipt.admission_commitment_sha256 != self._fixture.admission_commitment_sha256
            or receipt.seal_commitment_sha256 != seal["seal_commitment_sha256"]
            or receipt.operation_root_sha256 != seal["operation_root_sha256"]
            or receipt.operation_inventory_root_sha256 != seal["operation_inventory_root_sha256"]
            or receipt.deleted_operation_count != 1
            or receipt.residual_record_count != 0
            or receipt.residual_root_sha256 != hashlib.sha256(b"").hexdigest()
        ):
            raise E2EVerificationError("e2e_cleanup_receipt_invalid")

    def _assert_receipt_tamper_rejected(self, receipt: dict[str, object]) -> None:
        self._receipt_verifier.verify(receipt)
        forged = deepcopy(receipt)
        metadata = forged["metadata"]
        assert isinstance(metadata, dict)
        metadata["receipt_hmac_sha256"] = "f" * 64
        try:
            self._receipt_verifier.verify(forged)
        except E2EVerificationError as exc:
            if str(exc) == "e2e_receipt_unauthenticated":
                return
            raise
        raise E2EVerificationError("e2e_receipt_tamper_accepted")

    def _assert_state_tamper_rejected(self) -> None:
        self._state.audit(
            expected_identity=self._fixture.unit.unit_identity_sha256,
            expected_request_sha256=self._fixture.request_body_sha256,
            expected_state="CLEANED",
        )
        with tempfile.TemporaryDirectory(prefix="mem0-v5-e2e-state-tamper-") as directory:
            copied = Path(directory) / "operations.sqlite3"
            shutil.copy2(self._operation_state_path, copied)
            connection = sqlite3.connect(copied)
            try:
                connection.execute("UPDATE operations_v2 SET row_hmac = ?", ("0" * 64,))
                connection.commit()
            finally:
                connection.close()
            auditor = self._state.for_path(copied)
            try:
                auditor.audit(
                    expected_identity=self._fixture.unit.unit_identity_sha256,
                    expected_request_sha256=self._fixture.request_body_sha256,
                    expected_state="CLEANED",
                )
            except E2EVerificationError as exc:
                if str(exc) == "e2e_state_row_unauthenticated":
                    return
                raise
        raise E2EVerificationError("e2e_state_tamper_accepted")

    def _assert_storage_residue_rejected(
        self,
        scope: StorageScope,
        cleanup_body: dict[str, object],
        *,
        expected_cleaned: object,
        sealed_provider_ids: tuple[str, ...],
    ) -> None:
        self._assert_cleanup_probe_integrity(
            scope=scope,
            expected_cleaned=expected_cleaned,
            sealed_provider_ids=sealed_provider_ids,
        )
        point_id = self._qdrant.inject_residue(scope)
        try:
            try:
                self._storage.verify_absent(scope=scope, sealed_provider_ids=())
            except E2EVerificationError as exc:
                if str(exc) != "e2e_storage_residue_detected":
                    raise
            else:
                raise E2EVerificationError("e2e_storage_residue_accepted")
            try:
                self._adapter.cleanup(cleanup_body, self._fixture.idempotency_key("cleanup-tamper"))
            except E2EVerificationError as exc:
                if str(exc) != "e2e_http_remote_failed":
                    raise
            else:
                raise E2EVerificationError("e2e_cleanup_residue_accepted")
        finally:
            self._qdrant.delete_point(point_id)
        self._assert_cleanup_probe_integrity(
            scope=scope,
            expected_cleaned=expected_cleaned,
            sealed_provider_ids=sealed_provider_ids,
        )

    def _assert_cleanup_probe_integrity(
        self,
        *,
        scope: StorageScope,
        expected_cleaned: object,
        sealed_provider_ids: tuple[str, ...],
    ) -> None:
        current = self._state.audit(
            expected_identity=self._fixture.unit.unit_identity_sha256,
            expected_request_sha256=self._fixture.request_body_sha256,
            expected_state="CLEANED",
        )
        if current != expected_cleaned or self._counter.read() != 1:
            raise E2EVerificationError("e2e_cleanup_probe_integrity_invalid")
        self._storage.verify_absent(
            scope=scope,
            sealed_provider_ids=sealed_provider_ids,
        )

    def _assert_no_private_durable_artifacts(self) -> None:
        patterns = tuple(
            value
            for value in (
                *self._forbidden,
                SYNTHETIC_OUTPUT.encode(),
                b"Alice likes tea.",
            )
            if value
        )
        scan_durable_artifacts(self._artifact_roots, patterns)


def scan_durable_artifacts(roots: tuple[Path, ...], patterns: tuple[bytes, ...]) -> None:
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise E2EVerificationError("e2e_durable_artifact_invalid")
        for path in root.rglob("*"):
            try:
                mode = os.lstat(path).st_mode
            except OSError:
                raise E2EVerificationError("e2e_artifact_scan_failed") from None
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise E2EVerificationError("e2e_durable_artifact_invalid")
            if stat.S_ISREG(mode) and _contains_any(path, patterns):
                raise E2EVerificationError("e2e_private_artifact_residue")


def _contains_any(path: Path, patterns: tuple[bytes, ...]) -> bool:
    overlap_size = max((len(pattern) for pattern in patterns), default=1) - 1
    overlap = b""
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                window = overlap + chunk
                if any(pattern in window for pattern in patterns):
                    return True
                overlap = window[-overlap_size:] if overlap_size else b""
    except OSError:
        raise E2EVerificationError("e2e_artifact_scan_failed") from None
    return False
