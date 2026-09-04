import { afterEach, describe, expect, it, vi } from "vitest";
import { FetchTransport, HttpClient } from "../src/index.js";
import { operationAbortError, timeoutAbortReason } from "../src/errors.js";
import { HangingTransport, waitForRecordedRequests } from "./fixtures.js";

const timeout = () => new DOMException("private deadline detail", "TimeoutError");
const expectedTimeout = { code: "memory.request_timeout", retryable: true, statusCode: 0 };
const expectedCancellation = { code: "memory.request_aborted", retryable: false, statusCode: 0 };

afterEach(() => vi.unstubAllGlobals());

describe("native caller deadline classification", () => {
  it("uses the native name without invoking caller getters or prototype traps", () => {
    let reads = 0;
    const hostile = () => { reads += 1; throw new Error("must not run"); };
    const revoked = Proxy.revocable({}, {});
    revoked.revoke();
    const fake = Object.create(DOMException.prototype, { name: { get: hostile } });
    const disguisedAbort = new DOMException("private cancellation detail", "AbortError");
    Object.defineProperty(disguisedAbort, "name", { get: () => { reads += 1; return "TimeoutError"; } });
    for (const reason of [
      null, undefined, "TimeoutError", 42, Symbol("TimeoutError"),
      { name: "TimeoutError" }, Object.assign(new Error(), { name: "TimeoutError" }),
      fake, disguisedAbort, revoked.proxy,
      new Proxy({}, { getPrototypeOf: hostile, get: hostile }),
      new Proxy(timeout(), { getPrototypeOf: hostile, get: hostile }),
      Object.defineProperty({}, "name", { get: hostile }),
      Object.defineProperty({}, Symbol.toStringTag, { get: hostile }),
    ]) {
      expect(operationAbortError(reason)).toMatchObject(expectedCancellation);
    }
    const genuine = timeout();
    Object.defineProperty(genuine, "name", { get: hostile });
    expect(operationAbortError(genuine)).toMatchObject(expectedTimeout);
    // A genuine exception's identity does not depend on its prototype chain.
    const detached = timeout();
    Object.setPrototypeOf(detached, null);
    expect(operationAbortError(detached)).toMatchObject(expectedTimeout);
    expect(reads).toBe(0);
    expect(operationAbortError(genuine).cause).toEqual({ name: "Error", message: "External error cause redacted" });
  });

  it("keeps the SDK deadline functional without a DOMException global", () => {
    vi.stubGlobal("DOMException", undefined);
    expect(operationAbortError(timeoutAbortReason())).toMatchObject(expectedTimeout);
    expect(operationAbortError({ name: "TimeoutError" })).toMatchObject(expectedCancellation);
  });

  it.each([0, 10_000])("does not send or retry a pre-aborted operation (SDK budget %s)", async (timeoutMs) => {
    const transport = new HangingTransport();
    const onRetry = vi.fn();
    const client = new HttpClient({ transport, timeoutMs, retryPolicy: { maxAttempts: 3 }, instrumentation: { onRetry } });
    await expect(client.request({ method: "GET", path: "/deadline", signal: AbortSignal.abort(timeout()) }))
      .rejects.toMatchObject(expectedTimeout);
    expect(transport.requests).toHaveLength(0);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("does not invoke fetch for a pre-aborted deadline", async () => {
    const fetchLike = vi.fn<typeof fetch>();
    await expect(new FetchTransport(fetchLike).send({
      method: "GET", url: new URL("http://memory.test"), headers: new Headers(), signal: AbortSignal.abort(timeout()),
    })).rejects.toMatchObject(expectedTimeout);
    expect(fetchLike).not.toHaveBeenCalled();
  });

  it("normalizes AbortSignal.timeout through HttpClient without replaying writes", async () => {
    const transport = new HangingTransport();
    const client = new HttpClient({ transport, timeoutMs: 0, retryPolicy: { maxAttempts: 3 } });
    await expect(client.request({ method: "POST", path: "/deadline", signal: AbortSignal.timeout(10) }))
      .rejects.toMatchObject(expectedTimeout);
    expect(transport.requests).toHaveLength(1);
  });

  it.each(["auth", "onRequest", "onResponse", "onError", "onRetry", "sleep"] as const)(
    "preserves the caller deadline during %s", async (phase) => {
      const controller = new AbortController();
      const hang = () => { controller.abort(timeout()); return new Promise<never>(() => undefined); };
      let sends = 0;
      const client = new HttpClient({
        timeoutMs: 10_000,
        token: () => phase === "auth" ? hang() : "test-token",
        transport: { async send() {
          sends += 1;
          if (phase !== "onResponse") throw new Error("unavailable");
          return { status: 200, headers: new Headers({ "content-type": "application/json" }), body: "{}" };
        } },
        retryPolicy: { maxAttempts: 3, baseDelayMs: 0, jitter: false },
        instrumentation: {
          onRequest: () => phase === "onRequest" ? hang() : undefined,
          onResponse: () => phase === "onResponse" ? hang() : undefined,
          onError: () => phase === "onError" ? hang() : undefined,
          onRetry: () => phase === "onRetry" ? hang() : undefined,
        },
        sleep: async () => { if (phase === "sleep") await hang(); },
      });
      await expect(client.request({ method: "GET", path: "/deadline", signal: controller.signal }))
        .rejects.toMatchObject(expectedTimeout);
      expect(sends).toBe(phase === "auth" || phase === "onRequest" ? 0 : 1);
    },
  );

  it("cancels a stalled response body on a caller deadline", async () => {
    let started!: () => void;
    const reading = new Promise<void>((resolve) => { started = resolve; });
    const cancel = vi.fn();
    const fetchLike = (async () => new Response(new ReadableStream({ pull: started, cancel }))) as typeof fetch;
    const controller = new AbortController();
    const request = new FetchTransport(fetchLike).send({
      method: "GET", url: new URL("http://memory.test"), headers: new Headers(), signal: controller.signal,
    });
    await reading;
    controller.abort(timeout());
    await expect(request).rejects.toMatchObject(expectedTimeout);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("preserves the first signal reason when SDK and caller deadlines compete", async () => {
    const controller = new AbortController();
    const transport = new HangingTransport();
    const client = new HttpClient({ transport, timeoutMs: 10, retryPolicy: { maxAttempts: 3 } });
    const request = client.request({ method: "GET", path: "/deadline", signal: controller.signal });
    await waitForRecordedRequests(transport, 1);
    controller.abort(new DOMException("cancel", "AbortError"));
    await expect(request).rejects.toMatchObject(expectedCancellation);
    expect(transport.requests).toHaveLength(1);
  });
});
