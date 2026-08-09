"""Typed local-state proof for a managed Mem0 run that never dispatched."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_store import (
    HmacAtomicManagedMem0V5CleanStateStore,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    managed_mem0_v5_unclaimed_dispatch_commitment,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_head_sqlite import (
    SQLiteManagedMem0V5CheckpointHead,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationManifest,
    OperationRunIdentity,
)
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)


class ManagedMem0V5PristineStateError(RuntimeError):
    pass


@final
class ManagedMem0V5PristineStateVerifier:
    __slots__ = (
        "_checkpoint",
        "_dispatch",
        "_durable",
        "_durable_key",
        "_head",
        "_head_key",
        "_identity",
        "_manifest",
        "_operations",
        "_operation_signer",
    )

    def __init__(
        self,
        *,
        checkpoint_file: Path,
        checkpoint_head_file: Path,
        dispatch_journal: Path,
        durable_clean_state: Path,
        checkpoint_head_key: bytes,
        durable_clean_state_key: bytes,
        operation_journal: ResumableOperationJournalService,
        operation_identity: OperationRunIdentity,
        operation_manifest: OperationManifest,
        operation_signer: object,
    ) -> None:
        paths = (
            checkpoint_file,
            checkpoint_head_file,
            dispatch_journal,
            durable_clean_state,
        )
        if (
            any(not isinstance(path, Path) or not path.is_absolute() for path in paths)
            or type(checkpoint_head_key) is not bytes
            or len(checkpoint_head_key) < 32
            or type(durable_clean_state_key) is not bytes
            or len(durable_clean_state_key) < 32
            or type(operation_journal) is not ResumableOperationJournalService
            or type(operation_identity) is not OperationRunIdentity
            or type(operation_manifest) is not OperationManifest
            or not callable(getattr(operation_signer, "close", None))
        ):
            _fail("managed_mem0_v5_pristine_inputs_invalid")
        self._checkpoint = checkpoint_file
        self._head = checkpoint_head_file
        self._dispatch = dispatch_journal
        self._durable = durable_clean_state
        self._head_key = bytearray(checkpoint_head_key)
        self._durable_key = bytearray(durable_clean_state_key)
        self._operations = operation_journal
        self._identity = operation_identity
        self._manifest = operation_manifest
        self._operation_signer = operation_signer

    def prove_pristine(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        clean_state_witness: ManagedMem0V5AuthenticatedCleanStateWitness,
    ) -> str:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(admission) is not Mem0OssFullRunAdmission
            or type(clean_state_witness) is not ManagedMem0V5AuthenticatedCleanStateWitness
        ):
            _fail("managed_mem0_v5_pristine_authority_invalid")
        _require_absent(self._checkpoint)
        try:
            dispatch = managed_mem0_v5_unclaimed_dispatch_commitment(self._dispatch)
            operations = self._operations.prove_pristine(self._identity, self._manifest)
            head = self._head_commitment(authority, admission)
            durable = self._durable_commitment(authority, admission, clean_state_witness)
        except Exception:
            _fail("managed_mem0_v5_pristine_state_invalid")
        return canonical_sha256(
            {
                "schema_version": "managed-mem0-v5-pristine-state.v1",
                "checkpoint_absence_sha256": _path_absence(self._checkpoint),
                "dispatch_unclaimed_sha256": dispatch,
                "operation_journal_pristine_sha256": operations,
                "checkpoint_head_pristine_sha256": head,
                "durable_clean_state_sha256": durable,
                "clean_state_witness_sha256": clean_state_witness.evidence_commitment_sha256,
            }
        )

    def _head_commitment(
        self, authority: ManagedMem0V5ManifestAuthority, admission: Mem0OssFullRunAdmission
    ) -> str:
        if not _present(self._head):
            return _path_absence(self._head)
        store = SQLiteManagedMem0V5CheckpointHead(self._head, hmac_key=bytes(self._head_key))
        value = store.load_head(
            authority_commitment_sha256=authority.authority_commitment_sha256,
            admission_commitment_sha256=admission.commitment_sha256,
        )
        if value is not None:
            _fail("managed_mem0_v5_pristine_checkpoint_head_present")
        return canonical_sha256(
            {
                "schema_version": "managed-mem0-v5-pristine-checkpoint-head.v1",
                "authority_commitment_sha256": authority.authority_commitment_sha256,
                "admission_commitment_sha256": admission.commitment_sha256,
            }
        )

    def _durable_commitment(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        witness: ManagedMem0V5AuthenticatedCleanStateWitness,
    ) -> str:
        if not _present(self._durable):
            return _path_absence(self._durable)
        issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
        store = HmacAtomicManagedMem0V5CleanStateStore(
            path=self._durable,
            hmac_key=bytes(self._durable_key),
            issuer=issuer,
            verifier=verifier,
        )
        restored = store.load_original(
            expected_admission_commitment_sha256=admission.commitment_sha256,
            expected_run_id_sha256=hashlib.sha256(admission.request.run_id.encode()).hexdigest(),
            expected_authority_commitment_sha256=authority.authority_commitment_sha256,
            expected_evidence_commitment_sha256=witness.evidence_commitment_sha256,
        )
        if restored.commitment_payload() != witness.commitment_payload():
            _fail("managed_mem0_v5_pristine_clean_state_mismatch")
        return restored.evidence_commitment_sha256

    def close(self) -> None:
        self._operation_signer.close()
        _wipe(self._head_key)
        _wipe(self._durable_key)


def _require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        _fail("managed_mem0_v5_pristine_state_unknown")
    _fail("managed_mem0_v5_pristine_checkpoint_present")


def _present(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        _fail("managed_mem0_v5_pristine_state_unknown")


def _path_absence(path: Path) -> str:
    return canonical_sha256(
        {
            "schema_version": "managed-mem0-v5-path-absence.v1",
            "absolute_path_sha256": hashlib.sha256(str(path).encode()).hexdigest(),
        }
    )


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
    value.clear()


def _fail(code: str) -> None:
    raise ManagedMem0V5PristineStateError(code)


__all__ = (
    "ManagedMem0V5PristineStateError",
    "ManagedMem0V5PristineStateVerifier",
)
