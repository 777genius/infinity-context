import { resolveAuthToken, type AuthTokenProvider } from "./auth.js";
import { safeErrorBody, type BoundedErrorJsonObject } from "./error-body.js";
import {
  copyInfinityContextError,
  createInfinityContextError,
  type InfinityContextError,
  networkError,
  operationAbortError,
  redactSensitiveText,
} from "./errors.js";
import type {
  InfinityContextInstrumentation,
  RequestErrorEvent,
  RequestInstrumentationContext,
  RequestResponseEvent,
  RequestRetryEvent,
  RequestStartEvent,
} from "./instrumentation.js";
import { DEFAULT_RETRY_POLICY, parseRetryAfterMs, retryDelayMs, shouldRetry, sleep, type RetryPolicy } from "./retry.js";
import { buildUrl, FetchTransport, type HttpBody, type HttpMethod, type HttpTransport, withTimeout } from "./transport.js";
import type { JsonValue, QueryParams } from "./types.js";

export interface InfinityContextClientOptions {
  readonly baseUrl?: string;
  readonly token?: AuthTokenProvider;
  readonly timeoutMs?: number;
  readonly transport?: HttpTransport;
  readonly retryPolicy?: Partial<RetryPolicy>;
  readonly sleep?: (ms: number) => Promise<void>;
  readonly instrumentation?: InfinityContextInstrumentation;
}

export interface RequestOptions {
  readonly method: HttpMethod;
  readonly path: string;
  readonly params?: QueryParams | undefined;
  readonly json?: JsonValue | undefined;
  readonly bytes?: BodyInit | undefined;
  readonly contentType?: string | undefined;
  readonly headers?: Record<string, string> | undefined;
  readonly idempotencyKey?: string | undefined;
  readonly signal?: AbortSignal | undefined;
  readonly timeoutMs?: number | undefined;
  readonly responseType?: "json" | "bytes" | undefined;
  readonly maxResponseBytes?: number | undefined;
  readonly maxErrorResponseBytes?: number | undefined;
  readonly errorDecoder?: HttpErrorDecoder | undefined;
}

export type HttpErrorDecoder = (
  statusCode: number,
  headers: Headers,
  body: Uint8Array | string,
) => InfinityContextError;

export interface RequestExecutor {
  request<T = JsonValue>(options: RequestOptions): Promise<T>;
}

export interface RequestControls {
  readonly headers?: Record<string, string>;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

export function requestControls(input: RequestControls): Pick<RequestOptions, "headers" | "signal" | "timeoutMs"> {
  return {
    ...(input.headers !== undefined ? { headers: input.headers } : {}),
    ...(input.signal !== undefined ? { signal: input.signal } : {}),
    ...(input.timeoutMs !== undefined ? { timeoutMs: input.timeoutMs } : {}),
  };
}

export class HttpClient implements RequestExecutor {
  readonly #baseUrl: string;
  readonly #token: AuthTokenProvider;
  readonly #timeoutMs: number;
  readonly #transport: HttpTransport;
  readonly #retryPolicy: RetryPolicy;
  readonly #sleep: (ms: number) => Promise<void>;
  readonly #instrumentation: InfinityContextInstrumentation | undefined;

  constructor(options: InfinityContextClientOptions = {}) {
    this.#baseUrl = options.baseUrl ?? "http://127.0.0.1:7788";
    this.#token = options.token;
    this.#timeoutMs = options.timeoutMs ?? 10_000;
    this.#transport = options.transport ?? new FetchTransport();
    this.#retryPolicy = { ...DEFAULT_RETRY_POLICY, ...options.retryPolicy };
    this.#sleep = options.sleep ?? sleep;
    this.#instrumentation = options.instrumentation;
  }

  async request<T = JsonValue>(options: RequestOptions): Promise<T> {
    const operation = withTimeout(options.signal, options.timeoutMs ?? this.#timeoutMs);
    try {
      return await this.#requestWithinBudget<T>(options, operation.signal);
    } catch (error) {
      if (operation.signal?.aborted) throw operationAbortError(operation.signal.reason);
      throw error;
    } finally {
      operation.cleanup();
    }
  }

  async #requestWithinBudget<T>(options: RequestOptions, signal: AbortSignal | undefined): Promise<T> {
    let lastError: InfinityContextError | undefined;
    const maxAttempts = Math.max(1, this.#retryPolicy.maxAttempts);

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const context = instrumentationContext(options, attempt + 1, maxAttempts, signal);
      const started = monotonicNowMs();
      try {
        await this.#notifyRequest(context, signal);
        const response = await this.#send(options, signal);
        const durationMs = durationSince(started);
        await this.#notifyResponse({
          ...context,
          statusCode: response.status,
          durationMs,
          requestId: response.headers.get("x-request-id") ?? undefined,
        }, signal);
        if (response.status < 400) {
          try {
            if (options.responseType === "bytes") {
              return response.body as T;
            }
            return parseJson(response.body as string) as T;
          } catch (error) {
            const sdkError = networkError(error);
            lastError = sdkError;
            const retry = shouldRetryAttempt(options, attempt, maxAttempts, sdkError);
            await this.#notifyError(errorEvent(context, sdkError, durationMs), signal);
            if (!retry) throw sdkError;
            await this.#retry(context, sdkError, attempt, durationMs, signal);
            continue;
          }
        }

        const decoded = options.errorDecoder === undefined
          ? toHttpError(
            response.status,
            response.headers,
            response.body,
          )
          : options.errorDecoder(response.status, response.headers, response.body);
        const error = copyInfinityContextError(decoded) ?? networkError(decoded);
        lastError = error;
        const retry = shouldRetryAttempt(options, attempt, maxAttempts, error, response.status);
        await this.#notifyError(errorEvent(context, error, durationMs), signal);
        if (!retry) throw error;
        await this.#retry(context, error, attempt, durationMs, signal);
      } catch (error) {
        if (signal?.aborted) throw operationAbortError(signal.reason);
        if (error === lastError) throw copyInfinityContextError(error) ?? networkError(error);
        const sdkError = copyInfinityContextError(error) ?? networkError(error);
        lastError = sdkError;
        const durationMs = durationSince(started);
        const retry = shouldRetryAttempt(options, attempt, maxAttempts, sdkError);
        await this.#notifyError(errorEvent(context, sdkError, durationMs), signal);
        if (!retry) throw sdkError;
        await this.#retry(context, sdkError, attempt, durationMs, signal);
      }
    }

    throw lastError ?? createInfinityContextError({
      statusCode: 0,
      code: "memory.request_failed",
      message: "Infinity Context request failed",
      retryable: true,
    });
  }

  async #send(options: RequestOptions, signal: AbortSignal | undefined) {
    throwIfAborted(signal);
    const headers = new Headers(options.headers);
    const token = await abortable(resolveAuthToken(this.#token, signal), signal);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    if (options.idempotencyKey) {
      headers.set("Idempotency-Key", options.idempotencyKey);
    }

    let body: HttpBody | undefined;
    if (options.json !== undefined) {
      body = { kind: "json", value: options.json };
    } else if (options.bytes !== undefined) {
      body = { kind: "bytes", value: options.bytes, contentType: options.contentType };
    }

    throwIfAborted(signal);
    return await abortable(this.#transport.send({
      method: options.method,
      url: buildUrl(this.#baseUrl, options.path, options.params),
      headers,
      body,
      signal,
      responseType: options.responseType,
      maxResponseBytes: options.maxResponseBytes,
      maxErrorResponseBytes: options.maxErrorResponseBytes,
    }), signal);
  }

  async #retry(
    context: RequestInstrumentationContext,
    error: InfinityContextError,
    attemptIndex: number,
    durationMs: number,
    signal: AbortSignal | undefined,
  ): Promise<void> {
    const delayMs = retryDelayMs(this.#retryPolicy, attemptIndex, error.retryAfterMs);
    await this.#notifyRetry({ ...errorEvent(context, error, durationMs), delayMs }, signal);
    throwIfAborted(signal);
    await abortable(this.#sleep(delayMs), signal);
  }

  async #notifyRequest(event: RequestStartEvent, signal: AbortSignal | undefined): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onRequest?.(event), signal);
  }

  async #notifyResponse(event: RequestResponseEvent, signal: AbortSignal | undefined): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onResponse?.(event), signal);
  }

  async #notifyError(event: RequestErrorEvent, signal: AbortSignal | undefined): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onError?.(event), signal);
  }

  async #notifyRetry(event: RequestRetryEvent, signal: AbortSignal | undefined): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onRetry?.(event), signal);
  }
}

function abortable<T>(promise: Promise<T>, signal: AbortSignal | undefined): Promise<T> {
  if (signal === undefined) return promise;
  if (signal.aborted) {
    // The producer may have aborted the signal synchronously before returning
    // its promise. Keep observing that promise even though cancellation wins.
    void promise.catch(() => undefined);
    return Promise.reject(signal.reason);
  }
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

function instrumentationContext(
  options: RequestOptions,
  attempt: number,
  maxAttempts: number,
  signal: AbortSignal | undefined,
): RequestInstrumentationContext {
  return {
    method: options.method,
    path: options.path,
    attempt,
    maxAttempts,
    idempotencyKeyPresent: Boolean(options.idempotencyKey),
    responseType: options.responseType ?? "json",
    signal,
  };
}

function shouldRetryAttempt(
  options: RequestOptions,
  attemptIndex: number,
  maxAttempts: number,
  error: InfinityContextError,
  status?: number,
): boolean {
  return attemptIndex + 1 < maxAttempts && shouldRetry({
    method: options.method,
    ...(status !== undefined ? { status } : {}),
    ...(status === undefined ? { retryableError: error.retryable } : {}),
    hasIdempotencyKey: Boolean(options.idempotencyKey),
  });
}

function errorEvent(
  context: RequestInstrumentationContext,
  error: InfinityContextError,
  durationMs: number,
): RequestErrorEvent {
  return {
    ...context,
    error,
    durationMs,
    statusCode: error.statusCode > 0 ? error.statusCode : undefined,
    requestId: error.requestId,
  };
}

async function notifyInstrumentation(
  callback: () => Promise<void> | void | undefined,
  signal: AbortSignal | undefined,
): Promise<void> {
  throwIfAborted(signal);
  let result: Promise<void> | void | undefined;
  try {
    result = callback();
  } catch {
    if (signal?.aborted) throw operationAbortError(signal.reason);
    return;
  }
  try {
    await abortable(Promise.resolve(result), signal);
  } catch {
    if (signal?.aborted) throw operationAbortError(signal.reason);
    // Instrumentation failures must not change SDK request semantics.
  }
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw operationAbortError(signal.reason);
}

function monotonicNowMs(): number {
  return globalThis.performance?.now() ?? Date.now();
}

function durationSince(startedMs: number): number {
  return Math.max(0, monotonicNowMs() - startedMs);
}

function parseJson(body: string): JsonValue {
  if (!body.trim()) {
    return {};
  }
  return JSON.parse(body) as JsonValue;
}

function toHttpError(statusCode: number, headers: Headers, body: string | Uint8Array): InfinityContextError {
  const safeBody = safeErrorBody(body);
  const payload = safeJsonObject(safeBody.json);
  const errorPayload = asRecord(payload.error);
  const detailPayload = asRecord(payload.detail);
  const code = String(errorPayload.code ?? detailPayload.code ?? "memory.http_error");
  const message = String((errorPayload.message ?? detailPayload.message ?? safeBody.text) || code);
  const requestId = headers.get("x-request-id") ?? undefined;
  return createInfinityContextError({
    statusCode,
    code,
    message: redactSensitiveText(message),
    retryable: Boolean(errorPayload.retryable ?? statusCode >= 500),
    retryAfterMs: parseRetryAfterMs(headers.get("retry-after")),
    details: payload,
    requestId,
  });
}

function safeJsonObject(body: BoundedErrorJsonObject | undefined): Record<string, JsonValue | undefined> {
  return body?.value ?? {};
}

function asRecord(value: unknown): Record<string, JsonValue | undefined> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, JsonValue | undefined>)
    : {};
}
