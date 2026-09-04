import { readFile } from "node:fs/promises";
import type { RequestExecutor, RequestOptions } from "../src/client.js";
import { ContextClient } from "../src/resources/context.js";
import { describe, expect, it, vi } from "vitest";
import {
  CONTEXT_RETRIEVAL_CONTRACT, InfinityContextClient,
  canonicalRetrievalCapabilityBytes, retrievalCapabilityFingerprint,
  decodeContextRetrievalCapabilitiesResponseBytes, decodeRetrievalCapability,
  decodeRetrievalCapabilityBytes, decodeRetrieveContextResponse,
  decodeRetrieveContextResponseBytes, retrievalRequestPayload, verifyRetrievalCapabilityFingerprint,
  type RetrievalCapability, type RetrieveContextInput,
} from "../src/index.js";
import {
  HangingTransport,
  RecordingTransport,
  jsonResponse,
  waitForRecordedRequests,
} from "./fixtures.js";

const fixtureRoot = new URL("../fixtures/context_retrieval_v2/", import.meta.url);
async function fixture(name: string): Promise<any> {
  return JSON.parse(await readFile(new URL(name, fixtureRoot), "utf8"));
}

function input(): RetrieveContextInput {
  return {
    contractVersion: CONTEXT_RETRIEVAL_CONTRACT,
    capabilityFingerprint: "522cf13b82d20b8cf8f37b6e9fb3f4dc5752e24c9802c35b0f2fc30482083fae",
    profileId: "locator-v2-pairs-relative-22222222",
    scope: { spaceId: "space-a", memoryScopeId: "scope-a", threadId: null },
    queries: [{ queryId: "q1", query: "approved launch decision", weightMicros: 1_000_000 }],
    filters: {
      sourceGenerations: [
        { sourceKey: "source-family-a", projectionGeneration: "generation-a-42" },
        { sourceKey: "source-family-b", projectionGeneration: "generation-b-7" },
      ],
      excludedSourceKeys: [], documentKeys: [], kinds: ["record_block"], category: "decision",
      tagsAny: ["approved"], tagsAll: [], tagsNone: ["draft"], actorKeys: ["actor-a"],
      timeInterval: null, relativeTimeInterval: { startMs: 420000, endMs: 480000 },
    },
    softPreferences: {
      sourcePreferences: [{ key: "source-family-a", weightMicros: 1_000_000 }], actorPreferences: [{ key: "actor-a", weightMicros: 1_000_000 }],
      timeInterval: null, relativeTimeInterval: { startMs: 420000, endMs: 480000 }, timeWeightMicros: 1_000_000,
    },
    bounds: { candidateLimit: 100, resultLimit: 10, neighborRadius: 1, responseByteLimit: 16384, deadlineMs: 900 },
  };
}

describe("Contract C locator Retrieval", () => {
  it("loads the exact cases.json behavioral matrix used by the SDK boundary tests", async () => {
    const matrix = await fixture("cases.json");
    expect(matrix.schema_version).toBe("context-retrieval-v2-cases.v1");
    expect(Object.fromEntries(matrix.cases.map((item: any) =>
      [item.id, [item.subject, item.expect]]))).toEqual({
      wire_exact_accept: ["wire", "accept"],
      unknown_or_text_field_reject: ["wire", "reject"],
      capability_shape_or_fingerprint_drift_reject: ["capability", "reject"],
      required_lane_missing_unhealthy_unqualified_reject: ["capability", "reject"],
      bounds_changed_or_response_oversize_reject: ["retrieval", "unavailable"],
      duplicate_locator_or_identity_reject: ["response", "reject"],
      cross_source_neighbor_reject: ["neighbor", "reject"],
      same_source_cross_document_neighbor_accept: ["neighbor", "accept"],
      projection_absent_not_eligible: ["projection", "not_eligible"],
      projection_partial_unknown_or_caller_version_reject: ["projection", "reject"],
      locator_owner_conflict_reject: ["ownership", "locator_conflict"],
      ordinal_owner_conflict_reject: ["ownership", "ordinal_conflict"],
      same_content_distinct_locator_accept: ["ownership", "accept"],
      exact_projection_retry_idempotent: ["ownership", "idempotent"],
      wrong_scope_generation_lifecycle_or_version_drop: ["hydration", "drop"],
      profile_digest_generation_or_membership_drift_unavailable: ["profile", "unavailable"],
      delete_both_profiles_without_serving: ["lifecycle", "accepted_deferred"],
      legacy_ingest_and_context_search_unchanged: ["legacy", "compatible"],
      local_locator_zero_or_multiple_owner_drop_and_reauthorize: ["hydration", "drop"],
    });
  });

  it("maps the exact source-generation pairs and relative interval fixture", async () => {
    expect(retrievalRequestPayload(input())).toEqual(await fixture("request.json"));
  });

  it("requires query IDs to be unique and strictly UTF-8 byte sorted", () => {
    const sorted = input();
    (sorted.queries as any[]).splice(0, 1,
      { queryId: "\ue000", query: "first" },
      { queryId: "\u{10000}", query: "second" });
    expect(() => retrievalRequestPayload(sorted)).not.toThrow();

    const utf16SortedButUtf8Wrong = input();
    (utf16SortedButUtf8Wrong.queries as any[]).splice(0, 1,
      { queryId: "\u{10000}", query: "first" },
      { queryId: "\ue000", query: "second" });
    expect(() => retrievalRequestPayload(utf16SortedButUtf8Wrong)).toThrowError(
      /UTF-8 sorted and unique/,
    );
  });

  it("validates the full capability and exact fingerprint", async () => {
    const raw = await fixture("capability.json");
    const capability = decodeRetrievalCapability(raw);
    expect(capability.endpoint).toBe("/v1/context/retrieve");
    expect(capability.provider_lanes[0]?.weight_micros).toBe(1_000_000);
    expect(await retrievalCapabilityFingerprint(capability)).toBe(raw.capability_fingerprint);
    await expect(verifyRetrievalCapabilityFingerprint(capability)).resolves.toBeUndefined();
    const changed = { ...raw, provider_lanes: raw.provider_lanes.map((lane: any, index: number) =>
      index === 0 ? { ...lane, healthy: false } : lane) };
    expect(await retrievalCapabilityFingerprint(changed)).not.toBe(raw.capability_fingerprint);
    await expect(verifyRetrievalCapabilityFingerprint(changed)).rejects.toMatchObject({
      code: "memory.context_retrieval_capability_mismatch",
    });
  });

  it("verifies before transport and decodes the shared success fixture", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const success = await fixture("success.json");
    const transport = new RecordingTransport([jsonResponse(success)]);
    const client = new InfinityContextClient({ baseUrl: "http://memory.test", transport, retryPolicy: { maxAttempts: 1 } });
    const result = await client.context.retrieve(input(), capability, {
      capabilityFingerprint: capability.capability_fingerprint, profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    });
    expect(transport.requests).toHaveLength(1);
    expect(transport.bodies[0]).toEqual(await fixture("request.json"));
    expect(result.candidates[0]?.neighbors[0]?.document_key).toBe("doc-008");
  });

  it.each([201, 202])("rejects valid Retrieval payloads returned with non-canonical status %i", async (status) => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const success = await fixture("success.json");
    const transport = new RecordingTransport([jsonResponse(success, status)]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 3 },
    });

    await expect(client.context.retrieve(input(), capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    })).rejects.toMatchObject({
      code: "memory.unexpected_response_status",
      statusCode: status,
      retryable: false,
    });
    expect(transport.requests).toHaveLength(1);
    expect(transport.requests[0]?.expectedStatuses).toEqual([200]);
  });

  it("clamps the transport timeout to the attested request deadline", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = new HangingTransport();
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const bounded = input();
    (bounded.bounds as any).deadlineMs = 20;
    const started = performance.now();
    await expect(client.context.retrieve(bounded, capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    }, { timeoutMs: 5_000 })).rejects.toMatchObject({
      code: "memory.context_retrieval_deadline_exceeded", retryable: true,
    });
    expect(performance.now() - started).toBeLessThan(500);
    expect(transport.requests[0]?.signal?.aborted).toBe(true);
  });

  it("rejects an already-aborted caller before fingerprint or transport work", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const controller = new AbortController();
    controller.abort("cancel before Retrieval entry");
    const digest = vi.spyOn(globalThis.crypto.subtle, "digest");
    try {
      await expect(client.context.retrieve(input(), capability, {
        capabilityFingerprint: capability.capability_fingerprint,
        profileId: capability.profile_id,
        requiredProviderLanes: capability.required_provider_lanes,
      }, { signal: controller.signal })).rejects.toMatchObject({
        code: "memory.context_retrieval_cancelled", retryable: false,
      });
      expect(digest).not.toHaveBeenCalled();
      expect(transport.requests).toHaveLength(0);
    } finally {
      digest.mockRestore();
    }
  });

  it("times out a blocked fingerprint within the entry absolute deadline", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const bounded = input();
    (bounded.bounds as any).deadlineMs = 20;
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const digest = vi.spyOn(globalThis.crypto.subtle, "digest").mockImplementation(
      () => new Promise<ArrayBuffer>(() => undefined),
    );
    const started = performance.now();
    try {
      await expect(client.context.retrieve(bounded, capability, {
        capabilityFingerprint: capability.capability_fingerprint,
        profileId: capability.profile_id,
        requiredProviderLanes: capability.required_provider_lanes,
      })).rejects.toMatchObject({
        code: "memory.context_retrieval_deadline_exceeded", retryable: true,
      });
      expect(performance.now() - started).toBeLessThan(500);
      expect(transport.requests).toHaveLength(0);
    } finally {
      digest.mockRestore();
    }
  });

  it("observes caller cancellation while fingerprinting", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const controller = new AbortController();
    const digest = vi.spyOn(globalThis.crypto.subtle, "digest").mockImplementation(
      () => new Promise<ArrayBuffer>(() => undefined),
    );
    try {
      const pending = client.context.retrieve(input(), capability, {
        capabilityFingerprint: capability.capability_fingerprint,
        profileId: capability.profile_id,
        requiredProviderLanes: capability.required_provider_lanes,
      }, { signal: controller.signal });
      setTimeout(() => controller.abort("cancel fingerprint"), 10);
      await expect(pending).rejects.toMatchObject({
        code: "memory.context_retrieval_cancelled", retryable: false,
      });
      expect(transport.requests).toHaveLength(0);
    } finally {
      digest.mockRestore();
    }
  });

  it("does not enter transport when synchronous payload work exhausts the deadline", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const bounded = input();
    (bounded.bounds as any).deadlineMs = 5;
    const queries = bounded.queries;
    Object.defineProperty(bounded, "queries", {
      enumerable: true,
      get: () => {
        const until = performance.now() + 20;
        while (performance.now() < until) { /* hostile synchronous preflight */ }
        return queries;
      },
    });
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });

    await expect(client.context.retrieve(bounded, capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    })).rejects.toMatchObject({
      code: "memory.context_retrieval_deadline_exceeded", retryable: true,
    });
    expect(transport.requests).toHaveLength(0);
  });

  it("passes transport only the positive budget remaining after preflight work", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const bounded = input();
    const queries = bounded.queries;
    Object.defineProperty(bounded, "queries", {
      enumerable: true,
      get: () => {
        const until = performance.now() + 15;
        while (performance.now() < until) { /* hostile synchronous preflight */ }
        return queries;
      },
    });
    const requests: RequestOptions[] = [];
    const executor: RequestExecutor = {
      request: async <T>(options: RequestOptions): Promise<T> => {
        requests.push(options);
        throw new Error("stop after observing remaining budget");
      },
    };
    await expect(new ContextClient(executor).retrieve(bounded, capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    })).rejects.toMatchObject({ code: "memory.context_retrieval_unavailable" });
    expect(requests[0]?.timeoutMs).toBeGreaterThan(0);
    expect(requests[0]?.timeoutMs).toBeLessThan(900);
  });

  it("interrupts a blocked read with the canonical cancellation code", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = new HangingTransport();
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 3 } });
    const controller = new AbortController();
    const pending = client.context.retrieve(input(), capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    }, { signal: controller.signal });
    await waitForRecordedRequests(transport, 1);
    controller.abort("cancel blocked Retrieval read");
    await expect(pending).rejects.toMatchObject({
      code: "memory.context_retrieval_cancelled", retryable: false,
    });
    expect(transport.requests).toHaveLength(1);
  });

  it("maps provider-independent transport failure to canonical unavailable", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = { send: async () => { throw new Error("socket details must not leak"); } };
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    await expect(client.context.retrieve(input(), capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    })).rejects.toMatchObject({
      code: "memory.context_retrieval_unavailable", retryable: true,
    });
  });

  it("uses the exact Contract C error boundary for Retrieval HTTP failures", async () => {
    const capability = await fixture("capability.json") as RetrievalCapability;
    const transport = new RecordingTransport([jsonResponse({
      error: { code: "memory.unauthorized", message: "Denied", retryable: false },
    }, 401)]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 3 } });
    await expect(client.context.retrieve(input(), capability, {
      capabilityFingerprint: capability.capability_fingerprint,
      profileId: capability.profile_id,
      requiredProviderLanes: capability.required_provider_lanes,
    })).rejects.toMatchObject({ statusCode: 401, code: "memory.unauthorized", retryable: false });
    expect(transport.requests).toHaveLength(1);
  });

  it("accepts the shared response through the public decoder", async () => {
    const response = await fixture("success.json");
    const capability = await fixture("capability.json");
    expect(() => decodeRetrieveContextResponse(response, input(), capability,
      new TextEncoder().encode(JSON.stringify(response)).byteLength)).not.toThrow();
  });

  it("enforces matched weight within requested weight for every preference dimension", async () => {
    const response = await fixture("success.json");
    const capability = await fixture("capability.json");
    response.candidates[0].source_requested_weight_micros = 0;
    response.candidates[0].actor_requested_weight_micros = 2_000_000;
    expect(() => decodeRetrieveContextResponse(
      response, input(), capability, new TextEncoder().encode(JSON.stringify(response)).byteLength,
    )).toThrowError(/preference dimension evidence is out of bounds/);
  });

  it("accepts max-safe canonical versions and rejects wider or non-integer versions", async () => {
    const capability = await fixture("capability.json");
    const response = await fixture("success.json");
    response.candidates[0].canonical_version = Number.MAX_SAFE_INTEGER;
    response.candidates[0].neighbors[0].canonical_version = Number.MAX_SAFE_INTEGER;
    expect(() => decodeRetrieveContextResponse(
      response, input(), capability, new TextEncoder().encode(JSON.stringify(response)).byteLength,
    )).not.toThrow();
    for (const version of [Number.MAX_SAFE_INTEGER + 1, 1.5, true]) {
      const invalid = structuredClone(response);
      invalid.candidates[0].canonical_version = version;
      expect(() => decodeRetrieveContextResponse(
        invalid, input(), capability, new TextEncoder().encode(JSON.stringify(invalid)).byteLength,
      )).toThrow();
    }
  });

  it("keeps locator-only response parsing strict at every nested object", async () => {
    const response = await fixture("success.json");
    const capability = await fixture("capability.json");
    response.candidates[0].neighbors[0].text = "forbidden payload";
    expect(() => decodeRetrieveContextResponse(
      response, input(), capability, new TextEncoder().encode(JSON.stringify(response)).byteLength,
    )).toThrowError(/\.text is unsupported/);
  });

  it.each([
    ["empty pairs", (value: any) => { value.filters.sourceGenerations = []; }],
    ["duplicate source", (value: any) => { value.filters.sourceGenerations[1].sourceKey = "source-family-a"; }],
    ["pair order", (value: any) => { value.filters.sourceGenerations.reverse(); }],
    ["unsafe relative", (value: any) => { value.filters.relativeTimeInterval.endMs = Number.MAX_SAFE_INTEGER + 1; }],
    ["relative order", (value: any) => { value.filters.relativeTimeInterval = { startMs: 2, endMs: 1 }; }],
    ["hard overlap", (value: any) => { value.filters.timeInterval = { startAt: "2026-01-01T00:00:00Z", endAt: "2026-01-01T00:00:00Z" }; }],
    ["soft overlap", (value: any) => { value.softPreferences.timeInterval = { startAt: "2026-01-01T00:00:00Z", endAt: "2026-01-01T00:00:00Z" }; }],
    ["malformed surrogate", (value: any) => { value.filters.sourceGenerations[0].sourceKey = "bad\ud800"; }],
  ])("rejects invalid public request: %s", (_name, mutate) => {
    const value = input(); mutate(value);
    expect(() => retrievalRequestPayload(value)).toThrowError(expect.objectContaining({ code: "memory.context_retrieval_contract_invalid" }));
  });

  it("uses unsigned UTF-8 order and preserves NFC/NFD", () => {
    const value = input();
    (value.filters.sourceGenerations as any[]).splice(0, 2,
      { sourceKey: "é", projectionGeneration: "g1" }, { sourceKey: "\ue000", projectionGeneration: "g2" });
    expect(() => retrievalRequestPayload(value)).not.toThrow();
    expect(Array.from(canonicalRetrievalCapabilityBytes({ "é": 1 })))
      .not.toEqual(Array.from(canonicalRetrievalCapabilityBytes({ "e\u0301": 1 })));
    expect(() => canonicalRetrievalCapabilityBytes({ bad: "\udc00" })).toThrow();
  });

  it("rejects capability floats and invalid integer weight micros", async () => {
    const capability = await fixture("capability.json");
    expect(() => canonicalRetrievalCapabilityBytes({ ...capability, extra: 0.5 })).toThrow();
    for (const invalid of [99_999, 10_000_001, 1.5, Number.NaN]) {
      const changed = structuredClone(capability); changed.provider_lanes[0].weight_micros = invalid;
      expect(() => decodeRetrievalCapability(changed)).toThrow();
    }
    for (const field of ["healthy", "profile_qualified"] as const) {
      const changed = structuredClone(capability); changed.provider_lanes[0][field] = false;
      expect(() => decodeRetrievalCapability(changed)).toThrow();
    }
  });

  it("rejects malformed and duplicate-after-decoding JSON keys", () => {
    expect(() => decodeRetrievalCapabilityBytes('{"profile_id":"x","profile\\u005fid":"y"}'))
      .toThrowError(/duplicate key after decoding/);
    expect(() => decodeRetrievalCapabilityBytes('{"profile_id":"\\ud800"}')).toThrow();
  });

  it("rejects an UTF-8 BOM instead of silently stripping it", () => {
    const payload = new TextEncoder().encode("{}");
    const withBom = new Uint8Array(payload.byteLength + 3);
    withBom.set([0xef, 0xbb, 0xbf]);
    withBom.set(payload, 3);
    expect(() => decodeRetrievalCapabilityBytes(withBom)).toThrowError(
      expect.objectContaining({ code: "memory.context_retrieval_contract_invalid" }),
    );
  });

  it.each([
    ["capability bound decimal", (raw: string) => raw.replace('"candidate_limit": [1, 1000]', '"candidate_limit": [1, 1000.0]')],
    ["capability lane exponent", (raw: string) => raw.replace('"weight_micros": 1000000', '"weight_micros": 1e6')],
  ])("rejects non-integer lexical syntax in %s", async (_name, mutate) => {
    const raw = await readFile(new URL("capability.json", fixtureRoot), "utf8");
    expect(() => decodeRetrievalCapabilityBytes(mutate(raw))).toThrowError(/integer JSON syntax/);
  });

  it("preserves integer lexical evidence through the full capabilities response", async () => {
    const capability = await readFile(new URL("capability.json", fixtureRoot), "utf8");
    const raw = `{"context":{"retrieval":${capability.replace('"weight_micros": 1000000', '"weight_micros": 1000000.0')}}}`;
    expect(() => decodeContextRetrievalCapabilitiesResponseBytes(raw)).toThrowError(/integer JSON syntax/);
  });

  it.each([
    ["applied bound", (raw: string) => raw.replace('"deadline_ms": 900', '"deadline_ms": 900.0')],
    ["candidate version", (raw: string) => raw.replace('"canonical_version": 1,\n      "lifecycle_status"', '"canonical_version": 1e0,\n      "lifecycle_status"')],
    ["contribution rank", (raw: string) => raw.replace('"provider_rank": 1,\n          "provider_weight_micros"', '"provider_rank": 1.0,\n          "provider_weight_micros"')],
    ["neighbor distance", (raw: string) => raw.replace('"distance": 1\n        }', '"distance": 1e0\n        }')],
  ])("rejects non-integer response syntax in representative nested %s", async (_name, mutate) => {
    const raw = await readFile(new URL("success.json", fixtureRoot), "utf8");
    const capability = await fixture("capability.json");
    expect(() => decodeRetrieveContextResponseBytes(mutate(raw), retrievalRequestPayload(input()), capability))
      .toThrowError(/integer JSON syntax/);
  });

  it.each(["capability_profile_mismatch", "neighbor_capability_unavailable"])(
    "accepts canonical empty pre-provider unavailable response: %s",
    async (reason) => {
      const response = await fixture("success.json");
      response.status = "unavailable";
      response.candidates = [];
      response.provider_outcomes = [];
      response.degradation_reason_codes = [reason];
      response.applied_bounds.returned_seeds = 0;
      response.applied_bounds.returned_neighbors = 0;
      const capability = await fixture("capability.json");
      const request = input();
      if (reason === "neighbor_capability_unavailable") {
        capability.supports_neighbors = false;
        capability.capability_fingerprint = await retrievalCapabilityFingerprint(capability);
        (request as any).capabilityFingerprint = capability.capability_fingerprint;
        response.capability_fingerprint = capability.capability_fingerprint;
      }
      expect(() => decodeRetrieveContextResponse(
        response, request, capability, new TextEncoder().encode(JSON.stringify(response)).byteLength,
      )).not.toThrow();
    },
  );

  it("still rejects missing provider outcomes after provider execution", async () => {
    const response = await fixture("success.json");
    const capability = await fixture("capability.json");
    response.provider_outcomes = [];
    expect(() => decodeRetrieveContextResponse(
      response, input(), capability,
      new TextEncoder().encode(JSON.stringify(response)).byteLength,
    )).toThrowError(/exactly cover the attested provider lanes/);
  });

  it("decodes valid escaped surrogate pairs as the same scalar", async () => {
    const capability = await fixture("capability.json");
    const raw = JSON.stringify(capability);
    const escaped = raw.replace(capability.profile_id, "\\ud83d\\ude00");
    const direct = raw.replace(capability.profile_id, "😀");
    expect(decodeRetrievalCapabilityBytes(escaped).profile_id)
      .toBe(decodeRetrievalCapabilityBytes(direct).profile_id);
  });

  it("makes zero network calls when Web Crypto is unavailable", async () => {
    const transport = new RecordingTransport([jsonResponse({})]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const capability = await fixture("capability.json");
    vi.stubGlobal("crypto", undefined);
    try {
      await expect(client.context.retrieve(input(), capability, {
        capabilityFingerprint: capability.capability_fingerprint,
        profileId: capability.profile_id,
        requiredProviderLanes: capability.required_provider_lanes,
      })).rejects.toMatchObject({ code: "memory.context_retrieval_capability_mismatch" });
      expect(transport.requests).toHaveLength(0);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
