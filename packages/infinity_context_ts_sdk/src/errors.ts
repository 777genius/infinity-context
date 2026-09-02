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

const NATIVE_ERROR_PROTOTYPES = new Map<object, string>([
  [Error.prototype, "Error"],
  [EvalError.prototype, "EvalError"],
  [RangeError.prototype, "RangeError"],
  [ReferenceError.prototype, "ReferenceError"],
  [SyntaxError.prototype, "SyntaxError"],
  [TypeError.prototype, "TypeError"],
  [URIError.prototype, "URIError"],
]);
const NATIVE_STACK_ACCESSOR = Object.getOwnPropertyDescriptor(new Error(), "stack");

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
  if (safeErrorName(cause) === "TimeoutError") return networkError(cause);
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.request_aborted",
    message: safeErrorMessage(cause) ?? safeStringCause(cause) ?? "Infinity Context request aborted",
    retryable: false,
    cause,
  });
}

export function networkError(cause: unknown): InfinityContextError {
  const name = safeErrorName(cause);
  if (name === "TimeoutError") {
    return new InfinityContextError({
      statusCode: 0,
      code: "memory.request_timeout",
      message: safeErrorMessage(cause) ?? "Infinity Context request timed out",
      retryable: true,
      cause,
    });
  }
  if (name === "AbortError") {
    return new InfinityContextError({
      statusCode: 0,
      code: "memory.request_aborted",
      message: safeErrorMessage(cause) ?? "Infinity Context request aborted",
      retryable: false,
      cause,
    });
  }
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.network_error",
    message: safeErrorMessage(cause) ?? "Infinity Context request failed",
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

export function redactSensitiveText(value: string): string {
  let output = "";
  let cursor = 0;
  while (cursor < value.length) {
    const assignment = scanAssignment(value, cursor);
    if (assignment !== undefined && isSensitiveKey(assignment.key)) {
      const assigned = scanAssignedValue(value, assignment.valueStart);
      if (assigned !== undefined) {
        output += value.slice(cursor, assignment.valueStart) + assigned.replacement;
        cursor = assigned.end;
        continue;
      }
    }
    const auth = scanAuthAtom(value, cursor);
    if (auth !== undefined) {
      output += auth.scheme + auth.spacing + "[REDACTED]";
      cursor = auth.end;
      continue;
    }
    output += value[cursor];
    cursor += 1;
  }
  return output;
}

export function redactJson(value: JsonValue | undefined): JsonValue | undefined {
  if (typeof value === "string") return redactSensitiveText(value);
  if (value === undefined || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((item) => redactJson(item) ?? null);
  const output: Record<string, JsonValue | undefined> = {};
  for (const [key, item] of Object.entries(value)) {
    output[key] = isSensitiveKey(key) ? "[REDACTED]" : redactJson(item);
  }
  return output;
}

function scanAssignment(
  value: string,
  start: number,
): { readonly key: string; readonly valueStart: number } | undefined {
  if (start > 0 && isIdentifierCharacter(value[start - 1])) return undefined;
  let key: string;
  let cursor: number;
  const delimiter = quoteDelimiterAt(value, start);
  if (delimiter !== undefined) {
    const closing = value.indexOf(delimiter, start + delimiter.length);
    if (closing < 0) return undefined;
    key = value.slice(start + delimiter.length, closing);
    cursor = closing + delimiter.length;
  } else {
    cursor = start;
    while (cursor < value.length && isIdentifierCharacter(value[cursor])) cursor += 1;
    if (cursor === start) return undefined;
    key = value.slice(start, cursor);
    if (/^(?:api|access|refresh)$/i.test(key)) {
      const spaceStart = cursor;
      while (isHorizontalSpace(value[cursor])) cursor += 1;
      const suffixStart = cursor;
      while (isAlphaNumeric(value[cursor])) cursor += 1;
      const suffix = value.slice(suffixStart, cursor);
      if (/^(?:key|token|secret)$/i.test(suffix)) key += value.slice(spaceStart, cursor);
      else cursor = spaceStart;
    }
  }
  while (isHorizontalSpace(value[cursor])) cursor += 1;
  if (value[cursor] !== "=" && value[cursor] !== ":") return undefined;
  cursor += 1;
  while (isHorizontalSpace(value[cursor])) cursor += 1;
  return { key, valueStart: cursor };
}

function scanAssignedValue(
  value: string,
  start: number,
): { readonly end: number; readonly replacement: string } | undefined {
  const delimiter = quoteDelimiterAt(value, start);
  if (delimiter !== undefined) {
    const closing = findClosingQuote(value, start + delimiter.length, delimiter);
    return closing < 0
      ? { end: value.length, replacement: `${delimiter}[REDACTED]` }
      : { end: closing + delimiter.length, replacement: `${delimiter}[REDACTED]${delimiter}` };
  }

  if (value[start] === "(") {
    let inner = start + 1;
    while (isHorizontalSpace(value[inner])) inner += 1;
    const auth = scanAuthAtom(value, inner, false);
    if (auth !== undefined) {
      let end = auth.end;
      while (isHorizontalSpace(value[end])) end += 1;
      if (value[end] === ")") end += 1;
      return { end, replacement: "([REDACTED])" };
    }
  }

  const auth = scanAuthAtom(value, start, false);
  if (auth !== undefined) return { end: auth.end, replacement: "[REDACTED]" };
  let end = start;
  while (end < value.length && !isAssignmentBoundary(value[end])) end += 1;
  return end === start ? undefined : { end, replacement: "[REDACTED]" };
}

function scanAuthAtom(
  value: string,
  start: number,
  requireBoundary = true,
): { readonly end: number; readonly scheme: string; readonly spacing: string } | undefined {
  if (requireBoundary && start > 0 && isAlphaNumeric(value[start - 1])) return undefined;
  const scheme = value.slice(start, start + 6).toLowerCase() === "bearer"
    ? value.slice(start, start + 6)
    : value.slice(start, start + 5).toLowerCase() === "basic"
      ? value.slice(start, start + 5)
      : undefined;
  if (scheme === undefined) return undefined;
  let cursor = start + scheme.length;
  const spacingStart = cursor;
  while (isHorizontalSpace(value[cursor])) cursor += 1;
  if (cursor === spacingStart) return undefined;
  const tokenStart = cursor;
  while (isAuthTokenCharacter(value[cursor])) cursor += 1;
  if (cursor === tokenStart) return undefined;
  return { end: cursor, scheme, spacing: value.slice(spacingStart, tokenStart) };
}

function quoteDelimiterAt(value: string, start: number): "\"" | "'" | "\\\"" | "\\'" | undefined {
  if (value[start] === "\"" || value[start] === "'") return value[start] as "\"" | "'";
  if (value[start] === "\\" && (value[start + 1] === "\"" || value[start + 1] === "'")) {
    return value.slice(start, start + 2) as "\\\"" | "\\'";
  }
  return undefined;
}

function findClosingQuote(value: string, start: number, delimiter: string): number {
  if (delimiter.length === 2) return value.indexOf(delimiter, start);
  let cursor = start;
  while (cursor < value.length) {
    if (value[cursor] === "\\") cursor += 2;
    else if (value[cursor] === delimiter) return cursor;
    else cursor += 1;
  }
  return -1;
}

function isSensitiveKey(key: string): boolean {
  const separated = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .toLowerCase();
  const components = separated.split(/[^a-z0-9]+/).filter((part) => part.length > 0);
  const normalized = components.join("");
  return components.some((component) => SENSITIVE_KEY_COMPONENTS.includes(
    component as typeof SENSITIVE_KEY_COMPONENTS[number],
  )) || SENSITIVE_KEY_COMPONENTS.some((sensitive) => normalized.endsWith(sensitive));
}

function isAlphaNumeric(value: string | undefined): boolean {
  return value !== undefined && /[A-Za-z0-9]/.test(value);
}

function isIdentifierCharacter(value: string | undefined): boolean {
  return value !== undefined && /[A-Za-z0-9._-]/.test(value);
}

function isHorizontalSpace(value: string | undefined): boolean {
  return value === " " || value === "\t";
}

function isAuthTokenCharacter(value: string | undefined): boolean {
  return value !== undefined && /[A-Za-z0-9._~+/=-]/.test(value);
}

function isAssignmentBoundary(value: string | undefined): boolean {
  return value === undefined || /[\s&;,!?}\])]/.test(value);
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
  if (typeof cause !== "object" || depth >= 100 || !isExactNativeError(cause)) return false;
  if (checked.has(cause)) return true;
  checked.add(cause);
  const message = safeErrorMessage(cause);
  const name = safeErrorName(cause);
  if (message === undefined || name === undefined
    || redactSensitiveText(message) !== message || redactSensitiveText(name) !== name) return false;
  return safeOwnDescriptors(cause).every(([key, descriptor]) => {
    if (isSensitiveKey(key)) return false;
    if (!("value" in descriptor)) return isNativeStackAccessor(key, descriptor);
    return isSafeCauseProperty(descriptor.value, checked, depth + 1);
  }) && safeOwnSymbols(cause).length === 0;
}

function isSafeCauseProperty(value: unknown, checked: WeakSet<object>, depth: number): boolean {
  if (value === undefined || value === null || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (typeof value === "string") return redactSensitiveText(value) === value;
  if (typeof value !== "object" || depth >= 100) return false;
  if (isErrorObject(value)) return isSafeCauseGraph(value, checked, depth);
  if (checked.has(value)) return true;
  const prototype = safePrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null && !Array.isArray(value)) return false;
  checked.add(value);
  return safeOwnSymbols(value).length === 0 && safeOwnDescriptors(value).every(([key, descriptor]) => (
    !isSensitiveKey(key)
    && "value" in descriptor
    && isSafeCauseProperty(descriptor.value, checked, depth + 1)
  ));
}

function sanitizeUnsafeCause(
  cause: unknown,
  clones: WeakMap<object, Error>,
  depth: number,
): unknown {
  if (cause === undefined) return undefined;
  if (typeof cause === "string") return redactSensitiveText(cause).slice(0, 500);
  if (cause === null || typeof cause === "number" || typeof cause === "boolean") return cause;
  if (typeof cause !== "object" || !isErrorObject(cause)) return undefined;
  if (depth >= 100) return new Error("Nested error cause omitted");
  const existing = clones.get(cause);
  if (existing !== undefined) return existing;
  if (isSafeCauseGraph(cause)) return cause;

  const sanitized = new Error(redactSensitiveText(safeErrorMessage(cause) ?? "Error cause omitted").slice(0, 500));
  clones.set(cause, sanitized);
  sanitized.name = redactSensitiveText(safeErrorName(cause) ?? "Error").slice(0, 100);
  const causeDescriptor = safeOwnDescriptor(cause, "cause");
  const nested = causeDescriptor !== undefined && "value" in causeDescriptor
    ? sanitizeUnsafeCause(causeDescriptor.value, clones, depth + 1)
    : undefined;
  if (nested !== undefined) {
    Object.defineProperty(sanitized, "cause", { configurable: true, writable: true, value: nested });
  }
  return sanitized;
}

function safeErrorName(value: unknown): string | undefined {
  if (typeof value !== "object" || value === null || !isErrorObject(value)) return undefined;
  const own = safeOwnString(value, "name");
  if (own !== undefined) return own;
  const prototype = safePrototypeOf(value);
  const nativeName = prototype === undefined ? undefined : NATIVE_ERROR_PROTOTYPES.get(prototype);
  if (nativeName !== undefined) return nativeName;
  if (isExactDomException(value)) return callNativeDomStringGetter(value, "name");
  return undefined;
}

function safeErrorMessage(value: unknown): string | undefined {
  if (typeof value !== "object" || value === null || !isErrorObject(value)) return undefined;
  const own = safeOwnString(value, "message");
  if (own !== undefined) return own;
  if (isExactNativeError(value)) {
    return isExactDomException(value) ? callNativeDomStringGetter(value, "message") : "";
  }
  return undefined;
}

function safeStringCause(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function isErrorObject(value: object): boolean {
  let prototype = safePrototypeOf(value);
  while (prototype !== undefined && prototype !== null) {
    if (NATIVE_ERROR_PROTOTYPES.has(prototype) || prototype === domExceptionPrototype()) return true;
    prototype = safePrototypeOf(prototype);
  }
  return false;
}

function isExactNativeError(value: object): boolean {
  const prototype = safePrototypeOf(value);
  return prototype !== undefined
    && (NATIVE_ERROR_PROTOTYPES.has(prototype) || prototype === domExceptionPrototype());
}

function isExactDomException(value: object): boolean {
  return safePrototypeOf(value) === domExceptionPrototype();
}

function domExceptionPrototype(): object | undefined {
  return typeof DOMException === "undefined" ? undefined : DOMException.prototype;
}

function callNativeDomStringGetter(value: object, key: "name" | "message"): string | undefined {
  const prototype = domExceptionPrototype();
  if (prototype === undefined) return undefined;
  const getter = Object.getOwnPropertyDescriptor(prototype, key)?.get;
  if (getter === undefined) return undefined;
  try {
    const result: unknown = Reflect.apply(getter, value, []);
    return typeof result === "string" ? result : undefined;
  } catch {
    return undefined;
  }
}

function safeOwnString(value: object, key: string): string | undefined {
  const descriptor = safeOwnDescriptor(value, key);
  return descriptor !== undefined && "value" in descriptor && typeof descriptor.value === "string"
    ? descriptor.value
    : undefined;
}

function isNativeStackAccessor(key: string, descriptor: PropertyDescriptor): boolean {
  return key === "stack"
    && NATIVE_STACK_ACCESSOR !== undefined
    && descriptor.get === NATIVE_STACK_ACCESSOR.get
    && descriptor.set === NATIVE_STACK_ACCESSOR.set;
}

function safeOwnDescriptor(value: object, key: string): PropertyDescriptor | undefined {
  try {
    return Object.getOwnPropertyDescriptor(value, key);
  } catch {
    return undefined;
  }
}

function safeOwnDescriptors(value: object): ReadonlyArray<readonly [string, PropertyDescriptor]> {
  try {
    return Object.getOwnPropertyNames(value).map(
      (key): readonly [string, PropertyDescriptor] => [key, Object.getOwnPropertyDescriptor(value, key)!],
    );
  } catch {
    return [["<uninspectable>", {}]];
  }
}

function safeOwnSymbols(value: object): readonly symbol[] {
  try {
    return Object.getOwnPropertySymbols(value);
  } catch {
    return [Symbol("uninspectable")];
  }
}

function safePrototypeOf(value: object): object | null | undefined {
  try {
    return Object.getPrototypeOf(value) as object | null;
  } catch {
    return undefined;
  }
}
