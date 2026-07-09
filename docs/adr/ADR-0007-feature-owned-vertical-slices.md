# ADR-0007: Feature-Owned Vertical Slices

Status: accepted

## Context

Infinity Context already has deployable package boundaries:

- `infinity_context_core`
- `infinity_context_contracts`
- `infinity_context_adapters`
- `infinity_context_server`
- `infinity_context_sdk`
- `infinity_context_mcp`

The refactor target is not a global `domain/application/ports` directory split. That is Clean
Architecture by layers, not Feature-Sliced Design. The target is feature ownership: every business
capability owns its domain rules, use cases, ports, errors, commands, results, and tests.

## Decision

Keep package boundaries for dependency isolation, but mirror the same feature ids across packages.

Target feature ids:

- `memory_facts`
- `context_building`
- `document_ingestion`
- `memory_scopes`

Core feature capsules use Clean Architecture internally:

```text
infinity_context_core/
  shared_kernel/
  features/
    memory_facts/
      public.py
      domain/
      application/
      ports/
      tests/
```

Infrastructure mirrors feature ids:

```text
infinity_context_adapters/
  features/
    memory_facts/
    context_building/
    document_ingestion/
    memory_scopes/
```

Server mirrors feature ids:

```text
infinity_context_server/
  features/
    memory_facts/
    context_building/
    document_ingestion/
    memory_scopes/
```

Contracts mirror feature ids:

```text
infinity_context_contracts/
  features/
    memory_facts.py
    context_building.py
    document_ingestion.py
    memory_scopes.py
```

## Rules

- `shared_kernel` contains technical primitives only. No business policy.
- A feature may expose `public.py`; other features must not import its internals.
- Core feature domain code may import only `shared_kernel` and standard-library modules.
- Core feature application code may import its own domain and own ports.
- Adapters implement feature ports and may import infrastructure dependencies.
- Server owns routes, mappers, and composition only.
- Cross-feature workflows belong in a process/orchestration layer and must use feature public APIs.
- Postgres remains canonical truth. Qdrant and Graphiti are derived projections.

## Consequences

This creates some duplication between features. That is acceptable when it preserves ownership and
keeps feature changes reviewable. Shared code is promoted only after two or more features need the
same technical primitive for the same reason.

Old layer-first modules remain compatibility shims while feature capsules are introduced one slice
at a time. They can be removed only after focused tests prove equivalent behavior.
