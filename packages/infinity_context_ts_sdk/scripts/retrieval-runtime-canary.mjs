#!/usr/bin/env node
import { readFile, realpath } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const commandName = "infinity-context-retrieval-runtime-canary";
const capabilityResponseByteLimit = 1_048_576;

export async function runRetrievalRuntimeCanaryCli({
  args = process.argv.slice(2),
  env = process.env,
  stdout = process.stdout,
  sdk: suppliedSdk,
  requestFixture,
  exitCodeTarget,
} = {}) {
  if (hasCliFlag(args, "--help", "-h")) {
    printHelp(commandName, stdout);
    return recordExitCode({ exitCode: 0 }, exitCodeTarget);
  }

  if (hasCliFlag(args, "--version", "-v")) {
    stdout.write(`${await packageVersion()}\n`);
    return recordExitCode({ exitCode: 0 }, exitCodeTarget);
  }

  try {
    const result = await runRetrievalRuntimeCanary({ env, sdk: suppliedSdk, requestFixture });
    stdout.write(`${JSON.stringify(result.report)}\n`);
    return recordExitCode({ ...result, exitCode: 0 }, exitCodeTarget);
  } catch (error) {
    const report = failureReport(error);
    stdout.write(`${JSON.stringify(report)}\n`);
    return recordExitCode({ exitCode: 1, report, error }, exitCodeTarget);
  }
}

export async function runRetrievalRuntimeCanary({
  env = process.env,
  sdk: suppliedSdk,
  requestFixture,
} = {}) {
  const baseUrl = (env.INFINITY_CONTEXT_URL ?? "http://127.0.0.1:7788").replace(/\/$/, "");
  const token = env.INFINITY_CONTEXT_TOKEN;
  const spaceId = required(env, "RETRIEVAL_CANARY_SPACE_ID");
  const memoryScopeId = required(env, "RETRIEVAL_CANARY_MEMORY_SCOPE_ID");
  const expectedFingerprint = required(env, "RETRIEVAL_CAPABILITY_FINGERPRINT");
  const expectedProfile = required(env, "RETRIEVAL_PROFILE_ID");
  const expectedSdkRevision = required(env, "RETRIEVAL_SDK_REVISION");
  const expectedServiceRevision = required(env, "RETRIEVAL_SERVICE_REVISION");
  const expectedLocator = required(env, "RETRIEVAL_CANARY_EXPECTED_LOCATOR");
  const headers = {
    accept: "application/json",
    "content-type": "application/json",
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  };
  const { assertRetrievalRuntimeCanary } = await import("./retrieval-runtime-canary-policy.mjs");
  const sdk = suppliedSdk ?? await import("../dist/index.js");
  const transport = new sdk.FetchTransport();

  const capabilityResponse = await transport.send({
    method: "GET",
    url: new URL(`${baseUrl}/v1/capabilities`),
    headers: new Headers(headers),
    signal: AbortSignal.timeout(10_000),
    responseType: "bytes",
    maxResponseBytes: capabilityResponseByteLimit,
    maxErrorResponseBytes: capabilityResponseByteLimit,
  });
  if (capabilityResponse.status >= 400) {
    throw new Error(`Capabilities returned HTTP ${capabilityResponse.status}`);
  }
  const capabilityEnvelope = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(capabilityResponse.body),
  );
  const capability = sdk.decodeRetrievalCapability(capabilityEnvelope?.context?.retrieval);
  await sdk.verifyRetrievalCapabilityFingerprint(capability);

  const fixture = requestFixture ?? JSON.parse(await readFile(
    new URL("../fixtures/context_retrieval_v2/request.json", import.meta.url),
    "utf8",
  ));
  const request = {
    ...fixture,
    capability_fingerprint: expectedFingerprint,
    profile_id: expectedProfile,
    scope: { space_id: spaceId, memory_scope_id: memoryScopeId, thread_id: null },
    queries: [{
      query_id: "runtime-canary",
      query: env.RETRIEVAL_CANARY_QUERY ?? "runtime readiness",
      weight_micros: 1000000,
    }],
  };
  const response = await transport.send({
    method: "POST",
    url: new URL(`${baseUrl}/v1/context/retrieve`),
    headers: new Headers(headers),
    body: { kind: "json", value: request },
    signal: AbortSignal.timeout(request.bounds.deadline_ms),
    responseType: "bytes",
    maxResponseBytes: request.bounds.response_byte_limit,
    maxErrorResponseBytes: request.bounds.response_byte_limit,
  });
  if (response.status >= 400) throw new Error(`Retrieval returned HTTP ${response.status}`);
  const decoded = sdk.decodeRetrieveContextResponseBytes(response.body, request, capability);
  assertRetrievalRuntimeCanary({
    capability,
    response: decoded,
    expectedFingerprint,
    expectedProfile,
    expectedSdkRevision,
    expectedServiceRevision,
    expectedLocator,
  });
  return {
    report: {
      schema_version: "infinity-context-retrieval-runtime-canary.v1",
      ok: true,
      capability_fingerprint: capability.capability_fingerprint,
      profile_id: capability.profile_id,
      service_revision: capability.service_revision,
      sdk_revision: capability.sdk_revision,
      status: decoded.status,
      candidate_count: decoded.candidates.length,
      expected_locator: expectedLocator,
    },
  };
}

function failureReport(error) {
  const typed = typeof error === "object" && error !== null ? error : {};
  return {
    schema_version: "infinity-context-retrieval-runtime-canary.v1",
    ok: false,
    error: {
      name: typeof typed.name === "string" ? typed.name : "Error",
      code: typeof typed.code === "string" ? typed.code : "retrieval_runtime_canary_failed",
      message: error instanceof Error ? error.message : String(error),
      ...(Number.isInteger(typed.statusCode) ? { status_code: typed.statusCode } : {}),
      ...(typeof typed.retryable === "boolean" ? { retryable: typed.retryable } : {}),
      ...(typeof typed.requestId === "string" ? { request_id: typed.requestId } : {}),
    },
  };
}

function recordExitCode(result, target) {
  if (target !== undefined) target.exitCode = result.exitCode;
  return result;
}

function required(env, name) {
  const value = env[name];
  if (value === undefined || value.trim() === "") throw new Error(`${name} is required`);
  return value;
}

function hasCliFlag(args, ...flags) {
  return args.some((arg) => flags.includes(arg));
}

function printHelp(command, stdout) {
  stdout.write(`Usage: ${command} [--help] [--version]\n\nRuns the pinned retrieval runtime canary against an Infinity Context service.\n\nOptions:\n  -h, --help       Show this help without validating configuration or contacting the service.\n  -v, --version    Print the package version.\n`);
}

async function packageVersion() {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  if (typeof packageJson.version !== "string" || packageJson.version.length === 0) {
    throw new Error("SDK package version is invalid");
  }
  return packageJson.version;
}

async function isMainEntry(moduleUrl, entryPath) {
  if (typeof entryPath !== "string" || entryPath.length === 0) return false;
  try {
    return await realpath(fileURLToPath(moduleUrl)) === await realpath(entryPath);
  } catch {
    return false;
  }
}

if (await isMainEntry(import.meta.url, process.argv[1])) {
  await runRetrievalRuntimeCanaryCli({ exitCodeTarget: process });
}
