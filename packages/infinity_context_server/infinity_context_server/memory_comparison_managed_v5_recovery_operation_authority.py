"""Pure reconstruction of the initialized live operation-journal authority."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_head_sqlite import (
    SQLiteManagedMem0V5CheckpointHead,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    inspect_managed_mem0_v5_production_authority,
    issue_managed_mem0_v5_production_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery_pristine import (
    ManagedMem0V5PristineStateVerifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_managed_v5_live_public_composition import (
    ManagedV5LivePublicComposition,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationRunIdentity,
    sha256_commitment,
)
from infinity_context_server.resumable_operation_journal.service import (
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal

_NAMESPACE = "managed_mem0_v5_production"
_KIND = "managed_mem0_v5_extraction"


class ManagedV5RecoveryOperationAuthorityError(RuntimeError):
    pass


@final
class _RecoveryOperationSigner:
    __slots__ = ("_closed", "_key_id", "_secret")

    def __init__(self, *, key_id: str, secret: bytes) -> None:
        if type(key_id) is not str or not key_id or type(secret) is not bytes or len(secret) < 32:
            raise OperationJournalError("operation_journal_signer_invalid")
        self._key_id = key_id
        self._secret = bytearray(secret)
        self._closed = False

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, message: bytes) -> str:
        if self._closed or type(message) is not bytes:
            raise OperationJournalError("operation_journal_signer_closed")
        return hmac.new(bytes(self._secret), message, hashlib.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        if self._closed:
            raise OperationJournalError("operation_journal_signer_closed")
        try:
            return hmac.compare_digest(self.sign(message), signature)
        except (TypeError, UnicodeError):
            return False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._secret[:] = b"\x00" * len(self._secret)
            self._secret.clear()


@final
class _ExactPolicy:
    __slots__ = ("_identity", "_manifest")

    def __init__(self, identity: OperationRunIdentity, manifest: OperationManifest) -> None:
        self._identity = identity
        self._manifest = manifest

    def validate(self, *, identity: OperationRunIdentity, manifest: OperationManifest) -> None:
        if identity != self._identity or manifest != self._manifest:
            _fail("managed_v5_recovery_operation_authority_mismatch")


@final
class _NoReceiptVerifier:
    def verify(self, **_kwargs: object) -> object:
        _fail("managed_v5_recovery_receipt_verification_forbidden")


def require_managed_v5_recovery_pristine_checkpoint_head(
    *,
    checkpoint_head_file: Path,
    checkpoint_head_secret: bytes,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
) -> None:
    """Authenticate an initialized checkpoint-head store and require zero rows."""

    if (
        not isinstance(checkpoint_head_file, Path)
        or not checkpoint_head_file.is_absolute()
        or type(checkpoint_head_secret) is not bytes
        or len(checkpoint_head_secret) < 32
        or type(authority) is not ManagedMem0V5ManifestAuthority
        or type(admission) is not Mem0OssFullRunAdmission
    ):
        _fail("managed_v5_recovery_checkpoint_head_invalid")
    try:
        store = SQLiteManagedMem0V5CheckpointHead(
            checkpoint_head_file,
            hmac_key=checkpoint_head_secret,
            require_existing=True,
        )
        store.require_empty()
        if (
            store.load_head(
                authority_commitment_sha256=authority.authority_commitment_sha256,
                admission_commitment_sha256=admission.commitment_sha256,
            )
            is not None
        ):
            _fail("managed_v5_recovery_checkpoint_head_nonempty")
    except ManagedV5RecoveryOperationAuthorityError:
        raise
    except (ManagedRunError, OSError, TypeError, ValueError):
        _fail("managed_v5_recovery_checkpoint_head_invalid")


def build_managed_v5_recovery_pristine_verifier(
    *,
    public: ManagedV5LivePublicComposition,
    budget_policy: ManagedMem0V5BudgetPolicy,
    operation_signer_secret: bytes,
    checkpoint_head_secret: bytes,
    durable_clean_state_secret: bytes,
    dispatch_journal: object,
    operation_journal: object,
    durable_clean_state: object,
) -> ManagedMem0V5PristineStateVerifier:
    if (
        type(public) is not ManagedV5LivePublicComposition
        or type(budget_policy) is not ManagedMem0V5BudgetPolicy
        or any(
            type(value) is not bytes or len(value) < 32
            for value in (
                operation_signer_secret,
                checkpoint_head_secret,
                durable_clean_state_secret,
            )
        )
    ):
        _fail("managed_v5_recovery_operation_inputs_invalid")
    inputs = public.inputs
    manifest = OperationManifest(
        tuple(
            LogicalOperationIdentity(
                run_id=inputs.request.run_id,
                operation_key=item.operation_id_sha256,
                operation_kind=_KIND,
                ordinal=index,
                authority_commitment_sha256=public.manifest_authority.authority_commitment_sha256,
            )
            for index, item in enumerate(inputs.receipt_authority.operations)
        )
    )
    production = issue_managed_mem0_v5_production_authority(
        cases=inputs.cases,
        current_date=inputs.current_date,
        request=inputs.request,
        composition_binding=inputs.composition_binding,
        origin=inputs.mem0_origin,
        timeout_seconds=inputs.timeout_seconds,
        state_paths=inputs.state_paths,
        credential_paths=inputs.credential_paths,
        runtime_receipt_boundary=inputs.runtime_receipt_boundary,
        trusted_runtime_binding=inputs.trusted_runtime_binding,
        receipt_authority=inputs.receipt_authority,
        operation_manifest=manifest,
        transport=None,
    )
    descriptor = inspect_managed_mem0_v5_production_authority(production)
    signer = _RecoveryOperationSigner(
        key_id=f"managed-mem0-v5-journal-v1-{descriptor.run_id_sha256[:16]}",
        secret=operation_signer_secret,
    )
    token_budget = budget_policy.extraction_token_budget
    budget_commitment = (
        "provider-free-unbounded" if token_budget is None else token_budget.commitment_sha256
    )
    policy = sha256_commitment(
        {
            "domain": "managed-mem0-v5-live-operation-policy.v1",
            "production_authority_commitment_sha256": descriptor.authority_commitment_sha256,
            "extraction_token_budget_commitment_sha256": budget_commitment,
        }
    )
    identity = OperationRunIdentity(
        run_id=inputs.request.run_id,
        operation_namespace=_NAMESPACE,
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=policy,
        signer_key_id=signer.key_id,
        expected_operation_count=len(manifest.operations),
    )
    try:
        service = ResumableOperationJournalService(
            journal=_existing_operation_journal(
                operation_journal, inputs.state_paths.checkpoint.parent
            ),
            signer=signer,
            manifest_policy=_ExactPolicy(identity, manifest),
            receipt_verifier=_NoReceiptVerifier(),
            notifications=NullOperationNotification(),
        )
        return ManagedMem0V5PristineStateVerifier(
            checkpoint_file=inputs.state_paths.checkpoint,
            checkpoint_head_file=inputs.state_paths.local_checkpoint_head,
            dispatch_journal=dispatch_journal,
            durable_clean_state=durable_clean_state,
            checkpoint_head_key=checkpoint_head_secret,
            durable_clean_state_key=durable_clean_state_secret,
            operation_journal=service,
            operation_identity=identity,
            operation_manifest=manifest,
            operation_signer=signer,
        )
    except (OperationJournalError, OSError, TypeError, ValueError):
        _fail("managed_v5_recovery_operation_state_invalid")


def _existing_operation_journal(path: object, state_root: Path) -> SQLiteOperationJournal:
    if (
        type(path) is not Path
        or not path.is_absolute()
        or path.parent != state_root
        or path.name in {"", ".", ".."}
    ):
        _fail("managed_v5_recovery_operation_state_invalid")
    try:
        metadata = path.lstat()
    except OSError:
        _fail("managed_v5_recovery_operation_state_invalid")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        _fail("managed_v5_recovery_operation_state_invalid")
    return SQLiteOperationJournal(path, private_directory=state_root)


def _fail(code: str) -> None:
    raise ManagedV5RecoveryOperationAuthorityError(code)


__all__ = (
    "ManagedV5RecoveryOperationAuthorityError",
    "build_managed_v5_recovery_pristine_verifier",
    "require_managed_v5_recovery_pristine_checkpoint_head",
)
