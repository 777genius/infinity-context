import { createInfinityContextError, InfinityContextError } from "../errors.js";
import type { JsonObject } from "../types.js";
import type {
  InspectMemoryIssue,
  InspectMemoryResult,
} from "./memory-inspection.js";
import { uniqueStrings } from "./workflow-helpers.js";

export type MemoryInspectionStatus = "ready" | "degraded" | "failed";
export type MemoryInspectionSection =
  | "memoryBrowser"
  | "operationsConsole"
  | "usage"
  | "capabilities"
  | "runtimeDiagnostics"
  | "graph"
  | "snapshot"
  | "snapshotPreview";
export type MemoryInspectionSectionStatus = "present" | "missing" | "failed" | "skipped";

export interface MemoryInspectionSectionReport {
  readonly status: MemoryInspectionSectionStatus;
  readonly present: boolean;
  readonly issues: readonly InspectMemoryIssue[];
}

export interface MemoryInspectionCounts {
  readonly facts: number;
  readonly episodes: number;
  readonly documents: number;
  readonly chunks: number;
  readonly extractionJobs: number;
  readonly threads: number;
  readonly captures: number;
  readonly assets: number;
  readonly anchors: number;
  readonly contextLinks: number;
  readonly contextLinkSuggestions: number;
  readonly operationExtractionJobs: number;
  readonly operationContextLinkSuggestions: number;
}

export interface MemoryInspectionRuntimeSummary {
  readonly enabledAdapters: readonly string[];
  readonly supportsQdrant: boolean | null;
  readonly supportsGraphiti: boolean | null;
  readonly diagnosticsSections: readonly string[];
}

export interface MemoryInspectionReport {
  readonly ok: boolean;
  readonly status: MemoryInspectionStatus;
  readonly sections: Readonly<Record<MemoryInspectionSection, MemoryInspectionSectionReport>>;
  readonly counts: MemoryInspectionCounts;
  readonly runtime: MemoryInspectionRuntimeSummary;
  readonly optionalSections: readonly string[];
  readonly warnings: readonly string[];
  readonly issues: readonly InspectMemoryIssue[];
  readonly errors: readonly string[];
}

export interface MemoryInspectionPolicy {
  readonly requireComplete?: boolean;
  readonly failOnWarnings?: boolean;
  readonly maxIssues?: number;
  readonly requiredSections?: readonly MemoryInspectionSection[];
  readonly requiredAdapters?: readonly string[];
  readonly minFacts?: number;
  readonly minDocuments?: number;
  readonly minAnchors?: number;
  readonly minContextLinks?: number;
  readonly maxOperationExtractionJobs?: number;
  readonly maxOperationContextLinkSuggestions?: number;
}

export interface MemoryInspectionPolicyEvaluation {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly policy: MemoryInspectionPolicy;
  readonly report: MemoryInspectionReport;
}

const INSPECTION_SECTIONS = [
  "memoryBrowser",
  "operationsConsole",
  "usage",
  "capabilities",
  "runtimeDiagnostics",
  "graph",
  "snapshot",
  "snapshotPreview",
] as const satisfies readonly MemoryInspectionSection[];

export function summarizeMemoryInspection(inspection: InspectMemoryResult): MemoryInspectionReport {
  const sections = inspectionSections(inspection);
  const errors = uniqueStrings(inspection.inspection.issues.map((issue) =>
    `${issue.section}: ${issue.error.message}`,
  ));
  const warnings = uniqueStrings(inspection.inspection.warnings);

  return {
    ok: inspection.inspection.issues.length === 0,
    status: inspectionStatus(sections, warnings),
    sections,
    counts: inspectionCounts(inspection),
    runtime: inspectionRuntimeSummary(inspection),
    optionalSections: inspection.inspection.optionalSections,
    warnings,
    issues: inspection.inspection.issues,
    errors,
  };
}

export function evaluateMemoryInspectionPolicy(
  input: InspectMemoryResult | MemoryInspectionReport,
  policy: MemoryInspectionPolicy = {},
): MemoryInspectionPolicyEvaluation {
  const report = memoryInspectionReport(input);
  const errors: string[] = [...report.errors];
  const warnings = [...report.warnings];

  if (!report.ok && errors.length === 0) {
    errors.push("memory inspection is not ok");
  }
  if ((policy.requireComplete ?? false)) {
    for (const section of report.optionalSections) {
      const normalized = inspectionSection(section);
      if (normalized !== undefined) {
        requireSection(errors, normalized, report.sections[normalized]);
      }
    }
  }
  if ((policy.failOnWarnings ?? false) && warnings.length > 0) {
    errors.push(`memory inspection returned ${warnings.length} warning(s)`);
  }
  if (policy.maxIssues !== undefined && report.issues.length > policy.maxIssues) {
    errors.push(`memory inspection returned ${report.issues.length} issue(s), expected at most ${policy.maxIssues}`);
  }
  for (const section of policy.requiredSections ?? []) {
    requireSection(errors, section, report.sections[section]);
  }
  for (const adapter of policy.requiredAdapters ?? []) {
    if (!report.runtime.enabledAdapters.includes(adapter)) {
      errors.push(`runtime adapter ${adapter} is not enabled`);
    }
  }

  minimumCount(errors, "facts", report.counts.facts, policy.minFacts);
  minimumCount(errors, "documents", report.counts.documents, policy.minDocuments);
  minimumCount(errors, "anchors", report.counts.anchors, policy.minAnchors);
  minimumCount(errors, "context links", report.counts.contextLinks, policy.minContextLinks);
  maximumCount(
    errors,
    "operation extraction jobs",
    report.counts.operationExtractionJobs,
    policy.maxOperationExtractionJobs,
  );
  maximumCount(
    errors,
    "operation context link suggestions",
    report.counts.operationContextLinkSuggestions,
    policy.maxOperationContextLinkSuggestions,
  );

  return {
    ok: errors.length === 0,
    errors: uniqueStrings(errors),
    warnings,
    policy,
    report,
  };
}

export function assertMemoryInspectionPolicy(
  input: InspectMemoryResult | MemoryInspectionReport,
  policy: MemoryInspectionPolicy = {},
): MemoryInspectionPolicyEvaluation {
  const evaluation = evaluateMemoryInspectionPolicy(input, policy);
  if (evaluation.ok) {
    return evaluation;
  }

  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.inspection_policy_failed",
    message: `Memory inspection policy failed: ${evaluation.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: evaluation.errors,
      warnings: evaluation.warnings,
      policy: evaluation.policy as unknown as JsonObject,
      report: {
        status: evaluation.report.status,
        sections: evaluation.report.sections as unknown as JsonObject,
        counts: evaluation.report.counts as unknown as JsonObject,
        runtime: evaluation.report.runtime as unknown as JsonObject,
      },
    } satisfies JsonObject,
  });
}

function memoryInspectionReport(input: InspectMemoryResult | MemoryInspectionReport): MemoryInspectionReport {
  return "sections" in input && "counts" in input && "runtime" in input
    ? input
    : summarizeMemoryInspection(input);
}

function inspectionSections(
  inspection: InspectMemoryResult,
): Readonly<Record<MemoryInspectionSection, MemoryInspectionSectionReport>> {
  return Object.fromEntries(INSPECTION_SECTIONS.map((section) => [
    section,
    sectionReport(section, sectionPresent(section, inspection), inspection),
  ])) as Readonly<Record<MemoryInspectionSection, MemoryInspectionSectionReport>>;
}

function sectionReport(
  section: MemoryInspectionSection,
  present: boolean,
  inspection: InspectMemoryResult,
): MemoryInspectionSectionReport {
  const issues = inspection.inspection.issues.filter((issue) => issueBelongsToSection(issue, section));
  const enabled = inspection.inspection.optionalSections.includes(section);
  const status = issues.length > 0
    ? "failed"
    : present
      ? "present"
      : enabled
        ? "missing"
        : "skipped";

  return {
    status,
    present,
    issues,
  };
}

function sectionPresent(section: MemoryInspectionSection, inspection: InspectMemoryResult): boolean {
  if (section === "memoryBrowser") {
    return inspection.memoryBrowser !== undefined;
  }
  if (section === "operationsConsole") {
    return inspection.operationsConsole !== undefined;
  }
  if (section === "usage") {
    return inspection.usage !== undefined;
  }
  if (section === "capabilities") {
    return inspection.capabilities !== undefined;
  }
  if (section === "runtimeDiagnostics") {
    return inspection.runtimeDiagnostics !== undefined;
  }
  if (section === "graph") {
    return inspection.graph !== undefined;
  }
  if (section === "snapshot") {
    return inspection.snapshot !== undefined;
  }
  return inspection.snapshotPreview !== undefined;
}

function issueBelongsToSection(issue: InspectMemoryIssue, section: MemoryInspectionSection): boolean {
  if (section === "runtimeDiagnostics") {
    return issue.section === section || issue.section.startsWith("diagnostics.");
  }
  return issue.section === section;
}

function inspectionStatus(
  sections: Readonly<Record<MemoryInspectionSection, MemoryInspectionSectionReport>>,
  warnings: readonly string[],
): MemoryInspectionStatus {
  if (INSPECTION_SECTIONS.some((section) => sections[section].status === "failed")) {
    return "failed";
  }
  if (warnings.length > 0 || INSPECTION_SECTIONS.some((section) => sections[section].status === "missing")) {
    return "degraded";
  }
  return "ready";
}

function inspectionCounts(inspection: InspectMemoryResult): MemoryInspectionCounts {
  const browser = inspection.memoryBrowser.data;
  const operations = inspection.operationsConsole?.data;
  return {
    facts: browser.facts.length,
    episodes: browser.episodes.length,
    documents: browser.documents.length,
    chunks: browser.chunks.length,
    extractionJobs: browser.extraction_jobs.length,
    threads: browser.threads.length,
    captures: browser.captures.length,
    assets: browser.assets.length,
    anchors: browser.anchors.length,
    contextLinks: browser.context_links.length,
    contextLinkSuggestions: browser.context_link_suggestions.length,
    operationExtractionJobs: operations?.extraction_jobs.length ?? 0,
    operationContextLinkSuggestions: operations?.context_link_suggestions.length ?? 0,
  };
}

function inspectionRuntimeSummary(inspection: InspectMemoryResult): MemoryInspectionRuntimeSummary {
  const runtimeDiagnostics = inspection.runtimeDiagnostics;
  return {
    enabledAdapters: inspection.capabilities?.enabled_adapters ?? [],
    supportsQdrant: inspection.capabilities?.supports_qdrant ?? null,
    supportsGraphiti: inspection.capabilities?.supports_graphiti ?? null,
    diagnosticsSections: runtimeDiagnostics === undefined
      ? []
      : Object.entries(runtimeDiagnostics)
        .filter(([, value]) => value !== undefined)
        .map(([key]) => key)
        .sort(),
  };
}

function inspectionSection(section: string): MemoryInspectionSection | undefined {
  return (INSPECTION_SECTIONS as readonly string[]).includes(section)
    ? section as MemoryInspectionSection
    : undefined;
}

function requireSection(
  errors: string[],
  section: MemoryInspectionSection,
  report: MemoryInspectionSectionReport,
): void {
  if (report.status !== "present") {
    errors.push(`inspection section ${section} is ${report.status}`);
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

function maximumCount(
  errors: string[],
  name: string,
  actual: number,
  maximum: number | undefined,
): void {
  if (maximum !== undefined && actual > maximum) {
    errors.push(`${name} ${actual}, expected at most ${maximum}`);
  }
}
