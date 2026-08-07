from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from mem0.memory.storage import SQLiteManager

from mem0_oss_adapter_v5.cleanup import (
    CleanupError,
    CleanupPhase,
    cleanup_scope,
    cleanup_scope_idempotent,
    tombstone_commitment,
)
from mem0_oss_adapter_v5.mem0_storage import (
    Mem0StorageAdapter,
    PinnedMem0Backend,
    StorageError,
    StorageMemory,
    StorageScope,
    independent_snapshot,
)


class _PinnedMemorySurface:
    def __init__(self, db: object) -> None:
        self.db = db
        self.vector_store = object()
        self.entity_store = object()

    def add(self) -> None:
        raise AssertionError("not used")

    def delete(self) -> None:
        raise AssertionError("not used")


class FakeMem0Backend:
    def __init__(self) -> None:
        self.vectors: dict[str, dict[str, object]] = {}
        self.history: set[str] = set()
        self.messages: dict[str, tuple[str, str]] = {}
        self.entities: dict[str, tuple[StorageScope, tuple[str, ...]]] = {}
        self.fail_vector_delete = False

    def add_raw(self, *, scope: StorageScope, memory: StorageMemory) -> str:
        provider_id = f"provider-{memory.memory_id}"
        self.vectors[provider_id] = {
            "id": provider_id,
            "payload": {
                **scope.filters,
                "memory": memory.text,
                "extraction_memory_id": memory.memory_id,
                "attributed_to": memory.attributed_to,
                "linked_memory_ids": list(memory.linked_memory_ids),
            },
        }
        self.history.add(provider_id)
        return provider_id

    def list_vectors(self, *, filters: Mapping[str, str], limit: int) -> Sequence[object]:
        values = [
            row
            for row in self.vectors.values()
            if all(row["payload"].get(key) == value for key, value in filters.items())  # type: ignore[union-attr]
        ]
        return values[:limit]

    def history_memory_ids(self, *, provider_memory_ids: Sequence[str]) -> Sequence[str]:
        return sorted(self.history.intersection(provider_memory_ids))

    def message_ids(self, *, scope: StorageScope) -> Sequence[str]:
        return sorted(
            key
            for key, identity in self.messages.items()
            if identity == (scope.user_id, scope.run_id)
        )

    def entity_links(self, *, scope: StorageScope) -> Sequence[tuple[str, Sequence[str]]]:
        return sorted(
            (entity_id, links)
            for entity_id, (identity, links) in self.entities.items()
            if identity == scope
        )

    def delete_memory(self, provider_memory_id: str) -> None:
        if not self.fail_vector_delete:
            self.vectors.pop(provider_memory_id, None)

    def delete_history(self, provider_memory_ids: Sequence[str]) -> None:
        self.history.difference_update(provider_memory_ids)

    def delete_messages(self, *, scope: StorageScope) -> None:
        self.messages = {
            key: value
            for key, value in self.messages.items()
            if value != (scope.user_id, scope.run_id)
        }

    def delete_entity_links(self, *, scope: StorageScope) -> None:
        self.entities = {key: value for key, value in self.entities.items() if value[0] != scope}


class CascadingEntityCrashBackend(FakeMem0Backend):
    """Matches pinned Mem0 link shrink and injects one cut before vector two."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_calls = 0
        self.crashed = False

    def delete_memory(self, provider_memory_id: str) -> None:
        self.delete_calls += 1
        if self.delete_calls == 2 and not self.crashed:
            self.crashed = True
            raise RuntimeError("crash between vector deletes")
        super().delete_memory(provider_memory_id)
        self.entities = {
            entity_id: (
                identity,
                tuple(link for link in links if link != provider_memory_id),
            )
            for entity_id, (identity, links) in self.entities.items()
        }


@pytest.fixture
def scope() -> StorageScope:
    return StorageScope(
        user_id="user-opaque",
        run_id="run-opaque",
        source_id="source-opaque",
        source_sha256="a" * 64,
    )


@pytest.fixture
def memories() -> tuple[StorageMemory, ...]:
    return (
        StorageMemory(memory_id="memory-1", text="Alice likes tea", attributed_to="Alice"),
        StorageMemory(
            memory_id="memory-2",
            text="Alice moved to Rome",
            attributed_to="Alice",
            linked_memory_ids=("memory-1",),
        ),
    )


def test_real_pinned_sqlite_manager_supports_exact_reads_and_deletes(
    tmp_path: Path,
    scope: StorageScope,
) -> None:
    manager = SQLiteManager(str(tmp_path / "mem0-history.sqlite"))
    backend = PinnedMem0Backend(_PinnedMemorySurface(manager))
    session_scope = f"user_id={scope.user_id}&run_id={scope.run_id}"
    try:
        manager.add_history("provider-1", None, "Alice likes tea", "ADD")
        manager.save_messages(
            [{"role": "user", "content": "Alice likes tea"}],
            session_scope,
        )

        assert backend.history_memory_ids(provider_memory_ids=("provider-1", "missing")) == (
            "provider-1",
        )
        assert len(backend.message_ids(scope=scope)) == 1

        backend.delete_history(("provider-1",))
        backend.delete_messages(scope=scope)

        assert backend.history_memory_ids(provider_memory_ids=("provider-1",)) == ()
        assert backend.message_ids(scope=scope) == ()
    finally:
        manager.close()


def test_pinned_sqlite_handles_reject_legacy_missing_and_wrong_surfaces() -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    databases = (
        SimpleNamespace(conn=connection, lock=threading.Lock()),
        SimpleNamespace(),
        SimpleNamespace(connection=connection, _lock=threading.Lock()),
    )
    try:
        for db in databases:
            backend = PinnedMem0Backend(_PinnedMemorySurface(db))
            with pytest.raises(StorageError, match="handles differ from the pinned runtime"):
                backend.history_memory_ids(provider_memory_ids=())
    finally:
        connection.close()


def test_exact_pinned_manager_rejects_missing_wrong_and_subclassed_handles(
    tmp_path: Path,
) -> None:
    class ConnectionSubclass(sqlite3.Connection):
        pass

    class SQLiteManagerSubclass(SQLiteManager):
        pass

    manager = SQLiteManager(str(tmp_path / "mutated.sqlite"))
    subclassed_connection = sqlite3.connect(
        ":memory:",
        check_same_thread=False,
        factory=ConnectionSubclass,
    )
    subclassed_manager = SQLiteManagerSubclass(str(tmp_path / "subclassed.sqlite"))
    original_connection = manager.connection
    original_lock = manager._lock
    try:
        for attribute, invalid in (
            ("connection", object()),
            ("connection", subclassed_connection),
            ("_lock", threading.RLock()),
        ):
            setattr(manager, attribute, invalid)
            with pytest.raises(StorageError, match="handles differ from the pinned runtime"):
                PinnedMem0Backend(_PinnedMemorySurface(manager)).history_memory_ids(
                    provider_memory_ids=()
                )
            manager.connection = original_connection
            manager._lock = original_lock

        del manager.connection
        with pytest.raises(StorageError, match="handles differ from the pinned runtime"):
            PinnedMem0Backend(_PinnedMemorySurface(manager)).history_memory_ids(
                provider_memory_ids=()
            )
        manager.connection = original_connection

        with pytest.raises(StorageError, match="handles differ from the pinned runtime"):
            PinnedMem0Backend(_PinnedMemorySurface(subclassed_manager)).history_memory_ids(
                provider_memory_ids=()
            )
    finally:
        manager.connection = original_connection
        manager._lock = original_lock
        manager.close()
        subclassed_connection.close()
        subclassed_manager.close()


def test_persist_and_independently_verify_exact_vector_history_and_entity_links(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    result = adapter.persist(scope=scope, memories=memories)
    independent = independent_snapshot(backend, scope=scope)
    assert result.snapshot == independent
    assert result.commitment_sha256 == independent.commitment_sha256
    assert independent.provider_memory_ids == ("provider-memory-1", "provider-memory-2")
    assert independent.history_memory_ids == independent.provider_memory_ids
    assert independent.entity_links == ()


def test_exact_verifier_rejects_vector_content_tampering(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    adapter.persist(scope=scope, memories=memories)
    backend.vectors["provider-memory-1"]["payload"]["memory"] = "tampered"  # type: ignore[index]
    with pytest.raises(StorageError, match="content or provenance"):
        adapter.verify_exact(scope=scope, memories=memories)


def test_independent_snapshot_rejects_scope_provenance_tampering(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    Mem0StorageAdapter(backend).persist(scope=scope, memories=memories)
    backend.vectors["provider-memory-1"]["payload"]["run_id"] = "other"  # type: ignore[index]
    # Simulate a compromised provider returning an out-of-scope row despite its filter.
    original = backend.list_vectors
    backend.list_vectors = lambda **_kwargs: list(backend.vectors.values())  # type: ignore[method-assign]
    try:
        with pytest.raises(StorageError, match="scope provenance"):
            independent_snapshot(backend, scope=scope)
    finally:
        backend.list_vectors = original  # type: ignore[method-assign]


def test_exact_verifier_rejects_history_deletion(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    adapter.persist(scope=scope, memories=memories)
    backend.history.remove("provider-memory-1")
    with pytest.raises(StorageError, match="history identity"):
        adapter.verify_exact(scope=scope, memories=memories)


def test_exact_verifier_rejects_messages_and_unknown_entity_links(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    adapter.persist(scope=scope, memories=memories)
    backend.messages["message-1"] = (scope.user_id, scope.run_id)
    with pytest.raises(StorageError, match="retained messages"):
        adapter.verify_exact(scope=scope, memories=memories)
    backend.messages.clear()
    backend.entities["hostile"] = (scope, ("provider-outside-scope",))
    with pytest.raises(StorageError, match="retained entity links"):
        adapter.verify_exact(scope=scope, memories=memories)


def test_complete_exact_persistence_is_idempotent(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    first = adapter.persist(scope=scope, memories=memories)
    second = adapter.persist_or_resume(scope=scope, memories=memories)
    assert second == first


@pytest.mark.parametrize("crash_memory_id", ["memory-1", "memory-2"])
def test_persist_or_resume_after_each_item_crash_and_adapter_reopen(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
    crash_memory_id: str,
) -> None:
    backend = FakeMem0Backend()

    def crash(memory_id: str) -> None:
        if memory_id == crash_memory_id:
            raise RuntimeError("injected crash")

    with pytest.raises(RuntimeError, match="injected crash"):
        Mem0StorageAdapter(backend).persist_or_resume(
            scope=scope,
            memories=memories,
            after_item_durable=crash,
        )
    resumed = Mem0StorageAdapter(backend).persist_or_resume(
        scope=scope,
        memories=memories,
    )
    assert {vector.extraction_memory_id for vector in resumed.snapshot.vectors} == {
        "memory-1",
        "memory-2",
    }
    assert len(backend.vectors) == 2


def test_persist_or_resume_rejects_extra_or_mutated_partial_state(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    backend.add_raw(scope=scope, memory=memories[0])
    backend.vectors["provider-memory-1"]["payload"]["memory"] = "mutated"  # type: ignore[index]
    with pytest.raises(StorageError, match="content or provenance"):
        Mem0StorageAdapter(backend).persist_or_resume(scope=scope, memories=memories)

    backend = FakeMem0Backend()
    backend.add_raw(scope=scope, memory=StorageMemory(memory_id="extra", text="extra"))
    with pytest.raises(StorageError, match="unsealed extras"):
        Mem0StorageAdapter(backend).persist_or_resume(scope=scope, memories=memories)


def test_empty_extraction_is_an_exact_zero_storage_commit(
    scope: StorageScope,
) -> None:
    backend = FakeMem0Backend()
    verification = Mem0StorageAdapter(backend).persist(scope=scope, memories=())
    assert verification.snapshot.empty
    assert (
        verification.commitment_sha256
        == independent_snapshot(backend, scope=scope).commitment_sha256
    )


def test_empty_extraction_cleanup_is_idempotent_and_zero_residue(
    scope: StorageScope,
) -> None:
    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=()).snapshot
    first = cleanup_scope(backend, scope=scope, expected_before=before)
    second = cleanup_scope_idempotent(
        backend,
        scope=scope,
        sealed_before=before,
        prior_receipt=first,
    )
    assert first == second
    assert first.provider_memory_ids == ()
    assert independent_snapshot(backend, scope=scope).empty


def test_cleanup_removes_all_surfaces_and_runtime_receipt(
    tmp_path: Path,
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    backend.messages["message-1"] = (scope.user_id, scope.run_id)
    before = independent_snapshot(backend, scope=scope)
    receipt_path = tmp_path / "runtime-receipt.json"
    receipt_path.write_bytes(b'{"receipt":"sanitized"}')
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    receipt = cleanup_scope(
        backend,
        scope=scope,
        expected_before=before,
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256=receipt_sha,
    )
    after = independent_snapshot(backend, scope=scope)
    assert after.empty
    assert not receipt_path.exists()
    assert receipt.runtime_receipt_removed
    assert receipt.tombstone_commitment_sha256 == tombstone_commitment(
        scope=scope,
        before=before,
        after=after,
        runtime_receipt_removed=True,
    )


@pytest.mark.parametrize("crash_phase", list(CleanupPhase))
def test_cleanup_resumes_after_crash_at_every_durable_delete_phase(
    tmp_path: Path,
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
    crash_phase: CleanupPhase,
) -> None:
    backend = FakeMem0Backend()
    Mem0StorageAdapter(backend).persist(scope=scope, memories=memories)
    backend.messages["message-1"] = (scope.user_id, scope.run_id)
    backend.entities["entity-1"] = (scope, ("provider-memory-1",))
    sealed_before = independent_snapshot(backend, scope=scope)
    receipt_path = tmp_path / f"receipt-{crash_phase.value}"
    receipt_bytes = b'{"receipt":"sanitized"}'
    receipt_path.write_bytes(receipt_bytes)
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()

    def crash(phase: CleanupPhase) -> None:
        if phase is crash_phase:
            raise RuntimeError("injected cleanup crash")

    with pytest.raises(RuntimeError, match="injected cleanup crash"):
        cleanup_scope(
            backend,
            scope=scope,
            expected_before=sealed_before,
            runtime_receipt_path=receipt_path,
            runtime_receipt_sha256=receipt_sha,
            after_phase_durable=crash,
        )
    result = cleanup_scope(
        backend,
        scope=scope,
        expected_before=sealed_before,
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256=receipt_sha,
    )
    assert result.runtime_receipt_removed
    assert not receipt_path.exists()
    assert not backend.vectors
    assert not backend.history
    assert not backend.messages
    assert not backend.entities


def test_cleanup_resumes_after_cascading_entity_shrink_between_vector_deletes(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = CascadingEntityCrashBackend()
    Mem0StorageAdapter(backend).persist(scope=scope, memories=memories)
    backend.entities["entity-1"] = (
        scope,
        ("provider-memory-1", "provider-memory-2"),
    )
    sealed_before = independent_snapshot(backend, scope=scope)

    with pytest.raises(RuntimeError, match="crash between vector deletes"):
        cleanup_scope(backend, scope=scope, expected_before=sealed_before)
    assert backend.entities["entity-1"][1] == ("provider-memory-2",)

    receipt = cleanup_scope(backend, scope=scope, expected_before=sealed_before)
    assert receipt.before_commitment_sha256 == sealed_before.commitment_sha256
    assert independent_snapshot(backend, scope=scope).empty


@pytest.mark.parametrize(
    "hostile_links",
    [
        ("provider-memory-1", "provider-hostile"),
        ("provider-memory-1", "provider-memory-1"),
    ],
)
def test_cleanup_rejects_unknown_or_duplicate_entity_links(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
    hostile_links: tuple[str, ...],
) -> None:
    backend = FakeMem0Backend()
    Mem0StorageAdapter(backend).persist(scope=scope, memories=memories)
    backend.entities["entity-1"] = (
        scope,
        ("provider-memory-1", "provider-memory-2"),
    )
    sealed_before = independent_snapshot(backend, scope=scope)
    backend.entities["entity-1"] = (scope, hostile_links)

    with pytest.raises(StorageError, match=r"entity cleanup state|duplicate identities"):
        cleanup_scope(backend, scope=scope, expected_before=sealed_before)


def test_cleanup_rejects_mutated_subset_after_crash(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    sealed_before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot

    def crash(phase: CleanupPhase) -> None:
        if phase is CleanupPhase.VECTORS:
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        cleanup_scope(
            backend,
            scope=scope,
            expected_before=sealed_before,
            after_phase_durable=crash,
        )
    backend.history.add("provider-hostile")
    # Hostile rows outside the sealed provider inventory are never used as cleanup authority.
    backend.vectors["provider-hostile"] = {
        "id": "provider-hostile",
        "payload": {
            **scope.filters,
            "memory": "hostile",
            "extraction_memory_id": "hostile",
            "attributed_to": None,
            "linked_memory_ids": [],
        },
    }
    with pytest.raises(StorageError, match="outside sealed provider inventory"):
        cleanup_scope(backend, scope=scope, expected_before=sealed_before)


def test_cleanup_is_idempotent_only_with_valid_prior_tombstone(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    first = cleanup_scope(backend, scope=scope, expected_before=before)
    second = cleanup_scope_idempotent(
        backend,
        scope=scope,
        sealed_before=before,
        prior_receipt=first,
    )
    assert second == first
    bad = first.__class__(
        before_commitment_sha256=first.before_commitment_sha256,
        after_commitment_sha256=first.after_commitment_sha256,
        tombstone_commitment_sha256="f" * 64,
        provider_memory_ids=first.provider_memory_ids,
        runtime_receipt_removed=first.runtime_receipt_removed,
    )
    with pytest.raises(CleanupError, match="prior cleanup receipt"):
        cleanup_scope_idempotent(
            backend,
            scope=scope,
            sealed_before=before,
            prior_receipt=bad,
        )


def test_prior_tombstone_replay_removes_exact_resurrected_runtime_receipt(
    tmp_path: Path,
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    sealed_before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    receipt_path = tmp_path / "runtime-receipt"
    receipt_bytes = b'{"receipt":"sealed"}'
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path.write_bytes(receipt_bytes)
    first = cleanup_scope(
        backend,
        scope=scope,
        expected_before=sealed_before,
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256=receipt_sha,
    )
    receipt_path.write_bytes(receipt_bytes)
    replayed = cleanup_scope_idempotent(
        backend,
        scope=scope,
        sealed_before=sealed_before,
        prior_receipt=first,
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256=receipt_sha,
    )
    assert replayed == first
    assert not receipt_path.exists()


def test_prior_tombstone_replay_rejects_mismatched_or_unbound_receipt(
    tmp_path: Path,
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    sealed_before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    receipt_path = tmp_path / "runtime-receipt"
    receipt_bytes = b'{"receipt":"sealed"}'
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path.write_bytes(receipt_bytes)
    first = cleanup_scope(
        backend,
        scope=scope,
        expected_before=sealed_before,
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256=receipt_sha,
    )
    with pytest.raises(CleanupError, match="requires sealed runtime receipt"):
        cleanup_scope_idempotent(
            backend,
            scope=scope,
            sealed_before=sealed_before,
            prior_receipt=first,
        )
    invalid_prior = first.__class__(
        before_commitment_sha256=first.before_commitment_sha256,
        after_commitment_sha256=first.after_commitment_sha256,
        tombstone_commitment_sha256="0" * 64,
        provider_memory_ids=first.provider_memory_ids,
        runtime_receipt_removed=True,
    )
    receipt_path.write_bytes(receipt_bytes)
    with pytest.raises(CleanupError, match="prior cleanup receipt"):
        cleanup_scope_idempotent(
            backend,
            scope=scope,
            sealed_before=sealed_before,
            prior_receipt=invalid_prior,
            runtime_receipt_path=receipt_path,
            runtime_receipt_sha256=receipt_sha,
        )
    assert receipt_path.exists()
    receipt_path.write_bytes(b"mismatched-resurrection")
    with pytest.raises(CleanupError, match="digest differs"):
        cleanup_scope_idempotent(
            backend,
            scope=scope,
            sealed_before=sealed_before,
            prior_receipt=first,
            runtime_receipt_path=receipt_path,
            runtime_receipt_sha256=receipt_sha,
        )
    assert receipt_path.exists()


def test_cleanup_fails_if_independent_zero_residue_proof_fails(
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    backend.fail_vector_delete = True
    with pytest.raises(CleanupError, match="residue"):
        cleanup_scope(backend, scope=scope, expected_before=before)


def test_cleanup_rejects_changed_prestate_and_receipt_digest(
    tmp_path: Path,
    scope: StorageScope,
    memories: tuple[StorageMemory, ...],
) -> None:
    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    backend.vectors["provider-memory-1"]["payload"]["memory"] = "changed"  # type: ignore[index]
    with pytest.raises(CleanupError, match="exact sealed subset"):
        cleanup_scope(backend, scope=scope, expected_before=before)

    backend = FakeMem0Backend()
    before = Mem0StorageAdapter(backend).persist(scope=scope, memories=memories).snapshot
    receipt_path = tmp_path / "receipt"
    receipt_path.write_text("actual")
    with pytest.raises(CleanupError, match="digest differs"):
        cleanup_scope(
            backend,
            scope=scope,
            expected_before=before,
            runtime_receipt_path=receipt_path,
            runtime_receipt_sha256="0" * 64,
        )


def test_storage_values_reject_duplicate_and_cross_result_links(scope: StorageScope) -> None:
    backend = FakeMem0Backend()
    adapter = Mem0StorageAdapter(backend)
    duplicate = (
        StorageMemory(memory_id="same", text="one"),
        StorageMemory(memory_id="same", text="two"),
    )
    with pytest.raises(ValueError, match="unique"):
        adapter.persist(scope=scope, memories=duplicate)
    with pytest.raises(ValueError, match="same extraction result"):
        adapter.persist(
            scope=scope,
            memories=(StorageMemory(memory_id="one", text="one", linked_memory_ids=("other",)),),
        )
