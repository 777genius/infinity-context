"""Service coordination for exact, identity-only derived projection evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryInfrastructureError,
    MemoryValidationError,
)
from infinity_context_core.ports.graph_evidence import (
    GraphProjectionDeleteEvidence,
    GraphProjectionEvidencePort,
    GraphProjectionIdentitySnapshot,
)
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionEvidencePort,
    VectorProjectionPresenceEvidence,
    VectorProjectionScope,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

QDRANT_PROJECTION_VERSION = "v1"
MAX_EXPECTED_IDENTITIES = 5_000
MAX_GRAPH_PHYSICAL_IDENTITIES = 20_000
_BLOCKING_OUTBOX_STATUSES = frozenset({"pending", "retry_pending", "running", "dead"})


@dataclass(frozen=True, slots=True)
class CanonicalProjectionScope:
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _identity(self.space_id, "space_id")
        _identity(self.memory_scope_id, "memory_scope_id")
        if self.thread_id is not None:
            _identity(self.thread_id, "thread_id")


@dataclass(frozen=True, slots=True)
class ProjectionOutboxCompletion:
    done_chunk_ids: tuple[str, ...]
    done_fact_ids: tuple[str, ...]
    done_event_count: int

    @property
    def complete(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class QdrantPresenceLane:
    evidence: VectorProjectionPresenceEvidence
    manifest_binding_sha256: str


@dataclass(frozen=True, slots=True)
class GraphitiPresenceLane:
    target_commitment_sha256: str
    manifest_binding_sha256: str
    snapshot: GraphProjectionIdentitySnapshot


@dataclass(frozen=True, slots=True)
class DerivedProjectionPresence:
    scope: CanonicalProjectionScope
    outbox: ProjectionOutboxCompletion
    qdrant: QdrantPresenceLane | None
    graphiti: GraphitiPresenceLane | None


@dataclass(frozen=True, slots=True)
class QdrantDeleteResult:
    first_pass: VectorProjectionDeleteEvidence
    second_pass: VectorProjectionDeleteEvidence


@dataclass(frozen=True, slots=True)
class GraphitiDeleteResult:
    bound_expected: GraphProjectionIdentitySnapshot
    evidence: GraphProjectionDeleteEvidence


class ProjectionReadinessPort(Protocol):
    async def prove_presence_ready(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        fact_ids: tuple[str, ...],
    ) -> ProjectionOutboxCompletion: ...

    async def prove_delete_ready(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        fact_ids: tuple[str, ...],
    ) -> ProjectionOutboxCompletion: ...


class SqlAlchemyProjectionReadiness:
    """Prove canonical scope ownership and relevant outbox completion."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def prove_presence_ready(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        fact_ids: tuple[str, ...],
    ) -> ProjectionOutboxCompletion:
        _expected_ids(chunk_ids, "chunk_ids", allow_empty=True)
        _expected_ids(fact_ids, "fact_ids", allow_empty=True)
        async with AsyncSession(self._engine) as session:
            await _prove_scope_exists(session, scope)
            chunk_rows = await _load_rows(session, MemoryChunkRow, chunk_ids)
            fact_rows = await _load_rows(session, MemoryFactRow, fact_ids)
            _prove_canonical_rows(scope, chunk_ids, chunk_rows, kind="chunk")
            _prove_canonical_rows(scope, fact_ids, fact_rows, kind="fact")
            if fact_ids:
                await _prove_complete_graph_group_manifest(session, scope, fact_ids)
            chunk_events = await _load_outbox_events(
                session, aggregate_ids=chunk_ids, event_type="vector.upsert_chunk"
            )
            fact_events = await _load_outbox_events(
                session, aggregate_ids=fact_ids, event_type="graph.upsert_fact"
            )
            chunk_delete_events = await _load_projection_delete_events(
                session, event_type="vector.delete_chunks", expected_ids=chunk_ids
            )
            fact_delete_events = await _load_projection_delete_events(
                session, event_type="graph.delete_fact", expected_ids=fact_ids
            )
        _prove_all_events_terminal((*chunk_delete_events, *fact_delete_events))
        done_chunks, chunk_count = _prove_event_completion(chunk_ids, chunk_events)
        versions = {str(row.id): int(row.version) for row in fact_rows}
        done_facts, fact_count = _prove_event_completion(
            fact_ids, fact_events, current_versions=versions
        )
        return ProjectionOutboxCompletion(
            done_chunk_ids=done_chunks,
            done_fact_ids=done_facts,
            done_event_count=(
                chunk_count + fact_count + len(chunk_delete_events) + len(fact_delete_events)
            ),
        )

    async def prove_delete_ready(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        fact_ids: tuple[str, ...],
    ) -> ProjectionOutboxCompletion:
        _expected_ids(chunk_ids, "chunk_ids", allow_empty=True)
        _expected_ids(fact_ids, "fact_ids", allow_empty=True)
        async with AsyncSession(self._engine) as session:
            await _prove_scope_exists(session, scope)
            chunk_rows = await _load_rows(session, MemoryChunkRow, chunk_ids)
            fact_rows = await _load_rows(session, MemoryFactRow, fact_ids)
            _prove_delete_rows(scope, chunk_ids, chunk_rows, kind="chunk")
            _prove_delete_rows(scope, fact_ids, fact_rows, kind="fact")
            upsert_chunks = await _load_outbox_events(
                session, aggregate_ids=chunk_ids, event_type="vector.upsert_chunk"
            )
            upsert_facts = await _load_outbox_events(
                session, aggregate_ids=fact_ids, event_type="graph.upsert_fact"
            )
            delete_chunks = await _load_projection_delete_events(
                session, event_type="vector.delete_chunks", expected_ids=chunk_ids
            )
            delete_facts = await _load_projection_delete_events(
                session, event_type="graph.delete_fact", expected_ids=fact_ids
            )
        done_chunks = _prove_delete_event_completion(
            chunk_ids, chunk_rows, upsert_chunks, delete_chunks
        )
        done_facts = _prove_delete_event_completion(fact_ids, fact_rows, upsert_facts, delete_facts)
        return ProjectionOutboxCompletion(
            done_chunk_ids=done_chunks,
            done_fact_ids=done_facts,
            done_event_count=len(upsert_chunks)
            + len(upsert_facts)
            + len(delete_chunks)
            + len(delete_facts),
        )


class DerivedIdentityEvidenceCoordinator:
    """Coordinate fail-closed evidence without exposing provider content."""

    def __init__(
        self,
        *,
        readiness: ProjectionReadinessPort,
        vector_evidence: VectorProjectionEvidencePort | None,
        graph_evidence: GraphProjectionEvidencePort | None,
        graph_target_commitment_sha256: str | None,
    ) -> None:
        if graph_target_commitment_sha256 is not None:
            _digest(graph_target_commitment_sha256, "graph_target_commitment_sha256")
        self._readiness = readiness
        self._vector = vector_evidence
        self._graph = graph_evidence
        self._graph_target = graph_target_commitment_sha256

    async def observe_presence(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        fact_ids: tuple[str, ...],
    ) -> DerivedProjectionPresence:
        _request_manifest(chunk_ids, fact_ids)
        outbox = await self._readiness.prove_presence_ready(
            scope=scope, chunk_ids=chunk_ids, fact_ids=fact_ids
        )
        qdrant = await self._observe_qdrant(scope, chunk_ids, outbox) if chunk_ids else None
        graphiti = await self._observe_graphiti(scope, fact_ids, outbox) if fact_ids else None
        return DerivedProjectionPresence(scope, outbox, qdrant, graphiti)

    async def delete_qdrant_two_pass(
        self,
        *,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        target_commitment_sha256: str,
        manifest_binding_sha256: str,
    ) -> QdrantDeleteResult:
        _expected_ids(chunk_ids, "chunk_ids", allow_empty=False)
        _digest(target_commitment_sha256, "target_commitment_sha256")
        _digest(manifest_binding_sha256, "manifest_binding_sha256")
        outbox = await self._readiness.prove_delete_ready(
            scope=scope, chunk_ids=chunk_ids, fact_ids=()
        )
        current_evidence = await self._require_vector().observe_exact(
            scope=_vector_scope(scope), chunk_ids=chunk_ids
        )
        current = QdrantPresenceLane(
            current_evidence,
            _qdrant_manifest_binding(scope, chunk_ids, current_evidence, outbox),
        )
        if (
            current.evidence.target_commitment_sha256 != target_commitment_sha256
            or current.manifest_binding_sha256 != manifest_binding_sha256
        ):
            raise MemoryConflictError("Qdrant evidence receipt no longer matches")
        vector = self._require_vector()
        vector_scope = _vector_scope(scope)
        first = await vector.delete_and_observe_exact(
            scope=vector_scope, chunk_ids=chunk_ids, pass_index=1
        )
        if not first.verified_absent:
            raise MemoryConflictError("Qdrant first delete pass was not terminal")
        second = await vector.delete_and_observe_exact(
            scope=vector_scope, chunk_ids=chunk_ids, pass_index=2
        )
        if not second.verified_absent:
            raise MemoryConflictError("Qdrant second delete pass was not terminal")
        return QdrantDeleteResult(first, second)

    async def delete_graphiti_two_pass(
        self,
        *,
        scope: CanonicalProjectionScope,
        fact_ids: tuple[str, ...],
        episode_ids: tuple[str, ...],
        entity_ids: tuple[str, ...],
        mentions_edge_ids: tuple[str, ...],
        relates_to_edge_ids: tuple[str, ...],
        target_commitment_sha256: str,
        manifest_binding_sha256: str,
    ) -> GraphitiDeleteResult:
        _expected_ids(fact_ids, "fact_ids", allow_empty=False)
        group_id = graphiti_group_id(scope.space_id, scope.memory_scope_id)
        expected = GraphProjectionIdentitySnapshot(
            group_ids=(group_id,),
            episode_ids=episode_ids,
            entity_ids=entity_ids,
            mentions_edge_ids=mentions_edge_ids,
            relates_to_edge_ids=relates_to_edge_ids,
        )
        _graph_snapshot_cap(expected)
        _digest(target_commitment_sha256, "target_commitment_sha256")
        _digest(manifest_binding_sha256, "manifest_binding_sha256")
        outbox = await self._readiness.prove_delete_ready(
            scope=scope, chunk_ids=(), fact_ids=fact_ids
        )
        graph = self._require_graph()
        target = self._require_graph_target()
        binding = _graph_manifest_binding(scope, fact_ids, target, expected, outbox)
        if target != target_commitment_sha256 or binding != manifest_binding_sha256:
            raise MemoryConflictError("Graphiti evidence receipt does not match")
        current = await graph.inventory_group(group_id, expected_fact_ids=fact_ids)
        global_current = await graph.readback_identities(expected)
        empty = GraphProjectionIdentitySnapshot()
        if (current, global_current) not in ((expected, expected), (empty, empty)):
            raise MemoryConflictError("Graphiti evidence receipt is stale")
        delete_expected = expected if current == expected else empty
        delete_fact_ids = fact_ids if current == expected else ()
        result = await graph.delete_group_two_pass(
            group_id=group_id,
            expected=delete_expected,
            expected_fact_ids=delete_fact_ids,
        )
        if not result.verified_absent:
            raise MemoryConflictError("Graphiti delete was not terminal")
        return GraphitiDeleteResult(expected, result)

    async def _observe_qdrant(
        self,
        scope: CanonicalProjectionScope,
        chunk_ids: tuple[str, ...],
        outbox: ProjectionOutboxCompletion,
    ) -> QdrantPresenceLane:
        evidence = await self._require_vector().observe_exact(
            scope=_vector_scope(scope), chunk_ids=chunk_ids
        )
        if not evidence.complete:
            raise MemoryConflictError("Qdrant exact presence is incomplete")
        binding = _qdrant_manifest_binding(scope, chunk_ids, evidence, outbox)
        return QdrantPresenceLane(evidence, binding)

    async def _observe_graphiti(
        self,
        scope: CanonicalProjectionScope,
        fact_ids: tuple[str, ...],
        outbox: ProjectionOutboxCompletion,
    ) -> GraphitiPresenceLane:
        graph = self._require_graph()
        group_id = graphiti_group_id(scope.space_id, scope.memory_scope_id)
        snapshot = await graph.inventory_group(group_id, expected_fact_ids=fact_ids)
        _graph_snapshot_cap(snapshot)
        if snapshot.empty or await graph.readback_identities(snapshot) != snapshot:
            raise MemoryConflictError("Graphiti exact presence is incomplete")
        target = self._require_graph_target()
        return GraphitiPresenceLane(
            target,
            _graph_manifest_binding(scope, fact_ids, target, snapshot, outbox),
            snapshot,
        )

    def _require_vector(self) -> VectorProjectionEvidencePort:
        if self._vector is None:
            raise MemoryInfrastructureError("Qdrant identity evidence is unavailable")
        return self._vector

    def _require_graph(self) -> GraphProjectionEvidencePort:
        if self._graph is None:
            raise MemoryInfrastructureError("Graphiti identity evidence is unavailable")
        return self._graph

    def _require_graph_target(self) -> str:
        if self._graph_target is None:
            raise MemoryInfrastructureError("Graphiti target commitment is unavailable")
        return self._graph_target


def graphiti_target_commitment_sha256(*, neo4j_uri: str, database: str = "default") -> str:
    """Bind evidence to a configured target without exposing its URL or database."""
    if not neo4j_uri.strip() or not database.strip():
        raise MemoryValidationError("Graphiti target configuration is incomplete")
    normalized_uri = _normalized_neo4j_target(neo4j_uri)
    return hashlib.sha256(f"graphiti\0{normalized_uri}\0{database}".encode()).hexdigest()


def _normalized_neo4j_target(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise MemoryValidationError("Graphiti target URI is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"neo4j", "neo4j+s", "bolt", "bolt+s"}:
        raise MemoryValidationError("Graphiti target URI scheme is invalid")
    hostname = parsed.hostname
    if hostname is None or not hostname.strip():
        raise MemoryValidationError("Graphiti target URI host is invalid")
    normalized_host = hostname.lower()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    netloc = normalized_host if port is None else f"{normalized_host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


async def _prove_scope_exists(session: AsyncSession, scope: CanonicalProjectionScope) -> None:
    space = (
        await session.execute(
            select(MemorySpaceRow.id).where(
                MemorySpaceRow.id == scope.space_id, MemorySpaceRow.status == "active"
            )
        )
    ).scalar_one_or_none()
    memory_scope = (
        await session.execute(
            select(MemoryScopeRow.id).where(
                MemoryScopeRow.id == scope.memory_scope_id,
                MemoryScopeRow.space_id == scope.space_id,
                MemoryScopeRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if space is None or memory_scope is None:
        raise MemoryValidationError("Canonical projection scope does not exist")
    if scope.thread_id is None:
        return
    thread = (
        await session.execute(
            select(MemoryThreadRow.id).where(
                MemoryThreadRow.id == scope.thread_id,
                MemoryThreadRow.space_id == scope.space_id,
                MemoryThreadRow.memory_scope_id == scope.memory_scope_id,
                MemoryThreadRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise MemoryValidationError("Canonical projection thread does not exist")


async def _load_rows(session: AsyncSession, model: object, ids: tuple[str, ...]) -> list[object]:
    if not ids:
        return []
    return list((await session.execute(select(model).where(model.id.in_(ids)))).scalars())


def _prove_canonical_rows(
    scope: CanonicalProjectionScope,
    expected_ids: tuple[str, ...],
    rows: list[object],
    *,
    kind: str,
) -> None:
    if {str(row.id) for row in rows} != set(expected_ids):
        raise MemoryValidationError(f"Expected canonical {kind} identities do not exist")
    if any(
        row.space_id != scope.space_id
        or row.memory_scope_id != scope.memory_scope_id
        or row.thread_id != scope.thread_id
        or row.status != "active"
        for row in rows
    ):
        raise MemoryValidationError(f"Expected canonical {kind} identities differ from scope")


def _prove_delete_rows(
    scope: CanonicalProjectionScope,
    expected_ids: tuple[str, ...],
    rows: list[object],
    *,
    kind: str,
) -> None:
    if {str(row.id) for row in rows} != set(expected_ids):
        raise MemoryValidationError(f"Expected canonical {kind} identities do not exist")
    if any(
        row.space_id != scope.space_id
        or row.memory_scope_id != scope.memory_scope_id
        or row.thread_id != scope.thread_id
        or row.status not in {"active", "deleted"}
        for row in rows
    ):
        raise MemoryValidationError(f"Expected canonical {kind} identities differ from scope")


async def _prove_complete_graph_group_manifest(
    session: AsyncSession,
    scope: CanonicalProjectionScope,
    fact_ids: tuple[str, ...],
) -> None:
    active_ids = set(
        str(value)
        for value in (
            await session.execute(
                select(MemoryFactRow.id).where(
                    MemoryFactRow.space_id == scope.space_id,
                    MemoryFactRow.memory_scope_id == scope.memory_scope_id,
                    MemoryFactRow.status == "active",
                )
            )
        ).scalars()
    )
    if active_ids != set(fact_ids):
        raise MemoryConflictError("Expected facts are not the complete Graphiti group manifest")


async def _load_outbox_events(
    session: AsyncSession,
    *,
    aggregate_ids: tuple[str, ...],
    event_type: str,
) -> list[object]:
    if not aggregate_ids:
        return []
    return list(
        (
            await session.execute(
                select(MemoryOutboxRow).where(
                    MemoryOutboxRow.aggregate_id.in_(aggregate_ids),
                    MemoryOutboxRow.event_type == event_type,
                )
            )
        ).scalars()
    )


async def _load_projection_delete_events(
    session: AsyncSession,
    *,
    event_type: str,
    expected_ids: tuple[str, ...],
) -> list[object]:
    if not expected_ids:
        return []
    rows = list(
        (
            await session.execute(
                select(MemoryOutboxRow)
                .where(MemoryOutboxRow.event_type == event_type)
                .limit(100_001)
            )
        ).scalars()
    )
    if len(rows) > 100_000:
        raise MemoryConflictError("Projection delete outbox evidence exceeds its cap")
    expected = set(expected_ids)
    return [row for row in rows if _delete_event_ids(row).intersection(expected)]


def _delete_event_ids(event: object) -> set[str]:
    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    identities = {
        str(value) for key in ("chunk_id", "fact_id") if (value := payload.get(key)) is not None
    }
    chunk_ids = payload.get("chunk_ids")
    if isinstance(chunk_ids, list):
        identities.update(str(value) for value in chunk_ids if isinstance(value, str))
    if event.aggregate_type in {"chunk", "fact"}:
        identities.add(str(event.aggregate_id))
    return identities


def _prove_delete_event_completion(
    expected_ids: tuple[str, ...],
    rows: list[object],
    upsert_events: list[object],
    delete_events: list[object],
) -> tuple[str, ...]:
    upserts_by_id = {identity: [] for identity in expected_ids}
    deletes_by_id = {identity: [] for identity in expected_ids}
    for event in upsert_events:
        upserts_by_id.get(str(event.aggregate_id), []).append(event)
    for event in delete_events:
        for identity in _delete_event_ids(event).intersection(deletes_by_id):
            deletes_by_id[identity].append(event)
    rows_by_id = {str(row.id): row for row in rows}
    for identity in expected_ids:
        events = (*upserts_by_id[identity], *deletes_by_id[identity])
        if any(event.status in _BLOCKING_OUTBOX_STATUSES for event in events):
            raise MemoryConflictError("Relevant projection outbox work is not terminal")
        if any(event.status != "done" for event in events):
            raise MemoryConflictError("Relevant projection outbox status is unsupported")
        row = rows_by_id[identity]
        required = deletes_by_id[identity] if row.status == "deleted" else upserts_by_id[identity]
        if not required or not any(event.status == "done" for event in required):
            raise MemoryConflictError("Relevant terminal projection event is missing")
    return expected_ids


def _prove_event_completion(
    expected_ids: tuple[str, ...],
    events: list[object],
    *,
    current_versions: dict[str, int] | None = None,
) -> tuple[tuple[str, ...], int]:
    by_id = {identity: [] for identity in expected_ids}
    for event in events:
        by_id.get(str(event.aggregate_id), []).append(event)
    done_count = 0
    for identity in expected_ids:
        relevant = by_id[identity]
        if any(event.status in _BLOCKING_OUTBOX_STATUSES for event in relevant):
            raise MemoryConflictError("Relevant projection outbox work is not terminal")
        if any(event.status != "done" for event in relevant):
            raise MemoryConflictError("Relevant projection outbox status is unsupported")
        version = current_versions.get(identity) if current_versions is not None else None
        done = [
            event
            for event in relevant
            if event.status == "done"
            and (current_versions is None or event.aggregate_version == version)
        ]
        if not done:
            raise MemoryConflictError("Relevant projection outbox completion is missing")
        done_count += len(done)
    return expected_ids, done_count


def _prove_all_events_terminal(events: tuple[object, ...]) -> None:
    if any(event.status in _BLOCKING_OUTBOX_STATUSES for event in events):
        raise MemoryConflictError("Relevant projection outbox work is not terminal")
    if any(event.status != "done" for event in events):
        raise MemoryConflictError("Relevant projection outbox status is unsupported")


def _vector_scope(scope: CanonicalProjectionScope) -> VectorProjectionScope:
    return VectorProjectionScope(
        scope.space_id,
        scope.memory_scope_id,
        scope.thread_id,
        QDRANT_PROJECTION_VERSION,
    )


def _graph_manifest_binding(
    scope: CanonicalProjectionScope,
    fact_ids: tuple[str, ...],
    target: str,
    snapshot: GraphProjectionIdentitySnapshot,
    outbox: ProjectionOutboxCompletion,
) -> str:
    physical = {
        "episode_ids": list(snapshot.episode_ids),
        "entity_ids": list(snapshot.entity_ids),
        "mentions_edge_ids": list(snapshot.mentions_edge_ids),
        "relates_to_edge_ids": list(snapshot.relates_to_edge_ids),
    }
    lane_outbox = ProjectionOutboxCompletion((), outbox.done_fact_ids, outbox.done_event_count)
    return _manifest_digest("graphiti-v1", scope, (), fact_ids, target, physical, lane_outbox)


def _qdrant_manifest_binding(
    scope: CanonicalProjectionScope,
    chunk_ids: tuple[str, ...],
    evidence: VectorProjectionPresenceEvidence,
    outbox: ProjectionOutboxCompletion,
) -> str:
    physical = [[item.chunk_id, item.point_id] for item in evidence.expected]
    lane_outbox = ProjectionOutboxCompletion(outbox.done_chunk_ids, (), outbox.done_event_count)
    return _manifest_digest(
        "qdrant-v1",
        scope,
        chunk_ids,
        (),
        evidence.target_commitment_sha256,
        physical,
        lane_outbox,
    )


def _manifest_digest(
    lane: str,
    scope: CanonicalProjectionScope,
    chunk_ids: tuple[str, ...],
    fact_ids: tuple[str, ...],
    target: str,
    physical: object,
    outbox: ProjectionOutboxCompletion,
) -> str:
    payload = {
        "lane": lane,
        "scope": [scope.space_id, scope.memory_scope_id, scope.thread_id],
        "chunk_ids": list(chunk_ids),
        "fact_ids": list(fact_ids),
        "target_commitment_sha256": target,
        "physical_manifest": physical,
        "outbox_done_chunk_ids": list(outbox.done_chunk_ids),
        "outbox_done_fact_ids": list(outbox.done_fact_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _request_manifest(chunk_ids: tuple[str, ...], fact_ids: tuple[str, ...]) -> None:
    _expected_ids(chunk_ids, "chunk_ids", allow_empty=True)
    _expected_ids(fact_ids, "fact_ids", allow_empty=True)
    if not chunk_ids and not fact_ids:
        raise MemoryValidationError("At least one expected identity is required")


def _expected_ids(value: object, name: str, *, allow_empty: bool) -> None:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise MemoryValidationError(f"{name} must be an identity tuple")
    if not allow_empty and not value:
        raise MemoryValidationError(f"{name} cannot be empty")
    if len(value) > MAX_EXPECTED_IDENTITIES:
        raise MemoryValidationError(f"{name} exceeds the identity cap")
    for item in value:
        _identity(item, name)
    if len(set(value)) != len(value):
        raise MemoryValidationError(f"{name} cannot contain duplicates")


def _graph_snapshot_cap(snapshot: GraphProjectionIdentitySnapshot) -> None:
    if type(snapshot) is not GraphProjectionIdentitySnapshot:
        raise MemoryValidationError("Graphiti snapshot is invalid")
    if snapshot.identity_count > MAX_GRAPH_PHYSICAL_IDENTITIES:
        raise MemoryValidationError("Graphiti snapshot exceeds the identity cap")


def _identity(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise MemoryValidationError(f"{name} contains an invalid identity")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MemoryValidationError(f"{name} must be a lowercase SHA-256 digest")


__all__ = (
    "CanonicalProjectionScope",
    "DerivedIdentityEvidenceCoordinator",
    "DerivedProjectionPresence",
    "GraphitiPresenceLane",
    "GraphitiDeleteResult",
    "MAX_EXPECTED_IDENTITIES",
    "MAX_GRAPH_PHYSICAL_IDENTITIES",
    "ProjectionOutboxCompletion",
    "QDRANT_PROJECTION_VERSION",
    "QdrantDeleteResult",
    "QdrantPresenceLane",
    "SqlAlchemyProjectionReadiness",
    "graphiti_target_commitment_sha256",
)
