# ADR-0001 - Memo Stack Core Lite Boundaries

## Context

Memo Stack starts as Core Lite: a reusable Python service/library that Client App can consume without importing storage or provider SDKs.

## Decision

Keep `memo_stack_core` free of FastAPI, SQLAlchemy, Qdrant, Graphiti, OpenAI and Client App imports.

Dependency direction:

```text
memo_stack_core.domain -> stdlib only
memo_stack_core.application -> domain + ports
memo_stack_core.ports -> protocols and DTO contracts
memo_stack_adapters -> memo_stack_core ports + provider SDKs later
memo_stack_server -> FastAPI, config and composition root
memo_stack_sdk -> HTTP client only later
```

## Consequences

- Provider changes are adapter changes, not use case rewrites.
- Tests can enforce import boundaries from PR 0.
- Early server behavior is intentionally small: health and capabilities only.
