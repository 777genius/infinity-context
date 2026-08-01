import pytest
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.graph_evidence import (
    GraphProjectionDeleteEvidence,
    GraphProjectionDeletePass,
    GraphProjectionIdentitySnapshot,
)


def _snapshot() -> GraphProjectionIdentitySnapshot:
    return GraphProjectionIdentitySnapshot(
        group_ids=("group-1",),
        episode_ids=("episode-1",),
        entity_ids=("entity-1",),
        mentions_edge_ids=("mentions-1",),
        relates_to_edge_ids=("relates-1",),
    )


def test_graph_projection_identity_snapshot_exposes_only_sorted_physical_identities() -> None:
    snapshot = _snapshot()

    assert snapshot.identity_count == 4
    assert snapshot.node_ids == ("episode-1", "entity-1")
    assert snapshot.edge_ids == ("mentions-1", "relates-1")
    assert not snapshot.empty


@pytest.mark.parametrize(
    "kwargs",
    [
        {"group_ids": ("group-1",), "episode_ids": ("z", "a")},
        {"group_ids": ("group-1",), "episode_ids": ("same",), "entity_ids": ("same",)},
        {"episode_ids": ("episode-1",)},
        {"group_ids": ("group-1",)},
    ],
)
def test_graph_projection_identity_snapshot_rejects_ambiguous_inventories(
    kwargs: dict[str, tuple[str, ...]],
) -> None:
    with pytest.raises(MemoryValidationError):
        GraphProjectionIdentitySnapshot(**kwargs)


def test_graph_projection_delete_evidence_requires_exact_idempotent_two_pass_absence() -> None:
    expected = _snapshot()
    empty = GraphProjectionIdentitySnapshot()

    evidence = GraphProjectionDeleteEvidence(
        group_id="group-1",
        expected=expected,
        first_pass=GraphProjectionDeletePass(1, expected, expected, empty, empty),
        second_pass=GraphProjectionDeletePass(2, empty, empty, empty, empty),
    )

    assert evidence.verified_absent


def test_graph_projection_delete_evidence_rejects_residual_global_identity() -> None:
    expected = _snapshot()
    empty = GraphProjectionIdentitySnapshot()

    with pytest.raises(MemoryValidationError):
        GraphProjectionDeleteEvidence(
            group_id="group-1",
            expected=expected,
            first_pass=GraphProjectionDeletePass(1, expected, expected, empty, expected),
            second_pass=GraphProjectionDeletePass(2, empty, empty, empty, empty),
        )
