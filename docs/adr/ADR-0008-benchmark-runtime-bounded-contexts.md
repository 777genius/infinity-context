# ADR-0008: Benchmark and external-runtime bounded contexts

Status: accepted

## Context

The publishable benchmark evolved inside `infinity_context_server`, while managed
benchmark lifecycle contracts also accumulated in `infinity_context_core`. Product
serving, benchmark orchestration, Mem0 lifecycle and external subscription-runtime
attestation have different reasons to change. Keeping them in one deployable package
increases installation weight and makes unrelated changes share a release surface.

## Decision

The architecture has four explicit directions:

1. `infinity_context_core` owns provider-neutral product use cases and ports only.
2. `infinity_context_server` owns HTTP/product serving composition only.
3. Publishable comparison orchestration and Mem0 lifecycle move toward a dedicated
   benchmark package, depending on public product contracts rather than internals.
4. External subscription-runtime attestation is an independent adapter package.

This change performs the first reversible slice: the provider-free runtime bridge is
moved to `infinity_context_runtime_bridge`. It has no imports from core, adapters or
server. Existing scheduler composition imports the new outward adapter explicitly.

The remaining benchmark debt in core and server is frozen by file-count and line-count
ceilings. Those ceilings may only decrease. New benchmark behavior must be placed in
the benchmark bounded context instead of increasing either product package.

## Consequences

- Product feature capsules no longer classify the runtime bridge as a server feature.
- Runtime transport, encrypted output, process control and attestation can evolve
  without changing product-serving modules.
- The current publishable scheduler remains compatible while its later extraction is
  performed in independently testable slices.
- The freeze is intentionally aggregate: existing large files remain visible debt,
  while the repository-wide 1000-line gate continues to prevent new oversized files.

## Migration order

1. External runtime bridge - completed by this ADR.
2. Publishable scheduler/canary orchestration - move without behavior changes.
3. Mem0-specific lifecycle adapters - move behind benchmark-owned ports.
4. Provider-neutral benchmark contracts currently in core - move only after callers
   depend on a stable public benchmark contract package.

Each slice must preserve provider-free contract tests and must not use paid/live LLM
calls as a structural verification step.
