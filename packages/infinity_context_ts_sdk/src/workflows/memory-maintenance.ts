import type { RequestControls } from "../client.js";
import { ValueError, type SingleScopeInput } from "../payload.js";
import type { AnchorsClient, AnchorMergeCandidate } from "../resources/anchors.js";
import type { AssetsClient } from "../resources/assets.js";
import type { CapturesClient } from "../resources/captures.js";
import type { ContextLinksClient } from "../resources/context-links.js";
import type { OperationsConsoleData, ReadModelsClient } from "../resources/read-models.js";
import type { SuggestionsClient } from "../resources/suggestions.js";
import type {
  ApiEnvelope,
  AssetExtractionJobRecord,
  CaptureRecord,
  ContextLinkSuggestionRecord,
  SuggestionRecord,
} from "../types.js";
import {
  isDefined,
  optional,
  singleScopeInput,
  workflowControls,
} from "./workflow-helpers.js";
import {
  memoryBrowserScopeInput,
  optionalInspectionSection,
  type InspectMemoryIssue,
} from "./memory-inspection.js";

export interface MemoryMaintenanceResourceOptions {
  readonly anchors?: AnchorsClient;
  readonly assets?: AssetsClient;
  readonly captures: CapturesClient;
  readonly contextLinks: ContextLinksClient;
  readonly readModels?: ReadModelsClient;
  readonly suggestions?: SuggestionsClient;
}

interface MemoryMaintenanceResources {
  readonly anchors: AnchorsClient;
  readonly assets: AssetsClient;
  readonly captures: CapturesClient;
  readonly contextLinks: ContextLinksClient;
  readonly readModels: ReadModelsClient;
  readonly suggestions: SuggestionsClient;
}

export interface PlanMemoryMaintenanceInput extends SingleScopeInput, RequestControls {
  readonly limit?: number;
  readonly continueOnError?: boolean;
  readonly includeOperations?: boolean;
  readonly includeContextLinkSuggestions?: boolean;
  readonly includeMemorySuggestions?: boolean;
  readonly includeAnchorMergeCandidates?: boolean;
  readonly includeCaptureDiagnostics?: boolean;
  readonly includeExtractionJobs?: boolean;
  readonly contextLinkSuggestionStatus?: string | null;
  readonly memorySuggestionStatus?: string | null;
  readonly captureConsolidationStatus?: string | null;
  readonly extractionStatus?: string | null;
  readonly anchorKind?: string;
}

export interface MemoryMaintenanceQueues {
  readonly operationsConsole?: ApiEnvelope<OperationsConsoleData>;
  readonly contextLinkSuggestions?: ApiEnvelope<ContextLinkSuggestionRecord[]>;
  readonly memorySuggestions?: ApiEnvelope<SuggestionRecord[]>;
  readonly anchorMergeCandidates?: ApiEnvelope<AnchorMergeCandidate[]>;
  readonly captureDiagnostics?: ApiEnvelope<CaptureRecord[]>;
  readonly extractionJobs?: ApiEnvelope<AssetExtractionJobRecord[]>;
}

export type MemoryMaintenanceActionKind =
  | "review_context_links"
  | "resolve_memory_suggestions"
  | "merge_duplicate_anchors"
  | "consolidate_captures"
  | "retry_or_triage_extractions";

export interface MemoryMaintenanceAction {
  readonly kind: MemoryMaintenanceActionKind;
  readonly priority: "low" | "medium" | "high";
  readonly count: number;
  readonly reason: string;
}

export interface MemoryMaintenanceSummary {
  readonly totalActionable: number;
  readonly contextLinkSuggestions: number;
  readonly memorySuggestions: number;
  readonly anchorMergeCandidates: number;
  readonly capturesPendingConsolidation: number;
  readonly extractionJobs: number;
  readonly suggestedActions: readonly MemoryMaintenanceAction[];
}

export interface MemoryMaintenanceDiagnostics {
  readonly partial: boolean;
  readonly issues: readonly InspectMemoryIssue[];
  readonly optionalSections: readonly string[];
}

export interface PlanMemoryMaintenanceResult {
  readonly queues: MemoryMaintenanceQueues;
  readonly summary: MemoryMaintenanceSummary;
  readonly diagnostics: MemoryMaintenanceDiagnostics;
}

export async function planMemoryMaintenance(
  resourceOptions: MemoryMaintenanceResourceOptions,
  input: PlanMemoryMaintenanceInput = {},
): Promise<PlanMemoryMaintenanceResult> {
  const resources = maintenanceResources(resourceOptions);
  const controls = workflowControls(input);
  const issues: InspectMemoryIssue[] = [];
  const continueOnError = input.continueOnError ?? false;
  const optionalSections = enabledMaintenanceSections(input);
  const limit = input.limit ?? 50;

  const [
    operationsConsole,
    contextLinkSuggestions,
    memorySuggestions,
    anchorMergeCandidates,
    captureDiagnostics,
    extractionJobs,
  ] = await Promise.all([
    optionalInspectionSection("operationsConsole", continueOnError, issues, () =>
      resources.readModels.getOperationsConsole({
        ...singleScopeInput(input),
        ...controls,
        limit,
      }),
    input.includeOperations ?? true),
    optionalInspectionSection("contextLinkSuggestions", continueOnError, issues, () =>
      resources.contextLinks.listContextLinkSuggestions({
        ...singleScopeInput(input),
        ...controls,
        status: input.contextLinkSuggestionStatus === undefined ? "pending" : input.contextLinkSuggestionStatus,
        limit,
      }),
    input.includeContextLinkSuggestions ?? true),
    optionalInspectionSection("memorySuggestions", continueOnError, issues, () =>
      resources.suggestions.listSuggestions({
        ...singleScopeInput(input),
        ...controls,
        status: input.memorySuggestionStatus === undefined ? "pending" : input.memorySuggestionStatus,
        limit,
      }),
    input.includeMemorySuggestions ?? true),
    optionalInspectionSection("anchorMergeCandidates", continueOnError, issues, () =>
      resources.anchors.listAnchorMergeSuggestions({
        ...memoryBrowserScopeInput(input),
        ...controls,
        ...optional("kind", input.anchorKind),
        limit,
      }),
    input.includeAnchorMergeCandidates ?? true),
    optionalInspectionSection("captureDiagnostics", continueOnError, issues, () =>
      resources.captures.captureDiagnostics({
        ...singleScopeInput(input),
        ...controls,
        consolidationStatus: input.captureConsolidationStatus === undefined
          ? "pending"
          : input.captureConsolidationStatus,
        limit,
      }),
    input.includeCaptureDiagnostics ?? true),
    optionalInspectionSection("extractionJobs", continueOnError, issues, () =>
      resources.assets.listScopeAssetExtractions({
        ...singleScopeInput(input),
        ...controls,
        status: input.extractionStatus === undefined ? "failed" : input.extractionStatus,
        limit,
      }),
    input.includeExtractionJobs ?? true),
  ]);

  const queues = {
    ...(operationsConsole ? { operationsConsole } : {}),
    ...(contextLinkSuggestions ? { contextLinkSuggestions } : {}),
    ...(memorySuggestions ? { memorySuggestions } : {}),
    ...(anchorMergeCandidates ? { anchorMergeCandidates } : {}),
    ...(captureDiagnostics ? { captureDiagnostics } : {}),
    ...(extractionJobs ? { extractionJobs } : {}),
  };

  return {
    queues,
    summary: maintenanceSummary(queues),
    diagnostics: {
      partial: issues.length > 0,
      issues,
      optionalSections,
    },
  };
}

function maintenanceResources(resources: MemoryMaintenanceResourceOptions): MemoryMaintenanceResources {
  const anchors = resources.anchors;
  const assets = resources.assets;
  const readModels = resources.readModels;
  const suggestions = resources.suggestions;
  const missing: string[] = [];

  if (anchors === undefined) {
    missing.push("anchors");
  }
  if (assets === undefined) {
    missing.push("assets");
  }
  if (readModels === undefined) {
    missing.push("readModels");
  }
  if (suggestions === undefined) {
    missing.push("suggestions");
  }

  if (anchors === undefined || assets === undefined || readModels === undefined || suggestions === undefined) {
    throw new ValueError(`planMemoryMaintenance requires MemoryWorkflowResources: ${missing.join(", ")}`);
  }

  return {
    anchors,
    assets,
    captures: resources.captures,
    contextLinks: resources.contextLinks,
    readModels,
    suggestions,
  };
}

function enabledMaintenanceSections(input: PlanMemoryMaintenanceInput): readonly string[] {
  const sections: string[] = [];
  if (input.includeOperations ?? true) {
    sections.push("operationsConsole");
  }
  if (input.includeContextLinkSuggestions ?? true) {
    sections.push("contextLinkSuggestions");
  }
  if (input.includeMemorySuggestions ?? true) {
    sections.push("memorySuggestions");
  }
  if (input.includeAnchorMergeCandidates ?? true) {
    sections.push("anchorMergeCandidates");
  }
  if (input.includeCaptureDiagnostics ?? true) {
    sections.push("captureDiagnostics");
  }
  if (input.includeExtractionJobs ?? true) {
    sections.push("extractionJobs");
  }
  return sections;
}

function maintenanceSummary(queues: MemoryMaintenanceQueues): MemoryMaintenanceSummary {
  const contextLinkSuggestions = queues.contextLinkSuggestions?.data.length ?? 0;
  const memorySuggestions = queues.memorySuggestions?.data.length ?? 0;
  const anchorMergeCandidates = queues.anchorMergeCandidates?.data.length ?? 0;
  const capturesPendingConsolidation = queues.captureDiagnostics?.data.length ?? 0;
  const extractionJobs = queues.extractionJobs?.data.length ?? 0;

  const suggestedActions = [
    maintenanceAction(
      "review_context_links",
      contextLinkSuggestions,
      "Pending context link suggestions can improve graph-aware retrieval when reviewed.",
    ),
    maintenanceAction(
      "resolve_memory_suggestions",
      memorySuggestions,
      "Pending memory suggestions should be approved, rejected or expired before beta reads rely on them.",
    ),
    maintenanceAction(
      "merge_duplicate_anchors",
      anchorMergeCandidates,
      "Anchor merge candidates reduce duplicate graph nodes and improve retrieval precision.",
    ),
    maintenanceAction(
      "consolidate_captures",
      capturesPendingConsolidation,
      "Pending captures should be consolidated into durable facts or review suggestions.",
    ),
    maintenanceAction(
      "retry_or_triage_extractions",
      extractionJobs,
      "Failed or queued extraction jobs can leave document evidence unavailable for summaries.",
    ),
  ].filter(isDefined);

  return {
    totalActionable: contextLinkSuggestions + memorySuggestions + anchorMergeCandidates +
      capturesPendingConsolidation + extractionJobs,
    contextLinkSuggestions,
    memorySuggestions,
    anchorMergeCandidates,
    capturesPendingConsolidation,
    extractionJobs,
    suggestedActions,
  };
}

function maintenanceAction(
  kind: MemoryMaintenanceActionKind,
  count: number,
  reason: string,
): MemoryMaintenanceAction | undefined {
  if (count <= 0) {
    return undefined;
  }

  return {
    kind,
    count,
    priority: count >= 10 ? "high" : count >= 3 ? "medium" : "low",
    reason,
  };
}
