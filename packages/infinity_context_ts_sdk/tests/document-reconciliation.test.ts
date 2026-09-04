import { describe, expect, it } from "vitest";
import hostileFixture from "../fixtures/document_reconciliation/hostile_responses.json";
import {
  EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  InfinityContextClient,
  InfinityContextError,
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
    expect(transport.bodies[0]).toEqual({
      contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
      space_id: "space-1",
      memory_scope_id: "scope-1",
      thread_id: "thread-1",
      source_type: "opaque-kind",
      source_external_id: "opaque-id",
      projection_generation: "projection-2",
      profile_generation: "profile-4",
      idempotency_key: "mutation-9",
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

  it("requires exact capability and response object keys", async () => {
    for (const invalidCapability of [
      { ...capability, extra: true },
      { contract_version: capability.contract_version },
      { ...capability, max_deadline_ms: 50.5 },
      { ...capability, max_deadline_ms: "50" },
      { ...capability, max_deadline_ms: Number.NaN },
      { ...capability, max_deadline_ms: Number.POSITIVE_INFINITY },
      { ...capability, max_response_bytes: "65536" },
    ]) {
      const client = new InfinityContextClient({ transport: new RecordingTransport([]) });
      await expect(client.documents.reconcileExactDocument({
        ...input,
        capability: invalidCapability as typeof capability,
      })).rejects.toBeInstanceOf(ValueError);
    }

    for (const response of [
      { ...result(), extra: true },
      { data: { ...result().data, extra: true } },
      { data: { ...result().data, scope: { ...result().data.scope, extra: true } } },
    ]) {
      const client = new InfinityContextClient({
        transport: new RecordingTransport([jsonResponse(response)]),
        retryPolicy: { maxAttempts: 1 },
      });
      await expect(client.documents.reconcileExactDocument(input)).rejects.toBeInstanceOf(ValueError);
    }
  });

  it("rejects hostile response bytes before accepting a decoded shape", async () => {
    const encoded = JSON.stringify(result());
    const hostileBodies: Array<string | Uint8Array> = [
      encoded.replace('"state":"indexed"', '"state":"present","state":"indexed"'),
      encoded.replace('"space_id":"space-1"', '"space_id":"wrong","\\u0073pace_id":"space-1"'),
      new Uint8Array([0x7b, 0x22, 0x64, 0x61, 0x74, 0x61, 0x22, 0x3a, 0xff, 0x7d]),
      `\ufeff${encoded}`,
    ];
    for (const body of hostileBodies) {
      const client = new InfinityContextClient({
        transport: new RecordingTransport([{
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          body,
        }]),
        retryPolicy: { maxAttempts: 1 },
      });
      const error = await client.documents.reconcileExactDocument(input).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(ValueError);
      expect((error as Error).message).not.toContain(input.sourceExternalId);
    }
  });

  it("rejects missing or wrong response media types before reconciliation decoding", async () => {
    const hidden = "opaque-wrong-media-response";
    for (const headers of [new Headers(), new Headers({ "content-type": "text/plain" })]) {
      const client = new InfinityContextClient({
        transport: new RecordingTransport([{ status: 200, headers, body: hidden }]),
        retryPolicy: { maxAttempts: 1 },
      });
      const error = await client.documents.reconcileExactDocument(input).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(InfinityContextError);
      expect(error).toMatchObject({ code: "memory.invalid_response_content_type", retryable: false });
      expect(`${(error as Error).message}\n${JSON.stringify((error as InfinityContextError).details)}`)
        .not.toContain(hidden);
    }
  });

  it("enforces byte limits and propagates timeout/cancellation", async () => {
    const hidden = "must-not-leak-from-oversized-reconciliation-body";
    const tooLarge = `${hidden}${"x".repeat(65_537)}`;
    const malformed = new RecordingTransport([jsonResponse({ data: tooLarge })]);
    const error = await new InfinityContextClient({ transport: malformed, retryPolicy: { maxAttempts: 1 } })
      .documents.reconcileExactDocument(input).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(InfinityContextError);
    expect(error).toMatchObject({ code: "memory.response_byte_limit_exceeded", retryable: false });
    expect(`${(error as Error).message}\n${JSON.stringify((error as InfinityContextError).details)}`)
      .not.toContain(hidden);

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

  it("rejects coercible and non-finite request deadlines before transport", async () => {
    for (const deadlineMs of ["50", true, 50.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      const transport = new RecordingTransport([]);
      const client = new InfinityContextClient({ transport });
      await expect(client.documents.reconcileExactDocument({
        ...input,
        deadlineMs: deadlineMs as unknown as number,
      })).rejects.toBeInstanceOf(ValueError);
      expect(transport.requests).toHaveLength(0);
    }
  });

  it("rejects every shared hostile decoder fixture", async () => {
    for (const hostile of hostileFixture.cases) {
      const response = structuredClone(result()) as Record<string, any>;
      let target = response.data as Record<string, any>;
      for (const segment of hostile.path.slice(0, -1)) target = target[segment] as Record<string, any>;
      const field = hostile.path.at(-1) as string;
      if ("operation" in hostile && hostile.operation === "delete") delete target[field];
      else target[field] = "value" in hostile ? hostile.value : undefined;
      const client = new InfinityContextClient({
        transport: new RecordingTransport([jsonResponse(response)]),
        retryPolicy: { maxAttempts: 1 },
      });
      await expect(client.documents.reconcileExactDocument(input), hostile.id).rejects.toBeInstanceOf(ValueError);
    }
  });
});
