from __future__ import annotations

import pytest

from scripts.pytest_ci_shard import (
    select_nodeids_for_shard,
    shard_index_for_nodeid,
    validate_shard,
)


def test_shard_assignment_is_stable() -> None:
    nodeids = (
        "tests/unit/test_a.py::test_one",
        "tests/e2e/test_b.py::test_two[param]",
        "packages/pkg/test_c.py::test_three",
    )

    assert [
        shard_index_for_nodeid(nodeid, shard_total=8) for nodeid in nodeids
    ] == [5, 5, 3]


def test_shards_are_exhaustive_and_exclusive() -> None:
    nodeids = tuple(
        f"tests/unit/test_example_{module}.py::test_case[{case}]"
        for module in range(125)
        for case in range(4)
    )
    shards = tuple(
        select_nodeids_for_shard(
            nodeids,
            shard_index=shard_index,
            shard_total=8,
        )
        for shard_index in range(8)
    )

    assert sorted(nodeid for shard in shards for nodeid in shard) == sorted(nodeids)
    assert sum(len(shard) for shard in shards) == len(nodeids)
    for shard_index, shard in enumerate(shards):
        assert all(
            shard_index_for_nodeid(nodeid, shard_total=8) == shard_index
            for nodeid in shard
        )


def test_tests_from_same_module_stay_together() -> None:
    nodeids = tuple(f"tests/unit/test_example.py::test_case[{index}]" for index in range(50))

    assignments = {shard_index_for_nodeid(nodeid, shard_total=8) for nodeid in nodeids}

    assert len(assignments) == 1


def test_selector_preserves_collection_order() -> None:
    nodeids = tuple(f"test_module_{index}.py::test_case" for index in range(20))

    selected = select_nodeids_for_shard(
        nodeids,
        shard_index=2,
        shard_total=8,
    )

    assert selected
    assert selected == tuple(
        nodeid
        for nodeid in nodeids
        if shard_index_for_nodeid(nodeid, shard_total=8) == 2
    )


@pytest.mark.parametrize(
    ("shard_index", "shard_total"),
    [
        (-1, 8),
        (8, 8),
        (0, 0),
    ],
)
def test_invalid_shard_configuration_is_rejected(
    shard_index: int,
    shard_total: int,
) -> None:
    with pytest.raises(ValueError):
        validate_shard(shard_index=shard_index, shard_total=shard_total)
