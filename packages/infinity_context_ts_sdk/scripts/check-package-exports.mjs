import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const require = createRequire(import.meta.url);
const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));

const expectedExports = [
  ["@infinity-context/sdk", "InfinityContextClient"],
  ["@infinity-context/sdk", "assertRetrievalCapability"],
  ["@infinity-context/sdk", "CONTEXT_RETRIEVAL_CONTRACT"],
  ["@infinity-context/sdk", "CONTEXT_RETRIEVAL_RANKING_POLICY"],
  ["@infinity-context/sdk", "decodeRetrieveContextResponse"],
  ["@infinity-context/sdk", "decodeRetrieveContextResponseBytes"],
  ["@infinity-context/sdk", "decodeRetrievalCapability"],
  ["@infinity-context/sdk", "decodeRetrievalCapabilityBytes"],
  ["@infinity-context/sdk", "decodeContextRetrievalCapabilitiesResponseBytes"],
  ["@infinity-context/sdk", "canonicalRetrievalCapabilityBytes"],
  ["@infinity-context/sdk", "retrievalCapabilityFingerprint"],
  ["@infinity-context/sdk", "verifyRetrievalCapabilityFingerprint"],
  ["@infinity-context/sdk", "CONTEXT_RETRIEVAL_ERROR_SPECS"],
  ["@infinity-context/sdk", "retrievalErrorDecoder"],
  ["@infinity-context/sdk", "decodeRetrievalError"],
  ["@infinity-context/sdk", "DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1"],
  ["@infinity-context/sdk", "documentRetrievalProjectionV1Payload"],
  ["@infinity-context/sdk", "retrievalRequestPayload"],
  ["@infinity-context/sdk", "validateRetrievalPreflight"],
  ["@infinity-context/sdk", "EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1"],
  ["@infinity-context/sdk", "EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES"],
  ["@infinity-context/sdk", "assertExactDocumentReconciliationCapabilityV1"],
  ["@infinity-context/sdk", "decodeExactDocumentReconciliationResponseV1"],
  ["@infinity-context/sdk/instrumentation", "noopInstrumentation"],
  ["@infinity-context/sdk/pagination", "iterateCursorItems"],
  ["@infinity-context/sdk/runtime", "assertFullMemoryReady"],
  ["@infinity-context/sdk/canary", "runRuntimeCanary"],
  ["@infinity-context/sdk/proof", "runFullMemoryProof"],
  ["@infinity-context/sdk/workflows", "MemoryWorkflows"],
];
const expectedTypeExports = [
  "RetrievalCapability", "RetrievalErrorCode",
  "DocumentRetrievalProjectionRelativeTimeIntervalV1Input",
  "DocumentRetrievalProjectionTimeIntervalV1Input", "DocumentRetrievalProjectionV1Input",
  "RequiredRetrievalCapability", "RetrievalAppliedBounds", "RetrievalBoundsInput",
  "RetrievalCandidate", "RetrievalCapabilityBounds", "RetrievalCapabilityProviderLane",
  "RetrievalContribution", "RetrievalDegradationReasonCode", "RetrievalHardFiltersInput",
  "RetrievalHardFilterSignal", "RetrievalNeighbor", "RetrievalProviderOutcome",
  "RetrievalProviderReasonCode", "RetrievalProviderStatus", "RetrievalQueryInput",
  "RetrievalRankingParameters", "RetrievalRawScoreKind", "RetrievalRelativeTimeIntervalInput", "RetrievalScopeInput",
  "RetrievalSoftPreferencesInput", "RetrievalSoftPreferenceSignal",
  "RetrievalSourceGenerationInput", "RetrievalTimeIntervalInput", "RetrievalWeightedKeyInput",
  "RetrieveContextInput", "RetrieveContextResponse",
  "BenchmarkSearchInput", "ResolveCodeRepositoryInput", "RegisterCodeScopeInput",
  "ObserveDerivedPresenceInput", "DeleteQdrantEvidenceInput", "DeleteGraphitiEvidenceInput",
  "ConfirmFactInput", "EndFactValidityInput", "SupersedeFactInput", "DisputeFactInput",
  "ReinstateSupersessionInput", "RegisterMemoryComparisonRunInput", "CleanupTargetAuthorityInput",
  "SealProjectionManifestInput", "CleanupMemoryComparisonRunInput",
  "FinalizeMemoryComparisonCleanupInput", "FinalizeMemoryComparisonAbortInput",
  "ExactDocumentReconciliationCapabilityV1", "ExactDocumentReconciliationResultV1",
  "ExactDocumentReconciliationState", "ExactDocumentVisibilityEvidence",
  "ReconcileExactDocumentInput",
];
const expectedBins = [
  ["infinity-context-full-memory-proof", "scripts/full-memory-proof.mjs"],
  ["infinity-context-runtime-canary", "scripts/runtime-canary.mjs"],
  ["infinity-context-retrieval-runtime-canary", "scripts/retrieval-runtime-canary.mjs"],
];
const fixtureExports = [
  ["context_retrieval_v2", ["capability.json", "cases.json", "document_projection.json", "errors.json", "request.json", "scoring_golden.json", "success.json"]],
  ["document_reconciliation", ["hostile_responses.json"]],
];

if (JSON.stringify(Object.keys(packageJson.bin ?? {}).sort()) !==
    JSON.stringify(expectedBins.map(([name]) => name).sort())) {
  throw new Error("Published package bin inventory drifted");
}

for (const [specifier, exportName] of expectedExports) {
  const esm = await import(specifier);
  if (typeof esm[exportName] === "undefined") {
    throw new Error(`Missing ESM export ${exportName} from ${specifier}`);
  }

  const cjs = require(specifier);
  if (typeof cjs[exportName] === "undefined") {
    throw new Error(`Missing CJS export ${exportName} from ${specifier}`);
  }
}

for (const [resource, method] of [
  ["codeRepositories", "resolve"], ["codeRepositories", "registerScope"],
  ["derivedEvidence", "observePresence"], ["derivedEvidence", "deleteQdrant"],
  ["derivedEvidence", "deleteGraphiti"], ["factLifecycle", "confirm"],
  ["factLifecycle", "endValidity"], ["factLifecycle", "supersede"],
  ["factLifecycle", "dispute"], ["factLifecycle", "reinstateSupersession"],
  ["memoryComparisonRuns", "register"], ["memoryComparisonRuns", "prepareCleanupTargetAuthority"],
  ["memoryComparisonRuns", "sealProjectionManifest"], ["memoryComparisonRuns", "getCleanup"],
  ["memoryComparisonRuns", "cleanup"], ["memoryComparisonRuns", "finalizeCleanup"],
  ["memoryComparisonRuns", "finalizeAbort"], ["context", "benchmarkSearch"],
]) {
  const { InfinityContextClient } = await import("@infinity-context/sdk");
  if (typeof new InfinityContextClient()[resource]?.[method] !== "function") {
    throw new Error(`Missing resource method InfinityContextClient.${resource}.${method}`);
  }
}

const declarationPath = new URL(`../${packageJson.types.replace(/^\.\//, "")}`, import.meta.url);
const declarations = await readFile(declarationPath, "utf8");
for (const exportName of expectedTypeExports) {
  const directExport = new RegExp(
    `\\bexport\\s+(?:declare\\s+)?(?:interface|type)\\s+${exportName}\\b`,
  ).test(declarations);
  const listedExport = [...declarations.matchAll(/export\s+(?:type\s+)?\{([^}]*)\}/gs)]
    .some((match) => new RegExp(`\\b(?:type\\s+)?${exportName}\\b`).test(match[1]));
  if (!directExport && !listedExport) {
    throw new Error(`Missing type export ${exportName} from ${packageJson.types}`);
  }
}

for (const [binName, targetPath] of expectedBins) {
  const declaredTarget = packageJson.bin?.[binName];
  if (declaredTarget !== `./${targetPath}`) {
    throw new Error(`Missing package bin ${binName} -> ./${targetPath}`);
  }

  const targetUrl = new URL(`../${targetPath}`, import.meta.url);
  const targetStat = await stat(targetUrl);
  if (!targetStat.isFile()) {
    throw new Error(`Package bin target is not a file: ${targetPath}`);
  }

  const targetText = await readFile(targetUrl, "utf8");
  if (!targetText.startsWith("#!/usr/bin/env node")) {
    throw new Error(`Package bin target is missing node shebang: ${targetPath}`);
  }

  const resolvedTargetPath = fileURLToPath(targetUrl);
  const help = await execFileAsync(process.execPath, [resolvedTargetPath, "--help"]);
  if (help.stderr.trim().length > 0 || !help.stdout.includes(`Usage: ${binName}`)) {
    throw new Error(`Package bin help output is invalid for ${binName}`);
  }

  const version = await execFileAsync(process.execPath, [resolvedTargetPath, "--version"]);
  if (version.stderr.trim().length > 0 || version.stdout.trim() !== packageJson.version) {
    throw new Error(`Package bin version output is invalid for ${binName}`);
  }
}

for (const [family, names] of fixtureExports) {
  const exportKey = `./fixtures/${family}/*.json`;
  if (packageJson.exports?.[exportKey]?.default !== `./fixtures/${family}/*.json`) {
    throw new Error(`Fixture package export is missing: ${family}`);
  }
  for (const name of names) {
    const packaged = await readFile(new URL(`../fixtures/${family}/${name}`, import.meta.url));
    const specifier = `@infinity-context/sdk/fixtures/${family}/${name}`;
    const esmResolved = fileURLToPath(import.meta.resolve(specifier));
    const cjsResolved = require.resolve(specifier);
    if (esmResolved !== cjsResolved || !packaged.equals(await readFile(esmResolved))) {
      throw new Error(`Fixture export is invalid: ${family}/${name}`);
    }
  }
}

console.log(
  `Package exports ok: ${expectedExports.length} runtime entries, ${expectedTypeExports.length} type entries, ` +
    `${expectedBins.length} bins and ${fixtureExports.reduce((count, [, names]) => count + names.length, 0)} fixture bytes`,
);
