import type { JsonValue } from "./types.js";

const MAX_MESSAGE_BYTES = 2_048;
const MAX_CODE_BYTES = 256;
const MAX_REQUEST_ID_BYTES = 512;
const MAX_STACK_BYTES = 4_096;
const MAX_DETAIL_DEPTH = 16;
const MAX_DETAIL_NODES = 256;
const MAX_DETAIL_PROPERTIES = 256;
const MAX_DETAIL_STRING_BYTES = 16_384;
const MAX_DETAIL_KEY_BYTES = 256;
const MAX_DETAIL_BYTES = 16_384;
const MAX_CAUSE_DEPTH = 4;
const REDACTED = "[REDACTED]";
const OMITTED_DETAILS = "[Untrusted details omitted]";
const TRUNCATED = "[Truncated]";
const CIRCULAR = "[Circular]";

type CauseSnapshot =
  | string
  | number
  | boolean
  | null
  | { readonly kind: "external" }
  | { readonly kind: "sdk"; readonly snapshot: ErrorSnapshot };

interface ErrorSnapshot {
  readonly statusCode: number;
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly retryAfterMs?: number | undefined;
  readonly details?: JsonValue | undefined;
  readonly requestId?: string | undefined;
  readonly cause?: CauseSnapshot | undefined;
}

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

const ERROR_SNAPSHOTS = new WeakMap<object, ErrorSnapshot>();
const TRUSTED_OPTIONS = new WeakSet<object>();
const TIMEOUT_REASON = Object.freeze({ kind: "infinity-context-timeout" });
const EXTERNAL_CAUSE = Object.freeze({ name: "Error", message: "External error cause redacted" });

export class InfinityContextError extends Error {
  readonly statusCode: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly retryAfterMs: number | undefined;
  readonly details: JsonValue | undefined;
  readonly requestId: string | undefined;

  constructor(options: InfinityContextErrorOptions) {
    const trusted = TRUSTED_OPTIONS.has(options);
    if (trusted) TRUSTED_OPTIONS.delete(options);
    const snapshot = snapshotOptions(options, trusted);
    super(snapshot.message, snapshot.cause === undefined ? undefined : { cause: materializeCause(snapshot.cause, 0) });
    for (const key of Object.getOwnPropertyNames(this)) {
      if (key !== "message" && key !== "cause" && key !== "stack") Reflect.deleteProperty(this, key);
    }
    this.name = "InfinityContextError";
    this.statusCode = snapshot.statusCode;
    this.code = snapshot.code;
    this.retryable = snapshot.retryable;
    this.retryAfterMs = snapshot.retryAfterMs;
    this.details = snapshot.details;
    this.requestId = snapshot.requestId;
    boundOwnStack(this);
    ERROR_SNAPSHOTS.set(this, snapshot);
    Object.freeze(this);
  }
}

/** Internal SDK construction path. This is intentionally not part of the package exports. */
export function createInfinityContextError(options: InfinityContextErrorOptions): InfinityContextError {
  TRUSTED_OPTIONS.add(options);
  return new InfinityContextError(options);
}

/** Returns a fresh safe SDK-owned error, never the supplied public object. */
export function copyInfinityContextError(value: unknown): InfinityContextError | undefined {
  if (!isWeakKey(value)) return undefined;
  const snapshot = ERROR_SNAPSHOTS.get(value);
  return snapshot === undefined ? undefined : constructFromSnapshot(snapshot);
}

export function timeoutAbortReason(): unknown {
  return TIMEOUT_REASON;
}

export function operationAbortError(cause: unknown): InfinityContextError {
  if (cause === TIMEOUT_REASON) {
    return createInfinityContextError({
      statusCode: 0,
      code: "memory.request_timeout",
      message: "Infinity Context request timed out",
      retryable: true,
      cause,
    });
  }
  return createInfinityContextError({
    statusCode: 0,
    code: "memory.request_aborted",
    message: "Infinity Context request aborted",
    retryable: false,
    cause,
  });
}

export function networkError(cause: unknown): InfinityContextError {
  const branded = copyInfinityContextError(cause);
  if (branded !== undefined) return branded;
  return createInfinityContextError({
    statusCode: 0,
    code: "memory.network_error",
    message: "Infinity Context request failed",
    retryable: true,
    cause,
  });
}

export function responseByteLimitError(statusCode: number, requestId?: string): InfinityContextError {
  return createInfinityContextError({
    statusCode,
    code: "memory.response_byte_limit_exceeded",
    message: "Infinity Context response exceeds the caller byte limit",
    retryable: false,
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

export function redactSensitiveText(value: string): string {
  const bounded = boundUtf8(value, MAX_DETAIL_STRING_BYTES);
  if (bounded === REDACTED) return REDACTED;
  let word = "";
  let wordOverflow = false;
  let previous = "";
  let previousLowerOrDigit = false;
  let sensitive = false;
  const flush = () => {
    if (word.length > 0) {
      const component = wordOverflow ? "" : word.toLowerCase();
      sensitive ||= component === "token" || component === "credential" || component === "secret"
        || component === "passwd" || component === "password" || component === "authorization"
        || component === "apikey" || component === "accesstoken" || component === "refreshtoken"
        || component === "clientsecret" || (previous === "api" && component === "key")
        || ((previous === "access" || previous === "refresh") && component === "token")
        || (previous === "client" && component === "secret");
      previous = component;
    }
    word = "";
    wordOverflow = false;
    previousLowerOrDigit = false;
  };
  for (let index = 0; index < bounded.length; index += 1) {
    const code = bounded.charCodeAt(index);
    const lower = code >= 97 && code <= 122;
    const upper = code >= 65 && code <= 90;
    const digit = code >= 48 && code <= 57;
    if (!lower && !upper && !digit) {
      flush();
      continue;
    }
    if (upper && previousLowerOrDigit) flush();
    if (word.length < 32) word += bounded[index];
    else wordOverflow = true;
    previousLowerOrDigit = lower || digit;
  }
  flush();
  return sensitive || hasAuthPayload(bounded) ? REDACTED : bounded;
}

/** Public compatibility helper: objects fail closed because their origin is not known. */
export function redactJson(value: JsonValue | undefined): JsonValue | undefined {
  return snapshotPublicDetail(value);
}

function constructFromSnapshot(snapshot: ErrorSnapshot): InfinityContextError {
  const options: InfinityContextErrorOptions = {
    statusCode: snapshot.statusCode,
    code: snapshot.code,
    message: snapshot.message,
    retryable: snapshot.retryable,
    ...(snapshot.retryAfterMs !== undefined ? { retryAfterMs: snapshot.retryAfterMs } : {}),
    ...(snapshot.details !== undefined ? { details: snapshot.details } : {}),
    ...(snapshot.requestId !== undefined ? { requestId: snapshot.requestId } : {}),
    ...(snapshot.cause !== undefined ? { cause: materializeCause(snapshot.cause, 0) } : {}),
  };
  TRUSTED_OPTIONS.add(options);
  return new InfinityContextError(options);
}

function snapshotOptions(options: InfinityContextErrorOptions, trusted: boolean): ErrorSnapshot {
  const cause = snapshotCause(options.cause, 0);
  return Object.freeze({
    statusCode: safeNumber(options.statusCode, 0),
    code: safeText(options.code, "memory.unknown_error", MAX_CODE_BYTES),
    message: safeText(options.message, "Infinity Context request failed", MAX_MESSAGE_BYTES),
    retryable: options.retryable === true,
    ...(typeof options.retryAfterMs === "number" && Number.isFinite(options.retryAfterMs)
      ? { retryAfterMs: Math.max(0, Math.trunc(options.retryAfterMs)) } : {}),
    ...(options.details !== undefined
      ? { details: trusted ? snapshotTrustedDetails(options.details) : snapshotPublicDetail(options.details) } : {}),
    ...(typeof options.requestId === "string"
      ? { requestId: safeText(options.requestId, "", MAX_REQUEST_ID_BYTES) } : {}),
    ...(cause !== undefined ? { cause } : {}),
  });
}

function snapshotCause(value: unknown, depth: number): CauseSnapshot | undefined {
  if (value === undefined) return undefined;
  if (typeof value === "string") return safeText(value, "External error cause redacted", MAX_MESSAGE_BYTES);
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return safeNumber(value, 0);
  if (!isWeakKey(value)) return Object.freeze({ kind: "external" });
  const snapshot = ERROR_SNAPSHOTS.get(value);
  if (snapshot === undefined || depth >= MAX_CAUSE_DEPTH) return Object.freeze({ kind: "external" });
  return Object.freeze({ kind: "sdk", snapshot });
}

function materializeCause(snapshot: CauseSnapshot, depth: number): unknown {
  if (typeof snapshot !== "object" || snapshot === null) return snapshot;
  if (snapshot.kind === "external" || depth >= MAX_CAUSE_DEPTH) return EXTERNAL_CAUSE;
  return constructFromSnapshotWithoutCauseOverflow(snapshot.snapshot, depth + 1);
}

function constructFromSnapshotWithoutCauseOverflow(snapshot: ErrorSnapshot, depth: number): InfinityContextError {
  const options: InfinityContextErrorOptions = {
    statusCode: snapshot.statusCode,
    code: snapshot.code,
    message: snapshot.message,
    retryable: snapshot.retryable,
    ...(snapshot.retryAfterMs !== undefined ? { retryAfterMs: snapshot.retryAfterMs } : {}),
    ...(snapshot.details !== undefined ? { details: snapshot.details } : {}),
    ...(snapshot.requestId !== undefined ? { requestId: snapshot.requestId } : {}),
    ...(snapshot.cause !== undefined ? { cause: materializeCause(snapshot.cause, depth) } : {}),
  };
  TRUSTED_OPTIONS.add(options);
  return new InfinityContextError(options);
}

function snapshotPublicDetail(value: JsonValue | undefined): JsonValue | undefined {
  if (value === undefined || value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return safeNumber(value, 0);
  if (typeof value === "string") return safeText(value, "", MAX_DETAIL_STRING_BYTES);
  return OMITTED_DETAILS;
}

function snapshotTrustedDetails(root: JsonValue): JsonValue {
  if (root === null || typeof root !== "object") return snapshotPublicDetail(root) ?? null;
  type DetailSource = readonly (JsonValue | undefined)[] | { readonly [key: string]: JsonValue | undefined };
  type DetailTarget = JsonValue[] | Record<string, JsonValue>;
  type Frame = { source: DetailSource; target: DetailTarget; depth: number };
  const output: JsonValue[] | Record<string, JsonValue> = Array.isArray(root) ? [] : {};
  const seen = new WeakMap<object, DetailTarget>([[root, output]]);
  const sizes = new WeakMap<object, number>([[output, 0]]);
  const frames: Frame[] = [{ source: root, target: output, depth: 0 }];
  const freeze: object[] = [output];
  let nodes = 1;
  // This tracks the exact UTF-8 size of JSON.stringify(output), including
  // property names and structural punctuation. Empty root containers cost 2.
  let detailBytes = 2;
  while (frames.length > 0) {
    const frame = frames.pop()!;
    const visit = (sourceKey: string, readItem: () => JsonValue | undefined): boolean => {
      const sensitive = !Array.isArray(frame.target) && sensitiveDetailKey(sourceKey);
      const key = Array.isArray(frame.target)
        ? sourceKey : safeDetailKey(sourceKey, frame.target, sensitive);
      const assign = (value: JsonValue): boolean => {
        const valueBytes = jsonBytes(value);
        const size = sizes.get(frame.target) ?? 0;
        const separatorBytes = size === 0 ? 0 : 1;
        const propertyBytes = Array.isArray(frame.target) ? 0 : jsonBytes(key) + 1;
        if (detailBytes + separatorBytes + propertyBytes + valueBytes > MAX_DETAIL_BYTES) return false;
        if (Array.isArray(frame.target)) frame.target.push(value);
        else Object.defineProperty(frame.target, key, {
          configurable: true, enumerable: true, writable: true, value,
        });
        sizes.set(frame.target, size + 1);
        detailBytes += separatorBytes + propertyBytes + valueBytes;
        return true;
      };
      if (nodes >= MAX_DETAIL_NODES) {
        frames.length = 0;
        return false;
      }
      if (sensitive) { nodes += 1; return assign(REDACTED); }
      nodes += 1;
      if (frame.depth >= MAX_DETAIL_DEPTH) return assign(TRUNCATED);
      const item = readItem();
      if (typeof item === "string") {
        const value = safeText(item, "", MAX_DETAIL_STRING_BYTES);
        if (assign(value)) return true;
        const fitted = fitJsonString(
          value,
          remainingValueBytes(frame.target, key, detailBytes, sizes.get(frame.target) ?? 0),
        );
        return fitted !== undefined && assign(fitted);
      } else if (item === null || typeof item === "boolean") return assign(item);
      else if (typeof item === "number") return assign(safeNumber(item, 0));
      else if (typeof item === "object") {
        const prior = seen.get(item);
        if (prior !== undefined) return assign(CIRCULAR);
        const child: DetailTarget = Array.isArray(item) ? [] : {};
        if (!assign(child)) return false;
        seen.set(item, child);
        sizes.set(child, 0);
        freeze.push(child);
        frames.push({ source: item, target: child, depth: frame.depth + 1 });
        return true;
      } else return assign(TRUNCATED);
    };

    if (Array.isArray(frame.source)) {
      const count = Math.min(frame.source.length, MAX_DETAIL_PROPERTIES);
      for (let index = 0; index < count; index += 1) {
        if (!visit(String(index), () => frame.source[index])) break;
      }
    } else {
      // Do not materialize an unbounded server object with Object.keys/entries.
      // The iterator is stopped at the global node bound, so property values and
      // descriptors beyond that point are never visited.
      const source = frame.source as { readonly [key: string]: JsonValue | undefined };
      let properties = 0;
      for (const key in source) {
        if (properties >= MAX_DETAIL_PROPERTIES) break;
        if (!Object.hasOwn(source, key)) continue;
        properties += 1;
        if (!visit(key, () => source[key])) break;
      }
    }
  }
  for (let index = freeze.length - 1; index >= 0; index -= 1) Object.freeze(freeze[index]);
  return output;
}

function safeDetailKey(
  source: string,
  target: Record<string, JsonValue>,
  sensitive: boolean,
): string {
  const base = sensitive ? "[REDACTED_KEY]" : boundUtf8(source, MAX_DETAIL_KEY_BYTES);
  if (!Object.hasOwn(target, base)) return base;
  let collision = 2;
  while (collision <= MAX_DETAIL_NODES) {
    const suffix = `_${collision}`;
    const candidate = `${boundUtf8(base, MAX_DETAIL_KEY_BYTES - utf8Length(suffix))}${suffix}`;
    if (!Object.hasOwn(target, candidate)) return candidate;
    collision += 1;
  }
  return `[COLLISION_${collision}]`;
}

function sensitiveDetailKey(value: string): boolean {
  let component = "";
  let overflow = false;
  let previous = "";
  let previousLowerOrDigit = false;
  const flush = (): boolean => {
    if (component.length === 0) return false;
    const current = overflow ? "" : component.toLowerCase();
    const sensitive = current === "token" || current === "credential" || current === "secret"
      || current === "passwd" || current === "password"
      || current === "authorization" || current === "apikey" || current === "accesstoken"
      || current === "refreshtoken" || current === "clientsecret" || current === "basic"
      || current === "bearer" || (previous === "api" && current === "key")
      || ((previous === "access" || previous === "refresh") && current === "token")
      || (previous === "client" && current === "secret");
    previous = current;
    component = "";
    overflow = false;
    previousLowerOrDigit = false;
    return sensitive;
  };
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    const lower = code >= 97 && code <= 122;
    const upper = code >= 65 && code <= 90;
    const digit = code >= 48 && code <= 57;
    if (!lower && !upper && !digit) {
      if (flush()) return true;
      continue;
    }
    if (upper && previousLowerOrDigit && flush()) return true;
    if (component.length < 32) component += value[index];
    else overflow = true;
    previousLowerOrDigit = lower || digit;
  }
  return flush();
}

function jsonBytes(value: JsonValue | string): number {
  const encoded = JSON.stringify(value);
  return encoded === undefined ? 0 : utf8Length(encoded);
}

function remainingValueBytes(
  target: JsonValue[] | Record<string, JsonValue>,
  key: string,
  detailBytes: number,
  size: number,
): number {
  const separatorBytes = size === 0 ? 0 : 1;
  const propertyBytes = Array.isArray(target) ? 0 : jsonBytes(key) + 1;
  return Math.max(0, MAX_DETAIL_BYTES - detailBytes - separatorBytes - propertyBytes);
}

function fitJsonString(value: string, maximumJsonBytes: number): string | undefined {
  if (maximumJsonBytes < 2) return undefined;
  let bytes = 2;
  let end = 0;
  for (const character of value) {
    const characterBytes = jsonBytes(character) - 2;
    if (bytes + characterBytes > maximumJsonBytes) break;
    bytes += characterBytes;
    end += character.length;
  }
  return value.slice(0, end);
}

function safeText(value: unknown, fallback: string, maximumBytes: number): string {
  return typeof value === "string" ? redactSensitiveText(boundUtf8(value, maximumBytes)) : fallback;
}

function boundUtf8(value: string, maximumBytes: number): string {
  if (maximumBytes <= 0 || value.length === 0) return "";
  let bytes = 0;
  let end = 0;
  while (end < value.length) {
    const code = value.charCodeAt(end);
    let units = 1;
    let width = code <= 0x7f ? 1 : code <= 0x7ff ? 2 : 3;
    if (code >= 0xd800 && code <= 0xdbff && end + 1 < value.length) {
      const next = value.charCodeAt(end + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        units = 2;
        width = 4;
      }
    }
    if (bytes + width > maximumBytes) break;
    bytes += width;
    end += units;
  }
  return end === value.length ? value : value.slice(0, end);
}

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function safeNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function sensitiveComponents(value: string): boolean {
  return redactSensitiveText(value) === REDACTED;
}

function hasAuthPayload(value: string): boolean {
  for (let cursor = 0; cursor < value.length; cursor += 1) {
    const remaining = value.slice(cursor, cursor + 6).toLowerCase();
    const component = remaining.startsWith("bearer") ? "bearer"
      : remaining.startsWith("basic") ? "basic" : undefined;
    if (component === undefined) continue;
    let after = cursor + component.length;
    if ((cursor > 0 && /[a-z0-9]/iu.test(value[cursor - 1]))
      || (after < value.length && /[a-z0-9]/iu.test(value[after]))) continue;
    const spacing = after;
    while (value[after] === " " || value[after] === "\t") after += 1;
    if (after > spacing && after < value.length) return true;
  }
  return false;
}

function isWeakKey(value: unknown): value is object {
  return (typeof value === "object" && value !== null) || typeof value === "function";
}

function boundOwnStack(error: InfinityContextError): void {
  const descriptor = Object.getOwnPropertyDescriptor(error, "stack");
  const raw = descriptor !== undefined && "value" in descriptor && typeof descriptor.value === "string"
    ? descriptor.value : `${error.name}: ${error.message}`;
  Object.defineProperty(error, "stack", {
    configurable: false,
    enumerable: false,
    writable: false,
    value: safeText(raw, `${error.name}: ${error.message}`, MAX_STACK_BYTES),
  });
}
