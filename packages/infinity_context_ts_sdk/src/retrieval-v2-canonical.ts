import { InfinityContextError } from "./errors.js";
import type { ContextRetrievalCapabilityV2 } from "./retrieval-v2-types.js";

const encoder = new TextEncoder();

export function assertUnicodeScalarString(value: string, path: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) canonicalInvalid(`${path} contains a malformed Unicode surrogate`);
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      canonicalInvalid(`${path} contains a malformed Unicode surrogate`);
    }
  }
}

export function utf8Bytes(value: string, path = "value"): Uint8Array {
  assertUnicodeScalarString(value, path);
  return encoder.encode(value);
}

export function compareUtf8(left: string, right: string): number {
  const leftBytes = utf8Bytes(left);
  const rightBytes = utf8Bytes(right);
  const length = Math.min(leftBytes.length, rightBytes.length);
  for (let index = 0; index < length; index += 1) {
    if (leftBytes[index] !== rightBytes[index]) return leftBytes[index]! - rightBytes[index]!;
  }
  return leftBytes.length - rightBytes.length;
}

export function unicodeScalarLength(value: string): number {
  assertUnicodeScalarString(value, "value");
  let length = 0;
  for (const _point of value) length += 1;
  return length;
}

export function normalizePythonWhitespace(value: string): string {
  const words: string[] = [];
  let word = "";
  for (const point of value) {
    if (isPythonWhitespace(point.codePointAt(0)!)) {
      if (word !== "") { words.push(word); word = ""; }
    } else word += point;
  }
  if (word !== "") words.push(word);
  return words.join(" ");
}

export function pythonTrim(value: string): string {
  const points = [...value];
  let start = 0;
  let end = points.length;
  while (start < end && isPythonWhitespace(points[start]!.codePointAt(0)!)) start += 1;
  while (end > start && isPythonWhitespace(points[end - 1]!.codePointAt(0)!)) end -= 1;
  return points.slice(start, end).join("");
}

function isPythonWhitespace(codePoint: number): boolean {
  return (codePoint >= 0x0009 && codePoint <= 0x000d) ||
    (codePoint >= 0x001c && codePoint <= 0x0020) || codePoint === 0x0085 || codePoint === 0x00a0 ||
    codePoint === 0x1680 || (codePoint >= 0x2000 && codePoint <= 0x200a) ||
    codePoint === 0x2028 || codePoint === 0x2029 || codePoint === 0x202f ||
    codePoint === 0x205f || codePoint === 0x3000;
}

/** Canonical Contract C bytes, excluding only the root capability_fingerprint key. */
export function canonicalContextRetrievalCapabilityV2Bytes(value: unknown): Uint8Array {
  if (!isRecord(value)) canonicalInvalid("capability fingerprint input must be an object");
  const root: Record<string, unknown> = { ...value };
  delete root.capability_fingerprint;
  return encoder.encode(renderCanonicalJson(root, "capability"));
}

export async function contextRetrievalCapabilityV2Fingerprint(value: unknown): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined) canonicalCapabilityInvalid("Web Crypto SHA-256 is unavailable");
  const canonicalBytes = canonicalContextRetrievalCapabilityV2Bytes(value);
  const digestInput = new Uint8Array(canonicalBytes.byteLength);
  digestInput.set(canonicalBytes);
  const digest = await subtle.digest("SHA-256", digestInput);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function verifyContextRetrievalCapabilityV2Fingerprint(
  capability: ContextRetrievalCapabilityV2,
): Promise<void> {
  const actual = await contextRetrievalCapabilityV2Fingerprint(capability);
  if (actual !== capability.capability_fingerprint) {
    canonicalCapabilityInvalid("capability.capability_fingerprint does not match the canonical payload");
  }
}

function renderCanonicalJson(value: unknown, path: string): string {
  if (value === null) return "null";
  if (typeof value === "string") {
    assertUnicodeScalarString(value, path);
    return JSON.stringify(value) as string;
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) canonicalInvalid(`${path} contains a noncanonical number`);
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, index) => renderCanonicalJson(item, `${path}.${index}`)).join(",")}]`;
  }
  if (!isRecord(value)) canonicalInvalid(`${path} contains a non-JSON value`);
  const keys = Object.keys(value);
  for (const key of keys) assertUnicodeScalarString(key, `${path} key`);
  keys.sort(compareUtf8);
  return `{${keys.map((key) => `${JSON.stringify(key)}:${renderCanonicalJson(value[key], `${path}.${key}`)}`).join(",")}}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalInvalid(message: string): never {
  throw new InfinityContextError({
    statusCode: 0,
    code: "memory.context_retrieval_contract_invalid",
    message,
    retryable: false,
  });
}

function canonicalCapabilityInvalid(message: string): never {
  throw new InfinityContextError({
    statusCode: 0,
    code: "memory.context_retrieval_capability_mismatch",
    message,
    retryable: false,
  });
}
