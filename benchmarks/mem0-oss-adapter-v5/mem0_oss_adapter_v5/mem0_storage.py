"""Narrow Mem0 2.0.15 storage boundary and independent exact-state projection."""

from __future__ import annotations

import _thread
import hashlib
import json
import math
import re
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

from mem0_oss_adapter_v5.evidence_contracts import (
    EvidenceOperation,
    ObservedRecord,
    ObservedStorage,
    SearchRecord,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORDS = 10_000


class StorageError(RuntimeError):
    """Mem0 storage differs from the exact admitted extraction result."""


@dataclass(frozen=True, slots=True)
class StorageScope:
    user_id: str
    run_id: str
    source_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        for name in ("user_id", "run_id", "source_id"):
            _opaque(getattr(self, name), name)
        _digest(self.source_sha256, "source_sha256")

    @property
    def filters(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class SearchScope:
    user_id: str
    run_id: str

    def __post_init__(self) -> None:
        _opaque(self.user_id, "user_id")
        _opaque(self.run_id, "run_id")

    @property
    def filters(self) -> dict[str, str]:
        return {"user_id": self.user_id, "run_id": self.run_id}


@dataclass(frozen=True, slots=True)
class StorageMemory:
    memory_id: str
    text: str
    attributed_to: str | None = None
    linked_memory_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _opaque(self.memory_id, "memory_id")
        if not isinstance(self.text, str) or not self.text or self.text != self.text.strip():
            raise ValueError("storage memory text must be nonempty and trimmed")
        if self.attributed_to is not None:
            _opaque(self.attributed_to, "attributed_to")
        if not isinstance(self.linked_memory_ids, tuple):
            raise ValueError("linked_memory_ids must be a tuple")
        for memory_id in self.linked_memory_ids:
            _opaque(memory_id, "linked_memory_id")
        if len(set(self.linked_memory_ids)) != len(self.linked_memory_ids):
            raise ValueError("linked_memory_ids must be unique")


@dataclass(frozen=True, slots=True)
class VectorProjection:
    provider_memory_id: str
    extraction_memory_id: str
    text: str
    attributed_to: str | None
    linked_memory_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityLinkProjection:
    entity_id: str
    linked_provider_memory_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    vectors: tuple[VectorProjection, ...]
    history_memory_ids: tuple[str, ...]
    message_ids: tuple[str, ...]
    entity_links: tuple[EntityLinkProjection, ...]

    @property
    def provider_memory_ids(self) -> tuple[str, ...]:
        return tuple(vector.provider_memory_id for vector in self.vectors)

    @property
    def empty(self) -> bool:
        return not (
            self.vectors or self.history_memory_ids or self.message_ids or self.entity_links
        )

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class CleanStateStorageSnapshot:
    storage: StorageSnapshot
    isolated_history_record_count: int

    def __post_init__(self) -> None:
        if type(self.storage) is not StorageSnapshot or (
            type(self.isolated_history_record_count) is not int
            or self.isolated_history_record_count < 0
        ):
            raise StorageError("clean-state storage snapshot is invalid")

    @property
    def empty(self) -> bool:
        return self.storage.empty and self.isolated_history_record_count == 0


@dataclass(frozen=True, slots=True)
class StorageVerification:
    snapshot: StorageSnapshot
    commitment_sha256: str


@runtime_checkable
class Mem0StorageBackend(Protocol):
    """Small provider-facing port implemented by the pinned Mem0 runtime wrapper."""

    def add_raw(self, *, scope: StorageScope, memory: StorageMemory) -> str: ...

    def list_vectors(self, *, filters: Mapping[str, str], limit: int) -> Sequence[object]: ...

    def history_memory_ids(self, *, provider_memory_ids: Sequence[str]) -> Sequence[str]: ...

    def message_ids(self, *, scope: StorageScope) -> Sequence[str]: ...

    def entity_links(self, *, scope: StorageScope) -> Sequence[tuple[str, Sequence[str]]]: ...

    def delete_memory(self, provider_memory_id: str) -> None: ...

    def delete_history(self, provider_memory_ids: Sequence[str]) -> None: ...

    def delete_messages(self, *, scope: StorageScope) -> None: ...

    def delete_entity_links(self, *, scope: StorageScope) -> None: ...


@runtime_checkable
class Mem0CleanStateBackend(Protocol):
    """Isolated storage surface required only by pre-dispatch clean-state proof."""

    def isolated_history_record_count(self) -> int: ...


@runtime_checkable
class Mem0SearchBackend(Protocol):
    """Segregated provider port used only by authenticated retrieval evidence."""

    def search_vectors(
        self,
        *,
        query: str,
        filters: Mapping[str, str],
        limit: int,
    ) -> Sequence[object]: ...


class Mem0StorageAdapter:
    """Persist sanitized extraction memories, then prove exact derived state."""

    def __init__(self, backend: Mem0StorageBackend) -> None:
        if not isinstance(backend, Mem0StorageBackend):
            raise TypeError("backend does not implement the Mem0 storage port")
        self._backend = backend
        self._lock = threading.RLock()

    @property
    def backend(self) -> Mem0StorageBackend:
        return self._backend

    def persist(
        self, *, scope: StorageScope, memories: Sequence[StorageMemory]
    ) -> StorageVerification:
        return self.persist_or_resume(scope=scope, memories=memories)

    def persist_or_resume(
        self,
        *,
        scope: StorageScope,
        memories: Sequence[StorageMemory],
        after_item_durable: Callable[[str], None] | None = None,
    ) -> StorageVerification:
        """Resume only an exact subset of the sealed extraction memory inventory."""

        expected = _validated_memories(memories)
        with self._lock:
            current = independent_snapshot(self._backend, scope=scope)
            persisted = _verify_snapshot_subset(current, expected)
            for memory in expected:
                if memory.memory_id in persisted:
                    continue
                provider_id = self._backend.add_raw(scope=scope, memory=memory)
                _opaque(provider_id, "provider_memory_id")
                if after_item_durable is not None:
                    after_item_durable(memory.memory_id)
                current = independent_snapshot(self._backend, scope=scope)
                persisted = _verify_snapshot_subset(current, expected)
            return self.verify_exact(scope=scope, memories=expected)

    def verify_exact(
        self, *, scope: StorageScope, memories: Sequence[StorageMemory]
    ) -> StorageVerification:
        expected = _validated_memories(memories)
        snapshot = independent_snapshot(self._backend, scope=scope)
        persisted = _verify_snapshot_subset(snapshot, expected)
        if persisted != {memory.memory_id for memory in expected}:
            raise StorageError("vector extraction identity inventory differs")
        return StorageVerification(
            snapshot=snapshot,
            commitment_sha256=snapshot.commitment_sha256,
        )


class Mem0EvidenceStorage:
    """Independent exact-state observation plus run/corpus scoped retrieval."""

    def __init__(self, backend: Mem0StorageBackend) -> None:
        if not isinstance(backend, Mem0StorageBackend) or not isinstance(
            backend, Mem0SearchBackend
        ):
            raise TypeError("backend does not implement the Mem0 evidence ports")
        self._backend = backend

    def observe(self, operation: EvidenceOperation) -> ObservedStorage:
        scope = StorageScope(
            user_id=operation.corpus_id,
            run_id=operation.admission_commitment_sha256,
            source_id=operation.source_id,
            source_sha256=operation.source_sha256,
        )
        snapshot = independent_snapshot(self._backend, scope=scope)
        records = tuple(
            ObservedRecord(
                record_id=item.provider_memory_id,
                extraction_memory_id=item.extraction_memory_id,
                source_id=operation.source_id,
                source_sha256=operation.source_sha256,
                memory_sha256=hashlib.sha256(item.text.encode()).hexdigest(),
            )
            for item in snapshot.vectors
        )
        actual = {item.extraction_memory_id: item.memory_sha256 for item in records}
        if (
            len(actual) != len(records)
            or actual != operation.expected_memory_sha256_by_id
            or snapshot.commitment_sha256 != operation.storage_commitment_sha256
        ):
            raise StorageError("Mem0 storage differs from trusted durable state")
        return ObservedStorage(
            records=records,
            storage_commitment_sha256=snapshot.commitment_sha256,
        )

    def observe_corpus(
        self,
        operations: tuple[EvidenceOperation, ...],
    ) -> tuple[ObservedRecord, ...]:
        if not operations:
            raise StorageError("Mem0 corpus observation requires committed operations")
        admission = operations[0].admission_commitment_sha256
        corpus_id = operations[0].corpus_id
        if any(
            item.admission_commitment_sha256 != admission or item.corpus_id != corpus_id
            for item in operations
        ):
            raise StorageError("Mem0 corpus observation scope is inconsistent")
        expected = {(item.source_id, item.source_sha256): item for item in operations}
        if len(expected) != len(operations):
            raise StorageError("Mem0 corpus observation source inventory is ambiguous")
        scope = SearchScope(user_id=corpus_id, run_id=admission)
        rows = self._backend.list_vectors(filters=scope.filters, limit=_MAX_RECORDS)
        if len(rows) >= _MAX_RECORDS:
            raise StorageError("storage corpus reached the exact-verification bound")
        records = tuple(
            _corpus_observed_record(row, scope=scope, expected=expected) for row in rows
        )
        if len({item.record_id for item in records}) != len(records):
            raise StorageError("Mem0 corpus observation has duplicate provider identities")
        actual_by_source: dict[tuple[str, str], set[str]] = {key: set() for key in expected}
        for record in records:
            values = actual_by_source[(record.source_id, record.source_sha256)]
            if record.extraction_memory_id in values:
                raise StorageError("Mem0 corpus observation has duplicate extraction identities")
            values.add(record.extraction_memory_id)
        actual_commitments: dict[tuple[str, str], dict[str, str]] = {key: {} for key in expected}
        for record in records:
            values = actual_commitments[(record.source_id, record.source_sha256)]
            if record.extraction_memory_id in values:
                raise StorageError("Mem0 corpus observation has duplicate extraction identities")
            values[record.extraction_memory_id] = record.memory_sha256
        if any(
            actual_commitments[key] != operation.expected_memory_sha256_by_id
            for key, operation in expected.items()
        ):
            raise StorageError("Mem0 corpus observation differs from trusted durable content")
        return tuple(sorted(records, key=lambda item: item.record_id))

    def search(
        self,
        *,
        admission_commitment_sha256: str,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> tuple[SearchRecord, ...]:
        scope = SearchScope(user_id=corpus_id, run_id=admission_commitment_sha256)
        rows = self._backend.search_vectors(query=query, filters=scope.filters, limit=limit)
        if isinstance(rows, str | bytes) or not isinstance(rows, Sequence) or len(rows) > limit:
            raise StorageError("Mem0 scoped search result is invalid")
        results = tuple(_search_record(row, scope) for row in rows)
        if len({item.record_id for item in results}) != len(results):
            raise StorageError("Mem0 scoped search returned duplicate identities")
        return results


def _verify_snapshot_subset(
    snapshot: StorageSnapshot, expected: Sequence[StorageMemory]
) -> set[str]:
    """Prove current storage is an unmodified subset of one sealed result."""

    expected_by_id = {memory.memory_id: memory for memory in expected}
    by_extraction_id = {vector.extraction_memory_id: vector for vector in snapshot.vectors}
    if len(by_extraction_id) != len(snapshot.vectors):
        raise StorageError("duplicate extraction memory identity in vector state")
    if not set(by_extraction_id).issubset(expected_by_id):
        raise StorageError("vector extraction identity inventory has unsealed extras")
    for memory_id, vector in by_extraction_id.items():
        memory = expected_by_id[memory_id]
        if (
            vector.text != memory.text
            or vector.attributed_to != memory.attributed_to
            or vector.linked_memory_ids != tuple(sorted(memory.linked_memory_ids))
        ):
            raise StorageError("vector memory content or provenance differs")
    provider_ids = tuple(sorted(snapshot.provider_memory_ids))
    if provider_ids != snapshot.history_memory_ids:
        raise StorageError("history identity inventory differs from vectors")
    if snapshot.message_ids:
        raise StorageError("raw-passthrough storage unexpectedly retained messages")
    if snapshot.entity_links:
        raise StorageError("raw-passthrough storage unexpectedly retained entity links")
    return set(by_extraction_id)


class PinnedMem0Backend:
    """Mem0 2.0.15 Memory wrapper; FastEmbed/Qdrant remain provider details."""

    def __init__(self, memory: object) -> None:
        required = ("add", "delete", "vector_store", "entity_store", "db")
        if any(not hasattr(memory, name) for name in required):
            raise TypeError("memory does not match the pinned Mem0 2.0.15 surface")
        self._memory = memory
        self._lock = threading.RLock()

    def add_raw(self, *, scope: StorageScope, memory: StorageMemory) -> str:
        metadata: dict[str, object] = {
            **scope.filters,
            "extraction_memory_id": memory.memory_id,
            "attributed_to": memory.attributed_to,
            "linked_memory_ids": list(memory.linked_memory_ids),
        }
        with self._lock:
            result = self._memory.add(  # type: ignore[attr-defined]
                [{"role": "assistant", "content": memory.text}],
                user_id=scope.user_id,
                run_id=scope.run_id,
                metadata=metadata,
                infer=False,
                timestamp=None,
            )
        if not isinstance(result, Mapping):
            raise StorageError("Mem0 add returned an invalid payload")
        values = result.get("results")
        if not isinstance(values, Sequence) or isinstance(values, str | bytes) or len(values) != 1:
            raise StorageError("Mem0 raw add must create exactly one memory")
        row = values[0]
        provider_id = row.get("id") if isinstance(row, Mapping) else None
        return _opaque(provider_id, "provider_memory_id")

    def list_vectors(self, *, filters: Mapping[str, str], limit: int) -> Sequence[object]:
        with self._lock:
            result = self._memory.vector_store.list(  # type: ignore[attr-defined]
                filters=dict(filters), top_k=limit
            )
        if not isinstance(result, tuple) or len(result) != 2 or result[1] is not None:
            raise StorageError("Qdrant exact-scope listing is incomplete")
        if not isinstance(result[0], list):
            raise StorageError("Qdrant exact-scope listing is invalid")
        return result[0]

    def search_vectors(
        self,
        *,
        query: str,
        filters: Mapping[str, str],
        limit: int,
    ) -> Sequence[object]:
        if set(filters) != {"user_id", "run_id"}:
            raise StorageError("Mem0 scoped search filters are invalid")
        with self._lock:
            result = self._memory.search(  # type: ignore[attr-defined]
                query,
                top_k=limit,
                filters=dict(filters),
                threshold=0.0,
                rerank=False,
                explain=False,
            )
        if not isinstance(result, Mapping) or set(result) != {"results"}:
            raise StorageError("Mem0 scoped search returned an invalid envelope")
        rows = result["results"]
        if not isinstance(rows, list):
            raise StorageError("Mem0 scoped search returned an invalid result list")
        return rows

    def history_memory_ids(self, *, provider_memory_ids: Sequence[str]) -> Sequence[str]:
        ids = tuple(sorted({_opaque(value, "provider_memory_id") for value in provider_memory_ids}))
        connection, lock = _db_handles(self._memory.db)  # type: ignore[attr-defined]
        with lock:
            rows: list[tuple[object, ...]] = []
            for batch in _batches(ids):
                placeholders = ",".join("?" for _ in batch)
                query = (
                    f"SELECT DISTINCT memory_id FROM history WHERE memory_id IN ({placeholders})"
                )
                rows.extend(connection.execute(query, batch).fetchall())
        return tuple(sorted(_opaque(row[0], "history memory_id") for row in rows))

    def isolated_history_record_count(self) -> int:
        connection, lock = _db_handles(self._memory.db)  # type: ignore[attr-defined]
        with lock:
            row = connection.execute("SELECT COUNT(*) FROM history").fetchone()
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int or row[0] < 0:
            raise StorageError("Mem0 isolated history count is invalid")
        return row[0]

    def message_ids(self, *, scope: StorageScope) -> Sequence[str]:
        connection, lock = _db_handles(self._memory.db)  # type: ignore[attr-defined]
        with lock:
            rows = connection.execute(
                """SELECT id FROM messages
                   WHERE instr('&' || session_scope || '&', '&user_id=' || ? || '&') > 0
                     AND instr('&' || session_scope || '&', '&run_id=' || ? || '&') > 0
                   ORDER BY id""",
                (scope.user_id, scope.run_id),
            ).fetchall()
        return tuple(_opaque(str(row[0]), "message_id") for row in rows)

    def entity_links(self, *, scope: StorageScope) -> Sequence[tuple[str, Sequence[str]]]:
        rows = _list_store(self._memory.entity_store, scope.filters)  # type: ignore[attr-defined]
        projections: list[tuple[str, Sequence[str]]] = []
        for row in rows:
            payload = _payload(row)
            links = payload.get("linked_memory_ids", [])
            if not isinstance(links, list):
                raise StorageError("Mem0 entity linked_memory_ids are invalid")
            projections.append((_record_id(row), tuple(str(value) for value in links)))
        return projections

    def delete_memory(self, provider_memory_id: str) -> None:
        memory_id = _opaque(provider_memory_id, "provider_memory_id")
        with self._lock:
            existing = self._memory.vector_store.get(vector_id=memory_id)  # type: ignore[attr-defined]
            if existing is None:
                return
            self._memory.delete(memory_id)  # type: ignore[attr-defined]

    def delete_history(self, provider_memory_ids: Sequence[str]) -> None:
        _delete_sql_ids(self._memory.db, "history", "memory_id", provider_memory_ids)  # type: ignore[attr-defined]

    def delete_messages(self, *, scope: StorageScope) -> None:
        connection, lock = _db_handles(self._memory.db)  # type: ignore[attr-defined]
        with lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """DELETE FROM messages
                       WHERE instr('&' || session_scope || '&', '&user_id=' || ? || '&') > 0
                         AND instr('&' || session_scope || '&', '&run_id=' || ? || '&') > 0""",
                    (scope.user_id, scope.run_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def delete_entity_links(self, *, scope: StorageScope) -> None:
        store = self._memory.entity_store  # type: ignore[attr-defined]
        for row in _list_store(store, scope.filters):
            store.delete(vector_id=_record_id(row))


def independent_snapshot(backend: Mem0StorageBackend, *, scope: StorageScope) -> StorageSnapshot:
    """Read each provider surface afresh; it does not trust any write receipt."""

    rows = backend.list_vectors(filters=scope.filters, limit=_MAX_RECORDS)
    if len(rows) >= _MAX_RECORDS:
        raise StorageError("storage scope reached the exact-verification bound")
    vectors = tuple(sorted((_vector_projection(row, scope) for row in rows), key=_vector_key))
    return _snapshot_for_vectors(backend, scope=scope, vectors=vectors)


def independent_clean_state_snapshot(
    backend: Mem0StorageBackend, *, scope: StorageScope
) -> CleanStateStorageSnapshot:
    """Read exact scope state plus the whole isolated SQLite history surface."""

    if not isinstance(backend, Mem0CleanStateBackend):
        raise StorageError("Mem0 clean-state history audit capability is unavailable")
    snapshot = independent_snapshot(backend, scope=scope)
    count = backend.isolated_history_record_count()
    return CleanStateStorageSnapshot(
        storage=snapshot,
        isolated_history_record_count=count,
    )


def independent_cleanup_snapshot(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    sealed_provider_memory_ids: Sequence[str],
) -> StorageSnapshot:
    """Read all surfaces from sealed provider IDs, even after vectors disappear."""

    sealed_ids = tuple(sorted(_unique(sealed_provider_memory_ids)))
    rows = backend.list_vectors(filters=scope.filters, limit=_MAX_RECORDS)
    if len(rows) >= _MAX_RECORDS:
        raise StorageError("storage scope reached the exact-verification bound")
    vectors = tuple(sorted((_vector_projection(row, scope) for row in rows), key=_vector_key))
    if not set(vector.provider_memory_id for vector in vectors).issubset(sealed_ids):
        raise StorageError("cleanup scope contains a vector outside sealed provider inventory")
    return _snapshot_for_vectors(
        backend,
        scope=scope,
        vectors=vectors,
        history_inventory=sealed_ids,
    )


def _snapshot_for_vectors(
    backend: Mem0StorageBackend,
    *,
    scope: StorageScope,
    vectors: tuple[VectorProjection, ...],
    history_inventory: Sequence[str] | None = None,
) -> StorageSnapshot:
    provider_ids = (
        tuple(vector.provider_memory_id for vector in vectors)
        if history_inventory is None
        else tuple(history_inventory)
    )
    history = tuple(sorted(_unique(backend.history_memory_ids(provider_memory_ids=provider_ids))))
    messages = tuple(sorted(_unique(backend.message_ids(scope=scope))))
    entity_links = tuple(
        sorted(
            (
                EntityLinkProjection(
                    entity_id=_opaque(entity_id, "entity_id"),
                    linked_provider_memory_ids=tuple(sorted(_unique(linked_provider_memory_ids))),
                )
                for entity_id, linked_provider_memory_ids in backend.entity_links(scope=scope)
            ),
            key=lambda item: item.entity_id,
        )
    )
    return StorageSnapshot(vectors, history, messages, entity_links)


def canonical_sha256(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _validated_memories(memories: Sequence[StorageMemory]) -> tuple[StorageMemory, ...]:
    if isinstance(memories, str | bytes):
        raise TypeError("memories must be a sequence of StorageMemory values")
    values = tuple(memories)
    if any(not isinstance(memory, StorageMemory) for memory in values):
        raise TypeError("memories must contain StorageMemory values")
    identities = tuple(memory.memory_id for memory in values)
    if len(set(identities)) != len(identities):
        raise ValueError("extracted memory identities must be unique")
    unknown_links = {
        link for memory in values for link in memory.linked_memory_ids if link not in identities
    }
    if unknown_links:
        raise ValueError("linked memory identities must belong to the same extraction result")
    return tuple(sorted(values, key=lambda item: item.memory_id))


def _vector_projection(row: object, scope: StorageScope) -> VectorProjection:
    payload = _payload(row)
    if any(payload.get(key) != value for key, value in scope.filters.items()):
        raise StorageError("vector projection scope provenance differs")
    text = payload.get("memory", payload.get("data"))
    if not isinstance(text, str) or not text:
        candidate = row.get("memory") if isinstance(row, Mapping) else getattr(row, "memory", None)
        text = candidate
    if not isinstance(text, str) or not text:
        raise StorageError("vector projection has no exact memory text")
    extraction_id = _opaque(payload.get("extraction_memory_id"), "extraction_memory_id")
    attributed = payload.get("attributed_to")
    if attributed is not None:
        attributed = _opaque(attributed, "attributed_to")
    links = payload.get("linked_memory_ids", [])
    if not isinstance(links, list):
        raise StorageError("vector linked_memory_ids are invalid")
    return VectorProjection(
        provider_memory_id=_record_id(row),
        extraction_memory_id=extraction_id,
        text=text,
        attributed_to=attributed,
        linked_memory_ids=tuple(sorted(_unique(links))),
    )


def _search_record(row: object, scope: SearchScope) -> SearchRecord:
    if not isinstance(row, Mapping):
        raise StorageError("Mem0 scoped search record is invalid")
    if any(row.get(key) != value for key, value in scope.filters.items()):
        raise StorageError("Mem0 scoped search escaped its run or corpus scope")
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        raise StorageError("Mem0 scoped search metadata is invalid")
    if any(key in metadata and metadata[key] != value for key, value in scope.filters.items()):
        raise StorageError("Mem0 scoped search metadata conflicts with its exact scope")
    source_id = _opaque(metadata.get("source_id"), "source_id")
    source_sha256 = _digest(metadata.get("source_sha256"), "source_sha256")
    memory = row.get("memory")
    if (
        not isinstance(memory, str)
        or not memory
        or memory != memory.strip()
        or len(memory) > 16_384
    ):
        raise StorageError("Mem0 scoped search memory is invalid")
    score = row.get("score")
    if type(score) not in {int, float} or not math.isfinite(float(score)):
        raise StorageError("Mem0 scoped search score is invalid")
    normalized_score = float(score)
    if not 0.0 <= normalized_score <= 1.0:
        raise StorageError("Mem0 scoped search score is not normalized")
    return SearchRecord(
        record_id=_record_id(row),
        memory=memory,
        source_id=source_id,
        source_sha256=source_sha256,
        score=normalized_score,
    )


def _corpus_observed_record(
    row: object,
    *,
    scope: SearchScope,
    expected: Mapping[tuple[str, str], EvidenceOperation],
) -> ObservedRecord:
    payload = _payload(row)
    if any(payload.get(key) != value for key, value in scope.filters.items()):
        raise StorageError("vector projection escaped its corpus or run scope")
    source_id = _opaque(payload.get("source_id"), "source_id")
    source_sha256 = _digest(payload.get("source_sha256"), "source_sha256")
    if (source_id, source_sha256) not in expected:
        raise StorageError("vector projection has unknown canonical source provenance")
    text = payload.get("memory", payload.get("data"))
    if not isinstance(text, str) or not text or text != text.strip() or len(text) > 16_384:
        raise StorageError("vector projection has invalid memory text")
    return ObservedRecord(
        record_id=_record_id(row),
        extraction_memory_id=_opaque(payload.get("extraction_memory_id"), "extraction_memory_id"),
        source_id=source_id,
        source_sha256=source_sha256,
        memory_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def _payload(row: object) -> Mapping[str, object]:
    value = row.get("payload") if isinstance(row, Mapping) else getattr(row, "payload", None)
    if not isinstance(value, Mapping):
        raise StorageError("provider record payload is invalid")
    return value


def _record_id(row: object) -> str:
    value = row.get("id") if isinstance(row, Mapping) else getattr(row, "id", None)
    return _opaque(str(value) if value is not None else value, "provider record id")


def _vector_key(value: VectorProjection) -> tuple[str, str]:
    return value.extraction_memory_id, value.provider_memory_id


def _opaque(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a bounded nonempty string")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _unique(values: Sequence[object]) -> tuple[str, ...]:
    result = tuple(_opaque(value, "provider identity") for value in values)
    if len(set(result)) != len(result):
        raise StorageError("provider returned duplicate identities")
    return result


def _list_store(store: object, filters: Mapping[str, str]) -> list[object]:
    result = store.list(filters=dict(filters), top_k=_MAX_RECORDS)  # type: ignore[attr-defined]
    if not isinstance(result, tuple) or len(result) != 2 or result[1] is not None:
        raise StorageError("Mem0 provider listing is incomplete")
    if not isinstance(result[0], list):
        raise StorageError("Mem0 provider listing is invalid")
    return result[0]


def _db_handles(db: object) -> tuple[sqlite3.Connection, _thread.LockType]:
    from mem0.memory.storage import SQLiteManager

    if type(db) is not SQLiteManager:
        raise StorageError("Mem0 SQLite handles differ from the pinned runtime")
    connection = getattr(db, "connection", None)
    lock = getattr(db, "_lock", None)
    if type(connection) is not sqlite3.Connection or type(lock) is not _thread.LockType:
        raise StorageError("Mem0 SQLite handles differ from the pinned runtime")
    return connection, lock


def _delete_sql_ids(db: object, table: str, column: str, values: Sequence[str]) -> None:
    ids = tuple(_unique(values))
    connection, lock = _db_handles(db)
    with lock:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for batch in _batches(ids):
                placeholders = ",".join("?" for _ in batch)
                connection.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", batch)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def _batches(values: Sequence[str], size: int = 400) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


__all__ = (
    "CleanStateStorageSnapshot",
    "EntityLinkProjection",
    "Mem0CleanStateBackend",
    "Mem0EvidenceStorage",
    "Mem0SearchBackend",
    "Mem0StorageAdapter",
    "Mem0StorageBackend",
    "PinnedMem0Backend",
    "SearchScope",
    "StorageError",
    "StorageMemory",
    "StorageScope",
    "StorageSnapshot",
    "StorageVerification",
    "VectorProjection",
    "canonical_sha256",
    "independent_clean_state_snapshot",
    "independent_cleanup_snapshot",
    "independent_snapshot",
)
