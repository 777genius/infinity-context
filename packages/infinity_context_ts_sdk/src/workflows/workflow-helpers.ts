import type { RequestControls } from "../client.js";
import type { ContextRetrievalComponent } from "../diagnostics.js";
import { copyInfinityContextError, createInfinityContextError, type InfinityContextError } from "../errors.js";
import { ValueError, type SingleScopeInput } from "../payload.js";
import type { JsonObject, SourceRef } from "../types.js";

export interface MemoryBriefRetrievalHealth {
  readonly vectorHealthy: boolean;
  readonly graphHealthy: boolean;
  readonly ragHealthy: boolean;
}

export interface WorkflowErrorData {
  readonly name: string;
  readonly message: string;
  readonly code?: string;
  readonly statusCode?: number;
  readonly retryable?: boolean;
  readonly requestId?: string;
}

export type WorkflowStepOptions<TOptions extends object> = boolean | TOptions;

export function memoryBriefRetrievalHealthy(
  diagnostics: MemoryBriefRetrievalHealth,
  component: ContextRetrievalComponent,
): boolean {
  if (component === "vector") {
    return diagnostics.vectorHealthy;
  }
  if (component === "graph") {
    return diagnostics.graphHealthy;
  }
  return diagnostics.ragHealthy;
}

export function sourceRefKey(sourceRef: SourceRef): string {
  return `${sourceRef.source_type}:${sourceRef.source_id}`;
}

export function citationSourceRef(
  citation: { readonly source_type?: string; readonly source_id?: string },
): SourceRef | undefined {
  if (!citation.source_type || !citation.source_id) {
    return undefined;
  }

  return {
    source_type: citation.source_type,
    source_id: citation.source_id,
  };
}

export function uniqueStrings(values: readonly string[]): readonly string[] {
  return [...new Set(values)];
}

export function isEnabled<TOptions extends object>(
  value: boolean | TOptions | undefined,
  defaultValue: boolean,
): boolean {
  return value === undefined ? defaultValue : value !== false;
}

export function stepOptions<TOptions extends object>(
  value: boolean | TOptions | undefined,
): Partial<TOptions> {
  return typeof value === "object" ? value : {};
}

export function requiredStepOptions<TOptions extends object>(
  value: boolean | TOptions | undefined,
  message: string,
): TOptions {
  if (typeof value !== "object" || value === null) {
    throw new ValueError(message);
  }
  return value;
}

export function stringField(input: JsonObject, key: string): string | undefined {
  const value = input[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function requiredWorkflowText(value: string | undefined, message: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ValueError(message);
  }
  return value;
}

export function jsonObjectField(input: JsonObject, key: string): JsonObject | undefined {
  const value = input[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

export function normalizeBatchConcurrency(value: number | undefined): number {
  if (value === undefined) {
    return 4;
  }
  if (!Number.isInteger(value) || value < 1 || value > 25) {
    throw new ValueError("recordSourceEvidenceBatch concurrency must be an integer from 1 to 25");
  }
  return value;
}

export function workflowErrorData(error: unknown): WorkflowErrorData {
  const safe = copyInfinityContextError(error);
  const message = safe?.message ?? "Workflow operation failed";
  const name = safe?.name ?? "Error";
  const code = safe?.code;
  const statusCode = safe?.statusCode;
  const retryable = safe?.retryable;
  const requestId = safe?.requestId;

  return {
    name,
    message,
    ...(code === undefined ? {} : { code }),
    ...(statusCode === undefined ? {} : { statusCode }),
    ...(retryable === undefined ? {} : { retryable }),
    ...(requestId === undefined ? {} : { requestId }),
  };
}

export function workflowConflict(error: unknown): boolean {
  return copyInfinityContextError(error)?.statusCode === 409;
}

export function safeWorkflowError(error: unknown): InfinityContextError {
  return copyInfinityContextError(error) ?? createInfinityContextError({
    statusCode: 0,
    code: "memory.workflow_failed",
    message: "Infinity Context workflow failed",
    retryable: false,
    cause: error,
  });
}

export function workflowControls(input: RequestControls): RequestControls {
  return {
    ...optional("headers", input.headers),
    ...optional("signal", input.signal),
    ...optional("timeoutMs", input.timeoutMs),
  };
}

export function singleScopeInput(input: SingleScopeInput): SingleScopeInput {
  return {
    ...optional("spaceId", input.spaceId),
    ...optional("memoryScopeId", input.memoryScopeId),
    ...optional("threadId", input.threadId),
    ...optional("spaceSlug", input.spaceSlug),
    ...optional("memoryScopeExternalRef", input.memoryScopeExternalRef),
    ...optional("threadExternalRef", input.threadExternalRef),
  };
}

export function withWorkflowControls<TInput extends RequestControls>(
  batchControls: RequestControls,
  input: TInput,
): TInput {
  return {
    ...input,
    ...mergeWorkflowControls(batchControls, input),
  };
}

export function mergeWorkflowControls(parent: RequestControls, child: RequestControls): RequestControls {
  const headers = parent.headers === undefined && child.headers === undefined
    ? undefined
    : { ...parent.headers, ...child.headers };

  return {
    ...optional("headers", headers),
    ...optional("signal", child.signal ?? parent.signal),
    ...optional("timeoutMs", child.timeoutMs ?? parent.timeoutMs),
  };
}

export function isDefined<TValue>(value: TValue | undefined): value is TValue {
  return value !== undefined;
}

export function ratio(value: number, total: number): number {
  return total <= 0 ? 0 : value / total;
}

export function incrementCount(counts: Record<string, number>, key: string): void {
  counts[key] = (counts[key] ?? 0) + 1;
}

export function optional<TKey extends string, TValue>(
  key: TKey,
  value: TValue | undefined,
): { readonly [K in TKey]?: TValue } {
  return value === undefined ? {} : { [key]: value } as { readonly [K in TKey]: TValue };
}
