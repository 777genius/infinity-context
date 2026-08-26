#!/usr/bin/env node
import { readFile } from "node:fs/promises";

const commandName = "infinity-context-retrieval-runtime-canary";
const cliArgs = process.argv.slice(2);

if (hasCliFlag(cliArgs, "--help", "-h")) {
  printHelp(commandName);
  process.exit(0);
}

if (hasCliFlag(cliArgs, "--version", "-v")) {
  process.stdout.write(`${await packageVersion()}\n`);
  process.exit(0);
}

const baseUrl = (process.env.INFINITY_CONTEXT_URL ?? "http://127.0.0.1:7788").replace(/\/$/, "");
const token = process.env.INFINITY_CONTEXT_TOKEN;
const spaceId = required("RETRIEVAL_CANARY_SPACE_ID");
const memoryScopeId = required("RETRIEVAL_CANARY_MEMORY_SCOPE_ID");
const expectedFingerprint = required("RETRIEVAL_CAPABILITY_FINGERPRINT");
const expectedProfile = required("RETRIEVAL_PROFILE_ID");
const expectedSdkRevision = required("RETRIEVAL_SDK_REVISION");
const expectedServiceRevision = required("RETRIEVAL_SERVICE_REVISION");
const expectedLocator = required("RETRIEVAL_CANARY_EXPECTED_LOCATOR");
const headers = {
  accept: "application/json",
  "content-type": "application/json",
  ...(token ? { authorization: `Bearer ${token}` } : {}),
};
const { assertRetrievalRuntimeCanary } = await import("./retrieval-runtime-canary-policy.mjs");
const sdk = await import("../dist/index.js");

const capabilityResponse = await fetch(`${baseUrl}/v1/capabilities`, { headers });
if (!capabilityResponse.ok) throw new Error(`Capabilities returned HTTP ${capabilityResponse.status}`);
const capabilityEnvelope = await capabilityResponse.json();
const capability = sdk.decodeRetrievalCapability(capabilityEnvelope?.context?.retrieval);
await sdk.verifyRetrievalCapabilityFingerprint(capability);

const fixture = JSON.parse(await readFile(
  new URL("../fixtures/context_retrieval_v2/request.json", import.meta.url),
  "utf8",
));
const request = {
  ...fixture,
  capability_fingerprint: expectedFingerprint,
  profile_id: expectedProfile,
  scope: { space_id: spaceId, memory_scope_id: memoryScopeId, thread_id: null },
  queries: [{ query_id: "runtime-canary", query: process.env.RETRIEVAL_CANARY_QUERY ?? "runtime readiness", weight_micros: 1000000 }],
};
const response = await fetch(`${baseUrl}/v1/context/retrieve`, {
  method: "POST",
  headers,
  body: JSON.stringify(request),
  signal: AbortSignal.timeout(request.bounds.deadline_ms + 1000),
});
const bytes = new Uint8Array(await response.arrayBuffer());
if (!response.ok) throw new Error(`Retrieval returned HTTP ${response.status}`);
const decoded = sdk.decodeRetrieveContextResponseBytes(bytes, request, capability);
assertRetrievalRuntimeCanary({
  capability,
  response: decoded,
  expectedFingerprint,
  expectedProfile,
  expectedSdkRevision,
  expectedServiceRevision,
  expectedLocator,
});
process.stdout.write(`${JSON.stringify({
  schema_version: "infinity-context-retrieval-runtime-canary.v1",
  ok: true,
  capability_fingerprint: capability.capability_fingerprint,
  profile_id: capability.profile_id,
  service_revision: capability.service_revision,
  sdk_revision: capability.sdk_revision,
  status: decoded.status,
  candidate_count: decoded.candidates.length,
  expected_locator: expectedLocator,
})}\n`);

function required(name) {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") throw new Error(`${name} is required`);
  return value;
}

function hasCliFlag(args, ...flags) {
  return args.some((arg) => flags.includes(arg));
}

function printHelp(command) {
  process.stdout.write(`Usage: ${command} [--help] [--version]

Runs the pinned retrieval runtime canary against an Infinity Context service.

Options:
  -h, --help       Show this help without validating configuration or contacting the service.
  -v, --version    Print the package version.
`);
}

async function packageVersion() {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  if (typeof packageJson.version !== "string" || packageJson.version.length === 0) {
    throw new Error("SDK package version is invalid");
  }
  return packageJson.version;
}
