import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  FetchTransport,
  HttpClient,
  parseRetryAfterMs,
} from "../src/index.js";
import {
  HangingTransport,
  RecordingTransport,
  jsonResponse,
  waitForRecordedRequests,
} from "./fixtures.js";

describe("transport, retry and errors", () => {
  it("stops bounded byte responses before buffering beyond the limit", async () => {
    const fetchLike = (async () => new Response("x".repeat(33))) as typeof fetch;
    const transport = new FetchTransport(fetchLike);
    await expect(transport.send({
      method: "GET", url: new URL("http://memory.test/bounded"), headers: new Headers(),
      responseType: "bytes", maxResponseBytes: 32,
    })).rejects.toMatchObject({
      code: "memory.response_byte_limit_exceeded", statusCode: 200, retryable: false,
    });

    const exact = await transport.send({
      method: "GET", url: new URL("http://memory.test/bounded"), headers: new Headers(),
      responseType: "bytes", maxResponseBytes: 33,
    });
    expect(exact.body).toBeInstanceOf(Uint8Array);
    expect((exact.body as Uint8Array).byteLength).toBe(33);
  });

  it.each([
    ["never settles", () => new Promise<void>(() => undefined)],
    ["rejects", () => Promise.reject(new Error("cancel failed"))],
  ] as const)("settles the typed byte-limit error promptly when reader cancellation %s", async (_name, cancel) => {
    let cancelCalls = 0;
    const fetchLike = (async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(33));
      },
      cancel() {
        cancelCalls += 1;
        return cancel();
      },
    }), { status: 403, headers: { "x-request-id": "request-cancel" } })) as typeof fetch;
    const transport = new FetchTransport(fetchLike);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const outcome = await Promise.race([
      transport.send({
        method: "GET", url: new URL("http://memory.test/bounded"), headers: new Headers(),
        responseType: "bytes", maxResponseBytes: 32,
      }).then(
        () => ({ kind: "resolved" as const }),
        (error: unknown) => ({ kind: "rejected" as const, error }),
      ),
      new Promise<{ readonly kind: "timeout" }>((resolve) => {
        timeout = setTimeout(() => resolve({ kind: "timeout" }), 100);
      }),
    ]);
    if (timeout !== undefined) clearTimeout(timeout);

    expect(outcome.kind).toBe("rejected");
    expect(outcome).toMatchObject({
      error: {
        code: "memory.response_byte_limit_exceeded", statusCode: 403,
        requestId: "request-cancel", retryable: false,
      },
    });
    expect(cancelCalls).toBe(1);
  });

  it.each([
    [403, "request-403"],
    [200, "request-200"],
  ] as const)("preserves oversized HTTP %s identity without guessing a hidden server code", async (status, requestId) => {
    const hidden = JSON.stringify({
      error: { code: "memory.hidden_after_bound", message: "must not be parsed", retryable: true },
      padding: "x".repeat(128),
    });
    let calls = 0;
    const fetchLike = (async () => {
      calls += 1;
      return new Response(hidden, { status, headers: { "x-request-id": requestId } });
    }) as typeof fetch;
    const client = new HttpClient({
      transport: new FetchTransport(fetchLike),
      retryPolicy: { maxAttempts: 2 },
    });

    await expect(client.request({
      method: "GET", path: "/bounded",
      responseType: "bytes", maxResponseBytes: 32,
    })).rejects.toMatchObject({
      code: "memory.response_byte_limit_exceeded",
      statusCode: status,
      requestId,
      retryable: false,
    });
    expect(calls).toBe(1);
  });

  it("retains an exact normal-sized 403 server error code and non-retryable semantics", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ error: { code: "memory.denied", message: "denied", retryable: false } }, 403, {
        "x-request-id": "request-denied",
      }),
    ]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 2 } });
    await expect(client.system.capabilities()).rejects.toMatchObject({
      code: "memory.denied", statusCode: 403, requestId: "request-denied", retryable: false,
    });
    expect(transport.requests).toHaveLength(1);
  });

  it("sends auth, params and idempotency headers through resource clients", async () => {
    const transport = new RecordingTransport([jsonResponse({ data: { id: "fact_1" } })]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      token: async () => "test-token",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await client.facts.rememberFact({
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      text: "Remember user likes source-rich summaries.",
      sourceRefs: [{ source_type: "test", source_id: "case_1" }],
      idempotencyKey: "case_1",
      category: "preference",
      tags: ["summary"],
    });

    expect(transport.requests[0]?.url.toString()).toBe("http://memory.test/v1/facts");
    expect(transport.requests[0]?.headers.get("authorization")).toBe("Bearer test-token");
    expect(transport.requests[0]?.headers.get("idempotency-key")).toBe("case_1");
    expect(transport.bodies[0]).toMatchObject({
      space_id: "space_1",
      memory_scope_id: "scope_1",
      text: "Remember user likes source-rich summaries.",
      category: "preference",
      tags: ["summary"],
    });
  });

  it("emits request instrumentation events without exposing headers or bodies", async () => {
    const events: string[] = [];
    const transport = new RecordingTransport([
      jsonResponse(
        { error: { code: "temporary", message: "try again", retryable: true } },
        503,
        { "x-request-id": "req_503" },
      ),
      jsonResponse({ data: { id: "fact_1" } }, 200, { "x-request-id": "req_ok" }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      sleep: async () => undefined,
      retryPolicy: { maxAttempts: 2, baseDelayMs: 10, maxDelayMs: 10, jitter: false },
      instrumentation: {
        onRequest: (event) => {
          events.push(`request:${event.attempt}:${event.method}:${event.path}`);
        },
        onResponse: (event) => {
          events.push(`response:${event.attempt}:${event.statusCode}:${event.requestId}`);
        },
        onError: (event) => {
          events.push(`error:${event.attempt}:${event.error.code}:${event.statusCode}`);
        },
        onRetry: (event) => {
          events.push(`retry:${event.attempt}:${event.delayMs}`);
        },
      },
    });

    await client.facts.rememberFact({
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      text: "Remember user likes source-rich summaries.",
      sourceRefs: [{ source_type: "test", source_id: "case_1" }],
      idempotencyKey: "case_1",
    });

    expect(events).toEqual([
      "request:1:POST:/v1/facts",
      "response:1:503:req_503",
      "error:1:temporary:503",
      "retry:1:10",
      "request:2:POST:/v1/facts",
      "response:2:200:req_ok",
    ]);
  });

  it("applies per-request timeout controls and cleans up completed request timers", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: { status: "ok" } }),
      jsonResponse({ enabled_adapters: [] }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      timeoutMs: 0,
      retryPolicy: { maxAttempts: 1 },
    });

    await client.system.health();
    await client.system.capabilities({ timeoutMs: 10 });

    expect(transport.requests[0]?.signal).toBeUndefined();
    const timedSignal = transport.requests[1]?.signal;
    expect(timedSignal).toBeDefined();
    expect(timedSignal?.aborted).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(timedSignal?.aborted).toBe(false);
  });

  it("fails hanging requests with a typed timeout error", async () => {
    const transport = new HangingTransport();
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      timeoutMs: 0,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(client.system.capabilities({ timeoutMs: 1 })).rejects.toMatchObject({
      code: "memory.request_timeout",
      retryable: true,
    });
    expect(transport.requests[0]?.signal?.aborted).toBe(true);
  });

  it("starts the operation budget before async authentication", async () => {
    let authSignal: AbortSignal | undefined;
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      token: (signal) => { authSignal = signal; return new Promise<string>(() => undefined); },
      transport, retryPolicy: { maxAttempts: 1 },
    });
    await expect(client.system.capabilities({ timeoutMs: 10 })).rejects.toMatchObject({ code: "memory.request_timeout" });
    expect(authSignal?.aborted).toBe(true);
    expect(transport.requests).toHaveLength(0);
  });

  it("races caller cancellation through never-settling request instrumentation", async () => {
    const controller = new AbortController();
    let instrumentationSignal: AbortSignal | undefined;
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({
      transport, retryPolicy: { maxAttempts: 1 },
      instrumentation: { onRequest: (event) => {
        instrumentationSignal = event.signal;
        return new Promise<void>(() => undefined);
      } },
    });
    const request = client.system.capabilities({ signal: controller.signal });
    controller.abort("cancel before transport");
    await expect(request).rejects.toMatchObject({ code: "memory.request_aborted" });
    expect(instrumentationSignal?.aborted).toBe(true);
    expect(transport.requests).toHaveLength(0);
  });

  it("keeps response instrumentation inside the operation budget without duplicate effects", async () => {
    let responses = 0;
    let errors = 0;
    const transport = new RecordingTransport([jsonResponse({ enabled_adapters: [] })]);
    const client = new InfinityContextClient({
      transport, retryPolicy: { maxAttempts: 2 },
      instrumentation: {
        onResponse: () => { responses += 1; return new Promise<void>(() => undefined); },
        onError: () => { errors += 1; },
      },
    });
    await expect(client.system.capabilities({ timeoutMs: 10 })).rejects.toMatchObject({ code: "memory.request_timeout" });
    expect(transport.requests).toHaveLength(1);
    expect(responses).toBe(1);
    expect(errors).toBe(0);
  });

  it.each(["onError", "onRetry", "sleep"] as const)(
    "normalizes timeout while %s never settles after a transport failure",
    async (phase) => {
      let sends = 0;
      let errors = 0;
      let retries = 0;
      let sleeps = 0;
      const client = new HttpClient({
        transport: {
          async send() {
            sends += 1;
            throw new Error("transport unavailable");
          },
        },
        retryPolicy: { maxAttempts: 2, baseDelayMs: 1, maxDelayMs: 1, jitter: false },
        instrumentation: {
          onError: () => {
            errors += 1;
            if (phase === "onError") return new Promise<void>(() => undefined);
          },
          onRetry: () => {
            retries += 1;
            if (phase === "onRetry") return new Promise<void>(() => undefined);
          },
        },
        sleep: async () => {
          sleeps += 1;
          if (phase === "sleep") return new Promise<void>(() => undefined);
        },
      });

      await expect(client.request({ method: "GET", path: "/failure", timeoutMs: 10 })).rejects.toMatchObject({
        code: "memory.request_timeout",
        retryable: true,
      });
      expect(sends).toBe(1);
      expect(errors).toBe(1);
      expect(retries).toBe(phase === "onError" ? 0 : 1);
      expect(sleeps).toBe(phase === "sleep" ? 1 : 0);
    },
  );

  it.each(["onError", "onRetry", "sleep"] as const)(
    "normalizes caller abort while %s never settles after a transport failure",
    async (phase) => {
      const controller = new AbortController();
      const reason = new Error(`cancel during ${phase}`);
      let sends = 0;
      const hang = () => {
        controller.abort(reason);
        return new Promise<void>(() => undefined);
      };
      const client = new HttpClient({
        transport: {
          async send() {
            sends += 1;
            throw new Error("transport unavailable");
          },
        },
        retryPolicy: { maxAttempts: 2, baseDelayMs: 1, maxDelayMs: 1, jitter: false },
        instrumentation: {
          onError: () => phase === "onError" ? hang() : undefined,
          onRetry: () => phase === "onRetry" ? hang() : undefined,
        },
        sleep: async () => {
          if (phase === "sleep") await hang();
        },
      });

      await expect(client.request({ method: "GET", path: "/failure", signal: controller.signal })).rejects.toMatchObject({
        code: "memory.request_aborted",
        retryable: false,
        message: reason.message,
        cause: reason,
      });
      expect(sends).toBe(1);
    },
  );

  it.each([
    ["string", "cancel string", "memory.request_aborted", false],
    ["generic Error", new Error("cancel error"), "memory.request_aborted", false],
    ["AbortError", new DOMException("cancel abort", "AbortError"), "memory.request_aborted", false],
    ["TimeoutError", new DOMException("cancel timeout", "TimeoutError"), "memory.request_timeout", true],
  ] as const)("classifies caller %s reasons from the operation signal", async (_name, reason, code, retryable) => {
    const controller = new AbortController();
    const transport = new HangingTransport();
    const client = new HttpClient({ transport, timeoutMs: 0, retryPolicy: { maxAttempts: 2 } });
    const request = client.request({ method: "GET", path: "/cancel", signal: controller.signal });
    await waitForRecordedRequests(transport, 1);
    controller.abort(reason);

    try {
      await request;
      throw new Error("expected request to be cancelled");
    } catch (error) {
      expect(error).toMatchObject({ code, retryable, message: reason instanceof Error ? reason.message : reason });
      expect((error as Error).cause).toBe(reason);
    }
    expect(transport.requests).toHaveLength(1);
  });

  it.each([
    ["string", "cancel transport string", "memory.request_aborted", false],
    ["generic Error", new Error("cancel transport error"), "memory.request_aborted", false],
    ["AbortError", new DOMException("cancel transport abort", "AbortError"), "memory.request_aborted", false],
    ["TimeoutError", new DOMException("cancel transport timeout", "TimeoutError"), "memory.request_timeout", true],
  ] as const)("classifies direct FetchTransport %s abort reasons from the request signal", async (
    _name,
    reason,
    code,
    retryable,
  ) => {
    const controller = new AbortController();
    let fetchCalls = 0;
    let cancellations = 0;
    const fetchLike = ((_url: URL | RequestInfo, init?: RequestInit) => {
      fetchCalls += 1;
      init?.signal?.addEventListener("abort", () => { cancellations += 1; }, { once: true });
      return new Promise<Response>(() => undefined);
    }) as typeof fetch;
    const transport = new FetchTransport(fetchLike);
    const request = transport.send({
      method: "GET", url: new URL("http://memory.test/direct-cancel"), headers: new Headers(),
      signal: controller.signal,
    });
    controller.abort(reason);

    try {
      await request;
      throw new Error("expected direct transport request to be cancelled");
    } catch (error) {
      expect(error).toMatchObject({
        code,
        retryable,
        message: reason instanceof Error ? reason.message : reason,
      });
      expect((error as Error).cause).toBe(reason);
    }
    expect(fetchCalls).toBe(1);
    expect(cancellations).toBe(1);
  });

  it("propagates a caller abort when onResponse aborts synchronously and throws", async () => {
    const controller = new AbortController();
    const reason = new Error("cancel in response hook");
    let responses = 0;
    let errors = 0;
    const transport = new RecordingTransport([jsonResponse({ enabled_adapters: [] })]);
    const client = new InfinityContextClient({
      transport,
      retryPolicy: { maxAttempts: 2 },
      instrumentation: {
        onResponse: () => {
          responses += 1;
          controller.abort(reason);
          throw new Error("instrumentation failed after abort");
        },
        onError: () => { errors += 1; },
      },
    });

    await expect(client.system.capabilities({ signal: controller.signal })).rejects.toMatchObject({
      code: "memory.request_aborted",
      retryable: false,
      message: reason.message,
      cause: reason,
    });
    expect(transport.requests).toHaveLength(1);
    expect(responses).toBe(1);
    expect(errors).toBe(0);
  });

  it("bounds a never-settling fetch before response buffering begins", async () => {
    const fetchLike = (() => new Promise<Response>(() => undefined)) as typeof fetch;
    const transport = new FetchTransport(fetchLike);
    await expect(transport.send({
      method: "GET", url: new URL("http://memory.test/capabilities"), headers: new Headers(),
      signal: AbortSignal.timeout(10), responseType: "bytes", maxResponseBytes: 32,
    })).rejects.toMatchObject({ code: "memory.request_timeout" });
  });

  it("aborts and cancels a stalled response stream", async () => {
    let cancelCalls = 0;
    const fetchLike = (async () => new Response(new ReadableStream<Uint8Array>({
      cancel() { cancelCalls += 1; },
    }))) as typeof fetch;
    const transport = new FetchTransport(fetchLike);
    const controller = new AbortController();
    const response = transport.send({
      method: "GET", url: new URL("http://memory.test/stalled"), headers: new Headers(),
      signal: controller.signal, responseType: "bytes", maxResponseBytes: 32,
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    controller.abort();
    await expect(response).rejects.toMatchObject({ code: "memory.request_aborted" });
    expect(cancelCalls).toBe(1);
  });

  it("propagates caller aborts while a request is in flight", async () => {
    const controller = new AbortController();
    const transport = new HangingTransport();
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      timeoutMs: 0,
      retryPolicy: { maxAttempts: 1 },
    });

    const request = client.system.capabilities({ signal: controller.signal, timeoutMs: 1000 });
    await waitForRecordedRequests(transport, 1);
    controller.abort("cancel active request");

    await expect(request).rejects.toMatchObject({
      code: "memory.request_aborted",
      retryable: false,
    });
    expect(transport.requests[0]?.signal?.aborted).toBe(true);
  });

  it("keeps instrumentation hook failures from changing request results", async () => {
    const transport = new RecordingTransport([jsonResponse({ data: { id: "fact_1" } })]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
      instrumentation: {
        onRequest: () => {
          throw new Error("metrics sink unavailable");
        },
      },
    });

    const response = await client.facts.rememberFact({
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      text: "Remember user likes source-rich summaries.",
      sourceRefs: [{ source_type: "test", source_id: "case_1" }],
      idempotencyKey: "case_1",
    });

    expect(response.data.id).toBe("fact_1");
  });

  it("emits one error event for a final non-retryable HTTP error", async () => {
    const events: string[] = [];
    const transport = new RecordingTransport([
      jsonResponse({ error: { code: "bad_request", message: "invalid", retryable: false } }, 400),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
      instrumentation: {
        onRequest: () => {
          events.push("request");
        },
        onResponse: (event) => {
          events.push(`response:${event.statusCode}`);
        },
        onError: (event) => {
          events.push(`error:${event.error.code}`);
        },
      },
    });

    await expect(client.facts.getFact("fact_1")).rejects.toBeInstanceOf(InfinityContextError);
    expect(events).toEqual(["request", "response:400", "error:bad_request"]);
  });

  it("keeps unsafe writes from retrying unless an idempotency key exists", async () => {
    const noRetryTransport = new RecordingTransport([
      jsonResponse({ error: { code: "temporary", message: "try again", retryable: true } }, 503),
      jsonResponse({ data: { id: "fact_1" } }),
    ]);
    const noRetryClient = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport: noRetryTransport,
      sleep: async () => undefined,
      retryPolicy: { maxAttempts: 2, jitter: false },
    });

    await expect(
      noRetryClient.facts.updateFact("fact_1", {
        expectedVersion: 1,
        text: "updated",
        reason: "test",
        sourceRefs: [{ source_type: "test", source_id: "case" }],
      }),
    ).rejects.toBeInstanceOf(InfinityContextError);
    expect(noRetryTransport.requests).toHaveLength(1);

    const retryTransport = new RecordingTransport([
      jsonResponse({ error: { code: "temporary", message: "try again", retryable: true } }, 503),
      jsonResponse({ data: { id: "doc_1" } }),
    ]);
    const retryClient = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport: retryTransport,
      sleep: async () => undefined,
      retryPolicy: { maxAttempts: 2, jitter: false },
    });

    await retryClient.documents.processDocument("doc_1", { idempotencyKey: "process:doc_1" });

    expect(retryTransport.requests).toHaveLength(2);
    expect(retryTransport.requests[1]?.headers.get("idempotency-key")).toBe("process:doc_1");
  });

  it("uses bounded Retry-After headers for retry delays", async () => {
    const delays: number[] = [];
    const retries: number[] = [];
    const transport = new RecordingTransport([
      jsonResponse(
        { error: { code: "rate_limited", message: "slow down", retryable: true } },
        429,
        { "retry-after": "2" },
      ),
      jsonResponse(
        { error: { code: "temporary", message: "still slow", retryable: true } },
        503,
        { "retry-after": "120" },
      ),
      jsonResponse({ data: { status: "ok" } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      sleep: async (ms) => {
        delays.push(ms);
      },
      retryPolicy: {
        maxAttempts: 3,
        baseDelayMs: 10,
        maxDelayMs: 10,
        maxRetryAfterMs: 3000,
        jitter: false,
      },
      instrumentation: {
        onRetry: (event) => {
          retries.push(event.delayMs);
        },
      },
    });

    await client.system.capabilities();

    expect(delays).toEqual([2000, 3000]);
    expect(retries).toEqual([2000, 3000]);
    expect(transport.requests).toHaveLength(3);
  });

  it("parses Retry-After seconds and HTTP dates", () => {
    expect(parseRetryAfterMs("1.25", 1000)).toBe(1250);
    expect(parseRetryAfterMs("Wed, 21 Oct 2015 07:28:00 GMT", Date.parse("Wed, 21 Oct 2015 07:27:58 GMT")))
      .toBe(2000);
    expect(parseRetryAfterMs("Wed, 21 Oct 2015 07:27:00 GMT", Date.parse("Wed, 21 Oct 2015 07:28:00 GMT")))
      .toBe(0);
    expect(parseRetryAfterMs("not a date", 1000)).toBeUndefined();
  });

  it("redacts sensitive data from HTTP errors", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        error: {
          code: "memory.bad_request",
          message: "bad Authorization: Bearer secret-token and ?api_key=abc",
          retryable: false,
        },
      }, 400),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    try {
      await client.system.capabilities();
      throw new Error("expected capabilities to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(InfinityContextError);
      const sdkError = error as InfinityContextError;
      expect(sdkError.code).toBe("memory.bad_request");
      expect(sdkError.message).toBe("bad Authorization: [REDACTED] and ?api_key=[REDACTED]");
      expect(sdkError.retryable).toBe(false);
    }
  });

  it("downloads byte responses without JSON parsing", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const transport = new RecordingTransport([{ status: 200, headers: new Headers(), body: bytes }]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(client.assets.downloadAsset("asset_1")).resolves.toEqual(bytes);
  });
});
