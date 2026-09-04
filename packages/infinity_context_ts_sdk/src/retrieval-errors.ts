import type { HttpErrorDecoder } from "./client.js";
import { createInfinityContextError, InfinityContextError, responseByteLimitError } from "./errors.js";
import { assertUnicodeScalarString, pythonTrim } from "./retrieval-canonical.js";
import { decodeRetrievalJson } from "./retrieval-json.js";
import type { JsonObject } from "./types.js";

export const CONTEXT_RETRIEVAL_ERROR_SPECS = Object.freeze({
  "memory.context_retrieval_contract_invalid": [400, false],
  "memory.unauthorized": [401, false],
  "memory.forbidden": [403, false],
  "memory.context_retrieval_scope_not_found": [404, false],
  "memory.context_retrieval_capability_mismatch": [409, false],
  "memory.context_retrieval_unsupported": [422, false],
  "memory.context_retrieval_unavailable": [503, true],
  "memory.context_retrieval_deadline_exceeded": [504, true],
  "memory.document_projection_invalid": [400, false],
  "memory.document_projection_locator_conflict": [409, false],
  "memory.document_projection_ordinal_conflict": [409, false],
  "memory.document_projection_idempotency_conflict": [409, false],
} as const);

export type RetrievalErrorCode = keyof typeof CONTEXT_RETRIEVAL_ERROR_SPECS;

export function retrievalErrorDecoder(maximumBytes: number): HttpErrorDecoder {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 0) {
    throw new TypeError("Contract C error byte limit must be a non-negative safe integer");
  }
  return (statusCode, headers, body) => decodeRetrievalError(
    statusCode,
    body,
    maximumBytes,
    headers.get("x-request-id") ?? undefined,
  );
}

export function decodeRetrievalError(
  statusCode: number,
  body: Uint8Array | string,
  maximumBytes = 1_048_576,
  requestId?: string,
): InfinityContextError {
  const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
  if (bytes.byteLength > maximumBytes) throw responseByteLimitError(statusCode, requestId);
  const root = exactObject(decodeRetrievalJson(body), ["error"], "error envelope");
  const error = exactObject(root.error, ["code", "message", "retryable"], "error");
  if (typeof error.code !== "string" || !Object.hasOwn(CONTEXT_RETRIEVAL_ERROR_SPECS, error.code)) {
    invalid("error.code is unsupported");
  }
  const code = error.code as RetrievalErrorCode;
  const spec = CONTEXT_RETRIEVAL_ERROR_SPECS[code];
  if (statusCode !== spec[0]) invalid("HTTP status does not match error.code");
  if (typeof error.retryable !== "boolean" || error.retryable !== spec[1]) {
    invalid("error.retryable does not match error.code");
  }
  if (typeof error.message !== "string" || pythonTrim(error.message) === "") {
    invalid("error.message must be a non-blank string");
  }
  assertUnicodeScalarString(error.message, "error.message");
  for (const point of error.message) {
    const value = point.codePointAt(0)!;
    if (value < 0x20 || (value >= 0x7f && value <= 0x9f)) {
      invalid("error.message contains invalid Unicode or controls");
    }
  }
  return createInfinityContextError({
    statusCode,
    code,
    message: error.message,
    retryable: spec[1],
    details: root as unknown as JsonObject,
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

function exactObject(value: unknown, keys: readonly string[], path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid(`${path} must be an object`);
  const output = value as Record<string, unknown>;
  if (Object.keys(output).length !== keys.length || keys.some((key) => !Object.hasOwn(output, key))) {
    invalid(`${path} fields do not match the canonical envelope`);
  }
  return output;
}

function invalid(message: string): never {
  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.context_retrieval_contract_invalid",
    message,
    retryable: false,
  });
}
