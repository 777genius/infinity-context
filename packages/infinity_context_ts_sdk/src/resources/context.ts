import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import type {
  ContextBundleData,
  ContextEnvelope,
  MemoryDigestData,
  SearchMemoryData,
} from "../context-types.js";
import {
  ReadScope,
  ValueError,
  readScopePayload,
  validateReadScopePayload,
  withoutUndefined,
  type ReadScopeInput,
} from "../payload.js";
import type { ApiEnvelope, JsonObject } from "../types.js";
import {
  decodeContextRetrievalCapabilityV2,
  decodeRetrieveContextV2ResponseBytes,
  retrievalV2RequestPayload,
  validateContextRetrievalPreflightV2,
} from "../retrieval-v2.js";
import type {
  ContextRetrievalCapabilityV2,
  RequiredContextRetrievalCapabilityV2,
  RetrieveContextV2Input,
  RetrieveContextV2Response,
} from "../retrieval-v2-types.js";
import { verifyContextRetrievalCapabilityV2Fingerprint } from "../retrieval-v2-canonical.js";
import { contextRetrievalV2ErrorDecoder } from "../retrieval-v2-errors.js";
import { InfinityContextError } from "../errors.js";
import { requireAllowedKeys, requireArray, requireEnum, requireInteger, requireString } from "../canonical-validation.js";

export interface ContextScopeInput extends ReadScopeInput, RequestControls {
  readonly readScope?: ReadScope;
}

export interface BuildContextInput extends ContextScopeInput {
  readonly repositoryId?: string;
  readonly codeScopeId?: string;
  readonly asOf?: string;
  readonly query: string;
  readonly tokenBudget?: number;
  readonly maxFacts?: number;
  readonly maxChunks?: number;
  readonly maxEvidenceItems?: number;
  readonly consistencyMode?: string;
  readonly maxConflictingSuggestions?: number;
  readonly includeSuperseded?: boolean;
  readonly includeStale?: boolean;
  readonly category?: string;
  readonly tagsAny?: readonly string[];
  readonly tagsAll?: readonly string[];
  readonly tagsNone?: readonly string[];
  readonly projectAnchorPolicy?: "required" | "advisory";
}

export interface BenchmarkSearchInput extends BuildContextInput {}

export interface BuildDigestInput extends ContextScopeInput {
  readonly topic: string;
  readonly tokenBudget?: number;
  readonly maxFacts?: number;
  readonly maxChunks?: number;
  readonly maxSuggestions?: number;
  readonly includePendingSuggestions?: boolean;
  readonly includeSuperseded?: boolean;
  readonly includeRelated?: boolean;
  readonly format?: string;
}

export interface BuildInsightsInput extends ContextScopeInput {
  readonly maxFacts?: number;
  readonly maxDocuments?: number;
  readonly maxEpisodes?: number;
  readonly maxSuggestions?: number;
  readonly maxCaptures?: number;
  readonly maxActivity?: number;
}

export class ContextClient {
  constructor(private readonly http: RequestExecutor) {}

  async retrieve(
    input: RetrieveContextV2Input,
    capability: ContextRetrievalCapabilityV2,
    required: RequiredContextRetrievalCapabilityV2,
    controls: RequestControls = {},
  ): Promise<RetrieveContextV2Response> {
    const attestedCapability = decodeContextRetrievalCapabilityV2(capability);
    validateContextRetrievalPreflightV2(input, attestedCapability, required);
    const payload = retrievalV2RequestPayload(input);
    await verifyContextRetrievalCapabilityV2Fingerprint(attestedCapability);
    const transportTimeoutMs = Math.min(
      controls.timeoutMs ?? input.bounds.deadlineMs,
      input.bounds.deadlineMs,
    );
    const budget = retrievalCallBudget(controls.signal, transportTimeoutMs);
    try {
      const response = await this.http.request<Uint8Array | string>({
        method: "POST",
        path: "/v1/context/retrieve",
        ...requestControls({ ...controls, signal: budget.signal, timeoutMs: transportTimeoutMs }),
        json: payload,
        responseType: "bytes",
        maxResponseBytes: input.bounds.responseByteLimit,
        maxErrorResponseBytes: input.bounds.responseByteLimit,
        errorDecoder: contextRetrievalV2ErrorDecoder(input.bounds.responseByteLimit),
      });
      return decodeRetrieveContextV2ResponseBytes(response, payload, attestedCapability);
    } catch (error) {
      throw retrievalTransportError(error, budget.timedOut(), controls.signal?.aborted === true);
    } finally {
      budget.cleanup();
    }
  }

  buildContext(input: BuildContextInput): Promise<ContextEnvelope<ContextBundleData>> {
    return this.http.request<ContextEnvelope<ContextBundleData>>({
      method: "POST",
      path: "/v1/context",
      ...requestControls(input),
      json: contextPayload(input),
    });
  }

  search(input: BuildContextInput): Promise<ContextEnvelope<SearchMemoryData>> {
    return this.http.request<ContextEnvelope<SearchMemoryData>>({
      method: "POST",
      path: "/v1/search",
      ...requestControls(input),
      json: contextPayload(input),
    });
  }

  async benchmarkSearch(input: BenchmarkSearchInput): Promise<ContextEnvelope<SearchMemoryData>> {
    validateBenchmarkSearch(input);
    return this.http.request<ContextEnvelope<SearchMemoryData>>({
      method: "POST",
      path: "/v1/context/benchmark-search",
      ...requestControls(input),
      json: contextPayload(input, {
        tokenBudget: 16_000,
        maxFacts: 200,
        maxChunks: 400,
        maxEvidenceItems: 200,
      }),
    });
  }

  buildDigest(input: BuildDigestInput): Promise<ContextEnvelope<MemoryDigestData>> {
    return this.http.request<ContextEnvelope<MemoryDigestData>>({
      method: "POST",
      path: "/v1/digest",
      ...requestControls(input),
      json: withoutUndefined({
        ...scopePayload(input),
        topic: input.topic,
        token_budget: input.tokenBudget ?? 2400,
        max_facts: input.maxFacts ?? 20,
        max_chunks: input.maxChunks ?? 20,
        max_suggestions: input.maxSuggestions ?? 10,
        include_pending_suggestions: input.includePendingSuggestions ?? true,
        include_superseded: input.includeSuperseded ?? false,
        include_related: input.includeRelated ?? true,
        format: input.format ?? "markdown",
      }) as JsonObject,
    });
  }

  buildInsights(input: BuildInsightsInput): Promise<ApiEnvelope<JsonObject>> {
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "POST",
      path: "/v1/insights",
      ...requestControls(input),
      json: withoutUndefined({
        ...scopePayload(input),
        max_facts: input.maxFacts ?? 200,
        max_documents: input.maxDocuments ?? 100,
        max_episodes: input.maxEpisodes ?? 100,
        max_suggestions: input.maxSuggestions ?? 100,
        max_captures: input.maxCaptures ?? 100,
        max_activity: input.maxActivity ?? 50,
      }) as JsonObject,
    });
  }
}

function retrievalCallBudget(caller: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => controller.abort(caller?.reason);
  if (caller?.aborted) onCallerAbort();
  else caller?.addEventListener("abort", onCallerAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Retrieval V2 deadline exceeded", "TimeoutError"));
  }, timeoutMs);
  timer.unref?.();
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      clearTimeout(timer);
      caller?.removeEventListener("abort", onCallerAbort);
    },
  };
}

function retrievalTransportError(
  error: unknown,
  timedOut: boolean,
  callerAborted: boolean,
): unknown {
  if (error instanceof InfinityContextError) {
    if (timedOut || error.code === "memory.request_timeout") {
      return retrievalClientError(
        "memory.context_retrieval_deadline_exceeded",
        "Retrieval V2 request exceeded its absolute deadline",
        true,
      );
    }
    if (callerAborted || error.code === "memory.request_aborted") {
      return retrievalClientError(
        "memory.context_retrieval_cancelled",
        "Retrieval V2 request was cancelled",
        false,
      );
    }
    if (error.code === "memory.network_error") {
      return retrievalClientError(
        "memory.context_retrieval_unavailable",
        "Retrieval V2 transport is unavailable",
        true,
      );
    }
    return error;
  }
  return retrievalClientError(
    callerAborted ? "memory.context_retrieval_cancelled" :
      timedOut ? "memory.context_retrieval_deadline_exceeded" :
        "memory.context_retrieval_unavailable",
    callerAborted ? "Retrieval V2 request was cancelled" :
      timedOut ? "Retrieval V2 request exceeded its absolute deadline" :
        "Retrieval V2 transport is unavailable",
    !callerAborted,
  );
}

function retrievalClientError(code: string, message: string, retryable: boolean) {
  return new InfinityContextError({ statusCode: 0, code, message, retryable });
}

function contextPayload(
  input: BuildContextInput,
  defaults: { readonly tokenBudget: number; readonly maxFacts: number; readonly maxChunks: number; readonly maxEvidenceItems?: number } = {
    tokenBudget: 1800, maxFacts: 20, maxChunks: 30,
  },
): JsonObject {
  return withoutUndefined({
    ...scopePayload(input),
    repository_id: input.repositoryId,
    code_scope_id: input.codeScopeId,
    as_of: input.asOf,
    query: input.query,
    token_budget: input.tokenBudget ?? defaults.tokenBudget,
    max_facts: input.maxFacts ?? defaults.maxFacts,
    max_chunks: input.maxChunks ?? defaults.maxChunks,
    max_evidence_items: input.maxEvidenceItems ?? defaults.maxEvidenceItems,
    consistency_mode: input.consistencyMode,
    max_conflicting_suggestions: input.maxConflictingSuggestions,
    include_superseded: input.includeSuperseded || undefined,
    include_stale: input.includeStale || undefined,
    category: input.category,
    tags_any: input.tagsAny,
    tags_all: input.tagsAll,
    tags_none: input.tagsNone,
    project_anchor_policy: input.projectAnchorPolicy,
  }) as JsonObject;
}

const BENCHMARK_KEYS = [
  "readScope", "spaceId", "memoryScopeIds", "threadId", "spaceSlug", "memoryScopeExternalRef",
  "memoryScopeExternalRefs", "threadExternalRef", "repositoryId", "codeScopeId", "asOf", "query",
  "tokenBudget", "maxFacts", "maxChunks", "maxEvidenceItems", "consistencyMode",
  "maxConflictingSuggestions", "includeSuperseded", "includeStale", "category", "tagsAny", "tagsAll",
  "tagsNone", "projectAnchorPolicy", "headers", "signal", "timeoutMs",
] as const;

function validateBenchmarkSearch(input: BenchmarkSearchInput): void {
  requireAllowedKeys(input, BENCHMARK_KEYS, "benchmarkSearch");
  requireString(input.query, "query", 1, 12_000);
  requireInteger(input.tokenBudget ?? 16_000, "tokenBudget", 64, 64_000);
  requireInteger(input.maxFacts ?? 200, "maxFacts", 0, 1_000);
  requireInteger(input.maxChunks ?? 400, "maxChunks", 0, 2_000);
  requireInteger(input.maxEvidenceItems ?? 200, "maxEvidenceItems", 0, 200);
  requireInteger(input.maxConflictingSuggestions ?? 5, "maxConflictingSuggestions", 0, 20);
  if (input.consistencyMode !== undefined) requireEnum(input.consistencyMode, ["canonical_only", "best_effort", "require_fresh_projection"], "consistencyMode");
  if (input.projectAnchorPolicy !== undefined) requireEnum(input.projectAnchorPolicy, ["required", "advisory"], "projectAnchorPolicy");
  if (input.repositoryId !== undefined) requireString(input.repositoryId, "repositoryId", 1, 80);
  if (input.codeScopeId !== undefined) requireString(input.codeScopeId, "codeScopeId", 1, 96);
  if (input.category !== undefined) requireString(input.category, "category", 0, 80);
  for (const [label, value] of [["includeSuperseded", input.includeSuperseded], ["includeStale", input.includeStale]] as const) {
    if (value !== undefined && typeof value !== "boolean") throw new ValueError(`${label} must be boolean`);
  }
  for (const [label, tags] of [["tagsAny", input.tagsAny], ["tagsAll", input.tagsAll], ["tagsNone", input.tagsNone]] as const) {
    if (tags !== undefined) {
      requireArray(tags, label, 0, 10);
      for (const tag of tags) requireString(tag, `${label} item`);
    }
  }
  validateReadScopePayload(scopePayload(input));
}

function scopePayload(input: ContextScopeInput): JsonObject {
  return input.readScope?.toPayload() ?? readScopePayload(input);
}
