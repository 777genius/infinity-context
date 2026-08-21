"""Fail-closed anti-join stream for cleanup-v3 source exhaustiveness."""

from __future__ import annotations

from typing import Final

UNSUPPORTED_SQL: Final = """
WITH invalid AS (
    SELECT 'memory_scopes'::text AS source_table, s.id::text AS source_pk,
           to_jsonb(s) AS row_json
    FROM memory_scopes AS s
    WHERE s.space_id = $1
      AND NOT EXISTS (
          SELECT 1
          FROM memory_threads AS t
          WHERE t.space_id = s.space_id AND t.memory_scope_id = s.id
            AND (
                EXISTS (
                    SELECT 1 FROM memory_facts AS f
                    WHERE f.space_id = s.space_id AND f.memory_scope_id = s.id
                      AND f.thread_id = t.id
                )
                OR EXISTS (
                    SELECT 1 FROM memory_documents AS d
                    WHERE d.space_id = s.space_id AND d.memory_scope_id = s.id
                      AND d.thread_id = t.id
                )
            )
      )
    UNION ALL
    SELECT 'memory_threads', t.id::text, to_jsonb(t)
    FROM memory_threads AS t
    WHERE t.space_id = $1
      AND (
          NOT EXISTS (
              SELECT 1 FROM memory_scopes AS s
              WHERE s.id = t.memory_scope_id AND s.space_id = t.space_id
          )
          OR NOT (
              EXISTS (
                  SELECT 1 FROM memory_facts AS f
                  WHERE f.space_id = t.space_id
                    AND f.memory_scope_id = t.memory_scope_id AND f.thread_id = t.id
              )
              OR EXISTS (
                  SELECT 1 FROM memory_documents AS d
                  WHERE d.space_id = t.space_id
                    AND d.memory_scope_id = t.memory_scope_id AND d.thread_id = t.id
              )
          )
      )
    UNION ALL
    SELECT 'memory_facts', f.id::text, to_jsonb(f)
    FROM memory_facts AS f
    WHERE f.space_id = $1
      AND (
          NOT EXISTS (
              SELECT 1 FROM memory_scopes AS s
              JOIN memory_threads AS t
                ON t.id = f.thread_id AND t.space_id = f.space_id
               AND t.memory_scope_id = f.memory_scope_id
              WHERE s.id = f.memory_scope_id AND s.space_id = f.space_id
          )
          OR NOT EXISTS (
              SELECT 1 FROM memory_fact_versions AS fv
              WHERE fv.fact_id = f.id AND fv.version = f.version
          )
          OR 1 <> (
              SELECT count(*) FROM (
                  SELECT 1 FROM memory_source_refs AS sr
                  WHERE sr.fact_id = f.id AND sr.fact_version = f.version
                  LIMIT 2
              ) AS bounded_refs
          )
      )
    UNION ALL
    SELECT 'memory_source_refs',
           concat_ws(':', sr.id::text, sr.fact_id, sr.fact_version::text),
           to_jsonb(sr)
    FROM memory_source_refs AS sr
    JOIN memory_facts AS owning_fact
      ON owning_fact.id = sr.fact_id AND owning_fact.space_id = $1
    WHERE owning_fact.version <> sr.fact_version
       OR NOT EXISTS (
           SELECT 1 FROM memory_fact_versions AS fv
           WHERE fv.fact_id = sr.fact_id AND fv.version = sr.fact_version
       )
       OR 1 <> (
           SELECT count(*) FROM (
               SELECT 1 FROM memory_source_refs AS sibling
               WHERE sibling.fact_id = sr.fact_id
                 AND sibling.fact_version = sr.fact_version
               LIMIT 2
           ) AS bounded_refs
       )
    UNION ALL
    SELECT 'memory_documents', d.id::text, to_jsonb(d)
    FROM memory_documents AS d
    WHERE d.space_id = $1
      AND (
          NOT EXISTS (
              SELECT 1 FROM memory_scopes AS s
              JOIN memory_threads AS t
                ON t.id = d.thread_id AND t.space_id = d.space_id
               AND t.memory_scope_id = d.memory_scope_id
              WHERE s.id = d.memory_scope_id AND s.space_id = d.space_id
          )
          OR NOT EXISTS (
              SELECT 1 FROM memory_chunks AS c
              WHERE c.space_id = d.space_id AND c.memory_scope_id = d.memory_scope_id
                AND c.thread_id = d.thread_id AND c.document_id = d.id
          )
      )
    UNION ALL
    SELECT 'memory_chunks', c.id::text, to_jsonb(c)
    FROM memory_chunks AS c
    WHERE c.space_id = $1
      AND NOT EXISTS (
          SELECT 1
          FROM memory_documents AS d
          JOIN memory_scopes AS s
            ON s.id = c.memory_scope_id AND s.space_id = c.space_id
          JOIN memory_threads AS t
            ON t.id = c.thread_id AND t.space_id = c.space_id
           AND t.memory_scope_id = c.memory_scope_id
          WHERE d.id = c.document_id AND d.space_id = c.space_id
            AND d.memory_scope_id = c.memory_scope_id AND d.thread_id = c.thread_id
      )
    UNION ALL
    SELECT 'memory_episodes', e.id::text, to_jsonb(e)
    FROM memory_episodes AS e
    WHERE e.space_id = $1
    UNION ALL
    SELECT 'memory_outbox', o.id::text, to_jsonb(o)
    FROM memory_outbox AS o
    WHERE (
        o.payload_json ->> 'space_id' = $1
        OR o.payload_json ->> 'cleanup_run_id_sha256' = $2
        OR (o.aggregate_type = 'benchmark_run' AND o.aggregate_id = $2)
        OR EXISTS (
            SELECT 1 FROM memory_projection_result_receipts AS r
            WHERE r.outbox_id = o.id AND r.run_id_sha256 = $2
              AND r.context_sha256 = $3
        )
        OR EXISTS (
            SELECT 1 FROM memory_chunks AS c
            WHERE c.id = o.aggregate_id AND c.space_id = $1
        )
        OR EXISTS (
            SELECT 1 FROM memory_facts AS f
            WHERE f.id = o.aggregate_id AND f.space_id = $1
        )
    )
      AND (
          o.event_type NOT IN (
              'vector.upsert_chunk', 'vector.upsert_chunks', 'vector.delete_chunks',
              'graph.upsert_fact', 'graph.delete_fact'
          )
          OR NOT EXISTS (
              SELECT 1
              FROM memory_projection_result_receipts AS r
              JOIN memory_projection_receipt_identity_links AS l
                ON l.outbox_id = r.outbox_id AND l.run_id_sha256 = r.run_id_sha256
              JOIN memory_projection_target_identities AS i
                ON i.run_id_sha256 = l.run_id_sha256 AND i.kind = l.kind
               AND i.identity_sha256 = l.identity_sha256
               AND i.identity_commitment_sha256 = l.identity_commitment_sha256
              WHERE r.outbox_id = o.id AND r.run_id_sha256 = $2
                AND r.context_sha256 = $3 AND r.space_id = $1 AND o.status = 'done'
                AND (
                    (r.lane = 'qdrant' AND EXISTS (
                        SELECT 1 FROM memory_chunks AS c
                        WHERE c.id = i.canonical_source_id AND c.space_id = $1
                    ))
                    OR (r.lane = 'graphiti' AND EXISTS (
                        SELECT 1 FROM memory_facts AS f
                        WHERE f.id = i.canonical_source_id AND f.space_id = $1
                    ))
                )
          )
      )
    UNION ALL
    SELECT 'memory_projection_result_receipts',
           concat_ws(':', r.outbox_id::text, r.run_id_sha256), to_jsonb(r)
    FROM memory_projection_result_receipts AS r
    WHERE r.run_id_sha256 = $2 AND r.space_id = $1
      AND (r.context_sha256 <> $3 OR NOT EXISTS (
          SELECT 1 FROM memory_outbox AS o
          JOIN memory_projection_receipt_identity_links AS l
            ON l.outbox_id = r.outbox_id AND l.run_id_sha256 = r.run_id_sha256
          JOIN memory_projection_target_identities AS i
            ON i.run_id_sha256 = l.run_id_sha256 AND i.kind = l.kind
           AND i.identity_sha256 = l.identity_sha256
           AND i.identity_commitment_sha256 = l.identity_commitment_sha256
          WHERE o.id = r.outbox_id AND o.status = 'done'
            AND r.context_sha256 = $3
      ))
    UNION ALL
    SELECT 'memory_projection_target_identities',
           concat_ws(':', i.run_id_sha256, i.kind, i.identity_sha256), to_jsonb(i)
    FROM memory_projection_target_identities AS i
    WHERE i.run_id_sha256 = $2
      AND NOT EXISTS (
          SELECT 1 FROM memory_projection_receipt_identity_links AS l
          JOIN memory_projection_result_receipts AS r
            ON r.outbox_id = l.outbox_id AND r.run_id_sha256 = l.run_id_sha256
          WHERE l.run_id_sha256 = i.run_id_sha256 AND l.kind = i.kind
            AND l.identity_sha256 = i.identity_sha256
            AND l.identity_commitment_sha256 = i.identity_commitment_sha256
            AND r.space_id = $1 AND r.context_sha256 = $3
      )
    UNION ALL
    SELECT 'memory_projection_receipt_identity_links',
           concat_ws(':', l.outbox_id::text, l.run_id_sha256, l.kind,
                     l.identity_sha256, l.ordinal::text), to_jsonb(l)
    FROM memory_projection_receipt_identity_links AS l
    WHERE l.run_id_sha256 = $2
      AND NOT EXISTS (
          SELECT 1 FROM memory_projection_result_receipts AS r
          JOIN memory_projection_target_identities AS i
            ON i.run_id_sha256 = l.run_id_sha256 AND i.kind = l.kind
           AND i.identity_sha256 = l.identity_sha256
           AND i.identity_commitment_sha256 = l.identity_commitment_sha256
          WHERE r.outbox_id = l.outbox_id AND r.run_id_sha256 = l.run_id_sha256
            AND r.space_id = $1 AND r.context_sha256 = $3
      )
)
SELECT jsonb_build_object(
           'source_table', source_table, 'source_pk', source_pk
       ) AS locator_json,
       row_json || jsonb_build_object('__unsupported_pk', source_pk) AS row_json,
       source_table AS cursor_1,
       source_pk AS cursor_2
FROM invalid
WHERE (($4::text IS NULL) OR (source_table, source_pk) > ($4, $5))
ORDER BY source_table, source_pk
LIMIT $6
"""


__all__ = ("UNSUPPORTED_SQL",)
