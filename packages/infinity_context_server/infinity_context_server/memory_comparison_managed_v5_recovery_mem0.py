"""Provider-free Mem0 recovery adapter with no dispatch capability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    managed_mem0_v5_expected_clean_state_scopes,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery import (
    ManagedMem0V5RecoveryCoordinatorPort,
    ManagedMem0V5RecoveryError,
    recover_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery_cleanup_readback import (
    ManagedMem0V5RecoveryCleanupReadback,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5CleanupRequest
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_commitment,
)

_NOT_STARTED_SCHEMA = "managed-mem0-v5.recovery-not-started.v1"


class ManagedV5RecoveryMem0Error(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class _CleanSnapshotPort(Protocol):
    def prove_empty_scopes(self, **kwargs: object) -> object: ...


class _CleanVerifierPort(Protocol):
    def authenticate_clean_state(self, witness: object) -> object: ...


class ManagedMem0V5PristineStatePort(Protocol):
    def prove_pristine(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        clean_state_witness: ManagedMem0V5AuthenticatedCleanStateWitness,
    ) -> str: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RecoveryCapabilities:
    cleanup_readback: ManagedMem0V5RecoveryCleanupReadback
    clean_snapshot: _CleanSnapshotPort
    clean_verifier: _CleanVerifierPort

    def __post_init__(self) -> None:
        if (
            type(self.cleanup_readback) is not ManagedMem0V5RecoveryCleanupReadback
            or not callable(getattr(self.clean_snapshot, "prove_empty_scopes", None))
            or not callable(getattr(self.clean_verifier, "authenticate_clean_state", None))
        ):
            _fail("managed_v5_recovery_mem0_capabilities_invalid")


@final
@dataclass(frozen=True, slots=True)
class RecoveryMem0Terminal:
    terminal_state: str
    terminal_commitment_sha256: str
    clean_state_witness_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            self.terminal_state not in {"deleted", "aborted", "not_started"}
            or not _sha(self.terminal_commitment_sha256)
            or (self.terminal_state == "not_started" and not _sha(self.clean_state_witness_sha256))
            or (
                self.terminal_state != "not_started" and self.clean_state_witness_sha256 is not None
            )
        ):
            _fail("managed_v5_recovery_mem0_terminal_invalid")


@final
@dataclass(frozen=True, slots=True)
class RecoveryMem0Readback:
    witness_sha256: str

    def __post_init__(self) -> None:
        if not _sha(self.witness_sha256):
            _fail("managed_v5_recovery_mem0_readback_invalid")


@final
class ManagedV5RecoveryMem0Adapter:
    """Restore/terminalize or prove an exact never-started clean state."""

    __slots__ = (
        "_admission",
        "_authority",
        "_budget",
        "_cleanup",
        "_clean_snapshot",
        "_clean_verifier",
        "_coordinator",
        "_request",
        "_pristine_state",
        "_terminal",
    )

    def __init__(
        self,
        *,
        coordinator: ManagedMem0V5RecoveryCoordinatorPort,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        request: object,
        budget_policy: ManagedMem0V5BudgetPolicy,
        cleanup_readback: ManagedMem0V5RecoveryCleanupReadback,
        clean_snapshot: _CleanSnapshotPort,
        clean_verifier: _CleanVerifierPort,
        pristine_state: ManagedMem0V5PristineStatePort,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(admission) is not Mem0OssFullRunAdmission
            or type(budget_policy) is not ManagedMem0V5BudgetPolicy
            or type(cleanup_readback) is not ManagedMem0V5RecoveryCleanupReadback
            or not callable(getattr(pristine_state, "prove_pristine", None))
        ):
            _fail("managed_v5_recovery_mem0_inputs_invalid")
        self._coordinator = coordinator
        self._authority = authority
        self._admission = admission
        self._request = request
        self._budget = budget_policy
        self._cleanup = cleanup_readback
        self._clean_snapshot = clean_snapshot
        self._clean_verifier = clean_verifier
        self._pristine_state = pristine_state
        self._terminal: Mem0OssTerminalCleanupEvidence | None = None

    def recover(self, *, execution_started: bool) -> RecoveryMem0Terminal:
        try:
            result = recover_managed_mem0_v5(
                coordinator=self._coordinator,
                authority=self._authority,
                request=self._request,
                budget_policy=self._budget,
                execution_started=execution_started,
            )
        except ManagedMem0V5RecoveryError as error:
            raise ManagedV5RecoveryMem0Error(
                error.code, retryable=error.code.endswith("_transient")
            ) from None
        if result.terminal is None:
            return self._prove_not_started(execution_started=execution_started)
        self._terminal = result.terminal
        return RecoveryMem0Terminal(
            result.terminal.terminal_state, result.terminal.commitment_sha256
        )

    def pass_two(self, *, terminal: RecoveryMem0Terminal) -> RecoveryMem0Readback:
        if terminal.terminal_state == "not_started" or self._terminal is None:
            _fail("managed_v5_recovery_mem0_pass_two_invalid")
        evidence = self._terminal
        context = _cleanup_request(evidence, self._authority.operation_count)
        try:
            witness = self._cleanup.readback(request=context, terminal=evidence)
        except Exception as error:
            code = getattr(error, "code", "managed_v5_recovery_mem0_readback_invalid")
            raise ManagedV5RecoveryMem0Error(
                code, retryable=type(code) is str and code.endswith("_transient")
            ) from None
        if not self._cleanup.authenticate(witness):
            _fail("managed_v5_recovery_mem0_readback_invalid")
        return RecoveryMem0Readback(witness.evidence_commitment_sha256)

    def _prove_not_started(self, *, execution_started: bool) -> RecoveryMem0Terminal:
        del execution_started  # absence evidence, not the crash marker, is authoritative
        scopes = managed_mem0_v5_expected_clean_state_scopes(
            authority=self._authority, admission=self._admission
        )
        try:
            witness = self._clean_snapshot.prove_empty_scopes(
                expected_admission_commitment_sha256=self._admission.commitment_sha256,
                expected_run_id_sha256=hashlib.sha256(
                    self._admission.request.run_id.encode()
                ).hexdigest(),
                expected_authority_commitment_sha256=self._authority.authority_commitment_sha256,
                expected_scopes=scopes,
            )
            authenticated = self._clean_verifier.authenticate_clean_state(witness)
        except Exception as error:
            raise ManagedV5RecoveryMem0Error(
                "managed_v5_recovery_mem0_clean_state_transient"
                if _transient(error)
                else "managed_v5_recovery_mem0_clean_state_failed",
                retryable=_transient(error),
            ) from None
        if (
            type(authenticated) is not ManagedMem0V5AuthenticatedCleanStateWitness
            or authenticated is not witness
        ):
            _fail("managed_v5_recovery_mem0_clean_state_invalid")
        witness.__post_init__()
        try:
            pristine_commitment = self._pristine_state.prove_pristine(
                authority=self._authority,
                admission=self._admission,
                clean_state_witness=witness,
            )
        except Exception:
            _fail("managed_v5_recovery_mem0_state_not_pristine")
        if not _sha(pristine_commitment):
            _fail("managed_v5_recovery_mem0_state_not_pristine")
        absence = canonical_sha256(
            {
                "schema_version": _NOT_STARTED_SCHEMA,
                "admission_commitment_sha256": self._admission.commitment_sha256,
                "authority_commitment_sha256": self._authority.authority_commitment_sha256,
                "clean_state_witness_sha256": witness.evidence_commitment_sha256,
                "pristine_state_commitment_sha256": pristine_commitment,
            }
        )
        return RecoveryMem0Terminal("not_started", absence, witness.evidence_commitment_sha256)

    def close(self) -> None:
        self._cleanup.close()


def _cleanup_request(
    terminal: Mem0OssTerminalCleanupEvidence, expected_count: int
) -> Mem0V5CleanupRequest:
    from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
        CleanupVerificationContext,
    )

    context = CleanupVerificationContext(
        terminal.admission_commitment_sha256,
        terminal.seal_commitment_sha256,
        terminal.operation_root_sha256,
        terminal.operation_inventory_root_sha256,
        expected_count,
        terminal.terminal_state == "aborted",
    )
    return Mem0V5CleanupRequest(
        context.admission_commitment_sha256,
        context.seal_commitment_sha256,
        context.operation_root_sha256,
        context.operation_inventory_root_sha256,
        context.expected_operation_count,
        context.aborting,
        canonical_sha256({"kind": "cleanup", "binding": cleanup_request_commitment(context)}),
    )


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _transient(error: BaseException) -> bool:
    current: BaseException | None = error
    for _index in range(8):
        if current is None:
            break
        if "mem0_v5_http_remote_failed" in str(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _fail(code: str) -> None:
    raise ManagedV5RecoveryMem0Error(code)


__all__ = (
    "ManagedMem0V5RecoveryCapabilities",
    "ManagedMem0V5PristineStatePort",
    "ManagedV5RecoveryMem0Adapter",
    "ManagedV5RecoveryMem0Error",
    "RecoveryMem0Readback",
    "RecoveryMem0Terminal",
)
