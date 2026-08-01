import asyncio
from copy import deepcopy
from typing import Any

import pytest
from infinity_context_adapters.graphiti.identity_evidence import (
    GraphitiIdentityEvidenceError,
    Neo4jGraphitiIdentityEvidenceAdapter,
)
from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id

GROUP_ID = "memory__space-1__scope-1"


def _graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {
            "labels": ["Episodic"],
            "uuid": "episode-1",
            "group_id": GROUP_ID,
            "episode_name": "fact:fact-1",
            "entity_edges": ["relates-1"],
        },
        {"labels": ["Entity"], "uuid": "entity-1", "group_id": GROUP_ID},
        {"labels": ["Entity"], "uuid": "entity-2", "group_id": GROUP_ID},
    ]
    relationships = [
        {
            "kind": "MENTIONS",
            "uuid": "mentions-1",
            "group_id": GROUP_ID,
            "source_labels": ["Episodic"],
            "source_uuid": "episode-1",
            "source_group_id": GROUP_ID,
            "target_labels": ["Entity"],
            "target_uuid": "entity-1",
            "target_group_id": GROUP_ID,
            "episodes": [],
        },
        {
            "kind": "MENTIONS",
            "uuid": "mentions-2",
            "group_id": GROUP_ID,
            "source_labels": ["Episodic"],
            "source_uuid": "episode-1",
            "source_group_id": GROUP_ID,
            "target_labels": ["Entity"],
            "target_uuid": "entity-2",
            "target_group_id": GROUP_ID,
            "episodes": [],
        },
        {
            "kind": "RELATES_TO",
            "uuid": "relates-1",
            "group_id": GROUP_ID,
            "source_labels": ["Entity"],
            "source_uuid": "entity-1",
            "source_group_id": GROUP_ID,
            "target_labels": ["Entity"],
            "target_uuid": "entity-2",
            "target_group_id": GROUP_ID,
            "episodes": ["episode-1"],
        },
    ]
    return nodes, relationships


class _Result:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def data(self) -> list[dict[str, Any]]:
        return self._records


class _Transaction:
    def __init__(self, driver: "_Driver") -> None:
        self._driver = driver

    async def run(self, query: str, parameters: dict[str, Any]) -> _Result:
        self._driver.queries.append((query, parameters))
        if "DELETE relationship" in query:
            selected = {
                identity
                for identity in parameters["identity_ids"]
                if any(
                    row["uuid"] == identity and row["group_id"] == parameters["group_id"]
                    for row in self._driver.relationships
                )
            }
            self._driver.relationships = [
                row for row in self._driver.relationships if row["uuid"] not in selected
            ]
            return _Result([{"deleted_count": len(selected)}])
        if "DETACH DELETE node" in query:
            selected = {
                identity
                for identity in parameters["identity_ids"]
                if any(
                    row["uuid"] == identity and row["group_id"] == parameters["group_id"]
                    for row in self._driver.nodes
                )
            }
            self._driver.nodes = [row for row in self._driver.nodes if row["uuid"] not in selected]
            return _Result([{"deleted_count": len(selected)}])
        return _Result(self._driver.records(query, parameters))


class _Session:
    def __init__(self, driver: "_Driver") -> None:
        self._driver = driver

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute_write(self, callback: Any, *args: object) -> object:
        return await callback(_Transaction(self._driver), *args)


class _Driver:
    def __init__(self, nodes: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> None:
        self.nodes = deepcopy(nodes)
        self.relationships = deepcopy(relationships)
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def session(self, **_kwargs: object) -> _Session:
        return _Session(self)

    async def execute_query(self, query: str, **kwargs: object) -> tuple[object, ...]:
        parameters = kwargs["parameters_"]
        assert isinstance(parameters, dict)
        self.queries.append((query, parameters))
        return self.records(query, parameters), None, None

    def records(self, query: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        if "node.uuid IN $identity_ids" in query:
            identities = set(parameters["identity_ids"])
            return [self._global_node(row) for row in self.nodes if row["uuid"] in identities]
        if "relationship.uuid IN $identity_ids" in query:
            identities = set(parameters["identity_ids"])
            return [
                self._global_relationship(row)
                for row in self.relationships
                if row["uuid"] in identities
            ]
        if "MATCH (node)" in query:
            return [
                deepcopy(row) for row in self.nodes if row["group_id"] == parameters["group_id"]
            ][: parameters["identity_limit"]]
        group_id = parameters["group_id"]
        return [
            deepcopy(row)
            for row in self.relationships
            if group_id in (row["group_id"], row["source_group_id"], row["target_group_id"])
        ][: parameters["identity_limit"]]

    @staticmethod
    def _global_node(row: dict[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(row[key]) for key in ("labels", "uuid", "group_id")}

    @staticmethod
    def _global_relationship(row: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "kind",
            "uuid",
            "group_id",
            "source_labels",
            "source_group_id",
            "target_labels",
            "target_group_id",
        )
        return {key: deepcopy(row[key]) for key in keys}


def test_graphiti_inventory_proves_manifest_structure_without_exporting_names() -> None:
    nodes, relationships = _graph()
    nodes[1]["labels"] = ["Entity", "Person"]
    relationships[0]["target_labels"] = ["Entity", "Person"]
    relationships[2]["source_labels"] = ["Entity", "Person"]
    driver = _Driver(nodes, relationships)
    adapter = Neo4jGraphitiIdentityEvidenceAdapter(driver=driver)

    snapshot = asyncio.run(adapter.inventory_group(GROUP_ID, expected_fact_ids=("fact-1",)))

    assert snapshot.episode_ids == ("episode-1",)
    assert snapshot.entity_ids == ("entity-1", "entity-2")
    assert snapshot.mentions_edge_ids == ("mentions-1", "mentions-2")
    assert snapshot.relates_to_edge_ids == ("relates-1",)
    assert not hasattr(snapshot, "episode_names")
    assert all(GROUP_ID not in query for query, _ in driver.queries)
    assert all(parameters.get("group_id") == GROUP_ID for _, parameters in driver.queries)


@pytest.mark.parametrize("corruption", ["manifest", "mentions", "reciprocity", "label"])
def test_graphiti_inventory_fails_closed_on_manifest_or_structure_drift(
    corruption: str,
) -> None:
    nodes, relationships = _graph()
    if corruption == "manifest":
        nodes[0]["episode_name"] = "fact:another"
    elif corruption == "mentions":
        relationships[0]["source_uuid"] = "entity-1"
    elif corruption == "reciprocity":
        nodes[0]["entity_edges"] = []
    else:
        nodes[1]["labels"] = ["Entity", "Community"]
    adapter = Neo4jGraphitiIdentityEvidenceAdapter(driver=_Driver(nodes, relationships))

    with pytest.raises(GraphitiIdentityEvidenceError):
        asyncio.run(adapter.inventory_group(GROUP_ID, expected_fact_ids=("fact-1",)))


def test_graphiti_inventory_enforces_total_identity_cardinality_cap() -> None:
    nodes, relationships = _graph()
    adapter = Neo4jGraphitiIdentityEvidenceAdapter(
        driver=_Driver(nodes, relationships),
        max_identity_count=5,
    )

    with pytest.raises(GraphitiIdentityEvidenceError, match="cardinality"):
        asyncio.run(adapter.inventory_group(GROUP_ID, expected_fact_ids=("fact-1",)))


def test_graphiti_two_pass_delete_is_exact_global_and_idempotent() -> None:
    nodes, relationships = _graph()
    driver = _Driver(nodes, relationships)
    adapter = Neo4jGraphitiIdentityEvidenceAdapter(driver=driver)
    expected = asyncio.run(adapter.inventory_group(GROUP_ID, expected_fact_ids=("fact-1",)))

    evidence = asyncio.run(
        adapter.delete_group_two_pass(
            group_id=GROUP_ID,
            expected=expected,
            expected_fact_ids=("fact-1",),
        )
    )

    assert evidence.verified_absent
    assert evidence.first_pass.deleted == expected
    assert evidence.second_pass.deleted.empty
    assert not driver.nodes
    assert not driver.relationships
    deletion_counts = [
        parameters["identity_ids"]
        for query, parameters in driver.queries
        if "DELETE relationship" in query or "DETACH DELETE node" in query
    ]
    assert deletion_counts[-2:] == [[], []]


def test_graphiti_global_readback_detects_identity_moved_to_another_group() -> None:
    nodes, relationships = _graph()
    driver = _Driver(nodes, relationships)
    adapter = Neo4jGraphitiIdentityEvidenceAdapter(driver=driver)
    expected = asyncio.run(adapter.inventory_group(GROUP_ID, expected_fact_ids=("fact-1",)))
    driver.nodes[0]["group_id"] = "moved-group"

    readback = asyncio.run(adapter.readback_identities(expected))

    assert readback.episode_ids == ("episode-1",)
    assert readback.group_ids == (GROUP_ID, "moved-group")


def test_shared_graphiti_group_identity_preserves_writer_mapping() -> None:
    assert graphiti_group_id(" Space/A ", "scope:B") == "memory__Space_A__scope_B"
