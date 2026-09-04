#!/usr/bin/env node
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";
import { runInNewContext } from "node:vm";

const execFileAsync = promisify(execFile);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const tscPath = fileURLToPath(new URL("../node_modules/typescript/bin/tsc", import.meta.url));
const esbuildPath = fileURLToPath(new URL("../node_modules/esbuild/bin/esbuild", import.meta.url));
const expectedBins = [
  "infinity-context-full-memory-proof",
  "infinity-context-runtime-canary",
  "infinity-context-retrieval-runtime-canary",
];
const fixtureExports = [
  ["context_retrieval_v2", ["capability.json", "cases.json", "document_projection.json", "errors.json", "request.json", "scoring_golden.json", "success.json"]],
  ["document_reconciliation", ["hostile_responses.json"]],
];

const tempRoot = await mkdtemp(join(tmpdir(), "infinity-context-sdk-consumer-"));

try {
  const { artifactPath, manifestPath } = await resolveInputs();

  await writeFile(join(tempRoot, "package.json"), JSON.stringify({ private: true }, null, 2));
  await execFileAsync("npm", ["install", "--ignore-scripts", "--no-audit", "--no-fund", artifactPath], {
    cwd: tempRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  const installedRoot = join(tempRoot, "node_modules", "@infinity-context", "sdk");
  const installedPackage = JSON.parse(await readFile(join(installedRoot, "package.json"), "utf8"));
  const installedIdentityBytes = await readFile(join(installedRoot, "dist", "sdk-artifact-identity.json"));
  const sourceIdentityBytes = await readFile(join(packageRoot, "dist", "sdk-artifact-identity.json"));
  if (!installedIdentityBytes.equals(sourceIdentityBytes)) {
    throw new Error("Installed SDK artifact identity differs from the pack-once source identity");
  }
  const installedIdentity = JSON.parse(installedIdentityBytes.toString("utf8"));
  if (JSON.stringify(Object.keys(installedPackage.bin ?? {}).sort()) !== JSON.stringify([...expectedBins].sort())) {
    throw new Error("Installed package bin inventory drifted");
  }
  const binEnv = { ...process.env };
  for (const name of [
    "RETRIEVAL_CANARY_SPACE_ID", "RETRIEVAL_CANARY_MEMORY_SCOPE_ID", "RETRIEVAL_CAPABILITY_FINGERPRINT",
    "RETRIEVAL_PROFILE_ID", "RETRIEVAL_SDK_REVISION", "RETRIEVAL_SERVICE_REVISION",
    "RETRIEVAL_CANARY_EXPECTED_LOCATOR",
  ]) delete binEnv[name];
  for (const binName of expectedBins) {
    const binPath = join(tempRoot, "node_modules", ".bin", binName);
    const help = await execFileAsync(binPath, ["--help"], { cwd: tempRoot, env: binEnv });
    if (help.stderr.trim().length > 0 || !help.stdout.includes(`Usage: ${binName}`)) {
      throw new Error(`Installed package bin help is invalid: ${binName}`);
    }
    const version = await execFileAsync(binPath, ["--version"], { cwd: tempRoot, env: binEnv });
    if (version.stderr.trim().length > 0 || version.stdout.trim() !== installedPackage.version) {
      throw new Error(`Installed package bin version is invalid: ${binName}`);
    }
  }
  const installedExportGate = await execFileAsync(
    process.execPath,
    [join(installedRoot, "scripts", "check-package-exports.mjs")],
    { cwd: tempRoot, env: binEnv, maxBuffer: 10 * 1024 * 1024 },
  );
  if (!installedExportGate.stdout.includes("Package exports ok:")) {
    throw new Error("Installed package export inventory gate did not complete");
  }

  await writeFile(join(tempRoot, "consumer.ts"), consumerTypecheckSource());
  const capability = JSON.parse(await readFile(join(packageRoot, "fixtures", "context_retrieval_v2", "capability.json"), "utf8"));
  const request = JSON.parse(await readFile(join(packageRoot, "fixtures", "context_retrieval_v2", "request.json"), "utf8"));
  const success = JSON.parse(await readFile(join(packageRoot, "fixtures", "context_retrieval_v2", "success.json"), "utf8"));
  if (manifestPath !== undefined) {
    await checkInstalledRetrievalCanary({
      artifactPath, capability, installedIdentity, manifestPath, success,
    });
  }
  await writeFile(join(tempRoot, "consumer-esm.mjs"), consumerEsmSource(capability, request, success));
  await writeFile(join(tempRoot, "consumer-cjs.cjs"), consumerCjsSource(capability, request, success));
  await writeFile(join(tempRoot, "consumer-browser.mjs"), consumerBrowserSource());
  await writeFile(join(tempRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: {
      target: "ES2022",
      lib: ["ES2022", "DOM"],
      module: "NodeNext",
      moduleResolution: "NodeNext",
      strict: true,
      exactOptionalPropertyTypes: true,
      noUncheckedIndexedAccess: true,
      skipLibCheck: false,
      noEmit: true,
    },
    include: ["consumer.ts"],
  }, null, 2));

  await execFileAsync(process.execPath, [tscPath, "-p", join(tempRoot, "tsconfig.json")], {
    cwd: tempRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  await execFileAsync(process.execPath, [join(tempRoot, "consumer-esm.mjs")], {
    cwd: tempRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  await execFileAsync(process.execPath, [join(tempRoot, "consumer-cjs.cjs")], {
    cwd: tempRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  await execFileAsync(esbuildPath, [
    join(tempRoot, "consumer-browser.mjs"), "--bundle", "--platform=browser", "--format=iife",
    `--outfile=${join(tempRoot, "consumer-browser.js")}`,
  ], { cwd: tempRoot, maxBuffer: 10 * 1024 * 1024 });
  const browserBundle = await readFile(join(tempRoot, "consumer-browser.js"), "utf8");
  if (/\bnode:|\brequire\s*\(/u.test(browserBundle)) {
    throw new Error("Browser Retrieval bundle contains a Node-only runtime dependency");
  }
  let subtleCalls = 0;
  const browserGlobal = {
    TextEncoder,
    TextDecoder,
    Uint8Array,
    crypto: { subtle: { digest: async () => { subtleCalls += 1; return new Uint8Array(32).buffer; } } },
  };
  runInNewContext(browserBundle, browserGlobal);
  await browserGlobal.__infinityContextBrowserSmoke;
  if (subtleCalls !== 1) throw new Error("Browser Retrieval smoke did not use Web Crypto SHA-256");
  for (const [family, names] of fixtureExports) {
    for (const name of names) {
      const source = await readFile(join(packageRoot, "fixtures", family, name));
      const packed = await readFile(join(installedRoot, "fixtures", family, name));
      if (!source.equals(packed)) throw new Error(`Packed fixture bytes drifted: ${family}/${name}`);
    }
  }

  console.log(`Consumer install ok: ${artifactPath}`);
} finally {
  await rm(tempRoot, { force: true, recursive: true });
}

async function resolveInputs() {
  const { values } = parseArgs({
    options: { artifact: { type: "string" }, manifest: { type: "string" } },
    strict: true,
    allowPositionals: false,
  });
  if (values.artifact !== undefined) {
    if (values.artifact.trim() === "") throw new Error("--artifact must not be empty");
    const artifactPath = isAbsolute(values.artifact) ? values.artifact : resolve(process.cwd(), values.artifact);
    const manifestPath = values.manifest === undefined ? undefined
      : isAbsolute(values.manifest) ? values.manifest : resolve(process.cwd(), values.manifest);
    if (values.manifest !== undefined && values.manifest.trim() === "") throw new Error("--manifest must not be empty");
    return { artifactPath, manifestPath };
  }
  if (values.manifest !== undefined) throw new Error("--manifest requires --artifact");
  const pack = await execFileAsync("npm", ["pack", "--json", "--pack-destination", tempRoot], {
    cwd: packageRoot,
    maxBuffer: 10 * 1024 * 1024,
  });
  const [packResult] = JSON.parse(pack.stdout);
  if (packResult === undefined || typeof packResult.filename !== "string") {
    throw new Error("npm pack did not return a package filename");
  }
  return { artifactPath: join(tempRoot, packResult.filename), manifestPath: undefined };
}

async function checkInstalledRetrievalCanary({ artifactPath, capability, installedIdentity, manifestPath, success }) {
  const requests = [];
  const canaryCapability = structuredClone(capability);
  canaryCapability.sdk_revision = installedIdentity.source_commit;
  const { retrievalCapabilityFingerprint } = await import("../dist/index.js");
  canaryCapability.capability_fingerprint = await retrievalCapabilityFingerprint(canaryCapability);
  const canarySuccess = structuredClone(success);
  canarySuccess.capability_fingerprint = canaryCapability.capability_fingerprint;
  for (const candidate of canarySuccess.candidates) {
    for (const contribution of candidate.contributions) contribution.query_id = "runtime-canary";
  }
  const server = createServer((request, response) => {
    requests.push(`${request.method} ${request.url}`);
    const body = request.url === "/v1/capabilities"
      ? { context: { retrieval: canaryCapability } }
      : canarySuccess;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(body));
  });
  await new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolvePromise);
  });
  try {
    const address = server.address();
    const artifactBytes = await readFile(artifactPath);
    const manifestBytes = await readFile(manifestPath);
    const binPath = join(tempRoot, "node_modules", ".bin", "infinity-context-retrieval-runtime-canary");
    const result = await execFileAsync(binPath, [], {
      cwd: tempRoot,
      env: {
        ...process.env,
        INFINITY_CONTEXT_URL: `http://127.0.0.1:${address.port}`,
        RETRIEVAL_CANARY_EXPECTED_LOCATOR: success.candidates[0].locator,
        RETRIEVAL_CANARY_MEMORY_SCOPE_ID: "scope-canary",
        RETRIEVAL_CANARY_SPACE_ID: "space-canary",
        RETRIEVAL_CAPABILITY_FINGERPRINT: canaryCapability.capability_fingerprint,
        RETRIEVAL_PROFILE_ID: canaryCapability.profile_id,
        RETRIEVAL_PROVIDER_LANES: canaryCapability.provider_lanes.map((lane) => lane.provider_id).join(","),
        RETRIEVAL_REQUIRED_PROVIDER_LANES: canaryCapability.required_provider_lanes.join(","),
        RETRIEVAL_SDK_ARTIFACT: artifactPath,
        RETRIEVAL_SDK_ARTIFACT_SHA256: sha256(artifactBytes),
        RETRIEVAL_SDK_MANIFEST_SHA256: sha256(manifestBytes),
        RETRIEVAL_SDK_RELEASE_MANIFEST: manifestPath,
        RETRIEVAL_SDK_REVISION: installedIdentity.source_commit,
        RETRIEVAL_SDK_SOURCE_TREE: installedIdentity.source_git_tree_oid,
        RETRIEVAL_SERVICE_REVISION: canaryCapability.service_revision,
      },
      maxBuffer: 10 * 1024 * 1024,
    });
    const report = JSON.parse(result.stdout);
    if (!report.ok || result.stderr !== "" || requests.join(",") !== "GET /v1/capabilities,POST /v1/context/retrieve") {
      throw new Error("Installed retrieval canary did not complete exactly one pinned submission");
    }
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
}

function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }

function consumerTypecheckSource() {
  return `import {
  InfinityContextClient,
  ReadScope,
  CONTEXT_RETRIEVAL_CONTRACT,
  CONTEXT_RETRIEVAL_RANKING_POLICY,
  assertRetrievalCapability,
  decodeRetrieveContextResponse,
  retrievalRequestPayload,
  assertMemoryBriefQuality,
  createMemoryReviewPlan,
  createMemorySummaryLoopPlan,
  type ApplyMemoryReviewPlanResult,
  type BuildMemoryBriefInput,
  type MemoryReviewPlan,
  type RetrievalScopeInput,
  type RetrieveContextInput,
  type BenchmarkSearchInput,
  type ResolveCodeRepositoryInput,
  type ConfirmFactInput,
  type ObserveDerivedPresenceInput,
  type RegisterMemoryComparisonRunInput,
  type ExactDocumentReconciliationCapabilityV1,
  type ExactDocumentReconciliationResultV1,
  type ExactDocumentReconciliationState,
  type ExactDocumentVisibilityEvidence,
  type ReconcileExactDocumentInput,
} from "@infinity-context/sdk";
import { noopInstrumentation } from "@infinity-context/sdk/instrumentation";
import { iterateCursorItems } from "@infinity-context/sdk/pagination";
import { runRuntimeCanary } from "@infinity-context/sdk/canary";
import { runFullMemoryProof } from "@infinity-context/sdk/proof";
import { assertFullMemoryReady } from "@infinity-context/sdk/runtime";
import {
  MemoryWorkflows,
  createMemoryScopePlan,
  type ApplyMemoryReviewPlanSummary,
} from "@infinity-context/sdk/workflows";

const client = new InfinityContextClient({
  baseUrl: "http://127.0.0.1:7788",
  token: "test-token",
  instrumentation: noopInstrumentation(),
});

const reviewPlan: MemoryReviewPlan = createMemoryReviewPlan({
  reason: "consumer smoke",
  contextLinks: {
    items: [{ suggestionId: "ctx_suggestion_1", action: "reject" }],
  },
  suggestions: {
    items: [{ suggestionId: "memory_suggestion_1", action: "approve" }],
  },
});

const applied: Promise<ApplyMemoryReviewPlanResult> = client.workflows.applyMemoryReviewPlan(reviewPlan);
const benchmarkInput: BenchmarkSearchInput = { spaceSlug: "workspace", query: "consumer parity" };
const repositoryInput: ResolveCodeRepositoryInput = {
  spaceId: "space", evidence: [{ kind: "normalized_remote", digest: "a".repeat(64) }],
};
const factInput: ConfirmFactInput = {
  evidenceRefs: [{ sourceRef: { source_type: "document", source_id: "doc" } }],
  expectedVersion: 1, confirmedAt: "2026-08-23T00:00:00Z", confirmationBasis: "review",
  idempotencyKey: "consumer-key",
};
const presenceInput: ObserveDerivedPresenceInput = {
  spaceId: "space", memoryScopeId: "scope", expectedFactIds: ["fact"],
};
const runInput: RegisterMemoryComparisonRunInput | undefined = undefined;
const reconciliationCapability: ExactDocumentReconciliationCapabilityV1 = {
  contract_version: "document-reconciliation.v1", endpoint: "/v1/documents/reconcile-exact",
  max_deadline_ms: 10000, max_response_bytes: 65536,
  visibility_evidence: ["accepted", "processing", "indexed"], read_only: true,
};
const reconciliationInput: ReconcileExactDocumentInput = {
  capability: reconciliationCapability, spaceId: "space", memoryScopeId: "scope",
  sourceType: "document", sourceExternalId: "external",
};
const reconciliationState: ExactDocumentReconciliationState = "present";
const reconciliationVisibility: ExactDocumentVisibilityEvidence = "accepted";
const reconciliationResult: ExactDocumentReconciliationResultV1 | undefined = undefined;
const retrievalScope: RetrievalScopeInput = { spaceId: "space", memoryScopeId: "scope" };
const retrievalInput: RetrieveContextInput = {
  contractVersion: CONTEXT_RETRIEVAL_CONTRACT,
  capabilityFingerprint: "sha256:consumer",
  profileId: "consumer-profile",
  scope: retrievalScope,
  queries: [{ queryId: "q1", query: "consumer query" }],
  filters: {
    sourceGenerations: [{ sourceKey: "source", projectionGeneration: "generation" }],
    excludedSourceKeys: [], documentKeys: [], kinds: [], category: null,
    tagsAny: [], tagsAll: [], tagsNone: [], actorKeys: [], timeInterval: null, relativeTimeInterval: null,
  },
  softPreferences: { sourcePreferences: [], actorPreferences: [], timeInterval: null, relativeTimeInterval: null, timeWeightMicros: null },
  bounds: { candidateLimit: 10, resultLimit: 5, neighborRadius: 0, responseByteLimit: 16384, deadlineMs: 1000 },
};
const retrievalPins = {
  capabilityFingerprint: "sha256:consumer",
  profileId: "consumer-profile",
  requiredProviderLanes: ["dense"],
} as const;
const retrievalCapability = assertRetrievalCapability({ context: { retrieval: {
  endpoint: "/v1/context/retrieve",
  contract_version: CONTEXT_RETRIEVAL_CONTRACT,
  ranking_policy: CONTEXT_RETRIEVAL_RANKING_POLICY,
  ranking_parameters: {
    rank_constant: 60, weight_scale_micros: 1000000, score_scale_picos: 1000000000000,
    preference_scale_micros: 1000000, max_preference_boost_micros: 250000,
    contribution_rounding: "round_half_even", preference_rounding: "floor",
    canonical_signal_match_policy: "canonical_exact_key_interval_overlap.v1",
  },
  capability_fingerprint: "1111111111111111111111111111111111111111111111111111111111111111",
  profile_id: "consumer-profile",
  service_revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  sdk_revision: "cccccccccccccccccccccccccccccccccccccccc",
  attribute_schema: "document-retrieval-projection.v1",
  index_profile_digest: "2222222222222222222222222222222222222222222222222222222222222222",
  coverage: "top_k_only",
  supports_neighbors: true,
  bounds: {
    query_variants: [1, 6], query_characters: [1, 512], provider_lanes: [1, 4], provider_rank: [1, 1000],
    source_generations: [1, 100], candidate_limit: [1, 1000], result_limit: [1, 50], neighbor_radius: [0, 2],
    response_byte_limit: [16384, 1048576], deadline_ms: [1, 2000], weight_micros: [100000, 10000000],
  },
  hard_filter_signals: ["actor_keys", "category", "document_keys", "excluded_source_keys", "kinds", "relative_time_interval", "source_generations", "tags_all", "tags_any", "tags_none", "time_interval"],
  soft_preference_signals: ["actor_preferences", "relative_time_interval", "source_preferences", "time_interval"],
  required_provider_lanes: ["dense"],
  provider_lanes: [{ provider_id: "dense", required: true, healthy: true, weight_micros: 1000000, profile_qualified: true }],
} } }, retrievalPins);
const retrieval = client.context.retrieve(retrievalInput, retrievalCapability, retrievalPins, { timeoutMs: 1000 });
const readScope = ReadScope.external({
  spaceSlug: "workspace",
  memoryScopeExternalRefs: ["scope"],
});
const brief: BuildMemoryBriefInput = {
  query: "What should the digest prioritize?",
  readScope,
};
const summaryLoop = createMemorySummaryLoopPlan({ brief });
const scopePlan = createMemoryScopePlan({
  spaceSlug: "workspace",
  topics: [{ slug: "scope", name: "Scope" }],
});
const workflowCtor: typeof MemoryWorkflows = MemoryWorkflows;
const appliedSummary: ApplyMemoryReviewPlanSummary = {
  total: 2,
  contextLinkReviews: 1,
  suggestionReviews: 1,
  byAction: { approve: 1, reject: 1 },
  applied: 2,
  failed: 0,
  stopped: false,
};

void applied;
void benchmarkInput; void repositoryInput; void factInput; void presenceInput; void runInput;
void reconciliationInput; void reconciliationState; void reconciliationVisibility; void reconciliationResult;
void client.context.benchmarkSearch; void client.codeRepositories.resolve;
void client.factLifecycle.confirm; void client.derivedEvidence.observePresence;
void client.memoryComparisonRuns.register;
void retrieval;
void decodeRetrieveContextResponse;
void retrievalRequestPayload;
void assertRetrievalCapability;
void brief;
void summaryLoop;
void scopePlan;
void workflowCtor;
void appliedSummary;
void assertMemoryBriefQuality;
void assertFullMemoryReady;
void iterateCursorItems;
void runRuntimeCanary;
void runFullMemoryProof;
`;
}

function consumerEsmSource(capability, request, success) {
  return `import { InfinityContextClient, CONTEXT_RETRIEVAL_CONTRACT, CONTEXT_RETRIEVAL_RANKING_POLICY, assertRetrievalCapability, decodeRetrieveContextResponse, retrievalRequestPayload, createMemoryReviewPlan, EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1, EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES, assertExactDocumentReconciliationCapabilityV1, decodeExactDocumentReconciliationResponseV1 } from "@infinity-context/sdk";
import { MemoryWorkflows } from "@infinity-context/sdk/workflows";
import { noopInstrumentation } from "@infinity-context/sdk/instrumentation";
import { assertFullMemoryReady } from "@infinity-context/sdk/runtime";
import { runRuntimeCanary } from "@infinity-context/sdk/canary";
import { runFullMemoryProof } from "@infinity-context/sdk/proof";
import { iterateCursorItems } from "@infinity-context/sdk/pagination";

for (const value of [
  InfinityContextClient,
  CONTEXT_RETRIEVAL_CONTRACT,
  CONTEXT_RETRIEVAL_RANKING_POLICY,
  assertRetrievalCapability,
  decodeRetrieveContextResponse,
  retrievalRequestPayload,
  createMemoryReviewPlan,
  MemoryWorkflows,
  noopInstrumentation,
  assertFullMemoryReady,
  runRuntimeCanary,
  runFullMemoryProof,
  iterateCursorItems,
  EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES,
  assertExactDocumentReconciliationCapabilityV1,
  decodeExactDocumentReconciliationResponseV1,
]) {
  if (value === undefined) {
    throw new Error("Missing ESM consumer export");
  }
}
const client = new InfinityContextClient();
if (typeof client.context.retrieve !== "function") throw new Error("Missing ESM context.retrieve");
if (typeof client.documents.reconcileExactDocument !== "function") throw new Error("Missing ESM documents.reconcileExactDocument");
if (typeof client.context.benchmarkSearch !== "function" || typeof client.codeRepositories.resolve !== "function" ||
    typeof client.factLifecycle.confirm !== "function" || typeof client.derivedEvidence.observePresence !== "function" ||
    typeof client.memoryComparisonRuns.register !== "function") throw new Error("Missing ESM parity resource");
for (const specifier of ${JSON.stringify(fixtureSpecifiers())}) {
  if (!import.meta.resolve(specifier).endsWith(".json")) throw new Error("Missing ESM fixture export: " + specifier);
}
let retrievalRequest;
const retrievalTransport = { send: async (request) => {
  retrievalRequest = request;
  return { status: 200, headers: new Headers({ "content-type": "application/json" }), body: JSON.stringify(${JSON.stringify(success)}) };
} };
const retrievalClient = new InfinityContextClient({ transport: retrievalTransport });
const retrievalResult = await retrievalClient.context.retrieve(
  ${JSON.stringify(retrievalInputFixture(request))}, ${JSON.stringify(capability)},
  ${JSON.stringify(retrievalPins(capability))},
);
if (retrievalResult.candidates.length !== 1) throw new Error("ESM context.retrieve execution failed");
if (retrievalRequest?.method !== "POST" || retrievalRequest?.url.pathname !== "/v1/context/retrieve" ||
    retrievalRequest?.responseType !== "bytes" || retrievalRequest?.requireJsonResponse !== true ||
    JSON.stringify(retrievalRequest?.expectedStatuses) !== "[200]" ||
    retrievalRequest?.body?.kind !== "json" ||
    retrievalRequest.body.value.contract_version !== CONTEXT_RETRIEVAL_CONTRACT) {
  throw new Error("ESM packed retrieval mock transport contract failed");
}
for (const status of [201, 202]) {
  const unexpectedStatusClient = new InfinityContextClient({
    retryPolicy: { maxAttempts: 3 },
    transport: { send: async () => ({
      status, headers: new Headers({ "content-type": "application/json" }),
      body: JSON.stringify(${JSON.stringify(success)}),
    }) },
  });
  let rejected = false;
  try {
    await unexpectedStatusClient.context.retrieve(
      ${JSON.stringify(retrievalInputFixture(request))}, ${JSON.stringify(capability)},
      ${JSON.stringify(retrievalPins(capability))},
    );
  } catch (error) {
    if (error?.code !== "memory.unexpected_response_status" || error?.statusCode !== status ||
        error?.retryable !== false) throw error;
    rejected = true;
  }
  if (!rejected) throw new Error("ESM packed retrieval accepted unexpected status " + status);
}
${reconciliationConsumerSource("ESM")}
`;
}

function consumerCjsSource(capability, request, success) {
  return `const { InfinityContextClient, CONTEXT_RETRIEVAL_CONTRACT, CONTEXT_RETRIEVAL_RANKING_POLICY, assertRetrievalCapability, decodeRetrieveContextResponse, retrievalRequestPayload, createMemoryReviewPlan, EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1, EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES, assertExactDocumentReconciliationCapabilityV1, decodeExactDocumentReconciliationResponseV1 } = require("@infinity-context/sdk");
const { MemoryWorkflows } = require("@infinity-context/sdk/workflows");
const { noopInstrumentation } = require("@infinity-context/sdk/instrumentation");
const { assertFullMemoryReady } = require("@infinity-context/sdk/runtime");
const { runRuntimeCanary } = require("@infinity-context/sdk/canary");
const { runFullMemoryProof } = require("@infinity-context/sdk/proof");
const { iterateCursorItems } = require("@infinity-context/sdk/pagination");

for (const value of [
  InfinityContextClient,
  CONTEXT_RETRIEVAL_CONTRACT,
  CONTEXT_RETRIEVAL_RANKING_POLICY,
  assertRetrievalCapability,
  decodeRetrieveContextResponse,
  retrievalRequestPayload,
  createMemoryReviewPlan,
  MemoryWorkflows,
  noopInstrumentation,
  assertFullMemoryReady,
  runRuntimeCanary,
  runFullMemoryProof,
  iterateCursorItems,
  EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
  EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES,
  assertExactDocumentReconciliationCapabilityV1,
  decodeExactDocumentReconciliationResponseV1,
]) {
  if (value === undefined) {
    throw new Error("Missing CJS consumer export");
  }
}
const client = new InfinityContextClient();
if (typeof client.context.retrieve !== "function") throw new Error("Missing CJS context.retrieve");
if (typeof client.documents.reconcileExactDocument !== "function") throw new Error("Missing CJS documents.reconcileExactDocument");
if (typeof client.context.benchmarkSearch !== "function" || typeof client.codeRepositories.resolve !== "function" ||
    typeof client.factLifecycle.confirm !== "function" || typeof client.derivedEvidence.observePresence !== "function" ||
    typeof client.memoryComparisonRuns.register !== "function") throw new Error("Missing CJS parity resource");
for (const specifier of ${JSON.stringify(fixtureSpecifiers())}) {
  if (!require.resolve(specifier).endsWith(".json")) throw new Error("Missing CJS fixture export: " + specifier);
}
(async () => {
  let retrievalRequest;
  const retrievalTransport = { send: async (request) => {
    retrievalRequest = request;
    return { status: 200, headers: new Headers({ "content-type": "application/json" }), body: JSON.stringify(${JSON.stringify(success)}) };
  } };
  const retrievalClient = new InfinityContextClient({ transport: retrievalTransport });
  const retrievalResult = await retrievalClient.context.retrieve(
    ${JSON.stringify(retrievalInputFixture(request))}, ${JSON.stringify(capability)},
    ${JSON.stringify(retrievalPins(capability))},
  );
  if (retrievalResult.candidates.length !== 1) throw new Error("CJS context.retrieve execution failed");
  if (retrievalRequest?.method !== "POST" || retrievalRequest?.url.pathname !== "/v1/context/retrieve" ||
      retrievalRequest?.responseType !== "bytes" || retrievalRequest?.requireJsonResponse !== true ||
      JSON.stringify(retrievalRequest?.expectedStatuses) !== "[200]" ||
      retrievalRequest?.body?.kind !== "json" ||
      retrievalRequest.body.value.contract_version !== CONTEXT_RETRIEVAL_CONTRACT) {
    throw new Error("CJS packed retrieval mock transport contract failed");
  }
  for (const status of [201, 202]) {
    const unexpectedStatusClient = new InfinityContextClient({
      retryPolicy: { maxAttempts: 3 },
      transport: { send: async () => ({
        status, headers: new Headers({ "content-type": "application/json" }),
        body: JSON.stringify(${JSON.stringify(success)}),
      }) },
    });
    let rejected = false;
    try {
      await unexpectedStatusClient.context.retrieve(
        ${JSON.stringify(retrievalInputFixture(request))}, ${JSON.stringify(capability)},
        ${JSON.stringify(retrievalPins(capability))},
      );
    } catch (error) {
      if (error?.code !== "memory.unexpected_response_status" || error?.statusCode !== status ||
          error?.retryable !== false) throw error;
      rejected = true;
    }
    if (!rejected) throw new Error("CJS packed retrieval accepted unexpected status " + status);
  }
  ${reconciliationConsumerSource("CJS")}
})().catch((error) => { console.error(error); process.exitCode = 1; });
`;
}

function reconciliationConsumerSource(format) {
  return `let reconciliationRequest;
  const reconciliationTransport = { send: async (request) => {
    reconciliationRequest = request;
    return {
      status: 200,
      headers: new Headers({ "content-type": "application/json", "x-request-id": "packed-reconciliation" }),
      body: new TextEncoder().encode(JSON.stringify({ data: {
        contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
        state: "indexed",
        scope: { space_id: "space", memory_scope_id: "scope", thread_id: null },
        source_type: "document", source_external_id: "external", document_id: "doc-packed",
        canonical_status: "active", projection_generation: "projection-v1",
        profile_generation: "profile-v1", visibility: "indexed", idempotency_key_matches: true,
      } })),
    };
  } };
  const reconciliationClient = new InfinityContextClient({
    baseUrl: "http://packed-consumer.test", transport: reconciliationTransport, retryPolicy: { maxAttempts: 1 },
  });
  const reconciliationResult = await reconciliationClient.documents.reconcileExactDocument({
    capability: {
      contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
      endpoint: "/v1/documents/reconcile-exact", max_deadline_ms: 1000,
      max_response_bytes: EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES,
      visibility_evidence: ["accepted", "processing", "indexed"], read_only: true,
    },
    spaceId: "space", memoryScopeId: "scope", sourceType: "document", sourceExternalId: "external",
    projectionGeneration: "projection-v1", profileGeneration: "profile-v1",
    idempotencyKey: "packed-reconciliation-key", deadlineMs: 500,
  });
  if (reconciliationResult.state !== "indexed" || reconciliationResult.document_id !== "doc-packed") {
    throw new Error("Packed documents.reconcileExactDocument execution failed");
  }
  if (reconciliationRequest?.url.pathname !== "/v1/documents/reconcile-exact" ||
      reconciliationRequest?.method !== "POST" ||
      reconciliationRequest?.responseType !== "bytes" ||
      reconciliationRequest?.requireJsonResponse !== true ||
      reconciliationRequest?.maxResponseBytes !== EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES ||
      reconciliationRequest?.body?.kind !== "json" ||
      reconciliationRequest.body.value.idempotency_key !== "packed-reconciliation-key") {
    throw new Error("Packed reconciliation mock transport contract failed");
  }`;
}

function consumerBrowserSource() {
  return `import { retrievalCapabilityFingerprint } from "@infinity-context/sdk";
globalThis.__infinityContextBrowserSmoke = retrievalCapabilityFingerprint({ browser: true });
`;
}

function fixtureSpecifiers() {
  return fixtureExports.flatMap(([family, names]) =>
    names.map((name) => `@infinity-context/sdk/fixtures/${family}/${name}`));
}

function retrievalPins(capability) {
  return {
    capabilityFingerprint: capability.capability_fingerprint,
    profileId: capability.profile_id,
    requiredProviderLanes: capability.required_provider_lanes,
  };
}

function retrievalInputFixture(value) {
  const interval = (item) => item === null ? null : { startAt: item.start_at, endAt: item.end_at };
  const relative = (item) => item === null ? null : { startMs: item.start_ms, endMs: item.end_ms };
  const weighted = (items) => items.map((item) => ({ key: item.key, weightMicros: item.weight_micros }));
  return {
    contractVersion: value.contract_version,
    capabilityFingerprint: value.capability_fingerprint,
    profileId: value.profile_id,
    scope: { spaceId: value.scope.space_id, memoryScopeId: value.scope.memory_scope_id, threadId: value.scope.thread_id },
    queries: value.queries.map((item) => ({ queryId: item.query_id, query: item.query, weightMicros: item.weight_micros })),
    filters: {
      sourceGenerations: value.filters.source_generations.map((item) => ({ sourceKey: item.source_key, projectionGeneration: item.projection_generation })),
      excludedSourceKeys: value.filters.excluded_source_keys, documentKeys: value.filters.document_keys,
      kinds: value.filters.kinds, category: value.filters.category, tagsAny: value.filters.tags_any,
      tagsAll: value.filters.tags_all, tagsNone: value.filters.tags_none, actorKeys: value.filters.actor_keys,
      timeInterval: interval(value.filters.time_interval), relativeTimeInterval: relative(value.filters.relative_time_interval),
    },
    softPreferences: {
      sourcePreferences: weighted(value.soft_preferences.source_preferences),
      actorPreferences: weighted(value.soft_preferences.actor_preferences),
      timeInterval: interval(value.soft_preferences.time_interval),
      relativeTimeInterval: relative(value.soft_preferences.relative_time_interval), timeWeightMicros: value.soft_preferences.time_weight_micros,
    },
    bounds: {
      candidateLimit: value.bounds.candidate_limit, resultLimit: value.bounds.result_limit,
      neighborRadius: value.bounds.neighbor_radius, responseByteLimit: value.bounds.response_byte_limit,
      deadlineMs: value.bounds.deadline_ms,
    },
  };
}
