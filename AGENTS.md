# AGENTS.md

## Project Intent

This repository is the reusable Infinity Context extracted from client application planning docs.

Implement according to:

- Clean Architecture;
- SOLID;
- simple DDD;
- port/adapter boundaries;
- Postgres canonical lifecycle;
- Qdrant and Graphiti as derived indexes;
- provider dependencies isolated in adapters;
- prompt memory rendered as evidence, not instruction.

## Source Of Truth

Start with:

```text
docs/infinity-context-core-lite-plan.md
```

Global reference:

```text
docs/infinity-context-architecture-plan.md
```

Client compatibility notes:

```text
docs/client-integration/interview-infinity-context-clean-architecture-plan.md
```

## Implementation Rule

Do not let `infinity_context_core` import FastAPI, SQLAlchemy, Qdrant, Graphiti, OpenAI or client application code.

Keep files small enough to review and maintain:

- strict hard cap: no more than 1000 lines per file;
- when a file approaches the cap, split by domain policy, application use case,
  DTO/contract, adapter, test fixture or orchestration responsibility instead of adding
  unrelated behavior to the same module.

Implementation order:

```text
domain/ports -> application use cases -> Postgres canonical lifecycle -> compatibility API -> Qdrant RAG -> context eval -> Graphiti adapter -> SDK/Docker
```
