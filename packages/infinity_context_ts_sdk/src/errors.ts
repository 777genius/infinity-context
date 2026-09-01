import type { JsonValue } from "./types.js";

const SENSITIVE_KEY_MARKERS = [
  "api_key",
  "apikey",
  "token",
  "secret",
  "password",
  "passwd",
  "credential",
  "authorization",
  "bearer",
] as const;

export interface InfinityContextErrorOptions {
  readonly statusCode: number;
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly retryAfterMs?: number | undefined;
  readonly details?: JsonValue | undefined;
  readonly requestId?: string | undefined;
  readonly cause?: unknown;
}

export class InfinityContextError extends Error {
  readonly statusCode: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly retryAfterMs: number | undefined;
  readonly details: JsonValue | undefined;
  readonly requestId: string | undefined;

  constructor(options: InfinityContextErrorOptions) {
    const message = redactSensitiveText(options.message).slice(0, 500);
    super(message, options.cause !== undefined ? { cause: options.cause } : undefined);
    this.name = "InfinityContextError";
    this.statusCode = options.statusCode;
    this.code = options.code;
    this.retryable = options.retryable;
    this.retryAfterMs = options.retryAfterMs;
    this.details = redactJson(options.details);
    this.requestId = options.requestId;
  }
}

export function operationAbortError(cause: unknown): InfinityContextError {
  if (errorName(cause) === "TimeoutError") {
    return networkError(cause);
  }
  const message = cause instanceof Error
    ? cause.message
    : typeof cause === "string" && cause.length > 0
      ? cause
      : "Infinity Context request aborted";
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.request_aborted",
    message,
    retryable: false,
    cause,
  });
}

export function networkError(cause: unknown): InfinityContextError {
  const name = errorName(cause);
  if (name === "TimeoutError") {
    return new InfinityContextError({
      statusCode: 0,
      code: "memory.request_timeout",
      message: cause instanceof Error ? cause.message : "Infinity Context request timed out",
      retryable: true,
      cause,
    });
  }
  if (name === "AbortError") {
    return new InfinityContextError({
      statusCode: 0,
      code: "memory.request_aborted",
      message: cause instanceof Error ? cause.message : "Infinity Context request aborted",
      retryable: false,
      cause,
    });
  }
  const message = cause instanceof Error ? cause.message : "Infinity Context request failed";
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.network_error",
    message,
    retryable: true,
    cause,
  });
}

export function responseByteLimitError(statusCode: number, requestId?: string): InfinityContextError {
  return new InfinityContextError({
    statusCode,
    code: "memory.response_byte_limit_exceeded",
    message: "Infinity Context response exceeds the caller byte limit",
    retryable: false,
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

function errorName(cause: unknown): string | undefined {
  return typeof cause === "object" && cause !== null && "name" in cause
    ? String((cause as { readonly name?: unknown }).name)
    : undefined;
}

export function redactSensitiveText(value: string): string {
  return value
    .replace(/(authorization:\s*)(?:bearer\s+)?[A-Za-z0-9._~+/=-]+/gi, "$1[REDACTED]")
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/([?&](?:token|api_key|apikey|secret|password)=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/(authorization:\s*)[^\n\r\s]+/gi, "$1[REDACTED]");
}

export function redactJson(value: JsonValue | undefined): JsonValue | undefined {
  if (value === undefined || value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactJson(item) ?? null);
  }
  const output: Record<string, JsonValue | undefined> = {};
  for (const [key, item] of Object.entries(value)) {
    const normalized = key.toLowerCase();
    output[key] = SENSITIVE_KEY_MARKERS.some((marker) => normalized.includes(marker))
      ? "[REDACTED]"
      : redactJson(item);
  }
  return output;
}
