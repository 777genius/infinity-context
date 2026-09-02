import { createInfinityContextError, InfinityContextError } from "./errors.js";
import { assertUnicodeScalarString, compareUtf8, pythonTrim } from "./retrieval-canonical.js";
import type { JsonObject } from "./types.js";

export const DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1 = "document-retrieval-projection.v1" as const;

export interface DocumentRetrievalProjectionTimeIntervalV1Input {
  readonly startAt: string;
  readonly endAt: string;
}

export interface DocumentRetrievalProjectionRelativeTimeIntervalV1Input {
  readonly startMs: number;
  readonly endMs: number;
}

export interface DocumentRetrievalProjectionV1Input {
  readonly schemaVersion: typeof DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1;
  readonly locator: string;
  readonly sourceKey: string;
  readonly projectionGeneration: string;
  readonly sequenceOrdinal: number;
  readonly actorKeys: readonly string[];
  readonly timeInterval: DocumentRetrievalProjectionTimeIntervalV1Input | null;
  readonly relativeTimeInterval: DocumentRetrievalProjectionRelativeTimeIntervalV1Input | null;
  readonly kind: string;
  readonly category: string;
  readonly tags: readonly string[];
}

export function documentRetrievalProjectionV1Payload(value: unknown): JsonObject {
  const input = exactObject(value, [
    "schemaVersion", "locator", "sourceKey", "projectionGeneration", "sequenceOrdinal",
    "actorKeys", "timeInterval", "relativeTimeInterval", "kind", "category", "tags",
  ], "retrievalProjection");
  if (input.schemaVersion !== DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1) invalid("retrievalProjection.schemaVersion is unsupported");
  return Object.freeze({
    schema_version: DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1,
    locator: opaque(input.locator, "retrievalProjection.locator"),
    source_key: opaque(input.sourceKey, "retrievalProjection.sourceKey"),
    projection_generation: opaque(input.projectionGeneration, "retrievalProjection.projectionGeneration"),
    sequence_ordinal: boundedInteger(input.sequenceOrdinal, 0, 2_147_483_647, "retrievalProjection.sequenceOrdinal"),
    actor_keys: sortedStrings(input.actorKeys, "retrievalProjection.actorKeys"),
    time_interval: absoluteInterval(input.timeInterval),
    relative_time_interval: relativeInterval(input.relativeTimeInterval),
    kind: opaque(input.kind, "retrievalProjection.kind"),
    category: opaque(input.category, "retrievalProjection.category"),
    tags: sortedStrings(input.tags, "retrievalProjection.tags"),
  }) as JsonObject;
}

function exactObject(value: unknown, keys: readonly string[], path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid(`${path} must be an object`);
  const input = value as Record<string, unknown>;
  if (Object.keys(input).length !== keys.length || keys.some((key) => !Object.hasOwn(input, key))) {
    invalid(`${path} must contain exactly the canonical fields`);
  }
  return input;
}

function opaque(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0 || pythonTrim(value) !== value || [...value].length > 256) {
    invalid(`${path} must be a normalized non-blank string of at most 256 code points`);
  }
  try {
    assertUnicodeScalarString(value, path);
  } catch {
    invalid(`${path} contains a malformed Unicode surrogate`);
  }
  for (const point of value) {
    const code = point.codePointAt(0)!;
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) invalid(`${path} contains a control character`);
  }
  return value;
}

function sortedStrings(value: unknown, path: string): readonly string[] {
  if (!Array.isArray(value) || value.length > 100) invalid(`${path} must contain at most 100 entries`);
  const result = value.map((item, index) => opaque(item, `${path}.${index}`));
  if (new Set(result).size !== result.length || result.some((item, index) => index > 0 && compareUtf8(result[index - 1]!, item) >= 0)) {
    invalid(`${path} must be UTF-8 sorted and unique`);
  }
  return Object.freeze(result);
}

function absoluteInterval(value: unknown): JsonObject | null {
  if (value === null) return null;
  const input = exactObject(value, ["startAt", "endAt"], "retrievalProjection.timeInterval");
  const start = timestamp(input.startAt, "retrievalProjection.timeInterval.startAt");
  const end = timestamp(input.endAt, "retrievalProjection.timeInterval.endAt");
  if (timestampOrder(start) > timestampOrder(end)) invalid("retrievalProjection.timeInterval must be ordered");
  return Object.freeze({ start_at: start, end_at: end });
}

function relativeInterval(value: unknown): JsonObject | null {
  if (value === null) return null;
  const input = exactObject(value, ["startMs", "endMs"], "retrievalProjection.relativeTimeInterval");
  const start = boundedInteger(input.startMs, 0, Number.MAX_SAFE_INTEGER, "retrievalProjection.relativeTimeInterval.startMs");
  const end = boundedInteger(input.endMs, 0, Number.MAX_SAFE_INTEGER, "retrievalProjection.relativeTimeInterval.endMs");
  if (start > end) invalid("retrievalProjection.relativeTimeInterval must be ordered");
  return Object.freeze({ start_ms: start, end_ms: end });
}

function timestamp(value: unknown, path: string): string {
  const output = opaque(value, path);
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?Z$/u.exec(output);
  if (match === null) invalid(`${path} must be RFC3339 UTC using Z`);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const maximumDay = month === 2 ? (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28)
    : [4, 6, 9, 11].includes(month) ? 30 : month >= 1 && month <= 12 ? 31 : 0;
  if (year < 1 || day < 1 || day > maximumDay || Number(match[4]) > 23 || Number(match[5]) > 59 || Number(match[6]) > 59) {
    invalid(`${path} must contain a valid calendar date and time`);
  }
  return output;
}

function timestampOrder(value: string): string {
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?Z$/u.exec(value)!;
  return `${match[1]}${match[2]}${match[3]}${match[4]}${match[5]}${match[6]}${(match[7] ?? "").padEnd(6, "0")}`;
}

function boundedInteger(value: unknown, minimum: number, maximum: number, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    invalid(`${path} must be an integer within ${minimum}..${maximum}`);
  }
  return value;
}

function invalid(message: string): never {
  throw createInfinityContextError({ statusCode: 0, code: "memory.document_projection_invalid", message, retryable: false });
}
