import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  ReadScope,
  assertMemoryBriefQuality,
  evaluateMemoryBriefQuality,
  summarizeMemoryBriefEvidence,
  type BuildMemoryBriefResult,
} from "../src/index.js";
import {
  RecordingTransport,
  contextResponse,
  digestResponse,
  expectCompletedSignalsDetached,
  factRecord,
  jsonResponse,
  searchResponse,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("builds a memory brief workflow across context, search and digest", async () => {
    const transport = new RecordingTransport([
      jsonResponse(
        contextResponse("brief", {
          retrieval_sources_used: ["keyword", "vector"],
          vector_query_count: 2,
          graph_query_count: 1,
          rag_query_count: 1,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["graph"],
          vector_query_count: 2,
          graph_query_count: 1,
        }),
      ),
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
        memoryScopeExternalRefs: [
          "workspace-global",
          "topic:ai-agents:preferences",
        ],
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["POST /v1/context", "POST /v1/search", "POST /v1/digest"]);
    expect(transport.bodies[0]).toMatchObject({
      memory_scope_external_refs: [
        "workspace-global",
        "topic:ai-agents:preferences",
      ],
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
      jsonResponse(
        contextResponse("brief-quality", {
          retrieval_sources_used: ["vector", "graph", "rag"],
          vector_query_count: 2,
          graph_query_count: 1,
          rag_query_count: 1,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["graph"],
          graph_query_count: 1,
        }),
      ),
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
      memoryScopeExternalRefs: [
        "workspace-global",
        "topic:ai-agents:preferences",
      ],
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
              source_refs: [
                { source_type: "reddit", source_id: "t3_ai_agents" },
              ],
              citations: [
                {
                  label: "R1",
                  source_type: "reddit",
                  source_id: "t3_ai_agents",
                },
              ],
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
              citation: {
                label: "G1",
                source_type: "github",
                source_id: "issue_1",
              },
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
                  source_refs: [
                    { source_type: "reddit", source_id: "t3_ai_agents" },
                  ],
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
    expect(() =>
      assertMemoryBriefQuality(poorBrief, {
        requireDigest: true,
        requireDerivedRetrieval: true,
        requiredRetrieval: ["vector"],
        failOnWarnings: true,
      }),
    ).toThrowError(InfinityContextError);

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
      expect((error as InfinityContextError).code).toBe(
        "memory.brief_quality_failed",
      );
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
      jsonResponse(
        contextResponse("seed-brief", {
          retrieval_sources_used: ["vector"],
          vector_query_count: 2,
          rag_query_count: 1,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["graph"],
          graph_query_count: 1,
        }),
      ),
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
    expect(result.brief.diagnostics.retrievalSourcesUsed).toEqual([
      "vector",
      "graph",
    ]);
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/facts",
      "POST /v1/facts",
      "GET /v1/diagnostics/outbox",
      "POST /v1/context",
      "POST /v1/search",
      "POST /v1/digest",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual([
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
      "trace_seed_memory",
    ]);
    expect(
      transport.requests.map((request) =>
        request.headers.get("idempotency-key"),
      ),
    ).toEqual([
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
      source_refs: [
        {
          source_type: "sdk-seed",
          source_id: "social-monitor:seed:ai-agents:fact:0",
        },
      ],
    });
    expect(transport.bodies[1]).toMatchObject({
      space_slug: "social-monitor:tenant:workspace",
      memory_scope_external_ref: "user:user_1",
      source_refs: [{ source_type: "user", source_id: "user_1" }],
    });
    expect(transport.bodies[3]).toMatchObject({
      memory_scope_external_refs: [
        "topic:ai-agents:preferences",
        "user:user_1",
      ],
      query: "Which summary style should today's AI agents digest use?",
      max_facts: 10,
      max_chunks: 4,
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel seed brief",
    );
  });

  it("checks full memory readiness through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("readiness", {
          retrieval_sources_used: ["vector", "graph"],
          vector_query_count: 3,
          graph_query_count: 2,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["vector"],
          vector_query_count: 2,
          graph_query_count: 1,
        }),
      ),
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
        memoryScopeExternalRefs: [
          "workspace-global",
          "topic:ai-agents:preferences",
        ],
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["GET /v1/capabilities", "POST /v1/context", "POST /v1/search"]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(["trace_readiness", "trace_readiness", "trace_readiness"]);
    expect(transport.bodies[0]).toMatchObject({
      query: "Prove full memory runtime before summary generation",
      memory_scope_external_refs: [
        "workspace-global",
        "topic:ai-agents:preferences",
      ],
      token_budget: 900,
      max_facts: 8,
      max_chunks: 6,
    });
    expect(transport.bodies[1]).toMatchObject(
      transport.bodies[0] as Record<string, unknown>,
    );
  });

  it("fails full memory readiness assertions when required adapters are missing", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: [],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["GET /v1/capabilities"]);
  });
});
