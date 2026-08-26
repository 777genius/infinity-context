"""Bounded Postgres reads and local schema for cleanup-v3 receipt scratch."""

from __future__ import annotations

import sqlite3
from typing import Final

RECEIPT_PAGE_SIZE: Final = 512
RECEIPT_PAGE_SQL: Final = """
SELECT r.outbox_id, to_jsonb(r) AS receipt,
       jsonb_build_object(
         'id',o.id,'message_key',o.message_key,'event_type',o.event_type,
         'aggregate_type',o.aggregate_type,'aggregate_id',o.aggregate_id,
         'aggregate_version',o.aggregate_version,'created_at',o.created_at,
         'status',o.status,
         'payload_without_chunk_ids',o.payload_json - 'chunk_ids',
         'payload_identity_count',CASE WHEN o.payload_json ? 'chunk_ids'
           THEN jsonb_array_length(o.payload_json -> 'chunk_ids') ELSE NULL END
       ) AS outbox
FROM memory_projection_result_receipts r
JOIN memory_outbox o ON o.id=r.outbox_id
WHERE r.run_id_sha256=$1 AND r.context_sha256=$2 AND r.space_id=$3
  AND r.outbox_id > $4
ORDER BY r.outbox_id
LIMIT $5
"""
LINK_PAGE_SQL: Final = """
SELECT l.outbox_id, l.ordinal, to_jsonb(l) AS link, to_jsonb(i) AS identity
FROM memory_projection_receipt_identity_links l
JOIN memory_projection_result_receipts r
  ON r.outbox_id=l.outbox_id AND r.run_id_sha256=l.run_id_sha256
JOIN memory_projection_target_identities i
  ON i.run_id_sha256=l.run_id_sha256 AND i.kind=l.kind
 AND i.identity_sha256=l.identity_sha256
 AND i.identity_commitment_sha256=l.identity_commitment_sha256
WHERE r.run_id_sha256=$1 AND r.context_sha256=$2 AND r.space_id=$3
  AND (l.outbox_id,l.ordinal) > ($4,$5)
ORDER BY l.outbox_id,l.ordinal
LIMIT $6
"""
PAYLOAD_PAGE_SQL: Final = """
SELECT o.id AS outbox_id, n AS ordinal,
       o.payload_json -> 'chunk_ids' ->> n AS source_id
FROM memory_projection_result_receipts r
JOIN memory_outbox o ON o.id=r.outbox_id
CROSS JOIN LATERAL generate_series(
  0,
  jsonb_array_length(o.payload_json -> 'chunk_ids') - 1
) AS n
WHERE r.run_id_sha256=$1 AND r.context_sha256=$2 AND r.space_id=$3
  AND o.payload_json ? 'chunk_ids'
  AND (o.id,n) > ($4,$5)
ORDER BY o.id,n
LIMIT $6
"""


def create_receipt_scratch_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE receipt_session(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          state TEXT NOT NULL CHECK(state IN ('active','finalized')),
          terminal_sha TEXT NOT NULL, session_sha TEXT NOT NULL, row_mac TEXT NOT NULL
        ) STRICT;
        CREATE TABLE verified_receipts(
          outbox_id INTEGER PRIMARY KEY, header_sha TEXT NOT NULL,
          receipt_sha TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, row_mac TEXT NOT NULL
        ) STRICT;
        CREATE TABLE verified_links(
          outbox_id INTEGER NOT NULL, ordinal INTEGER NOT NULL,
          inventory_kind TEXT NOT NULL, identity_kind TEXT NOT NULL,
          identity_sha TEXT NOT NULL, identity_commitment TEXT NOT NULL,
          evidence_sha TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
          row_mac TEXT NOT NULL,
          PRIMARY KEY(outbox_id,ordinal,inventory_kind)
        ) STRICT;
        CREATE TABLE verified_receipt_sources(
          outbox_id INTEGER NOT NULL, ordinal INTEGER NOT NULL, source_id TEXT NOT NULL,
          claimed INTEGER NOT NULL DEFAULT 0, row_mac TEXT NOT NULL,
          PRIMARY KEY(outbox_id,source_id), UNIQUE(outbox_id,ordinal)
        ) STRICT;
        """
    )


__all__ = (
    "LINK_PAGE_SQL",
    "PAYLOAD_PAGE_SQL",
    "RECEIPT_PAGE_SIZE",
    "RECEIPT_PAGE_SQL",
    "create_receipt_scratch_schema",
)
