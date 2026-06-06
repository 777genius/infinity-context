# ADR-0003 - Canonical Fact Lifecycle

## Context

PR 1 adds the first canonical write path: remembered facts with source refs, version history, idempotency and outbox events.

## Decision

Fact lifecycle is implemented through `memo_stack_core` use cases and a Postgres adapter.

Rules:

- active facts require source refs;
- remember writes fact, version, source refs, idempotency and outbox in one transaction;
- update requires `expected_version` and increments fact version;
- forget is a tombstone-style lifecycle change and increments fact version;
- graph projection is not called directly from the API path;
- graph changes are represented as outbox events.

## Consequences

- repeated idempotency key with the same body returns the existing fact;
- repeated idempotency key with a different body returns conflict;
- stale update returns conflict;
- deleted facts remain in history but are marked deleted;
- Qdrant/Graphiti remain derived future adapters.
