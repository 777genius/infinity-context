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
  decodeRetrievalCapability,
  decodeRetrieveContextResponseBytes,
  retrievalRequestPayload,
  validateRetrievalPreflight,
} from "../retrieval.js";
import type {
  RetrievalCapability,
  RequiredRetrievalCapability,
  RetrieveContextInput,
  RetrieveContextResponse,
} from "../retrieval-types.js";
import { verifyRetrievalCapabilityFingerprint } from "../retrieval-canonical.js";
import { retrievalErrorDecoder } from "../retrieval-errors.js";
import { copyInfinityContextError, createInfinityContextError, type InfinityContextError } from "../errors.js";
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
    input: RetrieveContextInput,
    capability: RetrievalCapability,
    required: RequiredRetrievalCapability,
    controls: RequestControls = {},
  ): Promise<RetrieveContextResponse> {
    const startedAtMs = monotonicNowMs();
    let budget: ReturnType<typeof retrievalCallBudget> | undefined;
    try {
      if (controls.signal?.aborted) {
        throw retrievalClientError(
          "memory.context_retrieval_cancelled",
          "Retrieval request was cancelled",
          false,
        );
      }
      const transportTimeoutMs = Math.min(
        controls.timeoutMs ?? input.bounds.deadlineMs,
        input.bounds.deadlineMs,
      );
      budget = retrievalCallBudget(controls.signal, transportTimeoutMs, startedAtMs);
      budget.throwIfExhausted();
      const attestedCapability = decodeRetrievalCapability(capability);
      budget.throwIfExhausted();
      validateRetrievalPreflight(input, attestedCapability, required);
      budget.throwIfExhausted();
      const payload = retrievalRequestPayload(input);
      budget.throwIfExhausted();
      await abortableRetrievalPreflight(
        verifyRetrievalCapabilityFingerprint(attestedCapability),
        budget.signal,
      );
      budget.throwIfExhausted();
      const remainingTimeoutMs = budget.remainingTimeoutMs();
      const response = await this.http.request<Uint8Array | string>({
        method: "POST",
        path: "/v1/context/retrieve",
        ...requestControls({
          ...controls, signal: budget.signal, timeoutMs: remainingTimeoutMs,
        }),
        json: payload,
        responseType: "bytes",
        expectedStatuses: [200],
        maxResponseBytes: input.bounds.responseByteLimit,
        maxErrorResponseBytes: input.bounds.responseByteLimit,
        errorDecoder: retrievalErrorDecoder(input.bounds.responseByteLimit),
      });
      budget.throwIfExhausted();
      const decoded = decodeRetrieveContextResponseBytes(response, payload, attestedCapability);
      budget.throwIfExhausted();
      return decoded;
    } catch (error) {
      throw retrievalTransportError(
        error, budget?.timedOut() === true, controls.signal?.aborted === true,
      );
    } finally {
      budget?.cleanup();
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

function retrievalCallBudget(
  caller: AbortSignal | undefined,
  timeoutMs: number,
  startedAtMs: number,
) {
  const controller = new AbortController();
  const deadlineAtMs = startedAtMs + timeoutMs;
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const onCallerAbort = () => {
    if (!controller.signal.aborted) controller.abort(caller?.reason);
  };
  const onTimeout = () => {
    if (controller.signal.aborted) return;
    timedOut = true;
    controller.abort(new DOMException("Retrieval deadline exceeded", "TimeoutError"));
  };
  if (caller?.aborted) onCallerAbort();
  else caller?.addEventListener("abort", onCallerAbort, { once: true });
  const remainingMs = () => Math.max(0, deadlineAtMs - monotonicNowMs());
  if (!controller.signal.aborted) {
    const remaining = remainingMs();
    if (remaining <= 0) onTimeout();
    else {
      timer = setTimeout(onTimeout, remaining);
      timer.unref?.();
    }
  }
  return {
    signal: controller.signal,
    throwIfExhausted: () => {
      if (!controller.signal.aborted && !(remainingMs() > 0)) onTimeout();
      throwIfRetrievalControl(controller.signal);
    },
    remainingTimeoutMs: () => {
      const remaining = remainingMs();
      if (!controller.signal.aborted && !(remaining > 0)) onTimeout();
      throwIfRetrievalControl(controller.signal);
      return remaining;
    },
    timedOut: () => timedOut,
    cleanup: () => {
      if (timer !== undefined) clearTimeout(timer);
      caller?.removeEventListener("abort", onCallerAbort);
    },
  };
}

function throwIfRetrievalControl(signal: AbortSignal): void {
  if (signal.aborted) throw signal.reason;
}

function abortableRetrievalPreflight<T>(
  promise: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  if (signal.aborted) {
    void promise.catch(() => undefined);
    return Promise.reject(signal.reason);
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    const onAbort = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(error);
      },
    );
  });
}

function monotonicNowMs(): number {
  return globalThis.performance?.now() ?? Date.now();
}

function retrievalTransportError(
  error: unknown,
  timedOut: boolean,
  callerAborted: boolean,
): unknown {
  const safe = copyInfinityContextError(error);
  if (safe !== undefined) {
    if (timedOut || safe.code === "memory.request_timeout") {
      return retrievalClientError(
        "memory.context_retrieval_deadline_exceeded",
        "Retrieval request exceeded its absolute deadline",
        true,
      );
    }
    if (callerAborted || safe.code === "memory.request_aborted") {
      return retrievalClientError(
        "memory.context_retrieval_cancelled",
        "Retrieval request was cancelled",
        false,
      );
    }
    if (safe.code === "memory.network_error") {
      return retrievalClientError(
        "memory.context_retrieval_unavailable",
        "Retrieval transport is unavailable",
        true,
      );
    }
    return safe;
  }
  return retrievalClientError(
    callerAborted ? "memory.context_retrieval_cancelled" :
      timedOut ? "memory.context_retrieval_deadline_exceeded" :
        "memory.context_retrieval_unavailable",
    callerAborted ? "Retrieval request was cancelled" :
      timedOut ? "Retrieval request exceeded its absolute deadline" :
        "Retrieval transport is unavailable",
    !callerAborted,
  );
}

function retrievalClientError(code: string, message: string, retryable: boolean) {
  return createInfinityContextError({ statusCode: 0, code, message, retryable });
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
