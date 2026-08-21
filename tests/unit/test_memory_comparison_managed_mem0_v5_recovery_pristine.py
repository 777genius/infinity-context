from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_store import (
    HmacAtomicManagedMem0V5CleanStateStore,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    create_managed_mem0_v5_single_dispatch_guard,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_head_sqlite import (
    SQLiteManagedMem0V5CheckpointHead,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery_pristine import (
    ManagedMem0V5PristineStateError,
    ManagedMem0V5PristineStateVerifier,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CleanCorpusScope,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_v5_recovery_operation_authority import (
    ManagedV5RecoveryOperationAuthorityError,
    _existing_operation_journal,
    _RecoveryOperationSigner,
    require_managed_v5_recovery_pristine_checkpoint_head,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.resumable_operation_journal import (
    AllowAllOperationManifestPolicy,
    LogicalOperationIdentity,
    NullOperationNotification,
    OperationManifest,
    OperationRunIdentity,
    ResumableOperationJournalService,
    RetryDisposition,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _UnusedReceiptVerifier:
    def verify(self, **_kwargs: object) -> object:
        raise AssertionError("receipt verification is forbidden for pristine state")


def _material(tmp_path: Path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice fact one.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    authority = ManagedMem0V5ManifestProjector().project(
        (ManagedRunCase("case-1", corpus_id, record),), current_date="2026-08-09"
    )
    request = Mem0OssAdmissionRequest(
        run_id="recovery-pristine-1",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.4",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-v1",
        runtime_source_sha256=_sha("source"),
        runtime_base_sha256=_sha("base"),
        expected_operation_count=authority.operation_count,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    signer = _RecoveryOperationSigner(key_id="recovery-pristine-signer-v1", secret=b"o" * 64)
    operation = LogicalOperationIdentity(
        run_id=request.run_id,
        operation_key="extract-000000",
        operation_kind="provider_extraction",
        ordinal=0,
        authority_commitment_sha256=authority.authority_commitment_sha256,
        retry_disposition=RetryDisposition.QUARANTINE_UNKNOWN,
    )
    manifest = OperationManifest((operation,))
    identity = OperationRunIdentity(
        run_id=request.run_id,
        operation_namespace="managed-mem0-v5",
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=_sha("policy"),
        signer_key_id=signer.key_id,
        expected_operation_count=1,
    )
    journal = ResumableOperationJournalService(
        journal=SQLiteOperationJournal(root / "operations.sqlite3", private_directory=root),
        signer=signer,
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=_UnusedReceiptVerifier(),
        notifications=NullOperationNotification(),
    )
    journal.initialize(identity, manifest)
    issuer, _verifier = create_managed_mem0_v5_clean_state_witness_authority()
    scope = ManagedMem0V5CleanCorpusScope(
        corpus_identity_sha256=canonical_sha256({"corpus_id": corpus_id}),
        scope_identity_sha256=authority.units[0].scope_sha256,
        source_scope_count=1,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
    )
    witness = issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=admission.commitment_sha256,
        run_id_sha256=_sha(request.run_id),
        authority_commitment_sha256=authority.authority_commitment_sha256,
        scopes=(scope,),
    )
    head_key = b"h" * 64
    durable_key = b"d" * 64
    SQLiteManagedMem0V5CheckpointHead(root / "head.sqlite3", hmac_key=head_key)
    durable_issuer, durable_verifier = create_managed_mem0_v5_clean_state_witness_authority()
    durable_witness = durable_issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=admission.commitment_sha256,
        run_id_sha256=_sha(request.run_id),
        authority_commitment_sha256=authority.authority_commitment_sha256,
        scopes=(scope,),
    )
    HmacAtomicManagedMem0V5CleanStateStore(
        path=root / "clean-state.json",
        hmac_key=durable_key,
        issuer=durable_issuer,
        verifier=durable_verifier,
    ).save_original(durable_witness)
    pristine = ManagedMem0V5PristineStateVerifier(
        checkpoint_file=root / "checkpoint.json",
        checkpoint_head_file=root / "head.sqlite3",
        dispatch_journal=root / "dispatch.json",
        durable_clean_state=root / "clean-state.json",
        checkpoint_head_key=head_key,
        durable_clean_state_key=durable_key,
        operation_journal=journal,
        operation_identity=identity,
        operation_manifest=manifest,
        operation_signer=signer,
    )
    return pristine, authority, admission, witness, journal, operation, root


def test_initialized_pre_registration_material_proves_pristine(tmp_path: Path) -> None:
    pristine, authority, admission, witness, *_unused = _material(tmp_path)

    commitment = pristine.prove_pristine(
        authority=authority, admission=admission, clean_state_witness=witness
    )

    assert len(commitment) == 64
    pristine.close()


def test_initialized_empty_checkpoint_head_is_accepted_without_operation_journal(
    tmp_path: Path,
) -> None:
    pristine, authority, admission, _witness, _journal, _operation, root = _material(tmp_path)
    pristine.close()

    require_managed_v5_recovery_pristine_checkpoint_head(
        checkpoint_head_file=root / "head.sqlite3",
        checkpoint_head_secret=b"h" * 64,
        authority=authority,
        admission=admission,
    )


@pytest.mark.parametrize("row_binding", ("expected", "other"))
def test_checkpoint_head_with_any_authenticated_row_is_rejected(
    tmp_path: Path, row_binding: str
) -> None:
    pristine, authority, admission, _witness, _journal, _operation, root = _material(tmp_path)
    pristine.close()
    store = SQLiteManagedMem0V5CheckpointHead(root / "head.sqlite3", hmac_key=b"h" * 64)
    store.compare_and_swap_head(
        authority_commitment_sha256=(
            authority.authority_commitment_sha256
            if row_binding == "expected"
            else _sha("other-authority")
        ),
        admission_commitment_sha256=(
            admission.commitment_sha256 if row_binding == "expected" else _sha("other-admission")
        ),
        expected_commitment_sha256=None,
        next_commitment_sha256=_sha("head"),
    )

    with pytest.raises(ManagedV5RecoveryOperationAuthorityError, match="head_invalid"):
        require_managed_v5_recovery_pristine_checkpoint_head(
            checkpoint_head_file=root / "head.sqlite3",
            checkpoint_head_secret=b"h" * 64,
            authority=authority,
            admission=admission,
        )


def test_arbitrary_checkpoint_head_bytes_are_rejected(tmp_path: Path) -> None:
    pristine, authority, admission, _witness, _journal, _operation, root = _material(tmp_path)
    pristine.close()
    (root / "head.sqlite3").write_bytes(b"not sqlite or authenticated")

    with pytest.raises(ManagedV5RecoveryOperationAuthorityError, match="head_invalid"):
        require_managed_v5_recovery_pristine_checkpoint_head(
            checkpoint_head_file=root / "head.sqlite3",
            checkpoint_head_secret=b"h" * 64,
            authority=authority,
            admission=admission,
        )


def test_checkpoint_head_removed_before_authenticated_open_is_not_recreated(
    tmp_path: Path,
) -> None:
    pristine, authority, admission, _witness, _journal, _operation, root = _material(tmp_path)
    pristine.close()
    head = root / "head.sqlite3"
    head.unlink()

    with pytest.raises(ManagedV5RecoveryOperationAuthorityError, match="head_invalid"):
        require_managed_v5_recovery_pristine_checkpoint_head(
            checkpoint_head_file=head,
            checkpoint_head_secret=b"h" * 64,
            authority=authority,
            admission=admission,
        )

    assert not head.exists()


def test_pristine_proof_rejects_any_operation_dispatch(tmp_path: Path) -> None:
    pristine, authority, admission, witness, journal, operation, _root = _material(tmp_path)
    journal.prepare_dispatch(operation, _sha("request"))

    with pytest.raises(ManagedMem0V5PristineStateError, match="state_invalid"):
        pristine.prove_pristine(
            authority=authority, admission=admission, clean_state_witness=witness
        )


def test_pristine_proof_rejects_dispatch_claim(tmp_path: Path) -> None:
    pristine, authority, admission, witness, _journal, _operation, root = _material(tmp_path)
    create_managed_mem0_v5_single_dispatch_guard(root / "dispatch.json").claim(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_sha("operation"),
        request_body_sha256=_sha("request"),
    )

    with pytest.raises(ManagedMem0V5PristineStateError, match="state_invalid"):
        pristine.prove_pristine(
            authority=authority, admission=admission, clean_state_witness=witness
        )


def test_missing_operation_journal_blocks_without_creating_file(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    journal = root / "operations.sqlite3"

    with pytest.raises(ManagedV5RecoveryOperationAuthorityError, match="state_invalid"):
        _existing_operation_journal(journal, root)

    assert not journal.exists()


def test_pristine_close_wipes_operation_signer_and_forbids_signing(tmp_path: Path) -> None:
    pristine, *_unused = _material(tmp_path)
    signer = pristine._operation_signer
    assert len(signer.sign(b"before-close")) == 64

    pristine.close()
    pristine.close()

    with pytest.raises(Exception, match="signer_closed"):
        signer.sign(b"after-close")
