import { ValueError } from "./payload.js";

export const SHA256_PATTERN = /^[0-9a-f]{64}$/u;

export function requireAllowedKeys(value: object, allowed: readonly string[], label: string): void {
  const permitted = new Set(allowed);
  const unexpected = Object.keys(value).filter((key) => !permitted.has(key));
  if (unexpected.length > 0) {
    throw new ValueError(`${label} contains unsupported field(s): ${unexpected.join(", ")}`);
  }
}

export function requireString(value: unknown, label: string, minimum = 1, maximum?: number): asserts value is string {
  if (typeof value !== "string" || value.length < minimum || (maximum !== undefined && value.length > maximum)) {
    throw new ValueError(`${label} must be a string between ${minimum} and ${maximum ?? "unbounded"} characters`);
  }
}

export function optionalString(value: unknown, label: string, minimum = 1, maximum?: number): void {
  if (value !== undefined) requireString(value, label, minimum, maximum);
}

export function requireSha256(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new ValueError(`${label} must be a lowercase SHA-256 digest`);
  }
}

export function requireInteger(value: unknown, label: string, minimum: number, maximum?: number): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (maximum !== undefined && (value as number) > maximum)) {
    throw new ValueError(`${label} must be an integer between ${minimum} and ${maximum ?? "unbounded"}`);
  }
}

export function requireEnum<T extends string>(value: unknown, allowed: readonly T[], label: string): asserts value is T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw new ValueError(`${label} must be one of: ${allowed.join(", ")}`);
  }
}

export function requireArray<T>(value: readonly T[], label: string, minimum: number, maximum: number): void {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) {
    throw new ValueError(`${label} must contain between ${minimum} and ${maximum} items`);
  }
}

export function requireAwareDateTime(value: unknown, label: string): asserts value is string {
  requireString(value, label);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/u.test(value) || Number.isNaN(Date.parse(value))) {
    throw new ValueError(`${label} must be an RFC 3339 datetime with timezone`);
  }
}

export function requireJsonObject(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ValueError(`${label} must be a JSON object`);
  }
}
