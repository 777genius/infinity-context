import type { JsonValue } from "./types.js";

/** Hard safety cap for public HTTP error bodies, in raw UTF-8 bytes. */
export const MAX_ERROR_RESPONSE_BYTES = 16_384;

declare const boundedErrorJsonBrand: unique symbol;

/** JSON object parsed exclusively from a raw error body within the hard byte cap. */
export interface BoundedErrorJsonObject {
  readonly [boundedErrorJsonBrand]: true;
  readonly value: Record<string, JsonValue | undefined>;
}

export interface SafeErrorBody {
  readonly text?: string | undefined;
  readonly json?: BoundedErrorJsonObject | undefined;
  readonly oversized: boolean;
}

/**
 * Validate raw bytes before decoding or parsing. Strings from custom transports
 * are measured as UTF-8 before JSON.parse and are discarded whole when too large.
 */
export function safeErrorBody(body: string | Uint8Array): SafeErrorBody {
  if (body instanceof Uint8Array) {
    if (body.byteLength > MAX_ERROR_RESPONSE_BYTES) return { oversized: true };
    try {
      return parseSafeErrorText(new TextDecoder("utf-8", { fatal: true }).decode(body));
    } catch {
      return { oversized: false };
    }
  }
  if (new TextEncoder().encode(body).byteLength > MAX_ERROR_RESPONSE_BYTES) return { oversized: true };
  return parseSafeErrorText(body);
}

function parseSafeErrorText(text: string): SafeErrorBody {
  try {
    const parsed = JSON.parse(text) as JsonValue;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { text, oversized: false };
    }
    return {
      text,
      json: { value: parsed as Record<string, JsonValue | undefined> } as BoundedErrorJsonObject,
      oversized: false,
    };
  } catch {
    return { text, oversized: false };
  }
}
