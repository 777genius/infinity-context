import type { ContextDiagnostics } from "./context-types.js";
import {
  healthyRetrievalComponents,
  retrievalDiagnostics,
  usedDerivedRetrieval,
  type ContextRetrievalComponent,
} from "./diagnostics.js";
import { InfinityContextError } from "./errors.js";
import type { InfinityContextCapabilities, JsonObject } from "./types.js";

export type MemoryRuntimeMode = "full" | "lite";
export type MemoryRuntimeAdapter = "qdrant" | "graphiti" | "openai" | (string & {});

export interface RuntimeReadinessInput {
  readonly capabilities: InfinityContextCapabilities;
  readonly diagnostics?: ContextDiagnostics;
  readonly requiredAdapters?: readonly MemoryRuntimeAdapter[];
  readonly requiredRetrieval?: readonly ContextRetrievalComponent[];
  readonly requireDerivedRetrieval?: boolean;
}

export interface RuntimeReadinessReport {
  readonly ok: boolean;
  readonly mode: MemoryRuntimeMode;
  readonly enabledAdapters: readonly string[];
  readonly requiredAdapters: readonly string[];
  readonly missingAdapters: readonly string[];
  readonly requiredRetrieval: readonly ContextRetrievalComponent[];
  readonly unhealthyRetrieval: readonly ContextRetrievalComponent[];
  readonly derivedRetrievalUsed: boolean | null;
  readonly supportsQdrant: boolean;
  readonly supportsGraphiti: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
}

const DEFAULT_FULL_MEMORY_ADAPTERS = ["qdrant", "graphiti"] as const;
const DEFAULT_FULL_MEMORY_RETRIEVAL = ["vector", "graph"] as const;

export function evaluateRuntimeReadiness(input: RuntimeReadinessInput): RuntimeReadinessReport {
  const requiredAdapters = input.requiredAdapters ?? DEFAULT_FULL_MEMORY_ADAPTERS;
  const requiredRetrieval = input.requiredRetrieval ?? DEFAULT_FULL_MEMORY_RETRIEVAL;
  const enabledAdapters = input.capabilities.enabled_adapters ?? [];
  const enabled = new Set(enabledAdapters);
  const missingAdapters = requiredAdapters.filter((adapter) => !enabled.has(adapter));
  const diagnostics = input.diagnostics;
  const unhealthyRetrieval = diagnostics
    ? requiredRetrieval.filter((component) => !healthyRetrievalComponents(diagnostics, [component]))
    : [];
  const derivedRetrievalUsed = diagnostics ? usedDerivedRetrieval(diagnostics) : null;
  const retrievalErrors = diagnostics
    ? unhealthyRetrieval.map((component) => {
        const componentDiagnostics = retrievalDiagnostics(diagnostics, component);
        return `Unhealthy ${component} retrieval: ${componentDiagnostics.status ?? "missing"}`;
      })
    : [];
  const errors = [
    ...missingAdapters.map((adapter) => `Missing runtime adapter: ${adapter}`),
    ...retrievalErrors,
    ...(input.requireDerivedRetrieval && derivedRetrievalUsed === false
      ? ["Derived retrieval was not used"]
      : []),
  ];
  const warnings = [
    ...supportWarnings(input.capabilities, enabledAdapters),
    ...(diagnostics ? [] : ["Context diagnostics were not provided"]),
  ];

  return {
    ok: errors.length === 0,
    mode: missingAdapters.length === 0 ? "full" : "lite",
    enabledAdapters,
    requiredAdapters,
    missingAdapters,
    requiredRetrieval,
    unhealthyRetrieval,
    derivedRetrievalUsed,
    supportsQdrant: input.capabilities.supports_qdrant === true,
    supportsGraphiti: input.capabilities.supports_graphiti === true,
    errors,
    warnings,
  };
}

export function assertRuntimeReadiness(input: RuntimeReadinessInput): RuntimeReadinessReport {
  const report = evaluateRuntimeReadiness(input);
  if (!report.ok) {
    throw runtimeReadinessError(report);
  }
  return report;
}

export function assertFullMemoryReady(
  capabilities: InfinityContextCapabilities,
  diagnostics?: ContextDiagnostics,
): RuntimeReadinessReport {
  return assertRuntimeReadiness({
    capabilities,
    ...(diagnostics !== undefined ? { diagnostics } : {}),
    requiredAdapters: DEFAULT_FULL_MEMORY_ADAPTERS,
    requiredRetrieval: DEFAULT_FULL_MEMORY_RETRIEVAL,
    requireDerivedRetrieval: diagnostics !== undefined,
  });
}

function supportWarnings(
  capabilities: InfinityContextCapabilities,
  enabledAdapters: readonly string[],
): readonly string[] {
  const enabled = new Set(enabledAdapters);
  const warnings: string[] = [];
  if (capabilities.supports_qdrant === true && !enabled.has("qdrant")) {
    warnings.push("Qdrant is supported by this service but not enabled in the current runtime");
  }
  if (capabilities.supports_graphiti === true && !enabled.has("graphiti")) {
    warnings.push("Graphiti is supported by this service but not enabled in the current runtime");
  }
  return warnings;
}

function runtimeReadinessError(report: RuntimeReadinessReport): InfinityContextError {
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.runtime_not_ready",
    message: `Infinity Context runtime is not ready: ${report.errors.join("; ")}`,
    retryable: false,
    details: report as unknown as JsonObject,
  });
}
