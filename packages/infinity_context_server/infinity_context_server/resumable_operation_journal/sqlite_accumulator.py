"""SQLite persistence for the journal's fixed-depth authenticated trees."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import final

from infinity_context_server.resumable_operation_journal.commitments import (
    CommitmentNode,
    combine_nodes,
    default_node,
    tree_depth,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationJournalError,
)

_UPSERT_NODE = """
    INSERT INTO operation_commitment_nodes(
        run_id, tree_kind, level, node_index, commitment_sha256,
        valid_count, pending_count, dispatched_count, committed_count,
        outcome_unknown_count, receipt_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(run_id, tree_kind, level, node_index) DO UPDATE SET
        commitment_sha256=excluded.commitment_sha256,
        valid_count=excluded.valid_count,
        pending_count=excluded.pending_count,
        dispatched_count=excluded.dispatched_count,
        committed_count=excluded.committed_count,
        outcome_unknown_count=excluded.outcome_unknown_count,
        receipt_count=excluded.receipt_count
"""


@final
class SQLiteCommitmentTree:
    """Authenticate and update one leaf using at most the fixed tree depth."""

    __slots__ = ("_connection", "_expected", "_kind", "_observe", "_run_id")

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        tree_kind: str,
        expected_operation_count: int,
        observe: Callable[[str, int], None] | None = None,
    ) -> None:
        self._connection = connection
        self._run_id = run_id
        self._kind = tree_kind
        self._expected = expected_operation_count
        self._observe = observe
        tree_depth(expected_operation_count)

    def authenticate_leaf(
        self,
        *,
        ordinal: int,
        leaf: CommitmentNode,
        expected_root: CommitmentNode,
    ) -> None:
        observed = self._root_from_path(ordinal=ordinal, leaf=leaf)
        if observed != expected_root:
            raise OperationJournalError("operation_journal_projection_authentication_invalid")

    def update_leaf(
        self,
        *,
        ordinal: int,
        previous_leaf: CommitmentNode,
        next_leaf: CommitmentNode,
        expected_root: CommitmentNode,
    ) -> CommitmentNode:
        self.authenticate_leaf(
            ordinal=ordinal,
            leaf=previous_leaf,
            expected_root=expected_root,
        )
        level = 0
        node_index = ordinal
        current = next_leaf
        self._put_node(level=level, node_index=node_index, node=current)
        depth = tree_depth(self._expected)
        while level < depth:
            sibling_index = node_index ^ 1
            sibling = self._load_node(level=level, node_index=sibling_index)
            if node_index & 1:
                current = combine_nodes(self._kind, level + 1, sibling, current)
            else:
                current = combine_nodes(self._kind, level + 1, current, sibling)
            level += 1
            node_index >>= 1
            self._put_node(level=level, node_index=node_index, node=current)
        return current

    def find_first(
        self,
        *,
        expected_root: CommitmentNode,
        count: Callable[[CommitmentNode], int],
    ) -> int | None:
        if count(expected_root) == 0:
            return None
        level = tree_depth(self._expected)
        node_index = 0
        current = self._load_node(level=level, node_index=node_index)
        if current != expected_root:
            raise OperationJournalError("operation_journal_projection_authentication_invalid")
        while level > 0:
            child_level = level - 1
            left = self._load_node(level=child_level, node_index=node_index * 2)
            right = self._load_node(level=child_level, node_index=node_index * 2 + 1)
            if combine_nodes(self._kind, level, left, right) != current:
                raise OperationJournalError("operation_journal_projection_authentication_invalid")
            if count(left):
                current = left
                node_index *= 2
            elif count(right):
                current = right
                node_index = node_index * 2 + 1
            else:
                raise OperationJournalError("operation_journal_projection_authentication_invalid")
            level = child_level
        if node_index >= self._expected:
            raise OperationJournalError("operation_journal_projection_authentication_invalid")
        return node_index

    def root_node(self) -> CommitmentNode:
        return self._load_node(level=tree_depth(self._expected), node_index=0)

    def _root_from_path(self, *, ordinal: int, leaf: CommitmentNode) -> CommitmentNode:
        if not 0 <= ordinal < self._expected:
            raise OperationJournalError("operation_journal_ordinal_invalid")
        current = leaf
        node_index = ordinal
        depth = tree_depth(self._expected)
        for level in range(depth):
            sibling = self._load_node(level=level, node_index=node_index ^ 1)
            if node_index & 1:
                current = combine_nodes(self._kind, level + 1, sibling, current)
            else:
                current = combine_nodes(self._kind, level + 1, current, sibling)
            node_index >>= 1
        return current

    def _load_node(self, *, level: int, node_index: int) -> CommitmentNode:
        row = self._connection.execute(
            """SELECT commitment_sha256, valid_count, pending_count,
                      dispatched_count, committed_count, outcome_unknown_count,
                      receipt_count
               FROM operation_commitment_nodes
               WHERE run_id=? AND tree_kind=? AND level=? AND node_index=?""",
            (self._run_id, self._kind, level, node_index),
        ).fetchone()
        if self._observe is not None:
            self._observe("accumulator_node_reads", 1)
        if row is None:
            return default_node(
                self._kind,
                level=level,
                node_index=node_index,
                expected_operation_count=self._expected,
            )
        try:
            return CommitmentNode(
                commitment_sha256=str(row[0]),
                valid_count=int(row[1]),
                pending_count=int(row[2]),
                dispatched_count=int(row[3]),
                committed_count=int(row[4]),
                outcome_unknown_count=int(row[5]),
                receipt_count=int(row[6]),
            )
        except (TypeError, ValueError) as error:
            raise OperationJournalError(
                "operation_journal_projection_authentication_invalid"
            ) from error

    def _put_node(
        self,
        *,
        level: int,
        node_index: int,
        node: CommitmentNode,
    ) -> None:
        self._connection.execute(
            _UPSERT_NODE,
            (
                self._run_id,
                self._kind,
                level,
                node_index,
                node.commitment_sha256,
                node.valid_count,
                node.pending_count,
                node.dispatched_count,
                node.committed_count,
                node.outcome_unknown_count,
                node.receipt_count,
            ),
        )
        if self._observe is not None:
            self._observe("accumulator_node_writes", 1)


__all__ = ("SQLiteCommitmentTree",)
