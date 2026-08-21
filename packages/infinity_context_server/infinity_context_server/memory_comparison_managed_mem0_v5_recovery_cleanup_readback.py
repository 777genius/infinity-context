"""Recovery-only fresh pass-two Mem0 cleanup/readback evidence."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationPort,
    CleanupVerificationResult,
    Mem0OssFullRunState,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
    Mem0V5CleanupRequest,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_commitment,
)

RECOVERY_CLEANUP_READBACK_SCHEMA = "managed-mem0-v5.recovery-cleanup-readback.v1"
_DOMAIN = b"infinity-context\0managed-mem0-v5-recovery-cleanup-readback.v1\0"


class ManagedMem0V5RecoveryCleanupReadbackError(RuntimeError):
    """Stable readback failure without response or secret material."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RecoveryCleanupHttpPort(Protocol):
    def cleanup(self, request: Mem0V5CleanupRequest) -> Mem0V5CleanupReceipt: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RecoveryCleanupWitness:
    terminal_state: str
    aborting: bool
    admission_commitment_sha256: str
    cleanup_request_commitment_sha256: str
    cleanup_result_commitment_sha256: str
    terminal_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    expected_operation_count: int
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str
    evidence_commitment_sha256: str
    mac_sha256: str

    def commitment_payload(self) -> dict[str, object]:
        return {
            "schema_version": RECOVERY_CLEANUP_READBACK_SCHEMA,
            "terminal_state": self.terminal_state,
            "aborting": self.aborting,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "cleanup_request_commitment_sha256": self.cleanup_request_commitment_sha256,
            "cleanup_result_commitment_sha256": self.cleanup_result_commitment_sha256,
            "terminal_commitment_sha256": self.terminal_commitment_sha256,
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "operation_inventory_root_sha256": self.operation_inventory_root_sha256,
            "expected_operation_count": self.expected_operation_count,
            "deleted_operation_count": self.deleted_operation_count,
            "residual_record_count": self.residual_record_count,
            "residual_root_sha256": self.residual_root_sha256,
        }

    def payload(self) -> dict[str, object]:
        return {
            **self.commitment_payload(),
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
            "mac_sha256": self.mac_sha256,
        }


@final
class ManagedMem0V5RecoveryCleanupReadback:
    __slots__ = ("_cleanup", "_key", "_used", "_verifier")

    def __init__(
        self,
        *,
        cleanup_port: RecoveryCleanupHttpPort,
        verification_port: CleanupVerificationPort,
        hmac_secret: bytes,
    ) -> None:
        if (
            not callable(getattr(cleanup_port, "cleanup", None))
            or not callable(getattr(verification_port, "verify", None))
            or type(hmac_secret) is not bytes
            or len(hmac_secret) < 32
        ):
            _fail("managed_mem0_v5_recovery_cleanup_inputs_invalid")
        self._cleanup = cleanup_port
        self._verifier = verification_port
        self._key = bytearray(hmac.new(hmac_secret, _DOMAIN, hashlib.sha256).digest())
        self._used = False

    def readback(
        self,
        *,
        request: Mem0V5CleanupRequest,
        terminal: Mem0OssTerminalCleanupEvidence,
    ) -> ManagedMem0V5RecoveryCleanupWitness:
        if self._used:
            _fail("managed_mem0_v5_recovery_cleanup_replayed")
        context = _authority(request=request, terminal=terminal)
        try:
            receipt = self._cleanup.cleanup(request)
            if type(receipt) is not Mem0V5CleanupReceipt:
                raise TypeError
            result = self._verifier.verify(payload=receipt, context=context)
            _result(result=result, context=context)
        except ManagedMem0V5RecoveryCleanupReadbackError:
            raise
        except Exception as error:
            _fail(
                "managed_mem0_v5_recovery_cleanup_call_transient"
                if _transient(error)
                else "managed_mem0_v5_recovery_cleanup_call_failed"
            )
        result_payload = {
            "admission_commitment_sha256": result.admission_commitment_sha256,
            "seal_commitment_sha256": result.seal_commitment_sha256,
            "operation_root_sha256": result.operation_root_sha256,
            "operation_inventory_root_sha256": result.operation_inventory_root_sha256,
            "deleted_operation_count": result.deleted_operation_count,
            "residual_record_count": result.residual_record_count,
            "residual_root_sha256": result.residual_root_sha256,
        }
        base = {
            "schema_version": RECOVERY_CLEANUP_READBACK_SCHEMA,
            "terminal_state": terminal.terminal_state,
            "aborting": context.aborting,
            "admission_commitment_sha256": context.admission_commitment_sha256,
            "cleanup_request_commitment_sha256": cleanup_request_commitment(context),
            "cleanup_result_commitment_sha256": canonical_sha256(result_payload),
            "terminal_commitment_sha256": terminal.commitment_sha256,
            "seal_commitment_sha256": context.seal_commitment_sha256,
            "operation_root_sha256": context.operation_root_sha256,
            "operation_inventory_root_sha256": context.operation_inventory_root_sha256,
            "expected_operation_count": context.expected_operation_count,
            "deleted_operation_count": result.deleted_operation_count,
            "residual_record_count": result.residual_record_count,
            "residual_root_sha256": result.residual_root_sha256,
        }
        digest = canonical_sha256(base)
        witness = ManagedMem0V5RecoveryCleanupWitness(
            **{key: value for key, value in base.items() if key != "schema_version"},
            evidence_commitment_sha256=digest,
            mac_sha256=hmac.new(self._key, digest.encode("ascii"), hashlib.sha256).hexdigest(),
        )
        self._used = True
        return witness

    def authenticate(self, witness: ManagedMem0V5RecoveryCleanupWitness) -> bool:
        return (
            bool(self._key)
            and type(witness) is ManagedMem0V5RecoveryCleanupWitness
            and witness.evidence_commitment_sha256 == canonical_sha256(witness.commitment_payload())
            and is_sha256(witness.mac_sha256)
            and hmac.compare_digest(
                witness.mac_sha256.encode(),
                hmac.new(
                    self._key,
                    witness.evidence_commitment_sha256.encode("ascii"),
                    hashlib.sha256,
                )
                .hexdigest()
                .encode(),
            )
        )

    def close(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0
        self._key.clear()


def _transient(error: BaseException) -> bool:
    current: BaseException | None = error
    for _index in range(8):
        if current is None:
            break
        if "mem0_v5_http_remote_failed" in str(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _authority(*, request: object, terminal: object) -> CleanupVerificationContext:
    if (
        type(request) is not Mem0V5CleanupRequest
        or type(terminal) is not Mem0OssTerminalCleanupEvidence
    ):
        _fail("managed_mem0_v5_recovery_cleanup_authority_invalid")
    request.__post_init__()
    terminal.__post_init__()
    context = CleanupVerificationContext(
        request.admission_commitment_sha256,
        request.seal_commitment_sha256,
        request.operation_root_sha256,
        request.operation_inventory_root_sha256,
        request.expected_operation_count,
        request.aborting,
    )
    expected_state = (
        Mem0OssFullRunState.ABORTED.value if context.aborting else Mem0OssFullRunState.DELETED.value
    )
    expected_key = canonical_sha256(
        {"kind": "cleanup", "binding": cleanup_request_commitment(context)}
    )
    if (
        terminal.terminal_state != expected_state
        or terminal.admission_commitment_sha256 != context.admission_commitment_sha256
        or terminal.seal_commitment_sha256 != context.seal_commitment_sha256
        or terminal.operation_root_sha256 != context.operation_root_sha256
        or terminal.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or not 0 <= terminal.deleted_operation_count <= context.expected_operation_count
        or not 0 <= terminal.provider_observed_extraction_calls <= context.expected_operation_count
        or terminal.residual_record_count != 0
        or terminal.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        or request.idempotency_key != expected_key
    ):
        _fail("managed_mem0_v5_recovery_cleanup_authority_mismatch")
    return context


def _result(*, result: object, context: CleanupVerificationContext) -> None:
    if type(result) is not CleanupVerificationResult:
        _fail("managed_mem0_v5_recovery_cleanup_result_invalid")
    result.__post_init__()
    if (
        result.admission_commitment_sha256 != context.admission_commitment_sha256
        or result.seal_commitment_sha256 != context.seal_commitment_sha256
        or result.operation_root_sha256 != context.operation_root_sha256
        or result.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or not 0 <= result.deleted_operation_count <= context.expected_operation_count
        or result.residual_record_count != 0
        or result.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
    ):
        _fail("managed_mem0_v5_recovery_cleanup_result_mismatch")


def _fail(code: str) -> None:
    raise ManagedMem0V5RecoveryCleanupReadbackError(code)


__all__ = (
    "ManagedMem0V5RecoveryCleanupReadback",
    "ManagedMem0V5RecoveryCleanupReadbackError",
    "ManagedMem0V5RecoveryCleanupWitness",
    "RECOVERY_CLEANUP_READBACK_SCHEMA",
    "RecoveryCleanupHttpPort",
)
