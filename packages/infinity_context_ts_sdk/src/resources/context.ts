import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import type {
  ContextBundleData,
  ContextEnvelope,
  MemoryDigestData,
  SearchMemoryData,
} from "../context-types.js";
import { ReadScope, readScopePayload, withoutUndefined, type ReadScopeInput } from "../payload.js";
import type { ApiEnvelope, JsonObject } from "../types.js";

export interface ContextScopeInput extends ReadScopeInput, RequestControls {
  readonly readScope?: ReadScope;
}

export interface BuildContextInput extends ContextScopeInput {
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
}

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

function contextPayload(input: BuildContextInput): JsonObject {
  return withoutUndefined({
    ...scopePayload(input),
    query: input.query,
    token_budget: input.tokenBudget ?? 1800,
    max_facts: input.maxFacts ?? 20,
    max_chunks: input.maxChunks ?? 30,
    max_evidence_items: input.maxEvidenceItems,
    consistency_mode: input.consistencyMode,
    max_conflicting_suggestions: input.maxConflictingSuggestions,
    include_superseded: input.includeSuperseded || undefined,
    include_stale: input.includeStale || undefined,
    category: input.category,
    tags_any: input.tagsAny,
    tags_all: input.tagsAll,
    tags_none: input.tagsNone,
  }) as JsonObject;
}

function scopePayload(input: ContextScopeInput): JsonObject {
  return input.readScope?.toPayload() ?? readScopePayload(input);
}
