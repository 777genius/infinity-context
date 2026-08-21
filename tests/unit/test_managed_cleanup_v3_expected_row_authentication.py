from __future__ import annotations

import sqlite3

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authentication import (
    expected_index_row_tag,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_claims import (
    DurableExpectedRowClaims,
    create_claim_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    create_index_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_lookup import (
    AuthenticatedExpectedRowLookup,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error


def test_authenticated_lookup_rejects_every_tampered_row_kind() -> None:
    authority_db = sqlite3.connect(":memory:")
    state_db = sqlite3.connect(":memory:")
    create_index_schema(authority_db)
    create_claim_schema(state_db)
    key, context, terminal = b"r" * 32, "c" * 64, "a" * 64
    claims = DurableExpectedRowClaims(authority_db, state_db, key, terminal)
    lookup = AuthenticatedExpectedRowLookup(authority_db, claims, context)

    corpus = ("a" * 64, 0)
    operation = (
        0,
        "document",
        corpus[0],
        "b" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        1,
        "5" * 64,
        "6" * 64,
        1,
    )
    source_ref = (0, 0, "7" * 64)
    fragment = (0, 0, "8" * 64)

    def tagged(table, values):
        return (
            *values,
            expected_index_row_tag(
                key,
                context_sha256=context,
                authority_terminal_sha256=terminal,
                table=table,
                values=values,
            ),
        )

    authority_db.execute("INSERT INTO corpora VALUES(?,?,?)", tagged("corpora", corpus))
    authority_db.execute(
        "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        tagged("operations", operation),
    )
    authority_db.execute(
        "INSERT INTO source_refs VALUES(?,?,?,?)", tagged("source_refs", source_ref)
    )
    authority_db.execute("INSERT INTO fragments VALUES(?,?,?,?)", tagged("fragments", fragment))
    authority_db.commit()
    assert lookup.lookup_sequence(0) is not None

    for sql, verify in (
        ("UPDATE corpora SET first_sequence=1", lambda: lookup.has_corpus(corpus[0])),
        ("UPDATE operations SET content_sha='tampered'", lambda: lookup.lookup_sequence(0)),
        (
            "UPDATE source_refs SET descriptor_sha='tampered'",
            lambda: lookup.lookup_source_ref_descriptors(0),
        ),
        (
            "UPDATE fragments SET descriptor_sha='tampered'",
            lambda: lookup.lookup_fragment_descriptors(0),
        ),
    ):
        authority_db.execute(sql)
        with pytest.raises(ManagedCleanupV3Error, match="row_authentication_invalid"):
            verify()
        authority_db.rollback()
    claims.close()
