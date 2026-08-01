"""Exact identity-only Neo4j evidence for Graphiti derived projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, final

from infinity_context_core.ports.graph_evidence import (
    GraphProjectionDeleteEvidence,
    GraphProjectionDeletePass,
    GraphProjectionIdentitySnapshot,
)

from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id

DEFAULT_MAX_GRAPH_IDENTITIES = 50_000
_MAX_CONFIGURED_IDENTITIES = 1_000_000

_GROUP_NODES_QUERY = """
MATCH (node)
WHERE node.group_id = $group_id
RETURN labels(node) AS labels,
       node.uuid AS uuid,
       node.group_id AS group_id,
       CASE WHEN node:Episodic THEN node.name ELSE null END AS episode_name,
       CASE WHEN node:Episodic THEN node.entity_edges ELSE [] END AS entity_edges
ORDER BY uuid
LIMIT $identity_limit
"""

_GROUP_RELATIONSHIPS_QUERY = """
MATCH (source)-[relationship]->(target)
WHERE relationship.group_id = $group_id
   OR source.group_id = $group_id
   OR target.group_id = $group_id
RETURN type(relationship) AS kind,
       relationship.uuid AS uuid,
       relationship.group_id AS group_id,
       labels(source) AS source_labels,
       source.uuid AS source_uuid,
       source.group_id AS source_group_id,
       labels(target) AS target_labels,
       target.uuid AS target_uuid,
       target.group_id AS target_group_id,
       CASE WHEN type(relationship) = 'RELATES_TO'
            THEN relationship.episodes ELSE [] END AS episodes
ORDER BY kind, uuid
LIMIT $identity_limit
"""

_GLOBAL_NODES_QUERY = """
MATCH (node)
WHERE node.uuid IN $identity_ids
RETURN labels(node) AS labels,
       node.uuid AS uuid,
       node.group_id AS group_id
ORDER BY uuid
LIMIT $identity_limit
"""

_GLOBAL_RELATIONSHIPS_QUERY = """
MATCH (source)-[relationship]->(target)
WHERE relationship.uuid IN $identity_ids
RETURN type(relationship) AS kind,
       relationship.uuid AS uuid,
       relationship.group_id AS group_id,
       labels(source) AS source_labels,
       source.group_id AS source_group_id,
       labels(target) AS target_labels,
       target.group_id AS target_group_id
ORDER BY kind, uuid
LIMIT $identity_limit
"""

_DELETE_RELATIONSHIPS_QUERY = """
MATCH ()-[relationship]->()
WHERE relationship.uuid IN $identity_ids
  AND relationship.group_id = $group_id
DELETE relationship
RETURN count(relationship) AS deleted_count
"""

_DELETE_NODES_QUERY = """
MATCH (node)
WHERE node.uuid IN $identity_ids
  AND node.group_id = $group_id
DETACH DELETE node
RETURN count(node) AS deleted_count
"""


class GraphitiIdentityEvidenceError(RuntimeError):
    """Safe fail-closed error for malformed or incomplete graph evidence."""


@final
class Neo4jGraphitiIdentityEvidenceAdapter:
    """Own exhaustive Graphiti inventory and exact two-pass group deletion."""

    __slots__ = (
        "_closed",
        "_database",
        "_driver",
        "_max_identity_count",
        "_neo4j_password",
        "_neo4j_uri",
        "_neo4j_user",
        "_owns_driver",
    )

    def __init__(
        self,
        *,
        driver: object | None = None,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        database: str | None = None,
        max_identity_count: int = DEFAULT_MAX_GRAPH_IDENTITIES,
    ) -> None:
        configured = (neo4j_uri, neo4j_user, neo4j_password)
        if driver is None and any(value is None or not value.strip() for value in configured):
            raise GraphitiIdentityEvidenceError(
                "graphiti identity evidence requires a driver or complete credentials"
            )
        if driver is not None and any(value is not None for value in configured):
            raise GraphitiIdentityEvidenceError(
                "graphiti identity evidence driver and credentials are mutually exclusive"
            )
        if database is not None:
            _identity(database, field_name="database")
        if (
            type(max_identity_count) is not int
            or not 1 <= max_identity_count <= _MAX_CONFIGURED_IDENTITIES
        ):
            raise GraphitiIdentityEvidenceError(
                "graphiti identity evidence cardinality cap is invalid"
            )
        self._driver = driver
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._database = database
        self._max_identity_count = max_identity_count
        self._owns_driver = driver is None
        self._closed = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Neo4jGraphitiIdentityEvidenceAdapter is final")

    @staticmethod
    def group_id(
        space_id: str,
        memory_scope_id: str,
        *,
        prefix: str = "memory",
    ) -> str:
        """Return the exact group identity used by Graphiti projection writes."""

        return graphiti_group_id(space_id, memory_scope_id, prefix=prefix)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        driver = self._driver
        self._driver = None
        if driver is None or not self._owns_driver:
            return
        close = getattr(driver, "close", None)
        if callable(close):
            await close()

    async def inventory_group(
        self,
        group_id: str,
        *,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionIdentitySnapshot:
        """Enumerate a group and prove exact binding to the fact manifest."""

        _identity(group_id, field_name="group_id")
        _expected_fact_ids(expected_fact_ids)
        try:
            node_records = await self._read(
                _GROUP_NODES_QUERY,
                group_id=group_id,
                identity_limit=self._query_limit,
            )
            relationship_records = await self._read(
                _GROUP_RELATIONSHIPS_QUERY,
                group_id=group_id,
                identity_limit=self._query_limit,
            )
            return self._snapshot(
                node_records,
                relationship_records,
                required_group_id=group_id,
                expected_fact_ids=expected_fact_ids,
            )
        except GraphitiIdentityEvidenceError:
            raise
        except Exception:
            raise GraphitiIdentityEvidenceError("graphiti identity inventory failed") from None

    async def readback_identities(
        self,
        expected: GraphProjectionIdentitySnapshot,
    ) -> GraphProjectionIdentitySnapshot:
        """Read captured UUIDs globally, including identities moved to another group."""

        _snapshot_type(expected)
        try:
            node_records = (
                await self._read(
                    _GLOBAL_NODES_QUERY,
                    identity_ids=list(expected.node_ids),
                    identity_limit=self._query_limit,
                )
                if expected.node_ids
                else ()
            )
            relationship_records = (
                await self._read(
                    _GLOBAL_RELATIONSHIPS_QUERY,
                    identity_ids=list(expected.edge_ids),
                    identity_limit=self._query_limit,
                )
                if expected.edge_ids
                else ()
            )
            return self._snapshot(node_records, relationship_records)
        except GraphitiIdentityEvidenceError:
            raise
        except Exception:
            raise GraphitiIdentityEvidenceError(
                "graphiti identity global readback failed"
            ) from None

    async def delete_group_two_pass(
        self,
        *,
        group_id: str,
        expected: GraphProjectionIdentitySnapshot,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionDeleteEvidence:
        """Delete captured group UUIDs, then prove exact idempotent absence twice."""

        _identity(group_id, field_name="group_id")
        _snapshot_type(expected)
        _expected_fact_ids(expected_fact_ids)
        if expected.group_ids not in ((), (group_id,)):
            raise GraphitiIdentityEvidenceError("graphiti delete expected snapshot group differs")
        try:
            first = await self._delete_pass(
                pass_index=1,
                group_id=group_id,
                required_before=expected,
                global_expected=expected,
                expected_fact_ids=expected_fact_ids,
            )
            second = await self._delete_pass(
                pass_index=2,
                group_id=group_id,
                required_before=GraphProjectionIdentitySnapshot(),
                global_expected=expected,
                expected_fact_ids=(),
            )
            return GraphProjectionDeleteEvidence(
                group_id=group_id,
                expected=expected,
                first_pass=first,
                second_pass=second,
            )
        except GraphitiIdentityEvidenceError:
            raise
        except Exception:
            raise GraphitiIdentityEvidenceError(
                "graphiti two-pass identity deletion failed"
            ) from None

    async def _delete_pass(
        self,
        *,
        pass_index: int,
        group_id: str,
        required_before: GraphProjectionIdentitySnapshot,
        global_expected: GraphProjectionIdentitySnapshot,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionDeletePass:
        before = await self._transactional_delete(
            group_id=group_id,
            required_before=required_before,
            expected_fact_ids=expected_fact_ids,
        )
        group_readback = await self.inventory_group(
            group_id,
            expected_fact_ids=(),
        )
        global_readback = await self.readback_identities(global_expected)
        if not group_readback.empty or not global_readback.empty:
            raise GraphitiIdentityEvidenceError(
                "graphiti identity deletion left residual identities"
            )
        return GraphProjectionDeletePass(
            pass_index=pass_index,
            before=before,
            deleted=before,
            group_readback=group_readback,
            global_readback=global_readback,
        )

    async def _transactional_delete(
        self,
        *,
        group_id: str,
        required_before: GraphProjectionIdentitySnapshot,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionIdentitySnapshot:
        driver = await self._driver_or_raise()
        session_factory = getattr(driver, "session", None)
        if not callable(session_factory):
            raise GraphitiIdentityEvidenceError(
                "graphiti identity evidence driver lacks transactions"
            )
        session_kwargs = {"database": self._database} if self._database is not None else {}
        async with session_factory(**session_kwargs) as session:
            execute_write = getattr(session, "execute_write", None)
            if not callable(execute_write):
                raise GraphitiIdentityEvidenceError(
                    "graphiti identity evidence session lacks write transactions"
                )
            return await execute_write(
                self._delete_in_transaction,
                group_id,
                required_before,
                expected_fact_ids,
            )

    async def _delete_in_transaction(
        self,
        transaction: object,
        group_id: str,
        required_before: GraphProjectionIdentitySnapshot,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionIdentitySnapshot:
        node_records = await _transaction_records(
            transaction,
            _GROUP_NODES_QUERY,
            group_id=group_id,
            identity_limit=self._query_limit,
        )
        relationship_records = await _transaction_records(
            transaction,
            _GROUP_RELATIONSHIPS_QUERY,
            group_id=group_id,
            identity_limit=self._query_limit,
        )
        before = self._snapshot(
            node_records,
            relationship_records,
            required_group_id=group_id,
            expected_fact_ids=expected_fact_ids,
        )
        if before != required_before:
            raise GraphitiIdentityEvidenceError(
                "graphiti transactional inventory differs from expected"
            )
        deleted_edges = await _transaction_deleted_count(
            transaction,
            _DELETE_RELATIONSHIPS_QUERY,
            identity_ids=list(before.edge_ids),
            group_id=group_id,
        )
        if deleted_edges != len(before.edge_ids):
            raise GraphitiIdentityEvidenceError("graphiti relationship deletion count differs")
        deleted_nodes = await _transaction_deleted_count(
            transaction,
            _DELETE_NODES_QUERY,
            identity_ids=list(before.node_ids),
            group_id=group_id,
        )
        if deleted_nodes != len(before.node_ids):
            raise GraphitiIdentityEvidenceError("graphiti node deletion count differs")
        return before

    async def _read(self, query: str, **parameters: object) -> tuple[object, ...]:
        driver = await self._driver_or_raise()
        execute_query = getattr(driver, "execute_query", None)
        if not callable(execute_query):
            raise GraphitiIdentityEvidenceError(
                "graphiti identity evidence driver lacks execute_query"
            )
        kwargs: dict[str, object] = {
            "parameters_": parameters,
            "routing_": "r",
        }
        if self._database is not None:
            kwargs["database_"] = self._database
        result = await execute_query(query, **kwargs)
        return _eager_records(result)

    async def _driver_or_raise(self) -> object:
        if self._closed:
            raise GraphitiIdentityEvidenceError("graphiti identity evidence adapter is closed")
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import AsyncGraphDatabase
        except Exception:
            raise GraphitiIdentityEvidenceError("neo4j async driver is unavailable") from None
        try:
            self._driver = AsyncGraphDatabase.driver(
                self._neo4j_uri,
                auth=(self._neo4j_user, self._neo4j_password),
            )
        except Exception:
            raise GraphitiIdentityEvidenceError(
                "neo4j async driver initialization failed"
            ) from None
        return self._driver

    @property
    def _query_limit(self) -> int:
        return self._max_identity_count + 1

    def _snapshot(
        self,
        node_records: Sequence[object],
        relationship_records: Sequence[object],
        *,
        required_group_id: str | None = None,
        expected_fact_ids: tuple[str, ...] | None = None,
    ) -> GraphProjectionIdentitySnapshot:
        if len(node_records) > self._max_identity_count:
            raise GraphitiIdentityEvidenceError(
                "graphiti node identity cardinality exceeds the hard cap"
            )
        if len(relationship_records) > self._max_identity_count:
            raise GraphitiIdentityEvidenceError(
                "graphiti relationship identity cardinality exceeds the hard cap"
            )
        if len(node_records) + len(relationship_records) > self._max_identity_count:
            raise GraphitiIdentityEvidenceError(
                "graphiti total identity cardinality exceeds the hard cap"
            )

        episode_ids: list[str] = []
        entity_ids: list[str] = []
        mentions_edge_ids: list[str] = []
        relates_to_edge_ids: list[str] = []
        group_ids: list[str] = []
        episode_names: list[str] = []
        episode_entity_edges: dict[str, frozenset[str]] = {}
        mentioned_entity_ids: set[str] = set()
        relates_to_episodes: dict[str, frozenset[str]] = {}

        for raw in node_records:
            record = _mapping(raw)
            node_id = _record_identity(record, "uuid")
            group_id = _record_identity(record, "group_id")
            labels = _labels(record.get("labels"))
            if required_group_id is not None and group_id != required_group_id:
                raise GraphitiIdentityEvidenceError("graphiti node escaped the requested group")
            node_kind = _node_kind(labels)
            is_episode = node_kind == "Episodic"
            target = episode_ids if is_episode else entity_ids
            target.append(node_id)
            group_ids.append(group_id)
            if expected_fact_ids is not None and is_episode:
                episode_name = record.get("episode_name")
                if type(episode_name) is not str:
                    raise GraphitiIdentityEvidenceError(
                        "graphiti episode manifest identity is invalid"
                    )
                entity_edges = _identity_sequence(
                    record.get("entity_edges"),
                    field_name="entity_edges",
                    allow_empty=True,
                )
                episode_names.append(episode_name)
                episode_entity_edges[node_id] = frozenset(entity_edges)

        for raw in relationship_records:
            record = _mapping(raw)
            relationship_id = _record_identity(record, "uuid")
            group_id = _record_identity(record, "group_id")
            kind = _record_identity(record, "kind")
            if kind == "MENTIONS":
                target = mentions_edge_ids
                expected_source = "Episodic"
                expected_target = "Entity"
            elif kind == "RELATES_TO":
                target = relates_to_edge_ids
                expected_source = expected_target = "Entity"
            else:
                raise GraphitiIdentityEvidenceError("graphiti relationship kind is unsupported")
            if required_group_id is not None:
                if any(
                    _record_identity(record, field_name) != required_group_id
                    for field_name in ("group_id", "source_group_id", "target_group_id")
                ):
                    raise GraphitiIdentityEvidenceError(
                        "graphiti relationship crosses the requested group"
                    )
                source_labels = _labels(record.get("source_labels"))
                target_labels = _labels(record.get("target_labels"))
                if (
                    _node_kind(source_labels) != expected_source
                    or _node_kind(target_labels) != expected_target
                ):
                    raise GraphitiIdentityEvidenceError(
                        "graphiti relationship endpoint kind is invalid"
                    )
                source_uuid = _record_identity(record, "source_uuid")
                target_uuid = _record_identity(record, "target_uuid")
                if kind == "MENTIONS":
                    if source_uuid not in episode_ids or target_uuid not in entity_ids:
                        raise GraphitiIdentityEvidenceError(
                            "graphiti MENTIONS endpoints are not captured nodes"
                        )
                    mentioned_entity_ids.add(target_uuid)
                else:
                    if source_uuid not in entity_ids or target_uuid not in entity_ids:
                        raise GraphitiIdentityEvidenceError(
                            "graphiti RELATES_TO endpoints are not captured entities"
                        )
                    episodes = _identity_sequence(
                        record.get("episodes"),
                        field_name="episodes",
                        allow_empty=False,
                    )
                    if not set(episodes).issubset(episode_ids):
                        raise GraphitiIdentityEvidenceError(
                            "graphiti RELATES_TO episodes are not captured episodes"
                        )
                    relates_to_episodes[relationship_id] = frozenset(episodes)
            target.append(relationship_id)
            group_ids.append(group_id)

        if expected_fact_ids is not None:
            expected_names = {f"fact:{fact_id}" for fact_id in expected_fact_ids}
            if (
                len(episode_names) != len(set(episode_names))
                or set(episode_names) != expected_names
            ):
                raise GraphitiIdentityEvidenceError(
                    "graphiti episode manifest differs from expected facts"
                )
            if set(entity_ids) != mentioned_entity_ids:
                raise GraphitiIdentityEvidenceError(
                    "graphiti entity MENTIONS coverage is incomplete"
                )
            _validate_episode_edge_reciprocity(
                episode_entity_edges,
                relates_to_episodes,
            )

        return GraphProjectionIdentitySnapshot(
            group_ids=tuple(sorted(set(group_ids))),
            episode_ids=tuple(sorted(episode_ids)),
            entity_ids=tuple(sorted(entity_ids)),
            mentions_edge_ids=tuple(sorted(mentions_edge_ids)),
            relates_to_edge_ids=tuple(sorted(relates_to_edge_ids)),
        )


async def _transaction_records(
    transaction: object,
    query: str,
    **parameters: object,
) -> tuple[object, ...]:
    run = getattr(transaction, "run", None)
    if not callable(run):
        raise GraphitiIdentityEvidenceError("graphiti identity evidence transaction lacks run")
    result = await run(query, parameters)
    data = getattr(result, "data", None)
    if not callable(data):
        raise GraphitiIdentityEvidenceError(
            "graphiti identity evidence transaction result is invalid"
        )
    records = await data()
    if not isinstance(records, Sequence) or isinstance(records, str | bytes):
        raise GraphitiIdentityEvidenceError(
            "graphiti identity evidence transaction records are invalid"
        )
    return tuple(records)


async def _transaction_deleted_count(
    transaction: object,
    query: str,
    **parameters: object,
) -> int:
    records = await _transaction_records(transaction, query, **parameters)
    if len(records) != 1:
        raise GraphitiIdentityEvidenceError("graphiti identity deletion acknowledgement is invalid")
    count = _mapping(records[0]).get("deleted_count")
    if type(count) is not int or count < 0:
        raise GraphitiIdentityEvidenceError("graphiti identity deletion count is invalid")
    return count


def _eager_records(result: object) -> tuple[object, ...]:
    if isinstance(result, tuple):
        records = result[0] if result else ()
    else:
        records = getattr(result, "records", None)
    if not isinstance(records, Sequence) or isinstance(records, str | bytes):
        raise GraphitiIdentityEvidenceError("graphiti identity evidence query records are invalid")
    return tuple(records)


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    data = getattr(value, "data", None)
    if callable(data):
        mapped = data()
        if isinstance(mapped, Mapping):
            return mapped
    raise GraphitiIdentityEvidenceError("graphiti identity record is invalid")


def _labels(value: object) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise GraphitiIdentityEvidenceError("graphiti identity labels are invalid")
    labels = tuple(value)
    if any(type(label) is not str or not label for label in labels):
        raise GraphitiIdentityEvidenceError("graphiti identity labels are invalid")
    return frozenset(labels)


def _node_kind(labels: frozenset[str]) -> str:
    graphiti_kinds = labels & {"Episodic", "Entity", "Community", "Saga"}
    if len(graphiti_kinds) != 1:
        raise GraphitiIdentityEvidenceError("graphiti node kind is unsupported")
    node_kind = next(iter(graphiti_kinds))
    if node_kind not in {"Episodic", "Entity"}:
        raise GraphitiIdentityEvidenceError("graphiti node kind is unsupported")
    if node_kind == "Episodic" and labels != frozenset(("Episodic",)):
        raise GraphitiIdentityEvidenceError("graphiti node labels are unsupported")
    return node_kind


def _record_identity(record: Mapping[str, object], field_name: str) -> str:
    value = record.get(field_name)
    _identity(value, field_name=field_name)
    return value


def _identity(value: object, *, field_name: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise GraphitiIdentityEvidenceError(f"graphiti identity {field_name} is invalid")


def _expected_fact_ids(value: object) -> None:
    if type(value) is not tuple:
        raise GraphitiIdentityEvidenceError("graphiti expected fact identities must be a tuple")
    for fact_id in value:
        _identity(fact_id, field_name="expected_fact_ids")
    if len(set(value)) != len(value):
        raise GraphitiIdentityEvidenceError("graphiti expected fact identities contain duplicates")


def _identity_sequence(
    value: object,
    *,
    field_name: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise GraphitiIdentityEvidenceError(f"graphiti identity {field_name} is invalid")
    identities = tuple(value)
    for identity in identities:
        _identity(identity, field_name=field_name)
    if len(set(identities)) != len(identities) or (not allow_empty and not identities):
        raise GraphitiIdentityEvidenceError(f"graphiti identity {field_name} is invalid")
    return identities


def _validate_episode_edge_reciprocity(
    episode_entity_edges: Mapping[str, frozenset[str]],
    relates_to_episodes: Mapping[str, frozenset[str]],
) -> None:
    relates_to_ids = set(relates_to_episodes)
    for episode_id, edge_ids in episode_entity_edges.items():
        if not edge_ids.issubset(relates_to_ids):
            raise GraphitiIdentityEvidenceError(
                "graphiti episode entity_edges contain an unknown relationship"
            )
        if any(episode_id not in relates_to_episodes[edge_id] for edge_id in edge_ids):
            raise GraphitiIdentityEvidenceError("graphiti episode entity_edges are not reciprocal")
    for edge_id, episode_ids in relates_to_episodes.items():
        if any(edge_id not in episode_entity_edges[episode_id] for episode_id in episode_ids):
            raise GraphitiIdentityEvidenceError("graphiti RELATES_TO episodes are not reciprocal")


def _snapshot_type(value: object) -> None:
    if type(value) is not GraphProjectionIdentitySnapshot:
        raise GraphitiIdentityEvidenceError("graphiti identity snapshot type is invalid")


__all__ = (
    "DEFAULT_MAX_GRAPH_IDENTITIES",
    "GraphitiIdentityEvidenceError",
    "Neo4jGraphitiIdentityEvidenceAdapter",
)
