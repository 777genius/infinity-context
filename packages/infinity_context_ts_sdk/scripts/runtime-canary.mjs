#!/usr/bin/env node
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { InfinityContextClient, runRuntimeCanary } from "../dist/index.js";

const env = process.env;
const baseUrl = env.INFINITY_CONTEXT_URL ?? "http://127.0.0.1:7788";
const token = env.INFINITY_CONTEXT_TOKEN;
const outputPath = env.INFINITY_CONTEXT_CANARY_OUTPUT;
const requireReady = env.INFINITY_CONTEXT_CANARY_REQUIRE_READY === undefined
  ? true
  : !["0", "false", "no"].includes(env.INFINITY_CONTEXT_CANARY_REQUIRE_READY.toLowerCase());

const report = await runRuntimeCanary({
  client: new InfinityContextClient({
    baseUrl,
    token: () => token,
    timeoutMs: parsePositiveInteger(env.INFINITY_CONTEXT_CANARY_TIMEOUT_MS) ?? 15_000,
    retryPolicy: { maxAttempts: 2 },
  }),
  ...(env.INFINITY_CONTEXT_CANARY_QUERY !== undefined ? { query: env.INFINITY_CONTEXT_CANARY_QUERY } : {}),
  ...(env.INFINITY_CONTEXT_CANARY_SPACE_SLUG !== undefined ? { spaceSlug: env.INFINITY_CONTEXT_CANARY_SPACE_SLUG } : {}),
  ...externalRefs("INFINITY_CONTEXT_CANARY_MEMORY_SCOPE_EXTERNAL_REFS"),
  ...canonicalIds("INFINITY_CONTEXT_CANARY_MEMORY_SCOPE_IDS"),
  ...(env.INFINITY_CONTEXT_CANARY_THREAD_EXTERNAL_REF !== undefined
    ? { threadExternalRef: env.INFINITY_CONTEXT_CANARY_THREAD_EXTERNAL_REF }
    : {}),
  includeContextProbe: parseBoolean(env.INFINITY_CONTEXT_CANARY_INCLUDE_CONTEXT_PROBE, true),
  includeSearchProbe: parseBoolean(env.INFINITY_CONTEXT_CANARY_INCLUDE_SEARCH_PROBE, false),
  requireDerivedRetrieval: parseBoolean(env.INFINITY_CONTEXT_CANARY_REQUIRE_DERIVED_RETRIEVAL, true),
  tokenBudget: parsePositiveInteger(env.INFINITY_CONTEXT_CANARY_TOKEN_BUDGET),
  maxFacts: parsePositiveInteger(env.INFINITY_CONTEXT_CANARY_MAX_FACTS),
  maxChunks: parsePositiveInteger(env.INFINITY_CONTEXT_CANARY_MAX_CHUNKS),
  maxEvidenceItems: parsePositiveInteger(env.INFINITY_CONTEXT_CANARY_MAX_EVIDENCE_ITEMS),
  ...(env.INFINITY_CONTEXT_CANARY_CONSISTENCY_MODE !== undefined
    ? { consistencyMode: env.INFINITY_CONTEXT_CANARY_CONSISTENCY_MODE }
    : {}),
});

const serialized = `${JSON.stringify(report, null, 2)}\n`;
if (outputPath === undefined || outputPath.trim().length === 0) {
  process.stdout.write(serialized);
} else {
  const resolvedOutputPath = resolve(outputPath);
  await mkdir(dirname(resolvedOutputPath), { recursive: true });
  await writeFile(resolvedOutputPath, serialized, "utf8");
  process.stdout.write(`${resolvedOutputPath}\n`);
}

if (requireReady && !report.ok) {
  process.exitCode = 1;
}

function parsePositiveInteger(value) {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number(value);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function parseBoolean(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  return !["0", "false", "no"].includes(value.toLowerCase());
}

function splitCsv(value) {
  if (value === undefined) {
    return undefined;
  }
  const items = value.split(",").map((item) => item.trim()).filter(Boolean);
  return items.length === 0 ? undefined : items;
}

function externalRefs(envKey) {
  const values = splitCsv(env[envKey]);
  return values === undefined ? {} : { memoryScopeExternalRefs: values };
}

function canonicalIds(envKey) {
  const values = splitCsv(env[envKey]);
  return values === undefined ? {} : { memoryScopeIds: values };
}
