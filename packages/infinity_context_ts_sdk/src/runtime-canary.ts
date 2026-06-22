import type { ContextDiagnostics } from "./context-types.js";
import type { ContextRetrievalComponent } from "./diagnostics.js";
import type { InfinityContextClient } from "./infinity-context-client.js";
import type { ReadScope, ReadScopeInput } from "./payload.js";
import type { MemoryRuntimeAdapter, RuntimeReadinessReport } from "./runtime.js";
import type { CheckFullMemoryReadinessResult } from "./workflows/memory.js";

export interface RuntimeCanaryOptions extends ReadScopeInput {
  readonly client: InfinityContextClient;
  readonly readScope?: ReadScope;
  readonly query?: string;
  readonly includeContextProbe?: boolean;
  readonly includeSearchProbe?: boolean;
  readonly tokenBudget?: number;
  readonly maxFacts?: number;
  readonly maxChunks?: number;
  readonly maxEvidenceItems?: number;
  readonly consistencyMode?: string;
  readonly includeStale?: boolean;
  readonly requiredAdapters?: readonly MemoryRuntimeAdapter[];
  readonly requiredRetrieval?: readonly ContextRetrievalComponent[];
  readonly requireDerivedRetrieval?: boolean;
}

export interface RuntimeCanaryReport {
  readonly ok: boolean;
  readonly mode: RuntimeReadinessReport["mode"];
  readonly query: string | null;
  readonly readiness: RuntimeReadinessReport;
  readonly probes: {
    readonly context: boolean;
    readonly search: boolean;
    readonly diagnosticsSource: CheckFullMemoryReadinessResult["diagnostics"]["diagnosticsSource"];
  };
  readonly capabilities: {
    readonly enabledAdapters: readonly string[];
    readonly supportsQdrant: boolean;
    readonly supportsGraphiti: boolean;
  };
  readonly diagnostics?: {
    readonly context?: ContextDiagnostics;
    readonly search?: ContextDiagnostics;
  };
  readonly warnings: readonly string[];
  readonly errors: readonly string[];
}

const DEFAULT_RUNTIME_CANARY_QUERY = "Infinity Context full memory runtime readiness probe";

export async function runRuntimeCanary(options: RuntimeCanaryOptions): Promise<RuntimeCanaryReport> {
  const includeContextProbe = options.includeContextProbe ?? true;
  const includeSearchProbe = options.includeSearchProbe ?? false;
  const query = includeContextProbe || includeSearchProbe
    ? options.query ?? DEFAULT_RUNTIME_CANARY_QUERY
    : options.query;

  const readiness = await options.client.workflows.checkFullMemoryReadiness({
    ...scopeInput(options),
    ...(options.readScope !== undefined ? { readScope: options.readScope } : {}),
    ...(query !== undefined ? { query } : {}),
    includeContextProbe,
    includeSearchProbe,
    ...(options.tokenBudget !== undefined ? { tokenBudget: options.tokenBudget } : {}),
    ...(options.maxFacts !== undefined ? { maxFacts: options.maxFacts } : {}),
    ...(options.maxChunks !== undefined ? { maxChunks: options.maxChunks } : {}),
    ...(options.maxEvidenceItems !== undefined ? { maxEvidenceItems: options.maxEvidenceItems } : {}),
    ...(options.consistencyMode !== undefined ? { consistencyMode: options.consistencyMode } : {}),
    ...(options.includeStale !== undefined ? { includeStale: options.includeStale } : {}),
    ...(options.requiredAdapters !== undefined ? { requiredAdapters: options.requiredAdapters } : {}),
    ...(options.requiredRetrieval !== undefined ? { requiredRetrieval: options.requiredRetrieval } : {}),
    requireDerivedRetrieval: options.requireDerivedRetrieval ?? (includeContextProbe || includeSearchProbe),
  });

  return {
    ok: readiness.readiness.ok,
    mode: readiness.readiness.mode,
    query: query ?? null,
    readiness: readiness.readiness,
    probes: {
      context: readiness.diagnostics.contextProbe,
      search: readiness.diagnostics.searchProbe,
      diagnosticsSource: readiness.diagnostics.diagnosticsSource,
    },
    capabilities: {
      enabledAdapters: readiness.capabilities.enabled_adapters ?? [],
      supportsQdrant: readiness.capabilities.supports_qdrant === true,
      supportsGraphiti: readiness.capabilities.supports_graphiti === true,
    },
    diagnostics: {
      ...(readiness.context !== undefined ? { context: readiness.context.data.diagnostics } : {}),
      ...(readiness.search !== undefined ? { search: readiness.search.data.diagnostics } : {}),
    },
    warnings: readiness.readiness.warnings,
    errors: readiness.readiness.errors,
  };
}

function scopeInput(input: ReadScopeInput): ReadScopeInput {
  return {
    ...(input.spaceId !== undefined ? { spaceId: input.spaceId } : {}),
    ...(input.memoryScopeIds !== undefined ? { memoryScopeIds: input.memoryScopeIds } : {}),
    ...(input.threadId !== undefined ? { threadId: input.threadId } : {}),
    ...(input.spaceSlug !== undefined ? { spaceSlug: input.spaceSlug } : {}),
    ...(input.memoryScopeExternalRef !== undefined ? { memoryScopeExternalRef: input.memoryScopeExternalRef } : {}),
    ...(input.memoryScopeExternalRefs !== undefined ? { memoryScopeExternalRefs: input.memoryScopeExternalRefs } : {}),
    ...(input.threadExternalRef !== undefined ? { threadExternalRef: input.threadExternalRef } : {}),
  };
}
