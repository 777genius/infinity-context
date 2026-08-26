"""PostgreSQL rules for one provably unique current runtime generation."""

from __future__ import annotations

import hashlib
from datetime import datetime

from infinity_context_core.features.context_building.public import RuntimeFenceOwner
from sqlalchemy import select, text

from infinity_context_adapters.postgres.models import MemoryLocatorRuntimeIncarnationRow


async def register_runtime(
    session, owner: RuntimeFenceOwner, *, now: datetime, supervisor_trust
) -> None:
    owner.assert_current_process()
    unrecoverable = owner.supervisor_public_key == "0" * 64
    if unrecoverable:
        if (
            owner.launch_signature
            or "unrecoverable" not in owner.supervisor_key_id
            or owner.trust_root_sha256 != "0" * 64
            or owner.trust_registry_generation != 0
        ):
            raise RuntimeError("retrieval_profile_runtime_launch_invalid")
    else:
        if supervisor_trust is None:
            raise RuntimeError("retrieval_profile_supervisor_trust_required")
        supervisor_trust.verify_launch(owner, now=now)
    launch_digest = hashlib.sha256(owner.launch_payload()).hexdigest()
    await lock_runtime_instance(session, owner.instance_id)
    row = await session.get(
        MemoryLocatorRuntimeIncarnationRow,
        (owner.instance_id, owner.generation),
        with_for_update=True,
    )
    if row is None:
        launch_owner = (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow)
                .where(MemoryLocatorRuntimeIncarnationRow.launch_token == owner.launch_token)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if launch_owner is not None:
            raise RuntimeError("retrieval_profile_runtime_supervisor_conflict")
        current = (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow).where(
                    MemoryLocatorRuntimeIncarnationRow.instance_id == owner.instance_id,
                    MemoryLocatorRuntimeIncarnationRow.sealed_dead_generation.is_(None),
                    MemoryLocatorRuntimeIncarnationRow.retired_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            raise RuntimeError("retrieval_profile_runtime_generation_competing")
        session.add(_runtime_row(owner, now=now, launch_digest=launch_digest))
        return
    if not _runtime_identity_matches(row, owner, launch_digest=launch_digest):
        raise RuntimeError("retrieval_profile_runtime_supervisor_conflict")
    if row.sealed_dead_generation is not None:
        raise RuntimeError("retrieval_profile_runtime_incarnation_sealed_dead")
    if row.retired_at is not None:
        raise RuntimeError("retrieval_profile_runtime_incarnation_retired")
    row.last_seen_at = now


async def verify_registered_runtime(session, owner: RuntimeFenceOwner):
    """Read and lock the unique current owner without creating or touching it."""

    owner.assert_current_process()
    await lock_runtime_instance(session, owner.instance_id)
    current = tuple(
        (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow)
                .where(
                    MemoryLocatorRuntimeIncarnationRow.instance_id == owner.instance_id,
                    MemoryLocatorRuntimeIncarnationRow.sealed_dead_generation.is_(None),
                    MemoryLocatorRuntimeIncarnationRow.retired_at.is_(None),
                )
                .with_for_update()
            )
        ).scalars()
    )
    if len(current) > 1:
        raise RuntimeError("retrieval_profile_runtime_generation_ambiguous")
    row = current[0] if current else None
    exact = await session.get(
        MemoryLocatorRuntimeIncarnationRow,
        (owner.instance_id, owner.generation),
        with_for_update=True,
    )
    if exact is None:
        launch_owner = (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow).where(
                    MemoryLocatorRuntimeIncarnationRow.launch_token == owner.launch_token
                )
            )
        ).scalar_one_or_none()
        if launch_owner is not None:
            raise RuntimeError("retrieval_profile_runtime_launch_token_reused")
        if row is not None:
            raise RuntimeError("retrieval_profile_runtime_generation_mismatch")
        raise RuntimeError("retrieval_profile_runtime_incarnation_missing")
    if exact.sealed_dead_generation is not None:
        raise RuntimeError("retrieval_profile_runtime_incarnation_sealed_dead")
    if exact.retired_at is not None:
        raise RuntimeError("retrieval_profile_runtime_incarnation_retired")
    if row is None or row.generation != owner.generation:
        raise RuntimeError("retrieval_profile_runtime_generation_mismatch")
    if exact.launch_token != owner.launch_token:
        launch_owner = (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow).where(
                    MemoryLocatorRuntimeIncarnationRow.launch_token == owner.launch_token
                )
            )
        ).scalar_one_or_none()
        if launch_owner is not None:
            raise RuntimeError("retrieval_profile_runtime_launch_token_reused")
        raise RuntimeError("retrieval_profile_runtime_lifecycle_identity_mismatch")
    if not _runtime_release_matches(exact, owner):
        raise RuntimeError("retrieval_profile_runtime_release_identity_mismatch")
    if not _runtime_lifecycle_matches(exact, owner):
        raise RuntimeError("retrieval_profile_runtime_lifecycle_identity_mismatch")
    return exact


async def lock_runtime_instance(session, instance_id: str) -> None:
    """Serialize absent-row registration by stable identity, never by wall clock."""

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:instance_id, 0))"),
        {"instance_id": instance_id},
    )


def _runtime_row(
    owner: RuntimeFenceOwner, *, now: datetime, launch_digest: str
) -> MemoryLocatorRuntimeIncarnationRow:
    release = owner.installed_release
    return MemoryLocatorRuntimeIncarnationRow(
        instance_id=owner.instance_id,
        generation=owner.generation,
        registered_at=now,
        last_seen_at=now,
        acknowledged_generation=0,
        supervisor_key_id=owner.supervisor_key_id,
        supervisor_public_key=owner.supervisor_public_key,
        trust_root_sha256=owner.trust_root_sha256,
        trust_registry_generation=owner.trust_registry_generation,
        launch_token=owner.launch_token,
        process_pid=owner.process_pid,
        process_birth_identity=owner.process_birth_identity,
        executable_identity=owner.executable_identity,
        executable_sha256=owner.executable_sha256,
        release_revision=release.service_revision,
        release_source_tree_sha256=release.source_tree_digest_sha256,
        release_installed_distribution_sha256=release.installed_distribution_digest_sha256,
        release_runtime_modules_sha256=release.runtime_modules_digest_sha256,
        release_identity_sha256=release.digest(),
        launch_identity_sha256=launch_digest,
    )


def _runtime_identity_matches(row, owner: RuntimeFenceOwner, *, launch_digest: str) -> bool:
    release = owner.installed_release
    return bool(
        row.supervisor_key_id == owner.supervisor_key_id
        and row.supervisor_public_key == owner.supervisor_public_key
        and row.trust_root_sha256 == owner.trust_root_sha256
        and row.trust_registry_generation == owner.trust_registry_generation
        and row.launch_token == owner.launch_token
        and row.process_pid == owner.process_pid
        and row.process_birth_identity == owner.process_birth_identity
        and row.executable_identity == owner.executable_identity
        and row.executable_sha256 == owner.executable_sha256
        and row.release_revision == release.service_revision
        and row.release_source_tree_sha256 == release.source_tree_digest_sha256
        and row.release_installed_distribution_sha256
        == release.installed_distribution_digest_sha256
        and row.release_runtime_modules_sha256 == release.runtime_modules_digest_sha256
        and row.release_identity_sha256 == release.digest()
        and row.launch_identity_sha256 == launch_digest
    )


def _runtime_release_matches(row, owner: RuntimeFenceOwner) -> bool:
    release = owner.installed_release
    return bool(
        row.release_revision == release.service_revision
        and row.release_source_tree_sha256 == release.source_tree_digest_sha256
        and row.release_installed_distribution_sha256
        == release.installed_distribution_digest_sha256
        and row.release_runtime_modules_sha256 == release.runtime_modules_digest_sha256
        and row.release_identity_sha256 == release.digest()
    )


def _runtime_lifecycle_matches(row, owner: RuntimeFenceOwner) -> bool:
    launch_digest = hashlib.sha256(owner.launch_payload()).hexdigest()
    return bool(
        row.instance_id == owner.instance_id
        and row.generation == owner.generation
        and row.supervisor_key_id == owner.supervisor_key_id
        and row.supervisor_public_key == owner.supervisor_public_key
        and row.trust_root_sha256 == owner.trust_root_sha256
        and row.trust_registry_generation == owner.trust_registry_generation
        and row.launch_token == owner.launch_token
        and row.process_pid == owner.process_pid
        and row.process_birth_identity == owner.process_birth_identity
        and row.executable_identity == owner.executable_identity
        and row.executable_sha256 == owner.executable_sha256
        and row.launch_identity_sha256 == launch_digest
    )


__all__ = ("lock_runtime_instance", "register_runtime", "verify_registered_runtime")
