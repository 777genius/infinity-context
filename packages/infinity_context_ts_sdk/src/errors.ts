import type { JsonValue } from "./types.js";

const SENSITIVE_KEY_COMPONENTS = [
  "apikey",
  "token",
  "secret",
  "password",
  "passwd",
  "credential",
  "authorization",
  "bearer",
] as const;

const TEXTUAL_ASSIGNMENT_PATTERN = /(?:(["'])([^"'\\]*(?:\\.[^"'\\]*)*)\1|\b([A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*|(?:api|access|refresh) +(?:key|token)))\s*[=:]\s*/gi;
const AUTH_SCHEME_VALUE_PATTERN = /^(?:Basic|Bearer)\s+[A-Za-z0-9._~+/=-]+/i;
const STANDALONE_AUTH_PATTERN = /\b(Basic|Bearer)(\s+)[A-Za-z0-9._~+/=-]+/gi;

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
    const cause = sanitizeErrorCause(options.cause);
    super(message, cause !== undefined ? { cause } : undefined);
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
  return redactSensitiveAssignments(value)
    .replace(STANDALONE_AUTH_PATTERN, "$1$2[REDACTED]");
}

export function redactJson(value: JsonValue | undefined): JsonValue | undefined {
  if (typeof value === "string") {
    return redactSensitiveText(value);
  }
  if (value === undefined || value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactJson(item) ?? null);
  }
  const output: Record<string, JsonValue | undefined> = {};
  for (const [key, item] of Object.entries(value)) {
    output[key] = isSensitiveKey(key)
      ? "[REDACTED]"
      : redactJson(item);
  }
  return output;
}

function sanitizeErrorCause(cause: unknown): unknown {
  if (isSafeCauseGraph(cause)) return cause;
  return sanitizeUnsafeCause(cause, new WeakMap<object, Error>(), 0);
}

function isSafeCauseGraph(
  cause: unknown,
  checked = new WeakSet<object>(),
  depth = 0,
): boolean {
  if (cause === undefined || cause === null || typeof cause === "number" || typeof cause === "boolean") {
    return true;
  }
  if (typeof cause === "string") return redactSensitiveText(cause) === cause;
  if (!(cause instanceof Error) || depth >= 100) return false;
  if (checked.has(cause)) return true;
  checked.add(cause);
  if (redactSensitiveText(cause.message) !== cause.message
    || redactSensitiveText(cause.name) !== cause.name) {
    return false;
  }
  return Object.getOwnPropertyNames(cause).every((key) => {
    if (isSensitiveKey(key)) return false;
    const descriptor = Object.getOwnPropertyDescriptor(cause, key);
    if (descriptor === undefined) return false;
    if (!("value" in descriptor)) {
      if (key !== "stack") return false;
      try {
        return cause.stack === undefined || redactSensitiveText(cause.stack) === cause.stack;
      } catch {
        return false;
      }
    }
    return isSafeCauseProperty(descriptor.value, checked, depth + 1);
  })
    && Object.getOwnPropertySymbols(cause).length === 0
    && (!("cause" in cause) || Object.hasOwn(cause, "cause"));
}

function isSafeCauseProperty(value: unknown, checked: WeakSet<object>, depth: number): boolean {
  if (value === undefined || value === null || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (typeof value === "string") return redactSensitiveText(value) === value;
  if (value instanceof Error) return isSafeCauseGraph(value, checked, depth);
  if (typeof value !== "object" || depth >= 100) return false;
  if (checked.has(value)) return true;
  checked.add(value);
  if (Object.getOwnPropertySymbols(value).length > 0) return false;
  return Object.getOwnPropertyNames(value).every((key) => {
    if (isSensitiveKey(key)) return false;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor !== undefined
      && "value" in descriptor
      && isSafeCauseProperty(descriptor.value, checked, depth + 1);
  });
}

function isSensitiveKey(key: string): boolean {
  const separated = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .toLowerCase();
  const components = separated.split(/[^a-z0-9]+/).filter((part) => part.length > 0);
  const normalized = components.join("");
  return components.some((component) => (
    SENSITIVE_KEY_COMPONENTS.some((sensitive) => component === sensitive)
  )) || SENSITIVE_KEY_COMPONENTS.some((sensitive) => normalized.endsWith(sensitive));
}

function redactSensitiveAssignments(value: string): string {
  let output = "";
  let copiedThrough = 0;
  TEXTUAL_ASSIGNMENT_PATTERN.lastIndex = 0;
  for (let match = TEXTUAL_ASSIGNMENT_PATTERN.exec(value); match !== null;
    match = TEXTUAL_ASSIGNMENT_PATTERN.exec(value)) {
    const key = match[2] ?? match[3] ?? "";
    if (!isSensitiveKey(key)) continue;
    const valueStart = TEXTUAL_ASSIGNMENT_PATTERN.lastIndex;
    const consumed = consumeAssignedValue(value, valueStart);
    if (consumed === undefined) continue;
    output += value.slice(copiedThrough, match.index) + match[0] + consumed.replacement;
    copiedThrough = consumed.end;
    TEXTUAL_ASSIGNMENT_PATTERN.lastIndex = consumed.end;
  }
  return output + value.slice(copiedThrough);
}

function consumeAssignedValue(
  value: string,
  start: number,
): { readonly end: number; readonly replacement: string } | undefined {
  const quote = value[start];
  if (quote === "\"" || quote === "'") {
    let cursor = start + 1;
    while (cursor < value.length) {
      if (value[cursor] === "\\") {
        cursor = Math.min(cursor + 2, value.length);
      } else if (value[cursor] === quote) {
        return { end: cursor + 1, replacement: `${quote}[REDACTED]${quote}` };
      } else {
        cursor += 1;
      }
    }
    return { end: value.length, replacement: `${quote}[REDACTED]` };
  }

  const authValue = AUTH_SCHEME_VALUE_PATTERN.exec(value.slice(start));
  if (authValue !== null) {
    return { end: start + authValue[0].length, replacement: "[REDACTED]" };
  }
  let end = start;
  while (end < value.length && !/[\s&;,}\]]/.test(value[end] ?? "")) end += 1;
  return end === start ? undefined : { end, replacement: "[REDACTED]" };
}

function sanitizeUnsafeCause(
  cause: unknown,
  clones: WeakMap<object, Error>,
  depth: number,
): unknown {
  if (cause === undefined) return undefined;
  if (typeof cause === "string") return redactSensitiveText(cause).slice(0, 500);
  if (cause === null || typeof cause === "number" || typeof cause === "boolean") return cause;
  if (!(cause instanceof Error)) return undefined;
  if (depth >= 100) return new Error("Nested error cause omitted");
  const existing = clones.get(cause);
  if (existing !== undefined) return existing;
  if (isSafeCauseGraph(cause)) return cause;

  const sanitized = new Error(redactSensitiveText(cause.message).slice(0, 500));
  clones.set(cause, sanitized);
  sanitized.name = redactSensitiveText(cause.name).slice(0, 100);
  const causeDescriptor = Object.getOwnPropertyDescriptor(cause, "cause");
  const nested = causeDescriptor !== undefined && "value" in causeDescriptor
    ? sanitizeUnsafeCause(causeDescriptor.value, clones, depth + 1)
    : undefined;
  if (nested !== undefined) {
    Object.defineProperty(sanitized, "cause", {
      configurable: true,
      writable: true,
      value: nested,
    });
  }
  return sanitized;
}
