import { createInfinityContextError, InfinityContextError } from "../errors.js";
import type { JsonObject } from "../types.js";
import type {
  MemorySnapshotTransferMode,
  TransferMemorySnapshotResult,
} from "./memory-snapshot-transfer.js";
import { uniqueStrings } from "./workflow-helpers.js";

export type MemorySnapshotTransferStatus = "safe" | "review_required" | "mutated" | "failed";

export interface MemorySnapshotTransferCounts {
  readonly facts: number;
  readonly episodes: number;
  readonly documents: number;
  readonly chunks: number;
  readonly captures: number;
  readonly anchors: number;
  readonly contextLinks: number;
}

export interface MemorySnapshotTransferReport {
  readonly ok: boolean;
  readonly status: MemorySnapshotTransferStatus;
  readonly mode: MemorySnapshotTransferMode;
  readonly mutated: boolean;
  readonly redacted: boolean;
  readonly mergeStrategy: string;
  readonly sameScope: boolean;
  readonly hasManifest: boolean;
  readonly hasPreview: boolean;
  readonly hasImportResult: boolean;
  readonly counts: MemorySnapshotTransferCounts;
  readonly warnings: readonly string[];
  readonly errors: readonly string[];
}

export interface MemorySnapshotTransferPolicy {
  readonly allowedModes?: readonly MemorySnapshotTransferMode[];
  readonly forbidMutation?: boolean;
  readonly requireMutation?: boolean;
  readonly requireRedacted?: boolean;
  readonly forbidSameScope?: boolean;
  readonly requireManifest?: boolean;
  readonly requirePreview?: boolean;
  readonly requireImportResult?: boolean;
  readonly failOnWarnings?: boolean;
  readonly maxWarnings?: number;
  readonly minFacts?: number;
  readonly minDocuments?: number;
  readonly minAnchors?: number;
  readonly requiredMergeStrategy?: string;
}

export interface MemorySnapshotTransferPolicyEvaluation {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly policy: MemorySnapshotTransferPolicy;
  readonly report: MemorySnapshotTransferReport;
}

export function summarizeMemorySnapshotTransfer(
  result: TransferMemorySnapshotResult,
): MemorySnapshotTransferReport {
  const warnings = uniqueStrings(result.diagnostics.warnings);
  const sameScope = result.source.spaceSlug === result.target.spaceSlug &&
    result.source.memoryScopeExternalRef === result.target.memoryScopeExternalRef;
  const errors = uniqueStrings([
    ...(result.diagnostics.mode === "preview" && result.preview === undefined ? ["preview result is missing"] : []),
    ...(result.diagnostics.mode === "confirmed_import" && result.importResult === undefined
      ? ["import result is missing"]
      : []),
  ]);

  return {
    ok: errors.length === 0,
    status: snapshotTransferStatus(result, sameScope, errors),
    mode: result.diagnostics.mode,
    mutated: result.diagnostics.mutated,
    redacted: result.diagnostics.redacted,
    mergeStrategy: result.diagnostics.mergeStrategy,
    sameScope,
    hasManifest: result.manifest !== undefined,
    hasPreview: result.preview !== undefined,
    hasImportResult: result.importResult !== undefined,
    counts: snapshotCounts(result.snapshot),
    warnings,
    errors,
  };
}

export function evaluateMemorySnapshotTransferPolicy(
  input: TransferMemorySnapshotResult | MemorySnapshotTransferReport,
  policy: MemorySnapshotTransferPolicy = {},
): MemorySnapshotTransferPolicyEvaluation {
  const report = snapshotTransferReport(input);
  const errors: string[] = [...report.errors];

  if (policy.allowedModes !== undefined && !policy.allowedModes.includes(report.mode)) {
    errors.push(`snapshot transfer mode ${report.mode} is not allowed`);
  }
  if ((policy.forbidMutation ?? false) && report.mutated) {
    errors.push("snapshot transfer mutated target memory");
  }
  if ((policy.requireMutation ?? false) && !report.mutated) {
    errors.push("snapshot transfer did not mutate target memory");
  }
  if ((policy.requireRedacted ?? false) && !report.redacted) {
    errors.push("snapshot transfer used an unredacted snapshot");
  }
  if ((policy.forbidSameScope ?? false) && report.sameScope) {
    errors.push("snapshot transfer source and target are the same scope");
  }
  if ((policy.requireManifest ?? false) && !report.hasManifest) {
    errors.push("snapshot transfer manifest is required");
  }
  if ((policy.requirePreview ?? false) && !report.hasPreview) {
    errors.push("snapshot transfer preview is required");
  }
  if ((policy.requireImportResult ?? false) && !report.hasImportResult) {
    errors.push("snapshot transfer import result is required");
  }
  if ((policy.failOnWarnings ?? false) && report.warnings.length > 0) {
    errors.push(`snapshot transfer returned ${report.warnings.length} warning(s)`);
  }
  maximumCount(errors, "snapshot transfer warnings", report.warnings.length, policy.maxWarnings);
  minimumCount(errors, "snapshot facts", report.counts.facts, policy.minFacts);
  minimumCount(errors, "snapshot documents", report.counts.documents, policy.minDocuments);
  minimumCount(errors, "snapshot anchors", report.counts.anchors, policy.minAnchors);
  if (policy.requiredMergeStrategy !== undefined && report.mergeStrategy !== policy.requiredMergeStrategy) {
    errors.push(`snapshot merge strategy ${report.mergeStrategy}, expected ${policy.requiredMergeStrategy}`);
  }

  return {
    ok: errors.length === 0,
    errors: uniqueStrings(errors),
    warnings: report.warnings,
    policy,
    report,
  };
}

export function assertMemorySnapshotTransferPolicy(
  input: TransferMemorySnapshotResult | MemorySnapshotTransferReport,
  policy: MemorySnapshotTransferPolicy = {},
): MemorySnapshotTransferPolicyEvaluation {
  const evaluation = evaluateMemorySnapshotTransferPolicy(input, policy);
  if (evaluation.ok) {
    return evaluation;
  }

  throw createInfinityContextError({
    statusCode: 0,
    code: "memory.snapshot_transfer_policy_failed",
    message: `Memory snapshot transfer policy failed: ${evaluation.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: evaluation.errors,
      warnings: evaluation.warnings,
      policy: evaluation.policy as unknown as JsonObject,
      report: {
        status: evaluation.report.status,
        mode: evaluation.report.mode,
        mutated: evaluation.report.mutated,
        redacted: evaluation.report.redacted,
        merge_strategy: evaluation.report.mergeStrategy,
        same_scope: evaluation.report.sameScope,
        counts: evaluation.report.counts as unknown as JsonObject,
      },
    } satisfies JsonObject,
  });
}

function snapshotTransferReport(
  input: TransferMemorySnapshotResult | MemorySnapshotTransferReport,
): MemorySnapshotTransferReport {
  return "sameScope" in input && "counts" in input && "hasPreview" in input
    ? input
    : summarizeMemorySnapshotTransfer(input);
}

function snapshotTransferStatus(
  result: TransferMemorySnapshotResult,
  sameScope: boolean,
  errors: readonly string[],
): MemorySnapshotTransferStatus {
  if (errors.length > 0) {
    return "failed";
  }
  if (result.diagnostics.mutated) {
    return "mutated";
  }
  return sameScope || result.diagnostics.warnings.length > 0 ? "review_required" : "safe";
}

function snapshotCounts(snapshot: JsonObject): MemorySnapshotTransferCounts {
  return {
    facts: arrayLength(snapshot.facts),
    episodes: arrayLength(snapshot.episodes),
    documents: arrayLength(snapshot.documents),
    chunks: arrayLength(snapshot.chunks),
    captures: arrayLength(snapshot.captures),
    anchors: arrayLength(snapshot.anchors),
    contextLinks: arrayLength(snapshot.context_links),
  };
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
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
