import { InfinityContextError } from "./errors.js";
import {
  assertUnicodeScalarString,
  compareUtf8,
  pythonTrim,
  unicodeScalarLength,
} from "./retrieval-v2-canonical.js";

export function exactObject(
  value: unknown,
  allowed: readonly string[] | undefined,
  path: string,
  optionalKeys = false,
): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${path} must be an object`);
  const input = value as Record<string, unknown>;
  if (allowed !== undefined) {
    const unknown = Object.keys(input).filter((key) => !allowed.includes(key)).sort(compareUtf8)[0];
    if (unknown !== undefined) fail(`${path}.${unknown} is unsupported`);
    if (!optionalKeys) {
      const missing = allowed.filter((key) => !Object.hasOwn(input, key)).sort(compareUtf8)[0];
      if (missing !== undefined) fail(`${path}.${missing} is required`);
    }
  }
  return input;
}

export function array(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) fail(`${path} must be an array`);
  return value;
}

export function opaqueArray(value: unknown, path: string, maximum = 256): readonly string[] {
  const output = array(value, path).map((item, index) => opaque(item, `${path}.${index}`, maximum));
  if (output.length > 100) fail(`${path} exceeds 100 entries`);
  unique(output, path);
  if (output.some((item, index) => index > 0 && compareUtf8(output[index - 1]!, item) >= 0)) {
    fail(`${path} must be UTF-8 sorted`);
  }
  return freeze(output);
}

export function enumArray<const T extends string>(
  value: unknown,
  choices: readonly T[],
  path: string,
  maximum: number,
): readonly T[] {
  const output = array(value, path).map((item, index) => oneOf(item, choices, `${path}.${index}`));
  if (output.length > maximum) fail(`${path} exceeds ${maximum} entries`);
  return freeze(output);
}

export function nullableOpaque(value: unknown, path: string): string | null {
  return value === null ? null : opaque(value, path);
}

export function opaque(value: unknown, path: string, maximum = 256): string {
  const output = string(value, path);
  if (unicodeScalarLength(output) > maximum) fail(`${path} exceeds ${maximum} characters`);
  return output;
}

export function string(value: unknown, path: string): string {
  if (typeof value !== "string" || unicodeScalarLength(value) === 0 || pythonTrim(value) !== value) {
    fail(`${path} must be a normalized non-blank string`);
  }
  assertUnicodeScalarString(value, path);
  for (const point of value) {
    const codePoint = point.codePointAt(0)!;
    if (codePoint < 0x20 || (codePoint >= 0x7f && codePoint <= 0x9f)) {
      fail(`${path} contains a control character`);
    }
  }
  return value;
}

export function lowerHex(value: unknown, length: number, path: string): string {
  const output = opaque(value, path);
  if (output.length !== length || !/^[0-9a-f]+$/u.test(output)) {
    fail(`${path} must be ${length} lowercase hexadecimal characters`);
  }
  return output;
}

export function timestamp(value: unknown, path: string): string {
  const output = opaque(value, path);
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?Z$/u.exec(output);
  if (match === null) fail(`${path} must be an RFC3339 UTC timestamp`);
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const maximumDay = daysInMonth(year, month);
  if (year < 1 || year > 9999 || maximumDay === 0 || day < 1 || day > maximumDay ||
    Number(hourText) > 23 || Number(minuteText) > 59 || Number(secondText) > 59) {
    fail(`${path} must contain a valid RFC3339 UTC calendar date and time`);
  }
  return output;
}

export function timestampValue(value: string): string {
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?Z$/u.exec(value)!;
  return `${match[1]}${match[2]}${match[3]}${match[4]}${match[5]}${match[6]}${(match[7] ?? "").padEnd(6, "0")}`;
}

export function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) fail(`${path} must be a safe integer`);
  return value;
}

export function boundedInteger(value: unknown, minimum: number, maximum: number, path: string): number {
  const output = integer(value, path);
  if (output < minimum || output > maximum) fail(`${path} must be within ${minimum}..${maximum}`);
  return output;
}

export function nonNegativeSafeInteger(value: unknown, path: string): number {
  return boundedInteger(value, 0, Number.MAX_SAFE_INTEGER, path);
}

export function finite(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(`${path} must be finite`);
  return value;
}

export function positiveFinite(value: unknown, path: string): number {
  const output = finite(value, path);
  if (output <= 0) fail(`${path} must be positive`);
  return output;
}

export function weight(value: unknown, path: string): number {
  const output = finite(value, path);
  if (output < 0.1 || output > 10) fail(`${path} must be within 0.1..10`);
  return output;
}

export function weightMicros(value: unknown, path: string): number {
  return boundedInteger(value, 100_000, 10_000_000, path);
}

export function literal<const T extends string | number>(value: unknown, expected: T, path: string): T {
  if (value !== expected) fail(`${path} must be ${String(expected)}`);
  return expected;
}

export function oneOf<const T extends string | number>(value: unknown, choices: readonly T[], path: string): T {
  if (!choices.includes(value as T)) fail(`${path} is unsupported`);
  return value as T;
}

export function unique(values: readonly string[], path: string): void {
  if (new Set(values).size !== values.length) fail(`${path} must be unique`);
}

export function sortedUnique(values: readonly string[], path: string): void {
  unique(values, path);
  if (values.some((value, index) => index > 0 && compareUtf8(values[index - 1]!, value) >= 0)) {
    fail(`${path} must be sorted`);
  }
}

export function noOverlap(left: readonly string[], right: readonly string[], path: string): void {
  if (left.some((value) => right.includes(value))) fail(`${path} overlap`);
}

export function freeze<T>(value: T): T {
  return Object.freeze(value);
}

export function fail(message: string): never {
  throw new InfinityContextError({
    statusCode: 0,
    code: "memory.context_retrieval_contract_invalid",
    message,
    retryable: false,
  });
}

export function capabilityFail(message: string): never {
  throw new InfinityContextError({
    statusCode: 0,
    code: "memory.context_retrieval_capability_mismatch",
    message,
    retryable: false,
  });
}

function daysInMonth(year: number, month: number): number {
  if (month < 1 || month > 12) return 0;
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}
