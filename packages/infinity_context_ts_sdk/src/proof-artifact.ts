import type { FullMemoryProofReport } from "./full-memory-proof.js";
import { createInfinityContextError, InfinityContextError } from "./errors.js";
import type { JsonObject } from "./types.js";

export const FULL_MEMORY_PROOF_ARTIFACT_SCHEMA = "infinity_context.full_memory_proof_artifact.v1";

export interface FullMemoryProofSdkMetadata {
  readonly packageName?: string;
  readonly packageVersion?: string;
}

export interface FullMemoryProofGitMetadata {
  readonly commitSha?: string;
  readonly branch?: string;
  readonly repository?: string;
}

export interface FullMemoryProofRuntimeMetadata {
  readonly baseUrl?: string;
  readonly profile?: string;
  readonly requireFullMemory?: boolean;
  readonly qualityPreset?: string;
}

export interface FullMemoryProofArtifactMetadata {
  readonly sdk?: FullMemoryProofSdkMetadata;
  readonly git?: FullMemoryProofGitMetadata;
  readonly runtime?: FullMemoryProofRuntimeMetadata;
  readonly labels?: JsonObject;
}

export interface FullMemoryProofArtifactInput {
  readonly report: FullMemoryProofReport;
  readonly startedAt?: Date | string;
  readonly finishedAt?: Date | string;
  readonly durationMs?: number;
  readonly metadata?: FullMemoryProofArtifactMetadata;
}

export interface FullMemoryProofArtifactSummary {
  readonly ok: boolean;
  readonly mode: "full" | "lite";
  readonly durableOk: boolean;
  readonly fullMemoryOk: boolean;
  readonly checksTotal: number;
  readonly checksPassed: number;
  readonly checksFailed: number;
  readonly failedChecks: readonly string[];
  readonly enabledAdapters: readonly string[];
  readonly supportsQdrant: boolean;
  readonly supportsGraphiti: boolean;
  readonly vectorHealthy: boolean;
  readonly graphHealthy: boolean;
  readonly derivedRetrievalUsed: boolean;
  readonly retrievalSourcesUsed: readonly string[];
  readonly vectorQueryCount: number;
  readonly graphQueryCount: number;
  readonly ragQueryCount: number;
  readonly sourceEvidenceSuccessRate: number;
  readonly memoryInspectionIssueCount: number;
  readonly maintenanceActionableCount: number;
  readonly outboxBlockingCount: number;
}

export interface FullMemoryProofArtifact {
  readonly schemaVersion: typeof FULL_MEMORY_PROOF_ARTIFACT_SCHEMA;
  readonly generatedAt: string;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly durationMs: number | null;
  readonly ok: boolean;
  readonly summary: FullMemoryProofArtifactSummary;
  readonly metadata: FullMemoryProofArtifactMetadata;
  readonly report: FullMemoryProofReport;
}

export interface FullMemoryProofArtifactPolicy {
  readonly requireOk?: boolean;
  readonly requireFullMemory?: boolean;
  readonly maxFailedChecks?: number;
  readonly minChecksPassed?: number;
  readonly minSourceEvidenceSuccessRate?: number;
  readonly maxMemoryInspectionIssues?: number;
  readonly maxMaintenanceActionable?: number;
  readonly maxOutboxBlocking?: number;
  readonly maxDurationMs?: number;
  readonly requiredAdapters?: readonly string[];
  readonly requiredRetrievalSources?: readonly string[];
  readonly requireGitCommit?: boolean;
  readonly requirePackageVersion?: boolean;
}

export interface FullMemoryProofArtifactEvaluation {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly policy: FullMemoryProofArtifactPolicy;
  readonly summary: FullMemoryProofArtifactSummary;
}

const fullMemoryCheckNames = new Set([
  "capabilitiesFullMemory",
  "derivedRetrievalUsed",
  "vectorHealthy",
  "graphHealthy",
]);

export function buildFullMemoryProofArtifact(
  input: FullMemoryProofArtifactInput,
): FullMemoryProofArtifact {
  const startedAt = normalizeDate(input.startedAt);
  const finishedAt = normalizeDate(input.finishedAt);
  const generatedAt = finishedAt ?? normalizeDate(new Date()) ?? new Date(0).toISOString();

  return {
    schemaVersion: FULL_MEMORY_PROOF_ARTIFACT_SCHEMA,
    generatedAt,
    startedAt,
    finishedAt,
    durationMs: proofDurationMs(input.durationMs, startedAt, finishedAt),
    ok: input.report.ok,
    summary: summarizeFullMemoryProofReport(input.report),
    metadata: input.metadata ?? {},
    report: input.report,
  };
}

export function summarizeFullMemoryProofReport(
  report: FullMemoryProofReport,
): FullMemoryProofArtifactSummary {
  const checkEntries = Object.entries(report.checks);
  const failedChecks = checkEntries
    .filter(([, passed]) => !passed)
    .map(([name]) => name)
    .sort();
  const durableEntries = checkEntries.filter(([name]) => !fullMemoryCheckNames.has(name));
  const fullMemoryEntries = checkEntries.filter(([name]) => fullMemoryCheckNames.has(name));
  const fullMemoryOk = fullMemoryEntries.every(([, passed]) => passed);

  return {
    ok: report.ok,
    mode: fullMemoryOk ? "full" : "lite",
    durableOk: durableEntries.every(([, passed]) => passed),
    fullMemoryOk,
    checksTotal: checkEntries.length,
    checksPassed: checkEntries.length - failedChecks.length,
    checksFailed: failedChecks.length,
    failedChecks,
    enabledAdapters: report.capabilities.enabledAdapters,
    supportsQdrant: report.capabilities.supportsQdrant,
    supportsGraphiti: report.capabilities.supportsGraphiti,
    vectorHealthy: report.checks.vectorHealthy,
    graphHealthy: report.checks.graphHealthy,
    derivedRetrievalUsed: report.checks.derivedRetrievalUsed,
    retrievalSourcesUsed: stringArrayField(report.contextDiagnostics, "retrieval_sources_used"),
    vectorQueryCount: queryCount(report.retrieval.vector.queryCount),
    graphQueryCount: queryCount(report.retrieval.graph.queryCount),
    ragQueryCount: queryCount(report.retrieval.rag.queryCount),
    sourceEvidenceSuccessRate: report.observed.sourceEvidenceBatchSummary.successRate,
    memoryInspectionIssueCount: report.observed.memoryInspectionIssueCount,
    maintenanceActionableCount: report.observed.maintenanceActionableCount,
    outboxBlockingCount: report.observed.outboxDrainDiagnostics.blocking_count,
  };
}

export function evaluateFullMemoryProofArtifact(
  artifact: FullMemoryProofArtifact,
  policy: FullMemoryProofArtifactPolicy = {},
): FullMemoryProofArtifactEvaluation {
  const errors: string[] = [];
  const warnings: string[] = [];
  const summary = artifact.summary;

  if ((policy.requireOk ?? true) && !artifact.ok) {
    errors.push("proof artifact is not ok");
  }
  if ((policy.requireFullMemory ?? false) && !summary.fullMemoryOk) {
    errors.push("full memory checks are not satisfied");
  }
  if (policy.maxFailedChecks !== undefined && summary.checksFailed > policy.maxFailedChecks) {
    errors.push(`proof has ${summary.checksFailed} failed check(s), expected at most ${policy.maxFailedChecks}`);
  }
  if (policy.minChecksPassed !== undefined && summary.checksPassed < policy.minChecksPassed) {
    errors.push(`proof passed ${summary.checksPassed} check(s), expected at least ${policy.minChecksPassed}`);
  }
  if (
    policy.minSourceEvidenceSuccessRate !== undefined &&
    summary.sourceEvidenceSuccessRate < policy.minSourceEvidenceSuccessRate
  ) {
    errors.push(
      `source evidence success rate is ${summary.sourceEvidenceSuccessRate}, expected at least ${policy.minSourceEvidenceSuccessRate}`,
    );
  }
  if (
    policy.maxMemoryInspectionIssues !== undefined &&
    summary.memoryInspectionIssueCount > policy.maxMemoryInspectionIssues
  ) {
    errors.push(
      `memory inspection has ${summary.memoryInspectionIssueCount} issue(s), expected at most ${policy.maxMemoryInspectionIssues}`,
    );
  }
  if (
    policy.maxMaintenanceActionable !== undefined &&
    summary.maintenanceActionableCount > policy.maxMaintenanceActionable
  ) {
    errors.push(
      `maintenance plan has ${summary.maintenanceActionableCount} actionable item(s), expected at most ${policy.maxMaintenanceActionable}`,
    );
  }
  if (policy.maxOutboxBlocking !== undefined && summary.outboxBlockingCount > policy.maxOutboxBlocking) {
    errors.push(
      `outbox has ${summary.outboxBlockingCount} blocking item(s), expected at most ${policy.maxOutboxBlocking}`,
    );
  }
  if (policy.maxDurationMs !== undefined && artifact.durationMs !== null && artifact.durationMs > policy.maxDurationMs) {
    errors.push(`proof took ${artifact.durationMs}ms, expected at most ${policy.maxDurationMs}ms`);
  } else if (policy.maxDurationMs !== undefined && artifact.durationMs === null) {
    warnings.push("proof duration is unavailable");
  }
  for (const adapter of policy.requiredAdapters ?? []) {
    if (!summary.enabledAdapters.includes(adapter)) {
      errors.push(`required adapter is missing: ${adapter}`);
    }
  }
  for (const source of policy.requiredRetrievalSources ?? []) {
    if (!summary.retrievalSourcesUsed.includes(source)) {
      errors.push(`required retrieval source was not used: ${source}`);
    }
  }
  if ((policy.requireGitCommit ?? false) && !hasText(artifact.metadata.git?.commitSha)) {
    errors.push("git commit metadata is required");
  }
  if ((policy.requirePackageVersion ?? false) && !hasText(artifact.metadata.sdk?.packageVersion)) {
    errors.push("SDK package version metadata is required");
  }

  if (summary.failedChecks.length > 0) {
    warnings.push(`failed checks: ${summary.failedChecks.join(", ")}`);
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
    policy,
    summary,
  };
}

export function assertFullMemoryProofArtifact(
  artifact: FullMemoryProofArtifact,
  policy: FullMemoryProofArtifactPolicy = {},
): FullMemoryProofArtifactEvaluation {
  const evaluation = evaluateFullMemoryProofArtifact(artifact, policy);
  if (evaluation.ok) {
    return evaluation;
  }

  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.full_memory_proof_artifact_failed",
    message: `Full memory proof artifact failed: ${evaluation.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: evaluation.errors,
      warnings: evaluation.warnings,
      policy: artifactPolicyDetails(policy),
      summary: artifactSummaryDetails(evaluation.summary),
    } satisfies JsonObject,
  });
}

function normalizeDate(value: Date | string | undefined): string | null {
  if (value === undefined) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  const timestamp = date.getTime();

  return Number.isFinite(timestamp) ? date.toISOString() : null;
}

function proofDurationMs(
  explicitDurationMs: number | undefined,
  startedAt: string | null,
  finishedAt: string | null,
): number | null {
  if (explicitDurationMs !== undefined && Number.isFinite(explicitDurationMs) && explicitDurationMs >= 0) {
    return Math.round(explicitDurationMs);
  }
  if (startedAt === null || finishedAt === null) {
    return null;
  }
  const durationMs = Date.parse(finishedAt) - Date.parse(startedAt);

  return Number.isFinite(durationMs) ? Math.max(0, durationMs) : null;
}

function stringArrayField(value: JsonObject, key: string): readonly string[] {
  const field = value[key];
  if (!Array.isArray(field)) {
    return [];
  }

  return field.filter((item): item is string => typeof item === "string");
}

function queryCount(value: number | undefined): number {
  return value === undefined ? 0 : value;
}

function hasText(value: string | undefined): boolean {
  return value !== undefined && value.trim().length > 0;
}

function artifactPolicyDetails(policy: FullMemoryProofArtifactPolicy): JsonObject {
  return {
    ...(policy.requireOk !== undefined ? { require_ok: policy.requireOk } : {}),
    ...(policy.requireFullMemory !== undefined ? { require_full_memory: policy.requireFullMemory } : {}),
    ...(policy.maxFailedChecks !== undefined ? { max_failed_checks: policy.maxFailedChecks } : {}),
    ...(policy.minChecksPassed !== undefined ? { min_checks_passed: policy.minChecksPassed } : {}),
    ...(policy.minSourceEvidenceSuccessRate !== undefined
      ? { min_source_evidence_success_rate: policy.minSourceEvidenceSuccessRate }
      : {}),
    ...(policy.maxMemoryInspectionIssues !== undefined
      ? { max_memory_inspection_issues: policy.maxMemoryInspectionIssues }
      : {}),
    ...(policy.maxMaintenanceActionable !== undefined
      ? { max_maintenance_actionable: policy.maxMaintenanceActionable }
      : {}),
    ...(policy.maxOutboxBlocking !== undefined ? { max_outbox_blocking: policy.maxOutboxBlocking } : {}),
    ...(policy.maxDurationMs !== undefined ? { max_duration_ms: policy.maxDurationMs } : {}),
    ...(policy.requiredAdapters !== undefined ? { required_adapters: [...policy.requiredAdapters] } : {}),
    ...(policy.requiredRetrievalSources !== undefined
      ? { required_retrieval_sources: [...policy.requiredRetrievalSources] }
      : {}),
    ...(policy.requireGitCommit !== undefined ? { require_git_commit: policy.requireGitCommit } : {}),
    ...(policy.requirePackageVersion !== undefined ? { require_package_version: policy.requirePackageVersion } : {}),
  };
}

function artifactSummaryDetails(summary: FullMemoryProofArtifactSummary): JsonObject {
  return {
    ok: summary.ok,
    mode: summary.mode,
    durable_ok: summary.durableOk,
    full_memory_ok: summary.fullMemoryOk,
    checks_total: summary.checksTotal,
    checks_passed: summary.checksPassed,
    checks_failed: summary.checksFailed,
    failed_checks: [...summary.failedChecks],
    enabled_adapters: [...summary.enabledAdapters],
    retrieval_sources_used: [...summary.retrievalSourcesUsed],
    vector_query_count: summary.vectorQueryCount,
    graph_query_count: summary.graphQueryCount,
    rag_query_count: summary.ragQueryCount,
    source_evidence_success_rate: summary.sourceEvidenceSuccessRate,
    memory_inspection_issue_count: summary.memoryInspectionIssueCount,
    maintenance_actionable_count: summary.maintenanceActionableCount,
    outbox_blocking_count: summary.outboxBlockingCount,
  };
}
