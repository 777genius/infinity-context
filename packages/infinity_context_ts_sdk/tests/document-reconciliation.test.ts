import { describe, expect, it } from "vitest";
import {
  EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  InfinityContextClient,
  ValueError,
} from "../src/index.js";
import {
  HangingTransport,
  RecordingTransport,
  jsonResponse,
  waitForRecordedRequests,
} from "./fixtures.js";

const capability = {
  contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  endpoint: "/v1/documents/reconcile-exact",
  max_deadline_ms: 10_000,
  max_response_bytes: 65_536,
  read_only: true,
} as const;
const input = {
  capability,
  spaceId: "space-1",
  memoryScopeId: "scope-1",
  threadId: "thread-1",
  sourceType: "opaque-kind",
  sourceExternalId: "opaque-id",
  projectionGeneration: "projection-2",
  profileGeneration: "profile-4",
  idempotencyKey: "mutation-9",
  deadlineMs: 500,
} as const;

function result(state = "indexed", visibility = "indexed") {
  return {
    data: {
      contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
      state,
      scope: { space_id: "space-1", memory_scope_id: "scope-1", thread_id: "thread-1" },
      source_type: "opaque-kind",
      source_external_id: "opaque-id",
      document_id: "doc-1",
      canonical_status: "active",
      projection_generation: "projection-2",
      profile_generation: "profile-4",
      visibility,
      idempotency_key_matches: true,
    },
  };
}

describe("exact document reconciliation", () => {
  it("attests capability, validates exact response, and performs only one read-only reconciliation call", async () => {
    const transport = new RecordingTransport([jsonResponse(result())]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const observed = await client.documents.reconcileExactDocument(input);
    expect(observed.state).toBe("indexed");
    expect(observed.visibility).toBe("indexed");
    expect(transport.requests).toHaveLength(1);
    expect(transport.requests[0]?.url.pathname).toBe("/v1/documents/reconcile-exact");
    expect(transport.bodies[0]).toMatchObject({
      contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
      source_external_id: "opaque-id",
      deadline_ms: 500,
    });
  });

  it("rejects malformed, weakened, pending-as-indexed, and unattested responses", async () => {
    for (const response of [
      jsonResponse({ nope: true }),
      jsonResponse({ ...result(), data: { ...result().data, source_external_id: "wrong" } }),
      jsonResponse(result("indexed", "processing")),
    ]) {
      const client = new InfinityContextClient({ transport: new RecordingTransport([response]), retryPolicy: { maxAttempts: 1 } });
      await expect(client.documents.reconcileExactDocument(input)).rejects.toBeInstanceOf(ValueError);
    }
    const client = new InfinityContextClient({ transport: new RecordingTransport([]), retryPolicy: { maxAttempts: 1 } });
    await expect(client.documents.reconcileExactDocument({
      ...input,
      capability: { ...capability, contract_version: "wrong" as typeof capability.contract_version },
    })).rejects.toBeInstanceOf(ValueError);
  });

  it("enforces byte limits and propagates timeout/cancellation", async () => {
    const tooLarge = "x".repeat(65_537);
    const malformed = new RecordingTransport([jsonResponse({ data: tooLarge })]);
    await expect(new InfinityContextClient({ transport: malformed, retryPolicy: { maxAttempts: 1 } })
      .documents.reconcileExactDocument(input)).rejects.toBeInstanceOf(ValueError);

    const hanging = new HangingTransport();
    await expect(new InfinityContextClient({ transport: hanging, retryPolicy: { maxAttempts: 1 } })
      .documents.reconcileExactDocument({ ...input, deadlineMs: 50 })).rejects.toThrow();

    const controller = new AbortController();
    const cancelled = new HangingTransport();
    const pending = new InfinityContextClient({ transport: cancelled, retryPolicy: { maxAttempts: 1 } })
      .documents.reconcileExactDocument({ ...input, signal: controller.signal });
    await waitForRecordedRequests(cancelled, 1);
    controller.abort("consumer cancelled");
    await expect(pending).rejects.toThrow();
  });

  it("redacts opaque values from local validation errors", async () => {
    const secret = "secret-opaque-value";
    const client = new InfinityContextClient({ transport: new RecordingTransport([]) });
    await expect(client.documents.reconcileExactDocument({ ...input, sourceExternalId: `${secret}\u0000` }))
      .rejects.not.toThrow(secret);
  });
});
