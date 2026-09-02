import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import { createInfinityContextError, InfinityContextError } from "../errors.js";
import {
  collectCursorItems,
  iterateCursorItems,
  type CursorPaginationOptions,
} from "../pagination.js";
import {
  normalizedPollingInterval,
  normalizedPollingMaxAttempts,
  throwIfAborted,
  waitForNextPoll,
  type PollingControls,
} from "../polling.js";
import { ValueError, withoutUndefined } from "../payload.js";
import type { ApiEnvelope, JsonObject, JsonValue } from "../types.js";

export interface ListOutboxDiagnosticsInput extends RequestControls {
  readonly limit?: number;
  readonly cursor?: string;
}

export interface OutboxDiagnosticItem extends JsonObject {
  readonly id: number;
  readonly event_type: string;
  readonly aggregate_type: string;
  readonly aggregate_id: string;
  readonly aggregate_version: number;
  readonly workload_class: string;
  readonly fairness_key: string;
  readonly status: string;
  readonly attempt_count: number;
  readonly last_safe_error: string | null;
  readonly last_safe_diagnostic_code: string | null;
  readonly next_attempt_at: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface OutboxDiagnosticsData extends JsonObject {
  readonly counts: JsonObject;
  readonly oldest_active_lag_seconds?: number | null;
  readonly items: readonly OutboxDiagnosticItem[];
  readonly next_cursor?: string | null;
}

export type OutboxDiagnosticsResponse = ApiEnvelope<OutboxDiagnosticsData> & JsonObject;

export type OutboxDrainStatus =
  | "pending"
  | "retry_pending"
  | "running"
  | "processing"
  | "leased"
  | "failed"
  | "poisoned"
  | "dead_letter"
  | "discarded"
  | "done"
  | (string & {});

export interface WaitForOutboxDrainInput extends PollingControls {
  readonly limit?: number;
  readonly blockingStatuses?: readonly OutboxDrainStatus[];
  readonly failureStatuses?: readonly OutboxDrainStatus[];
  readonly maxBlockingItems?: number;
  readonly throwOnFailure?: boolean;
}

export interface OutboxDrainDiagnostics extends JsonObject {
  readonly attempts: number;
  readonly blocking_count: number;
  readonly failure_count: number;
  readonly max_blocking_items: number;
  readonly oldest_active_lag_seconds?: number | null;
  readonly blocking_statuses: readonly string[];
  readonly failure_statuses: readonly string[];
  readonly listed_blocking_item_ids: readonly number[];
  readonly listed_failure_item_ids: readonly number[];
}

export interface OutboxDrainResult extends JsonObject {
  readonly response: OutboxDiagnosticsResponse;
  readonly diagnostics: OutboxDrainDiagnostics;
}

export class DiagnosticsClient {
  constructor(private readonly http: RequestExecutor) {}

  adapters(input: RequestControls = {}): Promise<JsonObject> {
    return this.http.request<JsonObject>({
      method: "GET",
      path: "/v1/diagnostics/adapters",
      ...requestControls(input),
    });
  }

  outbox(input: ListOutboxDiagnosticsInput = {}): Promise<OutboxDiagnosticsResponse> {
    return this.http.request<OutboxDiagnosticsResponse>({
      method: "GET",
      path: "/v1/diagnostics/outbox",
      ...requestControls(input),
      params: withoutUndefined({ limit: input.limit ?? 100, cursor: input.cursor }),
    });
  }

  iterateOutboxItems(options: CursorPaginationOptions = {}): AsyncIterable<OutboxDiagnosticItem> {
    return iterateCursorItems<OutboxDiagnosticItem>(
      async (page) => {
        const response = await this.outbox(page);
        return {
          data: response.data.items,
          next_cursor: response.data.next_cursor ?? null,
        };
      },
      options,
    );
  }

  listAllOutboxItems(options: CursorPaginationOptions = {}): Promise<readonly OutboxDiagnosticItem[]> {
    return collectCursorItems<OutboxDiagnosticItem>(
      async (page) => {
        const response = await this.outbox(page);
        return {
          data: response.data.items,
          next_cursor: response.data.next_cursor ?? null,
        };
      },
      options,
    );
  }

  async waitForOutboxDrain(input: WaitForOutboxDrainInput = {}): Promise<OutboxDrainResult> {
    const maxAttempts = normalizedPollingMaxAttempts(input.maxAttempts, "waitForOutboxDrain");
    const pollIntervalMs = normalizedPollingInterval(input.pollIntervalMs, "waitForOutboxDrain");
    const maxBlockingItems = normalizedMaxBlockingItems(input.maxBlockingItems);
    const blockingStatuses = new Set(input.blockingStatuses ?? DEFAULT_OUTBOX_BLOCKING_STATUSES);
    const failureStatuses = new Set(input.failureStatuses ?? DEFAULT_OUTBOX_FAILURE_STATUSES);
    let last: OutboxDrainResult | undefined;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      throwIfAborted(input.signal);
      const response = await this.outbox({
        ...(input.limit !== undefined ? { limit: input.limit } : {}),
        ...(input.headers !== undefined ? { headers: input.headers } : {}),
        ...(input.signal !== undefined ? { signal: input.signal } : {}),
        ...(input.timeoutMs !== undefined ? { timeoutMs: input.timeoutMs } : {}),
      });
      last = {
        response,
        diagnostics: outboxDrainDiagnostics(
          response.data,
          attempt + 1,
          maxBlockingItems,
          blockingStatuses,
          failureStatuses,
        ),
      };

      if (input.throwOnFailure === true && last.diagnostics.failure_count > 0) {
        throw outboxDrainFailure(last);
      }
      if (last.diagnostics.blocking_count <= maxBlockingItems) {
        return last;
      }
      if (attempt + 1 < maxAttempts) {
        await waitForNextPoll(input, pollIntervalMs);
      }
    }

    throw outboxDrainTimeout(maxAttempts, last);
  }

  memoryScope(memoryScopeId: string, input: RequestControls = {}): Promise<JsonObject> {
    return this.http.request<JsonObject>({
      method: "GET",
      path: `/v1/diagnostics/memory-scope/${memoryScopeId}`,
      ...requestControls(input),
    });
  }

  metrics(input: RequestControls = {}): Promise<JsonObject> {
    return this.http.request<JsonObject>({
      method: "GET",
      path: "/v1/diagnostics/metrics",
      ...requestControls(input),
    });
  }

  storage(input: RequestControls = {}): Promise<JsonObject> {
    return this.http.request<JsonObject>({
      method: "GET",
      path: "/v1/diagnostics/storage",
      ...requestControls(input),
    });
  }

  operationsConsole(input: { readonly limit?: number } & RequestControls = {}): Promise<ApiEnvelope<JsonObject>> {
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "GET",
      path: "/v1/operations-console",
      ...requestControls(input),
      params: { limit: input.limit ?? 50 },
    });
  }
}

const DEFAULT_OUTBOX_BLOCKING_STATUSES = ["pending", "retry_pending", "running", "processing", "leased"] as const;
const DEFAULT_OUTBOX_FAILURE_STATUSES = ["failed", "poisoned", "dead_letter", "discarded"] as const;

function normalizedMaxBlockingItems(value: number | undefined): number {
  const maxBlockingItems = value ?? 0;
  if (!Number.isInteger(maxBlockingItems) || maxBlockingItems < 0) {
    throw new ValueError("waitForOutboxDrain maxBlockingItems must be a non-negative integer");
  }
  return maxBlockingItems;
}

function outboxDrainDiagnostics(
  data: OutboxDiagnosticsData,
  attempts: number,
  maxBlockingItems: number,
  blockingStatuses: ReadonlySet<string>,
  failureStatuses: ReadonlySet<string>,
): OutboxDrainDiagnostics {
  const listedBlockingItems = data.items.filter((item) => blockingStatuses.has(item.status));
  const listedFailureItems = data.items.filter((item) => failureStatuses.has(item.status));
  const blockingCounts = countStatuses(data.counts, blockingStatuses);
  const failureCounts = countStatuses(data.counts, failureStatuses);

  return {
    attempts,
    blocking_count: conservativeStatusCount(blockingCounts, listedBlockingItems.length),
    failure_count: conservativeStatusCount(failureCounts, listedFailureItems.length),
    max_blocking_items: maxBlockingItems,
    oldest_active_lag_seconds: data.oldest_active_lag_seconds ?? null,
    blocking_statuses: [...blockingStatuses],
    failure_statuses: [...failureStatuses],
    listed_blocking_item_ids: listedBlockingItems.map((item) => item.id),
    listed_failure_item_ids: listedFailureItems.map((item) => item.id),
  };
}

function conservativeStatusCount(
  counts: { readonly matched: boolean; readonly total: number },
  listedCount: number,
): number {
  return Math.max(counts.matched ? counts.total : 0, listedCount);
}

function countStatuses(
  counts: JsonObject,
  statuses: ReadonlySet<string>,
): { readonly matched: boolean; readonly total: number } {
  let matched = false;
  let total = 0;
  for (const [status, rawCount] of Object.entries(counts)) {
    if (!statuses.has(status)) {
      continue;
    }
    matched = true;
    total += numericCount(rawCount);
  }
  return { matched, total };
}

function numericCount(value: JsonValue | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function outboxDrainTimeout(maxAttempts: number, last: OutboxDrainResult | undefined): InfinityContextError {
  return createInfinityContextError({
    statusCode: 0,
    code: "memory.outbox_drain_timeout",
    message: `Outbox did not drain after ${maxAttempts} attempt(s)`,
    retryable: true,
    details: withoutUndefined({
      max_attempts: maxAttempts,
      blocking_count: last?.diagnostics.blocking_count,
      failure_count: last?.diagnostics.failure_count,
      oldest_active_lag_seconds: last?.diagnostics.oldest_active_lag_seconds,
      listed_blocking_item_ids: last?.diagnostics.listed_blocking_item_ids,
    }),
  });
}

function outboxDrainFailure(result: OutboxDrainResult): InfinityContextError {
  return createInfinityContextError({
    statusCode: 0,
    code: "memory.outbox_drain_failed",
    message: "Outbox contains failed items",
    retryable: false,
    details: withoutUndefined({
      failure_count: result.diagnostics.failure_count,
      listed_failure_item_ids: result.diagnostics.listed_failure_item_ids,
      failure_statuses: result.diagnostics.failure_statuses,
    }),
  });
}
