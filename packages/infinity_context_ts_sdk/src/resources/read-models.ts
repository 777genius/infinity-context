import type { RequestExecutor } from "../client.js";
import { scopeQuery, withoutUndefined, type SingleScopeInput } from "../payload.js";
import type {
  AnchorRecord,
  ApiEnvelope,
  AssetRecord,
  CaptureRecord,
  ContextLinkRecord,
  ContextLinkSuggestionRecord,
  DocumentRecord,
  FactRecord,
  JsonObject,
  MemoryScopeRecord,
} from "../types.js";

export type MemoryBrowserInput = Omit<SingleScopeInput, "threadId" | "threadExternalRef"> & {
  readonly limit?: number;
  readonly factStatus?: string | null;
  readonly episodeStatus?: string | null;
  readonly documentStatus?: string | null;
  readonly chunkStatus?: string | null;
  readonly extractionStatus?: string | null;
  readonly threadStatus?: string | null;
  readonly captureStatus?: string | null;
  readonly assetStatus?: string | null;
  readonly anchorStatus?: string | null;
  readonly linkStatus?: string | null;
  readonly suggestionStatus?: string | null;
};

export type OperationsConsoleInput = SingleScopeInput & {
  readonly limit?: number;
};

export interface MemoryBrowserData {
  readonly generated_at: string | null;
  readonly memory_scope: MemoryScopeRecord | null;
  readonly facts: readonly FactRecord[];
  readonly episodes: readonly JsonObject[];
  readonly documents: readonly DocumentRecord[];
  readonly chunks: readonly JsonObject[];
  readonly extraction_jobs: readonly JsonObject[];
  readonly threads: readonly JsonObject[];
  readonly captures: readonly CaptureRecord[];
  readonly assets: readonly AssetRecord[];
  readonly anchors: readonly AnchorRecord[];
  readonly context_links: readonly ContextLinkRecord[];
  readonly context_link_suggestions: readonly ContextLinkSuggestionRecord[];
  readonly stats: JsonObject;
  readonly visual_summary: JsonObject;
  readonly quick_actions: readonly JsonObject[];
  readonly diagnostics: JsonObject;
}

export interface OperationsConsoleData {
  readonly generated_at: string | null;
  readonly scope: JsonObject | null;
  readonly extraction_status_counts: JsonObject;
  readonly link_suggestion_status_counts: JsonObject;
  readonly extraction_jobs: readonly JsonObject[];
  readonly context_link_suggestions: readonly ContextLinkSuggestionRecord[];
  readonly diagnostics: JsonObject;
}

export class ReadModelsClient {
  constructor(private readonly http: RequestExecutor) {}

  getMemoryBrowser(input: MemoryBrowserInput = {}): Promise<ApiEnvelope<MemoryBrowserData>> {
    return this.http.request<ApiEnvelope<MemoryBrowserData>>({
      method: "GET",
      path: "/v1/memory-browser",
      params: memoryBrowserQuery(input),
    });
  }

  getOperationsConsole(input: OperationsConsoleInput = {}): Promise<ApiEnvelope<OperationsConsoleData>> {
    return this.http.request<ApiEnvelope<OperationsConsoleData>>({
      method: "GET",
      path: "/v1/operations-console",
      params: withoutUndefined({
        ...scopeQuery(input),
        limit: input.limit ?? 50,
      }),
    });
  }
}

const memoryBrowserQuery = (input: MemoryBrowserInput): JsonObject =>
  withoutUndefined({
    space_id: input.spaceId,
    memory_scope_id: input.memoryScopeId,
    space_slug: input.spaceSlug,
    memory_scope_external_ref: input.memoryScopeExternalRef,
    limit: input.limit ?? 50,
    fact_status: input.factStatus ?? "active",
    episode_status: input.episodeStatus ?? "active",
    document_status: input.documentStatus ?? "active",
    chunk_status: input.chunkStatus ?? "active",
    extraction_status: input.extractionStatus,
    thread_status: input.threadStatus ?? "active",
    capture_status: input.captureStatus,
    asset_status: input.assetStatus ?? "stored",
    anchor_status: input.anchorStatus ?? "active",
    link_status: input.linkStatus,
    suggestion_status: input.suggestionStatus,
  }) as JsonObject;
