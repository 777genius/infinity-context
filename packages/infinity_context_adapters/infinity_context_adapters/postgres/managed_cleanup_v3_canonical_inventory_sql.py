"""SQL and canonical kind mappings for managed cleanup v3 inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class _Query:
    sql: str
    cursor_types: tuple[type, ...]


SIMPLE_QUERIES: Final = {
    "memory_scopes": _Query(
        """
        SELECT jsonb_build_object('id', s.id) AS locator_json,
               to_jsonb(s) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', authority.thread_external_ref,
                       'lane', authority.lane
                   )
               ) AS row_json,
               s.id AS cursor_1
        FROM memory_scopes AS s
        JOIN LATERAL (
            SELECT t.external_ref AS thread_external_ref, source.lane
            FROM memory_threads AS t
            JOIN LATERAL (
                SELECT 'fact'::text AS lane
                FROM memory_facts AS f
                WHERE f.space_id = s.space_id
                  AND f.memory_scope_id = s.id AND f.thread_id = t.id
                UNION ALL
                SELECT 'document'::text AS lane
                FROM memory_documents AS d
                WHERE d.space_id = s.space_id
                  AND d.memory_scope_id = s.id AND d.thread_id = t.id
                ORDER BY lane
                LIMIT 1
            ) AS source ON TRUE
            WHERE t.space_id = s.space_id AND t.memory_scope_id = s.id
            ORDER BY t.id
            LIMIT 1
        ) AS authority ON TRUE
        WHERE s.space_id = $1 AND ($2::text IS NULL OR s.id > $2)
        ORDER BY s.id LIMIT $3
        """,
        (str,),
    ),
    "memory_threads": _Query(
        """
        SELECT jsonb_build_object('id', t.id) AS locator_json,
               to_jsonb(t) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', t.external_ref,
                       'lane', authority.lane
                   )
               ) AS row_json,
               t.id AS cursor_1
        FROM memory_threads AS t
        JOIN memory_scopes AS s
          ON s.id = t.memory_scope_id AND s.space_id = t.space_id
        JOIN LATERAL (
            SELECT lane
            FROM (
                SELECT 'fact'::text AS lane
                FROM memory_facts AS f
                WHERE f.space_id = t.space_id
                  AND f.memory_scope_id = t.memory_scope_id AND f.thread_id = t.id
                UNION ALL
                SELECT 'document'::text AS lane
                FROM memory_documents AS d
                WHERE d.space_id = t.space_id
                  AND d.memory_scope_id = t.memory_scope_id AND d.thread_id = t.id
            ) AS source
            ORDER BY lane
            LIMIT 1
        ) AS authority ON TRUE
        WHERE t.space_id = $1 AND ($2::text IS NULL OR t.id > $2)
        ORDER BY t.id LIMIT $3
        """,
        (str,),
    ),
    "facts": _Query(
        """
        SELECT jsonb_build_object('id', f.id) AS locator_json,
               to_jsonb(f) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', t.external_ref,
                       'ordered_source_refs', refs.ordered_source_refs
                   )
               ) AS row_json,
               f.id AS cursor_1
        FROM memory_facts AS f
        JOIN memory_scopes AS s
          ON s.id = f.memory_scope_id AND s.space_id = f.space_id
        JOIN memory_threads AS t
          ON t.id = f.thread_id AND t.memory_scope_id = f.memory_scope_id
         AND t.space_id = f.space_id
        JOIN memory_fact_versions AS fv
          ON fv.fact_id = f.id AND fv.version = f.version
        JOIN LATERAL (
            SELECT jsonb_agg(to_jsonb(sr) ORDER BY sr.id) AS ordered_source_refs,
                   count(*) AS source_ref_count
            FROM (
                SELECT bounded.* FROM memory_source_refs AS bounded
                WHERE bounded.fact_id = f.id AND bounded.fact_version = f.version
                ORDER BY bounded.id LIMIT 2
            ) AS sr
        ) AS refs ON refs.source_ref_count = 1
        WHERE f.space_id = $1 AND ($2::text IS NULL OR f.id > $2)
        ORDER BY f.id LIMIT $3
        """,
        (str,),
    ),
    "documents": _Query(
        """
        SELECT jsonb_build_object('id', d.id) AS locator_json,
               to_jsonb(d) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', t.external_ref,
                       'ordered_chunks', chunks.ordered_chunks
                   )
               ) AS row_json,
               d.id AS cursor_1
        FROM memory_documents AS d
        JOIN memory_scopes AS s
          ON s.id = d.memory_scope_id AND s.space_id = d.space_id
        JOIN memory_threads AS t
          ON t.id = d.thread_id AND t.memory_scope_id = d.memory_scope_id
         AND t.space_id = d.space_id
        JOIN LATERAL (
            SELECT jsonb_agg(to_jsonb(bounded) ORDER BY bounded.sequence) AS ordered_chunks
            FROM (
                SELECT c.*
                FROM memory_chunks AS c
                WHERE c.space_id = d.space_id AND c.memory_scope_id = d.memory_scope_id
                  AND c.thread_id = d.thread_id AND c.document_id = d.id
                ORDER BY c.sequence
                LIMIT 106
            ) AS bounded
        ) AS chunks ON chunks.ordered_chunks IS NOT NULL
        WHERE d.space_id = $1 AND ($2::text IS NULL OR d.id > $2)
        ORDER BY d.id LIMIT $3
        """,
        (str,),
    ),
    "chunks": _Query(
        """
        SELECT jsonb_build_object('id', c.id) AS locator_json,
               to_jsonb(c) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'document', to_jsonb(d),
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', t.external_ref,
                       'chunk_ordinal', c.sequence
                   )
               ) AS row_json,
               c.id AS cursor_1
        FROM memory_chunks AS c
        JOIN memory_documents AS d
          ON d.id = c.document_id AND d.space_id = c.space_id
         AND d.memory_scope_id = c.memory_scope_id AND d.thread_id = c.thread_id
        JOIN memory_scopes AS s
          ON s.id = c.memory_scope_id AND s.space_id = c.space_id
        JOIN memory_threads AS t
          ON t.id = c.thread_id AND t.memory_scope_id = c.memory_scope_id
         AND t.space_id = c.space_id
        WHERE c.space_id = $1 AND ($2::text IS NULL OR c.id > $2)
        ORDER BY c.id LIMIT $3
        """,
        (str,),
    ),
    "fact_source_refs": _Query(
        """
        SELECT jsonb_build_object(
                   'id', sr.id, 'fact_id', sr.fact_id, 'fact_version', sr.fact_version
               ) AS locator_json,
               to_jsonb(sr) || jsonb_build_object(
                   '__authority_evidence', jsonb_build_object(
                       'canonical_fact', to_jsonb(f),
                       'memory_scope_external_ref', s.external_ref,
                       'thread_external_ref', t.external_ref,
                       'ordered_source_refs', refs.ordered_source_refs,
                       'source_ref_ordinal', 0
                   )
               ) AS row_json,
               sr.id AS cursor_1
        FROM memory_source_refs AS sr
        JOIN memory_facts AS f
          ON f.id = sr.fact_id AND f.version = sr.fact_version
        JOIN memory_fact_versions AS fv
          ON fv.fact_id = f.id AND fv.version = f.version
        JOIN memory_scopes AS s
          ON s.id = f.memory_scope_id AND s.space_id = f.space_id
        JOIN memory_threads AS t
          ON t.id = f.thread_id AND t.memory_scope_id = f.memory_scope_id
         AND t.space_id = f.space_id
        JOIN LATERAL (
            SELECT jsonb_agg(to_jsonb(candidate) ORDER BY candidate.id) AS ordered_source_refs,
                   count(*) AS source_ref_count
            FROM (
                SELECT bounded.* FROM memory_source_refs AS bounded
                WHERE bounded.fact_id = f.id AND bounded.fact_version = f.version
                ORDER BY bounded.id LIMIT 2
            ) AS candidate
        ) AS refs ON refs.source_ref_count = 1
        WHERE f.space_id = $1 AND ($2::bigint IS NULL OR sr.id > $2)
        ORDER BY sr.id LIMIT $3
        """,
        (int,),
    ),
}

CANONICAL_EVIDENCE: Final = {
    "memory_facts": (
        """to_jsonb(c) || jsonb_build_object(
               '__authority_evidence', jsonb_build_object(
                   'memory_scope_external_ref', cs.external_ref,
                   'thread_external_ref', ct.external_ref,
                   'ordered_source_refs', cr.ordered_source_refs))""",
        """JOIN LATERAL (
               SELECT cs.external_ref FROM memory_scopes AS cs
               WHERE cs.id = c.memory_scope_id AND cs.space_id = c.space_id
               LIMIT 1
           ) AS cs ON TRUE
           JOIN LATERAL (
               SELECT ct.external_ref FROM memory_threads AS ct
               WHERE ct.id = c.thread_id
                 AND ct.memory_scope_id = c.memory_scope_id
                 AND ct.space_id = c.space_id
               LIMIT 1
           ) AS ct ON TRUE
           JOIN memory_fact_versions AS cv
               ON cv.fact_id = c.id AND cv.version = c.version
           JOIN LATERAL (
               SELECT jsonb_agg(to_jsonb(sr) ORDER BY sr.id) AS ordered_source_refs,
                      count(*) AS source_ref_count
               FROM (
                   SELECT bounded.* FROM memory_source_refs AS bounded
                   WHERE bounded.fact_id = c.id AND bounded.fact_version = c.version
                   ORDER BY bounded.id LIMIT 2
               ) AS sr
           ) AS cr ON cr.source_ref_count = 1""",
    ),
    "memory_chunks": (
        """to_jsonb(c) || jsonb_build_object(
               '__authority_evidence', jsonb_build_object(
                   'document', to_jsonb(cd),
                   'memory_scope_external_ref', cs.external_ref,
                   'thread_external_ref', ct.external_ref,
                   'chunk_ordinal', c.sequence))""",
        """JOIN memory_documents AS cd
               ON cd.id = c.document_id AND cd.space_id = c.space_id
              AND cd.memory_scope_id = c.memory_scope_id AND cd.thread_id = c.thread_id
           JOIN LATERAL (
               SELECT cs.external_ref FROM memory_scopes AS cs
               WHERE cs.id = c.memory_scope_id AND cs.space_id = c.space_id
               LIMIT 1
           ) AS cs ON TRUE
           JOIN LATERAL (
               SELECT ct.external_ref FROM memory_threads AS ct
               WHERE ct.id = c.thread_id
                 AND ct.memory_scope_id = c.memory_scope_id
                 AND ct.space_id = c.space_id
               LIMIT 1
           ) AS ct ON TRUE""",
    ),
}


def canonical_evidence(canonical_table: str) -> tuple[str, str]:
    """Return the exact row expression and joins for a supported projection source."""

    try:
        return CANONICAL_EVIDENCE[canonical_table]
    except KeyError as exc:
        raise ValueError("unsupported canonical evidence table") from exc


def cleanup_receipts_sql() -> str:
    """Bind both projection lanes to the same canonical evidence representation."""

    fact_row, _ = canonical_evidence("memory_facts")
    chunk_row, _ = canonical_evidence("memory_chunks")
    return CLEANUP_RECEIPTS_SQL.format(
        fact_row_json=fact_row.replace("to_jsonb(c)", "to_jsonb(f)", 1),
        chunk_row_json=chunk_row,
    )


IDENTITY_KIND: Final = {
    "qdrant_target_identities": ("qdrant_point_id", "memory_chunks"),
    "graphiti_target_names": ("graphiti_episode_name", "memory_facts"),
    "graphiti_target_uuids": ("graphiti_episode_uuid", "memory_facts"),
}

JOB_KIND: Final = {
    "qdrant_upsert_jobs": (
        "qdrant",
        "upsert",
        "qdrant_point_id",
        "memory_chunks",
        ("vector.upsert_chunk", "vector.upsert_chunks"),
        "chunk",
    ),
    "qdrant_delete_jobs": (
        "qdrant",
        "delete",
        "qdrant_point_id",
        "memory_chunks",
        ("vector.delete_chunks",),
        "benchmark_run",
    ),
    "graphiti_upsert_jobs": (
        "graphiti",
        "upsert",
        "graphiti_episode_uuid",
        "memory_facts",
        ("graph.upsert_fact",),
        "fact",
    ),
    "graphiti_delete_jobs": (
        "graphiti",
        "delete",
        "graphiti_episode_uuid",
        "memory_facts",
        ("graph.delete_fact",),
        "benchmark_run",
    ),
}

IDENTITY_SQL: Final = """
WITH identity_page AS MATERIALIZED (
    SELECT i.*
    FROM memory_projection_target_identities AS i
    WHERE i.run_id_sha256 = $1 AND i.kind = $5
      AND (($8::char(64) IS NULL)
        OR (i.identity_sha256, i.identity_commitment_sha256)
           > ($8::char(64), $9::char(64)))
    ORDER BY i.identity_sha256, i.identity_commitment_sha256
    LIMIT $10
),
candidates AS MATERIALIZED (
    SELECT r.outbox_id, i.canonical_source_id,
           i.kind, i.identity_sha256, i.identity_commitment_sha256,
           i.lineage_root_sha256, i.target_authority_sha256,
           jsonb_build_object(
             'id',o.id,'message_key',o.message_key,'event_type',o.event_type,
             'aggregate_type',o.aggregate_type,'aggregate_id',o.aggregate_id,
             'aggregate_version',o.aggregate_version,'created_at',o.created_at,
             'status',o.status
           ) AS outbox_json,
           to_jsonb(r) AS receipt_json,
           to_jsonb(l) AS link_json,
           to_jsonb(i) AS identity_json
    FROM identity_page AS i
    JOIN LATERAL (
        SELECT l.* FROM memory_projection_receipt_identity_links AS l
        WHERE l.run_id_sha256 = i.run_id_sha256 AND l.kind = i.kind
          AND l.identity_sha256 = i.identity_sha256
          AND l.identity_commitment_sha256 = i.identity_commitment_sha256
        ORDER BY l.identity_sha256, l.identity_commitment_sha256, l.outbox_id
        OFFSET 0
        LIMIT 2
    ) AS l ON TRUE
    JOIN LATERAL (
        SELECT r.* FROM memory_projection_result_receipts AS r
        WHERE r.outbox_id = l.outbox_id AND r.run_id_sha256 = l.run_id_sha256
          AND r.context_sha256 = $2 AND r.space_id = $3 AND r.lane = $4
          AND r.operation = 'upsert' AND r.result_state = 'present'
        LIMIT 1
    ) AS r ON TRUE
    JOIN LATERAL (
        SELECT o.* FROM memory_outbox AS o
        WHERE o.id = l.outbox_id AND o.event_type = ANY($6::text[])
          AND o.aggregate_type = $7 AND o.aggregate_id = i.canonical_source_id
          AND o.status = 'done'
          AND (($4 = 'qdrant' AND (
                 (o.event_type = 'vector.upsert_chunk'
                  AND o.payload_json ->> 'chunk_id' = i.canonical_source_id)
              OR (o.event_type = 'vector.upsert_chunks'
                  AND o.payload_json -> 'chunk_ids'
                      = jsonb_build_array(i.canonical_source_id))))
            OR ($4 = 'graphiti'
                AND o.payload_json ->> 'fact_id' = i.canonical_source_id))
        LIMIT 1
    ) AS o ON TRUE
    ORDER BY i.identity_sha256, i.identity_commitment_sha256
    LIMIT $10
)
SELECT jsonb_build_object(
           'kind', candidate.kind,
           'identity_sha256', candidate.identity_sha256,
           'identity_commitment_sha256', candidate.identity_commitment_sha256,
           'lineage_root_sha256', candidate.lineage_root_sha256,
           'target_authority_sha256', candidate.target_authority_sha256
       ) AS locator_json,
       jsonb_build_object(
           'outbox', candidate.outbox_json,
           'receipt', candidate.receipt_json,
           'link', candidate.link_json,
           'identity', candidate.identity_json,
           'canonical_source', canonical.canonical_source
       ) AS row_json,
       candidate.identity_sha256 AS cursor_1,
       candidate.identity_commitment_sha256 AS cursor_2
FROM candidates AS candidate
JOIN LATERAL (
    SELECT {canonical_row_json} AS canonical_source
    FROM {canonical_table} AS c
    {canonical_authority_joins}
    WHERE c.id = candidate.canonical_source_id AND c.space_id = $3
    LIMIT 1
) AS canonical ON TRUE
ORDER BY candidate.identity_sha256, candidate.identity_commitment_sha256
"""

JOB_SQL: Final = """
WITH receipt_page AS MATERIALIZED (
    SELECT r.*
    FROM memory_projection_result_receipts AS r
    WHERE r.run_id_sha256 = $1 AND r.context_sha256 = $2 AND r.space_id = $3
      AND r.lane = $4 AND r.operation = $5
      AND r.outbox_id >= COALESCE($9::integer, -2147483648)
    ORDER BY r.run_id_sha256, r.context_sha256, r.space_id,
             r.lane, r.operation, r.outbox_id
    LIMIT $11 + CASE WHEN $9::integer IS NULL THEN 0 ELSE 1 END
),
candidates AS MATERIALIZED (
    SELECT r.outbox_id, i.canonical_source_id,
           i.identity_sha256, i.identity_commitment_sha256,
           jsonb_build_object(
             'id',o.id,'message_key',o.message_key,'event_type',o.event_type,
             'aggregate_type',o.aggregate_type,'aggregate_id',o.aggregate_id,
             'aggregate_version',o.aggregate_version,'created_at',o.created_at,
             'status',o.status
           ) AS outbox_json,
           to_jsonb(r) AS receipt_json,
           to_jsonb(l) AS link_json,
           to_jsonb(i) AS identity_json
    FROM receipt_page AS r
    JOIN LATERAL (
        SELECT l.* FROM memory_projection_receipt_identity_links AS l
        WHERE l.run_id_sha256 = r.run_id_sha256 AND l.outbox_id = r.outbox_id
          AND l.kind = $6
          AND (($9::integer IS NULL)
               OR (r.outbox_id, l.identity_sha256)
                  > ($9::integer, $10::char(64)))
        ORDER BY l.identity_sha256
        OFFSET 0
    ) AS l ON TRUE
    JOIN LATERAL (
        SELECT i.* FROM memory_projection_target_identities AS i
        WHERE i.run_id_sha256 = l.run_id_sha256 AND i.kind = l.kind
          AND i.identity_sha256 = l.identity_sha256
          AND i.identity_commitment_sha256 = l.identity_commitment_sha256
        LIMIT 1
    ) AS i ON TRUE
    JOIN LATERAL (
        SELECT o.* FROM memory_outbox AS o
        WHERE o.id = l.outbox_id AND o.event_type = ANY($7::text[])
          AND o.aggregate_type = $8 AND o.status = 'done'
        LIMIT 1
    ) AS o ON TRUE
    ORDER BY r.outbox_id, l.identity_sha256
    LIMIT $11
)
SELECT jsonb_build_object(
           'physical_outbox_id', candidate.outbox_id,
           'logical_target_identity_sha256', candidate.identity_sha256
       ) AS locator_json,
       jsonb_build_object(
           'outbox', candidate.outbox_json,
           'receipt', candidate.receipt_json,
           'link', candidate.link_json,
           'identity', candidate.identity_json,
           'canonical_source', canonical.canonical_source
       ) AS row_json,
       candidate.outbox_id AS cursor_1,
       candidate.identity_sha256 AS cursor_2
FROM candidates AS candidate
JOIN LATERAL (
    SELECT {canonical_row_json} AS canonical_source
    FROM {canonical_table} AS c
    {canonical_authority_joins}
    WHERE c.id = candidate.canonical_source_id AND c.space_id = $3
    LIMIT 1
) AS canonical ON TRUE
ORDER BY candidate.outbox_id, candidate.identity_sha256
"""

CLEANUP_RECEIPTS_SQL: Final = """
WITH receipt_page AS MATERIALIZED (
    SELECT r.*
    FROM memory_projection_result_receipts AS r
    WHERE r.run_id_sha256 = $1
      AND r.context_sha256 = $2 AND r.space_id = $3
      AND r.operation = 'delete'
      AND r.outbox_id >= COALESCE($4::integer, -2147483648)
    ORDER BY r.run_id_sha256, r.context_sha256, r.space_id, r.outbox_id
    LIMIT $6 + CASE WHEN $4::integer IS NULL THEN 0 ELSE 1 END
),
candidates AS MATERIALIZED (
    SELECT r.outbox_id, r.lane, i.canonical_source_id,
           i.identity_sha256, i.identity_commitment_sha256,
           jsonb_build_object(
             'id',o.id,'message_key',o.message_key,'event_type',o.event_type,
             'aggregate_type',o.aggregate_type,'aggregate_id',o.aggregate_id,
             'aggregate_version',o.aggregate_version,'created_at',o.created_at,
             'status',o.status
           ) AS outbox_json,
           to_jsonb(r) AS receipt_json,
           to_jsonb(l) AS link_json,
           to_jsonb(i) AS identity_json
    FROM receipt_page AS r
    JOIN LATERAL (
        SELECT l.* FROM memory_projection_receipt_identity_links AS l
        WHERE l.run_id_sha256 = r.run_id_sha256
          AND l.outbox_id = r.outbox_id
          AND (($4::integer IS NULL)
               OR (r.outbox_id, l.identity_sha256)
                  > ($4::integer, $5::char(64)))
        ORDER BY l.identity_sha256
        OFFSET 0
    ) AS l ON TRUE
    JOIN LATERAL (
        SELECT i.* FROM memory_projection_target_identities AS i
        WHERE i.run_id_sha256 = l.run_id_sha256 AND i.kind = l.kind
          AND i.identity_sha256 = l.identity_sha256
          AND i.identity_commitment_sha256 = l.identity_commitment_sha256
        LIMIT 1
    ) AS i ON TRUE
    JOIN LATERAL (
        SELECT o.* FROM memory_outbox AS o
        WHERE o.id = l.outbox_id AND o.status = 'done'
          AND ((r.lane = 'qdrant' AND i.kind = 'qdrant_point_id'
                AND o.event_type = 'vector.delete_chunks'
                AND o.aggregate_type = 'benchmark_run')
            OR (r.lane = 'graphiti' AND i.kind = 'graphiti_episode_uuid'
                AND o.event_type = 'graph.delete_fact'
                AND o.aggregate_type = 'benchmark_run'))
        LIMIT 1
    ) AS o ON TRUE
    ORDER BY r.outbox_id, l.identity_sha256
    LIMIT $6
)
SELECT jsonb_build_object(
           'physical_outbox_id', candidate.outbox_id,
           'logical_target_identity_sha256', candidate.identity_sha256
       ) AS locator_json,
       jsonb_build_object(
           'outbox', candidate.outbox_json,
           'receipt', candidate.receipt_json,
           'link', candidate.link_json,
           'identity', candidate.identity_json,
           'canonical_source', COALESCE(
               chunk_canonical.canonical_source,
               fact_canonical.canonical_source
           )
       ) AS row_json,
       candidate.outbox_id AS cursor_1,
       candidate.identity_sha256 AS cursor_2
FROM candidates AS candidate
LEFT JOIN LATERAL (
    SELECT {chunk_row_json} AS canonical_source
    FROM memory_chunks AS c
    JOIN memory_documents AS cd
      ON cd.id = c.document_id AND cd.space_id = c.space_id
     AND cd.memory_scope_id = c.memory_scope_id AND cd.thread_id = c.thread_id
    JOIN memory_scopes AS cs
      ON cs.id = c.memory_scope_id AND cs.space_id = c.space_id
    JOIN memory_threads AS ct
      ON ct.id = c.thread_id AND ct.memory_scope_id = c.memory_scope_id
     AND ct.space_id = c.space_id
    WHERE candidate.lane = 'qdrant'
      AND c.id = candidate.canonical_source_id AND c.space_id = $3
    LIMIT 1
) AS chunk_canonical ON TRUE
LEFT JOIN LATERAL (
    SELECT {fact_row_json} AS canonical_source
    FROM memory_facts AS f
    JOIN memory_scopes AS cs
      ON cs.id = f.memory_scope_id AND cs.space_id = f.space_id
    JOIN memory_threads AS ct
      ON ct.id = f.thread_id AND ct.memory_scope_id = f.memory_scope_id
     AND ct.space_id = f.space_id
    JOIN memory_fact_versions AS fv
      ON fv.fact_id = f.id AND fv.version = f.version
    JOIN LATERAL (
        SELECT jsonb_agg(to_jsonb(sr) ORDER BY sr.id) AS ordered_source_refs,
               count(*) AS source_ref_count
        FROM (
            SELECT bounded.* FROM memory_source_refs AS bounded
            WHERE bounded.fact_id = f.id AND bounded.fact_version = f.version
            ORDER BY bounded.id LIMIT 2
        ) AS sr
    ) AS cr ON cr.source_ref_count = 1
    WHERE candidate.lane = 'graphiti'
      AND f.id = candidate.canonical_source_id AND f.space_id = $3
    LIMIT 1
) AS fact_canonical ON TRUE
WHERE chunk_canonical.canonical_source IS NOT NULL
   OR fact_canonical.canonical_source IS NOT NULL
ORDER BY candidate.outbox_id, candidate.identity_sha256
"""

UNSUPPORTED_SQL: Final = """
WITH unsupported AS (
    SELECT 'memory_episodes'::text AS source_table,
           e.id::text AS source_pk,
           to_jsonb(e) AS row_json
    FROM memory_episodes AS e
    WHERE e.space_id = $1
    UNION ALL
    SELECT 'memory_outbox'::text AS source_table,
           o.id::text AS source_pk,
           to_jsonb(o) AS row_json
    FROM memory_outbox AS o
    WHERE (o.payload_json ->> 'space_id' = $1
        OR o.payload_json ->> 'cleanup_run_id_sha256' = $2)
      AND o.event_type NOT IN (
          'vector.upsert_chunk', 'vector.upsert_chunks', 'vector.delete_chunks',
          'graph.upsert_fact', 'graph.delete_fact'
      )
)
SELECT jsonb_build_object(
           'source_table', source_table, 'source_pk', source_pk
       ) AS locator_json,
       row_json,
       source_table AS cursor_1,
       source_pk AS cursor_2
FROM unsupported
WHERE (($3::text IS NULL) OR (source_table, source_pk) > ($3, $4))
ORDER BY source_table, source_pk
LIMIT $5
"""


__all__ = (
    "CANONICAL_EVIDENCE",
    "CLEANUP_RECEIPTS_SQL",
    "IDENTITY_KIND",
    "IDENTITY_SQL",
    "JOB_KIND",
    "JOB_SQL",
    "SIMPLE_QUERIES",
    "UNSUPPORTED_SQL",
    "canonical_evidence",
    "cleanup_receipts_sql",
)
