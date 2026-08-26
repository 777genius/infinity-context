"""Recovery-only Graphiti space inventory, deletion, and pass receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkProjectionPassReceipt,
    BenchmarkUnsealedProjectionScope,
)
from infinity_context_core.ports.graph_evidence import GraphProjectionIdentitySnapshot

from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id

_GLOBAL_EPISODES_BY_NAME_QUERY = """
MATCH (episode:Episodic)
WHERE episode.name IN $episode_names
RETURN episode.uuid AS uuid,
       episode.group_id AS group_id,
       episode.name AS episode_name
ORDER BY uuid
LIMIT $identity_limit
"""

_PREFIX_GROUPS_QUERY = """
CALL {
  MATCH (node) WHERE node.group_id STARTS WITH $group_prefix
  RETURN node.group_id AS group_id
  UNION
  MATCH (source)-[relationship]->(target)
  WHERE relationship.group_id STARTS WITH $group_prefix
     OR source.group_id STARTS WITH $group_prefix
     OR target.group_id STARTS WITH $group_prefix
  UNWIND [relationship.group_id, source.group_id, target.group_id] AS group_id
  RETURN group_id
}
WITH DISTINCT group_id
WHERE group_id STARTS WITH $group_prefix
RETURN group_id
ORDER BY group_id
LIMIT $identity_limit
"""


async def delete_benchmark_space_two_pass(
    adapter: Any,
    *,
    error_type: type[RuntimeError],
    space_id: str,
    scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]:
    """Inventory the collision-safe prefix and prove fresh absence twice."""

    _identity(space_id, field_name="space_id", error_type=error_type)
    target = adapter._target_commitment_sha256
    if target is None:
        raise error_type("graphiti recovery target is unavailable")
    expected = _benchmark_groups(space_id, scopes, error_type=error_type)
    prefix = _benchmark_group_prefix(space_id)
    await _require_expected_episodes_not_moved(
        adapter,
        expected,
        error_type=error_type,
    )
    present_groups = await _prefix_groups(adapter, prefix, error_type=error_type)
    if set(present_groups) - set(expected):
        raise error_type("graphiti recovery prefix contains an unknown group")
    snapshots: dict[str, GraphProjectionIdentitySnapshot] = {}
    captured_ids: set[str] = set()
    for group_id in present_groups:
        snapshot = await adapter.inventory_group(
            group_id,
            expected_fact_ids=expected[group_id],
        )
        if snapshot.empty:
            raise error_type("graphiti recovery prefix inventory changed during capture")
        identities = set((*snapshot.node_ids, *snapshot.edge_ids))
        if captured_ids & identities:
            raise error_type("graphiti recovery identities cross expected groups")
        captured_ids.update(identities)
        snapshots[group_id] = snapshot
    for group_id in sorted(expected):
        snapshot = snapshots.get(group_id, GraphProjectionIdentitySnapshot())
        await adapter.delete_group_two_pass(
            group_id=group_id,
            expected=snapshot,
            expected_fact_ids=expected[group_id] if not snapshot.empty else (),
        )
    captured = _merge_snapshots(tuple(snapshots.values()))
    receipts = []
    for pass_index in (1, 2):
        groups_after = await _prefix_groups(adapter, prefix, error_type=error_type)
        global_after = await adapter.readback_identities(captured)
        await _require_expected_episodes_not_moved(
            adapter,
            expected,
            error_type=error_type,
        )
        if groups_after or not global_after.empty:
            raise error_type("graphiti recovery space is not globally absent")
        receipts.append(
            BenchmarkProjectionPassReceipt(
                lane="graphiti",
                target_commitment_sha256=target,
                pass_index=pass_index,
                observed_count=0,
                absent=True,
                receipt_sha256=_json_sha256(
                    {
                        "schema_version": "benchmark-graphiti-recovery-pass.v1",
                        "target_commitment_sha256": target,
                        "space_id": space_id,
                        "group_prefix": prefix,
                        "pass_index": pass_index,
                        "expected_group_ids": sorted(expected),
                        "captured_identity_ids": sorted(captured_ids),
                        "prefix_group_count_after": 0,
                        "global_identity_count_after": 0,
                    }
                ),
            )
        )
    return receipts[0], receipts[1]


async def _require_expected_episodes_not_moved(
    adapter: Any,
    expected: Mapping[str, tuple[str, ...]],
    *,
    error_type: type[RuntimeError],
) -> None:
    names_to_group = {
        f"fact:{fact_id}": group_id
        for group_id, fact_ids in expected.items()
        for fact_id in fact_ids
    }
    if not names_to_group:
        return
    records = await adapter._read(
        _GLOBAL_EPISODES_BY_NAME_QUERY,
        episode_names=sorted(names_to_group),
        identity_limit=adapter._query_limit,
    )
    if len(records) > len(names_to_group):
        raise error_type("graphiti recovery expected episodes are ambiguous")
    seen_names: set[str] = set()
    for raw in records:
        record = _mapping(raw, error_type=error_type)
        _record_identity(record, "uuid", error_type=error_type)
        group_id = _record_identity(record, "group_id", error_type=error_type)
        name = _record_identity(record, "episode_name", error_type=error_type)
        if name in seen_names or names_to_group.get(name) != group_id:
            raise error_type("graphiti recovery expected identity moved to a foreign group")
        seen_names.add(name)


async def _prefix_groups(
    adapter: Any,
    group_prefix: str,
    *,
    error_type: type[RuntimeError],
) -> tuple[str, ...]:
    records = await adapter._read(
        _PREFIX_GROUPS_QUERY,
        group_prefix=group_prefix,
        identity_limit=adapter._query_limit,
    )
    if len(records) > adapter._max_identity_count:
        raise error_type("graphiti recovery group cardinality exceeds the hard cap")
    groups = tuple(
        _record_identity(
            _mapping(row, error_type=error_type),
            "group_id",
            error_type=error_type,
        )
        for row in records
    )
    if groups != tuple(sorted(set(groups))):
        raise error_type("graphiti recovery prefix inventory is malformed")
    return groups


def _benchmark_group_prefix(space_id: str) -> str:
    sentinel = graphiti_group_id(space_id, "sentinel")
    return sentinel.rsplit("__", 1)[0] + "__"


def _benchmark_groups(
    space_id: str,
    scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    *,
    error_type: type[RuntimeError],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, set[str]] = {}
    for scope in scopes:
        if type(scope) is not BenchmarkUnsealedProjectionScope:
            raise error_type("graphiti recovery scope is invalid")
        group_id = graphiti_group_id(space_id, scope.memory_scope_id)
        grouped.setdefault(group_id, set()).update(scope.fact_ids)
    return {group_id: tuple(sorted(fact_ids)) for group_id, fact_ids in sorted(grouped.items())}


def _merge_snapshots(
    snapshots: tuple[GraphProjectionIdentitySnapshot, ...],
) -> GraphProjectionIdentitySnapshot:
    if not snapshots:
        return GraphProjectionIdentitySnapshot()
    return GraphProjectionIdentitySnapshot(
        group_ids=tuple(sorted(group for item in snapshots for group in item.group_ids)),
        episode_ids=tuple(sorted(identity for item in snapshots for identity in item.episode_ids)),
        entity_ids=tuple(sorted(identity for item in snapshots for identity in item.entity_ids)),
        mentions_edge_ids=tuple(
            sorted(identity for item in snapshots for identity in item.mentions_edge_ids)
        ),
        relates_to_edge_ids=tuple(
            sorted(identity for item in snapshots for identity in item.relates_to_edge_ids)
        ),
    )


def _mapping(value: object, *, error_type: type[RuntimeError]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error_type("graphiti identity evidence record is invalid")
    return value


def _record_identity(
    record: Mapping[str, object],
    field_name: str,
    *,
    error_type: type[RuntimeError],
) -> str:
    value = record.get(field_name)
    _identity(value, field_name=field_name, error_type=error_type)
    return value


def _identity(
    value: object,
    *,
    field_name: str,
    error_type: type[RuntimeError],
) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise error_type(f"graphiti identity {field_name} is invalid")


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ("delete_benchmark_space_two_pass",)
