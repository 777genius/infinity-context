import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import {
  DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1,
  InfinityContextClient,
  documentRetrievalProjectionV1Payload,
  type DocumentRetrievalProjectionV1Input,
} from "../src/index.js";
import { RecordingTransport, jsonResponse } from "./fixtures.js";

function projection(): DocumentRetrievalProjectionV1Input {
  return {
    schemaVersion: DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1,
    locator: "candidate-007", sourceKey: "source-family-a", projectionGeneration: "generation-a-42",
    sequenceOrdinal: 7, actorKeys: ["actor-a"], timeInterval: null,
    relativeTimeInterval: { startMs: 420000, endMs: 480000 }, kind: "record_block",
    category: "decision", tags: ["approved", "launch"],
  };
}

describe("document Retrieval V2 projection", () => {
  it("maps the exact shared projection fixture", async () => {
    const fixture = JSON.parse(await readFile(
      new URL("../fixtures/context_retrieval_v2/document_projection.json", import.meta.url), "utf8"));
    expect({ retrieval_projection: documentRetrievalProjectionV1Payload(projection()) }).toEqual(fixture);
  });

  it("omits absent and null projection without changing legacy payload bytes", async () => {
    const responses = [jsonResponse({ data: {} }), jsonResponse({ data: {} }), jsonResponse({ data: {} })];
    const transport = new RecordingTransport(responses);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    const legacy = { spaceId: "space", memoryScopeId: "scope", title: "Title", text: "Text", sourceExternalId: "source" };
    await client.documents.ingestDocument(legacy);
    await client.documents.ingestDocument({ ...legacy, retrievalProjection: undefined } as any);
    await client.documents.ingestDocument({ ...legacy, retrievalProjection: null });
    expect(transport.bodies.map((body) => JSON.stringify(body))).toEqual([
      JSON.stringify(transport.bodies[0]), JSON.stringify(transport.bodies[0]), JSON.stringify(transport.bodies[0]),
    ]);
    expect(JSON.stringify(transport.bodies[0])).not.toContain("retrieval_projection");
  });

  it.each([
    ["unknown", (value: any) => { value.unknown = true; }],
    ["unsafe ordinal", (value: any) => { value.sequenceOrdinal = Number.MAX_SAFE_INTEGER; }],
    ["unsorted tags", (value: any) => { value.tags = ["z", "a"]; }],
    ["duplicate decoded scalar", (value: any) => { value.tags = ["é", "\u00e9"]; }],
    ["malformed surrogate", (value: any) => { value.locator = "bad\ud800"; }],
    ["relative order", (value: any) => { value.relativeTimeInterval = { startMs: 2, endMs: 1 }; }],
  ])("rejects invalid projection: %s", (_name, mutate) => {
    const value = projection(); mutate(value);
    expect(() => documentRetrievalProjectionV1Payload(value)).toThrowError(expect.objectContaining({
      code: "memory.document_projection_invalid",
    }));
  });

  it("matches Python strip semantics, including preserving U+FEFF", () => {
    const value = projection();
    (value as any).locator = "\ufeffcandidate-007";
    expect(documentRetrievalProjectionV1Payload(value).locator).toBe("\ufeffcandidate-007");
    for (const whitespace of ["\u00a0", "\u3000"]) {
      const changed = projection();
      (changed as any).locator = `${whitespace}candidate-007`;
      expect(() => documentRetrievalProjectionV1Payload(changed)).toThrow();
    }
  });
});
