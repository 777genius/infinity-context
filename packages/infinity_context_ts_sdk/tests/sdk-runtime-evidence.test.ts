import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  runRuntimeCanary,
  summarizeSourceEvidenceBatch,
  waitForRuntimeCanary,
} from "../src/index.js";
import {
  RecordingTransport,
  captureRecord,
  contextResponse,
  documentRecord,
  expectCompletedSignalsDetached,
  factRecord,
  jsonResponse,
  searchResponse,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("runs a non-mutating runtime canary against full memory retrieval", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary", {
          retrieval_sources_used: ["vector", "graph"],
          vector_status: "ok",
          graph_status: "ok",
          vector_query_count: 3,
          graph_query_count: 2,
        }),
      ),
      jsonResponse(
        searchResponse({
          retrieval_sources_used: ["vector"],
          vector_status: "ok",
          graph_status: "ok",
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["GET /v1/capabilities", "POST /v1/context", "POST /v1/search"]);
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
      jsonResponse({
        enabled_adapters: [],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary-lite", {
          vector_status: "degraded",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }),
      ),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["GET /v1/capabilities", "POST /v1/context"]);
  });

  it("waits for runtime canary readiness with abortable polling", async () => {
    const controller = new AbortController();
    const sleeps: number[] = [];
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: [],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary-wait-lite", {
          vector_status: "disabled",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }),
      ),
      jsonResponse({
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary-wait-full", {
          retrieval_sources_used: ["vector", "graph"],
          vector_status: "ok",
          graph_status: "ok",
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "GET /v1/capabilities",
      "POST /v1/context",
      "GET /v1/capabilities",
      "POST /v1/context",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual([
      "trace_canary_wait",
      "trace_canary_wait",
      "trace_canary_wait",
      "trace_canary_wait",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel runtime canary wait",
    );
  });

  it("times out runtime canary waits with typed readiness details", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        enabled_adapters: [],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary-timeout-1", {
          vector_status: "disabled",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }),
      ),
      jsonResponse({
        enabled_adapters: [],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse(
        contextResponse("canary-timeout-2", {
          vector_status: "degraded",
          graph_status: "disabled",
          vector_query_count: 0,
          graph_query_count: 0,
        }),
      ),
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
      jsonResponse({
        data: [factRecord("fact_1"), factRecord("fact_2")],
        next_cursor: "cursor_2",
      }),
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

    expect(facts.map((fact) => fact.id)).toEqual([
      "fact_1",
      "fact_2",
      "fact_3",
    ]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual(
      [
        "http://memory.test/v1/facts?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Apreferences&status=active&tag=summary&limit=2",
        "http://memory.test/v1/facts?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Apreferences&status=active&tag=summary&limit=2&cursor=cursor_2",
      ],
    );
  });

  it("records feedback through the workflow facade with safe capture defaults", async () => {
    const transport = new RecordingTransport([
      jsonResponse(
        {
          data: {
            ...captureRecord("capture_1"),
            duplicate: false,
            created_suggestions: 0,
            suggestion_ids: [],
            auto_applied_facts: 0,
            auto_applied_fact_ids: [],
          },
        },
        201,
      ),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["POST /v1/captures", "POST /v1/facts"]);
    expect(transport.requests[0]?.headers.get("idempotency-key")).toBe(
      "feedback:1",
    );
    expect(transport.requests[1]?.headers.get("idempotency-key")).toBe(
      "feedback:1:fact",
    );
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
      evidence_refs: [
        { source_type: "social-monitor", source_id: "feedback:1" },
      ],
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
      jsonResponse(
        {
          data: {
            ...captureRecord("capture_1"),
            duplicate: false,
            created_suggestions: 0,
            suggestion_ids: [],
            auto_applied_facts: 0,
            auto_applied_fact_ids: [],
          },
        },
        201,
      ),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/documents",
      "POST /v1/documents/doc_1/process",
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/facts",
      "POST /v1/link-suggestions",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual([
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
      "trace_source_evidence",
    ]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel source evidence",
    );
    expect(
      transport.requests.map((request) =>
        request.headers.get("idempotency-key"),
      ),
    ).toEqual([
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
      jsonResponse(
        {
          data: {
            ...captureRecord("capture_1"),
            duplicate: false,
            created_suggestions: 0,
            suggestion_ids: [],
            auto_applied_facts: 0,
            auto_applied_fact_ids: [],
          },
        },
        201,
      ),
      jsonResponse({ data: { candidates: [], diagnostics: {} } }),
      jsonResponse(
        {
          error: {
            code: "memory.provider_payload_invalid",
            message: "provider payload rejected",
            retryable: false,
          },
        },
        400,
        { "x-request-id": "req_bad_item" },
      ),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/link-suggestions",
      "POST /v1/episodes",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-batch-id")),
    ).toEqual(["batch_1", "batch_1", "batch_1", "batch_1"]);
    expect(
      transport.requests.map((request) => request.headers.get("x-item-id")),
    ).toEqual([null, null, null, "item_bad"]);
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(requestSignals, controller, "cancel batch");
  });

  it("stops source evidence batches after the first error when configured", async () => {
    const transport = new RecordingTransport([
      jsonResponse(
        {
          error: {
            code: "memory.provider_payload_invalid",
            message: "provider payload rejected",
            retryable: false,
          },
        },
        400,
      ),
      jsonResponse(
        { data: { id: "episode_after_stop", status: "active" } },
        201,
      ),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["POST /v1/episodes"]);
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
          result: {
            sourceRefs: [{ source_type: "reddit", source_id: "reddit:t3_ok" }],
          },
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
});
