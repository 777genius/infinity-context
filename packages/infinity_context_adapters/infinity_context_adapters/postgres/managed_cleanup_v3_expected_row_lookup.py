"""Authenticated bounded lookups over the sealed cleanup-v4 expected-row index."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error

_OPERATION_VALUES = (
    "sequence,lane,corpus_sha,scope_sha,thread_sha,source_sha,content_sha,"
    "commitment_sha,operation_sha,source_refs_sha,source_ref_root_sha,"
    "source_ref_count,fragments_sha,fragment_root_sha,fragment_count"
)


class _RowVerifier(Protocol):
    def verify_index_row(
        self,
        context_sha256: str,
        table: str,
        values: tuple[object, ...],
        authentication_tag: str,
    ) -> None: ...


@final
@dataclass(frozen=True, slots=True)
class ExpectedCleanupV3Operation:
    sequence: int
    lane: str
    corpus_identity_sha256: str
    memory_scope_external_ref_sha256: str
    thread_external_ref_sha256: str
    source_identity_sha256: str
    source_content_sha256: str
    operation_commitment_sha256: str
    operation_sha256: str
    source_refs_sha256: str
    source_ref_root_sha256: str
    source_ref_count: int
    fragments_sha256: str
    fragment_root_sha256: str
    fragment_count: int


@final
class AuthenticatedExpectedRowLookup:
    def __init__(self, db: sqlite3.Connection, verifier: _RowVerifier, context_sha256: str) -> None:
        self._db = db
        self._verifier = verifier
        self._context = context_sha256

    def lookup_sequence(self, sequence: int) -> ExpectedCleanupV3Operation | None:
        if type(sequence) is not int or sequence < 0:
            _fail("lookup_invalid")
        return self._operation(
            self._db.execute(
                f"SELECT {_OPERATION_VALUES},authentication_tag FROM operations WHERE sequence=?",
                (sequence,),
            ).fetchone()
        )

    def lookup_source(self, source_sha: str) -> ExpectedCleanupV3Operation | None:
        return self._operation(
            self._db.execute(
                f"SELECT {_OPERATION_VALUES},authentication_tag FROM operations WHERE source_sha=?",
                (source_sha,),
            ).fetchone()
        )

    def has_corpus(self, corpus_sha: str) -> bool:
        row = self._db.execute(
            "SELECT corpus_sha,first_sequence,authentication_tag FROM corpora WHERE corpus_sha=?",
            (corpus_sha,),
        ).fetchone()
        if row is None:
            return False
        self._verify("corpora", row)
        return True

    def lookup_fragment(
        self, *, sequence: int, ordinal: int, descriptor_sha256: str
    ) -> tuple[ExpectedCleanupV3Operation, int] | None:
        row = self._db.execute(
            "SELECT sequence,ordinal,descriptor_sha,authentication_tag FROM fragments "
            "WHERE sequence=? AND ordinal=? AND descriptor_sha=?",
            (sequence, ordinal, descriptor_sha256),
        ).fetchone()
        if row is None:
            return None
        self._verify("fragments", row)
        operation = self.lookup_sequence(int(row[0]))
        return None if operation is None else (operation, int(row[1]))

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]:
        return self._descriptors("source_refs", sequence)

    def lookup_fragment_descriptors(self, sequence: int) -> tuple[str, ...]:
        return self._descriptors("fragments", sequence)

    def _descriptors(self, table: str, sequence: int) -> tuple[str, ...]:
        result: list[str] = []
        for row in self._db.execute(
            f"SELECT sequence,ordinal,descriptor_sha,authentication_tag FROM {table} "
            "WHERE sequence=? ORDER BY ordinal",
            (sequence,),
        ):
            self._verify(table, row)
            result.append(str(row[2]))
        return tuple(result)

    def _operation(self, row: tuple[object, ...] | None) -> ExpectedCleanupV3Operation | None:
        if row is None:
            return None
        values = self._verify("operations", row)
        return ExpectedCleanupV3Operation(*values)  # type: ignore[arg-type]

    def _verify(self, table: str, row: tuple[object, ...]) -> tuple[object, ...]:
        values = tuple(row[:-1])
        self._verifier.verify_index_row(self._context, table, values, str(row[-1]))
        return values


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_{suffix}")


__all__ = ("AuthenticatedExpectedRowLookup", "ExpectedCleanupV3Operation")
