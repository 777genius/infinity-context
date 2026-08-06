"""Idempotent exact-scope cleanup with independently reproducible tombstones."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .mem0_storage import (
    Mem0StorageBackend,
    StorageError,
    StorageScope,
    StorageSnapshot,
    canonical_sha256,
    independent_cleanup_snapshot,
)


class CleanupError(StorageError):
    """Exact zero-residue cleanup could not be independently established."""


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    before_commitment_sha256: str
    after_commitment_sha256: str
    tombstone_commitment_sha256: str
    provider_memory_ids: tuple[str, ...]
    runtime_receipt_removed: bool


class CleanupPhase(StrEnum):
    VECTORS = "vectors"
    HISTORY = "history"
    MESSAGES = "messages"
    ENTITIES = "entities"
    RUNTIME_RECEIPT = "runtime_receipt"


def cleanup_scope(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    expected_before: StorageSnapshot,
    runtime_receipt_path: Path | None = None,
    runtime_receipt_sha256: str | None = None,
    after_phase_durable: Callable[[CleanupPhase], None] | None = None,
) -> CleanupReceipt:
    """Delete one scope resumably from its sealed provider identity inventory."""

    return _cleanup_scope_resumable(
        backend,
        scope=scope,
        sealed_before=expected_before,
        prior_receipt=None,
        runtime_receipt_path=runtime_receipt_path,
        runtime_receipt_sha256=runtime_receipt_sha256,
        after_phase_durable=after_phase_durable,
    )


def cleanup_scope_idempotent(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    sealed_before: StorageSnapshot,
    prior_receipt: CleanupReceipt | None = None,
    runtime_receipt_path: Path | None = None,
    runtime_receipt_sha256: str | None = None,
    after_phase_durable: Callable[[CleanupPhase], None] | None = None,
) -> CleanupReceipt:
    """Return a prior exact tombstone only after a fresh zero-residue snapshot."""

    return _cleanup_scope_resumable(
        backend,
        scope=scope,
        sealed_before=sealed_before,
        prior_receipt=prior_receipt,
        runtime_receipt_path=runtime_receipt_path,
        runtime_receipt_sha256=runtime_receipt_sha256,
        after_phase_durable=after_phase_durable,
    )


def _cleanup_scope_resumable(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    sealed_before: StorageSnapshot,
    prior_receipt: CleanupReceipt | None,
    runtime_receipt_path: Path | None,
    runtime_receipt_sha256: str | None,
    after_phase_durable: Callable[[CleanupPhase], None] | None,
) -> CleanupReceipt:
    provider_ids = tuple(sorted(sealed_before.provider_memory_ids))
    current = _cleanup_snapshot(backend, scope=scope, provider_ids=provider_ids)
    _require_exact_subset(current, sealed_before)
    if prior_receipt is not None:
        if not current.empty:
            raise CleanupError("storage was resurrected after the prior cleanup tombstone")
        _verified_prior_receipt(
            prior_receipt,
            scope=scope,
            sealed_before=sealed_before,
            current=current,
            receipt_removed=prior_receipt.runtime_receipt_removed,
        )
        receipt_removed = _ensure_prior_receipt_absence(
            prior_receipt,
            path=runtime_receipt_path,
            expected_sha256=runtime_receipt_sha256,
        )
        current = _cleanup_snapshot(backend, scope=scope, provider_ids=provider_ids)
        return _verified_prior_receipt(
            prior_receipt,
            scope=scope,
            sealed_before=sealed_before,
            current=current,
            receipt_removed=receipt_removed,
        )

    for memory_id in provider_ids:
        backend.delete_memory(memory_id)
    current = _verified_phase_snapshot(
        backend,
        scope=scope,
        provider_ids=provider_ids,
        sealed_before=sealed_before,
        phase=CleanupPhase.VECTORS,
    )
    _after_phase(after_phase_durable, CleanupPhase.VECTORS)

    backend.delete_history(provider_ids)
    current = _verified_phase_snapshot(
        backend,
        scope=scope,
        provider_ids=provider_ids,
        sealed_before=sealed_before,
        phase=CleanupPhase.HISTORY,
    )
    _after_phase(after_phase_durable, CleanupPhase.HISTORY)

    backend.delete_messages(scope=scope)
    current = _verified_phase_snapshot(
        backend,
        scope=scope,
        provider_ids=provider_ids,
        sealed_before=sealed_before,
        phase=CleanupPhase.MESSAGES,
    )
    _after_phase(after_phase_durable, CleanupPhase.MESSAGES)

    backend.delete_entity_links(scope=scope)
    current = _verified_phase_snapshot(
        backend,
        scope=scope,
        provider_ids=provider_ids,
        sealed_before=sealed_before,
        phase=CleanupPhase.ENTITIES,
    )
    _after_phase(after_phase_durable, CleanupPhase.ENTITIES)

    receipt_removed = _ensure_runtime_receipt_absent(
        runtime_receipt_path,
        expected_sha256=runtime_receipt_sha256,
    )
    _after_phase(after_phase_durable, CleanupPhase.RUNTIME_RECEIPT)
    current = _cleanup_snapshot(backend, scope=scope, provider_ids=provider_ids)
    if not current.empty:
        raise CleanupError("Mem0 scope has residue after cleanup")
    tombstone = tombstone_commitment(
        scope=scope,
        before=sealed_before,
        after=current,
        runtime_receipt_removed=receipt_removed,
    )
    return CleanupReceipt(
        before_commitment_sha256=sealed_before.commitment_sha256,
        after_commitment_sha256=current.commitment_sha256,
        tombstone_commitment_sha256=tombstone,
        provider_memory_ids=provider_ids,
        runtime_receipt_removed=receipt_removed,
    )


def tombstone_commitment(
    *,
    scope: StorageScope,
    before: StorageSnapshot,
    after: StorageSnapshot,
    runtime_receipt_removed: bool,
) -> str:
    """Pure verifier helper; callers can reproduce it without trusting cleanup code."""

    return canonical_sha256(
        {
            "schema": "mem0-oss-adapter-v5.cleanup-tombstone.v2",
            "scope": asdict(scope),
            "before_commitment_sha256": before.commitment_sha256,
            "after_commitment_sha256": after.commitment_sha256,
            "runtime_receipt_removed": runtime_receipt_removed,
            "zero_residue": after.empty,
        }
    )


def _cleanup_snapshot(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    provider_ids: tuple[str, ...],
) -> StorageSnapshot:
    return independent_cleanup_snapshot(
        backend,
        scope=scope,
        sealed_provider_memory_ids=provider_ids,
    )


def _verified_phase_snapshot(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    provider_ids: tuple[str, ...],
    sealed_before: StorageSnapshot,
    phase: CleanupPhase,
) -> StorageSnapshot:
    current = _cleanup_snapshot(backend, scope=scope, provider_ids=provider_ids)
    _require_exact_subset(current, sealed_before)
    incomplete = {
        CleanupPhase.VECTORS: bool(current.vectors),
        CleanupPhase.HISTORY: bool(current.vectors or current.history_memory_ids),
        CleanupPhase.MESSAGES: bool(
            current.vectors or current.history_memory_ids or current.message_ids
        ),
        CleanupPhase.ENTITIES: not current.empty,
    }[phase]
    if incomplete:
        raise CleanupError(f"{phase.value} residue remains after cleanup phase")
    return current


def _require_exact_subset(current: StorageSnapshot, sealed: StorageSnapshot) -> None:
    if not set(current.vectors).issubset(sealed.vectors):
        raise CleanupError("vector cleanup state is not an exact sealed subset")
    if not set(current.history_memory_ids).issubset(sealed.history_memory_ids):
        raise CleanupError("history cleanup state is not an exact sealed subset")
    if not set(current.message_ids).issubset(sealed.message_ids):
        raise CleanupError("message cleanup state is not an exact sealed subset")
    sealed_entities = {value.entity_id: value for value in sealed.entity_links}
    current_entities = {value.entity_id: value for value in current.entity_links}
    if len(current_entities) != len(current.entity_links):
        raise CleanupError("entity cleanup state contains duplicate identities")
    for entity_id, value in current_entities.items():
        sealed_value = sealed_entities.get(entity_id)
        if sealed_value is None or not set(value.linked_provider_memory_ids).issubset(
            sealed_value.linked_provider_memory_ids
        ):
            raise CleanupError("entity cleanup state is not an exact sealed subset")


def _after_phase(
    callback: Callable[[CleanupPhase], None] | None,
    phase: CleanupPhase,
) -> None:
    if callback is not None:
        callback(phase)


def _verified_prior_receipt(
    prior: CleanupReceipt,
    *,
    scope: StorageScope,
    sealed_before: StorageSnapshot,
    current: StorageSnapshot,
    receipt_removed: bool,
) -> CleanupReceipt:
    expected = tombstone_commitment(
        scope=scope,
        before=sealed_before,
        after=current,
        runtime_receipt_removed=receipt_removed,
    )
    if (
        not current.empty
        or prior.before_commitment_sha256 != sealed_before.commitment_sha256
        or prior.after_commitment_sha256 != current.commitment_sha256
        or prior.tombstone_commitment_sha256 != expected
        or prior.provider_memory_ids != tuple(sorted(sealed_before.provider_memory_ids))
        or prior.runtime_receipt_removed != receipt_removed
    ):
        raise CleanupError("prior cleanup receipt differs from independent snapshots")
    return prior


def _ensure_prior_receipt_absence(
    prior: CleanupReceipt,
    *,
    path: Path | None,
    expected_sha256: str | None,
) -> bool:
    if not prior.runtime_receipt_removed:
        if path is not None or expected_sha256 is not None:
            raise CleanupError("runtime receipt was resurrected after cleanup")
        return False
    if path is None or expected_sha256 is None:
        raise CleanupError("prior tombstone replay requires sealed runtime receipt identity")
    return _ensure_runtime_receipt_absent(path, expected_sha256=expected_sha256)


def _ensure_runtime_receipt_absent(path: Path | None, *, expected_sha256: str | None) -> bool:
    if path is None:
        if expected_sha256 is not None:
            raise CleanupError("runtime receipt digest was provided without a receipt path")
        return False
    if not path.is_absolute() or path.is_symlink():
        raise CleanupError("runtime receipt path is unsafe")
    if not path.exists():
        return expected_sha256 is not None
    if expected_sha256 is None:
        raise CleanupError("runtime receipt removal requires its sealed digest")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CleanupError("runtime receipt could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise CleanupError("runtime receipt path is not a regular file")
        digest_builder = hashlib.sha256()
        while chunk := os.read(descriptor, 64 * 1024):
            digest_builder.update(chunk)
        digest = digest_builder.hexdigest()
        current = path.stat(follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise CleanupError("runtime receipt identity changed during verification")
    finally:
        os.close(descriptor)
    if digest != expected_sha256:
        raise CleanupError("runtime receipt digest differs before removal")
    os.unlink(path)
    if path.exists():
        raise CleanupError("runtime receipt remains after exact removal")
    return True


__all__ = (
    "CleanupError",
    "CleanupPhase",
    "CleanupReceipt",
    "cleanup_scope",
    "cleanup_scope_idempotent",
    "tombstone_commitment",
)
