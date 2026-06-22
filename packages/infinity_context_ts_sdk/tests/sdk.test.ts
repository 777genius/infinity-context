import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  MemoryScope,
  ReadScope,
  ValueError,
  assertFullMemoryReady,
  evaluateRuntimeReadiness,
  healthyRetrievalComponents,
  retrievalDiagnostics,
  runFullMemoryProof,
  usedDerivedRetrieval,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
} from "../src/index.js";

class RecordingTransport implements HttpTransport {
  readonly requests: HttpRequest[] = [];
  readonly bodies: unknown[] = [];
  #responses: HttpResponse[];

  constructor(responses: HttpResponse[]) {
    this.#responses = [...responses];
  }

  async send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    if (request.body?.kind === "json") {
      this.bodies.push(request.body.value);
    }
    return this.#responses.shift() ?? jsonResponse({ data: { ok: true } });
  }
}

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

  it("runs the full memory proof loop through public SDK clients", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: spaceRecord("space_1", "sdk-full-memory-proof:sdk-proof") }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: scopeRecord("scope_workspace", "workspace-global") }),
      jsonResponse({ data: scopeRecord("scope_topic", "topic:full-memory-proof:feedback") }),
      jsonResponse({ data: scopeRecord("scope_source", "source:full-memory-proof-transcript") }),
      jsonResponse({ data: factRecord("fact_architecture") }),
      jsonResponse({ data: factRecord("fact_feedback") }),
      jsonResponse({ data: factRecord("fact_source") }),
      jsonResponse({ data: { id: "doc_1", title: "SDK proof doc", status: "active" } }),
      jsonResponse({ data: { id: "doc_1", title: "SDK proof doc", status: "processed" } }),
      jsonResponse({ data: { id: "episode_1" } }),
      jsonResponse({ data: contextLinkRecord("link_1") }),
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
      jsonResponse({
        data: {
          created: 1,
          existing: 0,
          failed: 0,
          stopped: false,
          results: [{ index: 0, status: "created", suggestion: memorySuggestionRecord("suggestion_1") }],
        },
      }, 201),
      jsonResponse({ data: [] }),
      jsonResponse({ data: anchorRecord("anchor_1", "sdk-proof full memory proof") }),
      jsonResponse({
        data: {
          anchors: [anchorRecord("anchor_1", "sdk-proof full memory proof")],
          created: 1,
          updated: 0,
          sources: [{ source_type: "fact", scanned: 2, observed: 1, skipped_conflicts: 0 }],
          diagnostics: { scanned_sources: 1 },
        },
      }),
      jsonResponse({ data: [] }),
      jsonResponse({
        data: {
          generated_at: "2026-06-06T00:00:00.000Z",
          memory_scope: scopeRecord("scope_topic", "topic:full-memory-proof:feedback"),
          facts: [factRecord("fact_feedback")],
          episodes: [],
          documents: [],
          chunks: [],
          extraction_jobs: [],
          threads: [],
          captures: [captureRecord("capture_1")],
          assets: [],
          anchors: [],
          context_links: [],
          context_link_suggestions: [],
          stats: { facts: 1, captures: 1 },
          visual_summary: { status: "ready" },
          quick_actions: [],
          diagnostics: { browser_version: "memory-browser-v1" },
        },
      }),
      jsonResponse({
        data: {
          generated_at: "2026-06-06T00:00:00.000Z",
          scope: { space_id: "space_1", memory_scope_id: "scope_topic" },
          extraction_status_counts: {},
          link_suggestion_status_counts: { pending: 1 },
          extraction_jobs: [],
          context_link_suggestions: [],
          diagnostics: { console_version: "memory-operations-console-v1" },
        },
      }),
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
        data: { schema_version: "memory_scope_snapshot.v1", facts: [] },
        status: "ok",
        counts: { facts: 1 },
        redacted: true,
        manifest: { snapshot_sha256: "snapshot_sha" },
      }),
      jsonResponse({ data: { dry_run: true, created: 0, updated: 0, conflicts: [] } }),
      jsonResponse(contextResponse("sdk-proof", { vector_query_count: 4, graph_query_count: 3 })),
      jsonResponse(searchResponse({ vector_query_count: 4, graph_query_count: 3 })),
      jsonResponse(digestResponse("sdk-proof")),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const report = await runFullMemoryProof({
      client,
      runId: "sdk-proof",
      sleep: async () => undefined,
      pollAttempts: 1,
      now: () => new Date("2026-06-06T00:00:00.000Z"),
    });

    expect(report.ok).toBe(true);
    expect(report.checks).toEqual({
      capabilitiesFullMemory: true,
      contextReturnedEvidence: true,
      searchReturnedEvidence: true,
      digestReturnedEvidence: true,
      contextLinkCreated: true,
      captureCreated: true,
      suggestionBatchCreated: true,
      anchorCreated: true,
      anchorBackfillReadable: true,
      memoryBrowserReadable: true,
      operationsConsoleReadable: true,
      usageReadable: true,
      snapshotPreviewSucceeded: true,
      derivedRetrievalUsed: true,
      vectorHealthy: true,
      graphHealthy: true,
    });
    expect(report.created.captureId).toBe("capture_1");
    expect(report.created.anchorId).toBe("anchor_1");
    expect(report.observed.suggestionsCreated).toBe(1);
    expect(report.observed.anchorBackfillCreated).toBe(1);
    expect(report.observed.usageResourceCount).toBe(0);
    expect(report.retrieval.vector.queryCount).toBe(4);
    expect(report.retrieval.graph.queryCount).toBe(3);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/memory-scopes",
      "GET /v1/memory-scopes",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "POST /v1/facts",
      "POST /v1/facts",
      "POST /v1/facts",
      "POST /v1/documents",
      "POST /v1/documents/doc_1/process",
      "POST /v1/episodes",
      "POST /v1/context-links",
      "POST /v1/captures",
      "POST /v1/suggestions/batch",
      "GET /v1/anchors",
      "POST /v1/anchors",
      "POST /v1/anchors/backfill",
      "GET /v1/anchors/merge-suggestions",
      "GET /v1/memory-browser",
      "GET /v1/operations-console",
      "GET /v1/usage",
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/preview",
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
    expect(transport.bodies).toContainEqual(expect.objectContaining({
      memory_scope_external_refs: [
        "workspace-global",
        "topic:full-memory-proof:feedback",
        "source:full-memory-proof-transcript",
      ],
    }));
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

function jsonResponse(body: unknown, status = 200): HttpResponse {
  return {
    status,
    headers: new Headers(),
    body: JSON.stringify(body),
  };
}

function spaceRecord(id: string, slug: string) {
  return {
    id,
    slug,
    name: "SDK proof",
    status: "active",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

function scopeRecord(id: string, externalRef: string) {
  return {
    id,
    space_id: "space_1",
    external_ref: externalRef,
    name: externalRef,
    status: "active",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

function factRecord(id: string) {
  return {
    id,
    text: `${id} text`,
    kind: "note",
    status: "active",
    version: 1,
  };
}

function documentChunkRecord(id: string, sequence: number) {
  return {
    id,
    document_id: "doc_1",
    sequence,
    text: `${id} text`,
    token_estimate: 3,
    metadata: {},
  };
}

function memorySuggestionRecord(id: string) {
  return {
    id,
    status: "pending",
    candidate_text: `${id} candidate`,
  };
}

function anchorRecord(id: string, label: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    kind: "project",
    normalized_key: label.toLowerCase().replaceAll(" ", "-"),
    label,
    aliases: [],
    description: null,
    status: "active",
    confidence: "medium",
    evidence_refs: [],
    observed_at: "2026-06-06T00:00:00.000Z",
    valid_from: null,
    valid_to: null,
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

function contextResponse(runId: string, diagnostics: Record<string, unknown>) {
  return {
    data: {
      bundle_id: "bundle_1",
      rendered_text: `${runId}: Qdrant and Graphiti memory evidence.`,
      items: [
        {
          item_id: "item_1",
          item_type: "fact",
          text: `${runId}: Qdrant owns vector recall.`,
          score: 0.9,
          source_refs: [{ source_type: "sdk-full-memory-proof", source_id: "fact" }],
        },
      ],
      top_evidence: [],
      answer_support: {
        status: "supported",
        items_returned: 1,
        coverage: {},
        policy: {},
        warnings: [],
      },
      diagnostics: {
        vector_status: "ok",
        graph_status: "ok",
        rag_status: "ok",
        ...diagnostics,
      },
    },
  };
}

function searchResponse(diagnostics: Record<string, unknown>) {
  return {
    data: {
      items: [
        {
          item_id: "item_1",
          item_type: "fact",
          text: "Qdrant owns vector recall.",
          score: 0.9,
          source_refs: [{ source_type: "sdk-full-memory-proof", source_id: "fact" }],
        },
      ],
      top_evidence: [],
      diagnostics: {
        vector_status: "ok",
        graph_status: "ok",
        ...diagnostics,
      },
    },
  };
}

function digestResponse(runId: string) {
  return {
    data: {
      digest_id: "digest_1",
      topic: "SDK proof",
      rendered_markdown: `${runId}: concise digest`,
      sections: [],
      source_refs: [],
      token_estimate: 10,
      diagnostics: { evidence_only: true },
    },
  };
}

function contextLinkRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    source_type: "capture",
    source_id: "capture_1",
    target_type: "fact",
    target_id: "fact_1",
    relation_type: "supports",
    confidence: "medium",
    reason: "reviewed",
    status: "active",
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

function contextLinkSuggestionRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    source_type: "capture",
    source_id: "capture_1",
    target_type: "fact",
    target_id: "fact_1",
    relation_type: "supports",
    confidence: "medium",
    reason: "semantic match",
    score: 0.91,
    status: "pending",
    review_actionable: true,
    available_review_actions: ["approve", "reject"],
    review_state_reason: "pending_user_review",
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
    reviewed_at: null,
    review_reason: null,
    review_audit: { events: [], event_count: 0, truncated: false },
  };
}

function captureRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    thread_id: "thread_1",
    source_agent: "social-monitor",
    source_kind: "hook",
    event_type: "summary.feedback.recorded",
    actor_role: "user",
    text_preview: "User says Reddit source freshness matters.",
    payload_hash: "hash_1",
    status: "active",
    consolidation_status: "pending",
    trust_level: "high",
    source_authority: "user_statement",
    sensitivity: "medium",
    data_classification: "internal",
    evidence_refs: [{ source_type: "summary", source_id: "summary_1" }],
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
    occurred_at: "2026-06-06T00:00:00.000Z",
    received_at: "2026-06-06T00:00:01.000Z",
    trace_id: "trace_1",
    versions: {
      schema: "capture.v1",
      parser: "parser.v1",
      redaction: "redaction.v1",
      admission: "admission.v1",
      normalization: "normalization.v1",
      policy: "policy.v1",
      extractor: "extractor.v1",
      resolver: "resolver.v1",
    },
    last_error_code: null,
  };
}

function assetExtractionJobRecord(id: string) {
  return {
    id,
    asset_id: "asset_1",
    space_id: "space_1",
    memory_scope_id: "scope_1",
    thread_id: "thread_1",
    parser_profile: "markdown-strict",
    parser_config_hash: "parser_hash_1",
    source_sha256_hex: "sha_1",
    status: "running",
    attempt_count: 1,
    safe_error_code: null,
    safe_error_message: null,
    parser_name: "markdown",
    parser_version: "1.0.0",
    model_version: null,
    result_document_ids: ["document_1"],
    metadata: {},
    progress: { phase: "parsing", percent: 60 },
    execution: { available_actions: ["cancel"] },
    usage: { input_bytes: 1024 },
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:01:00.000Z",
    started_at: "2026-06-06T00:00:05.000Z",
    finished_at: null,
  };
}

function extractionArtifactRecord(id: string) {
  return {
    id,
    job_id: "job_1",
    asset_id: "asset_1",
    artifact_type: "markdown",
    storage_backend: "local",
    download_path: `/v1/extraction-artifacts/${id}/download`,
    sha256_hex: "artifact_sha_1",
    byte_size: 256,
    metadata: {},
    created_at: "2026-06-06T00:02:00.000Z",
  };
}
