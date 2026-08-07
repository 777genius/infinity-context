"""Authenticated restart checkpoint for the managed Mem0 OSS v5 lane."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunError,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssFailedReceiptEvidence,
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    Mem0OssTerminalBasis,
    cleanup_request_commitment,
)

_SCHEMA = "managed-mem0-v5-checkpoint.v2"
_DOMAIN = b"managed-mem0-v5-checkpoint/v2\0"
_MAX_BYTES = 8_000_000


class ManagedMem0V5CheckpointError(RuntimeError):
    """Fixed error that never reflects checkpoint or credential material."""


class ManagedMem0V5CheckpointPhase(StrEnum):
    RESERVED = "reserved"
    DISPATCH_ATTEMPTED = "dispatch_attempted"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECEIPT_VERIFIED = "receipt_verified"
    STORAGE_VERIFIED = "storage_verified"
    COMMITTED = "committed"


class ManagedMem0V5RunPhase(StrEnum):
    ACTIVE = "active"
    SEALED = "sealed"
    CLEANUP_ATTEMPTED = "cleanup_attempted"
    TERMINAL = "terminal"


class ManagedMem0V5RecoveryAction(StrEnum):
    DISPATCH = "dispatch"
    STATUS = "status"
    STORAGE = "storage"
    COMMIT_LOCAL = "commit_local"
    NONE = "none"


_ACTION = {
    ManagedMem0V5CheckpointPhase.RESERVED: ManagedMem0V5RecoveryAction.DISPATCH,
    ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED: ManagedMem0V5RecoveryAction.STATUS,
    ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN: ManagedMem0V5RecoveryAction.STATUS,
    ManagedMem0V5CheckpointPhase.RECEIPT_VERIFIED: ManagedMem0V5RecoveryAction.STORAGE,
    ManagedMem0V5CheckpointPhase.STORAGE_VERIFIED: ManagedMem0V5RecoveryAction.COMMIT_LOCAL,
    ManagedMem0V5CheckpointPhase.COMMITTED: ManagedMem0V5RecoveryAction.NONE,
}
_ORDER = {
    ManagedMem0V5CheckpointPhase.RESERVED: 0,
    ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED: 1,
    ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN: 1,
    ManagedMem0V5CheckpointPhase.RECEIPT_VERIFIED: 2,
    ManagedMem0V5CheckpointPhase.STORAGE_VERIFIED: 3,
    ManagedMem0V5CheckpointPhase.COMMITTED: 4,
}


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5CheckpointUnit:
    unit_index: int
    operation_id_sha256: str
    phase: ManagedMem0V5CheckpointPhase
    provider_receipt_commitment_sha256: str | None = None
    observation_commitment_sha256: str | None = None
    record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.unit_index) is not int
            or not 0 <= self.unit_index < 10_000
            or not is_sha256(self.operation_id_sha256)
            or type(self.phase) is not ManagedMem0V5CheckpointPhase
            or type(self.record_ids) is not tuple
            or any(not _safe_id(item) for item in self.record_ids)
            or len(set(self.record_ids)) != len(self.record_ids)
        ):
            _fail("managed_mem0_v5_checkpoint_unit_invalid")
        receipt = self.provider_receipt_commitment_sha256
        observation = self.observation_commitment_sha256
        if self.phase in {
            ManagedMem0V5CheckpointPhase.RESERVED,
            ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED,
            ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN,
        }:
            valid = receipt is None and observation is None and not self.record_ids
        elif self.phase is ManagedMem0V5CheckpointPhase.RECEIPT_VERIFIED:
            valid = is_sha256(receipt) and observation is None and not self.record_ids
        else:
            valid = is_sha256(receipt) and is_sha256(observation)
        if not valid:
            _fail("managed_mem0_v5_checkpoint_unit_phase_invalid")

    @property
    def recovery_action(self) -> ManagedMem0V5RecoveryAction:
        return _ACTION[self.phase]

    def payload(self) -> dict[str, object]:
        return {
            "unit_index": self.unit_index,
            "operation_id_sha256": self.operation_id_sha256,
            "phase": self.phase.value,
            "provider_receipt_commitment_sha256": self.provider_receipt_commitment_sha256,
            "observation_commitment_sha256": self.observation_commitment_sha256,
            "record_ids": list(self.record_ids),
        }


class ManagedMem0V5CheckpointSignerPort(Protocol):
    def sign(self, message: bytes) -> str: ...
    def verify(self, message: bytes, signature: str) -> bool: ...


@final
class HmacSha256ManagedMem0V5CheckpointSigner:
    __slots__ = ("_key",)

    def __init__(self, *, key: bytes) -> None:
        if type(key) is not bytes or len(key) < 32:
            _fail("managed_mem0_v5_checkpoint_key_invalid")
        self._key = hmac.new(key, _DOMAIN, hashlib.sha256).digest()

    def sign(self, message: bytes) -> str:
        if type(message) is not bytes:
            _fail("managed_mem0_v5_checkpoint_message_invalid")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        return bool(is_sha256(signature)) and hmac.compare_digest(
            self.sign(message).encode(), signature.encode()
        )


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5Checkpoint:
    authority_commitment_sha256: str
    admission_commitment_sha256: str
    generation: int
    previous_checkpoint_commitment_sha256: str | None
    units: tuple[ManagedMem0V5CheckpointUnit, ...]
    run_phase: ManagedMem0V5RunPhase
    seal: Mem0OssRunSeal | None
    cleanup_context: CleanupVerificationContext | None
    cleanup_request_commitment_sha256: str | None
    terminal_basis: Mem0OssTerminalBasis | None
    terminal_evidence: Mem0OssTerminalCleanupEvidence | None
    checkpoint_commitment_sha256: str
    checkpoint_hmac_sha256: str
    schema_version: str = _SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA
            or not is_sha256(self.authority_commitment_sha256)
            or not is_sha256(self.admission_commitment_sha256)
            or type(self.generation) is not int
            or self.generation < 0
            or (
                self.previous_checkpoint_commitment_sha256 is not None
                and not is_sha256(self.previous_checkpoint_commitment_sha256)
            )
            or (self.generation == 0) != (self.previous_checkpoint_commitment_sha256 is None)
            or type(self.units) is not tuple
            or not 1 <= len(self.units) <= 10_000
            or any(type(item) is not ManagedMem0V5CheckpointUnit for item in self.units)
            or tuple(item.unit_index for item in self.units) != tuple(range(len(self.units)))
            or len({item.operation_id_sha256 for item in self.units}) != len(self.units)
            or type(self.run_phase) is not ManagedMem0V5RunPhase
            or not is_sha256(self.checkpoint_commitment_sha256)
            or not is_sha256(self.checkpoint_hmac_sha256)
            or self.checkpoint_commitment_sha256 != canonical_sha256(self.commitment_payload())
        ):
            _fail("managed_mem0_v5_checkpoint_invalid")
        requires_committed = self.run_phase is ManagedMem0V5RunPhase.SEALED or (
            self.cleanup_context is not None and not self.cleanup_context.aborting
        )
        if requires_committed and any(
            item.phase is not ManagedMem0V5CheckpointPhase.COMMITTED for item in self.units
        ):
            _fail("managed_mem0_v5_checkpoint_seal_invalid")
        if not _valid_run_payload(self):
            _fail("managed_mem0_v5_checkpoint_run_invalid")

    @classmethod
    def create(
        cls,
        *,
        authority_commitment_sha256: str,
        admission_commitment_sha256: str,
        generation: int,
        previous_checkpoint_commitment_sha256: str | None,
        units: tuple[ManagedMem0V5CheckpointUnit, ...],
        run_phase: ManagedMem0V5RunPhase = ManagedMem0V5RunPhase.ACTIVE,
        seal: Mem0OssRunSeal | None = None,
        cleanup_context: CleanupVerificationContext | None = None,
        cleanup_request_commitment_sha256: str | None = None,
        terminal_basis: Mem0OssTerminalBasis | None = None,
        terminal_evidence: Mem0OssTerminalCleanupEvidence | None = None,
        signer: ManagedMem0V5CheckpointSignerPort,
    ) -> ManagedMem0V5Checkpoint:
        base = {
            "schema_version": _SCHEMA,
            "authority_commitment_sha256": authority_commitment_sha256,
            "admission_commitment_sha256": admission_commitment_sha256,
            "generation": generation,
            "previous_checkpoint_commitment_sha256": previous_checkpoint_commitment_sha256,
            "units": [item.payload() for item in units],
            "run_phase": run_phase.value,
            "seal": None if seal is None else seal.payload(),
            "cleanup_context": _cleanup_context_payload(cleanup_context),
            "cleanup_request_commitment_sha256": cleanup_request_commitment_sha256,
            "terminal_basis": None if terminal_basis is None else terminal_basis.public_payload(),
            "terminal_evidence": (
                None if terminal_evidence is None else terminal_evidence.public_payload()
            ),
        }
        commitment = canonical_sha256(base)
        signature = signer.sign(_signed_bytes({**base, "checkpoint_commitment_sha256": commitment}))
        return cls(
            authority_commitment_sha256,
            admission_commitment_sha256,
            generation,
            previous_checkpoint_commitment_sha256,
            units,
            run_phase,
            seal,
            cleanup_context,
            cleanup_request_commitment_sha256,
            terminal_basis,
            terminal_evidence,
            commitment,
            signature,
        )

    def commitment_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "generation": self.generation,
            "previous_checkpoint_commitment_sha256": self.previous_checkpoint_commitment_sha256,
            "units": [item.payload() for item in self.units],
            "run_phase": self.run_phase.value,
            "seal": None if self.seal is None else self.seal.payload(),
            "cleanup_context": _cleanup_context_payload(self.cleanup_context),
            "cleanup_request_commitment_sha256": self.cleanup_request_commitment_sha256,
            "terminal_basis": (
                None if self.terminal_basis is None else self.terminal_basis.public_payload()
            ),
            "terminal_evidence": (
                None if self.terminal_evidence is None else self.terminal_evidence.public_payload()
            ),
        }

    def signed_payload(self) -> dict[str, object]:
        return {
            **self.commitment_payload(),
            "checkpoint_commitment_sha256": self.checkpoint_commitment_sha256,
        }

    def payload(self) -> dict[str, object]:
        return {**self.signed_payload(), "checkpoint_hmac_sha256": self.checkpoint_hmac_sha256}

    def recovery_plan(self) -> tuple[ManagedMem0V5RecoveryAction, ...]:
        return tuple(item.recovery_action for item in self.units)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(generation={self.generation!r}, "
            f"checkpoint_commitment_sha256={self.checkpoint_commitment_sha256!r}, "
            f"unit_count={len(self.units)!r})"
        )


class ManagedMem0V5CheckpointStorePort(Protocol):
    def load(
        self,
        *,
        expected_authority_commitment_sha256: str,
        expected_admission_commitment_sha256: str,
        expected_checkpoint_commitment_sha256: str | None = None,
    ) -> ManagedMem0V5Checkpoint | None: ...
    def save(
        self,
        checkpoint: ManagedMem0V5Checkpoint,
        *,
        expected_previous_commitment_sha256: str | None,
    ) -> None: ...


@final
class AtomicJsonManagedMem0V5CheckpointStore:
    """Dirfd-pinned atomic store; rollback needs a caller-held expected head."""

    __slots__ = ("_dirfd", "_lock_name", "_name", "_signer")

    def __init__(self, *, path: Path, signer: ManagedMem0V5CheckpointSignerPort) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or not _signer(signer)
        ):
            _fail("managed_mem0_v5_checkpoint_store_invalid")
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self._dirfd = os.open(path.parent, flags)
            directory = os.fstat(self._dirfd)
            if (
                not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) & 0o077
            ):
                raise OSError
        except OSError:
            _fail("managed_mem0_v5_checkpoint_path_invalid")
        self._name = path.name
        self._lock_name = path.name + ".lock"
        self._signer = signer

    def __del__(self) -> None:
        descriptor = getattr(self, "_dirfd", -1)
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
            self._dirfd = -1

    def load(
        self,
        *,
        expected_authority_commitment_sha256: str,
        expected_admission_commitment_sha256: str,
        expected_checkpoint_commitment_sha256: str | None = None,
    ) -> ManagedMem0V5Checkpoint | None:
        with self._locked():
            return self._load_unlocked(
                expected_authority_commitment_sha256=expected_authority_commitment_sha256,
                expected_admission_commitment_sha256=expected_admission_commitment_sha256,
                expected_checkpoint_commitment_sha256=expected_checkpoint_commitment_sha256,
            )

    def _load_unlocked(
        self,
        *,
        expected_authority_commitment_sha256: str,
        expected_admission_commitment_sha256: str,
        expected_checkpoint_commitment_sha256: str | None = None,
    ) -> ManagedMem0V5Checkpoint | None:
        if not is_sha256(expected_authority_commitment_sha256) or not is_sha256(
            expected_admission_commitment_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_binding_invalid")
        if expected_checkpoint_commitment_sha256 is not None and not is_sha256(
            expected_checkpoint_commitment_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_binding_invalid")
        try:
            raw = self._read_state()
        except FileNotFoundError:
            if expected_checkpoint_commitment_sha256 is not None:
                _fail("managed_mem0_v5_checkpoint_missing")
            return None
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ManagedMem0V5CheckpointError("managed_mem0_v5_checkpoint_corrupt") from None
        checkpoint = _from_payload(value)
        if not self._signer.verify(
            _signed_bytes(checkpoint.signed_payload()), checkpoint.checkpoint_hmac_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_unauthenticated")
        if (
            checkpoint.authority_commitment_sha256 != expected_authority_commitment_sha256
            or checkpoint.admission_commitment_sha256 != expected_admission_commitment_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_binding_invalid")
        if (
            expected_checkpoint_commitment_sha256 is not None
            and checkpoint.checkpoint_commitment_sha256 != expected_checkpoint_commitment_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_rollback_detected")
        return checkpoint

    def save(
        self,
        checkpoint: ManagedMem0V5Checkpoint,
        *,
        expected_previous_commitment_sha256: str | None,
    ) -> None:
        if type(checkpoint) is not ManagedMem0V5Checkpoint:
            _fail("managed_mem0_v5_checkpoint_store_invalid")
        if not self._signer.verify(
            _signed_bytes(checkpoint.signed_payload()), checkpoint.checkpoint_hmac_sha256
        ):
            _fail("managed_mem0_v5_checkpoint_unauthenticated")
        with self._locked():
            current = self._load_unlocked(
                expected_authority_commitment_sha256=checkpoint.authority_commitment_sha256,
                expected_admission_commitment_sha256=checkpoint.admission_commitment_sha256,
            )
            if current is None:
                if expected_previous_commitment_sha256 is not None or checkpoint.generation != 0:
                    _fail("managed_mem0_v5_checkpoint_conflict")
            else:
                if (
                    expected_previous_commitment_sha256 != current.checkpoint_commitment_sha256
                    or checkpoint.previous_checkpoint_commitment_sha256
                    != current.checkpoint_commitment_sha256
                    or checkpoint.generation != current.generation + 1
                ):
                    _fail("managed_mem0_v5_checkpoint_conflict")
                _forward_only(current, checkpoint)
            self._write_state(checkpoint.payload())

    def _read_state(self) -> str:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self._name, flags, dir_fd=self._dirfd)
        except FileNotFoundError:
            raise
        except OSError:
            raise ManagedMem0V5CheckpointError("managed_mem0_v5_checkpoint_path_invalid") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or not 1 <= opened.st_size <= _MAX_BYTES:
                _fail("managed_mem0_v5_checkpoint_corrupt")
            content = bytearray()
            while len(content) <= _MAX_BYTES:
                chunk = os.read(descriptor, min(65_536, _MAX_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            if len(content) != opened.st_size or len(content) > _MAX_BYTES:
                _fail("managed_mem0_v5_checkpoint_corrupt")
            return bytes(content).decode("utf-8")
        finally:
            os.close(descriptor)

    def _write_state(self, payload: dict[str, object]) -> None:
        rendered = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode()
        if not 1 <= len(rendered) <= _MAX_BYTES:
            _fail("managed_mem0_v5_checkpoint_corrupt")
        temporary = f".{self._name}.{secrets.token_hex(16)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=self._dirfd)
            view = memoryview(rendered)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary,
                self._name,
                src_dir_fd=self._dirfd,
                dst_dir_fd=self._dirfd,
            )
            os.fsync(self._dirfd)
        except OSError:
            raise ManagedMem0V5CheckpointError("managed_mem0_v5_checkpoint_write_failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=self._dirfd)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(self._lock_name, flags, 0o600, dir_fd=self._dirfd)
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                _fail("managed_mem0_v5_checkpoint_path_invalid")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = os.stat(self._lock_name, dir_fd=self._dirfd, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                _fail("managed_mem0_v5_checkpoint_lock_replaced")
            yield
            current = os.stat(self._lock_name, dir_fd=self._dirfd, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                _fail("managed_mem0_v5_checkpoint_lock_replaced")
        except ManagedMem0V5CheckpointError:
            raise
        except OSError:
            raise ManagedMem0V5CheckpointError("managed_mem0_v5_checkpoint_lock_failed") from None
        finally:
            if descriptor is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)


def _cleanup_context_payload(value: CleanupVerificationContext | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "admission_commitment_sha256": value.admission_commitment_sha256,
        "seal_commitment_sha256": value.seal_commitment_sha256,
        "operation_root_sha256": value.operation_root_sha256,
        "operation_inventory_root_sha256": value.operation_inventory_root_sha256,
        "expected_operation_count": value.expected_operation_count,
        "aborting": value.aborting,
    }


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail("managed_mem0_v5_checkpoint_corrupt")
    return value


def _seal_from_payload(value: object) -> Mem0OssRunSeal | None:
    if value is None:
        return None
    raw = _exact(
        value,
        {
            "admission_commitment_sha256",
            "operation_count",
            "ingestion_root_sha256",
            "operation_root_sha256",
            "provider_observed_extraction_calls",
            "provider_observed_request_tokens",
            "provider_observed_response_tokens",
        },
    )
    return Mem0OssRunSeal(**raw)


def _cleanup_context_from_payload(value: object) -> CleanupVerificationContext | None:
    if value is None:
        return None
    raw = _exact(
        value,
        {
            "admission_commitment_sha256",
            "seal_commitment_sha256",
            "operation_root_sha256",
            "operation_inventory_root_sha256",
            "expected_operation_count",
            "aborting",
        },
    )
    return CleanupVerificationContext(**raw)


def _failed_receipts(value: object) -> tuple[Mem0OssFailedReceiptEvidence, ...]:
    if type(value) is not list:
        _fail("managed_mem0_v5_checkpoint_corrupt")
    keys = {
        "operation_id_sha256",
        "unit_index",
        "disposition",
        "provider_receipt_sha256",
        "extraction_calls",
        "request_tokens",
        "response_tokens",
    }
    return tuple(Mem0OssFailedReceiptEvidence(**_exact(item, keys)) for item in value)


def _terminal_basis_from_payload(value: object) -> Mem0OssTerminalBasis | None:
    if value is None:
        return None
    raw = _exact(
        value,
        {
            "terminal_state",
            "cleanup_context",
            "provider_observed_extraction_calls",
            "provider_observed_request_tokens",
            "provider_observed_response_tokens",
            "failed_receipts",
        },
    )
    return Mem0OssTerminalBasis(
        terminal_state=raw["terminal_state"],
        cleanup_context=_cleanup_context_from_payload(raw["cleanup_context"]),
        provider_observed_extraction_calls=raw["provider_observed_extraction_calls"],
        provider_observed_request_tokens=raw["provider_observed_request_tokens"],
        provider_observed_response_tokens=raw["provider_observed_response_tokens"],
        failed_receipts=_failed_receipts(raw["failed_receipts"]),
    )


def _terminal_evidence_from_payload(value: object) -> Mem0OssTerminalCleanupEvidence | None:
    if value is None:
        return None
    raw = _exact(
        value,
        {
            "terminal_state",
            "admission_commitment_sha256",
            "seal_commitment_sha256",
            "operation_root_sha256",
            "operation_inventory_root_sha256",
            "deleted_operation_count",
            "residual_record_count",
            "residual_root_sha256",
            "provider_observed_extraction_calls",
            "provider_observed_request_tokens",
            "provider_observed_response_tokens",
            "failed_receipts",
        },
    )
    failed = _failed_receipts(raw.pop("failed_receipts"))
    return Mem0OssTerminalCleanupEvidence(**raw, failed_receipts=failed)


def _valid_run_payload(value: ManagedMem0V5Checkpoint) -> bool:
    fields = (
        value.seal,
        value.cleanup_context,
        value.cleanup_request_commitment_sha256,
        value.terminal_basis,
        value.terminal_evidence,
    )
    if value.run_phase is ManagedMem0V5RunPhase.ACTIVE:
        return all(item is None for item in fields)
    if type(value.seal) is not Mem0OssRunSeal and (
        value.run_phase is ManagedMem0V5RunPhase.SEALED
        or not (value.cleanup_context is not None and value.cleanup_context.aborting)
    ):
        return False
    if value.seal is not None and (
        value.seal.admission_commitment_sha256 != value.admission_commitment_sha256
        or value.seal.operation_count != len(value.units)
    ):
        return False
    if value.run_phase is ManagedMem0V5RunPhase.SEALED:
        return fields[1:] == (None, None, None, None)
    if (
        type(value.cleanup_context) is not CleanupVerificationContext
        or not is_sha256(value.cleanup_request_commitment_sha256)
        or type(value.terminal_basis) is not Mem0OssTerminalBasis
        or value.terminal_basis.cleanup_context != value.cleanup_context
        or cleanup_request_commitment(value.cleanup_context)
        != value.cleanup_request_commitment_sha256
        or value.cleanup_context.admission_commitment_sha256 != value.admission_commitment_sha256
        or value.cleanup_context.expected_operation_count != len(value.units)
        or (value.seal is None) != value.cleanup_context.aborting
        or (
            value.seal is not None
            and (
                value.seal.commitment_sha256 != value.cleanup_context.seal_commitment_sha256
                or value.seal.operation_root_sha256 != value.cleanup_context.operation_root_sha256
            )
        )
    ):
        return False
    if not value.cleanup_context.aborting and (
        value.terminal_basis.provider_observed_extraction_calls
        != value.seal.provider_observed_extraction_calls
        or value.terminal_basis.provider_observed_request_tokens
        != value.seal.provider_observed_request_tokens
        or value.terminal_basis.provider_observed_response_tokens
        != value.seal.provider_observed_response_tokens
        or value.terminal_basis.failed_receipts
    ):
        return False
    if value.run_phase is ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED:
        return value.terminal_evidence is None
    terminal = value.terminal_evidence
    context = value.cleanup_context
    basis = value.terminal_basis
    return type(terminal) is Mem0OssTerminalCleanupEvidence and (
        terminal.terminal_state == basis.terminal_state
        and terminal.admission_commitment_sha256 == context.admission_commitment_sha256
        and terminal.seal_commitment_sha256 == context.seal_commitment_sha256
        and terminal.operation_root_sha256 == context.operation_root_sha256
        and terminal.operation_inventory_root_sha256 == context.operation_inventory_root_sha256
        and terminal.provider_observed_extraction_calls == basis.provider_observed_extraction_calls
        and terminal.provider_observed_request_tokens == basis.provider_observed_request_tokens
        and terminal.provider_observed_response_tokens == basis.provider_observed_response_tokens
        and terminal.failed_receipts == basis.failed_receipts
        and (
            terminal.deleted_operation_count <= context.expected_operation_count
            if context.aborting
            else terminal.deleted_operation_count == context.expected_operation_count
        )
    )


def _from_payload(value: object) -> ManagedMem0V5Checkpoint:
    keys = {
        "schema_version",
        "authority_commitment_sha256",
        "admission_commitment_sha256",
        "generation",
        "previous_checkpoint_commitment_sha256",
        "units",
        "run_phase",
        "seal",
        "cleanup_context",
        "cleanup_request_commitment_sha256",
        "terminal_basis",
        "terminal_evidence",
        "checkpoint_commitment_sha256",
        "checkpoint_hmac_sha256",
    }
    if type(value) is not dict or set(value) != keys or type(value["units"]) is not list:
        _fail("managed_mem0_v5_checkpoint_corrupt")
    units = []
    unit_keys = {
        "unit_index",
        "operation_id_sha256",
        "phase",
        "provider_receipt_commitment_sha256",
        "observation_commitment_sha256",
        "record_ids",
    }
    for raw in value["units"]:
        if type(raw) is not dict or set(raw) != unit_keys or type(raw["record_ids"]) is not list:
            _fail("managed_mem0_v5_checkpoint_corrupt")
        try:
            phase = ManagedMem0V5CheckpointPhase(raw["phase"])
        except (TypeError, ValueError):
            raise ManagedMem0V5CheckpointError("managed_mem0_v5_checkpoint_corrupt") from None
        units.append(
            ManagedMem0V5CheckpointUnit(
                raw["unit_index"],
                raw["operation_id_sha256"],
                phase,
                raw["provider_receipt_commitment_sha256"],
                raw["observation_commitment_sha256"],
                tuple(raw["record_ids"]),
            )
        )
    try:
        run_phase = ManagedMem0V5RunPhase(value["run_phase"])
        seal = _seal_from_payload(value["seal"])
        cleanup_context = _cleanup_context_from_payload(value["cleanup_context"])
        terminal_basis = _terminal_basis_from_payload(value["terminal_basis"])
        terminal_evidence = _terminal_evidence_from_payload(value["terminal_evidence"])
    except (KeyError, TypeError, ValueError, Mem0OssFullRunError):
        _fail("managed_mem0_v5_checkpoint_corrupt")
    return ManagedMem0V5Checkpoint(
        value["authority_commitment_sha256"],
        value["admission_commitment_sha256"],
        value["generation"],
        value["previous_checkpoint_commitment_sha256"],
        tuple(units),
        run_phase,
        seal,
        cleanup_context,
        value["cleanup_request_commitment_sha256"],
        terminal_basis,
        terminal_evidence,
        value["checkpoint_commitment_sha256"],
        value["checkpoint_hmac_sha256"],
        value["schema_version"],
    )


def _forward_only(before: ManagedMem0V5Checkpoint, after: ManagedMem0V5Checkpoint) -> None:
    if (
        before.run_phase is not ManagedMem0V5RunPhase.ACTIVE
        or after.run_phase is not ManagedMem0V5RunPhase.ACTIVE
    ) and before.units != after.units:
        _fail("managed_mem0_v5_checkpoint_regression")
    if before.run_phase is not ManagedMem0V5RunPhase.ACTIVE and before.run_phase is after.run_phase:
        _fail("managed_mem0_v5_checkpoint_regression")
    if len(before.units) != len(after.units):
        _fail("managed_mem0_v5_checkpoint_regression")
    for old, new in zip(before.units, after.units, strict=True):
        if (
            old.unit_index != new.unit_index
            or old.operation_id_sha256 != new.operation_id_sha256
            or _ORDER[new.phase] < _ORDER[old.phase]
            or (
                old.phase is ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN
                and new.phase is ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED
            )
            or (
                old.provider_receipt_commitment_sha256 is not None
                and old.provider_receipt_commitment_sha256 != new.provider_receipt_commitment_sha256
            )
            or (
                old.observation_commitment_sha256 is not None
                and old.observation_commitment_sha256 != new.observation_commitment_sha256
            )
            or (old.observation_commitment_sha256 is not None and old.record_ids != new.record_ids)
        ):
            _fail("managed_mem0_v5_checkpoint_regression")
    allowed_run_phases = {
        ManagedMem0V5RunPhase.ACTIVE: {
            ManagedMem0V5RunPhase.ACTIVE,
            ManagedMem0V5RunPhase.SEALED,
            ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
        },
        ManagedMem0V5RunPhase.SEALED: {
            ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
        },
        ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED: {
            ManagedMem0V5RunPhase.TERMINAL,
        },
        ManagedMem0V5RunPhase.TERMINAL: set(),
    }
    if after.run_phase not in allowed_run_phases[before.run_phase]:
        _fail("managed_mem0_v5_checkpoint_regression")
    for field in ("seal", "cleanup_context", "cleanup_request_commitment_sha256", "terminal_basis"):
        old = getattr(before, field)
        if old is not None and old != getattr(after, field):
            _fail("managed_mem0_v5_checkpoint_regression")
    if before.terminal_evidence is not None and before.terminal_evidence != after.terminal_evidence:
        _fail("managed_mem0_v5_checkpoint_regression")


def _signed_bytes(value: dict[str, object]) -> bytes:
    return (
        _DOMAIN
        + json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    )


def _safe_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 512
        and value == value.strip()
        and all(char.isalnum() or char in "._:-" for char in value)
    )


def _signer(value: object) -> bool:
    return all(callable(getattr(value, name, None)) for name in ("sign", "verify"))


def _fail(code: str) -> None:
    raise ManagedMem0V5CheckpointError(code)


__all__ = (
    "AtomicJsonManagedMem0V5CheckpointStore",
    "HmacSha256ManagedMem0V5CheckpointSigner",
    "ManagedMem0V5Checkpoint",
    "ManagedMem0V5CheckpointError",
    "ManagedMem0V5CheckpointPhase",
    "ManagedMem0V5RunPhase",
    "ManagedMem0V5CheckpointSignerPort",
    "ManagedMem0V5CheckpointStorePort",
    "ManagedMem0V5CheckpointUnit",
    "ManagedMem0V5RecoveryAction",
)
