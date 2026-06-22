import { resolveAuthToken, type AuthTokenProvider } from "./auth.js";
import { InfinityContextError, networkError, redactSensitiveText } from "./errors.js";
import type {
  InfinityContextInstrumentation,
  RequestErrorEvent,
  RequestInstrumentationContext,
  RequestResponseEvent,
  RequestRetryEvent,
  RequestStartEvent,
} from "./instrumentation.js";
import { DEFAULT_RETRY_POLICY, retryDelayMs, shouldRetry, sleep, type RetryPolicy } from "./retry.js";
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
  readonly responseType?: "json" | "bytes" | undefined;
}

export interface RequestExecutor {
  request<T = JsonValue>(options: RequestOptions): Promise<T>;
}

export interface RequestControls {
  readonly headers?: Record<string, string>;
  readonly signal?: AbortSignal;
}

export function requestControls(input: RequestControls): Pick<RequestOptions, "headers" | "signal"> {
  return {
    ...(input.headers !== undefined ? { headers: input.headers } : {}),
    ...(input.signal !== undefined ? { signal: input.signal } : {}),
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
    let lastError: InfinityContextError | undefined;
    const maxAttempts = Math.max(1, this.#retryPolicy.maxAttempts);

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const context = instrumentationContext(options, attempt + 1, maxAttempts);
      await this.#notifyRequest(context);
      const started = monotonicNowMs();
      try {
        const response = await this.#send(options);
        const durationMs = durationSince(started);
        await this.#notifyResponse({
          ...context,
          statusCode: response.status,
          durationMs,
          requestId: response.headers.get("x-request-id") ?? undefined,
        });
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
            await this.#notifyError(errorEvent(context, sdkError, durationMs));
            if (!retry) {
              throw sdkError;
            }
            await this.#retry(context, sdkError, attempt, durationMs);
            continue;
          }
        }

        const error = toHttpError(response.status, response.headers, response.body as string);
        lastError = error;
        const retry = shouldRetryAttempt(options, attempt, maxAttempts, error, response.status);
        await this.#notifyError(errorEvent(context, error, durationMs));
        if (!retry) {
          throw error;
        }
        await this.#retry(context, error, attempt, durationMs);
        continue;
      } catch (error) {
        if (error instanceof InfinityContextError && error === lastError) {
          throw error;
        }
        const sdkError = error instanceof InfinityContextError ? error : networkError(error);
        lastError = sdkError;
        const durationMs = durationSince(started);
        const retry = shouldRetryAttempt(options, attempt, maxAttempts, sdkError);
        await this.#notifyError(errorEvent(context, sdkError, durationMs));
        if (!retry) {
          throw sdkError;
        }
        await this.#retry(context, sdkError, attempt, durationMs);
      }
    }

    throw lastError ?? new InfinityContextError({
      statusCode: 0,
      code: "memory.request_failed",
      message: "Infinity Context request failed",
      retryable: true,
    });
  }

  async #send(options: RequestOptions) {
    const headers = new Headers(options.headers);
    const token = await resolveAuthToken(this.#token);
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

    return this.#transport.send({
      method: options.method,
      url: buildUrl(this.#baseUrl, options.path, options.params),
      headers,
      body,
      signal: withTimeout(options.signal, this.#timeoutMs),
      responseType: options.responseType,
    });
  }

  async #retry(
    context: RequestInstrumentationContext,
    error: InfinityContextError,
    attemptIndex: number,
    durationMs: number,
  ): Promise<void> {
    const delayMs = retryDelayMs(this.#retryPolicy, attemptIndex);
    await this.#notifyRetry({ ...errorEvent(context, error, durationMs), delayMs });
    await this.#sleep(delayMs);
  }

  async #notifyRequest(event: RequestStartEvent): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onRequest?.(event));
  }

  async #notifyResponse(event: RequestResponseEvent): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onResponse?.(event));
  }

  async #notifyError(event: RequestErrorEvent): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onError?.(event));
  }

  async #notifyRetry(event: RequestRetryEvent): Promise<void> {
    await notifyInstrumentation(() => this.#instrumentation?.onRetry?.(event));
  }
}

function instrumentationContext(
  options: RequestOptions,
  attempt: number,
  maxAttempts: number,
): RequestInstrumentationContext {
  return {
    method: options.method,
    path: options.path,
    attempt,
    maxAttempts,
    idempotencyKeyPresent: Boolean(options.idempotencyKey),
    responseType: options.responseType ?? "json",
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

async function notifyInstrumentation(callback: () => Promise<void> | void | undefined): Promise<void> {
  try {
    await callback();
  } catch {
    // Instrumentation must not change SDK request semantics.
  }
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

function toHttpError(statusCode: number, headers: Headers, body: string): InfinityContextError {
  const payload = safeJsonObject(body);
  const errorPayload = asRecord(payload.error);
  const detailPayload = asRecord(payload.detail);
  const code = String(errorPayload.code ?? detailPayload.code ?? "memory.http_error");
  const message = String((errorPayload.message ?? detailPayload.message ?? body) || code);
  const requestId = headers.get("x-request-id") ?? undefined;
  return new InfinityContextError({
    statusCode,
    code,
    message: redactSensitiveText(message),
    retryable: Boolean(errorPayload.retryable ?? statusCode >= 500),
    details: payload,
    requestId,
  });
}

function safeJsonObject(body: string): Record<string, JsonValue | undefined> {
  try {
    const parsed = JSON.parse(body) as JsonValue;
    return asRecord(parsed);
  } catch {
    return {};
  }
}

function asRecord(value: unknown): Record<string, JsonValue | undefined> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, JsonValue | undefined>)
    : {};
}
