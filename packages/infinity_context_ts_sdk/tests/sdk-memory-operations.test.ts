import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  assertMemoryInspectionPolicy,
  assertMemoryMaintenancePolicy,
  assertMemorySummaryLoopPolicy,
  evaluateMemoryInspectionPolicy,
  evaluateMemoryMaintenancePolicy,
  evaluateMemorySummaryLoopPolicy,
  summarizeMemoryInspection,
  summarizeMemoryMaintenance,
  summarizeMemorySummaryLoop,
} from "../src/index.js";
import {
  RecordingTransport,
  anchorRecord,
  assetExtractionJobRecord,
  captureRecord,
  contextLinkSuggestionRecord,
  contextResponse,
  digestResponse,
  expectCompletedSignalsDetached,
  factRecord,
  jsonResponse,
  memoryBrowserData,
  memorySuggestionRecord,
  operationsConsoleData,
  outboxItem,
  scopeRecord,
  searchResponse,
  spaceRecord,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("downloads byte responses without JSON parsing", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const transport = new RecordingTransport([
      { status: 200, headers: new Headers(), body: bytes },
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(client.assets.downloadAsset("asset_1")).resolves.toEqual(bytes);
  });

  it("runs a durable memory summary loop across topology, readiness, evidence and brief", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse({ data: spaceRecord("space_1", "workspace") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse(
        { data: scopeRecord("scope_topic", "topic:ai-agents") },
        201,
      ),
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("loop-readiness", {
          vector_query_count: 2,
          graph_query_count: 1,
        }),
      ),
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
      jsonResponse(
        contextResponse("loop-brief", {
          retrieval_sources_used: ["vector", "graph"],
          vector_query_count: 4,
          graph_query_count: 2,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["graph"],
          vector_query_count: 3,
          graph_query_count: 2,
        }),
      ),
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
    const report = summarizeMemorySummaryLoop(loop);
    expect(report).toMatchObject({
      ok: true,
      status: "ready",
      gates: {
        readiness: { ok: true, status: "passed", errors: [], warnings: [] },
        sourceEvidence: {
          ok: true,
          status: "passed",
          errors: [],
          warnings: [],
        },
        outboxDrain: { ok: true, status: "passed", errors: [], warnings: [] },
        quality: { ok: true, status: "passed", errors: [], warnings: [] },
      },
      sourceEvidence: {
        total: 2,
        completed: 2,
        skipped: 0,
        succeeded: 2,
        failed: 0,
        successRate: 1,
        bySourceType: { reddit: 1, github: 1 },
      },
      summary: {
        contextItems: 1,
        searchItems: 1,
        digestSections: 0,
        sourceRefsTotal: 2,
        uniqueSourceRefs: 1,
        renderedMarkdown: "loop-brief: concise digest",
      },
      retrieval: {
        derivedRetrievalUsed: true,
        vectorHealthy: true,
        graphHealthy: true,
      },
      warnings: [],
      errors: [],
    });
    expect(
      evaluateMemorySummaryLoopPolicy(report, {
        requireReadiness: true,
        requireSourceEvidence: true,
        requireOutboxDrain: true,
        requireQuality: true,
        minSourceEvidenceSuccessRate: 1,
        maxSourceEvidenceFailures: 0,
        minContextItems: 1,
        minSearchItems: 1,
        minUniqueSourceRefs: 1,
        requiredSourceEvidenceTypes: ["reddit", "github"],
        requiredEvidenceSourceTypes: ["sdk-full-memory-proof"],
        requireDerivedRetrieval: true,
        requiredRetrieval: ["vector", "graph"],
      }),
    ).toMatchObject({
      ok: true,
      errors: [],
    });
    expect(() =>
      assertMemorySummaryLoopPolicy(loop, {
        requireReadiness: true,
        requireSourceEvidence: true,
        requireOutboxDrain: true,
        requireQuality: true,
        minDigestSections: 1,
        minUniqueSourceRefs: 2,
        minCitations: 1,
        requiredEvidenceSourceTypes: ["github"],
      }),
    ).toThrow(InfinityContextError);
    expect(() =>
      assertMemorySummaryLoopPolicy(loop, {
        minDigestSections: 1,
      }),
    ).toThrow(
      "Memory summary loop policy failed: digest sections 0, expected at least 1",
    );
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 13 }, () => "trace_loop"));
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
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["keyword"],
          vector_status: "disabled",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }),
      ),
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

    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["POST /v1/context", "POST /v1/search", "POST /v1/digest"]);
  });

  it("inspects memory across read models, diagnostics, graph and snapshot preview", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: memoryBrowserData() }),
      jsonResponse({ data: operationsConsoleData() }),
      jsonResponse({
        data: {
          space_id: "space_1",
          plan: {
            tier: "beta",
            display_name: "Beta",
            media_analysis_seconds_per_month: 3600,
          },
          resources: [],
        },
      }),
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse({ adapters: { qdrant: "ok", graphiti: "ok" } }),
      jsonResponse({ requests: 12 }),
      jsonResponse({ backend: "postgres" }),
      jsonResponse({
        data: { memory_scope_id: "scope_1", vector_status: "ok" },
      }),
      jsonResponse({ data: { nodes: [], edges: [] } }),
      jsonResponse({
        data: { facts: [] },
        manifest: { version: "snapshot.v1" },
      }),
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
    expect(inspection.operationsConsole?.data.diagnostics).toMatchObject({
      queue_lag: 0,
    });
    expect(inspection.usage?.data.plan.tier).toBe("beta");
    expect(inspection.capabilities?.enabled_adapters).toEqual([
      "qdrant",
      "graphiti",
    ]);
    expect(inspection.runtimeDiagnostics?.adapters).toMatchObject({
      adapters: { qdrant: "ok" },
    });
    expect(inspection.graph).toMatchObject({ data: { nodes: [], edges: [] } });
    expect(inspection.snapshotPreview).toMatchObject({
      data: { dry_run: true, conflicts: [] },
    });
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
    const report = summarizeMemoryInspection(inspection);
    expect(report).toMatchObject({
      ok: true,
      status: "ready",
      counts: {
        facts: 1,
        documents: 0,
        anchors: 0,
        operationExtractionJobs: 0,
        operationContextLinkSuggestions: 0,
      },
      runtime: {
        enabledAdapters: ["qdrant", "graphiti"],
        supportsQdrant: true,
        supportsGraphiti: true,
        diagnosticsSections: ["adapters", "memoryScope", "metrics", "storage"],
      },
      sections: {
        memoryBrowser: { status: "present", present: true, issues: [] },
        operationsConsole: { status: "present", present: true, issues: [] },
        usage: { status: "present", present: true, issues: [] },
        capabilities: { status: "present", present: true, issues: [] },
        runtimeDiagnostics: { status: "present", present: true, issues: [] },
        graph: { status: "present", present: true, issues: [] },
        snapshotPreview: { status: "present", present: true, issues: [] },
      },
    });
    expect(
      evaluateMemoryInspectionPolicy(report, {
        requireComplete: true,
        requiredAdapters: ["qdrant", "graphiti"],
        requiredSections: ["graph", "snapshotPreview"],
        minFacts: 1,
        maxOperationExtractionJobs: 0,
        maxOperationContextLinkSuggestions: 0,
      }),
    ).toMatchObject({
      ok: true,
      errors: [],
    });
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 11 }, () => "trace_inspect_memory"));
    expect(transport.requests[8]?.url.searchParams.get("max_facts")).toBe("25");
    expect(transport.requests[9]?.url.searchParams.get("redacted")).toBe(
      "true",
    );
    expect(transport.bodies.at(-1)).toMatchObject({
      snapshot: { facts: [] },
      manifest: { version: "snapshot.v1" },
      merge_strategy: "fail_on_conflict",
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel inspection",
    );
  });

  it("returns partial memory inspection issues when optional sections fail", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: memoryBrowserData() }),
      jsonResponse(
        {
          error: {
            code: "operations_unavailable",
            message: "temporarily unavailable",
          },
        },
        503,
      ),
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

    expect(inspection.memoryBrowser.data.memory_scope?.external_ref).toBe(
      "topic:ai-agents",
    );
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
    const report = summarizeMemoryInspection(inspection);
    expect(report).toMatchObject({
      ok: false,
      status: "failed",
      sections: {
        memoryBrowser: { status: "present", present: true },
        operationsConsole: { status: "failed", present: false },
        usage: { status: "skipped", present: false },
      },
      errors: ["operationsConsole: temporarily unavailable"],
    });
    expect(() =>
      assertMemoryInspectionPolicy(report, {
        requireComplete: true,
        requiredSections: ["operationsConsole"],
        maxIssues: 0,
      }),
    ).toThrow(InfinityContextError);
    expect(() =>
      assertMemoryInspectionPolicy(report, {
        requiredSections: ["operationsConsole"],
      }),
    ).toThrow(
      "Memory inspection policy failed: operationsConsole: temporarily unavailable",
    );
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
    const report = summarizeMemoryMaintenance(plan);
    expect(report).toMatchObject({
      ok: true,
      status: "action_required",
      totalActionable: 5,
      counts: {
        contextLinkSuggestions: 1,
        memorySuggestions: 1,
        anchorMergeCandidates: 1,
        capturesPendingConsolidation: 1,
        extractionJobs: 1,
      },
      actions: {
        total: 5,
        high: 0,
        medium: 0,
        low: 5,
        byKind: {
          review_context_links: 1,
          resolve_memory_suggestions: 1,
          merge_duplicate_anchors: 1,
          consolidate_captures: 1,
          retry_or_triage_extractions: 1,
        },
      },
      partial: false,
      errors: [],
    });
    expect(
      evaluateMemoryMaintenancePolicy(report, {
        requireComplete: true,
        maxIssues: 0,
        maxTotalActionable: 5,
        maxHighPriorityActions: 0,
        maxExtractionJobs: 1,
      }),
    ).toMatchObject({
      ok: true,
      errors: [],
    });
    expect(() =>
      assertMemoryMaintenancePolicy(report, {
        maxTotalActionable: 0,
        blockedActionKinds: ["retry_or_triage_extractions"],
      }),
    ).toThrow(
      "Memory maintenance policy failed: total actionable maintenance items 5, expected at most 0",
    );
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "GET /v1/operations-console",
      "GET /v1/context-link-suggestions",
      "GET /v1/suggestions",
      "GET /v1/anchors/merge-suggestions",
      "GET /v1/diagnostics/captures",
      "GET /v1/asset-extractions",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 6 }, () => "trace_maintenance"));
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe(
      "pending",
    );
    expect(transport.requests[3]?.url.searchParams.get("kind")).toBe("project");
    expect(
      transport.requests[4]?.url.searchParams.get("consolidation_status"),
    ).toBe("pending");
    expect(transport.requests[5]?.url.searchParams.get("status")).toBe(
      "failed",
    );
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel maintenance",
    );
  });

  it("returns partial maintenance plan issues when optional queues fail", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: operationsConsoleData() }),
      jsonResponse(
        { error: { code: "queue_unavailable", message: "queue unavailable" } },
        503,
      ),
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

    expect(plan.queues.operationsConsole?.data.diagnostics).toMatchObject({
      queue_lag: 0,
    });
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
    const report = summarizeMemoryMaintenance(plan);
    expect(report).toMatchObject({
      ok: false,
      status: "failed",
      partial: true,
      totalActionable: 0,
      errors: ["contextLinkSuggestions: queue unavailable"],
    });
    expect(() =>
      assertMemoryMaintenancePolicy(report, {
        requireComplete: true,
        maxIssues: 0,
      }),
    ).toThrow(InfinityContextError);
  });
});
