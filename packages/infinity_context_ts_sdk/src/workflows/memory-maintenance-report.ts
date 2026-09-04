import { createInfinityContextError, InfinityContextError } from "../errors.js";
import type { JsonObject } from "../types.js";
import type { InspectMemoryIssue } from "./memory-inspection.js";
import type {
  MemoryMaintenanceAction,
  MemoryMaintenanceActionKind,
  PlanMemoryMaintenanceResult,
} from "./memory-maintenance.js";
import { uniqueStrings } from "./workflow-helpers.js";

export type MemoryMaintenanceStatus = "clean" | "action_required" | "failed";

export interface MemoryMaintenanceActionSummary {
  readonly total: number;
  readonly high: number;
  readonly medium: number;
  readonly low: number;
  readonly byKind: Readonly<Record<MemoryMaintenanceActionKind, number>>;
}

export interface MemoryMaintenanceReport {
  readonly ok: boolean;
  readonly status: MemoryMaintenanceStatus;
  readonly totalActionable: number;
  readonly counts: {
    readonly contextLinkSuggestions: number;
    readonly memorySuggestions: number;
    readonly anchorMergeCandidates: number;
    readonly capturesPendingConsolidation: number;
    readonly extractionJobs: number;
  };
  readonly actions: MemoryMaintenanceActionSummary;
  readonly suggestedActions: readonly MemoryMaintenanceAction[];
  readonly partial: boolean;
  readonly optionalSections: readonly string[];
  readonly issues: readonly InspectMemoryIssue[];
  readonly errors: readonly string[];
}

export interface MemoryMaintenancePolicy {
  readonly requireComplete?: boolean;
  readonly maxIssues?: number;
  readonly maxTotalActionable?: number;
  readonly maxHighPriorityActions?: number;
  readonly maxMediumPriorityActions?: number;
  readonly maxLowPriorityActions?: number;
  readonly maxContextLinkSuggestions?: number;
  readonly maxMemorySuggestions?: number;
  readonly maxAnchorMergeCandidates?: number;
  readonly maxCapturesPendingConsolidation?: number;
  readonly maxExtractionJobs?: number;
  readonly blockedActionKinds?: readonly MemoryMaintenanceActionKind[];
}

export interface MemoryMaintenancePolicyEvaluation {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly policy: MemoryMaintenancePolicy;
  readonly report: MemoryMaintenanceReport;
}

const ACTION_KINDS = [
  "review_context_links",
  "resolve_memory_suggestions",
  "merge_duplicate_anchors",
  "consolidate_captures",
  "retry_or_triage_extractions",
] as const satisfies readonly MemoryMaintenanceActionKind[];

export function summarizeMemoryMaintenance(plan: PlanMemoryMaintenanceResult): MemoryMaintenanceReport {
  const errors = uniqueStrings(plan.diagnostics.issues.map((issue) =>
    `${issue.section}: ${issue.error.message}`,
  ));
  const actions = maintenanceActionSummary(plan.summary.suggestedActions);

  return {
    ok: !plan.diagnostics.partial,
    status: maintenanceStatus(plan, errors),
    totalActionable: plan.summary.totalActionable,
    counts: {
      contextLinkSuggestions: plan.summary.contextLinkSuggestions,
      memorySuggestions: plan.summary.memorySuggestions,
      anchorMergeCandidates: plan.summary.anchorMergeCandidates,
      capturesPendingConsolidation: plan.summary.capturesPendingConsolidation,
      extractionJobs: plan.summary.extractionJobs,
    },
    actions,
    suggestedActions: plan.summary.suggestedActions,
    partial: plan.diagnostics.partial,
    optionalSections: plan.diagnostics.optionalSections,
    issues: plan.diagnostics.issues,
    errors,
  };
}

export function evaluateMemoryMaintenancePolicy(
  input: PlanMemoryMaintenanceResult | MemoryMaintenanceReport,
  policy: MemoryMaintenancePolicy = {},
): MemoryMaintenancePolicyEvaluation {
  const report = memoryMaintenanceReport(input);
  const errors: string[] = [...report.errors];

  if ((policy.requireComplete ?? false) && report.partial) {
    errors.push("memory maintenance plan is partial");
  }
  if (policy.maxIssues !== undefined && report.issues.length > policy.maxIssues) {
    errors.push(`memory maintenance returned ${report.issues.length} issue(s), expected at most ${policy.maxIssues}`);
  }
  maximumCount(errors, "total actionable maintenance items", report.totalActionable, policy.maxTotalActionable);
  maximumCount(errors, "high priority maintenance actions", report.actions.high, policy.maxHighPriorityActions);
  maximumCount(errors, "medium priority maintenance actions", report.actions.medium, policy.maxMediumPriorityActions);
  maximumCount(errors, "low priority maintenance actions", report.actions.low, policy.maxLowPriorityActions);
  maximumCount(
    errors,
    "context link suggestions",
    report.counts.contextLinkSuggestions,
    policy.maxContextLinkSuggestions,
  );
  maximumCount(errors, "memory suggestions", report.counts.memorySuggestions, policy.maxMemorySuggestions);
  maximumCount(errors, "anchor merge candidates", report.counts.anchorMergeCandidates, policy.maxAnchorMergeCandidates);
  maximumCount(
    errors,
    "captures pending consolidation",
    report.counts.capturesPendingConsolidation,
    policy.maxCapturesPendingConsolidation,
  );
  maximumCount(errors, "extraction jobs", report.counts.extractionJobs, policy.maxExtractionJobs);

  for (const kind of policy.blockedActionKinds ?? []) {
    const count = report.actions.byKind[kind] ?? 0;
    if (count > 0) {
      errors.push(`maintenance action ${kind} has ${count} item(s)`);
    }
  }

  return {
    ok: errors.length === 0,
    errors: uniqueStrings(errors),
    policy,
    report,
  };
}

export function assertMemoryMaintenancePolicy(
  input: PlanMemoryMaintenanceResult | MemoryMaintenanceReport,
  policy: MemoryMaintenancePolicy = {},
): MemoryMaintenancePolicyEvaluation {
  const evaluation = evaluateMemoryMaintenancePolicy(input, policy);
  if (evaluation.ok) {
    return evaluation;
  }

  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.maintenance_policy_failed",
    message: `Memory maintenance policy failed: ${evaluation.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: evaluation.errors,
      policy: evaluation.policy as unknown as JsonObject,
      report: {
        status: evaluation.report.status,
        total_actionable: evaluation.report.totalActionable,
        counts: evaluation.report.counts as unknown as JsonObject,
        actions: evaluation.report.actions as unknown as JsonObject,
        partial: evaluation.report.partial,
      },
    } satisfies JsonObject,
  });
}

function memoryMaintenanceReport(
  input: PlanMemoryMaintenanceResult | MemoryMaintenanceReport,
): MemoryMaintenanceReport {
  return "actions" in input && "totalActionable" in input && "partial" in input
    ? input
    : summarizeMemoryMaintenance(input);
}

function maintenanceStatus(
  plan: PlanMemoryMaintenanceResult,
  errors: readonly string[],
): MemoryMaintenanceStatus {
  if (plan.diagnostics.partial || errors.length > 0) {
    return "failed";
  }
  return plan.summary.totalActionable > 0 ? "action_required" : "clean";
}

function maintenanceActionSummary(
  actions: readonly MemoryMaintenanceAction[],
): MemoryMaintenanceActionSummary {
  const byKind = Object.fromEntries(ACTION_KINDS.map((kind) => [kind, 0])) as Record<MemoryMaintenanceActionKind, number>;
  let high = 0;
  let medium = 0;
  let low = 0;

  for (const action of actions) {
    byKind[action.kind] += action.count;
    if (action.priority === "high") {
      high += 1;
    } else if (action.priority === "medium") {
      medium += 1;
    } else {
      low += 1;
    }
  }

  return {
    total: actions.length,
    high,
    medium,
    low,
    byKind,
  };
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
