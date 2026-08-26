import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  ReadScope,
  assertFullMemoryReady,
  createMemoryQualityPreset,
  createMemorySummaryLoopPlan,
  evaluateRuntimeReadiness,
  healthyRetrievalComponents,
  MEMORY_QUALITY_PRESETS,
  retrievalDiagnostics,
  usedDerivedRetrieval,
} from "../src/index.js";
import {
  RecordingTransport,
  contextResponse,
  expectCompletedSignalsDetached,
  factRecord,
  jsonResponse,
  outboxItem,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("passes per-request controls through context calls", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse(
        contextResponse("controls", {
          vector_status: "ok",
          graph_status: "ok",
        }),
      ),
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
      projectAnchorPolicy: "advisory",
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
    expect(transport.bodies[0]).toMatchObject({
      project_anchor_policy: "advisory",
    });
  });

  it("passes per-request controls through operational resource clients", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport(
      Array.from({ length: 11 }, () => jsonResponse({ data: { ok: true } })),
    );
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
    await client.suggestions.reviewSuggestionsBatch(
      [{ suggestion_id: "sugg_1", action: "reject" }],
      controls,
    );
    await client.diagnostics.outbox({ ...controls, limit: 1 });
    await client.readModels.getMemoryBrowser({
      ...controls,
      ...scope,
      limit: 1,
    });
    await client.usage.summary({ ...controls, spaceSlug: scope.spaceSlug });
    await client.threadMemory.status({
      ...controls,
      ...scope,
      threadExternalRef: "thread_1",
    });

    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 11 }, () => "trace_resource_controls"));
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel resources",
    );
    expect(
      transport.bodies.every(
        (body) => !Object.hasOwn(body as object, "headers"),
      ),
    ).toBe(true);
    expect(
      transport.bodies.every(
        (body) => !Object.hasOwn(body as object, "signal"),
      ),
    ).toBe(true);
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
    expect(
      transport.requests.map((request) => request.headers.get("x-worker-id")),
    ).toEqual(["worker_1", "worker_1"]);
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
    expect(transport.requests.map((request) => request.url.toString())).toEqual(
      [
        "http://memory.test/v1/diagnostics/outbox?limit=1",
        "http://memory.test/v1/diagnostics/outbox?limit=1&cursor=outbox_cursor_2",
      ],
    );
    expect(
      transport.requests.map((request) => request.headers.get("x-worker-id")),
    ).toEqual(["worker_outbox", "worker_outbox"]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel outbox scan",
    );
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
    expect(transport.requests.map((request) => request.url.toString())).toEqual(
      [
        "http://memory.test/v1/diagnostics/outbox?limit=2",
        "http://memory.test/v1/diagnostics/outbox?limit=2",
      ],
    );
    expect(
      transport.requests.map((request) => request.headers.get("x-worker-id")),
    ).toEqual(["worker_outbox_drain", "worker_outbox_drain"]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel outbox drain",
    );

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

    expect(response.data.diagnostics.query_decomposition_status).toBe(
      "available",
    );
    expect(response.data.diagnostics.vector_status).toBe("ok");
    expect(response.data.diagnostics.graph_status).toBe("ok");
    expect(response.data.diagnostics.vector_query_count).toBe(6);
    expect(response.data.diagnostics.graph_query_count).toBe(4);
    expect(response.data.diagnostics.rag_query_count).toBe(5);
    expect(usedDerivedRetrieval(response.data.diagnostics)).toBe(true);
    expect(
      healthyRetrievalComponents(response.data.diagnostics, [
        "vector",
        "graph",
        "rag",
      ]),
    ).toBe(true);
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
    expect(transport.requests[0]?.url.toString()).toBe(
      "http://memory.test/v1/context",
    );
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
      expect((error as InfinityContextError).code).toBe(
        "memory.runtime_not_ready",
      );
      expect((error as InfinityContextError).message).toContain(
        "Missing runtime adapter: qdrant",
      );
      expect((error as InfinityContextError).message).toContain(
        "Unhealthy vector retrieval: degraded",
      );
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

  it("provides immutable memory quality presets with safe overrides", () => {
    const durable = MEMORY_QUALITY_PRESETS.durable;

    expect(durable.brief).toMatchObject({
      requireSearch: true,
      requireDigest: true,
      requireSupportedAnswer: true,
    });
    expect(durable.summaryLoop).toMatchObject({
      requireReadiness: true,
      requireSourceEvidence: true,
      requireOutboxDrain: true,
      requireQuality: true,
      minSourceEvidenceSuccessRate: 1,
    });
    expect(durable.snapshotPreview).toMatchObject({
      allowedModes: ["preview"],
      forbidMutation: true,
      requireRedacted: true,
      requireManifest: true,
      requirePreview: true,
      forbidSameScope: true,
    });
    expect(durable.proofArtifact).toMatchObject({
      requireOk: true,
      requireFullMemory: false,
      maxFailedChecks: 0,
      requireGitCommit: true,
      requirePackageVersion: true,
    });
    expect(Object.isFrozen(durable)).toBe(true);
    expect(Object.isFrozen(durable.summaryLoop)).toBe(true);
    expect(Object.isFrozen(durable.snapshotPreview.allowedModes)).toBe(true);

    const customized = createMemoryQualityPreset("full", {
      summaryLoop: {
        minUniqueSourceRefs: 5,
        requiredEvidenceSourceTypes: ["reddit", "github"],
      },
      proofArtifact: {
        maxDurationMs: 30_000,
      },
    });

    expect(customized.summaryLoop).toMatchObject({
      minUniqueSourceRefs: 5,
      requiredEvidenceSourceTypes: ["reddit", "github"],
      requiredRetrieval: ["vector", "graph"],
    });
    expect(customized.proofArtifact).toMatchObject({
      requireFullMemory: true,
      maxDurationMs: 30_000,
      requiredAdapters: ["qdrant", "graphiti"],
    });
    expect(MEMORY_QUALITY_PRESETS.full.summaryLoop.minUniqueSourceRefs).toBe(2);
    expect(
      MEMORY_QUALITY_PRESETS.full.proofArtifact.maxDurationMs,
    ).toBeUndefined();
  });

  it("creates preset-aligned memory summary loop plans", () => {
    const durablePlan = createMemorySummaryLoopPlan(
      {
        sourceEvidence: {
          continueOnError: true,
          items: [],
        },
        brief: {
          query: "What changed in AI agents today?",
          spaceSlug: "workspace",
          memoryScopeExternalRefs: ["topic:ai-agents"],
          includeSearch: false,
          includeDigest: false,
        },
        qualityPolicy: {
          minDigestSections: 0,
        },
      },
      {
        preset: "durable",
        summaryPolicy: {
          requiredEvidenceSourceTypes: ["reddit", "github"],
        },
      },
    );

    expect(durablePlan.policy).toMatchObject({
      requireReadiness: true,
      requireSourceEvidence: true,
      requireOutboxDrain: true,
      requireQuality: true,
      requiredEvidenceSourceTypes: ["reddit", "github"],
    });
    expect(durablePlan.input.brief).toMatchObject({
      includeSearch: true,
      includeDigest: true,
    });
    expect(durablePlan.input.qualityPolicy).toMatchObject({
      requireSearch: true,
      requireDigest: true,
      minDigestSections: 0,
    });
    expect(durablePlan.input.readiness).toMatchObject({
      requiredAdapters: [],
      requiredRetrieval: [],
      requireDerivedRetrieval: false,
      assertReady: true,
    });
    expect(durablePlan.input.outboxDrain).toMatchObject({
      throwOnFailure: true,
    });
    expect(Object.isFrozen(durablePlan.input.qualityPolicy)).toBe(true);

    const fullPlan = createMemorySummaryLoopPlan(
      {
        brief: {
          query: "Prove full memory retrieval",
          spaceSlug: "workspace",
          memoryScopeExternalRefs: ["topic:ai-agents"],
          tokenBudget: 900,
        },
      },
      {
        preset: "full",
      },
    );

    expect(fullPlan.input.readiness).toMatchObject({
      query: "Prove full memory retrieval",
      includeContextProbe: true,
      includeSearchProbe: true,
      spaceSlug: "workspace",
      memoryScopeExternalRefs: ["topic:ai-agents"],
      tokenBudget: 900,
      requiredAdapters: ["qdrant", "graphiti"],
      requiredRetrieval: ["vector", "graph"],
      requireDerivedRetrieval: true,
      assertReady: true,
    });
    expect(fullPlan.input.qualityPolicy).toMatchObject({
      requireDerivedRetrieval: true,
      requiredRetrieval: ["vector", "graph"],
    });

    const litePlan = createMemorySummaryLoopPlan(
      {
        brief: {
          query: "Smoke summary",
          spaceSlug: "workspace",
          memoryScopeExternalRefs: ["topic:ai-agents"],
        },
      },
      {
        preset: "lite",
      },
    );

    expect(litePlan.input.readiness).toBe(false);
    expect(litePlan.input.outboxDrain).toBeUndefined();
    expect(litePlan.policy).toMatchObject({
      requireQuality: true,
      minContextItems: 1,
    });
  });
});
