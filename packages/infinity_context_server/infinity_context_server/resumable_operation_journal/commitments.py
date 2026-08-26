"""Bounded authenticated accumulators for operation-journal projections."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import final

from infinity_context_server.resumable_operation_journal.domain import (
    OperationJournalError,
    OperationJournalFacts,
    OperationState,
    OperationUnsettledState,
    VerifiedOperationReceipt,
    operation_state_projection,
    sha256_commitment,
    verified_receipt_projection,
)

STATE_TREE = "state"
RECEIPT_TREE = "receipt"
TREE_SCHEMA_VERSION = "operation-journal-merkle.v1"


@final
@dataclass(frozen=True, slots=True)
class CommitmentNode:
    commitment_sha256: str
    valid_count: int
    pending_count: int = 0
    dispatched_count: int = 0
    committed_count: int = 0
    outcome_unknown_count: int = 0
    receipt_count: int = 0

    def __post_init__(self) -> None:
        values = (
            self.valid_count,
            self.pending_count,
            self.dispatched_count,
            self.committed_count,
            self.outcome_unknown_count,
            self.receipt_count,
        )
        if (
            not _digest(self.commitment_sha256)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in values
            )
            or sum(values[1:5]) not in (0, self.valid_count)
            or self.receipt_count > self.valid_count
        ):
            raise OperationJournalError("operation_journal_commitment_node_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "commitment_sha256": self.commitment_sha256,
            "committed_count": self.committed_count,
            "dispatched_count": self.dispatched_count,
            "outcome_unknown_count": self.outcome_unknown_count,
            "pending_count": self.pending_count,
            "receipt_count": self.receipt_count,
            "valid_count": self.valid_count,
        }


def tree_depth(expected_operation_count: int) -> int:
    if (
        not isinstance(expected_operation_count, int)
        or isinstance(expected_operation_count, bool)
        or expected_operation_count <= 0
    ):
        raise OperationJournalError("operation_journal_expected_count_invalid")
    return (expected_operation_count - 1).bit_length()


def leaf_count(expected_operation_count: int) -> int:
    return 1 << tree_depth(expected_operation_count)


@cache
def homogeneous_default_node(tree_kind: str, level: int, *, valid: bool) -> CommitmentNode:
    if tree_kind not in (STATE_TREE, RECEIPT_TREE) or level < 0:
        raise OperationJournalError("operation_journal_commitment_tree_invalid")
    if level == 0:
        if valid:
            counts = {"valid_count": 1}
            if tree_kind == STATE_TREE:
                counts["pending_count"] = 1
            leaf_kind = "implicit_pending" if tree_kind == STATE_TREE else "empty_receipt"
        else:
            counts = {"valid_count": 0}
            leaf_kind = "padding"
        return CommitmentNode(
            commitment_sha256=sha256_commitment(
                {
                    "leaf_kind": leaf_kind,
                    "schema_version": TREE_SCHEMA_VERSION,
                    "tree_kind": tree_kind,
                }
            ),
            **counts,
        )
    child = homogeneous_default_node(tree_kind, level - 1, valid=valid)
    return combine_nodes(tree_kind, level, child, child)


def default_node(
    tree_kind: str,
    *,
    level: int,
    node_index: int,
    expected_operation_count: int,
) -> CommitmentNode:
    width = 1 << level
    start = node_index * width
    end = start + width
    if end <= expected_operation_count:
        return homogeneous_default_node(tree_kind, level, valid=True)
    if start >= expected_operation_count:
        return homogeneous_default_node(tree_kind, level, valid=False)
    if level == 0:
        raise OperationJournalError("operation_journal_commitment_tree_invalid")
    left = default_node(
        tree_kind,
        level=level - 1,
        node_index=node_index * 2,
        expected_operation_count=expected_operation_count,
    )
    right = default_node(
        tree_kind,
        level=level - 1,
        node_index=node_index * 2 + 1,
        expected_operation_count=expected_operation_count,
    )
    return combine_nodes(tree_kind, level, left, right)


def state_leaf(state: OperationState | None) -> CommitmentNode:
    if state is None:
        return homogeneous_default_node(STATE_TREE, 0, valid=True)
    counts = {
        "pending_count": 0,
        "dispatched_count": 0,
        "committed_count": 0,
        "outcome_unknown_count": 0,
    }
    counts[f"{state.phase.value}_count"] = 1
    return CommitmentNode(
        commitment_sha256=sha256_commitment(
            {
                "projection": operation_state_projection(state),
                "schema_version": TREE_SCHEMA_VERSION,
                "tree_kind": STATE_TREE,
            }
        ),
        valid_count=1,
        **counts,
    )


def receipt_leaf(
    ordinal: int,
    verified: VerifiedOperationReceipt | None,
) -> CommitmentNode:
    if verified is None:
        return homogeneous_default_node(RECEIPT_TREE, 0, valid=True)
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise OperationJournalError("operation_journal_receipt_ordinal_invalid")
    return CommitmentNode(
        commitment_sha256=sha256_commitment(
            {
                "ordinal": ordinal,
                "projection": verified_receipt_projection(verified),
                "schema_version": TREE_SCHEMA_VERSION,
                "tree_kind": RECEIPT_TREE,
            }
        ),
        valid_count=1,
        receipt_count=1,
    )


def combine_nodes(
    tree_kind: str,
    level: int,
    left: CommitmentNode,
    right: CommitmentNode,
) -> CommitmentNode:
    if tree_kind not in (STATE_TREE, RECEIPT_TREE) or level <= 0:
        raise OperationJournalError("operation_journal_commitment_tree_invalid")
    counts = {
        name: getattr(left, name) + getattr(right, name)
        for name in (
            "valid_count",
            "pending_count",
            "dispatched_count",
            "committed_count",
            "outcome_unknown_count",
            "receipt_count",
        )
    }
    payload = {
        "counts": counts,
        "left": left.commitment_sha256,
        "level": level,
        "right": right.commitment_sha256,
        "schema_version": TREE_SCHEMA_VERSION,
        "tree_kind": tree_kind,
    }
    return CommitmentNode(commitment_sha256=sha256_commitment(payload), **counts)


def initial_facts(expected_operation_count: int) -> OperationJournalFacts:
    depth = tree_depth(expected_operation_count)
    state = default_node(
        STATE_TREE,
        level=depth,
        node_index=0,
        expected_operation_count=expected_operation_count,
    )
    receipts = default_node(
        RECEIPT_TREE,
        level=depth,
        node_index=0,
        expected_operation_count=expected_operation_count,
    )
    return facts_from_roots(state=state, receipts=receipts, committed_prefix_count=0)


def facts_from_roots(
    *,
    state: CommitmentNode,
    receipts: CommitmentNode,
    committed_prefix_count: int,
    first_unsettled: OperationUnsettledState | None = None,
) -> OperationJournalFacts:
    if state.valid_count != receipts.valid_count:
        raise OperationJournalError("operation_journal_commitment_tree_invalid")
    return OperationJournalFacts(
        expected_operation_count=state.valid_count,
        pending_count=state.pending_count,
        dispatched_count=state.dispatched_count,
        committed_count=state.committed_count,
        outcome_unknown_count=state.outcome_unknown_count,
        receipt_count=receipts.receipt_count,
        committed_prefix_count=committed_prefix_count,
        state_commitment_sha256=state.commitment_sha256,
        receipts_commitment_sha256=receipts.commitment_sha256,
        first_unsettled=first_unsettled,
    )


@final
class StreamingCommitmentTree:
    """Build one complete Merkle root with O(log N) retained nodes."""

    __slots__ = ("_expected", "_frontier", "_kind", "_next")

    def __init__(self, tree_kind: str, expected_operation_count: int) -> None:
        if tree_kind not in (STATE_TREE, RECEIPT_TREE):
            raise OperationJournalError("operation_journal_commitment_tree_invalid")
        tree_depth(expected_operation_count)
        self._kind = tree_kind
        self._expected = expected_operation_count
        self._frontier: list[CommitmentNode | None] = [None] * (
            tree_depth(expected_operation_count) + 1
        )
        self._next = 0

    def append(self, node: CommitmentNode) -> None:
        if self._next >= leaf_count(self._expected) or node.valid_count not in (0, 1):
            raise OperationJournalError("operation_journal_commitment_stream_invalid")
        level = 0
        current = node
        position = self._next
        while position & 1:
            left = self._frontier[level]
            if left is None:
                raise OperationJournalError("operation_journal_commitment_stream_invalid")
            current = combine_nodes(self._kind, level + 1, left, current)
            self._frontier[level] = None
            position >>= 1
            level += 1
        self._frontier[level] = current
        self._next += 1

    def finish(self) -> CommitmentNode:
        total = leaf_count(self._expected)
        while self._next < total:
            self.append(
                homogeneous_default_node(
                    self._kind,
                    0,
                    valid=self._next < self._expected,
                )
            )
        root = self._frontier[tree_depth(self._expected)]
        if root is None or any(self._frontier[:-1]):
            raise OperationJournalError("operation_journal_commitment_stream_invalid")
        return root


def unsettled_from_state(state: OperationState) -> OperationUnsettledState:
    if state.request_commitment_sha256 is None:
        raise OperationJournalError("operation_journal_unsettled_request_missing")
    return OperationUnsettledState(
        ordinal=state.identity.ordinal,
        logical_operation_id=state.identity.logical_operation_id,
        phase=state.phase,
        request_commitment_sha256=state.request_commitment_sha256,
    )


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = (
    "CommitmentNode",
    "RECEIPT_TREE",
    "STATE_TREE",
    "StreamingCommitmentTree",
    "combine_nodes",
    "default_node",
    "facts_from_roots",
    "homogeneous_default_node",
    "initial_facts",
    "leaf_count",
    "receipt_leaf",
    "state_leaf",
    "tree_depth",
    "unsettled_from_state",
)
