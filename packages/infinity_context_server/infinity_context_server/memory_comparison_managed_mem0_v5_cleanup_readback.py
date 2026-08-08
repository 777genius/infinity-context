"""Fresh pass-two cleanup readback for managed Mem0 v5 evidence."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import InitVar, dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
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

CLEANUP_READBACK_SCHEMA = "managed-mem0-v5.cleanup-readback.v1"
_WITNESS_TOKEN = object()
_WITNESS_KEY = secrets.token_bytes(32)


class ManagedMem0V5IdempotentCleanupReadbackPort(Protocol):
    """Real HTTP integration seam; calling cleanup must perform fresh I/O."""

    def cleanup(self, request: Mem0V5CleanupRequest) -> Mem0V5CleanupReceipt: ...


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5CleanupReadbackWitness:
    pass_index: int
    admission_commitment_sha256: str
    cleanup_request_commitment_sha256: str
    cleanup_result_commitment_sha256: str
    terminal_commitment_sha256: str
    seal_commitment_sha256: str
    operation_root_sha256: str
    operation_inventory_root_sha256: str
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str
    evidence_commitment_sha256: str
    _authentication_sha256: str
    _token: InitVar[object]

    def __post_init__(self, _token: object) -> None:
        if (
            _token is not _WITNESS_TOKEN
            or self.pass_index != 2
            or any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.cleanup_request_commitment_sha256,
                    self.cleanup_result_commitment_sha256,
                    self.terminal_commitment_sha256,
                    self.seal_commitment_sha256,
                    self.operation_root_sha256,
                    self.operation_inventory_root_sha256,
                    self.residual_root_sha256,
                    self.evidence_commitment_sha256,
                )
            )
            or type(self.deleted_operation_count) is not int  # noqa: E721
            or self.deleted_operation_count < 1
            or self.residual_record_count != 0
            or self.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
            or self.evidence_commitment_sha256 != canonical_sha256(self.commitment_payload())
            or not hmac.compare_digest(
                self._authentication_sha256,
                hmac.new(
                    _WITNESS_KEY,
                    self.evidence_commitment_sha256.encode(),
                    hashlib.sha256,
                ).hexdigest(),
            )
        ):
            raise ManagedRunError("managed Mem0 v5 cleanup readback witness is invalid")

    def commitment_payload(self) -> dict[str, object]:
        return {
            "schema_version": CLEANUP_READBACK_SCHEMA,
            "pass_index": self.pass_index,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "cleanup_request_commitment_sha256": self.cleanup_request_commitment_sha256,
            "cleanup_result_commitment_sha256": self.cleanup_result_commitment_sha256,
            "terminal_commitment_sha256": self.terminal_commitment_sha256,
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "operation_inventory_root_sha256": self.operation_inventory_root_sha256,
            "deleted_operation_count": self.deleted_operation_count,
            "residual_record_count": self.residual_record_count,
            "residual_root_sha256": self.residual_root_sha256,
        }

    def public_payload(self) -> dict[str, object]:
        self.__post_init__(_WITNESS_TOKEN)
        return {
            **self.commitment_payload(),
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
        }

    def __repr__(self) -> str:
        return "ManagedMem0V5CleanupReadbackWitness(<opaque>)"


@final
class ManagedMem0V5CleanupPassTwoAdapter:
    """Issue one witness only after a fresh idempotent cleanup readback."""

    __slots__ = ("_cleanup", "_consumed", "_in_flight", "_lock", "_verifier")

    def __init__(
        self,
        *,
        cleanup_port: ManagedMem0V5IdempotentCleanupReadbackPort,
        verification_port: CleanupVerificationPort,
    ) -> None:
        try:
            valid = callable(getattr(cleanup_port, "cleanup", None)) and callable(
                getattr(verification_port, "verify", None)
            )
        except Exception:
            valid = False
        if not valid:
            raise ManagedRunError("managed Mem0 v5 cleanup readback adapter is invalid")
        self._cleanup = cleanup_port
        self._verifier = verification_port
        self._consumed = False
        self._in_flight = False
        self._lock = threading.Lock()

    def readback(
        self,
        *,
        pass_index: int,
        request: Mem0V5CleanupRequest,
        terminal: Mem0OssTerminalCleanupEvidence,
    ) -> ManagedMem0V5CleanupReadbackWitness:
        if pass_index != 2:
            raise ManagedRunError("managed Mem0 v5 cleanup readback pass differs")
        context = _validate_authority(request=request, terminal=terminal)
        with self._lock:
            if self._consumed:
                raise ManagedRunError("managed Mem0 v5 cleanup readback was replayed")
            if self._in_flight:
                raise ManagedRunError("managed Mem0 v5 cleanup readback is in progress")
            self._in_flight = True
        try:
            receipt = self._cleanup.cleanup(request)
        except Exception:
            with self._lock:
                self._in_flight = False
            raise ManagedRunError("managed Mem0 v5 cleanup readback call failed") from None
        try:
            if type(receipt) is not Mem0V5CleanupReceipt:
                raise ManagedRunError("managed Mem0 v5 cleanup readback DTO differs")
            result = self._verifier.verify(payload=receipt, context=context)
            _validate_result(result=result, context=context, terminal=terminal)
        except ManagedRunError:
            with self._lock:
                self._in_flight = False
            raise
        except Exception:
            with self._lock:
                self._in_flight = False
            raise ManagedRunError("managed Mem0 v5 cleanup readback verification failed") from None
        result_commitment = canonical_sha256(_result_payload(result))
        payload = {
            "schema_version": CLEANUP_READBACK_SCHEMA,
            "pass_index": 2,
            "admission_commitment_sha256": context.admission_commitment_sha256,
            "cleanup_request_commitment_sha256": cleanup_request_commitment(context),
            "cleanup_result_commitment_sha256": result_commitment,
            "terminal_commitment_sha256": terminal.commitment_sha256,
            "seal_commitment_sha256": context.seal_commitment_sha256,
            "operation_root_sha256": context.operation_root_sha256,
            "operation_inventory_root_sha256": context.operation_inventory_root_sha256,
            "deleted_operation_count": result.deleted_operation_count,
            "residual_record_count": result.residual_record_count,
            "residual_root_sha256": result.residual_root_sha256,
        }
        witness = ManagedMem0V5CleanupReadbackWitness(
            **{key: value for key, value in payload.items() if key != "schema_version"},
            evidence_commitment_sha256=canonical_sha256(payload),
            _authentication_sha256=hmac.new(
                _WITNESS_KEY,
                canonical_sha256(payload).encode(),
                hashlib.sha256,
            ).hexdigest(),
            _token=_WITNESS_TOKEN,
        )
        with self._lock:
            if not self._in_flight or self._consumed:
                raise ManagedRunError("managed Mem0 v5 cleanup readback state differs")
            self._in_flight = False
            self._consumed = True
        return witness


def _validate_authority(*, request: object, terminal: object) -> CleanupVerificationContext:
    if (
        type(request) is not Mem0V5CleanupRequest
        or type(terminal) is not Mem0OssTerminalCleanupEvidence
    ):
        raise ManagedRunError("managed Mem0 v5 cleanup readback authority is invalid")
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
    expected_idempotency_key = canonical_sha256(
        {"kind": "cleanup", "binding": cleanup_request_commitment(context)}
    )
    if (
        request.aborting
        or terminal.terminal_state != Mem0OssFullRunState.DELETED.value
        or terminal.admission_commitment_sha256 != context.admission_commitment_sha256
        or terminal.seal_commitment_sha256 != context.seal_commitment_sha256
        or terminal.operation_root_sha256 != context.operation_root_sha256
        or terminal.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or terminal.deleted_operation_count != context.expected_operation_count
        or terminal.residual_record_count != 0
        or terminal.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        or request.idempotency_key != expected_idempotency_key
    ):
        raise ManagedRunError("managed Mem0 v5 cleanup readback authority differs")
    return context


def validate_managed_mem0_v5_cleanup_readback_authority(
    *, request: object, terminal: object
) -> None:
    """Validate the complete pass-two authority without consuming or doing I/O."""

    _validate_authority(request=request, terminal=terminal)


def _validate_result(
    *,
    result: object,
    context: CleanupVerificationContext,
    terminal: Mem0OssTerminalCleanupEvidence,
) -> None:
    if type(result) is not CleanupVerificationResult:
        raise ManagedRunError("managed Mem0 v5 cleanup readback result is invalid")
    result.__post_init__()
    if (
        result.admission_commitment_sha256 != context.admission_commitment_sha256
        or result.seal_commitment_sha256 != context.seal_commitment_sha256
        or result.operation_root_sha256 != context.operation_root_sha256
        or result.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or result.deleted_operation_count != context.expected_operation_count
        or result.residual_record_count != 0
        or result.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        or result.deleted_operation_count != terminal.deleted_operation_count
    ):
        raise ManagedRunError("managed Mem0 v5 cleanup readback result differs")


def _result_payload(result: CleanupVerificationResult) -> dict[str, object]:
    return {
        "admission_commitment_sha256": result.admission_commitment_sha256,
        "seal_commitment_sha256": result.seal_commitment_sha256,
        "operation_root_sha256": result.operation_root_sha256,
        "operation_inventory_root_sha256": result.operation_inventory_root_sha256,
        "deleted_operation_count": result.deleted_operation_count,
        "residual_record_count": result.residual_record_count,
        "residual_root_sha256": result.residual_root_sha256,
    }


__all__ = (
    "CLEANUP_READBACK_SCHEMA",
    "ManagedMem0V5CleanupPassTwoAdapter",
    "ManagedMem0V5CleanupReadbackWitness",
    "ManagedMem0V5IdempotentCleanupReadbackPort",
    "validate_managed_mem0_v5_cleanup_readback_authority",
)
