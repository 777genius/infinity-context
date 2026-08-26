import { describe, expect, it } from "vitest";

import { InfinityContextClient } from "../src/index.js";
import {
  RecordingTransport,
  documentChunkRecord,
  documentRecord,
  jsonResponse,
} from "./fixtures.js";

describe("scoped document listing", () => {
  it("iterates document chunks with opaque cursors", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [documentChunkRecord("chunk_1", 1)], next_cursor: "chunk_cursor_2" }),
      jsonResponse({ data: [documentChunkRecord("chunk_2", 2)], next_cursor: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const chunks = [];
    for await (const chunk of client.documents.iterateDocumentChunks("doc_1", { pageLimit: 1 })) {
      chunks.push(chunk);
    }

    expect(chunks.map((chunk) => chunk.id)).toEqual(["chunk_1", "chunk_2"]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/documents/doc_1/chunks?limit=1",
      "http://memory.test/v1/documents/doc_1/chunks?limit=1&cursor=chunk_cursor_2",
    ]);
  });

  it("preserves an exact opaque cursor while normalizing stable text filters", async () => {
    const document = documentRecord("doc_1");
    const transport = new RecordingTransport([
      jsonResponse({ data: [document], next_cursor: "opaque_cursor_2" }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const page = await client.documents.listScopeDocuments({
      spaceSlug: "  social-monitor:tenant:workspace  ",
      memoryScopeExternalRef: "  topic:ai-agents:meetings  ",
      threadExternalRef: "  meeting:42  ",
      status: "active",
      sourceExternalId: "  meeting:42:turn:7  ",
      limit: 25,
      cursor: "  opaque_cursor_1  ",
    });

    expect(page).toEqual({ data: [document], next_cursor: "opaque_cursor_2" });
    expect(document.source_type).toBe("document");
    expect(document.source_external_id).toBe("doc_1.md");
    expect(transport.requests[0]?.url.toString()).toBe(
      "http://memory.test/v1/documents?" +
        "space_slug=social-monitor%3Atenant%3Aworkspace&" +
        "memory_scope_external_ref=topic%3Aai-agents%3Ameetings&" +
        "thread_external_ref=meeting%3A42&" +
        "status=active&" +
        "source_external_id=meeting%3A42%3Aturn%3A7&" +
        "limit=25&" +
        "cursor=++opaque_cursor_1++",
    );
  });

  it("collects every scoped document page without changing its filters", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: [documentRecord("doc_1"), documentRecord("doc_2")],
        next_cursor: "opaque_cursor_2",
      }),
      jsonResponse({ data: [documentRecord("doc_3")], next_cursor: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const documents = await client.documents.listAllScopeDocuments(
      {
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:meetings",
        status: "active",
        sourceExternalId: "meeting:42",
      },
      { pageLimit: 2 },
    );

    expect(documents.map((document) => document.id)).toEqual(["doc_1", "doc_2", "doc_3"]);
    expect(transport.requests.map((request) => request.url.toString())).toEqual([
      "http://memory.test/v1/documents?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Ameetings&status=active&source_external_id=meeting%3A42&limit=2",
      "http://memory.test/v1/documents?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Ameetings&status=active&source_external_id=meeting%3A42&limit=2&cursor=opaque_cursor_2",
    ]);
  });

  it("iterates scoped documents with default active status and a bounded item count", async () => {
    const transport = new RecordingTransport([
      jsonResponse({
        data: [documentRecord("doc_1"), documentRecord("doc_2")],
        next_cursor: "unused_cursor",
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const documents = [];
    for await (const document of client.documents.iterateScopeDocuments(
      {
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:meetings",
      },
      { pageLimit: 2, maxItems: 1 },
    )) {
      documents.push(document);
    }

    expect(documents.map((document) => document.id)).toEqual(["doc_1"]);
    expect(transport.requests[0]?.url.toString()).toBe(
      "http://memory.test/v1/documents?space_slug=social-monitor%3Atenant%3Aworkspace&memory_scope_external_ref=topic%3Aai-agents%3Ameetings&status=active&limit=2",
    );
  });

  it("rejects an absent or incomplete document scope before transport", () => {
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    expect(() => client.documents.listScopeDocuments({ limit: 1 })).toThrow(
      "listScopeDocuments requires spaceId + memoryScopeId or spaceSlug + memoryScopeExternalRef",
    );
    expect(() =>
      client.documents.listScopeDocuments({
        spaceSlug: "social-monitor:tenant:workspace",
        limit: 1,
      }),
    ).toThrow(
      "listScopeDocuments requires spaceId + memoryScopeId or spaceSlug + memoryScopeExternalRef",
    );
    expect(transport.requests).toHaveLength(0);
  });

  it("rejects invalid scoped-document query bounds and whitespace-only cursors", () => {
    const transport = new RecordingTransport([]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });
    const scope = {
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents:meetings",
    };

    for (const input of [
      { ...scope, status: "deleted" as "active" },
      { ...scope, sourceExternalId: " " },
      { ...scope, cursor: " \t " },
      { ...scope, sourceExternalId: "x".repeat(241) },
      { ...scope, cursor: "x".repeat(1001) },
      { ...scope, limit: 0 },
      { ...scope, limit: 501 },
      { ...scope, limit: 1.5 },
      { ...scope, spaceSlug: "x".repeat(161) },
      { ...scope, memoryScopeExternalRef: "x".repeat(201) },
    ]) {
      expect(() => client.documents.listScopeDocuments(input)).toThrow();
    }
    expect(transport.requests).toHaveLength(0);
  });

  it("stops unique-cursor pagination at the configured page bound", async () => {
    const transport = new RecordingTransport(
      Array.from({ length: 3 }, (_, index) =>
        jsonResponse({
          data: [documentRecord(`doc_${index + 1}`)],
          next_cursor: `unique_cursor_${index + 1}`,
        }),
      ),
    );
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.documents.listAllScopeDocuments(
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "topic:ai-agents:meetings",
        },
        { maxPages: 3 },
      ),
    ).rejects.toThrow("Pagination exceeded maxPages (3)");
    expect(transport.requests).toHaveLength(3);
  });

  it("applies the default page bound to an endless stream of unique cursors", async () => {
    const transport = new RecordingTransport(
      Array.from({ length: 100 }, (_, index) =>
        jsonResponse({
          data: [documentRecord(`doc_${index + 1}`)],
          next_cursor: `unique_default_cursor_${index + 1}`,
        }),
      ),
    );
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.documents.listAllScopeDocuments({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:meetings",
      }),
    ).rejects.toThrow("Pagination exceeded maxPages (100)");
    expect(transport.requests).toHaveLength(100);
  });

  it("rejects malformed scoped-document pagination envelopes", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: { id: "not-an-array" }, next_cursor: 42 }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.documents.listAllScopeDocuments({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:meetings",
      }),
    ).rejects.toThrow("Paginated response data must be an array");
    expect(transport.requests).toHaveLength(1);
  });

  it("rejects a non-string scoped-document next cursor", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [documentRecord("doc_1")], next_cursor: 42 }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.documents.listAllScopeDocuments({
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRef: "topic:ai-agents:meetings",
      }),
    ).rejects.toThrow("Paginated response next_cursor must be a string or null");
    expect(transport.requests).toHaveLength(1);
  });

  it("rejects a scoped-document cursor cycle instead of looping forever", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ data: [documentRecord("doc_1")], next_cursor: "repeated_cursor" }),
      jsonResponse({ data: [documentRecord("doc_2")], next_cursor: "repeated_cursor" }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(
      client.documents.listAllScopeDocuments(
        {
          spaceSlug: "social-monitor:tenant:workspace",
          memoryScopeExternalRef: "topic:ai-agents:meetings",
        },
        { pageLimit: 1 },
      ),
    ).rejects.toThrow("Paginated response cursor did not advance");
    expect(transport.requests).toHaveLength(2);
  });
});
