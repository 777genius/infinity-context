"""Production composition for attested publishable managed-Mem0 extraction."""

from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_adapters.postgres.managed_mem0_v6_sqlite_preparation import (
    SQLiteManagedMem0V6PreparationStore,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
    authenticate_strict_v4_preparation_receipt,
    strict_v4_preparation_key_commitment,
)

from infinity_context_server.memory_comparison_managed_full_run_extraction_ledger import (
    build_managed_full_run_extraction_context,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    ManagedMem0V5ExpectedRuntimeAuthority,
    VerifiedManagedMem0V5RuntimeAttestationValidation,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedMem0V5OperationReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
    Mem0V5ObservedExtractionReceiptVerifier,
)
from infinity_context_server.processes.publishable_full_extraction_composition import (
    open_publishable_full_extraction_worker,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    MANAGED_MEM0_EXTRACTION_NAMESPACE,
    MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
    OpenedPublishableExtractionStores,
    PublishableExtractionRunAuthority,
)
from infinity_context_server.processes.publishable_full_extraction_managed_mem0_v5_http import (
    PublishableManagedMem0V5HttpAdapter,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableFullExtractionWorker,
)
from infinity_context_server.resumable_operation_journal.crypto import (
    HmacSha256OperationJournalSigner,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationReceipt,
    OperationRunIdentity,
    sha256_commitment,
)
from infinity_context_server.resumable_operation_journal.service import (
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal

_JOURNAL_FILE = "publishable-extraction-journal-v4.sqlite3"
_LEDGER_FILE = "publishable-extraction-ledger-v1.sqlite3"


class PublishableFullExtractionCompositionError(RuntimeError):
    """Stable production-composition failure without secret or path reflection."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class PublishableFullExtractionRunConfiguration:
    """Caller-owned capabilities and public authorities for one durable run."""

    preparation_receipt: StrictV4PreparationReceipt
    preparation_authenticator: ProjectionReceiptAuthenticator = field(repr=False)
    preparation_key_authority: StrictV4PreparationKeyIdentityPort = field(repr=False)
    manifest_authority: ManagedMem0V5ManifestAuthority = field(repr=False)
    admission: Mem0OssFullRunAdmission
    runtime_receipt_authority: Mem0V5ObservedExtractionReceiptAuthority = field(repr=False)
    runtime_receipt_verifier: Mem0V5ObservedExtractionReceiptVerifier = field(repr=False)
    http_lane: ManagedMem0V5HttpLane = field(repr=False)
    expected_runtime: ManagedMem0V5ExpectedRuntimeAuthority
    runtime_attestation: VerifiedManagedMem0V5RuntimeAttestationValidation = field(repr=False)
    runtime_target_identity_sha256: str
    state_directory: Path
    journal_hmac_key: bytes = field(repr=False)
    operation_receipt_hmac_key: bytes = field(repr=False)
    ledger_hmac_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        nominal = (
            (self.preparation_receipt, StrictV4PreparationReceipt),
            (self.manifest_authority, ManagedMem0V5ManifestAuthority),
            (self.admission, Mem0OssFullRunAdmission),
            (self.runtime_receipt_authority, Mem0V5ObservedExtractionReceiptAuthority),
            (self.runtime_receipt_verifier, Mem0V5ObservedExtractionReceiptVerifier),
            (self.http_lane, ManagedMem0V5HttpLane),
            (self.expected_runtime, ManagedMem0V5ExpectedRuntimeAuthority),
            (
                self.runtime_attestation,
                VerifiedManagedMem0V5RuntimeAttestationValidation,
            ),
        )
        if (
            any(type(value) is not expected for value, expected in nominal)
            or not _sha(self.runtime_target_identity_sha256)
            or type(self.state_directory) is not Path
            or not self.state_directory.is_absolute()
            or self.state_directory == Path(self.state_directory.anchor)
            or any(
                type(key) is not bytes or len(key) < minimum
                for key, minimum in (
                    (self.journal_hmac_key, 32),
                    (self.operation_receipt_hmac_key, 32),
                    (self.ledger_hmac_key, 32),
                )
            )
            or len(self.operation_receipt_hmac_key) != 32
            or len(
                {
                    hashlib.sha256(key).digest()
                    for key in (
                        self.journal_hmac_key,
                        self.operation_receipt_hmac_key,
                        self.ledger_hmac_key,
                    )
                }
            )
            != 3
            or any(
                not callable(getattr(self.preparation_authenticator, method, None))
                for method in ("sign", "verify")
            )
            or not callable(getattr(self.preparation_key_authority, "resolve", None))
        ):
            _fail("publishable_extraction_configuration_invalid")
        if os.path.lexists(self.state_directory):
            try:
                info = os.lstat(self.state_directory)
            except OSError:
                _fail("publishable_extraction_state_directory_invalid")
            if not self.state_directory.is_dir() or os.path.islink(self.state_directory):
                _fail("publishable_extraction_state_directory_invalid")
            if info.st_uid != os.getuid():
                _fail("publishable_extraction_state_directory_invalid")
        state_files = {
            self.state_directory / _JOURNAL_FILE,
            self.state_directory / _LEDGER_FILE,
        }
        preparation_files = {
            Path(self.preparation_receipt.a1_path),
            Path(self.preparation_receipt.a2_path),
            Path(self.preparation_receipt.expected_index_path),
        }
        if state_files & preparation_files:
            _fail("publishable_extraction_state_path_cross_wire")


@final
class _ExactManifestPolicy:
    __slots__ = ("_identity", "_manifest")

    def __init__(self, identity: OperationRunIdentity, manifest: OperationManifest) -> None:
        self._identity = identity
        self._manifest = manifest

    def validate(
        self,
        *,
        identity: OperationRunIdentity,
        manifest: OperationManifest,
    ) -> None:
        if identity != self._identity or manifest != self._manifest:
            raise OperationJournalError("publishable_extraction_manifest_divergent")


@final
class _ExactOperationReceiptIssuer:
    __slots__ = ("_authority",)

    def __init__(self, authority: ManagedMem0V5OperationReceiptAuthority) -> None:
        self._authority = authority

    def issue(
        self,
        *,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
        result_commitment_sha256: str,
    ) -> OperationReceipt:
        return self._authority._issue_exact(
            identity=identity,
            request_commitment_sha256=request_commitment_sha256,
            result_commitment_sha256=result_commitment_sha256,
        )


def build_publishable_full_extraction_run(
    *,
    configuration: PublishableFullExtractionRunConfiguration,
) -> PublishableFullExtractionWorker:
    """Build one real HTTP-backed worker without contacting its service."""

    if type(configuration) is not PublishableFullExtractionRunConfiguration:
        _fail("publishable_extraction_configuration_invalid")
    configuration.__post_init__()
    receipt = configuration.preparation_receipt
    try:
        authenticate_strict_v4_preparation_receipt(
            receipt,
            authenticator=configuration.preparation_authenticator,
        )
        context = build_managed_full_run_extraction_context(
            preparation_receipt=receipt,
            preparation_authenticator=configuration.preparation_authenticator,
            runtime_binding_commitment_sha256=(
                configuration.expected_runtime.subscription_runtime_binding_commitment_sha256
            ),
        )
    except Exception:
        _fail("publishable_extraction_preparation_invalid")
    manifest = _operation_manifest(configuration)
    identity = _run_identity(configuration, manifest)
    authority = PublishableExtractionRunAuthority(
        journal_identity=identity,
        operation_manifest=manifest,
        runtime_receipt_authority=configuration.runtime_receipt_authority,
        ledger_context=context,
        preparation_receipt_sha256=receipt.receipt_sha256,
        dataset_sha256=receipt.dataset_sha256,
        a2_terminal_commitment_sha256=receipt.a2_authority.terminal_commitment_sha256,
    )
    _require_runtime_verifier_binding(configuration, context.runtime_binding_commitment_sha256)
    boundary = PublishableManagedMem0V5HttpAdapter(
        authority=authority,
        manifest=configuration.manifest_authority,
        admission=configuration.admission,
        lane=configuration.http_lane,
        expected_runtime=configuration.expected_runtime,
        runtime_attestation=configuration.runtime_attestation,
        runtime_target_identity_sha256=configuration.runtime_target_identity_sha256,
    )
    a1_key = _authenticated_a1_key(configuration)

    def open_stores(
        opened_authority: PublishableExtractionRunAuthority,
    ) -> OpenedPublishableExtractionStores:
        if opened_authority != authority:
            _fail("publishable_extraction_authority_cross_wire")
        return _open_stores(
            configuration=configuration,
            authority=authority,
            a1_key=a1_key,
        )

    return open_publishable_full_extraction_worker(
        authority=authority,
        stores_opener=open_stores,
        boundary=boundary,
        runtime_receipt_verifier=configuration.runtime_receipt_verifier,
    )


def _operation_manifest(
    configuration: PublishableFullExtractionRunConfiguration,
) -> OperationManifest:
    request = configuration.admission.request
    receipt = configuration.runtime_receipt_authority
    return OperationManifest(
        tuple(
            LogicalOperationIdentity(
                run_id=request.run_id,
                operation_key=operation.operation_id_sha256,
                operation_kind=MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
                ordinal=ordinal,
                authority_commitment_sha256=(
                    configuration.manifest_authority.authority_commitment_sha256
                ),
            )
            for ordinal, operation in enumerate(receipt.operations)
        )
    )


def _run_identity(
    configuration: PublishableFullExtractionRunConfiguration,
    manifest: OperationManifest,
) -> OperationRunIdentity:
    run_hash = configuration.preparation_receipt.run_id_sha256
    policy = sha256_commitment(
        {
            "domain": "publishable-managed-mem0-v5-extraction-policy.v1",
            "preparation_receipt_sha256": configuration.preparation_receipt.receipt_sha256,
            "manifest_authority_commitment_sha256": (
                configuration.manifest_authority.authority_commitment_sha256
            ),
            "admission_commitment_sha256": configuration.admission.commitment_sha256,
            "runtime_receipt_authority_commitment_sha256": (
                _runtime_receipt_authority_commitment(configuration.runtime_receipt_authority)
            ),
            "expected_runtime_commitment_sha256": sha256_commitment(
                configuration.expected_runtime.public_payload()
            ),
            "runtime_target_identity_sha256": (configuration.runtime_target_identity_sha256),
            "extraction_implementation_sha256": MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
        }
    )
    return OperationRunIdentity(
        run_id=configuration.admission.request.run_id,
        operation_namespace=MANAGED_MEM0_EXTRACTION_NAMESPACE,
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=policy,
        signer_key_id=f"publishable-mem0-v5-journal-{run_hash[:16]}",
        expected_operation_count=len(manifest.operations),
    )


def _runtime_receipt_authority_commitment(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> str:
    header = {
        name: getattr(authority, name)
        for name in authority.__dataclass_fields__
        if name != "operations"
    }
    digest = hashlib.sha256(
        b"publishable-managed-mem0-v5-runtime-receipt-authority/v1\0"
        + bytes.fromhex(sha256_commitment(header))
    )
    for operation in authority.operations:
        digest.update(
            bytes.fromhex(
                sha256_commitment(
                    {name: getattr(operation, name) for name in operation.__dataclass_fields__}
                )
            )
        )
    return digest.hexdigest()


def _require_runtime_verifier_binding(
    configuration: PublishableFullExtractionRunConfiguration,
    runtime_binding_commitment_sha256: str,
) -> None:
    verifier = configuration.runtime_receipt_verifier
    try:
        verifier._require_authority_state()
        verifier_authority = object.__getattribute__(verifier, "_authority")
        runtime_binding = object.__getattribute__(verifier, "_runtime_binding")
        verifier_binding = runtime_binding.commitment_sha256
    except Exception:
        _fail("publishable_extraction_runtime_verifier_invalid")
    if verifier_authority is not configuration.runtime_receipt_authority or not hmac.compare_digest(
        str(verifier_binding), runtime_binding_commitment_sha256
    ):
        _fail("publishable_extraction_runtime_verifier_cross_wire")


def _authenticated_a1_key(
    configuration: PublishableFullExtractionRunConfiguration,
) -> bytes:
    receipt = configuration.preparation_receipt
    try:
        key = configuration.preparation_key_authority.resolve(
            purpose="a1",
            key_id=receipt.a1_key_id,
        )
        observed = strict_v4_preparation_key_commitment(
            key,
            purpose="a1",
            key_id=receipt.a1_key_id,
            artifact_context=f"{receipt.run_id_sha256}:{Path(receipt.a1_path)}",
        )
    except Exception:
        _fail("publishable_extraction_a1_key_invalid")
    if not hmac.compare_digest(observed, receipt.a1_key_commitment_sha256):
        _fail("publishable_extraction_a1_key_invalid")
    return key


def _open_stores(
    *,
    configuration: PublishableFullExtractionRunConfiguration,
    authority: PublishableExtractionRunAuthority,
    a1_key: bytes,
) -> OpenedPublishableExtractionStores:
    a1: SQLiteManagedMem0V6PreparationStore | None = None
    ledger: SQLiteManagedFullRunExtractionLedger | None = None
    try:
        a1 = SQLiteManagedMem0V6PreparationStore.open(
            configuration.preparation_receipt.a1_path,
            authentication_key=a1_key,
        )
        journal_store = SQLiteOperationJournal(
            configuration.state_directory / _JOURNAL_FILE,
            private_directory=configuration.state_directory,
        )
        ledger = SQLiteManagedFullRunExtractionLedger.open_or_create(
            configuration.state_directory / _LEDGER_FILE,
            authentication_key=configuration.ledger_hmac_key,
        )
        signer = HmacSha256OperationJournalSigner(
            key_id=authority.journal_identity.signer_key_id,
            secret=configuration.journal_hmac_key,
        )
        receipt_authority = ManagedMem0V5OperationReceiptAuthority(
            key=configuration.operation_receipt_hmac_key,
            key_id=(
                "publishable-mem0-v5-receipt-"
                + configuration.preparation_receipt.run_id_sha256[:16]
            ),
            manifest=authority.operation_manifest,
        )
        service = ResumableOperationJournalService(
            journal=journal_store,
            signer=signer,
            manifest_policy=_ExactManifestPolicy(
                authority.journal_identity,
                authority.operation_manifest,
            ),
            receipt_verifier=receipt_authority,
            notifications=NullOperationNotification(),
        )
        return OpenedPublishableExtractionStores(
            journal_service=service,
            journal_store=journal_store,
            extraction_ledger=ledger,
            expected_operations=a1,
            operation_receipt_issuer=_ExactOperationReceiptIssuer(receipt_authority),
            close_callbacks=(ledger.close, a1.close),
        )
    except BaseException:
        if ledger is not None:
            with suppress(BaseException):
                ledger.close()
        if a1 is not None:
            with suppress(BaseException):
                a1.close()
        raise


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise PublishableFullExtractionCompositionError(code) from None


__all__ = (
    "PublishableFullExtractionCompositionError",
    "PublishableFullExtractionRunConfiguration",
    "build_publishable_full_extraction_run",
)
