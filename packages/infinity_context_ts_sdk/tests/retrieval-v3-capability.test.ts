import { readFile } from "node:fs/promises";
import { expect, it } from "vitest";
import { InfinityContextClient, retrievalCapabilityFingerprint } from "../src/index.js";
import { HangingTransport, RecordingTransport, jsonResponse } from "./fixtures.js";

async function capability() {
  const value = JSON.parse(await readFile(new URL("../fixtures/context_retrieval_v2/capability.json", import.meta.url), "utf8"));
  value.contract_version = "context-retrieval.v3";
  value.endpoint = "/v1/context/retrieve-v3";
  value.capability_fingerprint = await retrievalCapabilityFingerprint(value);
  return value;
}

it("fetches the exact V3 capability through the public context API", async () => {
  const value = await capability();
  const transport = new RecordingTransport([jsonResponse(value)]);
  const client = new InfinityContextClient({ baseUrl: "http://memory.test", transport });
  expect(await client.context.retrievalV3Capability({ headers: { "x-test": "capability" }, timeoutMs: 1000 })).toEqual(value);
  expect(transport.requests).toHaveLength(1);
  expect(transport.requests[0]?.method).toBe("GET");
  expect(new URL(transport.requests[0]!.url).pathname).toBe("/v1/context/retrieve-v3/capability");
  expect(transport.requests[0]?.body).toBeUndefined();
  expect(transport.requests[0]?.headers.get("x-test")).toBe("capability");
});

it("rejects malformed, duplicate, oversized and mismatched capability payloads", async () => {
  const value = await capability();
  for (const body of [
    JSON.stringify({ ...value, extra: true }),
    JSON.stringify({ ...value, endpoint: "/v1/context/retrieve" }),
    JSON.stringify({ ...value, capability_fingerprint: "0".repeat(64) }),
    '{"contract_version":"context-retrieval.v3",' + JSON.stringify(value).slice(1),
    JSON.stringify(value).replace(/("weight_micros":)([0-9]+)/, "$1$2.0"),
    " ".repeat(65_537),
  ]) {
    const transport = new RecordingTransport([{ ...jsonResponse({}), body }]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    await expect(client.context.retrievalV3Capability()).rejects.toBeDefined();
  }
});

it("preserves canonical HTTP errors and rejects invalid error envelopes", async () => {
  for (const body of [
    { error: { code: "memory.unauthorized", message: "Unauthorized", retryable: false } },
    { error: "invalid" },
  ]) {
    const transport = new RecordingTransport([jsonResponse(body, 401)]);
    const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
    await expect(client.context.retrievalV3Capability()).rejects.toMatchObject({
      code: typeof body.error === "string" ? "memory.context_retrieval_contract_invalid" : "memory.unauthorized",
    });
  }
});

it("bounds time and honours cancellation", async () => {
  const transport = new HangingTransport();
  const client = new InfinityContextClient({ transport, retryPolicy: { maxAttempts: 1 } });
  await expect(client.context.retrievalV3Capability({ timeoutMs: 20 })).rejects.toMatchObject({ code: "memory.context_retrieval_deadline_exceeded" });
  const controller = new AbortController();
  controller.abort();
  await expect(client.context.retrievalV3Capability({ signal: controller.signal })).rejects.toMatchObject({ code: "memory.context_retrieval_cancelled" });
  expect(transport.requests).toHaveLength(1);
});
