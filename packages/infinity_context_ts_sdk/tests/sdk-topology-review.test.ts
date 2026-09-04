import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  MemoryScope,
  ReadScope,
  ValueError,
  assertMemorySnapshotTransferPolicy,
  createMemoryReviewPlan,
  evaluateMemorySnapshotTransferPolicy,
  summarizeMemorySnapshotTransfer,
} from "../src/index.js";
import {
  RecordingTransport,
  assetExtractionJobRecord,
  expectCompletedSignalsDetached,
  extractionArtifactRecord,
  jsonResponse,
  membershipRecord,
  scopeRecord,
  spaceRecord,
  userRecord,
} from "./fixtures.js";

describe("InfinityContextClient", () => {
  it("transfers memory snapshots through safe preview and confirmed modes", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({
        data: { schema_version: "memory_scope_snapshot.v1", facts: [] },
        manifest: { sha256: "sha_1" },
      }),
      jsonResponse({ data: { dry_run: true, conflicts: [] } }),
      jsonResponse({
        data: {
          schema_version: "memory_scope_snapshot.v1",
          facts: [{ id: "fact_1" }],
        },
      }),
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
    expect(preview.preview).toMatchObject({
      data: { dry_run: true, conflicts: [] },
    });
    expect(preview.manifest).toMatchObject({ sha256: "sha_1" });
    const previewReport = summarizeMemorySnapshotTransfer(preview);
    expect(previewReport).toMatchObject({
      ok: true,
      status: "review_required",
      mode: "preview",
      mutated: false,
      redacted: true,
      mergeStrategy: "fail_on_conflict",
      sameScope: false,
      hasManifest: true,
      hasPreview: true,
      hasImportResult: false,
      counts: { facts: 0 },
    });
    expect(
      evaluateMemorySnapshotTransferPolicy(previewReport, {
        allowedModes: ["preview"],
        forbidMutation: true,
        requireRedacted: true,
        forbidSameScope: true,
        requireManifest: true,
        requirePreview: true,
        requiredMergeStrategy: "fail_on_conflict",
      }),
    ).toMatchObject({
      ok: true,
      errors: [],
    });

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
    expect(imported.importResult).toMatchObject({
      data: { imported: true, dry_run: false },
    });
    const importReport = summarizeMemorySnapshotTransfer(imported);
    expect(importReport).toMatchObject({
      ok: true,
      status: "mutated",
      mode: "confirmed_import",
      mutated: true,
      redacted: false,
      hasImportResult: true,
      counts: { facts: 1 },
    });
    expect(
      evaluateMemorySnapshotTransferPolicy(imported, {
        allowedModes: ["confirmed_import"],
        requireMutation: true,
        requireImportResult: true,
        minFacts: 1,
        requiredMergeStrategy: "replace",
      }),
    ).toMatchObject({
      ok: true,
      errors: [],
    });
    expect(() =>
      assertMemorySnapshotTransferPolicy(importReport, {
        forbidMutation: true,
        requireRedacted: true,
      }),
    ).toThrow(
      "Memory snapshot transfer policy failed: snapshot transfer mutated target memory",
    );
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/preview",
      "GET /v1/export/memory_scope-snapshot",
      "POST /v1/export/memory_scope-snapshot/import",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 4 }, () => "trace_snapshot_transfer"));
    expect(transport.requests[0]?.url.searchParams.get("redacted")).toBe(
      "true",
    );
    expect(transport.requests[2]?.url.searchParams.get("redacted")).toBe(
      "false",
    );
    expect(transport.bodies[1]).toMatchObject({
      space_slug: "workspace-target",
      memory_scope_external_ref: "topic:ai-agents-copy",
      snapshot: {
        schema_version: "memory_scope_snapshot.v1",
        facts: [{ id: "fact_1" }],
      },
      dry_run: false,
      confirmed: true,
      merge_strategy: "replace",
      source_name: "sdk-test-transfer",
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel snapshot transfer",
    );
  });

  it("ensures memory topology through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse({ data: spaceRecord("space_1", "workspace") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse(
        { data: scopeRecord("scope_workspace", "workspace-global") },
        201,
      ),
      jsonResponse({ data: [] }),
      jsonResponse(
        { data: scopeRecord("scope_topic", "topic:ai-agents") },
        201,
      ),
      jsonResponse({ data: [] }),
      jsonResponse({ data: userRecord("user_1", "user:owner") }, 201),
      jsonResponse({ data: [] }),
      jsonResponse(
        {
          data: membershipRecord("membership_1", "space_1", "user_1", "owner"),
        },
        201,
      ),
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
      users: [
        {
          externalRef: "user:owner",
          displayName: "Owner",
          email: "owner@example.com",
          metadata: { source: "sdk-test" },
          role: "owner",
        },
      ],
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
    expect(result.memoryScopes.map((scope) => scope.external_ref)).toEqual([
      "workspace-global",
      "topic:ai-agents",
    ]);
    expect(result.users.map((user) => user.external_ref)).toEqual([
      "user:owner",
    ]);
    expect(result.memberships.map((membership) => membership.role)).toEqual([
      "owner",
    ]);
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
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
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(Array.from({ length: 10 }, () => "trace_topology"));
    expect(transport.requests[0]?.url.searchParams.get("limit")).toBe("10");
    expect(transport.requests[2]?.url.searchParams.get("space_id")).toBe(
      "space_1",
    );
    expect(transport.requests[6]?.url.searchParams.get("status")).toBe(
      "active",
    );
    expect(transport.bodies[0]).toEqual({
      slug: "workspace",
      name: "Workspace",
    });
    expect(transport.bodies[3]).toEqual({
      external_ref: "user:owner",
      display_name: "Owner",
      email: "owner@example.com",
      metadata: { source: "sdk-test" },
    });
    expect(transport.bodies[4]).toEqual({ user_id: "user_1", role: "owner" });
    expect(
      transport.requests.every((request) => request.signal !== undefined),
    ).toBe(true);
  });

  it("recovers memory topology creation conflicts idempotently", async () => {
    const existingSpace = spaceRecord("space_1", "workspace");
    const existingScope = scopeRecord("scope_workspace", "workspace-global");
    const existingUser = userRecord("user_1", "user:owner");
    const existingMembership = membershipRecord(
      "membership_1",
      "space_1",
      "user_1",
      "viewer",
    );
    const transport = new RecordingTransport([
      jsonResponse({ data: [] }),
      jsonResponse(
        { error: { code: "conflict", message: "space already exists" } },
        409,
      ),
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
      memoryScopes: [
        { externalRef: "workspace-global", name: "Workspace global" },
      ],
      users: [
        { externalRef: "user:owner", displayName: "Owner", role: "owner" },
      ],
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "GET /v1/spaces",
      "POST /v1/spaces",
      "GET /v1/spaces",
      "GET /v1/memory-scopes",
      "GET /v1/users",
      "GET /v1/spaces/space_1/memberships",
    ]);
    expect(
      transport.requests.map((request) =>
        request.url.searchParams.get("limit"),
      ),
    ).toEqual(["7", null, "7", "7", "7", "7"]);
  });

  it("manages asset extraction lifecycle endpoints", async () => {
    const job = assetExtractionJobRecord("job_1");
    const transport = new RecordingTransport([
      jsonResponse({ data: job }, 202),
      jsonResponse({ data: [job] }),
      jsonResponse({ data: [{ ...job, id: "job_2", status: "failed" }] }),
      jsonResponse({
        data: { ...job, artifacts: [extractionArtifactRecord("artifact_1")] },
      }),
      jsonResponse(
        { data: { ...job, status: "queued", attempt_count: 2 } },
        202,
      ),
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
    expect(details.data.artifacts[0]?.download_path).toBe(
      "/v1/extraction-artifacts/artifact_1/download",
    );
    expect(retried.data.attempt_count).toBe(2);
    expect(canceled.data.status).toBe("canceled");
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/assets/asset_1/extractions",
      "GET /v1/assets/asset_1/extractions",
      "GET /v1/asset-extractions",
      "GET /v1/asset-extractions/job_1",
      "POST /v1/asset-extractions/job_1/retry",
      "POST /v1/asset-extractions/job_1/cancel",
    ]);
    expect(transport.requests[0]?.url.searchParams.get("parser_profile")).toBe(
      "markdown-strict",
    );
    expect(transport.requests[1]?.url.searchParams.get("status")).toBe(
      "running",
    );
    expect(transport.requests[1]?.url.searchParams.get("limit")).toBe("20");
    expect(transport.requests[2]?.url.searchParams.get("space_slug")).toBe(
      "workspace",
    );
    expect(
      transport.requests[2]?.url.searchParams.get("memory_scope_external_ref"),
    ).toBe("scope");
    expect(
      transport.requests[2]?.url.searchParams.get("thread_external_ref"),
    ).toBe("review-thread");
    expect(transport.requests[2]?.url.searchParams.get("status")).toBe(
      "failed",
    );
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
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
      "GET /v1/asset-extractions/job_1",
    ]);
    expect(
      transport.requests
        .slice(0, 3)
        .map((request) => request.headers.get("x-trace-id")),
    ).toEqual([
      "trace_extraction_wait",
      "trace_extraction_wait",
      "trace_extraction_wait",
    ]);
    const requestSignals = transport.requests
      .slice(0, 3)
      .map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel extraction wait",
    );
  });

  it("validates mixed canonical and external scopes", () => {
    expect(() =>
      MemoryScope.canonical({
        spaceId: "space_1",
        memoryScopeId: "scope_1",
      }).toPayload(),
    ).not.toThrow();
    expect(() =>
      ReadScope.external({
        spaceSlug: "workspace",
        memoryScopeExternalRef: "user:user_1",
      }).toPayload(),
    ).not.toThrow();
    expect(() => new InfinityContextClient()).not.toThrow();
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
    expect(() => MemoryScope.canonical(mixedInput).toPayload()).toThrow(
      ValueError,
    );
  });

  it("plans memory review batches across context links and suggestions", () => {
    const plan = createMemoryReviewPlan({
      reason: "weekly memory review",
      continueOnError: true,
      headers: { "x-review-id": "review_1" },
      contextLinks: {
        visibleFilter: {
          spaceSlug: "workspace",
          memoryScopeExternalRef: "scope",
          status: "pending",
          limit: 20,
        },
        items: [
          {
            suggestionId: "ctx_suggestion_1",
            targetType: "fact",
            targetId: "fact_1",
            relationType: "supports",
            confidence: "high",
            linkReason: "review selected exact target",
          },
          {
            suggestionId: "ctx_suggestion_2",
            action: "reject",
            reason: "weak semantic match",
          },
        ],
      },
      suggestions: {
        action: "approve",
        force: true,
        items: [
          { suggestionId: "memory_suggestion_1" },
          {
            suggestionId: "memory_suggestion_2",
            action: "expire",
            reason: "stale preference",
            force: false,
          },
        ],
      },
    });

    expect(plan.contextLinks?.items).toEqual([
      {
        suggestionId: "ctx_suggestion_1",
        action: "approve",
        reason: "weekly memory review",
        targetType: "fact",
        targetId: "fact_1",
        relationType: "supports",
        confidence: "high",
        linkReason: "review selected exact target",
      },
      {
        suggestionId: "ctx_suggestion_2",
        action: "reject",
        reason: "weak semantic match",
      },
    ]);
    expect(plan.contextLinks?.options).toMatchObject({
      headers: { "x-review-id": "review_1" },
      continueOnError: true,
      visibleFilter: {
        spaceSlug: "workspace",
        memoryScopeExternalRef: "scope",
        status: "pending",
        limit: 20,
      },
    });
    expect(plan.suggestions?.items).toEqual([
      {
        suggestionId: "memory_suggestion_1",
        action: "approve",
        reason: "weekly memory review",
        force: true,
      },
      {
        suggestionId: "memory_suggestion_2",
        action: "expire",
        reason: "stale preference",
        force: false,
      },
    ]);
    expect(plan.suggestions?.options).toMatchObject({
      headers: { "x-review-id": "review_1" },
      continueOnError: true,
    });
    expect(plan.summary).toEqual({
      total: 4,
      contextLinkReviews: 2,
      suggestionReviews: 2,
      byAction: { approve: 2, reject: 1, expire: 1 },
    });
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.contextLinks?.items)).toBe(true);
    expect(Object.isFrozen(plan.suggestions?.items)).toBe(true);
  });

  it("applies memory review plans through the workflow facade", async () => {
    const controller = new AbortController();
    const transport = new RecordingTransport([
      jsonResponse({
        data: {
          applied: 2,
          failed: 0,
          stopped: false,
          diagnostics: { reviewed: 2 },
          results: [
            {
              suggestion_id: "ctx_suggestion_1",
              action: "approve",
              status: "approved",
            },
            {
              suggestion_id: "ctx_suggestion_2",
              action: "reject",
              status: "rejected",
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
              suggestion_id: "memory_suggestion_1",
              action: "approve",
              status: "approved",
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

    const plan = createMemoryReviewPlan({
      reason: "weekly review",
      continueOnError: true,
      signal: controller.signal,
      headers: { "x-trace-id": "trace_review" },
      contextLinks: {
        visibleFilter: {
          spaceSlug: "workspace",
          memoryScopeExternalRef: "scope",
          status: "pending",
        },
        items: [
          {
            suggestionId: "ctx_suggestion_1",
            targetType: "fact",
            targetId: "fact_1",
            relationType: "supports",
          },
          {
            suggestionId: "ctx_suggestion_2",
            action: "reject",
            reason: "weak match",
          },
        ],
      },
      suggestions: {
        action: "approve",
        items: [{ suggestionId: "memory_suggestion_1" }],
      },
    });

    const result = await client.workflows.applyMemoryReviewPlan(plan);

    expect(result.summary).toEqual({
      total: 3,
      contextLinkReviews: 2,
      suggestionReviews: 1,
      byAction: { approve: 2, reject: 1 },
      applied: 3,
      failed: 0,
      stopped: false,
    });
    expect(result.diagnostics).toEqual({
      ok: true,
      contextLinksOk: true,
      suggestionsOk: true,
      warnings: [],
    });
    expect(
      transport.requests.map(
        (request) => `${request.method} ${request.url.pathname}`,
      ),
    ).toEqual([
      "POST /v1/context-link-suggestions/review-batch",
      "POST /v1/suggestions/review-batch",
    ]);
    expect(
      transport.requests.map((request) => request.headers.get("x-trace-id")),
    ).toEqual(["trace_review", "trace_review"]);
    expect(transport.bodies[0]).toMatchObject({
      continue_on_error: true,
      visible_filter: {
        space_slug: "workspace",
        memory_scope_external_ref: "scope",
        status: "pending",
      },
      items: [
        {
          suggestion_id: "ctx_suggestion_1",
          action: "approve",
          reason: "weekly review",
          target_type: "fact",
          target_id: "fact_1",
          relation_type: "supports",
        },
        {
          suggestion_id: "ctx_suggestion_2",
          action: "reject",
          reason: "weak match",
        },
      ],
    });
    expect(transport.bodies[1]).toMatchObject({
      continue_on_error: true,
      items: [
        {
          suggestion_id: "memory_suggestion_1",
          action: "approve",
          reason: "weekly review",
        },
      ],
    });
    const requestSignals = transport.requests.map((request) => request.signal);
    expectCompletedSignalsDetached(
      requestSignals,
      controller,
      "cancel review plan",
    );
  });

  it("validates memory review plans", () => {
    expect(() => createMemoryReviewPlan({})).toThrow(
      "createMemoryReviewPlan requires at least one review item",
    );
    expect(() =>
      createMemoryReviewPlan({
        contextLinks: {
          items: [{ suggestionId: "", action: "approve" }],
        },
      }),
    ).toThrow("context link review item 0 requires suggestionId");
    expect(() =>
      createMemoryReviewPlan({
        suggestions: {
          items: [{ suggestionId: "", action: "reject" }],
        },
      }),
    ).toThrow("suggestion review item 0 requires suggestionId");
  });
});
