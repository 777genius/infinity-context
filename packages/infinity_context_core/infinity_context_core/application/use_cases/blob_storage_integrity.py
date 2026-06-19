"""Blob storage integrity audit use case."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.ports.assets import (
    BlobStorageMaintenancePort,
    StoredBlobObject,
    StoredBlobReference,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MAX_REPORT_ITEMS = 300


@dataclass(frozen=True)
class BlobStorageIntegrityAuditCommand:
    storage_backend: str
    prefix: str = ""
    include_assets: bool = True
    include_artifacts: bool = True
    verify_checksum: bool = True
    max_references: int = 100
    max_blob_read_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True)
class BlobStorageIntegrityIssue:
    source_type: str
    source_id: str
    reason: str
    storage_key_hash: str
    storage_key_extension: str | None
    storage_key_path_depth: int
    expected_byte_size: int
    observed_byte_size: int | None = None
    expected_sha256_prefix: str | None = None
    observed_sha256_prefix: str | None = None
    created_at: datetime | None = None
    checked_at: datetime | None = None


@dataclass(frozen=True)
class BlobStorageIntegrityAuditResult:
    status: str
    storage_backend: str
    prefix: str
    scanned_count: int
    ok_count: int
    missing_count: int
    byte_size_mismatch_count: int
    checksum_mismatch_count: int
    checksum_skipped_count: int
    read_error_count: int
    stat_error_count: int
    issues: tuple[BlobStorageIntegrityIssue, ...]
    diagnostics: dict[str, object]


class RunBlobStorageIntegrityAuditUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        blob_storage: BlobStorageMaintenancePort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage
        self._clock = clock

    async def execute(
        self,
        command: BlobStorageIntegrityAuditCommand,
    ) -> BlobStorageIntegrityAuditResult:
        storage_backend = _required_text(command.storage_backend, "storage_backend", max_chars=80)
        prefix = _normalize_prefix(command.prefix)
        max_references = max(1, min(command.max_references, 1_000))
        max_blob_read_bytes = max(1, min(command.max_blob_read_bytes, 512 * 1024 * 1024))
        refs = await self._load_references(
            storage_backend=storage_backend,
            prefix=prefix,
            include_assets=command.include_assets,
            include_artifacts=command.include_artifacts,
            max_references=max_references,
        )

        ok_count = 0
        missing_count = 0
        byte_size_mismatch_count = 0
        checksum_mismatch_count = 0
        checksum_skipped_count = 0
        read_error_count = 0
        stat_error_count = 0
        issues: list[BlobStorageIntegrityIssue] = []
        checked_at = self._clock.now()
        for ref in refs:
            result = await self._audit_reference(
                ref,
                verify_checksum=command.verify_checksum,
                max_blob_read_bytes=max_blob_read_bytes,
                checked_at=checked_at,
            )
            if result is None:
                ok_count += 1
                continue
            if result.reason == "missing_blob":
                missing_count += 1
            elif result.reason == "byte_size_mismatch":
                byte_size_mismatch_count += 1
            elif result.reason == "checksum_mismatch":
                checksum_mismatch_count += 1
            elif result.reason == "checksum_skipped_too_large":
                checksum_skipped_count += 1
            elif result.reason == "read_error":
                read_error_count += 1
            elif result.reason == "stat_error":
                stat_error_count += 1
            _append_issue(issues, result)

        issue_count = (
            missing_count
            + byte_size_mismatch_count
            + checksum_mismatch_count
            + read_error_count
            + stat_error_count
        )
        return BlobStorageIntegrityAuditResult(
            status="ok" if issue_count == 0 else "degraded",
            storage_backend=storage_backend,
            prefix=prefix,
            scanned_count=len(refs),
            ok_count=ok_count,
            missing_count=missing_count,
            byte_size_mismatch_count=byte_size_mismatch_count,
            checksum_mismatch_count=checksum_mismatch_count,
            checksum_skipped_count=checksum_skipped_count,
            read_error_count=read_error_count,
            stat_error_count=stat_error_count,
            issues=tuple(issues),
            diagnostics={
                "audit_policy_version": "blob-storage-integrity-audit-v1",
                "include_assets": command.include_assets,
                "include_artifacts": command.include_artifacts,
                "verify_checksum": command.verify_checksum,
                "max_references": max_references,
                "max_blob_read_bytes": max_blob_read_bytes,
                "issues_truncated": len(issues) >= _MAX_REPORT_ITEMS,
                "storage_keys_are_redacted": True,
            },
        )

    async def _load_references(
        self,
        *,
        storage_backend: str,
        prefix: str,
        include_assets: bool,
        include_artifacts: bool,
        max_references: int,
    ) -> tuple[StoredBlobReference, ...]:
        if not include_assets and not include_artifacts:
            raise MemoryValidationError("At least one blob source type must be included")
        refs: list[StoredBlobReference] = []
        async with self._uow_factory() as uow:
            if include_assets:
                asset_limit = (
                    max_references
                    if not include_artifacts
                    else max(1, (max_references + 1) // 2)
                )
                asset_refs = await uow.assets.list_stored_blob_references(
                    storage_backend=storage_backend,
                    prefix=prefix,
                    limit=asset_limit,
                )
                refs.extend(asset_refs)
            remaining = max_references - len(refs)
            if include_artifacts and remaining > 0:
                artifact_refs = await uow.asset_extractions.list_retained_artifact_blob_references(
                    storage_backend=storage_backend,
                    prefix=prefix,
                    limit=remaining,
                )
                refs.extend(artifact_refs)
        return tuple(refs[:max_references])

    async def _audit_reference(
        self,
        ref: StoredBlobReference,
        *,
        verify_checksum: bool,
        max_blob_read_bytes: int,
        checked_at: datetime,
    ) -> BlobStorageIntegrityIssue | None:
        try:
            stat = await self._blob_storage.stat_object(storage_key=ref.storage_key)
        except MemoryNotFoundError:
            return _issue(ref, reason="missing_blob", checked_at=checked_at)
        except Exception:
            return _issue(ref, reason="stat_error", checked_at=checked_at)
        observed_byte_size = stat.byte_size
        if observed_byte_size != ref.byte_size:
            return _issue(
                ref,
                reason="byte_size_mismatch",
                observed_byte_size=observed_byte_size,
                checked_at=checked_at,
            )
        if not verify_checksum:
            return None
        if ref.byte_size > max_blob_read_bytes:
            return _issue(
                ref,
                reason="checksum_skipped_too_large",
                observed_byte_size=observed_byte_size,
                checked_at=checked_at,
            )
        return await self._audit_checksum(ref, stat=stat, checked_at=checked_at)

    async def _audit_checksum(
        self,
        ref: StoredBlobReference,
        *,
        stat: StoredBlobObject,
        checked_at: datetime,
    ) -> BlobStorageIntegrityIssue | None:
        try:
            content = await self._blob_storage.read_bytes(storage_key=ref.storage_key)
        except MemoryNotFoundError:
            return _issue(ref, reason="missing_blob", checked_at=checked_at)
        except Exception:
            return _issue(
                ref,
                reason="read_error",
                observed_byte_size=stat.byte_size,
                checked_at=checked_at,
            )
        observed_digest = hashlib.sha256(content).hexdigest()
        if len(content) != ref.byte_size:
            return _issue(
                ref,
                reason="byte_size_mismatch",
                observed_byte_size=len(content),
                observed_sha256_hex=observed_digest,
                checked_at=checked_at,
            )
        if observed_digest.lower() != ref.sha256_hex.lower():
            return _issue(
                ref,
                reason="checksum_mismatch",
                observed_byte_size=len(content),
                observed_sha256_hex=observed_digest,
                checked_at=checked_at,
            )
        return None


def _append_issue(
    issues: list[BlobStorageIntegrityIssue],
    issue: BlobStorageIntegrityIssue,
) -> None:
    if len(issues) >= _MAX_REPORT_ITEMS:
        return
    issues.append(issue)


def _issue(
    ref: StoredBlobReference,
    *,
    reason: str,
    observed_byte_size: int | None = None,
    observed_sha256_hex: str | None = None,
    checked_at: datetime | None = None,
) -> BlobStorageIntegrityIssue:
    return BlobStorageIntegrityIssue(
        source_type=ref.source_type,
        source_id=ref.source_id,
        reason=reason,
        storage_key_hash=hashlib.sha256(ref.storage_key.encode("utf-8")).hexdigest()[:16],
        storage_key_extension=_extension(ref.storage_key),
        storage_key_path_depth=sum(1 for part in ref.storage_key.split("/") if part),
        expected_byte_size=ref.byte_size,
        observed_byte_size=observed_byte_size,
        expected_sha256_prefix=ref.sha256_hex[:12],
        observed_sha256_prefix=observed_sha256_hex[:12] if observed_sha256_hex else None,
        created_at=ref.created_at,
        checked_at=checked_at,
    )


def _normalize_prefix(prefix: str) -> str:
    normalized = prefix.strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    if (
        normalized.startswith("/")
        or "\x00" in normalized
        or any(ord(char) < 32 for char in normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise MemoryValidationError("Invalid blob integrity audit prefix")
    return normalized


def _required_text(value: str, field: str, *, max_chars: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise MemoryValidationError(f"{field} is required")
    return normalized[:max_chars]


def _extension(storage_key: str) -> str | None:
    filename = storage_key.rsplit("/", 1)[-1]
    if "." not in filename:
        return None
    suffix = filename.rsplit(".", 1)[-1].strip().lower()
    if not suffix or len(suffix) > 24:
        return None
    return f".{suffix}"
