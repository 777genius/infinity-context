import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import {
  collectCursorItems,
  iterateCursorItems,
  type CursorPaginationOptions,
  type PaginatedEnvelope,
} from "../pagination.js";
import { MemoryScope, scopeQuery, singleScopePayload, withoutUndefined, type SingleScopeInput } from "../payload.js";
import type { ApiEnvelope, FactRecord, JsonObject, SourceRef } from "../types.js";

export interface RememberFactInput extends SingleScopeInput, RequestControls {
  readonly scope?: MemoryScope;
  readonly text: string;
  readonly sourceRefs: readonly SourceRef[];
  readonly kind?: string;
  readonly idempotencyKey?: string;
  readonly classification?: string;
  readonly category?: string;
  readonly tags?: readonly string[];
  readonly ttlPolicy?: string;
}

export interface ListFactsInput extends SingleScopeInput, RequestControls {
  readonly status?: string | null;
  readonly category?: string;
  readonly tag?: string;
  readonly limit?: number;
  readonly cursor?: string;
}

export interface UpdateFactInput extends RequestControls {
  readonly expectedVersion: number;
  readonly text: string;
  readonly reason: string;
  readonly sourceRefs: readonly SourceRef[];
}

export interface GetRelatedFactsInput extends RequestControls {
  readonly limit?: number;
  readonly includeOtherThreads?: boolean;
}

export interface LinkFactsInput extends RequestControls {
  readonly targetFactId: string;
  readonly relationType?: string;
  readonly reason: string;
}

export interface ListFactRelationsInput extends RequestControls {
  readonly status?: string | null;
  readonly limit?: number;
}

export class FactsClient {
  constructor(private readonly http: RequestExecutor) {}

  rememberFact(input: RememberFactInput): Promise<ApiEnvelope<FactRecord>> {
    const scope = input.scope?.toPayload() ?? singleScopePayload(input);
    return this.http.request<ApiEnvelope<FactRecord>>({
      method: "POST",
      path: "/v1/facts",
      idempotencyKey: input.idempotencyKey,
      ...requestControls(input),
      json: withoutUndefined({
        ...scope,
        text: input.text,
        kind: input.kind ?? "note",
        source_refs: input.sourceRefs,
        classification: input.classification ?? "internal",
        category: input.category,
        tags: input.tags,
        ttl_policy: input.ttlPolicy,
      }) as JsonObject,
    });
  }

  updateFact(
    factId: string,
    input: UpdateFactInput,
  ): Promise<ApiEnvelope<FactRecord>> {
    return this.http.request<ApiEnvelope<FactRecord>>({
      method: "PATCH",
      path: `/v1/facts/${factId}`,
      ...requestControls(input),
      json: {
        expected_version: input.expectedVersion,
        text: input.text,
        reason: input.reason,
        source_refs: input.sourceRefs,
      },
    });
  }

  forgetFact(factId: string, input: RequestControls = {}): Promise<ApiEnvelope<FactRecord>> {
    return this.http.request<ApiEnvelope<FactRecord>>({
      method: "DELETE",
      path: `/v1/facts/${factId}`,
      ...requestControls(input),
    });
  }

  getFact(factId: string, input: RequestControls = {}): Promise<ApiEnvelope<FactRecord>> {
    return this.http.request<ApiEnvelope<FactRecord>>({
      method: "GET",
      path: `/v1/facts/${factId}`,
      ...requestControls(input),
    });
  }

  listFacts(input: ListFactsInput): Promise<PaginatedEnvelope<FactRecord[]>> {
    return this.http.request<PaginatedEnvelope<FactRecord[]>>({
      method: "GET",
      path: "/v1/facts",
      ...requestControls(input),
      params: withoutUndefined({
        ...scopeQuery(input),
        status: input.status === undefined ? "active" : input.status,
        category: input.category,
        tag: input.tag,
        limit: input.limit ?? 100,
        cursor: input.cursor,
      }),
    });
  }

  iterateFacts(
    input: Omit<ListFactsInput, "cursor" | "limit">,
    options: CursorPaginationOptions = {},
  ): AsyncIterable<FactRecord> {
    return iterateCursorItems<FactRecord>(
      (page) => this.listFacts({ ...input, ...page }),
      options,
    );
  }

  listAllFacts(
    input: Omit<ListFactsInput, "cursor" | "limit">,
    options: CursorPaginationOptions = {},
  ): Promise<readonly FactRecord[]> {
    return collectCursorItems<FactRecord>(
      (page) => this.listFacts({ ...input, ...page }),
      options,
    );
  }

  getRelatedFacts(
    factId: string,
    input: GetRelatedFactsInput = {},
  ): Promise<ApiEnvelope<FactRecord[]>> {
    return this.http.request<ApiEnvelope<FactRecord[]>>({
      method: "GET",
      path: `/v1/facts/${factId}/related`,
      ...requestControls(input),
      params: {
        limit: input.limit ?? 10,
        include_other_threads: input.includeOtherThreads ?? false,
      },
    });
  }

  linkFacts(
    sourceFactId: string,
    input: LinkFactsInput,
  ): Promise<ApiEnvelope<JsonObject>> {
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "POST",
      path: `/v1/facts/${sourceFactId}/relations`,
      ...requestControls(input),
      json: {
        target_fact_id: input.targetFactId,
        relation_type: input.relationType ?? "related_to",
        reason: input.reason,
      },
    });
  }

  listFactRelations(
    factId: string,
    input: ListFactRelationsInput = {},
  ): Promise<ApiEnvelope<JsonObject[]>> {
    return this.http.request<ApiEnvelope<JsonObject[]>>({
      method: "GET",
      path: `/v1/facts/${factId}/relations`,
      ...requestControls(input),
      params: withoutUndefined({
        status: input.status === undefined ? "active" : input.status,
        limit: input.limit ?? 50,
      }),
    });
  }

  unlinkFactRelation(relationId: string, input: RequestControls = {}): Promise<ApiEnvelope<JsonObject>> {
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "DELETE",
      path: `/v1/facts/relations/${relationId}`,
      ...requestControls(input),
    });
  }

  listFactVersions(factId: string, input: RequestControls = {}): Promise<ApiEnvelope<JsonObject[]>> {
    return this.http.request<ApiEnvelope<JsonObject[]>>({
      method: "GET",
      path: `/v1/facts/${factId}/versions`,
      ...requestControls(input),
    });
  }
}
