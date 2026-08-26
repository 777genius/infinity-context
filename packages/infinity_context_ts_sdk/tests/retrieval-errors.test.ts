import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import {
  CONTEXT_RETRIEVAL_ERROR_SPECS,
  InfinityContextClient,
  decodeRetrievalError,
  type RetrievalErrorCode,
} from "../src/index.js";
import { RecordingTransport, jsonResponse } from "./fixtures.js";

const fixtureUrl = new URL("../fixtures/context_retrieval_v2/errors.json", import.meta.url);

describe("Contract C error envelopes", () => {
  it("behaviorally validates every errors.json status/code/retryability case", async () => {
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
    expect(fixture.schema_version).toBe("context-retrieval-v2-errors.v1");
    expect(fixture.cases).toHaveLength(12);
    for (const item of fixture.cases) {
      const body = JSON.stringify({ error: { code: item.code, message: "Expected failure", retryable: item.retryable } });
      const error = decodeRetrievalError(item.http_status, body);
      expect(error).toMatchObject({
        statusCode: item.http_status, code: item.code, retryable: item.retryable,
      });
      expect(CONTEXT_RETRIEVAL_ERROR_SPECS[item.code as RetrievalErrorCode])
        .toEqual([item.http_status, item.retryable]);
    }
    expect(decodeRetrievalError(400, JSON.stringify(fixture.envelope))).toMatchObject({
      code: "memory.context_retrieval_contract_invalid", retryable: false,
    });
  });

  it.each([
    ["root extra", '{"error":{"code":"memory.unauthorized","message":"no","retryable":false},"extra":1}', 401],
    ["error extra", '{"error":{"code":"memory.unauthorized","message":"no","retryable":false,"extra":1}}', 401],
    ["unknown code", '{"error":{"code":"memory.arbitrary","message":"no","retryable":false}}', 401],
    ["status mismatch", '{"error":{"code":"memory.unauthorized","message":"no","retryable":false}}', 403],
    ["retryability mismatch", '{"error":{"code":"memory.unauthorized","message":"no","retryable":true}}', 401],
    ["control", '{"error":{"code":"memory.unauthorized","message":"bad\\u0085","retryable":false}}', 401],
    ["surrogate", '{"error":{"code":"memory.unauthorized","message":"\\ud800","retryable":false}}', 401],
    ["decoded duplicate", '{"error":{"code":"memory.unauthorized","c\\u006fde":"memory.unauthorized","message":"no","retryable":false}}', 401],
  ])("rejects malformed canonical error: %s", (_name, body, status) => {
    expect(() => decodeRetrievalError(status, body)).toThrow();
  });

  it("rejects malformed UTF-8 and bodies over the caller limit", () => {
    expect(() => decodeRetrievalError(400, new Uint8Array([0xff]))).toThrow();
    expect(() => decodeRetrievalError(400,
      '{"error":{"code":"memory.context_retrieval_contract_invalid","message":"no","retryable":false}}', 8))
      .toThrowError(expect.objectContaining({ code: "memory.response_byte_limit_exceeded" }));
  });

  it("uses the strict boundary for projected ingest while legacy ingest keeps generic errors", async () => {
    const canonical = { error: { code: "memory.document_projection_invalid", message: "bad projection", retryable: false } };
    const transport = new RecordingTransport([
      jsonResponse(canonical, 400),
      jsonResponse({ error: { code: "legacy.custom", message: "legacy", retryable: true, extra: 1 } }, 418),
    ]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const base = { spaceId: "space", memoryScopeId: "scope", title: "title", text: "text", sourceExternalId: "source" };
    await expect(client.documents.ingestDocument({ ...base, retrievalProjection: {
      schemaVersion: "document-retrieval-projection.v1", locator: "locator", sourceKey: "source",
      projectionGeneration: "generation", sequenceOrdinal: 1, actorKeys: [], timeInterval: null,
      relativeTimeInterval: null, kind: "record_block", category: "unclassified", tags: [],
    } })).rejects.toMatchObject({ code: "memory.document_projection_invalid", statusCode: 400 });
    await expect(client.documents.ingestDocument(base)).rejects.toMatchObject({ code: "legacy.custom", statusCode: 418 });
  });
});
