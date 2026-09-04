import { describe, expect, it } from "vitest";
import { InfinityContextClient, ValueError } from "../src/index.js";
import { RecordingTransport, jsonResponse } from "./fixtures.js";

const DIGEST = "a".repeat(64);
const OTHER_DIGEST = "b".repeat(64);
const IDEMPOTENCY_KEY = "idempotency-key-123";

function clientWithResponses(count: number) {
  const transport = new RecordingTransport(
    Array.from({ length: count }, () => jsonResponse({ data: { ok: true } })),
  );
  return {
    client: new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    }),
    transport,
  };
}

describe("canonical API parity resources", () => {
  it("transports all seven internal memory-comparison lifecycle endpoints", async () => {
    const { client, transport } = clientWithResponses(7);
    const controls = { headers: { "x-trace-id": "trace_1" } };

    await client.memoryComparisonRuns.register({
      schemaVersion: "memory-comparison-run-registration.v2",
      runIdSha256: DIGEST,
      bindingCommitmentSha256: OTHER_DIGEST,
      infinityTargetIdentitySha256: DIGEST,
      spaceSlug: "memory-comparison-sdk-test",
      cleanupPlan: { schema_version: "memory-comparison-cleanup-plan.v1" },
      cleanupPlanSha256: OTHER_DIGEST,
      idempotencyKey: IDEMPOTENCY_KEY,
      ...controls,
    });
    await client.memoryComparisonRuns.prepareCleanupTargetAuthority({
      schemaVersion: "memory-comparison-cleanup-target-authority-request.v1",
      infinityTargetIdentitySha256: DIGEST,
      ...controls,
    });
    await client.memoryComparisonRuns.sealProjectionManifest(DIGEST, {
      schemaVersion: "memory-comparison-projection-manifest-seal.v1",
      projectionManifestSha256: OTHER_DIGEST,
      projectionManifest: { schema_version: "projection.v1" },
      ...controls,
    });
    await client.memoryComparisonRuns.getCleanup(DIGEST, controls);
    await client.memoryComparisonRuns.cleanup(DIGEST, {
      schemaVersion: "memory-comparison-run-cleanup.v2",
      bindingCommitmentSha256: OTHER_DIGEST,
      infinityTargetIdentitySha256: DIGEST,
      spaceId: "space_1",
      spaceSlug: "memory-comparison-sdk-test",
      cleanupPlanSha256: OTHER_DIGEST,
      idempotencyKey: IDEMPOTENCY_KEY,
      ...controls,
    });
    await client.memoryComparisonRuns.finalizeCleanup(DIGEST, {
      schemaVersion: "memory-comparison-run-cleanup-finalize.v2",
      receiptSha256: DIGEST,
      cleanupPlanSha256: OTHER_DIGEST,
      idempotencyKey: IDEMPOTENCY_KEY,
      ...controls,
    });
    await client.memoryComparisonRuns.finalizeAbort(DIGEST, {
      schemaVersion: "memory-comparison-run-abort-finalize.v2",
      bindingCommitmentSha256: OTHER_DIGEST,
      infinityTargetIdentitySha256: DIGEST,
      spaceId: "space_1",
      spaceSlug: "memory-comparison-sdk-test",
      receiptSha256: DIGEST,
      cleanupPlanSha256: OTHER_DIGEST,
      idempotencyKey: IDEMPOTENCY_KEY,
      ...controls,
    });

    expect(transport.requests.map(({ method, url }) => `${method} ${url.pathname}`)).toEqual([
      "POST /v1/internal/memory-comparison/runs",
      "POST /v1/internal/memory-comparison/runs/cleanup-target-authority",
      `PUT /v1/internal/memory-comparison/runs/${DIGEST}/projection-manifest`,
      `GET /v1/internal/memory-comparison/runs/${DIGEST}/cleanup`,
      `DELETE /v1/internal/memory-comparison/runs/${DIGEST}`,
      `POST /v1/internal/memory-comparison/runs/${DIGEST}/cleanup/finalize`,
      `POST /v1/internal/memory-comparison/runs/${DIGEST}/cleanup/abort/finalize`,
    ]);
    expect(transport.requests.map((request) => request.headers.get("x-trace-id"))).toEqual(
      Array.from({ length: 7 }, () => "trace_1"),
    );
    expect(transport.requests[0]?.headers.get("idempotency-key")).toBe(IDEMPOTENCY_KEY);
    expect(transport.requests[3]?.body).toBeUndefined();
    expect(transport.bodies[0]).toEqual({
      schema_version: "memory-comparison-run-registration.v2",
      run_id_sha256: DIGEST,
      binding_commitment_sha256: OTHER_DIGEST,
      infinity_target_identity_sha256: DIGEST,
      space_slug: "memory-comparison-sdk-test",
      cleanup_plan: { schema_version: "memory-comparison-cleanup-plan.v1" },
      cleanup_plan_sha256: OTHER_DIGEST,
    });
  });

  it("rejects invalid memory-comparison contracts before transport", async () => {
    const { client, transport } = clientWithResponses(1);
    await expect(client.memoryComparisonRuns.getCleanup("not-a-digest")).rejects.toBeInstanceOf(ValueError);
    expect(transport.requests).toHaveLength(0);
  });

  it("transports all five audited fact lifecycle endpoints", async () => {
    const { client, transport } = clientWithResponses(5);
    const common = {
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      evidenceRefs: [{ sourceRef: { source_type: "document", source_id: "doc_1" }, evidenceId: "ev_1" }],
      actorId: "agent_1",
      idempotencyKey: IDEMPOTENCY_KEY,
    } as const;
    await client.factLifecycle.confirm("fact_1", {
      ...common,
      expectedVersion: 1,
      confirmedAt: "2026-08-23T00:00:00Z",
      confirmationBasis: "source_review",
    });
    await client.factLifecycle.endValidity("fact_1", {
      ...common,
      expectedVersion: 2,
      effectiveAt: "2026-08-24T00:00:00Z",
      reasonCode: "expired",
    });
    await client.factLifecycle.supersede("fact_1", {
      ...common,
      successorFactId: "fact_2",
      expectedSuccessorVersion: 1,
      expectedPredecessorVersion: 2,
      effectiveAt: "2026-08-24T00:00:00Z",
      reasonCode: "corrected",
    });
    await client.factLifecycle.dispute("fact_1", {
      ...common,
      challengerFactId: "fact_3",
      expectedChallengerVersion: 1,
      expectedChallengedVersion: 2,
      reasonCode: "conflicting_source",
    });
    await client.factLifecycle.reinstateSupersession({
      ...common,
      supersessionDecisionId: "decision_1",
      expectedRejectedSuccessorVersion: 2,
      expectedOriginalPredecessorVersion: 3,
      reasonCode: "dispute_upheld",
    });

    expect(transport.requests.map(({ method, url }) => `${method} ${url.pathname}`)).toEqual([
      "POST /v1/facts/fact_1/confirm",
      "POST /v1/facts/fact_1/end-validity",
      "POST /v1/facts/fact_1/supersede",
      "POST /v1/facts/fact_1/dispute",
      "POST /v1/facts/reinstate-supersession",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_id: "space_1",
      memory_scope_id: "scope_1",
      evidence_refs: [{
        source_ref: { source_type: "document", source_id: "doc_1" },
        evidence_id: "ev_1",
      }],
      expected_version: 1,
      confirmed_at: "2026-08-23T00:00:00Z",
      confirmation_basis: "source_review",
    });
    expect(transport.requests.every((request) => request.headers.get("idempotency-key") === IDEMPOTENCY_KEY)).toBe(true);
  });

  it("rejects an unbounded fact lifecycle request before transport", async () => {
    const { client, transport } = clientWithResponses(1);
    await expect(client.factLifecycle.confirm("fact_1", {
      evidenceRefs: [],
      expectedVersion: 0,
      confirmedAt: "not-a-date",
      confirmationBasis: "",
      idempotencyKey: IDEMPOTENCY_KEY,
    })).rejects.toBeInstanceOf(ValueError);
    expect(transport.requests).toHaveLength(0);
  });

  it("transports both strict-admin code repository endpoints", async () => {
    const { client, transport } = clientWithResponses(2);
    await client.codeRepositories.resolve({
      spaceId: "space_1",
      evidence: [{ kind: "normalized_remote", digest: DIGEST }],
      provider: "github",
      allowCreate: true,
      safeLabel: "Infinity Context",
      defaultBranch: "main",
      initialCodeScope: { scopeLevel: "branch", branch: "main" },
    });
    await client.codeRepositories.registerScope("repository_1", {
      spaceId: "space_1",
      scopeLevel: "commit",
      commitSha: "a".repeat(40),
    });
    expect(transport.requests.map(({ method, url }) => `${method} ${url.pathname}`)).toEqual([
      "POST /v1/code-repositories/resolve",
      "POST /v1/code-repositories/repository_1/scopes",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_id: "space_1",
      evidence: [{ kind: "normalized_remote", digest: DIGEST }],
      provider: "github",
      allow_create: true,
      initial_code_scope: { scope_level: "branch", branch: "main" },
    });
  });

  it("rejects malformed code repository evidence before transport", async () => {
    const { client, transport } = clientWithResponses(1);
    await expect(client.codeRepositories.resolve({
      spaceId: "space_1",
      evidence: [{ kind: "normalized_remote", digest: "ABC" }],
    })).rejects.toBeInstanceOf(ValueError);
    expect(transport.requests).toHaveLength(0);
  });

  it("transports all three derived-evidence diagnostic endpoints", async () => {
    const { client, transport } = clientWithResponses(3);
    const scope = { spaceId: "space_1", memoryScopeId: "scope_1", threadId: "thread_1" };
    await client.derivedEvidence.observePresence({
      ...scope,
      expectedChunkIds: ["chunk_1"],
      expectedFactIds: ["fact_1"],
    });
    await client.derivedEvidence.deleteQdrant({
      ...scope,
      expectedChunkIds: ["chunk_1"],
      targetCommitmentSha256: DIGEST,
      manifestBindingSha256: OTHER_DIGEST,
    });
    await client.derivedEvidence.deleteGraphiti({
      ...scope,
      expectedFactIds: ["fact_1"],
      identityManifest: {
        episodeIds: ["episode_1"],
        entityIds: ["entity_1"],
        mentionsEdgeIds: ["edge_1"],
        relatesToEdgeIds: [],
      },
      targetCommitmentSha256: DIGEST,
      manifestBindingSha256: OTHER_DIGEST,
    });
    expect(transport.requests.map(({ method, url }) => `${method} ${url.pathname}`)).toEqual([
      "POST /v1/diagnostics/derived-evidence/presence",
      "POST /v1/diagnostics/derived-evidence/qdrant/delete",
      "POST /v1/diagnostics/derived-evidence/graphiti/delete",
    ]);
    expect(transport.bodies[2]).toMatchObject({
      expected_fact_ids: ["fact_1"],
      identity_manifest: {
        episode_ids: ["episode_1"],
        entity_ids: ["entity_1"],
        mentions_edge_ids: ["edge_1"],
        relates_to_edge_ids: [],
      },
      target_commitment_sha256: DIGEST,
      manifest_binding_sha256: OTHER_DIGEST,
    });
  });

  it("requires expected derived identities before transport", async () => {
    const { client, transport } = clientWithResponses(1);
    await expect(client.derivedEvidence.observePresence({
      spaceId: "space_1",
      memoryScopeId: "scope_1",
      expectedChunkIds: [],
      expectedFactIds: [],
    })).rejects.toBeInstanceOf(ValueError);
    expect(transport.requests).toHaveLength(0);
  });

  it("transports the canonical benchmark search endpoint with benchmark bounds", async () => {
    const { client, transport } = clientWithResponses(1);
    await client.context.benchmarkSearch({
      spaceSlug: "memory-comparison-sdk-test",
      memoryScopeExternalRef: "scope_1",
      query: "Which source is current?",
      tokenBudget: 64_000,
      maxFacts: 1_000,
      maxChunks: 2_000,
      maxEvidenceItems: 200,
    });
    expect(transport.requests.map(({ method, url }) => `${method} ${url.pathname}`)).toEqual([
      "POST /v1/context/benchmark-search",
    ]);
    expect(transport.bodies[0]).toMatchObject({
      space_slug: "memory-comparison-sdk-test",
      memory_scope_external_ref: "scope_1",
      query: "Which source is current?",
      token_budget: 64_000,
      max_facts: 1_000,
      max_chunks: 2_000,
      max_evidence_items: 200,
    });
  });

  it("rejects public context bounds on benchmark search", async () => {
    const { client, transport } = clientWithResponses(1);
    await expect(client.context.benchmarkSearch({
      spaceSlug: "memory-comparison-sdk-test",
      query: "Which source is current?",
      maxEvidenceItems: 201,
    })).rejects.toBeInstanceOf(ValueError);
    expect(transport.requests).toHaveLength(0);
  });
});
