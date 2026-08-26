import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import {
  collectCursorItems,
  iterateCursorItems,
  type CursorPaginationOptions,
  type PaginatedEnvelope,
} from "../pagination.js";
import { singleScopePayload, withoutUndefined, type SingleScopeInput } from "../payload.js";
import type { ApiEnvelope, DocumentRecord, JsonObject, SourceRef } from "../types.js";
import { validateSingleScopePayload, ValueError } from "../payload.js";
import {
  documentRetrievalProjectionV1Payload,
  type DocumentRetrievalProjectionV1Input,
} from "../document-retrieval-projection.js";
import { contextRetrievalV2ErrorDecoder } from "../retrieval-v2-errors.js";
import {
  EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES,
  assertExactDocumentReconciliationCapabilityV1,
  decodeExactDocumentReconciliationResponseV1,
  exactDocumentReconciliationValidation,
  type ExactDocumentReconciliationCapabilityV1,
  type ExactDocumentReconciliationResultV1,
} from "../document-reconciliation.js";

export interface ListDocumentChunksInput extends RequestControls {
  readonly limit?: number;
  readonly cursor?: string;
}

export interface IngestDocumentInput extends SingleScopeInput, RequestControls {
  readonly title: string;
  readonly text: string;
  readonly sourceExternalId: string;
  readonly sourceType?: string;
  readonly classification?: string;
  readonly sourceRefs?: readonly SourceRef[];
  readonly idempotencyKey?: string;
  readonly retrievalProjection?: DocumentRetrievalProjectionV1Input | null;
}

export interface IngestEpisodeInput extends SingleScopeInput, RequestControls {
  readonly sourceExternalId: string;
  readonly text: string;
  readonly sourceType?: string;
  readonly occurredAt?: string;
  readonly speaker?: string;
  readonly trustLevel?: string;
  readonly kindHint?: string;
  readonly language?: string;
  readonly metadata?: JsonObject;
  readonly idempotencyKey?: string;
}

export interface ProcessDocumentInput extends RequestControls {
  readonly idempotencyKey?: string;
}

export interface ListScopeDocumentsInput extends SingleScopeInput, RequestControls {
  readonly status?: "active";
  readonly sourceExternalId?: string;
  readonly limit?: number;
  readonly cursor?: string;
}

export interface ReconcileExactDocumentInput extends RequestControls {
  readonly capability: ExactDocumentReconciliationCapabilityV1;
  readonly spaceId: string;
  readonly memoryScopeId: string;
  readonly threadId?: string | null;
  readonly sourceType: string;
  readonly sourceExternalId: string;
  readonly projectionGeneration?: string;
  readonly profileGeneration?: string;
  readonly idempotencyKey?: string;
  readonly deadlineMs?: number;
}

export class DocumentsClient {
  constructor(private readonly http: RequestExecutor) {}

  async reconcileExactDocument(
    input: ReconcileExactDocumentInput,
  ): Promise<ExactDocumentReconciliationResultV1> {
    assertExactDocumentReconciliationCapabilityV1(input.capability);
    const validate = exactDocumentReconciliationValidation;
    validate.text(input.spaceId, 80, "spaceId");
    validate.text(input.memoryScopeId, 80, "memoryScopeId");
    if (input.threadId != null) validate.text(input.threadId, 80, "threadId");
    validate.text(input.sourceType, 80, "sourceType");
    validate.text(input.sourceExternalId, 240, "sourceExternalId");
    if (input.projectionGeneration !== undefined) validate.text(input.projectionGeneration, 256, "projectionGeneration");
    if (input.profileGeneration !== undefined) validate.text(input.profileGeneration, 160, "profileGeneration");
    if (input.idempotencyKey !== undefined) validate.text(input.idempotencyKey, 200, "idempotencyKey");
    const deadlineMs = validate.integer(input.deadlineMs ?? 5_000, 50, Math.min(10_000, input.capability.max_deadline_ms), "deadlineMs");
    const transportTimeoutMs = input.timeoutMs === undefined
      ? deadlineMs + 250
      : validate.integer(input.timeoutMs, 1, deadlineMs + 250, "timeoutMs");
    const response = await this.http.request<Uint8Array | string>({
      method: "POST",
      path: "/v1/documents/reconcile-exact",
      ...requestControls({
        ...(input.headers === undefined ? {} : { headers: input.headers }),
        ...(input.signal === undefined ? {} : { signal: input.signal }),
        timeoutMs: transportTimeoutMs,
      }),
      responseType: "bytes",
      maxResponseBytes: EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES,
      json: withoutUndefined({
        contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
        space_id: input.spaceId,
        memory_scope_id: input.memoryScopeId,
        thread_id: input.threadId ?? undefined,
        source_type: input.sourceType,
        source_external_id: input.sourceExternalId,
        projection_generation: input.projectionGeneration,
        profile_generation: input.profileGeneration,
        idempotency_key: input.idempotencyKey,
        deadline_ms: deadlineMs,
      }) as JsonObject,
    });
    return decodeExactDocumentReconciliationResponseV1(response, input);
  }

  ingestDocument(input: IngestDocumentInput): Promise<ApiEnvelope<DocumentRecord>> {
    return this.http.request<ApiEnvelope<DocumentRecord>>({
      method: "POST",
      path: "/v1/documents",
      idempotencyKey: input.idempotencyKey,
      ...(input.retrievalProjection == null ? {} : {
        maxErrorResponseBytes: 1_048_576,
        errorDecoder: contextRetrievalV2ErrorDecoder(1_048_576),
      }),
      ...requestControls(input),
      json: withoutUndefined({
        ...singleScopePayload(input),
        title: input.title,
        text: input.text,
        source_type: input.sourceType ?? "document",
        source_external_id: input.sourceExternalId,
        classification: input.classification ?? "unknown",
        source_refs: input.sourceRefs,
        retrieval_projection: input.retrievalProjection == null
          ? undefined
          : documentRetrievalProjectionV1Payload(input.retrievalProjection),
      }) as JsonObject,
    });
  }

  ingestEpisode(input: IngestEpisodeInput): Promise<ApiEnvelope<JsonObject>> {
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "POST",
      path: "/v1/episodes",
      idempotencyKey: input.idempotencyKey,
      ...requestControls(input),
      json: withoutUndefined({
        ...singleScopePayload(input),
        source_type: input.sourceType ?? "unknown",
        source_external_id: input.sourceExternalId,
        text: input.text,
        occurred_at: input.occurredAt,
        speaker: input.speaker,
        trust_level: input.trustLevel ?? "medium",
        kind_hint: input.kindHint,
        language: input.language,
        metadata: input.metadata,
      }) as JsonObject,
    });
  }

  getDocument(documentId: string, input: RequestControls = {}): Promise<ApiEnvelope<DocumentRecord>> {
    return this.http.request<ApiEnvelope<DocumentRecord>>({
      method: "GET",
      path: `/v1/documents/${documentId}`,
      ...requestControls(input),
    });
  }

  listDocumentChunks(
    documentId: string,
    input: ListDocumentChunksInput = {},
  ): Promise<PaginatedEnvelope<JsonObject[]>> {
    return this.http.request<PaginatedEnvelope<JsonObject[]>>({
      method: "GET",
      path: `/v1/documents/${documentId}/chunks`,
      ...requestControls(input),
      params: withoutUndefined({ limit: input.limit ?? 100, cursor: input.cursor }),
    });
  }

  iterateDocumentChunks(
    documentId: string,
    options: CursorPaginationOptions = {},
  ): AsyncIterable<JsonObject> {
    return iterateCursorItems<JsonObject>(
      (page) => this.listDocumentChunks(documentId, page),
      options,
    );
  }

  listAllDocumentChunks(
    documentId: string,
    options: CursorPaginationOptions = {},
  ): Promise<readonly JsonObject[]> {
    return collectCursorItems<JsonObject>(
      (page) => this.listDocumentChunks(documentId, page),
      options,
    );
  }

  processDocument(
    documentId: string,
    input: ProcessDocumentInput = {},
  ): Promise<ApiEnvelope<DocumentRecord>> {
    return this.http.request<ApiEnvelope<DocumentRecord>>({
      method: "POST",
      path: `/v1/documents/${documentId}/process`,
      idempotencyKey: input.idempotencyKey,
      ...requestControls(input),
    });
  }

  deleteDocument(documentId: string, input: RequestControls = {}): Promise<ApiEnvelope<DocumentRecord>> {
    return this.http.request<ApiEnvelope<DocumentRecord>>({
      method: "DELETE",
      path: `/v1/documents/${documentId}`,
      ...requestControls(input),
    });
  }

  listScopeDocuments(input: ListScopeDocumentsInput): Promise<PaginatedEnvelope<DocumentRecord[]>> {
    const scope = normalizedDocumentListScope(input);
    validateSingleScopePayload(scope);
    requireExplicitScope(scope);
    const status = normalizeOptionalText(input.status, "status", 40) ?? "active";
    if (status !== "active") {
      throw new ValueError("status must be active");
    }
    const sourceExternalId = normalizeOptionalText(input.sourceExternalId, "sourceExternalId", 240);
    const cursor = validateOpaqueCursor(input.cursor);
    const limit = input.limit ?? 100;
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw new ValueError("limit must be an integer between 1 and 500");
    }
    return this.http.request<PaginatedEnvelope<DocumentRecord[]>>({
      method: "GET",
      path: "/v1/documents",
      ...requestControls(input),
      params: withoutUndefined({
        ...scope,
        status,
        source_external_id: sourceExternalId,
        limit,
        cursor,
      }),
    });
  }

  iterateScopeDocuments(
    input: Omit<ListScopeDocumentsInput, "cursor" | "limit">,
    options: CursorPaginationOptions = {},
  ): AsyncIterable<DocumentRecord> {
    return iterateCursorItems<DocumentRecord>(
      (page) => this.listScopeDocuments({ ...input, ...page }),
      options,
    );
  }

  listAllScopeDocuments(
    input: Omit<ListScopeDocumentsInput, "cursor" | "limit">,
    options: CursorPaginationOptions = {},
  ): Promise<readonly DocumentRecord[]> {
    return collectCursorItems<DocumentRecord>(
      (page) => this.listScopeDocuments({ ...input, ...page }),
      options,
    );
  }
}

function requireExplicitScope(scope: JsonObject): void {
  const hasCanonicalScope =
    typeof scope.space_id === "string" && typeof scope.memory_scope_id === "string";
  const hasExternalScope =
    typeof scope.space_slug === "string" &&
    typeof scope.memory_scope_external_ref === "string";
  if (!hasCanonicalScope && !hasExternalScope) {
    throw new ValueError(
      "listScopeDocuments requires spaceId + memoryScopeId or spaceSlug + memoryScopeExternalRef",
    );
  }
}

function normalizedDocumentListScope(input: ListScopeDocumentsInput): JsonObject {
  return withoutUndefined({
    space_id: normalizeOptionalText(input.spaceId, "spaceId", 80),
    memory_scope_id: normalizeOptionalText(input.memoryScopeId, "memoryScopeId", 80),
    thread_id: normalizeOptionalText(input.threadId, "threadId", 80),
    space_slug: normalizeOptionalText(input.spaceSlug, "spaceSlug", 160),
    memory_scope_external_ref: normalizeOptionalText(
      input.memoryScopeExternalRef,
      "memoryScopeExternalRef",
      200,
    ),
    thread_external_ref: normalizeOptionalText(
      input.threadExternalRef,
      "threadExternalRef",
      200,
    ),
  });
}

function normalizeOptionalText(
  value: string | undefined,
  name: string,
  maxLength: number,
): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new ValueError(`${name} must not be blank`);
  }
  if (normalized.length > maxLength) {
    throw new ValueError(`${name} must be at most ${maxLength} characters`);
  }
  return normalized;
}

function validateOpaqueCursor(value: string | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (value.trim().length === 0) {
    throw new ValueError("cursor must not be blank");
  }
  if (value.length > 1000) {
    throw new ValueError("cursor must be at most 1000 characters");
  }
  return value;
}
