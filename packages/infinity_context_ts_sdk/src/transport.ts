import {
  copyInfinityContextError,
  createInfinityContextError,
  networkError,
  operationAbortError,
  responseByteLimitError,
  timeoutAbortReason,
} from "./errors.js";
import { MAX_ERROR_RESPONSE_BYTES } from "./error-body.js";
import type { JsonValue, QueryParams } from "./types.js";

export type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE" | "PUT";

export type HttpBody =
  | { readonly kind: "json"; readonly value: JsonValue }
  | { readonly kind: "bytes"; readonly value: BodyInit; readonly contentType?: string | undefined };

export interface HttpRequest {
  readonly method: HttpMethod;
  readonly url: URL;
  readonly headers: Headers;
  readonly body?: HttpBody | undefined;
  readonly signal?: AbortSignal | undefined;
  readonly responseType?: "json" | "bytes" | undefined;
  readonly requireJsonResponse?: boolean | undefined;
  readonly expectedStatuses?: readonly number[] | undefined;
  readonly maxResponseBytes?: number | undefined;
  readonly maxErrorResponseBytes?: number | undefined;
}

export interface HttpResponse {
  readonly status: number;
  readonly headers: Headers;
  readonly body: string | Uint8Array;
}

export interface HttpTransport {
  send(request: HttpRequest): Promise<HttpResponse>;
}

export type FetchLike = typeof fetch;

export interface TimeoutSignal {
  readonly signal?: AbortSignal | undefined;
  readonly cleanup: () => void;
}

export class FetchTransport implements HttpTransport {
  readonly #fetch: FetchLike;

  constructor(fetchLike: FetchLike = fetch) {
    this.#fetch = fetchLike;
  }

  async send(request: HttpRequest): Promise<HttpResponse> {
    const headers = new Headers(request.headers);
    let body: BodyInit | undefined;

    if (request.body?.kind === "json") {
      headers.set("Content-Type", headers.get("Content-Type") ?? "application/json");
      body = JSON.stringify(request.body.value);
    } else if (request.body?.kind === "bytes") {
      body = request.body.value;
      if (request.body.contentType) {
        headers.set("Content-Type", request.body.contentType);
      }
    }

    try {
      if (request.signal?.aborted) throw request.signal.reason;
      const init: RequestInit = {
        method: request.method,
        headers,
        // Manual mode exposes redirects without following or replaying request
        // bodies, so they can be classified as non-retryable protocol failures.
        redirect: "manual",
      };
      if (body !== undefined) {
        init.body = body;
      }
      if (request.signal !== undefined) {
        init.signal = request.signal;
      }
      const response = await abortable(this.#fetch(request.url, init), request.signal);
      if (response.type === "opaque" || response.type === "opaqueredirect") {
        throw redirectRejectedError(response.status);
      }
      if (response.status >= 300 && response.status <= 399) {
        throw redirectRejectedError(
          response.status,
          response.headers.get("x-request-id") ?? undefined,
        );
      }
      const responseMaximum = response.status >= 300
        ? errorResponseMaximum(request)
        : request.maxResponseBytes;
      const responseBytes = await readResponseBytes(response, responseMaximum, request.signal);
      const requestId = response.headers.get("x-request-id") ?? undefined;
      const expectedSuccess = response.status >= 200 && response.status < 300 &&
        (request.expectedStatuses === undefined || request.expectedStatuses.includes(response.status));
      const requiresJsonMedia = expectedSuccess && !(response.status === 204 && responseBytes.byteLength === 0) &&
        (request.responseType !== "bytes" || request.requireJsonResponse === true);
      if (requiresJsonMedia && !hasExactJsonContentType(response.headers)) {
        throw invalidContentTypeError(response.status, requestId);
      }
      return {
        status: response.status,
        headers: response.headers,
        body: request.responseType === "bytes" || response.status >= 300 ||
          (response.status < 300 && !expectedSuccess)
          ? responseBytes
          : decodeJsonResponseBytes(responseBytes, response.status, requestId),
      };
    } catch (error) {
      if (request.signal?.aborted) throw operationAbortError(request.signal.reason);
      const sdkError = copyInfinityContextError(error);
      if (sdkError !== undefined) throw sdkError;
      throw networkError(error);
    }
  }
}

function redirectRejectedError(statusCode: number, requestId?: string) {
  return createInfinityContextError({
    statusCode,
    code: "memory.redirect_rejected",
    message: "Infinity Context redirect response rejected",
    retryable: false,
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

export function hasExactJsonContentType(headers: Headers): boolean {
  const raw = headers.get("content-type");
  if (raw === null || raw.includes(",")) return false;
  const parts = raw.split(";").map((part) => part.trim());
  if (parts[0]?.toLowerCase() !== "application/json") return false;
  if (parts.length === 1) return true;
  if (parts.length !== 2) return false;
  const parameter = parts[1]?.split("=");
  return parameter?.length === 2 && parameter[0]?.trim().toLowerCase() === "charset"
    && parameter[1]?.trim().toLowerCase() === "utf-8";
}

function invalidContentTypeError(statusCode: number, requestId?: string) {
  return createInfinityContextError({
    statusCode,
    code: "memory.invalid_response_content_type",
    message: "Infinity Context response must use application/json with optional UTF-8 charset",
    retryable: false,
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

function decodeJsonResponseBytes(body: Uint8Array, statusCode: number, requestId?: string): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(body);
  } catch {
    throw createInfinityContextError({
      statusCode,
      code: "memory.invalid_json_response",
      message: "Infinity Context returned invalid UTF-8 JSON",
      retryable: false,
      ...(requestId !== undefined ? { requestId } : {}),
    });
  }
}

function errorResponseMaximum(request: HttpRequest): number {
  const requested = request.maxErrorResponseBytes ??
    (request.responseType === "bytes" ? request.maxResponseBytes : undefined);
  if (requested === undefined) return MAX_ERROR_RESPONSE_BYTES;
  if (!Number.isSafeInteger(requested) || requested < 0) {
    throw new TypeError("maxErrorResponseBytes must be a non-negative integer");
  }
  return Math.min(requested, MAX_ERROR_RESPONSE_BYTES);
}

async function readResponseBytes(
  response: Response,
  maximum: number | undefined,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  if (maximum !== undefined && (!Number.isSafeInteger(maximum) || maximum < 0)) {
    throw new TypeError("maxResponseBytes must be a non-negative integer");
  }
  if (response.body === null) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    const contentLength = response.headers.get("content-length");
    if (maximum !== undefined && contentLength !== null && /^\d+$/u.test(contentLength) && Number(contentLength) > maximum) {
      cancelReader(reader);
      throw responseByteLimitError(response.status, response.headers.get("x-request-id") ?? undefined);
    }
    while (true) {
      const { done, value } = await abortable(reader.read(), signal, () => cancelReader(reader, signal?.reason));
      if (done) break;
      received += value.byteLength;
      if (maximum !== undefined && received > maximum) {
        cancelReader(reader);
        throw responseByteLimitError(response.status, response.headers.get("x-request-id") ?? undefined);
      }
      chunks.push(value);
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Releasing a reader must not replace a typed byte-limit failure.
    }
  }
  const output = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

function cancelReader(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  reason: unknown = "response byte limit exceeded",
): void {
  try {
    void reader.cancel(reason).catch(() => undefined);
  } catch {
    // Cancellation is best-effort; the byte-limit failure must settle promptly.
  }
}

function abortable<T>(promise: Promise<T>, signal: AbortSignal | undefined, onAbort?: () => void): Promise<T> {
  if (signal === undefined) return promise;
  if (signal.aborted) {
    // Fetch and stream implementations can synchronously abort while creating
    // their promise, then reject it later. Cancellation wins, but the original
    // rejection must still be observed.
    void promise.catch(() => undefined);
    onAbort?.();
    return Promise.reject(signal.reason);
  }
  return new Promise<T>((resolve, reject) => {
    const handleAbort = () => {
      onAbort?.();
      reject(signal.reason);
    };
    signal.addEventListener("abort", handleAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", handleAbort));
  });
}

export function buildUrl(baseUrl: string, path: string, params?: QueryParams): URL {
  const url = new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  for (const [key, rawValue] of Object.entries(params ?? {})) {
    if (rawValue === undefined || rawValue === null) {
      continue;
    }
    if (Array.isArray(rawValue)) {
      for (const item of rawValue as readonly unknown[]) {
        url.searchParams.append(key, String(item));
      }
      continue;
    }
    url.searchParams.set(key, String(rawValue));
  }
  return url;
}

export function withTimeout(signal: AbortSignal | undefined, timeoutMs: number): TimeoutSignal {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return {
      ...(signal !== undefined ? { signal } : {}),
      cleanup: () => undefined,
    };
  }

  const timeoutController = new AbortController();
  const timeout = setTimeout(() => {
    timeoutController.abort(timeoutAbortReason());
  }, timeoutMs);
  timeout.unref?.();

  if (!signal) {
    return {
      signal: timeoutController.signal,
      cleanup: () => clearTimeout(timeout),
    };
  }

  const controller = new AbortController();
  let cleanedUp = false;
  const cleanup = () => {
    if (cleanedUp) {
      return;
    }
    cleanedUp = true;
    clearTimeout(timeout);
    signal.removeEventListener("abort", onAbort);
    timeoutController.signal.removeEventListener("abort", onTimeout);
  };
  const abort = (reason?: unknown) => {
    cleanup();
    if (!controller.signal.aborted) {
      controller.abort(reason);
    }
  };
  const onAbort = () => abort(signal.reason);
  const onTimeout = () => abort(timeoutController.signal.reason);

  if (signal.aborted) {
    abort(signal.reason);
    return {
      signal: controller.signal,
      cleanup,
    };
  }

  signal.addEventListener("abort", onAbort, { once: true });
  timeoutController.signal.addEventListener("abort", onTimeout, { once: true });
  return {
    signal: controller.signal,
    cleanup,
  };
}
