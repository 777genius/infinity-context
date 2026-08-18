import { describe, expect, it } from "vitest";
import { InfinityContextClient } from "../src/index.js";
import { RecordingTransport, jsonResponse } from "./fixtures.js";

describe("capabilities serving attestation", () => {
  it("exposes the additive runtime and embedding profile identity", async () => {
    const serviceRevision = "897efd211151e9a81a7466fdd6be5cb067ddb8eb";
    const profileDigest = `sha256:${"a".repeat(64)}` as const;
    const transport = new RecordingTransport([
      jsonResponse({
        api_version: "v1",
        service_revision: serviceRevision,
        embedding_profile_id: "openai-multilingual-minilm-384d-hybrid-sparse.v1",
        embedding_profile_digest_sha256: profileDigest,
      }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const capabilities = await client.system.capabilities();

    expect(capabilities.service_revision).toBe(serviceRevision);
    expect(capabilities.embedding_profile_id).toBe(
      "openai-multilingual-minilm-384d-hybrid-sparse.v1",
    );
    expect(capabilities.embedding_profile_digest_sha256).toBe(profileDigest);
    expect(transport.requests[0]?.url.toString()).toBe(
      "http://memory.test/v1/capabilities",
    );
  });


  it("accepts legacy omitted fields and explicit unattested nulls", async () => {
    const transport = new RecordingTransport([
      jsonResponse({ api_version: "v1" }),
      jsonResponse({ service_revision: null, embedding_profile_id: null, embedding_profile_digest_sha256: null }),
    ]);
    const client = new InfinityContextClient({
      baseUrl: "http://memory.test",
      transport,
      retryPolicy: { maxAttempts: 1 },
    });

    const legacy = await client.system.capabilities();
    const unattested = await client.system.capabilities();

    expect(legacy.service_revision).toBeUndefined();
    expect(legacy.embedding_profile_id).toBeUndefined();
    expect(legacy.embedding_profile_digest_sha256).toBeUndefined();
    expect(unattested.service_revision).toBeNull();
    expect(unattested.embedding_profile_id).toBeNull();
    expect(unattested.embedding_profile_digest_sha256).toBeNull();
  });
});
