import type { InfinityContextError } from "./errors.js";
import type { MaybePromise } from "./types.js";
import type { HttpMethod } from "./transport.js";

export interface RequestInstrumentationContext {
  readonly method: HttpMethod;
  readonly path: string;
  readonly attempt: number;
  readonly maxAttempts: number;
  readonly idempotencyKeyPresent: boolean;
  readonly responseType: "json" | "bytes";
  /** The signal for the complete logical SDK operation, including hooks and authentication. */
  readonly signal?: AbortSignal | undefined;
}

export interface RequestStartEvent extends RequestInstrumentationContext {}

export interface RequestResponseEvent extends RequestInstrumentationContext {
  readonly statusCode: number;
  readonly durationMs: number;
  readonly requestId?: string | undefined;
}

export interface RequestErrorEvent extends RequestInstrumentationContext {
  readonly error: InfinityContextError;
  readonly durationMs: number;
  readonly statusCode?: number | undefined;
  readonly requestId?: string | undefined;
}

export interface RequestRetryEvent extends RequestErrorEvent {
  readonly delayMs: number;
}

export interface InfinityContextInstrumentation {
  readonly onRequest?: (event: RequestStartEvent) => MaybePromise<void>;
  readonly onResponse?: (event: RequestResponseEvent) => MaybePromise<void>;
  readonly onError?: (event: RequestErrorEvent) => MaybePromise<void>;
  readonly onRetry?: (event: RequestRetryEvent) => MaybePromise<void>;
}

export function noopInstrumentation(): InfinityContextInstrumentation {
  return {};
}
