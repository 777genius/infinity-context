import type { ContextRetrievalComponent } from "../diagnostics.js";
import { createInfinityContextError, InfinityContextError } from "../errors.js";
import type { JsonObject } from "../types.js";
import type { MemoryBriefDiagnostics, RunMemorySummaryLoopResult } from "./memory.js";
import type {
  MemoryBriefEvidenceSummary,
  MemoryBriefQualityReport,
} from "./memory-brief-quality.js";
import type {
  RecordSourceEvidenceBatchSummary,
} from "./memory-source-evidence.js";
import { memoryBriefRetrievalHealthy, uniqueStrings } from "./workflow-helpers.js";

export type MemorySummaryLoopStatus = "ready" | "degraded" | "failed";
export type MemorySummaryLoopGateStatus = "passed" | "failed" | "skipped";

export interface MemorySummaryLoopGateReport {
  readonly status: MemorySummaryLoopGateStatus;
  readonly ok: boolean | null;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
}

export interface MemorySummaryLoopSourceEvidenceReport {
  readonly total: number;
  readonly completed: number;
  readonly skipped: number;
  readonly succeeded: number;
  readonly failed: number;
  readonly successRate: number;
  readonly retryableFailures: number;
  readonly nonRetryableFailures: number;
  readonly bySourceType: Readonly<Record<string, number>>;
}

export interface MemorySummaryLoopReadableSummary {
  readonly contextItems: number;
  readonly searchItems: number;
  readonly digestSections: number;
  readonly topEvidenceItems: number;
  readonly sourceRefsTotal: number;
  readonly uniqueSourceRefs: number;
  readonly citationsTotal: number;
  readonly uniqueCitations: number;
  readonly bySourceType: Readonly<Record<string, number>>;
  readonly renderedText: string;
  readonly renderedMarkdown?: string;
}

export interface MemorySummaryLoopReport {
  readonly ok: boolean;
  readonly status: MemorySummaryLoopStatus;
  readonly gates: {
    readonly readiness: MemorySummaryLoopGateReport;
    readonly sourceEvidence: MemorySummaryLoopGateReport;
    readonly outboxDrain: MemorySummaryLoopGateReport;
    readonly quality: MemorySummaryLoopGateReport;
  };
  readonly sourceEvidence?: MemorySummaryLoopSourceEvidenceReport;
  readonly quality?: MemoryBriefQualityReport;
  readonly evidence: MemoryBriefEvidenceSummary;
  readonly retrieval: MemoryBriefDiagnostics;
  readonly summary: MemorySummaryLoopReadableSummary;
  readonly warnings: readonly string[];
  readonly errors: readonly string[];
}

export interface MemorySummaryLoopPolicy {
  readonly requireReadiness?: boolean;
  readonly requireSourceEvidence?: boolean;
  readonly requireOutboxDrain?: boolean;
  readonly requireQuality?: boolean;
  readonly failOnWarnings?: boolean;
  readonly minSourceEvidenceSuccessRate?: number;
  readonly maxSourceEvidenceFailures?: number;
  readonly minContextItems?: number;
  readonly minSearchItems?: number;
  readonly minDigestSections?: number;
  readonly minTopEvidenceItems?: number;
  readonly minUniqueSourceRefs?: number;
  readonly minCitations?: number;
  readonly requiredSourceEvidenceTypes?: readonly string[];
  readonly requiredEvidenceSourceTypes?: readonly string[];
  readonly requireDerivedRetrieval?: boolean;
  readonly requiredRetrieval?: readonly ContextRetrievalComponent[];
}

export interface MemorySummaryLoopPolicyEvaluation {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly policy: MemorySummaryLoopPolicy;
  readonly report: MemorySummaryLoopReport;
}

export function summarizeMemorySummaryLoop(loop: RunMemorySummaryLoopResult): MemorySummaryLoopReport {
  const errors = uniqueStrings([
    ...(loop.readiness?.readiness.errors ?? []),
    ...sourceEvidenceErrors(loop.sourceEvidenceSummary),
    ...outboxDrainErrors(loop),
    ...(loop.quality?.errors ?? []),
  ]);
  const warnings = uniqueStrings([
    ...loop.diagnostics.warnings,
    ...(loop.readiness?.readiness.warnings ?? []),
    ...(loop.quality?.warnings ?? []),
    ...loop.evidenceSummary.warnings,
  ]);

  return {
    ok: loop.diagnostics.ok,
    status: loopStatus(loop, errors),
    gates: {
      readiness: gateReport(
        loop.diagnostics.readinessOk,
        loop.readiness?.readiness.errors,
        loop.readiness?.readiness.warnings,
      ),
      sourceEvidence: gateReport(loop.diagnostics.sourceEvidenceOk, sourceEvidenceErrors(loop.sourceEvidenceSummary)),
      outboxDrain: gateReport(loop.diagnostics.outboxDrainOk, outboxDrainErrors(loop)),
      quality: gateReport(loop.diagnostics.qualityOk, loop.quality?.errors, loop.quality?.warnings),
    },
    ...(loop.sourceEvidenceSummary ? { sourceEvidence: sourceEvidenceReport(loop.sourceEvidenceSummary) } : {}),
    ...(loop.quality ? { quality: loop.quality } : {}),
    evidence: loop.evidenceSummary,
    retrieval: loop.brief.diagnostics,
    summary: readableSummary(loop),
    warnings,
    errors,
  };
}

export function evaluateMemorySummaryLoopPolicy(
  input: RunMemorySummaryLoopResult | MemorySummaryLoopReport,
  policy: MemorySummaryLoopPolicy = {},
): MemorySummaryLoopPolicyEvaluation {
  const report = memorySummaryLoopReport(input);
  const errors: string[] = [...report.errors];
  const warnings = [...report.warnings];

  if (!report.ok && errors.length === 0) {
    errors.push("memory summary loop diagnostics are not ok");
  }
  requireGate(errors, "readiness", report.gates.readiness, policy.requireReadiness ?? false);
  requireGate(errors, "source evidence", report.gates.sourceEvidence, policy.requireSourceEvidence ?? false);
  requireGate(errors, "outbox drain", report.gates.outboxDrain, policy.requireOutboxDrain ?? false);
  requireGate(errors, "quality", report.gates.quality, policy.requireQuality ?? false);
  if ((policy.failOnWarnings ?? false) && warnings.length > 0) {
    errors.push(`memory summary loop returned ${warnings.length} warning(s)`);
  }

  if (policy.minSourceEvidenceSuccessRate !== undefined) {
    if (report.sourceEvidence === undefined) {
      errors.push("source evidence summary is required for success rate policy");
    } else if (report.sourceEvidence.successRate < policy.minSourceEvidenceSuccessRate) {
      errors.push(
        `source evidence success rate ${report.sourceEvidence.successRate}, expected at least ${policy.minSourceEvidenceSuccessRate}`,
      );
    }
  }
  if (policy.maxSourceEvidenceFailures !== undefined && report.sourceEvidence !== undefined) {
    if (report.sourceEvidence.failed > policy.maxSourceEvidenceFailures) {
      errors.push(
        `source evidence failed ${report.sourceEvidence.failed} item(s), expected at most ${policy.maxSourceEvidenceFailures}`,
      );
    }
  }

  minimumCount(errors, "context items", report.summary.contextItems, policy.minContextItems);
  minimumCount(errors, "search items", report.summary.searchItems, policy.minSearchItems);
  minimumCount(errors, "digest sections", report.summary.digestSections, policy.minDigestSections);
  minimumCount(errors, "top evidence items", report.summary.topEvidenceItems, policy.minTopEvidenceItems);
  minimumCount(errors, "unique source refs", report.summary.uniqueSourceRefs, policy.minUniqueSourceRefs);
  minimumCount(errors, "citations", report.summary.citationsTotal, policy.minCitations);

  for (const sourceType of policy.requiredSourceEvidenceTypes ?? []) {
    if ((report.sourceEvidence?.bySourceType[sourceType] ?? 0) <= 0) {
      errors.push(`source evidence did not include source type ${sourceType}`);
    }
  }
  for (const sourceType of policy.requiredEvidenceSourceTypes ?? []) {
    if ((report.summary.bySourceType[sourceType] ?? 0) <= 0) {
      errors.push(`summary evidence did not include source type ${sourceType}`);
    }
  }

  if ((policy.requireDerivedRetrieval ?? false) && !report.retrieval.derivedRetrievalUsed) {
    errors.push("derived retrieval was not used");
  }
  for (const component of policy.requiredRetrieval ?? []) {
    if (!memoryBriefRetrievalHealthy(report.retrieval, component)) {
      errors.push(`${component} retrieval is not healthy`);
    }
  }

  return {
    ok: errors.length === 0,
    errors: uniqueStrings(errors),
    warnings,
    policy,
    report,
  };
}

export function assertMemorySummaryLoopPolicy(
  input: RunMemorySummaryLoopResult | MemorySummaryLoopReport,
  policy: MemorySummaryLoopPolicy = {},
): MemorySummaryLoopPolicyEvaluation {
  const evaluation = evaluateMemorySummaryLoopPolicy(input, policy);
  if (evaluation.ok) {
    return evaluation;
  }

  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.summary_loop_policy_failed",
    message: `Memory summary loop policy failed: ${evaluation.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: evaluation.errors,
      warnings: evaluation.warnings,
      policy: evaluation.policy as unknown as JsonObject,
      report: {
        status: evaluation.report.status,
        gates: evaluation.report.gates as unknown as JsonObject,
        source_evidence: evaluation.report.sourceEvidence as unknown as JsonObject,
        summary: evaluation.report.summary as unknown as JsonObject,
        retrieval: {
          derived_retrieval_used: evaluation.report.retrieval.derivedRetrievalUsed,
          vector_healthy: evaluation.report.retrieval.vectorHealthy,
          graph_healthy: evaluation.report.retrieval.graphHealthy,
          rag_healthy: evaluation.report.retrieval.ragHealthy,
          retrieval_sources_used: evaluation.report.retrieval.retrievalSourcesUsed,
        },
      },
    } satisfies JsonObject,
  });
}

function memorySummaryLoopReport(
  input: RunMemorySummaryLoopResult | MemorySummaryLoopReport,
): MemorySummaryLoopReport {
  return "gates" in input && "summary" in input && "retrieval" in input
    ? input
    : summarizeMemorySummaryLoop(input);
}

function requireGate(
  errors: string[],
  name: string,
  gate: MemorySummaryLoopGateReport,
  required: boolean,
): void {
  if (required && gate.status === "skipped") {
    errors.push(`${name} gate is required`);
  }
  if (gate.status === "failed" && gate.errors.length === 0) {
    errors.push(`${name} gate failed`);
  }
}

function minimumCount(
  errors: string[],
  name: string,
  actual: number,
  minimum: number | undefined,
): void {
  if (minimum !== undefined && actual < minimum) {
    errors.push(`${name} ${actual}, expected at least ${minimum}`);
  }
}

function loopStatus(loop: RunMemorySummaryLoopResult, errors: readonly string[]): MemorySummaryLoopStatus {
  if (!loop.diagnostics.ok || errors.length > 0) {
    return "failed";
  }
  return loop.diagnostics.warnings.length > 0 || loop.evidenceSummary.warnings.length > 0 ? "degraded" : "ready";
}

function gateReport(
  ok: boolean | null,
  errors: readonly string[] = [],
  warnings: readonly string[] = [],
): MemorySummaryLoopGateReport {
  return {
    ok,
    status: ok === null ? "skipped" : ok ? "passed" : "failed",
    errors,
    warnings,
  };
}

function sourceEvidenceReport(summary: RecordSourceEvidenceBatchSummary): MemorySummaryLoopSourceEvidenceReport {
  return {
    total: summary.total,
    completed: summary.completed,
    skipped: summary.skipped,
    succeeded: summary.succeeded,
    failed: summary.failed,
    successRate: summary.successRate,
    retryableFailures: summary.retryableFailures,
    nonRetryableFailures: summary.nonRetryableFailures,
    bySourceType: summary.bySourceType,
  };
}

function sourceEvidenceErrors(summary: RecordSourceEvidenceBatchSummary | undefined): readonly string[] {
  if (summary === undefined || (summary.failed === 0 && !summary.stopped)) {
    return [];
  }

  return [
    `source evidence batch failed ${summary.failed} item(s), skipped ${summary.skipped} item(s)`,
  ];
}

function outboxDrainErrors(loop: RunMemorySummaryLoopResult): readonly string[] {
  const outbox = loop.outboxDrain;
  if (outbox === undefined || loop.diagnostics.outboxDrainOk !== false) {
    return [];
  }

  return [
    `outbox still has ${outbox.diagnostics.blocking_count} blocking item(s) after ${outbox.diagnostics.attempts} attempt(s)`,
  ];
}

function readableSummary(loop: RunMemorySummaryLoopResult): MemorySummaryLoopReadableSummary {
  return {
    contextItems: loop.evidenceSummary.contextItems,
    searchItems: loop.evidenceSummary.searchItems,
    digestSections: loop.evidenceSummary.digestSections,
    topEvidenceItems: loop.evidenceSummary.topEvidenceItems,
    sourceRefsTotal: loop.evidenceSummary.sourceRefsTotal,
    uniqueSourceRefs: loop.evidenceSummary.uniqueSourceRefs,
    citationsTotal: loop.evidenceSummary.citationsTotal,
    uniqueCitations: loop.evidenceSummary.uniqueCitations,
    bySourceType: loop.evidenceSummary.bySourceType,
    renderedText: loop.brief.context.data.rendered_text,
    ...(loop.brief.digest ? { renderedMarkdown: loop.brief.digest.data.rendered_markdown } : {}),
  };
}
