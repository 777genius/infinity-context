import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  InfinityContextError,
  assertFullMemoryProofArtifact,
  buildFullMemoryProofArtifact,
  evaluateFullMemoryProofArtifact,
  runFullMemoryProof,
} from "../src/index.js";
import {
  RecordingTransport,
  anchorRecord,
  captureRecord,
  contextLinkRecord,
  contextLinkSuggestionRecord,
  contextResponse,
  digestResponse,
  factRecord,
  jsonResponse,
  memorySuggestionRecord,
  scopeRecord,
  searchResponse,
  spaceRecord,
} from "./fixtures.js";

describe("full memory proof", () => {
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
      jsonResponse({ data: scopeRecord("scope_workspace", "workspace-global") }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: scopeRecord("scope_topic", "topic:full-memory-proof:feedback") }),
      jsonResponse({ data: [] }),
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
      jsonResponse({ data: { id: "workflow_episode_1", status: "active" } }, 201),
      jsonResponse({
        data: {
          ...captureRecord("workflow_capture_1"),
          duplicate: false,
          created_suggestions: 0,
          suggestion_ids: [],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: { candidates: [], diagnostics: { persisted: true } } }),
      jsonResponse({ data: { id: "workflow_episode_2", status: "active" } }, 201),
      jsonResponse({
        data: {
          ...captureRecord("workflow_capture_2"),
          duplicate: false,
          created_suggestions: 0,
          suggestion_ids: [],
          auto_applied_facts: 0,
          auto_applied_fact_ids: [],
        },
      }, 201),
      jsonResponse({ data: { candidates: [], diagnostics: { persisted: true } } }),
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
          counts: { pending: 0, retry_pending: 0, done: 12 },
          oldest_active_lag_seconds: null,
          items: [],
          next_cursor: null,
        },
      }),
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
        enabled_adapters: ["qdrant", "graphiti"],
        supports_qdrant: true,
        supports_graphiti: true,
      }),
      jsonResponse({ adapters: { qdrant: "ok", graphiti: "ok" } }),
      jsonResponse({ requests: 12 }),
      jsonResponse({ backend: "postgres" }),
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
      jsonResponse({ data: [contextLinkSuggestionRecord("maintenance_link_suggestion_1")] }),
      jsonResponse({ data: [memorySuggestionRecord("maintenance_memory_suggestion_1")] }),
      jsonResponse({ data: [] }),
      jsonResponse({ data: [{ ...captureRecord("maintenance_capture_1"), consolidation_status: "pending" }] }),
      jsonResponse({ data: [] }),
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
      jsonResponse(contextResponse("sdk-proof", {
        retrieval_sources_used: ["vector", "graph"],
        vector_query_count: 4,
        graph_query_count: 3,
      })),
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
      sourceEvidenceBatchRecorded: true,
      sourceEvidenceBatchSummarized: true,
      anchorCreated: true,
      anchorBackfillReadable: true,
      memoryBrowserReadable: true,
      memoryInspectionReadable: true,
      maintenancePlanReadable: true,
      operationsConsoleReadable: true,
      outboxDrained: true,
      usageReadable: true,
      snapshotPreviewSucceeded: true,
      derivedRetrievalUsed: true,
      vectorHealthy: true,
      graphHealthy: true,
    });
    expect(report.created.captureId).toBe("capture_1");
    expect(report.created.anchorId).toBe("anchor_1");
    expect(report.observed.suggestionsCreated).toBe(1);
    expect(report.observed.sourceEvidenceBatchSummary).toMatchObject({
      total: 2,
      completed: 2,
      skipped: 0,
      succeeded: 2,
      failed: 0,
      bySourceType: { "sdk-full-memory-proof": 2 },
    });
    expect(report.observed.anchorBackfillCreated).toBe(1);
    expect(report.observed.memoryInspectionIssueCount).toBe(0);
    expect(report.observed.memoryInspectionSections).toContain("runtimeDiagnostics");
    expect(report.observed.maintenanceActionableCount).toBe(3);
    expect(report.observed.maintenanceIssueCount).toBe(0);
    expect(report.observed.outboxDrainDiagnostics).toMatchObject({
      attempts: 1,
      blocking_count: 0,
      failure_count: 0,
    });
    expect(report.observed.usageResourceCount).toBe(0);
    expect(report.retrieval.vector.queryCount).toBe(4);
    expect(report.retrieval.graph.queryCount).toBe(3);
    const artifact = buildFullMemoryProofArtifact({
      report,
      startedAt: "2026-06-06T00:00:00.000Z",
      finishedAt: "2026-06-06T00:00:02.500Z",
      metadata: {
        sdk: { packageName: "@infinity-context/sdk", packageVersion: "0.1.0" },
        git: { commitSha: "abc123", branch: "main", repository: "777genius/memo-stack" },
        runtime: { baseUrl: "http://memory.test", requireFullMemory: true },
      },
    });

    expect(artifact).toMatchObject({
      schemaVersion: "infinity_context.full_memory_proof_artifact.v1",
      generatedAt: "2026-06-06T00:00:02.500Z",
      startedAt: "2026-06-06T00:00:00.000Z",
      finishedAt: "2026-06-06T00:00:02.500Z",
      durationMs: 2500,
      ok: true,
      metadata: {
        sdk: { packageName: "@infinity-context/sdk", packageVersion: "0.1.0" },
        git: { commitSha: "abc123", branch: "main", repository: "777genius/memo-stack" },
        runtime: { baseUrl: "http://memory.test", requireFullMemory: true },
      },
      summary: {
        ok: true,
        mode: "full",
        durableOk: true,
        fullMemoryOk: true,
        checksTotal: 21,
        checksPassed: 21,
        checksFailed: 0,
        failedChecks: [],
        enabledAdapters: ["qdrant", "graphiti"],
        supportsQdrant: true,
        supportsGraphiti: true,
        vectorHealthy: true,
        graphHealthy: true,
        derivedRetrievalUsed: true,
        vectorQueryCount: 4,
        graphQueryCount: 3,
        sourceEvidenceSuccessRate: 1,
        memoryInspectionIssueCount: 0,
        maintenanceActionableCount: 3,
        outboxBlockingCount: 0,
      },
    });
    expect(artifact.report).toBe(report);
    const artifactEvaluation = assertFullMemoryProofArtifact(artifact, {
      requireFullMemory: true,
      maxFailedChecks: 0,
      minChecksPassed: 21,
      minSourceEvidenceSuccessRate: 1,
      maxMemoryInspectionIssues: 0,
      maxOutboxBlocking: 0,
      requiredAdapters: ["qdrant", "graphiti"],
      requiredRetrievalSources: ["vector"],
      requireGitCommit: true,
      requirePackageVersion: true,
    });
    expect(artifactEvaluation).toMatchObject({
      ok: true,
      errors: [],
      policy: {
        requireFullMemory: true,
        maxFailedChecks: 0,
        requiredAdapters: ["qdrant", "graphiti"],
      },
    });

    const failedEvaluation = evaluateFullMemoryProofArtifact(artifact, {
      requiredAdapters: ["pinecone"],
      maxDurationMs: 1,
    });
    expect(failedEvaluation).toMatchObject({
      ok: false,
      errors: [
        "proof took 2500ms, expected at most 1ms",
        "required adapter is missing: pinecone",
      ],
    });
    expect(() => assertFullMemoryProofArtifact(artifact, {
      requiredAdapters: ["pinecone"],
    })).toThrowError(InfinityContextError);
    expect(transport.requests.map((request) => `${request.method} ${request.url.pathname}`)).toEqual([
      "GET /v1/capabilities",
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "GET /v1/memory-scopes",
      "POST /v1/memory-scopes",
      "GET /v1/memory-scopes",
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
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/link-suggestions",
      "POST /v1/episodes",
      "POST /v1/captures",
      "POST /v1/link-suggestions",
      "GET /v1/anchors",
      "POST /v1/anchors",
      "POST /v1/anchors/backfill",
      "GET /v1/anchors/merge-suggestions",
      "GET /v1/diagnostics/outbox",
      "GET /v1/memory-browser",
      "GET /v1/operations-console",
      "GET /v1/memory-browser",
      "GET /v1/operations-console",
      "GET /v1/usage",
      "GET /v1/capabilities",
      "GET /v1/diagnostics/adapters",
      "GET /v1/diagnostics/metrics",
      "GET /v1/diagnostics/storage",
      "GET /v1/operations-console",
      "GET /v1/context-link-suggestions",
      "GET /v1/suggestions",
      "GET /v1/anchors/merge-suggestions",
      "GET /v1/diagnostics/captures",
      "GET /v1/asset-extractions",
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
});
