import type { RequestControls } from "./client.js";
import { ValueError } from "./payload.js";

export interface PollingControls extends RequestControls {
  readonly pollIntervalMs?: number;
  readonly maxAttempts?: number;
  readonly sleep?: (ms: number) => Promise<void>;
}

export function normalizedPollingMaxAttempts(
  value: number | undefined,
  operationName: string,
  defaultValue = 30,
): number {
  const attempts = value ?? defaultValue;
  if (!Number.isInteger(attempts) || attempts < 1) {
    throw new ValueError(`${operationName} maxAttempts must be an integer greater than 0`);
  }
  return attempts;
}

export function normalizedPollingInterval(
  value: number | undefined,
  operationName: string,
  defaultValue = 1_000,
): number {
  const pollIntervalMs = value ?? defaultValue;
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 0) {
    throw new ValueError(`${operationName} pollIntervalMs must be a non-negative number`);
  }
  return pollIntervalMs;
}

export async function waitForNextPoll(input: PollingControls, pollIntervalMs: number): Promise<void> {
  throwIfAborted(input.signal);
  if (pollIntervalMs === 0) {
    return;
  }
  if (input.sleep !== undefined) {
    await input.sleep(pollIntervalMs);
    throwIfAborted(input.signal);
    return;
  }
  await sleepWithSignal(pollIntervalMs, input.signal);
}

export function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted === true) {
    throw abortError(signal.reason);
  }
}

function sleepWithSignal(ms: number, signal: AbortSignal | undefined): Promise<void> {
  if (signal?.aborted === true) {
    return Promise.reject(abortError(signal.reason));
  }

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      resolve();
    }, ms);

    const onAbort = () => {
      cleanup();
      reject(abortError(signal?.reason));
    };
    const cleanup = () => {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", onAbort);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function abortError(reason: unknown): Error {
  void reason;
  return new DOMException("Operation aborted", "AbortError");
}
