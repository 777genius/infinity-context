"""Secret-free durable report contracts for managed-v5 recovery."""

from __future__ import annotations

import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    canonical_json,
)

RECOVERY_REPORT_SCHEMA = "managed-v5-provider-free-recovery-report.v1"
_SHA = frozenset("0123456789abcdef")
_REASON = re.compile(r"^managed_v5_recovery_[a-z0-9_]{1,96}$")


class ManagedV5RecoveryReportError(RuntimeError):
    pass


def managed_v5_registry_recovery_payload(error: object) -> dict[str, object]:
    """Project the legacy in-process registry recovery envelope without secrets."""

    from infinity_context_server.memory_comparison_managed_v5_production_runner import (
        ManagedV5ProductionRecoveryRequiredError,
    )

    if type(error) is not ManagedV5ProductionRecoveryRequiredError:
        raise TypeError("managed v5 recovery error required")
    envelope = error.envelope
    registration = envelope.registration
    receipt = envelope.cleanup_receipt
    return {
        "schema_version": envelope.schema_version,
        "cleanup_required": True,
        "canonical_state": ("unknown_may_exist" if registration is None else registration.state),
        "canonical_state_retained": registration is not None,
        "cleanup_stage": envelope.stage,
        "primary_reason_code": envelope.primary_reason_code,
        "run_id_sha256": envelope.run_id_sha256,
        "binding_commitment_sha256": envelope.binding_commitment_sha256,
        "infinity_target_identity_sha256": envelope.infinity_target_identity_sha256,
        "space_slug": envelope.space_slug,
        "registration": (
            None
            if registration is None
            else {
                "run_id_sha256": registration.run_id_sha256,
                "binding_commitment_sha256": registration.binding_commitment_sha256,
                "infinity_target_identity_sha256": (registration.infinity_target_identity_sha256),
                "space_id": registration.space_id,
                "space_slug": registration.space_slug,
                "state": registration.state,
                "created": registration.created,
            }
        ),
        "cleanup_receipt_sha256": None if receipt is None else receipt.receipt_sha256,
    }


@final
@dataclass(frozen=True, slots=True)
class CanonicalRecoveryProjection:
    state: str
    projection_cleanup_state: str
    cleanup_plan_sha256: str
    cleanup_receipt_sha256: str | None
    completion_receipt_sha256: str | None

    def __post_init__(self) -> None:
        allowed = {
            "active": {"unsealed", "sealed"},
            "cleanup_pending": {"pending", "blocked"},
            "cleanup_complete": {"complete"},
            "cleanup_aborted": {"unsealed_abort_complete"},
        }
        if (
            self.state not in allowed
            or self.projection_cleanup_state not in allowed[self.state]
            or not _sha(self.cleanup_plan_sha256)
            or (self.cleanup_receipt_sha256 is not None and not _sha(self.cleanup_receipt_sha256))
            or (
                self.completion_receipt_sha256 is not None
                and not _sha(self.completion_receipt_sha256)
            )
            or (self.state == "active" and self.cleanup_receipt_sha256 is not None)
            or (self.state == "cleanup_pending" and self.cleanup_receipt_sha256 is None)
            or (
                self.state in {"cleanup_complete", "cleanup_aborted"}
                and (self.cleanup_receipt_sha256 is None or self.completion_receipt_sha256 is None)
            )
        ):
            _fail("managed_v5_recovery_canonical_projection_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "projection_cleanup_state": self.projection_cleanup_state,
            "cleanup_plan_sha256": self.cleanup_plan_sha256,
            "cleanup_receipt_sha256": self.cleanup_receipt_sha256,
            "completion_receipt_sha256": self.completion_receipt_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class Mem0RecoveryProjection:
    terminal_state: str
    terminal_commitment_sha256: str
    cleanup_readback_witness_sha256: str

    def __post_init__(self) -> None:
        if self.terminal_state not in {"deleted", "aborted", "not_started"} or any(
            not _sha(value)
            for value in (self.terminal_commitment_sha256, self.cleanup_readback_witness_sha256)
        ):
            _fail("managed_v5_recovery_mem0_projection_invalid")

    def payload(self) -> dict[str, str]:
        return {
            "terminal_state": self.terminal_state,
            "terminal_commitment_sha256": self.terminal_commitment_sha256,
            "cleanup_readback_witness_sha256": self.cleanup_readback_witness_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedV5RecoveryReport:
    ok: bool
    status: str
    reason_code: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_slug: str
    canonical_before: CanonicalRecoveryProjection | None
    canonical_after: CanonicalRecoveryProjection | None
    mem0_before: str
    mem0_after: Mem0RecoveryProjection | None
    journal_last_event_sha256: str
    journal_body_sha256: str

    def __post_init__(self) -> None:
        no_registration = self.reason_code == "no_registration"
        completed = self.status == "completed"
        if (
            type(self.ok) is not bool
            or self.status not in {"completed", "retry_required", "blocked"}
            or (completed and self.ok is not True)
            or (not completed and self.ok is not False)
            or (completed and self.reason_code not in {"recovery_completed", "no_registration"})
            or (not completed and _REASON.fullmatch(self.reason_code) is None)
            or any(
                not _sha(value)
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.journal_last_event_sha256,
                    self.journal_body_sha256,
                )
            )
            or type(self.space_slug) is not str
            or not self.space_slug
            or (completed and (self.canonical_before is None) != no_registration)
            or (completed and (self.canonical_after is None) != no_registration)
            or (completed and (self.mem0_after is None) != no_registration)
            or (completed and no_registration and self.mem0_before != "not_registered")
            or (
                completed
                and not no_registration
                and self.mem0_before not in {"pre_execution", "execution_started"}
            )
            or (
                not completed
                and self.mem0_before
                not in {"unknown", "not_registered", "pre_execution", "execution_started"}
            )
            or (self.canonical_after is not None and self.canonical_before is None)
            or (self.mem0_after is not None and self.mem0_before in {"unknown", "not_registered"})
        ):
            _fail("managed_v5_recovery_report_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": RECOVERY_REPORT_SCHEMA,
            "ok": self.ok,
            "status": self.status,
            "reason_code": self.reason_code,
            "publishable": False,
            "provider_calls_performed": 0,
            "subscription_runtime_calls_performed": 0,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "infinity_target_identity_sha256": self.infinity_target_identity_sha256,
            "space_slug": self.space_slug,
            "canonical_before": (
                None if self.canonical_before is None else self.canonical_before.payload()
            ),
            "canonical_after": (
                None if self.canonical_after is None else self.canonical_after.payload()
            ),
            "mem0_before": self.mem0_before,
            "mem0_after": None if self.mem0_after is None else self.mem0_after.payload(),
            "journal_last_event_sha256": self.journal_last_event_sha256,
            "journal_body_sha256": self.journal_body_sha256,
        }


def write_recovery_report(
    path: Path, *, report_root: Path, report: ManagedV5RecoveryReport
) -> None:
    if (
        not isinstance(path, Path)
        or path.parent != report_root
        or type(report) is not ManagedV5RecoveryReport
    ):
        _fail("managed_v5_recovery_report_path_invalid")
    metadata = report_root.lstat()
    if (
        report_root.resolve(strict=True) != report_root
        or report_root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        _fail("managed_v5_recovery_report_root_invalid")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and not (
        stat.S_ISREG(existing.st_mode)
        and existing.st_uid == os.geteuid()
        and existing.st_nlink == 1
        and stat.S_IMODE(existing.st_mode) == 0o600
        and not path.is_symlink()
    ):
        _fail("managed_v5_recovery_report_path_invalid")
    rendered = canonical_json(report.payload())
    dirfd = os.open(report_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=dirfd,
        )
        view = memoryview(rendered)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path.name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)
    except OSError:
        _fail("managed_v5_recovery_report_write_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dirfd)
        os.close(dirfd)


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA


def _fail(code: str) -> None:
    raise ManagedV5RecoveryReportError(code)


__all__ = (
    "CanonicalRecoveryProjection",
    "ManagedV5RecoveryReport",
    "ManagedV5RecoveryReportError",
    "Mem0RecoveryProjection",
    "RECOVERY_REPORT_SCHEMA",
    "managed_v5_registry_recovery_payload",
    "write_recovery_report",
)
