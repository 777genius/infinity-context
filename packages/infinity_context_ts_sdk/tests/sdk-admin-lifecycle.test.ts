import { describe, expect, it } from "vitest";
import { InfinityContextClient, ValueError } from "../src/index.js";
import {
  RecordingTransport,
  anchorRecord,
  captureRecord,
  contextLinkRecord,
  contextLinkSuggestionRecord,
  factRecord,
  jsonResponse,
  memorySuggestionRecord,
  scopeRecord,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("validates applied memory review plans", async () => {
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport: new RecordingTransport([]),
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.workflows.applyMemoryReviewPlan({
        summary: {
          total: 0,
          contextLinkReviews: 0,
          suggestionReviews: 0,
          byAction: {},
        },
      }),
    ).rejects.toThrow(
      "applyMemoryReviewPlan requires at least one review item",
    );
  });

  it("supports context link creation, suggestion review and batch validation", async () => {
    const link = contextLinkRecord("link_1");
    const suggestion = contextLinkSuggestionRecord("suggestion_1");
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          candidates: [
            {
              ...suggestion,
              label: "Fact",
              preview: "Target",
              tier: "high",
              reasons: ["semantic"],
            },
          ],
          diagnostics: { candidates: 1 },
        },
      }),
      jsonResponse({ data: { ...link, duplicate: false } }),
      jsonResponse({ data: [link] }),
      jsonResponse({ data: [suggestion] }),
      jsonResponse({
        data: {
          suggestion: { ...suggestion, status: "approved" },
          link,
          duplicate_link: false,
        },
      }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          diagnostics: { reviewed: 1 },
          results: [
            {
              suggestion_id: "suggestion_1",
              action: "approve",
              status: "approved",
            },
          ],
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
      [
        {
          suggestionId: "suggestion_1",
          action: "approve",
          reason: "batch reviewed",
        },
      ],
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
    await client.contextLinks.updateContextLink("link_1", {
      confidence: "high",
      reason: "promoted",
    });
    await client.contextLinks.deleteContextLink("link_1");

    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(transport.requests[2]?.url.searchParams.get("statuses")).toBe(
      "active,deleted",
    );
    expect(transport.bodies).toContainEqual(
      expect.objectContaining({
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
      }),
    );
    expect(() =>
      client.contextLinks.reviewContextLinkSuggestionsBatch([]),
    ).toThrow(ValueError);
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
      jsonResponse(
        {
          data: {
            created: 1,
            existing: 0,
            failed: 0,
            stopped: false,
            results: [{ index: 0, status: "created", suggestion }],
          },
        },
        201,
      ),
      jsonResponse({
        data: {
          suggestion: { ...suggestion, status: "approved" },
          fact: factRecord("fact_1"),
        },
      }),
      jsonResponse({
        data: { suggestion: { ...suggestion, status: "rejected" } },
      }),
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
    const conflict = await client.suggestions.resolveSuggestionConflict(
      "suggestion_1",
      {
        action: "approve",
        reason: "latest feedback wins",
        force: true,
      },
    );
    const duplicate = await client.suggestions.resolveDuplicateMerge(
      "suggestion_1",
      {
        action: "reject",
        reason: "duplicate fact",
      },
    );

    expect(created.data.created).toBe(1);
    expect(conflict.data.fact?.id).toBe("fact_1");
    expect(duplicate.data.suggestion.status).toBe("rejected");
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
          results: [
            {
              suggestion_id: "suggestion_1",
              action: "approve",
              status: "approved",
              suggestion: approved,
            },
          ],
        },
      }),
      jsonResponse({
        data: {
          applied: 2,
          failed: 0,
          stopped: false,
          results: [
            {
              suggestion_id: "suggestion_1",
              action: "approve",
              status: "approved",
              suggestion: approved,
            },
            {
              suggestion_id: "suggestion_2",
              action: "approve",
              status: "approved",
              suggestion: approved,
            },
          ],
        },
      }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          results: [
            {
              suggestion_id: "suggestion_2",
              action: "reject",
              status: "rejected",
              suggestion: rejected,
            },
          ],
        },
      }),
      jsonResponse({
        data: {
          applied: 1,
          failed: 0,
          stopped: false,
          results: [
            {
              suggestion_id: "suggestion_3",
              action: "expire",
              status: "expired",
              suggestion: expired,
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

    const reviewed = await client.suggestions.reviewSuggestionsBatch(
      [
        {
          suggestionId: "suggestion_1",
          action: "approve",
          reason: "typed review",
          force: true,
        },
      ],
      { continueOnError: true },
    );
    const approvedBatch = await client.suggestions.approveSuggestionsBatch(
      [
        "suggestion_1",
        { suggestionId: "suggestion_2", reason: "specific approval" },
      ],
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
    ]);
    expect(transport.bodies).toEqual([
      {
        items: [
          {
            suggestion_id: "suggestion_1",
            action: "approve",
            reason: "typed review",
            force: true,
          },
        ],
        continue_on_error: true,
      },
      {
        items: [
          {
            suggestion_id: "suggestion_1",
            action: "approve",
            reason: "bulk approval",
            force: true,
          },
          {
            suggestion_id: "suggestion_2",
            action: "approve",
            reason: "specific approval",
            force: true,
          },
        ],
        continue_on_error: true,
      },
      {
        items: [
          {
            suggestion_id: "suggestion_2",
            action: "reject",
            reason: "not durable",
            force: false,
          },
        ],
        continue_on_error: false,
      },
      {
        items: [
          {
            suggestion_id: "suggestion_3",
            action: "expire",
            reason: "stale preference",
          },
        ],
        continue_on_error: false,
      },
    ]);
    expect(() => client.suggestions.approveSuggestionsBatch([])).toThrow(
      ValueError,
    );
    expect(() =>
      client.suggestions.reviewSuggestionsBatch([{ action: "approve" }]),
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
          sources: [
            {
              source_type: "fact",
              scanned: 10,
              observed: 3,
              skipped_conflicts: 1,
            },
          ],
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
      jsonResponse(
        {
          data: {
            ...capture,
            duplicate: false,
            created_suggestions: 1,
            suggestion_ids: ["suggestion_1"],
            auto_applied_facts: 0,
            auto_applied_fact_ids: [],
          },
        },
        201,
      ),
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
      jsonResponse({
        data: [{ ...capture, consolidation_status: "consolidated" }],
      }),
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
    await client.captures.purgeCapture("capture_1", {
      reason: "privacy_request",
    });

    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe(
      "active",
    );
    expect(
      transport.requests[1]?.url.searchParams.get("consolidation_status"),
    ).toBe("pending");
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
          documents: [
            { id: "document_1", title: "Digest source", status: "active" },
          ],
          chunks: [{ id: "chunk_1", status: "active" }],
          extraction_jobs: [{ id: "job_1", status: "complete" }],
          threads: [{ id: "thread_1", status: "active" }],
          captures: [captureRecord("capture_1")],
          assets: [{ id: "asset_1", filename: "source.md", status: "stored" }],
          anchors: [
            {
              id: "anchor_1",
              kind: "topic",
              label: "AI agents",
              status: "active",
            },
          ],
          context_links: [contextLinkRecord("link_1")],
          context_link_suggestions: [
            contextLinkSuggestionRecord("suggestion_1"),
          ],
          stats: { facts: 1, captures: 1, context_links: 1 },
          visual_summary: { status: "ready", evidence_count: 3 },
          quick_actions: [{ id: "review_links", priority: 1 }],
          diagnostics: { browser_version: "memory-browser-v1" },
        },
      }),
      jsonResponse({
        data: {
          generated_at: "2026-06-06T00:00:00.000Z",
          scope: {
            space_id: "space_1",
            memory_scope_id: "scope_1",
            thread_id: "thread_1",
          },
          extraction_status_counts: { complete: 1 },
          link_suggestion_status_counts: { pending: 1 },
          extraction_jobs: [{ id: "job_1", status: "complete" }],
          context_link_suggestions: [
            contextLinkSuggestionRecord("suggestion_1"),
          ],
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
    expect(operations.data.context_link_suggestions[0]?.id).toBe(
      "suggestion_1",
    );
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["GET /v1/memory-browser", "GET /v1/operations-console"]);
    expect(transport.requests[0]?.url.searchParams.get("space_slug")).toBe(
      "workspace",
    );
    expect(
      transport.requests[0]?.url.searchParams.get("memory_scope_external_ref"),
    ).toBe("scope");
    expect(transport.requests[0]?.url.searchParams.get("fact_status")).toBe(
      "active",
    );
    expect(transport.requests[0]?.url.searchParams.get("capture_status")).toBe(
      "active",
    );
    expect(transport.requests[0]?.url.searchParams.get("link_status")).toBe(
      "active",
    );
    expect(
      transport.requests[0]?.url.searchParams.get("suggestion_status"),
    ).toBe("pending");
    expect(
      transport.requests[0]?.url.searchParams.has("thread_external_ref"),
    ).toBe(false);
    expect(
      transport.requests[1]?.url.searchParams.get("thread_external_ref"),
    ).toBe("review-thread");
    expect(transport.requests[1]?.url.searchParams.get("limit")).toBe("10");
  });

  it("manages thread memory and reads usage summaries", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: { chunks: 3, facts: 2, jobs: 1, pending_jobs: 1 } }),
      jsonResponse({
        data: { deleted_chunks: 3, deleted_facts: 2, deleted_jobs: 1 },
      }),
      jsonResponse({
        data: { deleted_chunks: 0, deleted_facts: 0, deleted_jobs: 0 },
      }),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(transport.requests[3]?.url.searchParams.get("space_slug")).toBe(
      "workspace",
    );
  });

  it("previews memory scope snapshot imports before mutating state", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: { dry_run: true, created: 0, updated: 0, conflicts: [] },
      }),
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual(["POST /v1/export/memory_scope-snapshot/preview"]);
    expect(transport.bodies[0]).toEqual({
      space_slug: "workspace",
      memory_scope_external_ref: "scope",
      snapshot: { schema_version: "memory_scope_snapshot.v1", facts: [] },
      manifest: { sha256: "snapshot-sha" },
      merge_strategy: "merge_by_external_id",
    });
  });
});
