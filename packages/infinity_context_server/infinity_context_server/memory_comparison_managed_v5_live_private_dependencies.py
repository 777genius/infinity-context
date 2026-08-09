"""Post-readiness private dependency composition for managed-v5 live runs."""

from __future__ import annotations

import hashlib
import hmac
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import final

import httpx
from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialCapabilities,
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    inspect_managed_mem0_v5_production_authority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    _inspect_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_run import (
    create_managed_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_credentials import (
    ManagedV5InfinityCredentialBundle,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    _authenticate_activated_managed_v5_public_run,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_envelope import (
    ManagedV5LivePrivateDependencyError,
    ManagedV5RegistryRecoveryEnvelope,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_observer import (
    ManagedV5LiveRecoveryObserver,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_registration import (
    managed_v5_recovery_recorded_at,
    register_and_observe_managed_v5,
)
from infinity_context_server.memory_comparison_managed_v5_live_secret_snapshot import (
    ManagedV5LiveSecretSnapshotError,
    load_nine_distinct_secrets,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
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
    VerifiedOperationReceipt,
    sha256_commitment,
)
from infinity_context_server.resumable_operation_journal.service import (
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal

_MAX_SECRET_BYTES = 4_096
_OPERATION_NAMESPACE = "managed_mem0_v5_production"
_OPERATION_KIND = "managed_mem0_v5_extraction"
_RECEIPT_DOMAIN = b"managed-mem0-v5-operation-receipt/v1\0"
_RECEIPT_DERIVATION_DOMAIN = b"managed-mem0-v5-operation-receipt-key/v1\0"


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LivePrivateDependencyMaterial:
    """Nominal cycle-free equivalent of live-root runtime dependencies."""

    budget_policy: ManagedMem0V5BudgetPolicy
    clean_state_snapshot_factory: ManagedMem0V5HttpCleanStateSnapshotFactory
    durable_clean_state_factory: ManagedMem0V5HmacDurableCleanStateFactory
    operation_journal: ResumableOperationJournalService
    operation_signer_key_id: str
    operation_policy_commitment_sha256: str
    operation_receipt_authority: ManagedMem0V5OperationReceiptAuthority = field(repr=False)
    mem0_credential_capabilities: ManagedMem0V5CredentialCapabilities = field(repr=False)
    benchmark_registry: ManagedBenchmarkRegistryHttpAdapter
    benchmark_registration: ManagedBenchmarkRunRegistration
    recovery_observer: ManagedV5LiveRecoveryObserver = field(repr=False)
    infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = field(
        default=None, repr=False
    )
    infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        exact = (
            (self.budget_policy, ManagedMem0V5BudgetPolicy),
            (self.clean_state_snapshot_factory, ManagedMem0V5HttpCleanStateSnapshotFactory),
            (self.durable_clean_state_factory, ManagedMem0V5HmacDurableCleanStateFactory),
            (self.operation_journal, ResumableOperationJournalService),
            (self.operation_receipt_authority, ManagedMem0V5OperationReceiptAuthority),
            (self.mem0_credential_capabilities, ManagedMem0V5CredentialCapabilities),
            (self.benchmark_registry, ManagedBenchmarkRegistryHttpAdapter),
            (self.benchmark_registration, ManagedBenchmarkRunRegistration),
            (self.recovery_observer, ManagedV5LiveRecoveryObserver),
        )
        factories = (
            self.infinity_derived_transport_factory,
            self.infinity_cleanup_transport_factory,
        )
        if (
            any(type(value) is not expected for value, expected in exact)
            or type(self.operation_signer_key_id) is not str
            or not self.operation_signer_key_id
            or type(self.operation_policy_commitment_sha256) is not str
            or len(self.operation_policy_commitment_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.operation_policy_commitment_sha256
            )
            or any(value is not None and not callable(value) for value in factories)
        ):
            _fail("material_invalid")


@final
class ManagedMem0V5OperationReceiptAuthority:
    """Issue and verify exact HMAC-sealed internal operation receipts."""

    __slots__ = ("_issued", "_key", "_key_id", "_lock", "_manifest")

    def __init__(
        self,
        *,
        key: bytes,
        key_id: str,
        manifest: OperationManifest,
    ) -> None:
        if (
            type(key) is not bytes
            or len(key) != 32
            or type(key_id) is not str
            or not key_id
            or type(manifest) is not OperationManifest
        ):
            raise OperationJournalError("managed_mem0_v5_receipt_authority_invalid")
        self._key = key
        self._key_id = key_id
        self._manifest = manifest
        self._issued: dict[str, OperationReceipt] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "ManagedMem0V5OperationReceiptAuthority(<sealed>)"

    def __copy__(self) -> object:
        raise TypeError("managed Mem0 v5 receipt authority is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed Mem0 v5 receipt authority is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 receipt authority is nonserializable")

    def _issue_exact(
        self,
        *,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
        result_commitment_sha256: str,
    ) -> OperationReceipt:
        self._require_identity(identity)
        provisional = OperationReceipt(
            run_id=identity.run_id,
            logical_operation_id=identity.logical_operation_id,
            request_commitment_sha256=request_commitment_sha256,
            receipt_id="pending",
            result_commitment_sha256=result_commitment_sha256,
        )
        receipt = OperationReceipt(
            run_id=provisional.run_id,
            logical_operation_id=provisional.logical_operation_id,
            request_commitment_sha256=provisional.request_commitment_sha256,
            receipt_id="m5r_" + self._signature(identity, provisional),
            result_commitment_sha256=provisional.result_commitment_sha256,
        )
        with self._lock:
            existing = self._issued.get(identity.logical_operation_id)
            if existing is not None:
                if existing != receipt:
                    raise OperationJournalError("managed_mem0_v5_receipt_replay_divergent")
                return existing
            self._issued[identity.logical_operation_id] = receipt
        return receipt

    def verify(
        self,
        *,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> VerifiedOperationReceipt:
        if type(identity) is not LogicalOperationIdentity or type(receipt) is not OperationReceipt:
            raise OperationJournalError("managed_mem0_v5_receipt_invalid")
        self._require_identity(identity)
        expected_receipt_id = "m5r_" + self._signature(identity, receipt)
        if (
            receipt.run_id != identity.run_id
            or receipt.logical_operation_id != identity.logical_operation_id
            or not hmac.compare_digest(receipt.receipt_id, expected_receipt_id)
        ):
            raise OperationJournalError("managed_mem0_v5_receipt_authentication_failed")
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id=self._key_id,
            verification_commitment_sha256=sha256_commitment(
                {
                    "domain": "managed-mem0-v5-operation-receipt-verification.v1",
                    "operation_identity": identity.identity_payload(),
                    "receipt": receipt.identity_payload(),
                    "receipt_hmac": expected_receipt_id,
                }
            ),
        )

    def _signature(
        self,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> str:
        payload = sha256_commitment(
            {
                "domain": "managed-mem0-v5-operation-receipt.v1",
                "logical_operation_identity": identity.identity_payload(),
                "logical_operation_id": receipt.logical_operation_id,
                "request_commitment_sha256": receipt.request_commitment_sha256,
                "result_commitment_sha256": receipt.result_commitment_sha256,
                "run_id": receipt.run_id,
            }
        ).encode("ascii")
        return hmac.new(self._key, _RECEIPT_DOMAIN + payload, hashlib.sha256).hexdigest()

    def _require_identity(self, identity: LogicalOperationIdentity) -> None:
        if (
            type(identity) is not LogicalOperationIdentity
            or identity.operation_kind != _OPERATION_KIND
            or identity.run_id != self._manifest.run_id
            or identity.ordinal >= len(self._manifest.operations)
            or self._manifest.operations[identity.ordinal] != identity
        ):
            raise OperationJournalError("managed_mem0_v5_receipt_identity_invalid")


def managed_v5_live_operation_policy_commitment(
    *,
    production_authority_commitment_sha256: str,
    budget_policy: ManagedMem0V5BudgetPolicy,
) -> str:
    """Bind the journal identity to exact production and extraction authorities."""

    if (
        type(production_authority_commitment_sha256) is not str
        or len(production_authority_commitment_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in production_authority_commitment_sha256
        )
        or type(budget_policy) is not ManagedMem0V5BudgetPolicy
    ):
        _fail("operation_policy_invalid")
    token_budget = budget_policy.extraction_token_budget
    budget_commitment = (
        "provider-free-unbounded" if token_budget is None else token_budget.commitment_sha256
    )
    return sha256_commitment(
        {
            "domain": "managed-mem0-v5-live-operation-policy.v1",
            "production_authority_commitment_sha256": (production_authority_commitment_sha256),
            "extraction_token_budget_commitment_sha256": budget_commitment,
        }
    )


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
            raise OperationJournalError("managed_mem0_v5_manifest_policy_divergent")


@final
class _OneShotSecretCapability:
    __slots__ = ("_lock", "_secret")

    def __init__(self, secret: bytes) -> None:
        self._secret: bytes | None = secret
        self._lock = threading.Lock()

    def validate(self) -> None:
        with self._lock:
            if type(self._secret) is not bytes or not 32 <= len(self._secret) <= _MAX_SECRET_BYTES:
                _fail("secret_invalid")

    def consume(self) -> bytes:
        with self._lock:
            secret = self._secret
            self._secret = None
        if type(secret) is not bytes or not 32 <= len(secret) <= _MAX_SECRET_BYTES:
            _fail("secret_terminal")
        return secret


@final
class ManagedV5LivePrivateDependencyFactory:
    """One-shot deferred factory passed through the public-to-private root gate."""

    __slots__ = (
        "_budget_policy",
        "_config",
        "_derived_factory",
        "_lock",
        "_cleanup_factory",
        "_phase",
        "_cleanup_plan",
        "_cleanup_target_authority_sha256",
        "_recovery_authority",
        "_recovery_journal",
        "_recovery_secret_sha256",
    )

    def __init__(
        self,
        *,
        config: ManagedV5LiveConfig,
        budget_policy: ManagedMem0V5BudgetPolicy,
        cleanup_plan: ManagedBenchmarkCleanupPlan,
        cleanup_target_authority_sha256: str,
        recovery_authority: ManagedV5LiveRecoveryAuthority,
        recovery_journal: ManagedV5LiveRecoveryJournalStore,
        recovery_secret_sha256: str,
        infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        factories = (infinity_derived_transport_factory, infinity_cleanup_transport_factory)
        if (
            type(config) is not ManagedV5LiveConfig
            or type(budget_policy) is not ManagedMem0V5BudgetPolicy
            or type(cleanup_plan) is not ManagedBenchmarkCleanupPlan
            or not _is_sha256(cleanup_target_authority_sha256)
            or type(recovery_authority) is not ManagedV5LiveRecoveryAuthority
            or type(recovery_journal) is not ManagedV5LiveRecoveryJournalStore
            or not _is_sha256(recovery_secret_sha256)
            or any(value is not None and not callable(value) for value in factories)
        ):
            _fail("factory_inputs_invalid")
        self._config = config
        self._budget_policy = budget_policy
        self._cleanup_plan = cleanup_plan
        self._cleanup_target_authority_sha256 = cleanup_target_authority_sha256
        self._recovery_authority = recovery_authority
        self._recovery_journal = recovery_journal
        self._recovery_secret_sha256 = recovery_secret_sha256
        self._derived_factory = infinity_derived_transport_factory
        self._cleanup_factory = infinity_cleanup_transport_factory
        self._phase = "pending"
        self._lock = threading.Lock()

    def create(
        self,
        *,
        activated_preparation: object,
        plan: VerifiedManagedRunPlan,
        run_bindings: FullComparisonRunBindings,
        infinity_credentials: ManagedV5InfinityCredentialBundle,
        credential_paths: ManagedMem0V5CredentialPaths,
        deadline: datetime,
        now: datetime,
        clock: Callable[[], datetime],
    ) -> ManagedV5LivePrivateDependencyMaterial:
        with self._lock:
            if self._phase != "pending":
                _fail("factory_terminal")
            self._phase = "active"
        try:
            result = _create_managed_v5_live_private_dependency_material(
                config=self._config,
                activated_preparation=activated_preparation,
                plan=plan,
                run_bindings=run_bindings,
                infinity_credentials=infinity_credentials,
                credential_paths=credential_paths,
                budget_policy=self._budget_policy,
                cleanup_plan=self._cleanup_plan,
                cleanup_target_authority_sha256=self._cleanup_target_authority_sha256,
                recovery_authority=self._recovery_authority,
                recovery_journal=self._recovery_journal,
                recovery_secret_sha256=self._recovery_secret_sha256,
                deadline=deadline,
                now=now,
                clock=clock,
                infinity_derived_transport_factory=self._derived_factory,
                infinity_cleanup_transport_factory=self._cleanup_factory,
            )
        except BaseException:
            with self._lock:
                self._phase = "terminal"
            raise
        with self._lock:
            self._phase = "issued"
        return result

    @property
    def extraction_token_budget(self) -> object:
        """Expose only immutable public budget authority for root cross-checking."""

        return self._budget_policy.extraction_token_budget

    def __repr__(self) -> str:
        return "ManagedV5LivePrivateDependencyFactory(<sealed-one-shot>)"

    def __copy__(self) -> object:
        raise TypeError("managed v5 private dependency factory is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed v5 private dependency factory is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed v5 private dependency factory is nonserializable")


def _create_managed_v5_live_private_dependency_material(
    *,
    config: ManagedV5LiveConfig,
    activated_preparation: object,
    plan: VerifiedManagedRunPlan,
    infinity_credentials: ManagedV5InfinityCredentialBundle,
    credential_paths: ManagedMem0V5CredentialPaths,
    run_bindings: FullComparisonRunBindings,
    budget_policy: ManagedMem0V5BudgetPolicy,
    cleanup_plan: ManagedBenchmarkCleanupPlan,
    cleanup_target_authority_sha256: str,
    recovery_authority: ManagedV5LiveRecoveryAuthority,
    recovery_journal: ManagedV5LiveRecoveryJournalStore,
    recovery_secret_sha256: str,
    deadline: datetime,
    now: datetime,
    clock: Callable[[], datetime],
    infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> ManagedV5LivePrivateDependencyMaterial:
    """Build all private dependencies; registration is the final network effect."""

    factories = (infinity_derived_transport_factory, infinity_cleanup_transport_factory)
    if (
        type(config) is not ManagedV5LiveConfig
        or type(plan) is not VerifiedManagedRunPlan
        or type(infinity_credentials) is not ManagedV5InfinityCredentialBundle
        or type(credential_paths) is not ManagedMem0V5CredentialPaths
        or type(run_bindings) is not FullComparisonRunBindings
        or type(budget_policy) is not ManagedMem0V5BudgetPolicy
        or type(cleanup_plan) is not ManagedBenchmarkCleanupPlan
        or not _is_sha256(cleanup_target_authority_sha256)
        or type(recovery_authority) is not ManagedV5LiveRecoveryAuthority
        or type(recovery_journal) is not ManagedV5LiveRecoveryJournalStore
        or not _is_sha256(recovery_secret_sha256)
        or type(now) is not datetime
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(deadline) is not datetime
        or deadline.tzinfo is None
        or deadline.utcoffset() is None
        or now >= deadline
        or not callable(clock)
        or any(value is not None and not callable(value) for value in factories)
    ):
        _fail("inputs_invalid")
    try:
        activated = _authenticate_activated_managed_v5_public_run(activated_preparation)
        plan_state = _inspect_verified_managed_run_plan(plan)
        expected_bindings = create_managed_comparison_run_bindings(plan)
        descriptor = inspect_managed_mem0_v5_production_authority(activated.production_authority)
        if (
            activated.plan is not plan
            or activated.composition_binding.deadline != deadline
            or plan_state.run_id != activated.request.run_id
            or run_bindings != expected_bindings
        ):
            _fail("run_binding_invalid")
        infinity_credentials._bind_activated_preparation(activated, now=now)
        filesystem = config.filesystem
        credentials, signer_secret, durable_secret = load_nine_distinct_secrets(
            filesystem=filesystem,
            credential_paths=credential_paths,
            recovery_secret_sha256=recovery_secret_sha256,
        )
        signer_key_id = f"managed-mem0-v5-journal-v1-{descriptor.run_id_sha256[:16]}"
        signer = HmacSha256OperationJournalSigner(
            key_id=signer_key_id,
            secret=signer_secret,
        )
        policy_commitment = managed_v5_live_operation_policy_commitment(
            production_authority_commitment_sha256=descriptor.authority_commitment_sha256,
            budget_policy=budget_policy,
        )
        run_identity = OperationRunIdentity(
            run_id=activated.request.run_id,
            operation_namespace=_OPERATION_NAMESPACE,
            manifest_commitment_sha256=activated.operation_manifest.commitment_sha256,
            policy_commitment_sha256=policy_commitment,
            signer_key_id=signer.key_id,
            expected_operation_count=len(activated.operation_manifest.operations),
        )
        receipt_key = hmac.new(
            signer_secret,
            _RECEIPT_DERIVATION_DOMAIN
            + run_identity.manifest_commitment_sha256.encode("ascii")
            + b"\0"
            + descriptor.run_id_sha256.encode("ascii"),
            hashlib.sha256,
        ).digest()
        receipt_authority = ManagedMem0V5OperationReceiptAuthority(
            key=receipt_key,
            key_id=f"managed-mem0-v5-receipt-v1-{descriptor.run_id_sha256[:16]}",
            manifest=activated.operation_manifest,
        )
        journal = SQLiteOperationJournal(
            filesystem.operation_journal,
            private_directory=filesystem.state_root,
        )
        service = ResumableOperationJournalService(
            journal=journal,
            signer=signer,
            manifest_policy=_ExactManifestPolicy(run_identity, activated.operation_manifest),
            receipt_verifier=receipt_authority,
            notifications=NullOperationNotification(),
        )
        service.initialize(run_identity, activated.operation_manifest)
        snapshot_factory = ManagedMem0V5HttpCleanStateSnapshotFactory()
        durable_factory = ManagedMem0V5HmacDurableCleanStateFactory(
            path=filesystem.durable_clean_state,
            hmac_key_capability=_OneShotSecretCapability(durable_secret),
        )
        registry_config = infinity_credentials.issue_benchmark_registry_config(
            now=now,
            clock=clock,
        )
        registry = ManagedBenchmarkRegistryHttpAdapter(registry_config)
    except ManagedV5LivePrivateDependencyError:
        if "credentials" in locals():
            credentials.close()
        raise
    except ManagedV5LiveSecretSnapshotError as error:
        if "credentials" in locals():
            credentials.close()
        _fail(error.code)
    except Exception:
        if "credentials" in locals():
            credentials.close()
        _fail("construction_failed")

    try:
        recovery_journal.append(
            expected_authority=recovery_authority,
            kind="cleanup_plan_prepared",
            recorded_at=managed_v5_recovery_recorded_at(clock()),
            details={
                "cleanup_plan_sha256": cleanup_plan.sha256,
                "cleanup_target_authority_sha256": cleanup_target_authority_sha256,
            },
            cleanup_plan=cleanup_plan,
        )
        registration = _register_final(
            registry,
            cleanup_plan=cleanup_plan,
            recovery_authority=recovery_authority,
            recovery_journal=recovery_journal,
            registry_config=registry_config,
            run_id_sha256=descriptor.run_id_sha256,
            binding_commitment_sha256=run_bindings.binding_commitment_sha256,
            infinity_target_identity_sha256=registry_config.target_identity_sha256,
            space_slug=managed_http_lifecycle_space_slug(activated.request.run_id),
            clock=clock,
        )
        recovery_observer = ManagedV5LiveRecoveryObserver(
            journal=recovery_journal,
            authority=recovery_authority,
            registration=registration,
            registry_factory=lambda: ManagedBenchmarkRegistryHttpAdapter(registry_config),
            clock=clock,
        )
    except BaseException:
        credentials.close()
        raise
    return _material_after_registration(
        budget_policy=budget_policy,
        clean_state_snapshot_factory=snapshot_factory,
        durable_clean_state_factory=durable_factory,
        operation_journal=service,
        operation_signer_key_id=signer.key_id,
        operation_policy_commitment_sha256=policy_commitment,
        operation_receipt_authority=receipt_authority,
        mem0_credential_capabilities=credentials,
        benchmark_registry=registry,
        benchmark_registration=registration,
        recovery_observer=recovery_observer,
        infinity_derived_transport_factory=infinity_derived_transport_factory,
        infinity_cleanup_transport_factory=infinity_cleanup_transport_factory,
    )


def _material_after_registration(
    *,
    budget_policy: ManagedMem0V5BudgetPolicy,
    clean_state_snapshot_factory: ManagedMem0V5HttpCleanStateSnapshotFactory,
    durable_clean_state_factory: ManagedMem0V5HmacDurableCleanStateFactory,
    operation_journal: ResumableOperationJournalService,
    operation_signer_key_id: str,
    operation_policy_commitment_sha256: str,
    operation_receipt_authority: ManagedMem0V5OperationReceiptAuthority,
    mem0_credential_capabilities: ManagedMem0V5CredentialCapabilities,
    benchmark_registry: ManagedBenchmarkRegistryHttpAdapter,
    benchmark_registration: ManagedBenchmarkRunRegistration,
    recovery_observer: ManagedV5LiveRecoveryObserver,
    infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None,
    infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None,
) -> ManagedV5LivePrivateDependencyMaterial:
    """Transfer registration ownership or prove/reveal its recovery path."""

    try:
        return ManagedV5LivePrivateDependencyMaterial(
            budget_policy=budget_policy,
            clean_state_snapshot_factory=clean_state_snapshot_factory,
            durable_clean_state_factory=durable_clean_state_factory,
            operation_journal=operation_journal,
            operation_signer_key_id=operation_signer_key_id,
            operation_policy_commitment_sha256=operation_policy_commitment_sha256,
            operation_receipt_authority=operation_receipt_authority,
            mem0_credential_capabilities=mem0_credential_capabilities,
            benchmark_registry=benchmark_registry,
            benchmark_registration=benchmark_registration,
            recovery_observer=recovery_observer,
            infinity_derived_transport_factory=infinity_derived_transport_factory,
            infinity_cleanup_transport_factory=infinity_cleanup_transport_factory,
        )
    except BaseException:
        mem0_credential_capabilities.close()
        recovery_envelope = _abort_registered_material(
            benchmark_registry,
            benchmark_registration,
            primary_reason_code=(
                "managed_v5_live_private_dependencies_material_construction_failed"
            ),
        )
        failure = ManagedV5LivePrivateDependencyError(
            "managed_v5_live_private_dependencies_material_construction_failed",
            recovery_envelope=recovery_envelope,
        )
        if recovery_envelope is not None:
            failure.add_note("managed_benchmark_registry_cleanup_required")
        raise failure from None


def _abort_registered_material(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    registration: ManagedBenchmarkRunRegistration,
    *,
    primary_reason_code: str,
) -> ManagedV5RegistryRecoveryEnvelope | None:
    receipt: ManagedBenchmarkCleanupReceipt | ManagedBenchmarkPersistedCleanupReceipt | None = None
    try:
        if registration.state != "active":
            return _known_recovery_envelope(
                registry=registry,
                registration=registration,
                cleanup_receipt=None,
                stage="awaiting_projection_cleanup",
                primary_reason_code=primary_reason_code,
            )
        receipt = registry.cleanup_receipt
        if receipt is None:
            receipt = registry.begin_cleanup()
    except BaseException:
        current_receipt = receipt
        with suppress(BaseException):
            current_receipt = registry.cleanup_receipt or current_receipt
        return _known_recovery_envelope(
            registry=registry,
            registration=registration,
            cleanup_receipt=current_receipt,
            stage="begin_cleanup",
            primary_reason_code=primary_reason_code,
        )
    if receipt.projection_cleanup != "blocked":
        return _known_recovery_envelope(
            registry=registry,
            registration=registration,
            cleanup_receipt=receipt,
            stage="awaiting_projection_cleanup",
            primary_reason_code=primary_reason_code,
        )
    try:
        registry.finalize_unsealed_abort(
            cleanup_initiation_receipt_sha256=receipt.receipt_sha256,
        )
    except BaseException:
        current_receipt = receipt
        with suppress(BaseException):
            current_receipt = registry.cleanup_receipt or current_receipt
        return _known_recovery_envelope(
            registry=registry,
            registration=registration,
            cleanup_receipt=current_receipt,
            stage="finalize_unsealed_abort",
            primary_reason_code=primary_reason_code,
        )
    return None


def _known_recovery_envelope(
    *,
    registry: ManagedBenchmarkRegistryHttpAdapter,
    registration: ManagedBenchmarkRunRegistration,
    cleanup_receipt: ManagedBenchmarkCleanupReceipt
    | ManagedBenchmarkPersistedCleanupReceipt
    | None,
    stage: str,
    primary_reason_code: str,
) -> ManagedV5RegistryRecoveryEnvelope:
    return ManagedV5RegistryRecoveryEnvelope(
        stage=stage,
        primary_reason_code=primary_reason_code,
        run_id_sha256=registration.run_id_sha256,
        binding_commitment_sha256=registration.binding_commitment_sha256,
        infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
        space_slug=registration.space_slug,
        registration=registration,
        cleanup_receipt=cleanup_receipt,
        recovery_registry=registry,
    )


def _register_final(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    *,
    cleanup_plan: ManagedBenchmarkCleanupPlan,
    recovery_authority: ManagedV5LiveRecoveryAuthority,
    recovery_journal: ManagedV5LiveRecoveryJournalStore,
    registry_config: ManagedBenchmarkRegistryHttpConfig,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    infinity_target_identity_sha256: str,
    space_slug: str,
    clock: Callable[[], datetime],
) -> ManagedBenchmarkRunRegistration:
    try:
        return register_and_observe_managed_v5(
            registry,
            cleanup_plan=cleanup_plan,
            recovery_authority=recovery_authority,
            recovery_journal=recovery_journal,
            registry_config=registry_config,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
            clock=clock,
        )
    except Exception:
        recovery = registry if registry.cleanup_required else None
        if recovery is None:
            with suppress(Exception):
                registry.close()
        envelope = None
        if recovery is not None:
            envelope = ManagedV5RegistryRecoveryEnvelope(
                stage="registration_outcome_unknown",
                primary_reason_code=("managed_v5_live_private_dependencies_registration_failed"),
                run_id_sha256=run_id_sha256,
                binding_commitment_sha256=binding_commitment_sha256,
                infinity_target_identity_sha256=infinity_target_identity_sha256,
                space_slug=space_slug,
                recovery_registry=recovery,
            )
        failure = ManagedV5LivePrivateDependencyError(
            "managed_v5_live_private_dependencies_registration_failed",
            recovery_envelope=envelope,
        )
        if recovery is not None:
            failure.add_note("managed_benchmark_registry_cleanup_required")
        raise failure from None


def _fail(suffix: str) -> None:
    raise ManagedV5LivePrivateDependencyError(
        f"managed_v5_live_private_dependencies_{suffix}"
    ) from None


__all__ = (
    "ManagedMem0V5OperationReceiptAuthority",
    "ManagedV5LivePrivateDependencyFactory",
    "ManagedV5LivePrivateDependencyError",
    "ManagedV5LivePrivateDependencyMaterial",
    "ManagedV5RegistryRecoveryEnvelope",
)
