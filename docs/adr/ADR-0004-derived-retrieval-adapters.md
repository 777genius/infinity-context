# ADR-0004 - Derived Retrieval Adapters

## Context

Core Lite needs document recall and graph recall, but Qdrant and Graphiti must not become hidden sources of truth.

## Decision

Postgres owns documents, chunks, facts, episodes and lifecycle state. Qdrant and Graphiti are optional derived adapters behind `VectorMemoryPort` and `GraphMemoryPort`.

Context/search hydrates every derived candidate through Postgres before rendering it.

## Consequences

- canonical writes succeed when Qdrant, embeddings or Graphiti are disabled;
- deleted/superseded canonical rows are filtered even if an adapter returns stale ids;
- adapters can be replaced without changing `memo_stack_core`;
- repair/reindex can rebuild derived indexes from Postgres.
