import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  parseRetryAfterMs,
} from "../src/index.js";
import {
  HangingTransport,
  RecordingTransport,
  jsonResponse,
  waitForRecordedRequests,
} from "./fixtures.js";

describe("transport, retry and errors", () => {
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
