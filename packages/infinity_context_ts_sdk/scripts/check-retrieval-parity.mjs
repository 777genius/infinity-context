#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";

const packageRoot = new URL("..", import.meta.url);
const fixtureRoot = new URL("../fixtures/context_retrieval_v2/", import.meta.url);
const expectedFixtureSha256 = Object.freeze({
  "capability.json": "22f34e9e49abf16a8fd6fbe0328bc3f4af08433e93a2ce32d9d2ace148089ddc",
  "cases.json": "cf94c7f8628778712d09ddf2879d5cb04dc79a612b604962a1100aa3009289c9",
  "document_projection.json": "4f6baae9e328535c28f2d22eba4153481a38ce337a9c31cf5c5d1ae1dd9546b0",
  "errors.json": "4f689df00e84aa032c00f43d85ad1737dd7e92a51c0fe73225756d7c5277db41",
  "hostile_responses.json": "b7ff6fb07815d2906e645b963acbaea49a46d3868e3157999839218f53ef7c86",
  "request.json": "c219dd4da0588460205b95f7b0380df335a08a48fb33f9a1c0b9eac2df1a5672",
  "scoring_golden.json": "65b68e3a3076955c0295d193492137779d616b3dfee3669ab8cd26b5d9de6a4a",
  "success.json": "bba0c5b8b53f50c8408150e3c1be3c75bda1c5262ed58615650bf082da17b8c1",
  "transport_outcomes.json": "ede8e57d2dfc44765b370a2b4a53c2c1944cb30c5c4e347775f4eed5b058fb04",
});

const fixtureNames = (await readdir(fixtureRoot)).filter((name) => !name.startsWith(".")).sort();
const expectedNames = Object.keys(expectedFixtureSha256).sort();
if (JSON.stringify(fixtureNames) !== JSON.stringify(expectedNames)) {
  throw new Error(`Retrieval fixture set drifted: ${fixtureNames.join(", ")}`);
}
for (const name of expectedNames) {
  const bytes = await readFile(new URL(name, fixtureRoot));
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expectedFixtureSha256[name]) {
    throw new Error(`Retrieval fixture bytes drifted: ${name} (${actual})`);
  }
}

const contextResource = await readFile(new URL("../src/resources/context.ts", import.meta.url), "utf8");
// Bind each public method to its version and require the route to reach transport.
for (const [method, endpoint, version] of [
  ["retrieve", "/v1/context/retrieve", "false"],
  ["retrieveV3", "/v1/context/retrieve-v3", "true"],
]) {
  const body = contextResource.split(`async ${method}(`)[1]?.split("\n  }")[0] ?? "";
  if (!body.includes(`return this.retrieveVersion(input, capability, required, controls, { method: "POST", path: "${endpoint}" }, ${version})`)) {
    throw new Error(`Retrieval TypeScript SDK endpoint parity failed: ${method}`);
  }
}
if (!/const response = await this\.http\.request<Uint8Array \| string>\(\{\s*\.\.\.route,/u.test(contextResource)) {
  throw new Error("Retrieval TypeScript SDK route transport parity failed");
}
const pythonClient = await readFile(
  new URL("../../infinity_context_sdk/infinity_context_sdk/retrieval.py", import.meta.url),
  "utf8",
);
const pythonV2 = pythonClient.split("    def retrieve_context(")[1]?.split("\n    def ")[0] ?? "";
const pythonV3 = pythonClient.split("    def retrieve_context_v3(")[1]?.split("\n    async def ")[0] ?? "";
if (!pythonV2.includes("self._retrieve_context_async(") || /v3\s*=/u.test(pythonV2) ||
    !pythonV3.includes("self._retrieve_context_async(") || !pythonV3.includes("v3=True,") ||
    !/from infinity_context_contracts\.features\.context_retrieval_v3 import \(\s*ENDPOINT as V3_ENDPOINT,/u.test(pythonClient) ||
    !pythonClient.includes("v3: bool = False,") ||
    !/response, body = await _race_response\(\s*client,\s*payload,\s*maximum_bytes,\s*cancellation_event,\s*endpoint=V3_ENDPOINT if v3 else "\/v1\/context\/retrieve",/u.test(pythonClient) ||
    !pythonClient.includes("else _read_response(client, payload, maximum_bytes, endpoint)") ||
    !/async with client\.stream\("POST", endpoint, content=payload\)/u.test(pythonClient) ||
    !pythonClient.includes("await asyncio.gather(request_task, cancellation_task")) {
  throw new Error("Retrieval Python SDK endpoint parity failed");
}
if (!pythonClient.includes("decode_retrieve_context_response") ||
    !pythonClient.includes("RetrievalCapabilityDto.from_dict")) {
  throw new Error("Retrieval Python SDK strict response/capability parity failed");
}
const packageJson = JSON.parse(await readFile(new URL("package.json", packageRoot), "utf8"));
if (packageJson.exports?.["./fixtures/context_retrieval_v2/*.json"]?.default !==
  "./fixtures/context_retrieval_v2/*.json") {
  throw new Error("Retrieval fixture package export is missing");
}

console.log(`Retrieval parity ok: Python/TypeScript POST V2/V3 routing and ${expectedNames.length} canonical fixtures`);
