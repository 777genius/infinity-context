# AGENTS.md

## Project Intent

This repository is the reusable Memo Stack extracted from client application planning docs.

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
docs/memo-stack-core-lite-plan.md
```

Global reference:

```text
docs/memo-stack-architecture-plan.md
```

Client compatibility notes:

```text
docs/client-integration/interview-memo-stack-clean-architecture-plan.md
```

## Implementation Rule

Do not let `memo_stack_core` import FastAPI, SQLAlchemy, Qdrant, Graphiti, OpenAI or client application code.

Implementation order:

```text
domain/ports -> application use cases -> Postgres canonical lifecycle -> compatibility API -> Qdrant RAG -> context eval -> Graphiti adapter -> SDK/Docker
```
