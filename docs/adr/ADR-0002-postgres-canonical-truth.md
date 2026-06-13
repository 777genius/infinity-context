# ADR-0002 - Postgres Is Canonical Truth

## Context

Core Lite will later use Qdrant for document RAG and Graphiti for temporal graph recall. Both are powerful, but neither should decide memory lifecycle or visibility.

## Decision

Postgres owns canonical lifecycle for spaces, memory scopes, threads, documents, chunks, facts, source refs, tombstones, projection state, idempotency and outbox.

Qdrant and Graphiti are derived indexes.

## Consequences

- Delete/forget correctness is enforced by canonical hydration through Postgres.
- Adapter writes happen through outbox after canonical commit.
- Stale vector/graph hits are allowed only if hydration drops them before context rendering.
