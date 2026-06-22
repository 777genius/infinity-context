import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  MemoryScope,
  ReadScope,
  ValueError,
  assertMemoryBriefQuality,
  assertFullMemoryReady,
  evaluateMemoryBriefQuality,
  evaluateRuntimeReadiness,
  healthyRetrievalComponents,
  retrievalDiagnostics,
  runRuntimeCanary,
  parseRetryAfterMs,
  summarizeMemoryBriefEvidence,
  summarizeSourceEvidenceBatch,
  usedDerivedRetrieval,
  waitForRuntimeCanary,
  type BuildMemoryBriefResult,
} from "../src/index.js";
import {
  HangingTransport,
  RecordingTransport,
  anchorRecord,
  assetExtractionJobRecord,
  captureRecord,
  contextLinkRecord,
  contextLinkSuggestionRecord,
  contextResponse,
  digestResponse,
  documentChunkRecord,
  documentRecord,
  expectCompletedSignalsDetached,
  extractionArtifactRecord,
  factRecord,
  jsonResponse,
  membershipRecord,
  memoryBrowserData,
  memorySuggestionRecord,
  operationsConsoleData,
  outboxItem,
  scopeRecord,
  searchResponse,
  spaceRecord,
  userRecord,
  waitForRecordedRequests,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
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

  it("passes per-request controls through context calls", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse(contextResponse("controls", {
        vector_status: "ok",
        graph_status: "ok",
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await client.context.buildContext({
      query: "daily digest preferences",
      readScope: ReadScope.external({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: ["workspace-global", "user:user_1"],
      }),
      signal: controller.signal,
      headers: { "x-trace-id": "trace_1" },
    });

    const requestSignal = transport.requests[0]?.signal;
    expect(requestSignal).toBeDefined();
    expect(requestSignal?.aborted).toBe(false);
    controller.abort("cancel context");
    expect(requestSignal?.aborted).toBe(false);
    expect(requestSignal?.reason).toBeUndefined();
    expect(transport.requests[0]?.headers.get("x-trace-id")).toBe("trace_1");
    expect(transport.bodies[0]).not.toHaveProperty("headers");
    expect(transport.bodies[0]).not.toHaveProperty("signal");
  });

  it("passes per-request controls through operational resource clients", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport(Array.from({ length: 11 }, () => jsonResponse({ data: { ok: true } })));
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });
    const controls = {
      signal: controller.signal,
      headers: { "x-trace-id": "trace_resource_controls" },
    };
    const scope = {
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
    };

    await client.system.health(controls);
    await client.system.capabilities(controls);
    await client.spaces.listSpaces({ ...controls, limit: 1 });
    await client.users.listUsers({ ...controls, limit: 1 });
    await client.assets.getAsset("asset_1", controls);
    await client.anchors.listAnchors({ ...controls, ...scope, limit: 1 });
    await client.suggestions.reviewSuggestionsBatch([{ suggestion_id: "sugg_1", action: "reject" }], controls);
    await client.diagnostics.outbox({ ...controls, limit: 1 });
    await client.readModels.getMemoryBrowser({ ...controls, ...scope, limit: 1 });
    await client.usage.summary({ ...controls, spaceSlug: scope.spaceSlug });
    await client.threadMemory.status({ ...controls, ...scope, threadExternalRef: "thread_1" });

    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 11 }, () => "trace_resource_controls"),
    );
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel resources");
    expect(transport.bodies.every((body) => !Object.hasOwn(body as object, "headers"))).toBe(true);
    expect(transport.bodies.every((body) => !Object.hasOwn(body as object, "signal"))).toBe(true);
  });

  it("passes per-request controls through paginated fact scans", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: [factRecord("fact_1")], next_cursor: "cursor_2" }),
      jsonResponse({ data: [factRecord("fact_2")], next_cursor: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const facts = await client.facts.listAllFacts(
      {
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:preferences",
      },
      {
        pageLimit: 1,
        signal: controller.signal,
        headers: { "x-worker-id": "worker_1" },
      },
    );

    expect(facts.map((fact) => fact.id)).toEqual(["fact_1", "fact_2"]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel scan");
    expect(transport.requests.map((request) => request.headers.get("x-worker-id"))).toEqual([
      "worker_1",
      "worker_1",
    ]);
  });

  it("iterates diagnostics outbox items with opaque cursors", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          counts: { pending: 2 },
          oldest_active_lag_seconds: 30,
          items: [outboxItem(1, "pending")],
          next_cursor: "outbox_cursor_2",
        },
      }),
      jsonResponse({
        data: {
          counts: { pending: 1, done: 1 },
          oldest_active_lag_seconds: 10,
          items: [outboxItem(2, "retry_pending"), outboxItem(3, "done")],
          next_cursor: null,
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const items = await client.diagnostics.listAllOutboxItems({
      pageLimit: 1,
      maxItems: 2,
      signal: controller.signal,
      headers: { "x-worker-id": "worker_outbox" },
    });

    expect(items.map((item) => [item.id, item.status])).toEqual([
      [1, "pending"],
      [2, "retry_pending"],
    ]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/diagnostics/outbox?limit=1",
      "http://memory.test/v1/diagnostics/outbox?limit=1&cursor=outbox_cursor_2",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-worker-id"))).toEqual([
      "worker_outbox",
      "worker_outbox",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel outbox scan");
  });

  it("waits for diagnostics outbox drain", async () => {
    const controller = new AbortController();
    const sleeps: number[] = [];
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          counts: { pending: 1, retry_pending: 1 },
          oldest_active_lag_seconds: 45,
          items: [outboxItem(1, "pending"), outboxItem(2, "retry_pending")],
          next_cursor: null,
        },
      }),
      jsonResponse({
        data: {
          counts: { done: 2, pending: 0, retry_pending: 0 },
          oldest_active_lag_seconds: null,
          items: [outboxItem(1, "done"), outboxItem(2, "done")],
          next_cursor: null,
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const drained = await client.diagnostics.waitForOutboxDrain({
      limit: 2,
      maxAttempts: 3,
      pollIntervalMs: 7,
      signal: controller.signal,
      headers: { "x-worker-id": "worker_outbox_drain" },
      sleep: async (ms) => {
        sleeps.push(ms);
      },
      throwOnFailure: true,
    });

    expect(drained.diagnostics).toMatchObject({
      attempts: 2,
      blocking_count: 0,
      failure_count: 0,
      max_blocking_items: 0,
      listed_blocking_item_ids: [],
    });
    expect(sleeps).toEqual([7]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/diagnostics/outbox?limit=2",
      "http://memory.test/v1/diagnostics/outbox?limit=2",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-worker-id"))).toEqual([
      "worker_outbox_drain",
      "worker_outbox_drain",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel outbox drain");

    const failureTransport = new RecordingTransport([
      jsonResponse({
        data: {
          counts: { failed: 0 },
          oldest_active_lag_seconds: 120,
          items: [outboxItem(9, "failed")],
          next_cursor: null,
        },
      }),
    ]);
    const failureClient = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport: failureTransport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      failureClient.diagnostics.waitForOutboxDrain({ throwOnFailure: true }),
    ).rejects.toMatchObject({
      code: "memory.outbox_drain_failed",
      retryable: false,
    });
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

  it("maps external read scopes to typed context payloads", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          bundle_id: "bundle_1",
          rendered_text: "",
          items: [],
          top_evidence: [],
          answer_support: {
            status: "insufficient_evidence",
            items_returned: 0,
            coverage: {},
            policy: {},
            warnings: [],
          },
          diagnostics: {
            vector_status: "ok",
            graph_status: "ok",
            rag_status: "ok",
            query_decomposition_status: "available",
            query_decomposition_count: 2,
            query_decomposition_reasons: ["decomposition_event_context"],
            vector_query_count: 6,
            vector_query_limit: 15,
            vector_query_degraded_count: 0,
            graph_query_count: 4,
            graph_query_limit: 10,
            graph_query_degraded_count: 0,
            rag_query_count: 5,
            rag_query_limit: 12,
            rag_candidate_count: 7,
            rag_hydrated_count: 3,
            rag_query_degraded_count: 0,
          },
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const response = await client.context.buildContext({
      query: "daily digest preferences",
      readScope: ReadScope.external({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: ["workspace-global", "user:user_1"],
      }),
      includeStale: false,
    });

    expect(response.data.diagnostics.query_decomposition_status).toBe("available");
    expect(response.data.diagnostics.vector_status).toBe("ok");
    expect(response.data.diagnostics.graph_status).toBe("ok");
    expect(response.data.diagnostics.vector_query_count).toBe(6);
    expect(response.data.diagnostics.graph_query_count).toBe(4);
    expect(response.data.diagnostics.rag_query_count).toBe(5);
    expect(usedDerivedRetrieval(response.data.diagnostics)).toBe(true);
    expect(healthyRetrievalComponents(response.data.diagnostics, ["vector", "graph", "rag"])).toBe(true);
    expect(retrievalDiagnostics(response.data.diagnostics, "rag")).toEqual({
      component: "rag",
      status: "ok",
      queryCount: 5,
      queryLimit: 12,
      candidateCount: 7,
      hydratedCount: 3,
      staleDropCount: undefined,
      degradedCount: 0,
      degradedReason: undefined,
      degradedStep: undefined,
      deadlineSeconds: undefined,
    });
    expect(transport.requests[0]?.url.toString()).toBe("http://memory.test/v1/context");
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_refs: ["workspace-global", "user:user_1"],
      query: "daily digest preferences",
      token_budget: 1800,
      max_facts: 20,
      max_chunks: 30,
    });
    expect(transport.bodies[0]).not.toHaveProperty("include_stale");
  });

  it("evaluates full memory runtime readiness from capabilities and retrieval diagnostics", () => {
    const report = evaluateRuntimeReadiness({
      capabilities: {
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      },
      diagnostics: {
        vector_status: "ok",
        graph_status: "ok",
        vector_query_count: 4,
        graph_query_count: 3,
      },
      requireDerivedRetrieval: true,
    });

    expect(report).toMatchObject({
      ok: true,
      mode: "full",
      missingAdapters: [],
      unhealthyRetrieval: [],
      derivedRetrievalUsed: true,
      supportsQdrant: true,
      supportsGraphiti: true,
    });
  });

  it("throws a typed error when full memory runtime is not ready", () => {
    try {
      assertFullMemoryReady(
        {
          enabled_adapters: [],
          supports_qdrant: true,
          supports_graphiti: true,
        },
        {
          vector_status: "degraded",
          graph_status: "ok",
          vector_query_count: 0,
          graph_query_count: 0,
        },
      );
      throw new Error("expected runtime readiness failure");
    } catch (error) {
      expect(error).toBeInstanceOf(InfinityContextError);
      expect((error as InfinityContextError).code).toBe("memory.runtime_not_ready");
      expect((error as InfinityContextError).message).toContain("Missing runtime adapter: qdrant");
      expect((error as InfinityContextError).message).toContain("Unhealthy vector retrieval: degraded");
      expect((error as InfinityContextError).details).toMatchObject({
        mode: "lite",
        missingAdapters: ["qdrant", "graphiti"],
        unhealthyRetrieval: ["vector"],
        warnings: [
          "Qdrant is supported by this service but not enabled in the current runtime",
          "Graphiti is supported by this service but not enabled in the current runtime",
        ],
      });
    }
  });

  it("runs a non-mutating runtime canary against full memory retrieval", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: ["qdrant", "graphiti"], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary", {
        retrieval_sources_used: ["vector", "graph"],
        vector_status: "ok",
        graph_status: "ok",
        vector_query_count: 3,
        graph_query_count: 2,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["vector"],
        vector_status: "ok",
        graph_status: "ok",
        vector_query_count: 2,
        graph_query_count: 1,
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const report = await runRuntimeCanary({
      client,
      query: "Prove full memory runtime without mutating state",
      spaceSlug: "workspace",
      memoryScopeExternalRefs: ["workspace-global", "topic:ai-agents"],
      includeSearchProbe: true,
      tokenBudget: 900,
      maxFacts: 8,
      maxChunks: 6,
    });

    expect(report).toMatchObject({
      ok: true,
      mode: "full",
      query: "Prove full memory runtime without mutating state",
      probes: { context: true, search: true, diagnosticsSource: "context" },
      capabilities: {
        enabledAdapters: ["qdrant", "graphiti"],
        supportsQdrant: true,
        supportsGraphiti: true,
      },
      errors: [],
    });
    expect(report.readiness).toMatchObject({
      ok: true,
      missingAdapters: [],
      unhealthyRetrieval: [],
      derivedRetrievalUsed: true,
    });
    expect(report.diagnostics?.context?.vector_query_count).toBe(3);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "POST /v1/context",
      "POST /v1/search",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      query: "Prove full memory runtime without mutating state",
      space_slug: "workspace",
      memory_scope_external_refs: ["workspace-global", "topic:ai-agents"],
      token_budget: 900,
      max_facts: 8,
      max_chunks: 6,
    });
  });

  it("reports runtime canary failures without mutating memory", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: [], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary-lite", {
        vector_status: "degraded",
        graph_status: "disabled",
        vector_query_count: 0,
        graph_query_count: 0,
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const report = await runRuntimeCanary({
      client,
      query: "Detect lite runtime before beta promotion",
      spaceSlug: "workspace",
      memoryScopeExternalRefs: ["workspace-global"],
    });

    expect(report.ok).toBe(false);
    expect(report.mode).toBe("lite");
    expect(report.errors).toEqual([
      "Missing runtime adapter: qdrant",
      "Missing runtime adapter: graphiti",
      "Unhealthy vector retrieval: degraded",
      "Unhealthy graph retrieval: disabled",
      "Derived retrieval was not used",
    ]);
    expect(report.warnings).toEqual([
      "Qdrant is supported by this service but not enabled in the current runtime",
      "Graphiti is supported by this service but not enabled in the current runtime",
    ]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "POST /v1/context",
    ]);
  });

  it("waits for runtime canary readiness with abortable polling", async () => {
    const controller = new AbortController();
    const sleeps: number[] = [];
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: [], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary-wait-lite", {
        vector_status: "disabled",
        graph_status: "disabled",
        vector_query_count: 0,
        graph_query_count: 0,
      })),
      jsonResponse({ enabled_adapters: ["qdrant", "graphiti"], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary-wait-full", {
        retrieval_sources_used: ["vector", "graph"],
        vector_status: "ok",
        graph_status: "ok",
        vector_query_count: 2,
        graph_query_count: 1,
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const report = await waitForRuntimeCanary({
      client,
      query: "Wait until full memory runtime is serving derived retrieval",
      spaceSlug: "workspace",
      memoryScopeExternalRefs: ["workspace-global"],
      maxAttempts: 3,
      pollIntervalMs: 5,
      signal: controller.signal,
      headers: { "x-trace-id": "trace_canary_wait" },
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });

    expect(report.ok).toBe(true);
    expect(report.attempts).toBe(2);
    expect(report.mode).toBe("full");
    expect(sleeps).toEqual([5]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "POST /v1/context",
      "GET /v1/capabilities",
      "POST /v1/context",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual([
      "trace_canary_wait",
      "trace_canary_wait",
      "trace_canary_wait",
      "trace_canary_wait",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel runtime canary wait");
  });

  it("times out runtime canary waits with typed readiness details", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: [], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary-timeout-1", {
        vector_status: "disabled",
        graph_status: "disabled",
        vector_query_count: 0,
        graph_query_count: 0,
      })),
      jsonResponse({ enabled_adapters: [], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("canary-timeout-2", {
        vector_status: "degraded",
        graph_status: "disabled",
        vector_query_count: 0,
        graph_query_count: 0,
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      waitForRuntimeCanary({
        client,
        query: "Wait for full memory runtime",
        spaceSlug: "workspace",
        memoryScopeExternalRefs: ["workspace-global"],
        maxAttempts: 2,
        pollIntervalMs: 0,
      }),
    ).rejects.toMatchObject({
      code: "memory.runtime_canary_timeout",
      retryable: true,
      details: {
        max_attempts: 2,
        last_attempts: 2,
        last_mode: "lite",
        last_enabled_adapters: [],
      },
    });
  });

  it("collects paginated facts through typed cursor helpers", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [factRecord("fact_1"), factRecord("fact_2")], next_cursor: "cursor_2" }),
      jsonResponse({ data: [factRecord("fact_3")], next_cursor: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const facts = await client.facts.listAllFacts(
      {
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:preferences",
        tag: "summary",
      },
      { pageLimit: 2, maxItems: 3 },
    );

    expect(facts.map((fact) => fact.id)).toEqual(["fact_1", "fact_2", "fact_3"]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/facts?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Apreferences&status=active&tag=summary&limit=2",
      "http://memory.test/v1/facts?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Apreferences&status=active&tag=summary&limit=2&cursor=cursor_2",
    ]);
  });

  it("iterates document chunks with opaque cursors", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [documentChunkRecord("chunk_1", 1)], next_cursor: "chunk_cursor_2" }),
      jsonResponse({ data: [documentChunkRecord("chunk_2", 2)], next_cursor: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const chunks = [];
    for await (const chunk of client.documents.iterateDocumentChunks("doc_1", { pageLimit: 1 })) {
      chunks.push(chunk);
    }

    expect(chunks.map((chunk) => chunk.id)).toEqual(["chunk_1", "chunk_2"]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/documents/doc_1/chunks?limit=1",
      "http://memory.test/v1/documents/doc_1/chunks?limit=1&cursor=chunk_cursor_2",
    ]);
  });

  it("records feedback through the workflow facade with safe capture defaults", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          ...captureRecord("capture_1"),
          duplicate: false,
          created_suggestions: 0,
          suggestion_ids: [],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: factRecord("fact_1") }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const result = await client.workflows.recordFeedback({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents:feedback",
      threadExternalRef: "digest-run:1",
      sourceAgent: "social-monitor",
      sourceId: "feedback:1",
      sourceActorExternalRef: "user_1",
      text: "User wants Reddit freshness and primary citations in daily summaries.",
      idempotencyKey: "feedback:1",
      factMemoryScopeExternalRef: "topic:ai-agents:preferences",
      factTags: ["summary", "freshness"],
    });

    expect(result.capture.data.id).toBe("capture_1");
    expect(result.fact?.data.id).toBe("fact_1");
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/captures",
      "POST /v1/facts",
    ]);
    expect(transport.requests[0]?.headers.get("idempotency-key")).toBe("feedback:1");
    expect(transport.requests[1]?.headers.get("idempotency-key")).toBe("feedback:1:fact");
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "topic:ai-agents:feedback",
      thread_external_ref: "digest-run:1",
      source_agent: "social-monitor",
      source_kind: "hook",
      event_type: "memory.feedback.recorded",
      actor_role: "user",
      source_authority: "user_statement",
      trust_level: "high",
      data_classification: "internal",
      evidence_refs: [{ source_type: "social-monitor", source_id: "feedback:1" }],
      consolidate: true,
    });
    expect(transport.bodies[1]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "topic:ai-agents:preferences",
      thread_external_ref: "digest-run:1",
      text: "User wants Reddit freshness and primary citations in daily summaries.",
      kind: "user_preference",
      category: "feedback",
      tags: ["summary", "freshness"],
      ttl_policy: "durable",
      source_refs: [
        { source_type: "capture", source_id: "capture_1" },
        { source_type: "social-monitor", source_id: "feedback:1" },
      ],
    });
  });

  it("records source evidence through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: documentRecord("doc_1") }, 201),
      jsonResponse({ data: documentRecord("doc_1") }),
      jsonResponse({ data: { id: "episode_1", status: "active" } }, 201),
      jsonResponse({
        data: {
          ...captureRecord("capture_1"),
          duplicate: false,
          created_suggestions: 0,
          suggestion_ids: [],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: factRecord("fact_1") }, 201),
      jsonResponse({
        data: {
          candidates: [
            {
              target_type: "fact",
              target_id: "fact_1",
              label: "Reddit freshness",
              preview: "Primary-source freshness preference",
              score: 0.92,
              reasons: ["semantic_overlap"],
              suggestion_id: "ctx_suggestion_1",
              status: "pending",
              metadata: {},
            },
          ],
          diagnostics: { persisted: true },
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const result = await client.workflows.recordSourceEvidence({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "source:reddit:ai-agents",
      threadExternalRef: "scan:2026-06-22",
      sourceAgent: "social-monitor",
      sourceType: "reddit",
      sourceId: "reddit:t3_abc",
      title: "Reddit discussion on agent memory",
      text: "Operators want Reddit freshness, citations and source scoring in summaries.",
      occurredAt: "2026-06-22T10:00:00.000Z",
      idempotencyKey: "reddit:t3_abc",
      signal: controller.signal,
      headers: { "x-trace-id": "trace_source_evidence" },
      metadata: { provider: "reddit", subreddit: "LocalLLaMA" },
      document: { process: true, classification: "public" },
      fact: {
        memoryScopeExternalRef: "topic:ai-agents:preferences",
        category: "source_signal",
        tags: ["reddit", "freshness"],
      },
      linkSuggestions: { persist: true, limit: 5 },
    });

    expect(result.document?.data.id).toBe("doc_1");
    expect(result.processedDocument?.data.id).toBe("doc_1");
    expect(result.episode?.data.id).toBe("episode_1");
    expect(result.capture?.data.id).toBe("capture_1");
    expect(result.fact?.data.id).toBe("fact_1");
    expect(result.linkSuggestions?.data.candidates).toHaveLength(1);
    expect(result.sourceRefs).toEqual([
      { source_type: "reddit", source_id: "reddit:t3_abc" },
      { source_type: "document", source_id: "doc_1" },
      { source_type: "episode", source_id: "episode_1" },
      { source_type: "capture", source_id: "capture_1" },
    ]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/documents",
      "POST /v1/documents/doc_1/process",
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/facts",
      "POST /v1/link-suggestions",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual([
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel source evidence");
    expect(transport.requests.map((request) => request.headers.get("idempotency-key"))).toEqual([
      "reddit:t3_abc:document",
      "reddit:t3_abc:document:process",
      "reddit:t3_abc:episode",
      "reddit:t3_abc:capture",
      "reddit:t3_abc:fact",
      null,
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "source:reddit:ai-agents",
      thread_external_ref: "scan:2026-06-22",
      title: "Reddit discussion on agent memory",
      source_type: "reddit",
      source_external_id: "reddit:t3_abc",
      classification: "public",
      source_refs: [{ source_type: "reddit", source_id: "reddit:t3_abc" }],
    });
    expect(transport.bodies[1]).toMatchObject({
      source_type: "reddit",
      source_external_id: "reddit:t3_abc",
      trust_level: "medium",
      kind_hint: "fact_evidence",
      metadata: { provider: "reddit", subreddit: "LocalLLaMA" },
    });
    expect(transport.bodies[2]).toMatchObject({
      source_agent: "social-monitor",
      source_kind: "document",
      event_type: "memory.source_evidence.recorded",
      actor_role: "tool",
      source_authority: "tool_verified",
      evidence_refs: [
        { source_type: "reddit", source_id: "reddit:t3_abc" },
        { source_type: "document", source_id: "doc_1" },
        { source_type: "episode", source_id: "episode_1" },
      ],
      consolidate: true,
    });
    expect(transport.bodies[3]).toMatchObject({
      memory_scope_external_ref: "topic:ai-agents:preferences",
      kind: "source_signal",
      category: "source_signal",
      tags: ["reddit", "freshness"],
      source_refs: [
        { source_type: "document", source_id: "doc_1" },
        { source_type: "episode", source_id: "episode_1" },
        { source_type: "capture", source_id: "capture_1" },
        { source_type: "reddit", source_id: "reddit:t3_abc" },
      ],
    });
    expect(transport.bodies[4]).toMatchObject({
      source_type: "capture",
      source_id: "capture_1",
      limit: 5,
      persist: true,
    });
  });

  it("records source evidence batches with per-item errors", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: { id: "episode_1", status: "active" } }, 201),
      jsonResponse({
        data: {
          ...captureRecord("capture_1"),
          duplicate: false,
          created_suggestions: 0,
          suggestion_ids: [],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: { candidates: [], diagnostics: {} } }),
      jsonResponse({
        error: {
          code: "memory.provider_payload_invalid",
          message: "provider payload rejected",
          retryable: false,
        },
      }, 400, { "x-request-id": "req_bad_item" }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const batch = await client.workflows.recordSourceEvidenceBatch({
      concurrency: 1,
      continueOnError: true,
      signal: controller.signal,
      headers: { "x-batch-id": "batch_1" },
      items: [
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "source:reddit:ai-agents",
          sourceAgent: "social-monitor",
          sourceType: "reddit",
          sourceId: "reddit:t3_ok",
          text: "First provider item should be stored.",
          idempotencyKey: "reddit:t3_ok",
        },
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "source:reddit:ai-agents",
          sourceAgent: "social-monitor",
          sourceType: "reddit",
          sourceId: "reddit:t3_bad",
          text: "Second provider item should fail.",
          idempotencyKey: "reddit:t3_bad",
          headers: { "x-item-id": "item_bad" },
        },
      ],
    });

    expect(batch).toMatchObject({
      total: 2,
      succeeded: 1,
      failed: 1,
      stopped: false,
    });
    expect(batch.results[0]).toMatchObject({
      index: 0,
      sourceType: "reddit",
      sourceId: "reddit:t3_ok",
      idempotencyKey: "reddit:t3_ok",
      ok: true,
    });
    expect(batch.results[0]?.result?.episode?.data.id).toBe("episode_1");
    expect(batch.results[1]).toMatchObject({
      index: 1,
      sourceType: "reddit",
      sourceId: "reddit:t3_bad",
      idempotencyKey: "reddit:t3_bad",
      ok: false,
      error: {
        name: "InfinityContextError",
        code: "memory.provider_payload_invalid",
        statusCode: 400,
        retryable: false,
        requestId: "req_bad_item",
      },
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/link-suggestions",
      "POST /v1/episodes",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-batch-id"))).toEqual([
      "batch_1",
      "batch_1",
      "batch_1",
      "batch_1",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-item-id"))).toEqual([
      null,
      null,
      null,
      "item_bad",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel batch");
  });

  it("stops source evidence batches after the first error when configured", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        error: {
          code: "memory.provider_payload_invalid",
          message: "provider payload rejected",
          retryable: false,
        },
      }, 400),
      jsonResponse({ data: { id: "episode_after_stop", status: "active" } }, 201),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const batch = await client.workflows.recordSourceEvidenceBatch({
      concurrency: 1,
      continueOnError: false,
      items: [
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "source:reddit:ai-agents",
          sourceAgent: "social-monitor",
          sourceType: "reddit",
          sourceId: "reddit:t3_bad",
          text: "Bad provider item.",
          idempotencyKey: "reddit:t3_bad",
        },
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "source:reddit:ai-agents",
          sourceAgent: "social-monitor",
          sourceType: "reddit",
          sourceId: "reddit:t3_skipped",
          text: "This item should not be scheduled.",
          idempotencyKey: "reddit:t3_skipped",
        },
      ],
    });

    expect(batch).toMatchObject({
      total: 2,
      succeeded: 0,
      failed: 1,
      stopped: true,
    });
    expect(batch.results).toHaveLength(1);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/episodes",
    ]);
  });

  it("summarizes source evidence batch outcomes for observability", () => {
    const summary = summarizeSourceEvidenceBatch({
      total: 4,
      succeeded: 1,
      failed: 2,
      stopped: true,
      results: [
        {
          index: 0,
          sourceType: "reddit",
          sourceId: "reddit:t3_ok",
          idempotencyKey: "reddit:t3_ok",
          ok: true,
          result: { sourceRefs: [{ source_type: "reddit", source_id: "reddit:t3_ok" }] },
        },
        {
          index: 1,
          sourceType: "reddit",
          sourceId: "reddit:t3_retry",
          idempotencyKey: "reddit:t3_retry",
          ok: false,
          error: {
            name: "InfinityContextError",
            message: "rate limited",
            code: "provider.rate_limited",
            statusCode: 429,
            retryable: true,
            requestId: "req_retry",
          },
        },
        {
          index: 2,
          sourceType: "github",
          sourceId: "github:issue_1",
          idempotencyKey: "github:issue_1",
          ok: false,
          error: {
            name: "InfinityContextError",
            message: "bad payload",
            code: "provider.bad_payload",
            statusCode: 400,
            retryable: false,
          },
        },
      ],
    });

    expect(summary).toEqual({
      total: 4,
      completed: 3,
      skipped: 1,
      succeeded: 1,
      failed: 2,
      stopped: true,
      successRate: 0.25,
      failureRate: 0.5,
      retryableFailures: 1,
      nonRetryableFailures: 1,
      bySourceType: { reddit: 2, github: 1 },
      byErrorCode: { "provider.rate_limited": 1, "provider.bad_payload": 1 },
      byStatusCode: { "400": 1, "429": 1 },
      failedItems: [
        {
          index: 1,
          sourceType: "reddit",
          sourceId: "reddit:t3_retry",
          idempotencyKey: "reddit:t3_retry",
          error: {
            name: "InfinityContextError",
            message: "rate limited",
            code: "provider.rate_limited",
            statusCode: 429,
            retryable: true,
            requestId: "req_retry",
          },
        },
        {
          index: 2,
          sourceType: "github",
          sourceId: "github:issue_1",
          idempotencyKey: "github:issue_1",
          error: {
            name: "InfinityContextError",
            message: "bad payload",
            code: "provider.bad_payload",
            statusCode: 400,
            retryable: false,
          },
        },
      ],
    });
  });

  it("builds a memory brief workflow across context, search and digest", async () => {
    const transport = new RecordingTransport([
      jsonResponse(contextResponse("brief", {
        retrieval_sources_used: ["keyword", "vector"],
        vector_query_count: 2,
        graph_query_count: 1,
        rag_query_count: 1,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["graph"],
        vector_query_count: 2,
        graph_query_count: 1,
      })),
      jsonResponse(digestResponse("brief")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const brief = await client.workflows.buildMemoryBrief({
      query: "What should today's AI digest prioritize?",
      topic: "AI digest",
      readScope: ReadScope.external({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: ["workspace-global", "topic:ai-agents:preferences"],
      }),
      tokenBudget: 1200,
      maxFacts: 12,
      maxChunks: 8,
    });

    expect(brief.context.data.bundle_id).toBe("bundle_1");
    expect(brief.search?.data.items).toHaveLength(1);
    expect(brief.digest?.data.digest_id).toBe("digest_1");
    expect(brief.diagnostics).toMatchObject({
      derivedRetrievalUsed: true,
      vectorHealthy: true,
      graphHealthy: true,
      ragHealthy: true,
      retrievalSourcesUsed: ["keyword", "vector", "graph"],
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      memory_scope_external_refs: ["workspace-global", "topic:ai-agents:preferences"],
      query: "What should today's AI digest prioritize?",
      token_budget: 1200,
      max_facts: 12,
      max_chunks: 8,
    });
    expect(transport.bodies[2]).toMatchObject({
      topic: "AI digest",
      token_budget: 1200,
      max_facts: 12,
      max_chunks: 8,
    });
  });

  it("evaluates memory brief quality for release gates", async () => {
    const transport = new RecordingTransport([
      jsonResponse(contextResponse("brief-quality", {
        retrieval_sources_used: ["vector", "graph", "rag"],
        vector_query_count: 2,
        graph_query_count: 1,
        rag_query_count: 1,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["graph"],
        graph_query_count: 1,
      })),
      jsonResponse(digestResponse("brief-quality")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });
    const brief = await client.workflows.buildMemoryBrief({
      query: "What should today's AI digest prioritize?",
      topic: "AI digest",
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRefs: ["workspace-global", "topic:ai-agents:preferences"],
    });

    const quality = assertMemoryBriefQuality(brief, {
      requireSearch: true,
      minSearchItems: 1,
      requireDigest: true,
      requireDerivedRetrieval: true,
      requiredRetrieval: ["vector", "graph", "rag"],
    });

    expect(quality).toMatchObject({
      ok: true,
      errors: [],
      metrics: {
        contextItems: 1,
        contextSourceRefs: 1,
        topEvidenceItems: 0,
        searchItems: 1,
        digestSections: 0,
        digestSourceRefs: 0,
      },
      retrieval: {
        derivedRetrievalUsed: true,
        vectorHealthy: true,
        graphHealthy: true,
        ragHealthy: true,
        retrievalSourcesUsed: ["vector", "graph", "rag"],
      },
    });
  });

  it("summarizes memory brief evidence across context, search, digest and citations", () => {
    const brief: BuildMemoryBriefResult = {
      context: {
        data: {
          ...contextResponse("evidence", {
            retrieval_sources_used: ["vector", "graph"],
            vector_query_count: 2,
            graph_query_count: 1,
          }).data,
          items: [
            {
              item_id: "ctx_1",
              item_type: "fact",
              text: "Reddit source says users want freshness.",
              score: 0.9,
              source_refs: [{ source_type: "reddit", source_id: "t3_ai_agents" }],
              citations: [{ label: "R1", source_type: "reddit", source_id: "t3_ai_agents" }],
            },
            {
              item_id: "ctx_missing",
              item_type: "fact",
              text: "Unattributed evidence should be visible.",
              score: 0.1,
              source_refs: [],
            },
          ],
          top_evidence: [
            {
              item: {
                item_id: "top_1",
                item_type: "fact",
                text: "GitHub issue mentions rate limits.",
                score: 0.8,
                source_refs: [{ source_type: "github", source_id: "issue_1" }],
              },
              citation: { label: "G1", source_type: "github", source_id: "issue_1" },
              score: 0.8,
              reasons: ["fresh"],
            },
          ],
        },
      },
      search: {
        data: {
          items: [
            {
              item_id: "search_1",
              item_type: "fact",
              text: "HN post covers launch context.",
              score: 0.7,
              source_refs: [{ source_type: "hackernews", source_id: "item_1" }],
            },
          ],
          top_evidence: [],
          diagnostics: {
            vector_status: "ok",
            graph_status: "ok",
          },
        },
      },
      digest: {
        data: {
          ...digestResponse("evidence").data,
          sections: [
            {
              title: "Sources",
              truncated: false,
              items: [
                {
                  item_id: "digest_1",
                  item_type: "fact",
                  text: "Digest cites Reddit again.",
                  score: 0.85,
                  source_refs: [{ source_type: "reddit", source_id: "t3_ai_agents" }],
                },
              ],
            },
          ],
          source_refs: [
            { source_type: "reddit", source_id: "t3_ai_agents" },
            { source_type: "github", source_id: "issue_1" },
          ],
        },
      },
      diagnostics: {
        derivedRetrievalUsed: true,
        vectorHealthy: true,
        graphHealthy: true,
        ragHealthy: false,
        retrievalSourcesUsed: ["vector", "graph"],
        warnings: [],
      },
    };

    const evidence = summarizeMemoryBriefEvidence(brief);

    expect(evidence).toMatchObject({
      contextItems: 2,
      searchItems: 1,
      digestSections: 1,
      topEvidenceItems: 1,
      sourceRefsTotal: 8,
      uniqueSourceRefs: 3,
      citationsTotal: 2,
      uniqueCitations: 2,
      bySourceType: {
        github: 3,
        hackernews: 1,
        reddit: 4,
      },
      bySurface: {
        context: 2,
        search: 1,
        digest: 3,
        top_evidence: 2,
      },
      citationLabels: ["G1", "R1"],
      missingSourceRefItemIds: ["ctx_missing"],
    });
    expect(evidence.sourceRefs).toEqual([
      {
        sourceType: "reddit",
        sourceId: "t3_ai_agents",
        count: 4,
        surfaces: ["context", "digest"],
      },
      {
        sourceType: "github",
        sourceId: "issue_1",
        count: 3,
        surfaces: ["digest", "top_evidence"],
      },
      {
        sourceType: "hackernews",
        sourceId: "item_1",
        count: 1,
        surfaces: ["search"],
      },
    ]);
  });

  it("throws typed memory brief quality failures with diagnostics", () => {
    const poorBrief: BuildMemoryBriefResult = {
      context: {
        data: {
          ...contextResponse("poor-brief", {
            retrieval_sources_used: ["keyword"],
            vector_status: "disabled",
            graph_status: "disabled",
            rag_status: "disabled",
            vector_query_count: 0,
            graph_query_count: 0,
            rag_query_count: 0,
          }).data,
          items: [],
          answer_support: {
            status: "unsupported",
            items_returned: 0,
            coverage: {},
            policy: {},
            warnings: ["no supported evidence"],
          },
        },
      },
      diagnostics: {
        derivedRetrievalUsed: false,
        vectorHealthy: false,
        graphHealthy: false,
        ragHealthy: false,
        retrievalSourcesUsed: ["keyword"],
        warnings: ["no supported evidence"],
      },
    };

    const quality = evaluateMemoryBriefQuality(poorBrief, {
      minContextItems: 1,
      requireDigest: true,
      requireDerivedRetrieval: true,
      requiredRetrieval: ["vector", "graph"],
      failOnWarnings: true,
    });

    expect(quality.ok).toBe(false);
    expect(quality.errors).toEqual([
      "context returned 0 item(s), expected at least 1",
      "digest result is required",
      "context answer support is unsupported",
      "derived retrieval was not used",
      "vector retrieval is not healthy",
      "graph retrieval is not healthy",
      "brief returned 1 warning(s)",
    ]);
    expect(() => assertMemoryBriefQuality(poorBrief, {
      requireDigest: true,
      requireDerivedRetrieval: true,
      requiredRetrieval: ["vector"],
      failOnWarnings: true,
    })).toThrowError(InfinityContextError);

    try {
      assertMemoryBriefQuality(poorBrief, {
        requireDigest: true,
        requireDerivedRetrieval: true,
        requiredRetrieval: ["vector"],
        failOnWarnings: true,
      });
      throw new Error("expected memory brief quality failure");
    } catch (error) {
      expect(error).toBeInstanceOf(InfinityContextError);
      expect((error as InfinityContextError).code).toBe("memory.brief_quality_failed");
      expect((error as InfinityContextError).details).toMatchObject({
        metrics: {
          context_items: 0,
          context_source_refs: 0,
          top_evidence_items: 0,
          search_items: 0,
          digest_sections: 0,
          digest_source_refs: 0,
        },
        retrieval: {
          derived_retrieval_used: false,
          vector_healthy: false,
          graph_healthy: false,
          rag_healthy: false,
          retrieval_sources_used: ["keyword"],
        },
      });
    }
  });

  it("seeds durable memory before building a memory brief", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: factRecord("fact_seed_1") }),
      jsonResponse({ data: factRecord("fact_seed_2") }),
      jsonResponse({
        data: {
          counts: { done: 2 },
          oldest_active_lag_seconds: 0,
          items: [],
          next_cursor: null,
        },
      }),
      jsonResponse(contextResponse("seed-brief", {
        retrieval_sources_used: ["vector"],
        vector_query_count: 2,
        rag_query_count: 1,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["graph"],
        graph_query_count: 1,
      })),
      jsonResponse(digestResponse("seed-brief")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const result = await client.workflows.seedMemoryAndBuildBrief({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents:preferences",
      idempotencyKeyPrefix: "seed:ai-agents",
      sourceType: "sdk-seed",
      sourceIdPrefix: "social-monitor:seed:ai-agents",
      headers: { "x-trace-id": "trace_seed_memory" },
      signal: controller.signal,
      facts: [
        {
          text: "User prefers concise summaries grouped by source.",
          category: "summary_preference",
          tags: ["summary", "source_grouping"],
        },
        {
          text: "User wants Reddit evidence separated from GitHub evidence.",
          memoryScopeExternalRef: "user:user_1",
          idempotencyKey: "seed:ai-agents:user:fact",
          sourceRefs: [{ source_type: "user", source_id: "user_1" }],
          tags: ["summary", "provider_split"],
        },
      ],
      outboxDrain: {
        maxAttempts: 1,
        pollIntervalMs: 0,
        limit: 5,
      },
      brief: {
        query: "Which summary style should today's AI agents digest use?",
        topic: "AI agents digest preferences",
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: ["topic:ai-agents:preferences", "user:user_1"],
        maxFacts: 10,
        maxChunks: 4,
      },
    });

    expect(result.seed).toEqual({
      total: 2,
      remembered: 2,
      factIds: ["fact_seed_1", "fact_seed_2"],
      warnings: [],
    });
    expect(result.diagnostics).toMatchObject({
      ok: true,
      seededFactsOk: true,
      outboxDrainOk: true,
    });
    expect(result.brief.diagnostics.retrievalSourcesUsed).toEqual(["vector", "graph"]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/facts",
      "POST /v1/facts",
      "GET /v1/diagnostics/outbox",
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual([
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
    ]);
    expect(transport.requests.map((request) => request.headers.get("idempotency-key"))).toEqual([
      "seed:ai-agents:fact:0",
      "seed:ai-agents:user:fact",
      null,
      null,
      null,
      null,
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "topic:ai-agents:preferences",
      text: "User prefers concise summaries grouped by source.",
      kind: "memory_seed",
      category: "summary_preference",
      tags: ["summary", "source_grouping"],
      ttl_policy: "durable",
      source_refs: [{ source_type: "sdk-seed", source_id: "social-monitor:seed:ai-agents:fact:0" }],
    });
    expect(transport.bodies[1]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "user:user_1",
      source_refs: [{ source_type: "user", source_id: "user_1" }],
    });
    expect(transport.bodies[3]).toMatchObject({
      memory_scope_external_refs: ["topic:ai-agents:preferences", "user:user_1"],
      query: "Which summary style should today's AI agents digest use?",
      max_facts: 10,
      max_chunks: 4,
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel seed brief");
  });

  it("checks full memory readiness through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: ["qdrant", "graphiti"], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("readiness", {
        retrieval_sources_used: ["vector", "graph"],
        vector_query_count: 3,
        graph_query_count: 2,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["vector"],
        vector_query_count: 2,
        graph_query_count: 1,
      })),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const readiness = await client.workflows.checkFullMemoryReadiness({
      query: "Prove full memory runtime before summary generation",
      readScope: ReadScope.external({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: ["workspace-global", "topic:ai-agents:preferences"],
      }),
      includeSearchProbe: true,
      assertReady: true,
      tokenBudget: 900,
      maxFacts: 8,
      maxChunks: 6,
      signal: controller.signal,
      headers: { "x-trace-id": "trace_readiness" },
    });

    expect(readiness.readiness).toMatchObject({
      ok: true,
      mode: "full",
      missingAdapters: [],
      unhealthyRetrieval: [],
      derivedRetrievalUsed: true,
    });
    expect(readiness.diagnostics).toEqual({
      contextProbe: true,
      searchProbe: true,
      diagnosticsSource: "context",
      warnings: [],
    });
    expect(readiness.context?.data.bundle_id).toBe("bundle_1");
    expect(readiness.search?.data.items).toHaveLength(1);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "POST /v1/context",
      "POST /v1/search",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual([
      "trace_readiness",
      "trace_readiness",
      "trace_readiness",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      query: "Prove full memory runtime before summary generation",
      memory_scope_external_refs: ["workspace-global", "topic:ai-agents:preferences"],
      token_budget: 900,
      max_facts: 8,
      max_chunks: 6,
    });
    expect(transport.bodies[1]).toMatchObject(transport.bodies[0] as Record<string, unknown>);
  });

  it("fails full memory readiness assertions when required adapters are missing", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ enabled_adapters: [], supports_qdrant: true, supports_graphiti: true }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.workflows.checkFullMemoryReadiness({ assertReady: true }),
    ).rejects.toMatchObject({
      code: "memory.runtime_not_ready",
      statusCode: 0,
      retryable: false,
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
    ]);
  });

  it("runs a durable memory summary loop across topology, readiness, evidence and brief", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse({ data: spaceRecord("space_1", "workspace") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: scopeRecord("scope_topic", "topic:ai-agents") }, 201),
      jsonResponse({ enabled_adapters: ["qdrant", "graphiti"], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse(contextResponse("loop-readiness", {
        vector_query_count: 2,
        graph_query_count: 1,
      })),
      jsonResponse({ data: factRecord("fact_reddit") }, 201),
      jsonResponse({ data: factRecord("fact_github") }, 201),
      jsonResponse({
        data: {
          counts: { pending: 2 },
          oldest_active_lag_seconds: 15,
          items: [outboxItem(10, "pending"), outboxItem(11, "pending")],
          next_cursor: null,
        },
      }),
      jsonResponse({
        data: {
          counts: { done: 2, pending: 0 },
          oldest_active_lag_seconds: null,
          items: [outboxItem(10, "done"), outboxItem(11, "done")],
          next_cursor: null,
        },
      }),
      jsonResponse(contextResponse("loop-brief", {
        retrieval_sources_used: ["vector", "graph"],
        vector_query_count: 4,
        graph_query_count: 2,
      })),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["graph"],
        vector_query_count: 3,
        graph_query_count: 2,
      })),
      jsonResponse(digestResponse("loop-brief")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const loop = await client.workflows.runMemorySummaryLoop({
      headers: { "x-trace-id": "trace_loop" },
      topology: {
        spaceSlug: "workspace",
        spaceName: "Workspace",
        memoryScopes: [{ externalRef: "topic:ai-agents", name: "AI agents" }],
      },
      readiness: {
        query: "Prove memory before generating the AI agents summary",
        spaceSlug: "workspace",
        memoryScopeExternalRefs: ["topic:ai-agents"],
        assertReady: true,
      },
      sourceEvidence: {
        concurrency: 1,
        items: [
          {
            spaceSlug: "workspace",
            memoryScopeExternalRef: "topic:ai-agents",
            sourceAgent: "social-monitor",
            sourceType: "reddit",
            sourceId: "reddit:t3_ai",
            text: "Reddit discussion mentions agent memory evals.",
            idempotencyKey: "reddit:t3_ai",
            document: false,
            episode: false,
            capture: false,
            fact: true,
            linkSuggestions: false,
          },
          {
            spaceSlug: "workspace",
            memoryScopeExternalRef: "topic:ai-agents",
            sourceAgent: "social-monitor",
            sourceType: "github",
            sourceId: "github:issue_1",
            text: "GitHub issue tracks Graphiti temporal memory integration.",
            idempotencyKey: "github:issue_1",
            document: false,
            episode: false,
            capture: false,
            fact: true,
            linkSuggestions: false,
          },
        ],
      },
      outboxDrain: {
        limit: 5,
        maxAttempts: 3,
        pollIntervalMs: 0,
        throwOnFailure: true,
      },
      brief: {
        query: "What should the AI agents digest highlight?",
        topic: "AI agents digest",
        spaceSlug: "workspace",
        memoryScopeExternalRefs: ["topic:ai-agents"],
        tokenBudget: 1200,
      },
      qualityPolicy: {
        requireSearch: true,
        minSearchItems: 1,
        requireDigest: true,
        requireDerivedRetrieval: true,
        requiredRetrieval: ["vector", "graph"],
      },
    });

    expect(loop.topology?.created).toMatchObject({
      space: true,
      memoryScopes: ["topic:ai-agents"],
    });
    expect(loop.readiness?.readiness.ok).toBe(true);
    expect(loop.sourceEvidenceSummary).toMatchObject({
      total: 2,
      succeeded: 2,
      failed: 0,
      bySourceType: { reddit: 1, github: 1 },
    });
    expect(loop.outboxDrain?.diagnostics).toMatchObject({
      attempts: 2,
      blocking_count: 0,
      max_blocking_items: 0,
    });
    expect(loop.brief.digest?.data.digest_id).toBe("digest_1");
    expect(loop.quality).toMatchObject({
      ok: true,
      errors: [],
      metrics: {
        contextItems: 1,
        searchItems: 1,
        digestSections: 0,
      },
    });
    expect(loop.evidenceSummary).toMatchObject({
      contextItems: 1,
      searchItems: 1,
      digestSections: 0,
      sourceRefsTotal: 2,
      uniqueSourceRefs: 1,
      bySourceType: { "sdk-full-memory-proof": 2 },
    });
    expect(loop.diagnostics).toEqual({
      ok: true,
      readinessOk: true,
      sourceEvidenceOk: true,
      outboxDrainOk: true,
      qualityOk: true,
      warnings: [],
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "GET /v1/capabilities",
      "POST /v1/context",
      "POST /v1/facts",
      "POST /v1/facts",
      "GET /v1/diagnostics/outbox",
      "GET /v1/diagnostics/outbox",
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 13 }, () => "trace_loop"),
    );
    expect(transport.bodies[3]).toMatchObject({
      source_refs: [{ source_type: "reddit", source_id: "reddit:t3_ai" }],
      ttl_policy: "durable",
    });
    expect(transport.bodies[7]).toMatchObject({
      topic: "AI agents digest",
      token_budget: 1200,
    });
  });

  it("fails memory summary loops when brief quality policy is not satisfied", async () => {
    const poorContext = {
      data: {
        ...contextResponse("loop-poor-brief", {
          retrieval_sources_used: ["keyword"],
          vector_status: "disabled",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }).data,
        items: [],
        answer_support: {
          status: "unsupported",
          items_returned: 0,
          coverage: {},
          policy: {},
          warnings: ["no supported evidence"],
        },
      },
    };

    const transport = new RecordingTransport([
      jsonResponse(poorContext),
      jsonResponse(searchResponse({
        retrieval_sources_used: ["keyword"],
        vector_status: "disabled",
        graph_status: "disabled",
        vector_query_count: 0,
        graph_query_count: 0,
      })),
      jsonResponse(digestResponse("loop-poor-brief")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.workflows.runMemorySummaryLoop({
        readiness: false,
        brief: {
          query: "What should the AI agents digest highlight?",
          topic: "AI agents digest",
          spaceSlug: "workspace",
          memoryScopeExternalRefs: ["topic:ai-agents"],
        },
        qualityPolicy: {
          requireSearch: true,
          requireDigest: true,
          requireDerivedRetrieval: true,
          requiredRetrieval: ["vector", "graph"],
          failOnWarnings: true,
        },
      }),
    ).rejects.toMatchObject({
      code: "memory.brief_quality_failed",
      retryable: false,
      details: {
        metrics: {
          context_items: 0,
          search_items: 1,
        },
        retrieval: {
          derived_retrieval_used: false,
          vector_healthy: false,
          graph_healthy: false,
        },
      },
    });

    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
  });

  it("inspects memory across read models, diagnostics, graph and snapshot preview", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: memoryBrowserData() }),
      jsonResponse({ data: operationsConsoleData() }),
      jsonResponse({
        data: {
          space_id: "space_1",
          plan: { tier: "beta", display_name: "Beta", media_analysis_seconds_per_month: 3600 },
          resources: [],
        },
      }),
      jsonResponse({ enabled_adapters: ["qdrant", "graphiti"], supports_qdrant: true, supports_graphiti: true }),
      jsonResponse({ adapters: { qdrant: "ok", graphiti: "ok" } }),
      jsonResponse({ requests: 12 }),
      jsonResponse({ backend: "postgres" }),
      jsonResponse({ data: { memory_scope_id: "scope_1", vector_status: "ok" } }),
      jsonResponse({ data: { nodes: [], edges: [] } }),
      jsonResponse({ data: { facts: [] }, manifest: { version: "snapshot.v1" } }),
      jsonResponse({ data: { dry_run: true, conflicts: [] } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const inspection = await client.workflows.inspectMemory({
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      limit: 5,
      includeGraph: true,
      includeSnapshotPreview: true,
      graphMaxFacts: 25,
      snapshotMergeStrategy: "fail_on_conflict",
      signal: controller.signal,
      headers: { "x-trace-id": "trace_inspect_memory" },
    });

    expect(inspection.memoryBrowser.data.stats).toMatchObject({ facts: 1 });
    expect(inspection.operationsConsole?.data.diagnostics).toMatchObject({ queue_lag: 0 });
    expect(inspection.usage?.data.plan.tier).toBe("beta");
    expect(inspection.capabilities?.enabled_adapters).toEqual(["qdrant", "graphiti"]);
    expect(inspection.runtimeDiagnostics?.adapters).toMatchObject({ adapters: { qdrant: "ok" } });
    expect(inspection.graph).toMatchObject({ data: { nodes: [], edges: [] } });
    expect(inspection.snapshotPreview).toMatchObject({ data: { dry_run: true, conflicts: [] } });
    expect(inspection.inspection).toMatchObject({
      partial: false,
      issues: [],
      warnings: [],
      optionalSections: [
        "memoryBrowser",
        "operationsConsole",
        "usage",
        "capabilities",
        "runtimeDiagnostics",
        "graph",
        "snapshotPreview",
      ],
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/memory-browser",
      "GET /v1/operations-console",
      "GET /v1/usage",
      "GET /v1/capabilities",
      "GET /v1/diagnostics/adapters",
      "GET /v1/diagnostics/metrics",
      "GET /v1/diagnostics/storage",
      "GET /v1/diagnostics/memory-scope/scope_1",
      "GET /v1/export/graph.json",
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/preview",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 11 }, () => "trace_inspect_memory"),
    );
    expect(transport.requests[8]?.url.searchParams.get("max_facts")).toBe("25");
    expect(transport.requests[9]?.url.searchParams.get("redacted")).toBe("true");
    expect(transport.bodies.at(-1)).toMatchObject({
      snapshot: { facts: [] },
      manifest: { version: "snapshot.v1" },
      merge_strategy: "fail_on_conflict",
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel inspection");
  });

  it("returns partial memory inspection issues when optional sections fail", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: memoryBrowserData() }),
      jsonResponse({ error: { code: "operations_unavailable", message: "temporarily unavailable" } }, 503),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const inspection = await client.workflows.inspectMemory({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      continueOnError: true,
      includeUsage: false,
      includeCapabilities: false,
      includeDiagnostics: false,
      includeGraph: false,
      includeSnapshotPreview: false,
    });

    expect(inspection.memoryBrowser.data.memory_scope?.external_ref).toBe("topic:ai-agents");
    expect(inspection.operationsConsole).toBeUndefined();
    expect(inspection.inspection.partial).toBe(true);
    expect(inspection.inspection.issues).toMatchObject([
      {
        section: "operationsConsole",
        error: {
          name: "InfinityContextError",
          code: "operations_unavailable",
          statusCode: 503,
        },
      },
    ]);
  });

  it("plans memory maintenance across review queues", async () => {
    const controller = new AbortController();
    const sourceAnchor = anchorRecord("anchor_source", "Project Atlas");
    const targetAnchor = anchorRecord("anchor_target", "Atlas");
    const transport = new RecordingTransport([
      jsonResponse({ data: operationsConsoleData() }),
      jsonResponse({ data: [contextLinkSuggestionRecord("ctx_suggestion_1")] }),
      jsonResponse({ data: [memorySuggestionRecord("memory_suggestion_1")] }),
      jsonResponse({
        data: [
          {
            source_anchor: sourceAnchor,
            target_anchor: targetAnchor,
            confidence: "high",
            score: 0.94,
            reasons: ["alias overlap"],
            metadata: {},
          },
        ],
      }),
      jsonResponse({ data: [captureRecord("capture_pending_1")] }),
      jsonResponse({ data: [assetExtractionJobRecord("job_failed_1")] }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const plan = await client.workflows.planMemoryMaintenance({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      threadExternalRef: "thread_1",
      limit: 5,
      anchorKind: "project",
      signal: controller.signal,
      headers: { "x-trace-id": "trace_maintenance" },
    });

    expect(plan.summary).toMatchObject({
      totalActionable: 5,
      contextLinkSuggestions: 1,
      memorySuggestions: 1,
      anchorMergeCandidates: 1,
      capturesPendingConsolidation: 1,
      extractionJobs: 1,
    });
    expect(plan.summary.suggestedActions.map((action) => action.kind)).toEqual([
      "review_context_links",
      "resolve_memory_suggestions",
      "merge_duplicate_anchors",
      "consolidate_captures",
      "retry_or_triage_extractions",
    ]);
    expect(plan.diagnostics).toMatchObject({
      partial: false,
      issues: [],
      optionalSections: [
        "operationsConsole",
        "contextLinkSuggestions",
        "memorySuggestions",
        "anchorMergeCandidates",
        "captureDiagnostics",
        "extractionJobs",
      ],
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/operations-console",
      "GET /v1/context-link-suggestions",
      "GET /v1/suggestions",
      "GET /v1/anchors/merge-suggestions",
      "GET /v1/diagnostics/captures",
      "GET /v1/asset-extractions",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 6 }, () => "trace_maintenance"),
    );
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe("pending");
    expect(transport.requests[3]?.url.searchParams.get("kind")).toBe("project");
    expect(transport.requests[4]?.url.searchParams.get("consolidation_status")).toBe("pending");
    expect(transport.requests[5]?.url.searchParams.get("status")).toBe("failed");
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel maintenance");
  });

  it("returns partial maintenance plan issues when optional queues fail", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: operationsConsoleData() }),
      jsonResponse({ error: { code: "queue_unavailable", message: "queue unavailable" } }, 503),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const plan = await client.workflows.planMemoryMaintenance({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      continueOnError: true,
      includeMemorySuggestions: false,
      includeAnchorMergeCandidates: false,
      includeCaptureDiagnostics: false,
      includeExtractionJobs: false,
    });

    expect(plan.queues.operationsConsole?.data.diagnostics).toMatchObject({ queue_lag: 0 });
    expect(plan.queues.contextLinkSuggestions).toBeUndefined();
    expect(plan.summary.totalActionable).toBe(0);
    expect(plan.diagnostics.partial).toBe(true);
    expect(plan.diagnostics.issues).toMatchObject([
      {
        section: "contextLinkSuggestions",
        error: {
          name: "InfinityContextError",
          code: "queue_unavailable",
          statusCode: 503,
        },
      },
    ]);
  });

  it("transfers memory snapshots through safe preview and confirmed modes", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: { schema_version: "memory_scope_snapshot.v1", facts: [] }, manifest: { sha256: "sha_1" } }),
      jsonResponse({ data: { dry_run: true, conflicts: [] } }),
      jsonResponse({ data: { schema_version: "memory_scope_snapshot.v1", facts: [{ id: "fact_1" }] } }),
      jsonResponse({ data: { imported: true, dry_run: false } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const preview = await client.workflows.transferMemorySnapshot({
      sourceSpaceSlug: "workspace-source",
      sourceMemoryScopeExternalRef: "topic:ai-agents",
      targetSpaceSlug: "workspace-target",
      targetMemoryScopeExternalRef: "topic:ai-agents-copy",
      signal: controller.signal,
      headers: { "x-trace-id": "trace_snapshot_transfer" },
    });

    expect(preview.diagnostics).toMatchObject({
      mode: "preview",
      mutated: false,
      redacted: true,
      mergeStrategy: "fail_on_conflict",
    });
    expect(preview.preview).toMatchObject({ data: { dry_run: true, conflicts: [] } });
    expect(preview.manifest).toMatchObject({ sha256: "sha_1" });

    await expect(
      client.workflows.transferMemorySnapshot({
        sourceSpaceSlug: "workspace-source",
        sourceMemoryScopeExternalRef: "topic:ai-agents",
        mode: "confirmed_import",
      }),
    ).rejects.toThrow(ValueError);

    const imported = await client.workflows.transferMemorySnapshot({
      sourceSpaceSlug: "workspace-source",
      sourceMemoryScopeExternalRef: "topic:ai-agents",
      targetSpaceSlug: "workspace-target",
      targetMemoryScopeExternalRef: "topic:ai-agents-copy",
      mode: "confirmed_import",
      confirmed: true,
      redacted: false,
      mergeStrategy: "replace",
      sourceName: "sdk-test-transfer",
      signal: controller.signal,
      headers: { "x-trace-id": "trace_snapshot_transfer" },
    });

    expect(imported.diagnostics).toMatchObject({
      mode: "confirmed_import",
      mutated: true,
      redacted: false,
      mergeStrategy: "replace",
    });
    expect(imported.importResult).toMatchObject({ data: { imported: true, dry_run: false } });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/preview",
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/import",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 4 }, () => "trace_snapshot_transfer"),
    );
    expect(transport.requests[0]?.url.searchParams.get("redacted")).toBe("true");
    expect(transport.requests[2]?.url.searchParams.get("redacted")).toBe("false");
    expect(transport.bodies[1]).toMatchObject({
      space_slug: "workspace-target",
      memory_scope_external_ref: "topic:ai-agents-copy",
      snapshot: { schema_version: "memory_scope_snapshot.v1", facts: [{ id: "fact_1" }] },
      dry_run: false,
      confirmed: true,
      merge_strategy: "replace",
      source_name: "sdk-test-transfer",
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel snapshot transfer");
  });

  it("ensures memory topology through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse({ data: spaceRecord("space_1", "workspace") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: scopeRecord("scope_workspace", "workspace-global") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: scopeRecord("scope_topic", "topic:ai-agents") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: userRecord("user_1", "user:owner") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: membershipRecord("membership_1", "space_1", "user_1", "owner") }, 201),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const result = await client.workflows.ensureMemoryTopology({
      spaceSlug: "workspace",
      spaceName: "Workspace",
      memoryScopes: [
        { externalRef: "workspace-global", name: "Workspace global" },
        { externalRef: "topic:ai-agents", name: "AI agents" },
      ],
      users: [{
        externalRef: "user:owner",
        displayName: "Owner",
        email: "owner@example.com",
        metadata: { source: "sdk-test" },
        role: "owner",
      }],
      listLimit: 10,
      signal: controller.signal,
      headers: { "x-trace-id": "trace_topology" },
    });

    expect(result.created).toEqual({
      space: true,
      memoryScopes: ["workspace-global", "topic:ai-agents"],
      users: ["user:owner"],
      memberships: ["user:owner"],
    });
    expect(result.diagnostics).toEqual({ listLimit: 10, warnings: [] });
    expect(result.space.id).toBe("space_1");
    expect(result.memoryScopes.map((scope) => scope.external_ref)).toEqual(["workspace-global", "topic:ai-agents"]);
    expect(result.users.map((user) => user.external_ref)).toEqual(["user:owner"]);
    expect(result.memberships.map((membership) => membership.role)).toEqual(["owner"]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "GET /v1/users",
      "POST /v1/users",
      "GET /v1/spaces/space_1/memberships",
      "POST /v1/spaces/space_1/memberships",
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 10 }, () => "trace_topology"),
    );
    expect(transport.requests[0]?.url.searchParams.get("limit")).toBe("10");
    expect(transport.requests[2]?.url.searchParams.get("space_id")).toBe("space_1");
    expect(transport.requests[6]?.url.searchParams.get("status")).toBe("active");
    expect(transport.bodies[0]).toEqual({ slug: "workspace", name: "Workspace" });
    expect(transport.bodies[3]).toEqual({
      external_ref: "user:owner",
      display_name: "Owner",
      email: "owner@example.com",
      metadata: { source: "sdk-test" },
    });
    expect(transport.bodies[4]).toEqual({ user_id: "user_1", role: "owner" });
    expect(transport.requests.every((request) => request.signal !== undefined)).toBe(true);
  });

  it("recovers memory topology creation conflicts idempotently", async () => {
    const existingSpace = spaceRecord("space_1", "workspace");
    const existingScope = scopeRecord("scope_workspace", "workspace-global");
    const existingUser = userRecord("user_1", "user:owner");
    const existingMembership = membershipRecord("membership_1", "space_1", "user_1", "viewer");
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse({ error: { code: "conflict", message: "space already exists" } }, 409),
      jsonResponse({ data: [existingSpace] }),
      jsonResponse({ data: [existingScope] }),
      jsonResponse({ data: [existingUser] }),
      jsonResponse({ data: [existingMembership] }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const result = await client.workflows.ensureMemoryTopology({
      spaceSlug: "workspace",
      spaceName: "Workspace",
      memoryScopes: [{ externalRef: "workspace-global", name: "Workspace global" }],
      users: [{ externalRef: "user:owner", displayName: "Owner", role: "owner" }],
      listLimit: 7,
    });

    expect(result.space).toEqual(existingSpace);
    expect(result.memoryScopes).toEqual([existingScope]);
    expect(result.users).toEqual([existingUser]);
    expect(result.memberships).toEqual([existingMembership]);
    expect(result.created).toEqual({
      space: false,
      memoryScopes: [],
      users: [],
      memberships: [],
    });
    expect(result.diagnostics.warnings).toEqual([
      "membership for user:owner exists with role viewer",
    ]);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/spaces",
      "GET /v1/memory-scopes",
      "GET /v1/users",
      "GET /v1/spaces/space_1/memberships",
    ]);
    expect(transport.requests.map((request) => request.url.searchParams.get("limit"))).toEqual(
      ["7", null, "7", "7", "7", "7"],
    );
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

  it("manages asset extraction lifecycle endpoints", async () => {
    const job = assetExtractionJobRecord("job_1");
    const transport = new RecordingTransport([
      jsonResponse({ data: job }, 202),
      jsonResponse({ data: [job] }),
      jsonResponse({ data: [{ ...job, id: "job_2", status: "failed" }] }),
      jsonResponse({ data: { ...job, artifacts: [extractionArtifactRecord("artifact_1")] } }),
      jsonResponse({ data: { ...job, status: "queued", attempt_count: 2 } }, 202),
      jsonResponse({ data: { ...job, status: "canceled" } }, 202),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const requested = await client.assets.requestAssetExtraction("asset_1", {
      parserProfile: "markdown-strict",
    });
    const assetJobs = await client.assets.listAssetExtractions("asset_1", {
      status: "running",
      limit: 20,
    });
    const scopeJobs = await client.assets.listScopeAssetExtractions({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      threadExternalRef: "review-thread",
      status: "failed",
      limit: 15,
    });
    const details = await client.assets.getAssetExtraction("job_1");
    const retried = await client.assets.retryAssetExtraction("job_1");
    const canceled = await client.assets.cancelAssetExtraction("job_1");

    expect(requested.data.id).toBe("job_1");
    expect(assetJobs.data[0]?.status).toBe("running");
    expect(scopeJobs.data[0]?.status).toBe("failed");
    expect(details.data.artifacts[0]?.download_path).toBe("/v1/extraction-artifacts/artifact_1/download");
    expect(retried.data.attempt_count).toBe(2);
    expect(canceled.data.status).toBe("canceled");
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/assets/asset_1/extractions",
      "GET /v1/assets/asset_1/extractions",
      "GET /v1/asset-extractions",
      "GET /v1/asset-extractions/job_1",
      "POST /v1/asset-extractions/job_1/retry",
      "POST /v1/asset-extractions/job_1/cancel",
    ]);
    expect(transport.requests[0]?.url.searchParams.get("parser_profile")).toBe("markdown-strict");
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe("running");
    expect(transport.requests[1]?.url.searchParams.get("limit")).toBe("20");
    expect(transport.requests[2]?.url.searchParams.get("space_slug")).toBe("workspace");
    expect(transport.requests[2]?.url.searchParams.get("memory_scope_external_ref")).toBe("scope");
    expect(transport.requests[2]?.url.searchParams.get("thread_external_ref")).toBe("review-thread");
    expect(transport.requests[2]?.url.searchParams.get("status")).toBe("failed");
    expect(transport.requests[2]?.url.searchParams.get("limit")).toBe("15");
  });

  it("waits for asset extraction terminal status", async () => {
    const controller = new AbortController();
    const sleeps: number[] = [];
    const running = assetExtractionJobRecord("job_1");
    const succeeded = {
      ...running,
      status: "succeeded",
      finished_at: "2026-06-06T00:02:00.000Z",
      artifacts: [extractionArtifactRecord("artifact_1")],
    };
    const failed = {
      ...running,
      status: "failed",
      safe_error_code: "asset_extraction.pdf_parse_failed",
      safe_error_message: "PDF text extraction failed",
      artifacts: [],
    };
    const transport = new RecordingTransport([
      jsonResponse({ data: { ...running, artifacts: [] } }),
      jsonResponse({ data: { ...running, status: "running", artifacts: [] } }),
      jsonResponse({ data: succeeded }),
      jsonResponse({ data: failed }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const completed = await client.assets.waitForAssetExtraction("job_1", {
      maxAttempts: 3,
      pollIntervalMs: 5,
      signal: controller.signal,
      headers: { "x-trace-id": "trace_extraction_wait" },
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });

    expect(completed.data.status).toBe("succeeded");
    expect(completed.data.artifacts[0]?.id).toBe("artifact_1");
    expect(sleeps).toEqual([5, 5]);
    await expect(
      client.assets.waitForAssetExtraction("job_1", {
        maxAttempts: 1,
        throwOnFailure: true,
      }),
    ).rejects.toMatchObject({
      code: "asset_extraction.pdf_parse_failed",
      retryable: false,
    });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
    ]);
    expect(transport.requests.slice(0, 3).map((request) => request.headers.get("x-trace-id"))).toEqual([
      "trace_extraction_wait",
      "trace_extraction_wait",
      "trace_extraction_wait",
    ]);
    const requestSignals = transport.requests.slice(0, 3).map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel extraction wait");
  });

  it("validates mixed canonical and external scopes", () => {
    expect(() =>
      MemoryScope.canonical({ spaceId: "space_1", memoryScopeId: "scope_1" }).toPayload(),
    ).not.toThrow();
    expect(() =>
      ReadScope.external({ spaceSlug: "workspace", memoryScopeExternalRef: "user:user_1" }).toPayload(),
    ).not.toThrow();
    expect(() =>
      new InfinityContextClient(),
    ).not.toThrow();
    expect(() =>
      MemoryScope.external({
        spaceSlug: "workspace",
        memoryScopeExternalRef: "scope",
      }).toPayload(),
    ).not.toThrow();
    const mixedInput = {
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      spaceSlug: "workspace",
    } as unknown as Parameters<typeof MemoryScope.canonical>[0];
    expect(() => MemoryScope.canonical(mixedInput).toPayload()).toThrow(ValueError);
  });

  it("supports context link creation, suggestion review and batch validation", async () => {
    const link = contextLinkRecord("link_1");
    const suggestion = contextLinkSuggestionRecord("suggestion_1");
    const transport = new RecordingTransport([
      jsonResponse({ data: { candidates: [{ ...suggestion, label: "Fact", preview: "Target", tier: "high", reasons: ["semantic"] }], diagnostics: { candidates: 1 } } }),
      jsonResponse({ data: { ...link, duplicate: false } }),
      jsonResponse({ data: [link] }),
      jsonResponse({ data: [suggestion] }),
      jsonResponse({ data: { suggestion: { ...suggestion, status: "approved" }, link, duplicate_link: false } }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          diagnostics: { reviewed: 1 },
          results: [{ suggestion_id: "suggestion_1", action: "approve", status: "approved" }],
        },
      }),
      jsonResponse({ data: { ...link, confidence: "high" } }),
      jsonResponse({ data: { ...link, status: "deleted" } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await client.contextLinks.suggestContextLinks({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      threadExternalRef: "review",
      text: "Project Atlas screenshot evidence",
      sourceType: "capture",
      sourceId: "capture_1",
      limit: 5,
      persist: true,
    });
    await client.contextLinks.createContextLink({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      sourceType: "capture",
      sourceId: "capture_1",
      targetType: "fact",
      targetId: "fact_1",
      relationType: "supports",
      confidence: "high",
      reason: "manual review",
      metadata: { reviewer: "sdk" },
    });
    await client.contextLinks.listContextLinks({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      sourceType: "capture",
      sourceId: "capture_1",
      statuses: "active,deleted",
      limit: 20,
    });
    await client.contextLinks.listContextLinkSuggestions({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      status: "pending",
      limit: 20,
    });
    await client.contextLinks.approveContextLinkSuggestion("suggestion_1", {
      reason: "reviewed",
      targetType: "fact",
      targetId: "fact_1",
      relationType: "supports",
      confidence: "high",
      linkReason: "review selected exact target",
    });
    await client.contextLinks.reviewContextLinkSuggestionsBatch(
      [{ suggestionId: "suggestion_1", action: "approve", reason: "batch reviewed" }],
      {
        continueOnError: true,
        visibleFilter: {
          spaceSlug: "workspace",
          memoryScopeExternalRef: "scope",
          status: "pending",
          limit: 20,
        },
      },
    );
    await client.contextLinks.updateContextLink("link_1", { confidence: "high", reason: "promoted" });
    await client.contextLinks.deleteContextLink("link_1");

    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/link-suggestions",
      "POST /v1/context-links",
      "GET /v1/context-links",
      "GET /v1/context-link-suggestions",
      "POST /v1/context-link-suggestions/suggestion_1/review",
      "POST /v1/context-link-suggestions/review-batch",
      "PATCH /v1/context-links/link_1",
      "DELETE /v1/context-links/link_1",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      thread_external_ref: "review",
      text: "Project Atlas screenshot evidence",
      source_type: "capture",
      source_id: "capture_1",
      limit: 5,
      persist: true,
    });
    expect(transport.requests[2]?.url.searchParams.get("status")).toBeNull();
    expect(transport.requests[2]?.url.searchParams.get("statuses")).toBe("active,deleted");
    expect(transport.bodies).toContainEqual(expect.objectContaining({
      continue_on_error: true,
      visible_filter: {
        space_slug: "workspace",
        memory_scope_external_ref: "scope",
        status: "pending",
        limit: 20,
      },
      items: [
        {
          suggestion_id: "suggestion_1",
          action: "approve",
          reason: "batch reviewed",
        },
      ],
    }));
    expect(() => client.contextLinks.reviewContextLinkSuggestionsBatch([])).toThrow(ValueError);
    expect(() =>
      client.contextLinks.reviewContextLinkSuggestionsBatch([
        { suggestionId: "suggestion_1", action: "approve" },
        { suggestionId: "suggestion_1", action: "reject" },
      ]),
    ).toThrow(ValueError);
  });

  it("supports suggestion batch creation and advanced resolution", async () => {
    const suggestion = memorySuggestionRecord("suggestion_1");
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          created: 1,
          existing: 0,
          failed: 0,
          stopped: false,
          results: [{ index: 0, status: "created", suggestion }],
        },
      }, 201),
      jsonResponse({ data: { suggestion: { ...suggestion, status: "approved" }, fact: factRecord("fact_1") } }),
      jsonResponse({ data: { suggestion: { ...suggestion, status: "rejected" } } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const created = await client.suggestions.createSuggestionsBatch({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      continueOnError: true,
      items: [
        {
          candidateText: "Prefer citations from original sources.",
          safeReason: "feedback review",
          operation: "update",
          targetFactId: "fact_1",
          targetFactVersion: 1,
          expiresAt: "2026-07-01T00:00:00.000Z",
          expiryReason: "seasonal preference",
          createdFromCaptureId: "capture_1",
          autoApprove: false,
        },
      ],
    });
    const conflict = await client.suggestions.resolveSuggestionConflict("suggestion_1", {
      action: "approve",
      reason: "latest feedback wins",
      force: true,
    });
    const duplicate = await client.suggestions.resolveDuplicateMerge("suggestion_1", {
      action: "reject",
      reason: "duplicate fact",
    });

    expect(created.data.created).toBe(1);
    expect(conflict.data.fact?.id).toBe("fact_1");
    expect(duplicate.data.suggestion.status).toBe("rejected");
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/suggestions/batch",
      "POST /v1/suggestions/suggestion_1/resolve-conflict",
      "POST /v1/suggestions/suggestion_1/resolve-duplicate",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      continue_on_error: true,
      items: [
        {
          candidate_text: "Prefer citations from original sources.",
          target_fact_id: "fact_1",
          target_fact_version: 1,
          expires_at: "2026-07-01T00:00:00.000Z",
          created_from_capture_id: "capture_1",
          auto_approve: false,
        },
      ],
    });
    expect(transport.bodies[1]).toEqual({
      action: "approve",
      reason: "latest feedback wins",
      force: true,
    });
    expect(() =>
      client.suggestions.createSuggestion({
        spaceSlug: "workspace",
        memoryScopeExternalRef: "scope",
        candidateText: "Invalid update",
        safeReason: "missing version",
        targetFactId: "fact_1",
      }),
    ).toThrow(ValueError);
  });

  it("supports typed suggestion batch review helpers", async () => {
    const suggestion = memorySuggestionRecord("suggestion_1");
    const approved = { ...suggestion, status: "approved" };
    const rejected = { ...suggestion, id: "suggestion_2", status: "rejected" };
    const expired = { ...suggestion, id: "suggestion_3", status: "expired" };
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          results: [{ suggestion_id: "suggestion_1", action: "approve", status: "approved", suggestion: approved }],
        },
      }),
      jsonResponse({
        data: {
          applied: 2,
          failed: 0,
          stopped: false,
          results: [
            { suggestion_id: "suggestion_1", action: "approve", status: "approved", suggestion: approved },
            { suggestion_id: "suggestion_2", action: "approve", status: "approved", suggestion: approved },
          ],
        },
      }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          results: [{ suggestion_id: "suggestion_2", action: "reject", status: "rejected", suggestion: rejected }],
        },
      }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          results: [{ suggestion_id: "suggestion_3", action: "expire", status: "expired", suggestion: expired }],
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const reviewed = await client.suggestions.reviewSuggestionsBatch(
      [{ suggestionId: "suggestion_1", action: "approve", reason: "typed review", force: true }],
      { continueOnError: true },
    );
    const approvedBatch = await client.suggestions.approveSuggestionsBatch(
      ["suggestion_1", { suggestionId: "suggestion_2", reason: "specific approval" }],
      { reason: "bulk approval", force: true, continueOnError: true },
    );
    const rejectedBatch = await client.suggestions.rejectSuggestionsBatch(
      [{ suggestionId: "suggestion_2", force: false }],
      { reason: "not durable" },
    );
    const expiredBatch = await client.suggestions.expireSuggestionsBatch(
      ["suggestion_3"],
      { reason: "stale preference" },
    );

    expect(reviewed.data.results[0]?.suggestion?.status).toBe("approved");
    expect(approvedBatch.data.applied).toBe(2);
    expect(rejectedBatch.data.results[0]?.status).toBe("rejected");
    expect(expiredBatch.data.results[0]?.status).toBe("expired");
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
    ]);
    expect(transport.bodies).toEqual([
      {
        items: [{ suggestion_id: "suggestion_1", action: "approve", reason: "typed review", force: true }],
        continue_on_error: true,
      },
      {
        items: [
          { suggestion_id: "suggestion_1", action: "approve", reason: "bulk approval", force: true },
          { suggestion_id: "suggestion_2", action: "approve", reason: "specific approval", force: true },
        ],
        continue_on_error: true,
      },
      {
        items: [{ suggestion_id: "suggestion_2", action: "reject", reason: "not durable", force: false }],
        continue_on_error: false,
      },
      {
        items: [{ suggestion_id: "suggestion_3", action: "expire", reason: "stale preference" }],
        continue_on_error: false,
      },
    ]);
    expect(() => client.suggestions.approveSuggestionsBatch([])).toThrow(ValueError);
    expect(() => client.suggestions.reviewSuggestionsBatch([{ action: "approve" }])).toThrow(ValueError);
  });

  it("supports anchor merge, split and backfill lifecycle", async () => {
    const sourceAnchor = anchorRecord("anchor_source", "Project Atlas");
    const targetAnchor = anchorRecord("anchor_target", "Atlas");
    const transport = new RecordingTransport([
      jsonResponse({
        data: [
          {
            source_anchor: sourceAnchor,
            target_anchor: targetAnchor,
            confidence: "high",
            score: 0.94,
            reasons: ["alias overlap"],
            metadata: {},
          },
        ],
      }),
      jsonResponse({
        data: {
          anchors: [sourceAnchor],
          created: 1,
          updated: 2,
          sources: [{ source_type: "fact", scanned: 10, observed: 3, skipped_conflicts: 1 }],
          diagnostics: { scanned_sources: 1 },
        },
      }),
      jsonResponse({ data: targetAnchor }),
      jsonResponse({ data: { ...sourceAnchor, label: "Atlas Mobile" } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const candidates = await client.anchors.listAnchorMergeSuggestions({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      kind: "project",
      limit: 5,
    });
    const backfill = await client.anchors.backfillAnchors({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      limitPerSource: 50,
    });
    await client.anchors.mergeAnchor("anchor_source", {
      targetAnchorId: "anchor_target",
      reason: "same project",
    });
    await client.anchors.splitAnchor("anchor_source", {
      alias: "Atlas Mobile",
      newLabel: "Atlas Mobile",
      reason: "distinct product",
    });

    expect(candidates.data[0]?.score).toBe(0.94);
    expect(backfill.data.created).toBe(1);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/anchors/merge-suggestions",
      "POST /v1/anchors/backfill",
      "POST /v1/anchors/anchor_source/merge",
      "POST /v1/anchors/anchor_source/split",
    ]);
    expect(transport.requests[0]?.url.searchParams.get("kind")).toBe("project");
    expect(transport.requests[0]?.url.searchParams.get("limit")).toBe("5");
    expect(transport.bodies).toContainEqual({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      limit_per_source: 50,
    });
    expect(transport.bodies).toContainEqual({
      target_anchor_id: "anchor_target",
      reason: "same project",
    });
    expect(transport.bodies).toContainEqual({
      alias: "Atlas Mobile",
      new_label: "Atlas Mobile",
      reason: "distinct product",
    });
  });

  it("supports capture ingestion, consolidation, diagnostics and purge", async () => {
    const capture = captureRecord("capture_1");
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          ...capture,
          duplicate: false,
          created_suggestions: 1,
          suggestion_ids: ["suggestion_1"],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: [capture] }),
      jsonResponse({ data: capture }),
      jsonResponse({
        data: {
          ...capture,
          consolidation_status: "consolidated",
          created_suggestions: 1,
          suggestion_ids: ["suggestion_1"],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }),
      jsonResponse({ data: [{ ...capture, consolidation_status: "consolidated" }] }),
      jsonResponse({ data: { ...capture, status: "purged" } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await client.captures.createCapture({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      threadExternalRef: "review-thread",
      sourceAgent: "social-monitor",
      sourceKind: "hook",
      eventType: "summary.feedback.recorded",
      actorRole: "user",
      text: "User says Reddit source freshness matters.",
      sourceEventId: "feedback_1",
      sourceActorExternalRef: "user_1",
      clientInstanceId: "sdk-test",
      agentSessionExternalRef: "session_1",
      turnExternalRef: "turn_1",
      sequenceIndex: 3,
      evidenceRefs: [{ source_type: "summary", source_id: "summary_1" }],
      trustLevel: "high",
      sourceAuthority: "user_statement",
      sensitivity: "medium",
      dataClassification: "internal",
      occurredAt: "2026-06-06T00:00:00.000Z",
      metadata: { topic: "ai-agents" },
      traceId: "trace_1",
      idempotencyKey: "feedback_1",
      consolidate: true,
    });
    await client.captures.listCaptures({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      status: "active",
      consolidationStatus: "pending",
      limit: 25,
    });
    await client.captures.getCapture("capture_1");
    await client.captures.consolidateCapture("capture_1", { force: true });
    await client.captures.captureDiagnostics({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      consolidationStatus: "consolidated",
      limit: 25,
    });
    await client.captures.purgeCapture("capture_1", { reason: "privacy_request" });

    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/captures",
      "GET /v1/captures",
      "GET /v1/captures/capture_1",
      "POST /v1/captures/capture_1/consolidate",
      "GET /v1/diagnostics/captures",
      "DELETE /v1/captures/capture_1",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      thread_external_ref: "review-thread",
      source_agent: "social-monitor",
      source_kind: "hook",
      event_type: "summary.feedback.recorded",
      actor_role: "user",
      text: "User says Reddit source freshness matters.",
      evidence_refs: [{ source_type: "summary", source_id: "summary_1" }],
      idempotency_key: "feedback_1",
      consolidate: true,
    });
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe("active");
    expect(transport.requests[1]?.url.searchParams.get("consolidation_status")).toBe("pending");
    expect(transport.bodies).toContainEqual({ force: true });
    expect(transport.bodies).toContainEqual({ reason: "privacy_request" });
  });

  it("reads typed memory browser and operations console projections", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          generated_at: "2026-06-06T00:00:00.000Z",
          memory_scope: scopeRecord("scope_1", "scope"),
          facts: [factRecord("fact_1")],
          episodes: [{ id: "episode_1", status: "active" }],
          documents: [{ id: "document_1", title: "Digest source", status: "active" }],
          chunks: [{ id: "chunk_1", status: "active" }],
          extraction_jobs: [{ id: "job_1", status: "complete" }],
          threads: [{ id: "thread_1", status: "active" }],
          captures: [captureRecord("capture_1")],
          assets: [{ id: "asset_1", filename: "source.md", status: "stored" }],
          anchors: [{ id: "anchor_1", kind: "topic", label: "AI agents", status: "active" }],
          context_links: [contextLinkRecord("link_1")],
          context_link_suggestions: [contextLinkSuggestionRecord("suggestion_1")],
          stats: { facts: 1, captures: 1, context_links: 1 },
          visual_summary: { status: "ready", evidence_count: 3 },
          quick_actions: [{ id: "review_links", priority: 1 }],
          diagnostics: { browser_version: "memory-browser-v1" },
        },
      }),
      jsonResponse({
        data: {
          generated_at: "2026-06-06T00:00:00.000Z",
          scope: { space_id: "space_1", memory_scope_id: "scope_1", thread_id: "thread_1" },
          extraction_status_counts: { complete: 1 },
          link_suggestion_status_counts: { pending: 1 },
          extraction_jobs: [{ id: "job_1", status: "complete" }],
          context_link_suggestions: [contextLinkSuggestionRecord("suggestion_1")],
          diagnostics: { console_version: "memory-operations-console-v1" },
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const browser = await client.readModels.getMemoryBrowser({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      limit: 25,
      captureStatus: "active",
      linkStatus: "active",
      suggestionStatus: "pending",
    });
    const operations = await client.readModels.getOperationsConsole({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      threadExternalRef: "review-thread",
      limit: 10,
    });

    expect(browser.data.facts[0]?.id).toBe("fact_1");
    expect(browser.data.context_links[0]?.id).toBe("link_1");
    expect(operations.data.context_link_suggestions[0]?.id).toBe("suggestion_1");
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/memory-browser",
      "GET /v1/operations-console",
    ]);
    expect(transport.requests[0]?.url.searchParams.get("space_slug")).toBe("workspace");
    expect(transport.requests[0]?.url.searchParams.get("memory_scope_external_ref")).toBe("scope");
    expect(transport.requests[0]?.url.searchParams.get("fact_status")).toBe("active");
    expect(transport.requests[0]?.url.searchParams.get("capture_status")).toBe("active");
    expect(transport.requests[0]?.url.searchParams.get("link_status")).toBe("active");
    expect(transport.requests[0]?.url.searchParams.get("suggestion_status")).toBe("pending");
    expect(transport.requests[0]?.url.searchParams.has("thread_external_ref")).toBe(false);
    expect(transport.requests[1]?.url.searchParams.get("thread_external_ref")).toBe("review-thread");
    expect(transport.requests[1]?.url.searchParams.get("limit")).toBe("10");
  });

  it("manages thread memory and reads usage summaries", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: { chunks: 3, facts: 2, jobs: 1, pending_jobs: 1 } }),
      jsonResponse({ data: { deleted_chunks: 3, deleted_facts: 2, deleted_jobs: 1 } }),
      jsonResponse({ data: { deleted_chunks: 0, deleted_facts: 0, deleted_jobs: 0 } }),
      jsonResponse({
        data: {
          space_id: "space_1",
          plan: {
            tier: "beta",
            display_name: "Beta",
            media_analysis_seconds_per_month: 3600,
          },
          resources: [
            {
              resource: "media_analysis_seconds",
              limit: 3600,
              used: 120,
              remaining: 3480,
              window_start: "2026-06-01T00:00:00.000Z",
              window_end: "2026-07-01T00:00:00.000Z",
            },
          ],
        },
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });
    const scope = {
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      threadExternalRef: "thread:daily-digest",
    };

    const status = await client.threadMemory.status(scope);
    const deleted = await client.threadMemory.delete(scope);
    const compatDeleted = await client.threadMemory.deleteCompat(scope);
    const usage = await client.usage.summary({ spaceSlug: "workspace" });

    expect(status.data.pending_jobs).toBe(1);
    expect(deleted.data.deleted_facts).toBe(2);
    expect(compatDeleted.data.deleted_jobs).toBe(0);
    expect(usage.data.resources[0]?.remaining).toBe(3480);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/thread-memory/status",
      "DELETE /v1/thread-memory",
      "POST /v1/thread-memory/delete",
      "GET /v1/usage",
    ]);
    expect(transport.bodies).toEqual([
      {
        space_slug: "workspace",
        memory_scope_external_ref: "scope",
        thread_external_ref: "thread:daily-digest",
      },
      {
        space_slug: "workspace",
        memory_scope_external_ref: "scope",
        thread_external_ref: "thread:daily-digest",
      },
      {
        space_slug: "workspace",
        memory_scope_external_ref: "scope",
        thread_external_ref: "thread:daily-digest",
      },
    ]);
    expect(transport.requests[3]?.url.searchParams.get("space_slug")).toBe("workspace");
  });

  it("previews memory scope snapshot imports before mutating state", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: { dry_run: true, created: 0, updated: 0, conflicts: [] } }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const preview = await client.exports.previewMemoryScopeSnapshotImport({
      spaceSlug: "workspace",
      memoryScopeExternalRef: "scope",
      snapshot: { schema_version: "memory_scope_snapshot.v1", facts: [] },
      manifest: { sha256: "snapshot-sha" },
      mergeStrategy: "merge_by_external_id",
    });

    expect(preview.data).toMatchObject({ dry_run: true });
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "POST /v1/export/memory_scope-snapshot/preview",
    ]);
    expect(transport.bodies[0]).toEqual({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      snapshot: { schema_version: "memory_scope_snapshot.v1", facts: [] },
      manifest: { sha256: "snapshot-sha" },
      merge_strategy: "merge_by_external_id",
    });
  });
});
