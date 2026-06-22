import type { RequestControls } from "../client.js";
import type { ContextEnvelope, ContextBundleData, MemoryDigestData, SearchMemoryData } from "../context-types.js";
import {
  healthyRetrievalComponents,
  usedDerivedRetrieval,
  type ContextRetrievalComponent,
} from "../diagnostics.js";
import { ValueError, type ReadScope, type ReadScopeInput, type SingleScopeInput } from "../payload.js";
import type { AnchorsClient, AnchorMergeCandidate } from "../resources/anchors.js";
import type { AssetsClient } from "../resources/assets.js";
import type { CapturesClient, CreateCaptureData, CreateCaptureInput } from "../resources/captures.js";
import type { ContextLinksClient, SuggestContextLinksData } from "../resources/context-links.js";
import type { BuildContextInput, BuildDigestInput, ContextClient } from "../resources/context.js";
import type { DiagnosticsClient } from "../resources/diagnostics.js";
import type { DocumentsClient } from "../resources/documents.js";
import type { ExportsClient } from "../resources/exports.js";
import type { FactsClient, RememberFactInput } from "../resources/facts.js";
import type { MemoryBrowserData, OperationsConsoleData, ReadModelsClient } from "../resources/read-models.js";
import type { SpacesClient } from "../resources/spaces.js";
import type { SuggestionsClient } from "../resources/suggestions.js";
import type { SystemClient } from "../resources/system.js";
import type { UsageClient } from "../resources/usage.js";
import type { UsersClient } from "../resources/users.js";
import {
  assertRuntimeReadiness,
  evaluateRuntimeReadiness,
  type MemoryRuntimeAdapter,
  type RuntimeReadinessReport,
} from "../runtime.js";
import type {
  ApiEnvelope,
  AssetExtractionJobRecord,
  CaptureRecord,
  ContextLinkSuggestionRecord,
  DocumentRecord,
  FactRecord,
  InfinityContextCapabilities,
  JsonObject,
  MemoryScopeRecord,
  SourceRef,
  Space,
  SpaceMembership,
  SuggestionRecord,
  UsageSummaryData,
  UserRecord,
} from "../types.js";
import { InfinityContextError } from "../errors.js";

export interface MemoryWorkflowResources {
  readonly anchors?: AnchorsClient;
  readonly assets?: AssetsClient;
  readonly captures: CapturesClient;
  readonly context: ContextClient;
  readonly contextLinks: ContextLinksClient;
  readonly diagnostics?: DiagnosticsClient;
  readonly documents: DocumentsClient;
  readonly exports?: ExportsClient;
  readonly facts: FactsClient;
  readonly readModels?: ReadModelsClient;
  readonly spaces?: SpacesClient;
  readonly suggestions?: SuggestionsClient;
  readonly system?: SystemClient;
  readonly usage?: UsageClient;
  readonly users?: UsersClient;
}

interface MemoryInspectionResources {
  readonly diagnostics: DiagnosticsClient;
  readonly exports: ExportsClient;
  readonly readModels: ReadModelsClient;
  readonly system: SystemClient;
  readonly usage: UsageClient;
}

interface MemoryMaintenanceResources {
  readonly anchors: AnchorsClient;
  readonly assets: AssetsClient;
  readonly captures: CapturesClient;
  readonly contextLinks: ContextLinksClient;
  readonly readModels: ReadModelsClient;
  readonly suggestions: SuggestionsClient;
}

interface MemoryTopologyResources {
  readonly spaces: SpacesClient;
  readonly users: UsersClient;
}

interface MemoryRuntimeReadinessResources {
  readonly context: ContextClient;
  readonly system: SystemClient;
}

export interface RecordMemoryFeedbackInput extends SingleScopeInput, RequestControls {
  readonly sourceAgent: string;
  readonly text: string;
  readonly idempotencyKey: string;
  readonly sourceId?: string;
  readonly sourceRefs?: readonly SourceRef[];
  readonly eventType?: string;
  readonly actorRole?: "user" | "assistant" | "tool" | "system" | "subagent" | "unknown";
  readonly sourceActorExternalRef?: string;
  readonly occurredAt?: string;
  readonly metadata?: JsonObject;
  readonly consolidate?: boolean;
  readonly rememberAsFact?: boolean;
  readonly factText?: string;
  readonly factKind?: string;
  readonly factCategory?: string;
  readonly factTags?: readonly string[];
  readonly factTtlPolicy?: string;
  readonly factMemoryScopeExternalRef?: string;
}

export interface RecordMemoryFeedbackResult {
  readonly capture: ApiEnvelope<CreateCaptureData>;
  readonly fact?: ApiEnvelope<FactRecord>;
}

export interface BuildMemoryBriefInput extends ReadScopeInput, RequestControls {
  readonly readScope?: ReadScope;
  readonly query: string;
  readonly topic?: string;
  readonly tokenBudget?: number;
  readonly maxFacts?: number;
  readonly maxChunks?: number;
  readonly maxEvidenceItems?: number;
  readonly includeSearch?: boolean;
  readonly includeDigest?: boolean;
  readonly digestTokenBudget?: number;
  readonly consistencyMode?: string;
  readonly includeStale?: boolean;
}

export interface MemoryBriefDiagnostics {
  readonly derivedRetrievalUsed: boolean;
  readonly vectorHealthy: boolean;
  readonly graphHealthy: boolean;
  readonly ragHealthy: boolean;
  readonly retrievalSourcesUsed: readonly string[];
  readonly warnings: readonly string[];
}

export interface BuildMemoryBriefResult {
  readonly context: ContextEnvelope<ContextBundleData>;
  readonly search?: ContextEnvelope<SearchMemoryData>;
  readonly digest?: ContextEnvelope<MemoryDigestData>;
  readonly diagnostics: MemoryBriefDiagnostics;
}

export interface RunMemorySummaryLoopInput extends RequestControls {
  readonly topology?: WorkflowStepOptions<EnsureMemoryTopologyInput>;
  readonly readiness?: WorkflowStepOptions<CheckFullMemoryReadinessInput>;
  readonly sourceEvidence?: RecordSourceEvidenceBatchInput;
  readonly brief: BuildMemoryBriefInput;
  readonly stopOnSourceEvidenceFailure?: boolean;
}

export interface RunMemorySummaryLoopDiagnostics {
  readonly ok: boolean;
  readonly readinessOk: boolean | null;
  readonly sourceEvidenceOk: boolean | null;
  readonly warnings: readonly string[];
}

export interface RunMemorySummaryLoopResult {
  readonly topology?: EnsureMemoryTopologyResult;
  readonly readiness?: CheckFullMemoryReadinessResult;
  readonly sourceEvidence?: RecordSourceEvidenceBatchResult;
  readonly sourceEvidenceSummary?: RecordSourceEvidenceBatchSummary;
  readonly brief: BuildMemoryBriefResult;
  readonly diagnostics: RunMemorySummaryLoopDiagnostics;
}

export interface CheckFullMemoryReadinessInput extends ReadScopeInput, RequestControls {
  readonly readScope?: ReadScope;
  readonly query?: string;
  readonly includeContextProbe?: boolean;
  readonly includeSearchProbe?: boolean;
  readonly tokenBudget?: number;
  readonly maxFacts?: number;
  readonly maxChunks?: number;
  readonly maxEvidenceItems?: number;
  readonly consistencyMode?: string;
  readonly includeStale?: boolean;
  readonly requiredAdapters?: readonly MemoryRuntimeAdapter[];
  readonly requiredRetrieval?: readonly ContextRetrievalComponent[];
  readonly requireDerivedRetrieval?: boolean;
  readonly assertReady?: boolean;
}

export interface CheckFullMemoryReadinessDiagnostics {
  readonly contextProbe: boolean;
  readonly searchProbe: boolean;
  readonly diagnosticsSource: "context" | "search" | "none";
  readonly warnings: readonly string[];
}

export interface CheckFullMemoryReadinessResult {
  readonly capabilities: InfinityContextCapabilities;
  readonly readiness: RuntimeReadinessReport;
  readonly context?: ContextEnvelope<ContextBundleData>;
  readonly search?: ContextEnvelope<SearchMemoryData>;
  readonly diagnostics: CheckFullMemoryReadinessDiagnostics;
}

export interface InspectMemoryInput extends SingleScopeInput, RequestControls {
  readonly limit?: number;
  readonly continueOnError?: boolean;
  readonly includeOperations?: boolean;
  readonly includeUsage?: boolean;
  readonly includeCapabilities?: boolean;
  readonly includeDiagnostics?: boolean;
  readonly includeGraph?: boolean;
  readonly includeSnapshotPreview?: boolean;
  readonly graphIncludeDeleted?: boolean;
  readonly graphIncludeRestricted?: boolean;
  readonly graphMaxFacts?: number;
  readonly graphMaxDocuments?: number;
  readonly graphMaxEpisodes?: number;
  readonly graphMaxChunks?: number;
  readonly snapshotMergeStrategy?: string;
}

export interface InspectMemoryRuntimeDiagnostics {
  readonly adapters?: JsonObject;
  readonly metrics?: JsonObject;
  readonly storage?: JsonObject;
  readonly memoryScope?: JsonObject;
}

export interface InspectMemoryIssue {
  readonly section: string;
  readonly error: MemoryWorkflowErrorData;
}

export interface InspectMemoryDiagnostics {
  readonly partial: boolean;
  readonly warnings: readonly string[];
  readonly issues: readonly InspectMemoryIssue[];
  readonly optionalSections: readonly string[];
}

export interface InspectMemoryResult {
  readonly memoryBrowser: ApiEnvelope<MemoryBrowserData>;
  readonly operationsConsole?: ApiEnvelope<OperationsConsoleData>;
  readonly usage?: ApiEnvelope<UsageSummaryData>;
  readonly capabilities?: InfinityContextCapabilities;
  readonly runtimeDiagnostics?: InspectMemoryRuntimeDiagnostics;
  readonly graph?: JsonObject;
  readonly snapshot?: JsonObject;
  readonly snapshotPreview?: JsonObject;
  readonly inspection: InspectMemoryDiagnostics;
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

export type MemorySnapshotTransferMode = "export_only" | "preview" | "dry_run" | "confirmed_import";

export interface TransferMemorySnapshotInput extends RequestControls {
  readonly sourceSpaceSlug: string;
  readonly sourceMemoryScopeExternalRef: string;
  readonly targetSpaceSlug?: string;
  readonly targetMemoryScopeExternalRef?: string;
  readonly mode?: MemorySnapshotTransferMode;
  readonly redacted?: boolean;
  readonly mergeStrategy?: string;
  readonly confirmed?: boolean;
  readonly sourceName?: string;
}

export interface MemorySnapshotTransferEndpoint {
  readonly spaceSlug: string;
  readonly memoryScopeExternalRef: string;
}

export interface MemorySnapshotTransferDiagnostics {
  readonly mode: MemorySnapshotTransferMode;
  readonly mutated: boolean;
  readonly redacted: boolean;
  readonly mergeStrategy: string;
  readonly warnings: readonly string[];
}

export interface TransferMemorySnapshotResult {
  readonly source: MemorySnapshotTransferEndpoint;
  readonly target: MemorySnapshotTransferEndpoint;
  readonly snapshot: JsonObject;
  readonly manifest?: JsonObject;
  readonly preview?: JsonObject;
  readonly importResult?: JsonObject;
  readonly diagnostics: MemorySnapshotTransferDiagnostics;
}

export interface EnsureMemoryScopeInput {
  readonly externalRef: string;
  readonly name: string;
}

export interface EnsureMemoryUserInput {
  readonly externalRef: string;
  readonly displayName: string;
  readonly email?: string;
  readonly metadata?: JsonObject;
  readonly role?: string;
}

export interface EnsureMemoryTopologyInput extends RequestControls {
  readonly spaceSlug: string;
  readonly spaceName: string;
  readonly memoryScopes?: readonly EnsureMemoryScopeInput[];
  readonly users?: readonly EnsureMemoryUserInput[];
  readonly createMemberships?: boolean;
  readonly listLimit?: number;
}

export interface EnsureMemoryTopologyCreated {
  readonly space: boolean;
  readonly memoryScopes: readonly string[];
  readonly users: readonly string[];
  readonly memberships: readonly string[];
}

export interface EnsureMemoryTopologyDiagnostics {
  readonly listLimit: number;
  readonly warnings: readonly string[];
}

export interface EnsureMemoryTopologyResult {
  readonly space: Space;
  readonly memoryScopes: readonly MemoryScopeRecord[];
  readonly users: readonly UserRecord[];
  readonly memberships: readonly SpaceMembership[];
  readonly created: EnsureMemoryTopologyCreated;
  readonly diagnostics: EnsureMemoryTopologyDiagnostics;
}

export type WorkflowStepOptions<TOptions extends object> = boolean | TOptions;

export interface RecordSourceEvidenceDocumentOptions {
  readonly title?: string;
  readonly classification?: string;
  readonly process?: boolean;
}

export interface RecordSourceEvidenceEpisodeOptions {
  readonly occurredAt?: string;
  readonly speaker?: string;
  readonly trustLevel?: string;
  readonly kindHint?: string;
  readonly language?: string;
  readonly metadata?: JsonObject;
}

export interface RecordSourceEvidenceCaptureOptions {
  readonly sourceKind?: CreateCaptureInput["sourceKind"];
  readonly eventType?: string;
  readonly actorRole?: CreateCaptureInput["actorRole"];
  readonly sourceActorExternalRef?: string;
  readonly clientInstanceId?: string;
  readonly traceId?: string;
  readonly trustLevel?: CreateCaptureInput["trustLevel"];
  readonly sourceAuthority?: CreateCaptureInput["sourceAuthority"];
  readonly sensitivity?: CreateCaptureInput["sensitivity"];
  readonly dataClassification?: CreateCaptureInput["dataClassification"];
  readonly consolidate?: boolean;
}

export interface RecordSourceEvidenceFactOptions {
  readonly text?: string;
  readonly memoryScopeExternalRef?: string;
  readonly kind?: string;
  readonly category?: string;
  readonly tags?: readonly string[];
  readonly ttlPolicy?: string;
}

export interface RecordSourceEvidenceLinkSuggestionOptions {
  readonly persist?: boolean;
  readonly limit?: number;
  readonly sourceType?: string;
  readonly sourceId?: string;
}

export interface RecordSourceEvidenceInput extends SingleScopeInput, RequestControls {
  readonly sourceAgent: string;
  readonly sourceType: string;
  readonly sourceId: string;
  readonly text: string;
  readonly idempotencyKey: string;
  readonly title?: string;
  readonly occurredAt?: string;
  readonly sourceRefs?: readonly SourceRef[];
  readonly metadata?: JsonObject;
  readonly document?: WorkflowStepOptions<RecordSourceEvidenceDocumentOptions>;
  readonly episode?: WorkflowStepOptions<RecordSourceEvidenceEpisodeOptions>;
  readonly capture?: WorkflowStepOptions<RecordSourceEvidenceCaptureOptions>;
  readonly fact?: WorkflowStepOptions<RecordSourceEvidenceFactOptions>;
  readonly linkSuggestions?: WorkflowStepOptions<RecordSourceEvidenceLinkSuggestionOptions>;
}

export interface RecordSourceEvidenceResult {
  readonly sourceRefs: readonly SourceRef[];
  readonly document?: ApiEnvelope<DocumentRecord>;
  readonly processedDocument?: ApiEnvelope<DocumentRecord>;
  readonly episode?: ApiEnvelope<JsonObject>;
  readonly capture?: ApiEnvelope<CreateCaptureData>;
  readonly fact?: ApiEnvelope<FactRecord>;
  readonly linkSuggestions?: ApiEnvelope<SuggestContextLinksData>;
}

export interface MemoryWorkflowErrorData {
  readonly name: string;
  readonly message: string;
  readonly code?: string;
  readonly statusCode?: number;
  readonly retryable?: boolean;
  readonly requestId?: string;
}

export interface RecordSourceEvidenceBatchItemResult {
  readonly index: number;
  readonly sourceType: string;
  readonly sourceId: string;
  readonly idempotencyKey: string;
  readonly ok: boolean;
  readonly result?: RecordSourceEvidenceResult;
  readonly error?: MemoryWorkflowErrorData;
}

export interface RecordSourceEvidenceBatchInput extends RequestControls {
  readonly items: readonly RecordSourceEvidenceInput[];
  readonly concurrency?: number;
  readonly continueOnError?: boolean;
}

export interface RecordSourceEvidenceBatchResult {
  readonly total: number;
  readonly succeeded: number;
  readonly failed: number;
  readonly stopped: boolean;
  readonly results: readonly RecordSourceEvidenceBatchItemResult[];
}

export interface RecordSourceEvidenceBatchFailure {
  readonly index: number;
  readonly sourceType: string;
  readonly sourceId: string;
  readonly idempotencyKey: string;
  readonly error: MemoryWorkflowErrorData;
}

export interface RecordSourceEvidenceBatchSummary {
  readonly total: number;
  readonly completed: number;
  readonly skipped: number;
  readonly succeeded: number;
  readonly failed: number;
  readonly stopped: boolean;
  readonly successRate: number;
  readonly failureRate: number;
  readonly retryableFailures: number;
  readonly nonRetryableFailures: number;
  readonly bySourceType: Readonly<Record<string, number>>;
  readonly byErrorCode: Readonly<Record<string, number>>;
  readonly byStatusCode: Readonly<Record<string, number>>;
  readonly failedItems: readonly RecordSourceEvidenceBatchFailure[];
}

export function summarizeSourceEvidenceBatch(
  batch: RecordSourceEvidenceBatchResult,
): RecordSourceEvidenceBatchSummary {
  const bySourceType: Record<string, number> = {};
  const byErrorCode: Record<string, number> = {};
  const byStatusCode: Record<string, number> = {};
  const failedItems: RecordSourceEvidenceBatchFailure[] = [];
  let retryableFailures = 0;
  let nonRetryableFailures = 0;

  for (const item of batch.results) {
    incrementCount(bySourceType, item.sourceType);

    if (item.ok || item.error === undefined) {
      continue;
    }

    const errorCode = item.error.code ?? "unknown";
    const statusCode = item.error.statusCode === undefined ? "unknown" : String(item.error.statusCode);
    incrementCount(byErrorCode, errorCode);
    incrementCount(byStatusCode, statusCode);

    if (item.error.retryable === true) {
      retryableFailures += 1;
    } else {
      nonRetryableFailures += 1;
    }

    failedItems.push({
      index: item.index,
      sourceType: item.sourceType,
      sourceId: item.sourceId,
      idempotencyKey: item.idempotencyKey,
      error: item.error,
    });
  }

  const completed = batch.results.length;
  const skipped = Math.max(0, batch.total - completed);
  return {
    total: batch.total,
    completed,
    skipped,
    succeeded: batch.succeeded,
    failed: batch.failed,
    stopped: batch.stopped,
    successRate: ratio(batch.succeeded, batch.total),
    failureRate: ratio(batch.failed, batch.total),
    retryableFailures,
    nonRetryableFailures,
    bySourceType,
    byErrorCode,
    byStatusCode,
    failedItems,
  };
}

export class MemoryWorkflows {
  constructor(private readonly resources: MemoryWorkflowResources) {}

  async recordFeedback(input: RecordMemoryFeedbackInput): Promise<RecordMemoryFeedbackResult> {
    const sourceRefs = feedbackSourceRefs(input);
    const controls = workflowControls(input);
    const captureInput: CreateCaptureInput = {
      ...singleScopeInput(input),
      ...controls,
      sourceAgent: input.sourceAgent,
      sourceKind: "hook",
      eventType: input.eventType ?? "memory.feedback.recorded",
      actorRole: input.actorRole ?? "user",
      text: input.text,
      sourceEventId: input.sourceId ?? input.idempotencyKey,
      ...optional("sourceActorExternalRef", input.sourceActorExternalRef),
      evidenceRefs: sourceRefs,
      trustLevel: "high",
      sourceAuthority: input.actorRole === "assistant" ? "assistant_inference" : "user_statement",
      sensitivity: "medium",
      dataClassification: "internal",
      ...optional("occurredAt", input.occurredAt),
      ...optional("metadata", input.metadata),
      idempotencyKey: input.idempotencyKey,
      consolidate: input.consolidate ?? true,
    };

    const capture = await this.resources.captures.createCapture(captureInput);

    if (input.rememberAsFact === false) {
      return { capture };
    }

    const fact = await this.resources.facts.rememberFact({
      ...factScopeInput(input),
      ...controls,
      text: input.factText ?? input.text,
      kind: input.factKind ?? "user_preference",
      category: input.factCategory ?? "feedback",
      tags: input.factTags ?? ["feedback"],
      ttlPolicy: input.factTtlPolicy ?? "durable",
      sourceRefs: [{ source_type: "capture", source_id: capture.data.id }, ...sourceRefs],
      idempotencyKey: `${input.idempotencyKey}:fact`,
    });

    return { capture, fact };
  }

  async recordSourceEvidence(input: RecordSourceEvidenceInput): Promise<RecordSourceEvidenceResult> {
    const baseSourceRefs = sourceEvidenceRefs(input);
    const createdSourceRefs: SourceRef[] = [];
    const controls = workflowControls(input);

    let document: ApiEnvelope<DocumentRecord> | undefined;
    let processedDocument: ApiEnvelope<DocumentRecord> | undefined;
    if (isEnabled(input.document, false)) {
      const documentOptions = stepOptions(input.document);
      document = await this.resources.documents.ingestDocument({
        ...singleScopeInput(input),
        ...controls,
        title: documentOptions.title ?? input.title ?? input.sourceId,
        text: input.text,
        sourceExternalId: input.sourceId,
        sourceType: input.sourceType,
        classification: documentOptions.classification ?? "internal",
        sourceRefs: baseSourceRefs,
        idempotencyKey: `${input.idempotencyKey}:document`,
      });
      createdSourceRefs.push({ source_type: "document", source_id: document.data.id });

      if (documentOptions.process === true) {
        processedDocument = await this.resources.documents.processDocument(document.data.id, {
          ...controls,
          idempotencyKey: `${input.idempotencyKey}:document:process`,
        });
      }
    }

    let episode: ApiEnvelope<JsonObject> | undefined;
    if (isEnabled(input.episode, true)) {
      const episodeOptions = stepOptions(input.episode);
      episode = await this.resources.documents.ingestEpisode({
        ...singleScopeInput(input),
        ...controls,
        sourceExternalId: input.sourceId,
        sourceType: input.sourceType,
        text: input.text,
        ...optional("occurredAt", episodeOptions.occurredAt ?? input.occurredAt),
        ...optional("speaker", episodeOptions.speaker),
        trustLevel: episodeOptions.trustLevel ?? "medium",
        kindHint: episodeOptions.kindHint ?? "fact_evidence",
        ...optional("language", episodeOptions.language),
        metadata: { ...input.metadata, ...episodeOptions.metadata },
        idempotencyKey: `${input.idempotencyKey}:episode`,
      });
      const episodeId = stringField(episode.data, "id");
      if (episodeId) {
        createdSourceRefs.push({ source_type: "episode", source_id: episodeId });
      }
    }

    let capture: ApiEnvelope<CreateCaptureData> | undefined;
    if (isEnabled(input.capture, true)) {
      const captureOptions = stepOptions(input.capture);
      capture = await this.resources.captures.createCapture({
        ...singleScopeInput(input),
        ...controls,
        sourceAgent: input.sourceAgent,
        sourceKind: captureOptions.sourceKind ?? "document",
        eventType: captureOptions.eventType ?? "memory.source_evidence.recorded",
        actorRole: captureOptions.actorRole ?? "tool",
        text: input.text,
        sourceEventId: input.sourceId,
        ...optional("sourceActorExternalRef", captureOptions.sourceActorExternalRef),
        ...optional("clientInstanceId", captureOptions.clientInstanceId),
        evidenceRefs: [...baseSourceRefs, ...createdSourceRefs],
        trustLevel: captureOptions.trustLevel ?? "medium",
        sourceAuthority: captureOptions.sourceAuthority ?? "tool_verified",
        sensitivity: captureOptions.sensitivity ?? "medium",
        dataClassification: captureOptions.dataClassification ?? "internal",
        ...optional("occurredAt", input.occurredAt),
        ...optional("metadata", input.metadata),
        ...optional("traceId", captureOptions.traceId),
        idempotencyKey: `${input.idempotencyKey}:capture`,
        consolidate: captureOptions.consolidate ?? true,
      });
      createdSourceRefs.push({ source_type: "capture", source_id: capture.data.id });
    }

    let fact: ApiEnvelope<FactRecord> | undefined;
    if (isEnabled(input.fact, false)) {
      const factOptions = stepOptions(input.fact);
      fact = await this.resources.facts.rememberFact({
        ...singleScopeInput(input),
        ...controls,
        ...optional("memoryScopeExternalRef", factOptions.memoryScopeExternalRef ?? input.memoryScopeExternalRef),
        text: factOptions.text ?? input.text,
        kind: factOptions.kind ?? "source_signal",
        category: factOptions.category ?? "source_evidence",
        tags: factOptions.tags ?? [input.sourceType],
        ttlPolicy: factOptions.ttlPolicy ?? "durable",
        sourceRefs: [...createdSourceRefs, ...baseSourceRefs],
        idempotencyKey: `${input.idempotencyKey}:fact`,
      });
    }

    let linkSuggestions: ApiEnvelope<SuggestContextLinksData> | undefined;
    if (isEnabled(input.linkSuggestions, true)) {
      const linkOptions = stepOptions(input.linkSuggestions);
      linkSuggestions = await this.resources.contextLinks.suggestContextLinks({
        ...singleScopeInput(input),
        ...controls,
        text: input.text,
        sourceType: linkOptions.sourceType ?? (capture ? "capture" : input.sourceType),
        sourceId: linkOptions.sourceId ?? capture?.data.id ?? input.sourceId,
        limit: linkOptions.limit ?? 10,
        persist: linkOptions.persist ?? true,
      });
    }

    return {
      sourceRefs: [...baseSourceRefs, ...createdSourceRefs],
      ...(document ? { document } : {}),
      ...(processedDocument ? { processedDocument } : {}),
      ...(episode ? { episode } : {}),
      ...(capture ? { capture } : {}),
      ...(fact ? { fact } : {}),
      ...(linkSuggestions ? { linkSuggestions } : {}),
    };
  }

  async recordSourceEvidenceBatch(
    input: RecordSourceEvidenceBatchInput,
  ): Promise<RecordSourceEvidenceBatchResult> {
    const concurrency = normalizeBatchConcurrency(input.concurrency);
    const items = [...input.items];
    if (items.length > 500) {
      throw new ValueError("recordSourceEvidenceBatch supports at most 500 items");
    }
    if (items.length === 0) {
      return { total: 0, succeeded: 0, failed: 0, stopped: false, results: [] };
    }

    const continueOnError = input.continueOnError ?? true;
    const results: Array<RecordSourceEvidenceBatchItemResult | undefined> = [];
    let nextIndex = 0;
    let stopped = false;

    const workerCount = Math.min(concurrency, items.length);
    await Promise.all(Array.from({ length: workerCount }, async () => {
      for (;;) {
        if (stopped) {
          return;
        }

        const index = nextIndex;
        nextIndex += 1;
        const item = items[index];
        if (item === undefined) {
          return;
        }

        try {
          const scopedItem = withWorkflowControls(input, item);
          const result = await this.recordSourceEvidence(scopedItem);
          results[index] = batchItemResult(index, scopedItem, { result });
        } catch (error) {
          const scopedItem = withWorkflowControls(input, item);
          results[index] = batchItemResult(index, scopedItem, { error: workflowErrorData(error) });
          if (!continueOnError) {
            stopped = true;
            return;
          }
        }
      }
    }));

    const completedResults = results.filter(isDefined);
    const failed = completedResults.filter((result) => !result.ok).length;
    return {
      total: items.length,
      succeeded: completedResults.length - failed,
      failed,
      stopped,
      results: completedResults,
    };
  }

  async buildMemoryBrief(input: BuildMemoryBriefInput): Promise<BuildMemoryBriefResult> {
    const contextInput: BuildContextInput = {
      ...readScopeInput(input),
      ...workflowControls(input),
      query: input.query,
      ...optional("tokenBudget", input.tokenBudget),
      ...optional("maxFacts", input.maxFacts),
      ...optional("maxChunks", input.maxChunks),
      ...optional("maxEvidenceItems", input.maxEvidenceItems),
      ...optional("consistencyMode", input.consistencyMode),
      ...optional("includeStale", input.includeStale),
    };

    const [context, search, digest] = await Promise.all([
      this.resources.context.buildContext(contextInput),
      input.includeSearch === false ? Promise.resolve(undefined) : this.resources.context.search(contextInput),
      input.includeDigest === false
        ? Promise.resolve(undefined)
        : this.resources.context.buildDigest({
            ...readScopeInput(input),
            ...workflowControls(input),
            topic: input.topic ?? input.query,
            ...optional("tokenBudget", input.digestTokenBudget ?? input.tokenBudget),
            ...optional("maxFacts", input.maxFacts),
            ...optional("maxChunks", input.maxChunks),
          } satisfies BuildDigestInput),
    ]);

    return {
      context,
      ...(search ? { search } : {}),
      ...(digest ? { digest } : {}),
      diagnostics: briefDiagnostics(context, search),
    };
  }

  async runMemorySummaryLoop(input: RunMemorySummaryLoopInput): Promise<RunMemorySummaryLoopResult> {
    const topology = isEnabled(input.topology, false)
      ? await this.ensureMemoryTopology(withWorkflowControls(
          input,
          requiredStepOptions(input.topology, "runMemorySummaryLoop topology requires options"),
        ))
      : undefined;
    const readiness = isEnabled(input.readiness, true)
      ? await this.checkFullMemoryReadiness(withWorkflowControls(input, stepOptions(input.readiness)))
      : undefined;
    const sourceEvidence = input.sourceEvidence === undefined
      ? undefined
      : await this.recordSourceEvidenceBatch(withWorkflowControls(input, input.sourceEvidence));
    const sourceEvidenceSummary = sourceEvidence === undefined
      ? undefined
      : summarizeSourceEvidenceBatch(sourceEvidence);

    if ((input.stopOnSourceEvidenceFailure ?? false) && sourceEvidenceSummary !== undefined) {
      if (sourceEvidenceSummary.failed > 0 || sourceEvidenceSummary.stopped) {
        throw new ValueError(
          `runMemorySummaryLoop source evidence failed: ${sourceEvidenceSummary.failed} failed, ${sourceEvidenceSummary.skipped} skipped`,
        );
      }
    }

    const brief = await this.buildMemoryBrief(withWorkflowControls(input, input.brief));
    const readinessOk = readiness?.readiness.ok ?? null;
    const sourceEvidenceOk = sourceEvidenceSummary === undefined
      ? null
      : sourceEvidenceSummary.failed === 0 && !sourceEvidenceSummary.stopped;
    const warnings = uniqueStrings([
      ...(readiness?.diagnostics.warnings ?? []),
      ...(sourceEvidenceSummary !== undefined && !sourceEvidenceOk
        ? [`source evidence batch has ${sourceEvidenceSummary.failed} failed item(s)`]
        : []),
      ...brief.diagnostics.warnings,
    ]);

    return {
      ...(topology ? { topology } : {}),
      ...(readiness ? { readiness } : {}),
      ...(sourceEvidence ? { sourceEvidence } : {}),
      ...(sourceEvidenceSummary ? { sourceEvidenceSummary } : {}),
      brief,
      diagnostics: {
        ok: (readinessOk ?? true) && (sourceEvidenceOk ?? true),
        readinessOk,
        sourceEvidenceOk,
        warnings,
      },
    };
  }

  async checkFullMemoryReadiness(
    input: CheckFullMemoryReadinessInput = {},
  ): Promise<CheckFullMemoryReadinessResult> {
    const resources = runtimeReadinessResources(this.resources);
    const controls = workflowControls(input);
    const shouldProbeContext = input.includeContextProbe ?? input.query !== undefined;
    const shouldProbeSearch = input.includeSearchProbe ?? false;
    const probeRequested = shouldProbeContext || shouldProbeSearch;

    let probeInput: BuildContextInput | undefined;
    if (probeRequested) {
      const query = requiredWorkflowText(input.query, "checkFullMemoryReadiness probe requires query");
      probeInput = {
        ...readScopeInput(input),
        ...controls,
        query,
        ...optional("tokenBudget", input.tokenBudget),
        ...optional("maxFacts", input.maxFacts),
        ...optional("maxChunks", input.maxChunks),
        ...optional("maxEvidenceItems", input.maxEvidenceItems),
        ...optional("consistencyMode", input.consistencyMode),
        ...optional("includeStale", input.includeStale),
      };
    }

    const [capabilities, context, search] = await Promise.all([
      resources.system.capabilities(controls),
      shouldProbeContext && probeInput !== undefined
        ? resources.context.buildContext(probeInput)
        : Promise.resolve(undefined),
      shouldProbeSearch && probeInput !== undefined
        ? resources.context.search(probeInput)
        : Promise.resolve(undefined),
    ]);

    const diagnostics = context?.data.diagnostics ?? search?.data.diagnostics;
    const readinessInput = {
      capabilities,
      ...(diagnostics === undefined ? {} : { diagnostics }),
      ...optional("requiredAdapters", input.requiredAdapters),
      ...optional("requiredRetrieval", input.requiredRetrieval),
      requireDerivedRetrieval: input.requireDerivedRetrieval ?? diagnostics !== undefined,
    };
    const readiness = input.assertReady === true
      ? assertRuntimeReadiness(readinessInput)
      : evaluateRuntimeReadiness(readinessInput);

    return {
      capabilities,
      readiness,
      ...(context ? { context } : {}),
      ...(search ? { search } : {}),
      diagnostics: {
        contextProbe: context !== undefined,
        searchProbe: search !== undefined,
        diagnosticsSource: context ? "context" : search ? "search" : "none",
        warnings: readiness.warnings,
      },
    };
  }

  async ensureMemoryTopology(input: EnsureMemoryTopologyInput): Promise<EnsureMemoryTopologyResult> {
    const resources = topologyResources(this.resources);
    const controls = workflowControls(input);
    const listLimit = input.listLimit ?? 500;
    const warnings: string[] = [];
    const createdScopes: string[] = [];
    const createdUsers: string[] = [];
    const createdMemberships: string[] = [];

    const spaceResult = await ensureWorkflowSpace(resources, {
      ...controls,
      slug: requiredWorkflowText(input.spaceSlug, "ensureMemoryTopology requires spaceSlug"),
      name: requiredWorkflowText(input.spaceName, "ensureMemoryTopology requires spaceName"),
      listLimit,
    });

    const memoryScopes: MemoryScopeRecord[] = [];
    for (const scope of input.memoryScopes ?? []) {
      const result = await ensureWorkflowMemoryScope(resources, {
        ...controls,
        spaceId: spaceResult.record.id,
        externalRef: requiredWorkflowText(scope.externalRef, "ensureMemoryTopology scope requires externalRef"),
        name: requiredWorkflowText(scope.name, "ensureMemoryTopology scope requires name"),
        listLimit,
      });
      memoryScopes.push(result.record);
      if (result.created) {
        createdScopes.push(result.record.external_ref);
      }
    }

    const users: UserRecord[] = [];
    const memberships: SpaceMembership[] = [];
    if (input.users !== undefined && input.users.length > 0) {
      const existingUsers = await resources.users.listUsers({
        ...controls,
        limit: listLimit,
      });
      const userRecordsByExternalRef = new Map<string, UserRecord>();

      for (const user of input.users) {
        const result = await ensureWorkflowUser(resources, {
          ...controls,
          externalRef: requiredWorkflowText(user.externalRef, "ensureMemoryTopology user requires externalRef"),
          displayName: requiredWorkflowText(user.displayName, "ensureMemoryTopology user requires displayName"),
          ...optional("email", user.email),
          ...optional("metadata", user.metadata),
          listLimit,
          existingUsers: existingUsers.data,
        });
        users.push(result.record);
        userRecordsByExternalRef.set(result.record.external_ref, result.record);
        if (result.created) {
          createdUsers.push(result.record.external_ref);
        }
      }

      if (input.createMemberships ?? true) {
        const existingMemberships = await resources.users.listSpaceMemberships(spaceResult.record.id, {
          ...controls,
          limit: listLimit,
        });
        for (const user of input.users) {
          const userRecord = userRecordsByExternalRef.get(user.externalRef);
          if (userRecord === undefined) {
            continue;
          }
          const result = await ensureWorkflowMembership(resources, {
            ...controls,
            spaceId: spaceResult.record.id,
            userId: userRecord.id,
            role: user.role ?? "member",
            listLimit,
            existingMemberships: existingMemberships.data,
          });
          memberships.push(result.record);
          if (result.created) {
            createdMemberships.push(userRecord.external_ref);
          } else if (result.record.role !== (user.role ?? "member")) {
            warnings.push(`membership for ${userRecord.external_ref} exists with role ${result.record.role}`);
          }
        }
      }
    }

    return {
      space: spaceResult.record,
      memoryScopes,
      users,
      memberships,
      created: {
        space: spaceResult.created,
        memoryScopes: createdScopes,
        users: createdUsers,
        memberships: createdMemberships,
      },
      diagnostics: {
        listLimit,
        warnings,
      },
    };
  }

  async inspectMemory(input: InspectMemoryInput = {}): Promise<InspectMemoryResult> {
    const resources = inspectionResources(this.resources);
    const controls = workflowControls(input);
    const issues: InspectMemoryIssue[] = [];
    const warnings: string[] = [];
    const continueOnError = input.continueOnError ?? false;
    const optionalSections = enabledInspectionSections(input);

    const memoryBrowser = await resources.readModels.getMemoryBrowser({
      ...memoryBrowserScopeInput(input),
      ...controls,
      ...optional("limit", input.limit),
    });

    const [operationsConsole, usage, capabilities, runtimeDiagnostics, graph, snapshotBundle] = await Promise.all([
      optionalInspectionSection("operationsConsole", continueOnError, issues, () =>
        resources.readModels.getOperationsConsole({
          ...singleScopeInput(input),
          ...controls,
          ...optional("limit", input.limit),
        }),
      input.includeOperations ?? true),
      optionalInspectionSection("usage", continueOnError, issues, () =>
        resources.usage.summary({
          ...controls,
          ...optional("spaceId", input.spaceId),
          ...optional("spaceSlug", input.spaceSlug),
        }),
      input.includeUsage ?? true),
      optionalInspectionSection("capabilities", continueOnError, issues, () =>
        resources.system.capabilities(controls),
      input.includeCapabilities ?? true),
      optionalInspectionSection("runtimeDiagnostics", continueOnError, issues, () =>
        inspectRuntimeDiagnostics(resources, input, controls, continueOnError, issues),
      input.includeDiagnostics ?? true),
      optionalInspectionSection("graph", continueOnError, issues, () =>
        resources.exports.exportGraph({
          ...singleScopeInput(input),
          ...controls,
          ...optional("includeDeleted", input.graphIncludeDeleted),
          ...optional("includeRestricted", input.graphIncludeRestricted),
          ...optional("maxFacts", input.graphMaxFacts),
          ...optional("maxDocuments", input.graphMaxDocuments),
          ...optional("maxEpisodes", input.graphMaxEpisodes),
          ...optional("maxChunks", input.graphMaxChunks),
        }),
      input.includeGraph ?? false),
      optionalInspectionSection("snapshotPreview", continueOnError, issues, () =>
        previewMemorySnapshot(resources, input, controls, warnings),
      input.includeSnapshotPreview ?? false),
    ]);

    return {
      memoryBrowser,
      ...(operationsConsole ? { operationsConsole } : {}),
      ...(usage ? { usage } : {}),
      ...(capabilities ? { capabilities } : {}),
      ...(runtimeDiagnostics ? { runtimeDiagnostics } : {}),
      ...(graph ? { graph } : {}),
      ...(snapshotBundle?.snapshot ? { snapshot: snapshotBundle.snapshot } : {}),
      ...(snapshotBundle?.snapshotPreview ? { snapshotPreview: snapshotBundle.snapshotPreview } : {}),
      inspection: {
        partial: issues.length > 0,
        warnings,
        issues,
        optionalSections,
      },
    };
  }

  async planMemoryMaintenance(input: PlanMemoryMaintenanceInput = {}): Promise<PlanMemoryMaintenanceResult> {
    const resources = maintenanceResources(this.resources);
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

  async transferMemorySnapshot(input: TransferMemorySnapshotInput): Promise<TransferMemorySnapshotResult> {
    const exportsClient = snapshotResources(this.resources);
    const controls = workflowControls(input);
    const mode = input.mode ?? "preview";
    const redacted = input.redacted ?? true;
    const mergeStrategy = input.mergeStrategy ?? "fail_on_conflict";
    const source = snapshotSource(input);
    const target = snapshotTarget(input);
    const warnings = snapshotTransferWarnings(input, mode, source, target);
    validateSnapshotTransfer(input, mode);

    const snapshotExport = await exportsClient.exportMemoryScopeSnapshot({
      ...controls,
      spaceSlug: source.spaceSlug,
      memoryScopeExternalRef: source.memoryScopeExternalRef,
      redacted,
    });
    const snapshot = jsonObjectField(snapshotExport, "data");
    if (snapshot === undefined) {
      throw new ValueError("Snapshot export response did not include data");
    }
    const manifest = jsonObjectField(snapshotExport, "manifest");

    if (mode === "export_only") {
      return snapshotTransferResult(source, target, snapshot, manifest, {
        mode,
        redacted,
        mergeStrategy,
        warnings,
      });
    }

    if (mode === "preview") {
      const preview = await exportsClient.previewMemoryScopeSnapshotImport({
        ...controls,
        spaceSlug: target.spaceSlug,
        memoryScopeExternalRef: target.memoryScopeExternalRef,
        snapshot,
        ...optional("manifest", manifest),
        mergeStrategy,
      });

      return snapshotTransferResult(source, target, snapshot, manifest, {
        mode,
        redacted,
        mergeStrategy,
        warnings,
        preview,
      });
    }

    const importResult = await exportsClient.importMemoryScopeSnapshot({
      ...controls,
      spaceSlug: target.spaceSlug,
      memoryScopeExternalRef: target.memoryScopeExternalRef,
      snapshot,
      ...optional("manifest", manifest),
      dryRun: mode === "dry_run",
      mergeStrategy,
      confirmed: mode === "confirmed_import",
      sourceName: input.sourceName ?? "ts-sdk-transfer-memory-snapshot",
    });

    return snapshotTransferResult(source, target, snapshot, manifest, {
      mode,
      redacted,
      mergeStrategy,
      warnings,
      importResult,
    });
  }
}

interface MemorySnapshotPreviewBundle {
  readonly snapshot: JsonObject;
  readonly snapshotPreview: JsonObject;
}

interface EnsureWorkflowResult<TRecord> {
  readonly record: TRecord;
  readonly created: boolean;
}

function inspectionResources(resources: MemoryWorkflowResources): MemoryInspectionResources {
  const diagnostics = resources.diagnostics;
  const exportsClient = resources.exports;
  const readModels = resources.readModels;
  const system = resources.system;
  const usage = resources.usage;
  const missing: string[] = [];

  if (diagnostics === undefined) {
    missing.push("diagnostics");
  }
  if (exportsClient === undefined) {
    missing.push("exports");
  }
  if (readModels === undefined) {
    missing.push("readModels");
  }
  if (system === undefined) {
    missing.push("system");
  }
  if (usage === undefined) {
    missing.push("usage");
  }

  if (
    diagnostics === undefined ||
    exportsClient === undefined ||
    readModels === undefined ||
    system === undefined ||
    usage === undefined
  ) {
    throw new ValueError(`inspectMemory requires MemoryWorkflowResources: ${missing.join(", ")}`);
  }

  return { diagnostics, exports: exportsClient, readModels, system, usage };
}

function topologyResources(resources: MemoryWorkflowResources): MemoryTopologyResources {
  const spaces = resources.spaces;
  const users = resources.users;
  const missing: string[] = [];

  if (spaces === undefined) {
    missing.push("spaces");
  }
  if (users === undefined) {
    missing.push("users");
  }
  if (spaces === undefined || users === undefined) {
    throw new ValueError(`ensureMemoryTopology requires MemoryWorkflowResources: ${missing.join(", ")}`);
  }

  return { spaces, users };
}

function runtimeReadinessResources(resources: MemoryWorkflowResources): MemoryRuntimeReadinessResources {
  const system = resources.system;
  if (system === undefined) {
    throw new ValueError("checkFullMemoryReadiness requires MemoryWorkflowResources: system");
  }

  return { context: resources.context, system };
}

function maintenanceResources(resources: MemoryWorkflowResources): MemoryMaintenanceResources {
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

function snapshotResources(resources: MemoryWorkflowResources): ExportsClient {
  const exportsClient = resources.exports;
  if (exportsClient === undefined) {
    throw new ValueError("transferMemorySnapshot requires MemoryWorkflowResources: exports");
  }
  return exportsClient;
}

async function ensureWorkflowSpace(
  resources: MemoryTopologyResources,
  input: { readonly slug: string; readonly name: string; readonly listLimit: number } & RequestControls,
): Promise<EnsureWorkflowResult<Space>> {
  const existing = await resources.spaces.listSpaces({ ...workflowControls(input), limit: input.listLimit });
  const found = existing.data.find((space) => space.slug === input.slug);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.spaces.createSpace({
      ...workflowControls(input),
      slug: input.slug,
      name: input.name,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw error;
    }
    const afterConflict = await resources.spaces.listSpaces({ ...workflowControls(input), limit: input.listLimit });
    const created = afterConflict.data.find((space) => space.slug === input.slug);
    if (created === undefined) {
      throw error;
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowMemoryScope(
  resources: MemoryTopologyResources,
  input: {
    readonly spaceId: string;
    readonly externalRef: string;
    readonly name: string;
    readonly listLimit: number;
  } & RequestControls,
): Promise<EnsureWorkflowResult<MemoryScopeRecord>> {
  const existing = await resources.spaces.listMemoryScopes({
    ...workflowControls(input),
    spaceId: input.spaceId,
    limit: input.listLimit,
  });
  const found = existing.data.find((scope) => scope.external_ref === input.externalRef);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.spaces.createMemoryScope({
      ...workflowControls(input),
      spaceId: input.spaceId,
      externalRef: input.externalRef,
      name: input.name,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw error;
    }
    const afterConflict = await resources.spaces.listMemoryScopes({
      ...workflowControls(input),
      spaceId: input.spaceId,
      limit: input.listLimit,
    });
    const created = afterConflict.data.find((scope) => scope.external_ref === input.externalRef);
    if (created === undefined) {
      throw error;
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowUser(
  resources: MemoryTopologyResources,
  input: {
    readonly externalRef: string;
    readonly displayName: string;
    readonly email?: string;
    readonly metadata?: JsonObject;
    readonly listLimit: number;
    readonly existingUsers: readonly UserRecord[];
  } & RequestControls,
): Promise<EnsureWorkflowResult<UserRecord>> {
  const found = input.existingUsers.find((user) => user.external_ref === input.externalRef);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.users.createUser({
      ...workflowControls(input),
      externalRef: input.externalRef,
      displayName: input.displayName,
      ...optional("email", input.email),
      ...optional("metadata", input.metadata),
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw error;
    }
    const afterConflict = await resources.users.listUsers({ ...workflowControls(input), limit: input.listLimit });
    const created = afterConflict.data.find((user) => user.external_ref === input.externalRef);
    if (created === undefined) {
      throw error;
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowMembership(
  resources: MemoryTopologyResources,
  input: {
    readonly spaceId: string;
    readonly userId: string;
    readonly role: string;
    readonly listLimit: number;
    readonly existingMemberships: readonly SpaceMembership[];
  } & RequestControls,
): Promise<EnsureWorkflowResult<SpaceMembership>> {
  const found = input.existingMemberships.find((membership) => membership.user_id === input.userId);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.users.createSpaceMembership(input.spaceId, {
      ...workflowControls(input),
      userId: input.userId,
      role: input.role,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw error;
    }
    const afterConflict = await resources.users.listSpaceMemberships(input.spaceId, {
      ...workflowControls(input),
      limit: input.listLimit,
    });
    const created = afterConflict.data.find((membership) => membership.user_id === input.userId);
    if (created === undefined) {
      throw error;
    }
    return { record: created, created: false };
  }
}

function snapshotSource(input: TransferMemorySnapshotInput): MemorySnapshotTransferEndpoint {
  return {
    spaceSlug: requiredWorkflowText(input.sourceSpaceSlug, "transferMemorySnapshot requires sourceSpaceSlug"),
    memoryScopeExternalRef: requiredWorkflowText(
      input.sourceMemoryScopeExternalRef,
      "transferMemorySnapshot requires sourceMemoryScopeExternalRef",
    ),
  };
}

function snapshotTarget(input: TransferMemorySnapshotInput): MemorySnapshotTransferEndpoint {
  const targetSpaceSlug = input.targetSpaceSlug ?? input.sourceSpaceSlug;
  const targetMemoryScopeExternalRef = input.targetMemoryScopeExternalRef ?? input.sourceMemoryScopeExternalRef;
  return {
    spaceSlug: requiredWorkflowText(targetSpaceSlug, "transferMemorySnapshot requires targetSpaceSlug"),
    memoryScopeExternalRef: requiredWorkflowText(
      targetMemoryScopeExternalRef,
      "transferMemorySnapshot requires targetMemoryScopeExternalRef",
    ),
  };
}

function validateSnapshotTransfer(input: TransferMemorySnapshotInput, mode: MemorySnapshotTransferMode): void {
  if (mode === "confirmed_import" && input.confirmed !== true) {
    throw new ValueError("confirmed_import requires confirmed: true");
  }
  if (mode === "dry_run" && input.confirmed === true) {
    throw new ValueError("dry_run must not set confirmed: true");
  }
}

function snapshotTransferWarnings(
  input: TransferMemorySnapshotInput,
  mode: MemorySnapshotTransferMode,
  source: MemorySnapshotTransferEndpoint,
  target: MemorySnapshotTransferEndpoint,
): readonly string[] {
  const warnings: string[] = [];
  if (mode === "confirmed_import") {
    warnings.push("confirmed_import mutates target memory scope");
  }
  if (input.redacted ?? true) {
    warnings.push("redacted snapshots may omit restricted source fields");
  }
  if (source.spaceSlug === target.spaceSlug && source.memoryScopeExternalRef === target.memoryScopeExternalRef) {
    warnings.push("source and target memory scope are the same");
  }
  return warnings;
}

function snapshotTransferResult(
  source: MemorySnapshotTransferEndpoint,
  target: MemorySnapshotTransferEndpoint,
  snapshot: JsonObject,
  manifest: JsonObject | undefined,
  input: {
    readonly mode: MemorySnapshotTransferMode;
    readonly redacted: boolean;
    readonly mergeStrategy: string;
    readonly warnings: readonly string[];
    readonly preview?: JsonObject;
    readonly importResult?: JsonObject;
  },
): TransferMemorySnapshotResult {
  return {
    source,
    target,
    snapshot,
    ...optional("manifest", manifest),
    ...optional("preview", input.preview),
    ...optional("importResult", input.importResult),
    diagnostics: {
      mode: input.mode,
      mutated: input.mode === "confirmed_import",
      redacted: input.redacted,
      mergeStrategy: input.mergeStrategy,
      warnings: input.warnings,
    },
  };
}

function enabledInspectionSections(input: InspectMemoryInput): readonly string[] {
  const sections = ["memoryBrowser"];
  if (input.includeOperations ?? true) {
    sections.push("operationsConsole");
  }
  if (input.includeUsage ?? true) {
    sections.push("usage");
  }
  if (input.includeCapabilities ?? true) {
    sections.push("capabilities");
  }
  if (input.includeDiagnostics ?? true) {
    sections.push("runtimeDiagnostics");
  }
  if (input.includeGraph === true) {
    sections.push("graph");
  }
  if (input.includeSnapshotPreview === true) {
    sections.push("snapshotPreview");
  }
  return sections;
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

async function optionalInspectionSection<TValue>(
  section: string,
  continueOnError: boolean,
  issues: InspectMemoryIssue[],
  task: () => Promise<TValue>,
  enabled: boolean,
): Promise<TValue | undefined> {
  if (!enabled) {
    return undefined;
  }

  try {
    return await task();
  } catch (error) {
    if (!continueOnError) {
      throw error;
    }
    issues.push({ section, error: workflowErrorData(error) });
    return undefined;
  }
}

async function inspectRuntimeDiagnostics(
  resources: MemoryInspectionResources,
  input: InspectMemoryInput,
  controls: RequestControls,
  continueOnError: boolean,
  issues: InspectMemoryIssue[],
): Promise<InspectMemoryRuntimeDiagnostics> {
  const [adapters, metrics, storage, memoryScope] = await Promise.all([
    optionalInspectionSection("diagnostics.adapters", continueOnError, issues, () =>
      resources.diagnostics.adapters(controls),
    true),
    optionalInspectionSection("diagnostics.metrics", continueOnError, issues, () =>
      resources.diagnostics.metrics(controls),
    true),
    optionalInspectionSection("diagnostics.storage", continueOnError, issues, () =>
      resources.diagnostics.storage(controls),
    true),
    optionalInspectionSection("diagnostics.memoryScope", continueOnError, issues, () =>
      resources.diagnostics.memoryScope(input.memoryScopeId ?? "", controls),
    input.memoryScopeId !== undefined),
  ]);

  return {
    ...(adapters ? { adapters } : {}),
    ...(metrics ? { metrics } : {}),
    ...(storage ? { storage } : {}),
    ...(memoryScope ? { memoryScope } : {}),
  };
}

async function previewMemorySnapshot(
  resources: MemoryInspectionResources,
  input: InspectMemoryInput,
  controls: RequestControls,
  warnings: string[],
): Promise<MemorySnapshotPreviewBundle> {
  if (!input.spaceSlug || !input.memoryScopeExternalRef) {
    warnings.push("snapshotPreview requires spaceSlug and memoryScopeExternalRef");
    throw new ValueError("snapshotPreview requires spaceSlug and memoryScopeExternalRef");
  }

  const snapshot = await resources.exports.exportMemoryScopeSnapshot({
    ...controls,
    spaceSlug: input.spaceSlug,
    memoryScopeExternalRef: input.memoryScopeExternalRef,
    redacted: true,
  });
  const snapshotData = jsonObjectField(snapshot, "data");
  if (snapshotData === undefined) {
    throw new ValueError("Snapshot export response did not include data");
  }

  const snapshotPreview = await resources.exports.previewMemoryScopeSnapshotImport({
    ...controls,
    spaceSlug: input.spaceSlug,
    memoryScopeExternalRef: input.memoryScopeExternalRef,
    snapshot: snapshotData,
    ...optional("manifest", jsonObjectField(snapshot, "manifest")),
    ...optional("mergeStrategy", input.snapshotMergeStrategy),
  });

  return { snapshot, snapshotPreview };
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

function memoryBrowserScopeInput(input: SingleScopeInput): Omit<SingleScopeInput, "threadId" | "threadExternalRef"> {
  return {
    ...optional("spaceId", input.spaceId),
    ...optional("memoryScopeId", input.memoryScopeId),
    ...optional("spaceSlug", input.spaceSlug),
    ...optional("memoryScopeExternalRef", input.memoryScopeExternalRef),
  };
}

function sourceEvidenceRefs(input: RecordSourceEvidenceInput): readonly SourceRef[] {
  if (input.sourceRefs && input.sourceRefs.length > 0) {
    return input.sourceRefs;
  }
  return [{ source_type: input.sourceType, source_id: input.sourceId }];
}

function feedbackSourceRefs(input: RecordMemoryFeedbackInput): readonly SourceRef[] {
  if (input.sourceRefs && input.sourceRefs.length > 0) {
    return input.sourceRefs;
  }
  return [{ source_type: input.sourceAgent, source_id: input.sourceId ?? input.idempotencyKey }];
}

function singleScopeInput(input: SingleScopeInput): SingleScopeInput {
  return {
    ...optional("spaceId", input.spaceId),
    ...optional("memoryScopeId", input.memoryScopeId),
    ...optional("threadId", input.threadId),
    ...optional("spaceSlug", input.spaceSlug),
    ...optional("memoryScopeExternalRef", input.memoryScopeExternalRef),
    ...optional("threadExternalRef", input.threadExternalRef),
  };
}

function workflowControls(input: RequestControls): RequestControls {
  return {
    ...optional("headers", input.headers),
    ...optional("signal", input.signal),
  };
}

function withWorkflowControls<TInput extends RequestControls>(
  batchControls: RequestControls,
  input: TInput,
): TInput {
  return {
    ...input,
    ...mergeWorkflowControls(batchControls, input),
  };
}

function mergeWorkflowControls(parent: RequestControls, child: RequestControls): RequestControls {
  const headers = parent.headers === undefined && child.headers === undefined
    ? undefined
    : { ...parent.headers, ...child.headers };

  return {
    ...optional("headers", headers),
    ...optional("signal", child.signal ?? parent.signal),
  };
}

function factScopeInput(input: RecordMemoryFeedbackInput): RememberFactInput {
  return {
    ...singleScopeInput(input),
    ...optional("memoryScopeExternalRef", input.factMemoryScopeExternalRef ?? input.memoryScopeExternalRef),
    text: input.factText ?? input.text,
    sourceRefs: feedbackSourceRefs(input),
  };
}

function readScopeInput(input: ReadScopeInput & { readonly readScope?: ReadScope }): ReadScopeInput & {
  readonly readScope?: ReadScope;
} {
  return {
    ...optional("readScope", input.readScope),
    ...optional("spaceId", input.spaceId),
    ...optional("memoryScopeIds", input.memoryScopeIds),
    ...optional("threadId", input.threadId),
    ...optional("spaceSlug", input.spaceSlug),
    ...optional("memoryScopeExternalRef", input.memoryScopeExternalRef),
    ...optional("memoryScopeExternalRefs", input.memoryScopeExternalRefs),
    ...optional("threadExternalRef", input.threadExternalRef),
  };
}

function briefDiagnostics(
  context: ContextEnvelope<ContextBundleData>,
  search?: ContextEnvelope<SearchMemoryData>,
): MemoryBriefDiagnostics {
  const contextDiagnostics = context.data.diagnostics;
  const searchDiagnostics = search?.data.diagnostics;
  return {
    derivedRetrievalUsed: usedDerivedRetrieval(contextDiagnostics)
      || (searchDiagnostics ? usedDerivedRetrieval(searchDiagnostics) : false),
    vectorHealthy: healthyRetrievalComponents(contextDiagnostics, ["vector"])
      || (searchDiagnostics ? healthyRetrievalComponents(searchDiagnostics, ["vector"]) : false),
    graphHealthy: healthyRetrievalComponents(contextDiagnostics, ["graph"])
      || (searchDiagnostics ? healthyRetrievalComponents(searchDiagnostics, ["graph"]) : false),
    ragHealthy: healthyRetrievalComponents(contextDiagnostics, ["rag"])
      || (searchDiagnostics ? healthyRetrievalComponents(searchDiagnostics, ["rag"]) : false),
    retrievalSourcesUsed: uniqueStrings([
      ...(contextDiagnostics.retrieval_sources_used ?? []),
      ...(searchDiagnostics?.retrieval_sources_used ?? []),
    ]),
    warnings: context.data.answer_support.warnings,
  };
}

function uniqueStrings(values: readonly string[]): readonly string[] {
  return [...new Set(values)];
}

function isEnabled<TOptions extends object>(
  value: WorkflowStepOptions<TOptions> | undefined,
  defaultValue: boolean,
): boolean {
  return value === undefined ? defaultValue : value !== false;
}

function stepOptions<TOptions extends object>(
  value: WorkflowStepOptions<TOptions> | undefined,
): Partial<TOptions> {
  return typeof value === "object" ? value : {};
}

function requiredStepOptions<TOptions extends object>(
  value: WorkflowStepOptions<TOptions> | undefined,
  message: string,
): TOptions {
  if (typeof value !== "object" || value === null) {
    throw new ValueError(message);
  }
  return value;
}

function stringField(input: JsonObject, key: string): string | undefined {
  const value = input[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function requiredWorkflowText(value: string | undefined, message: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ValueError(message);
  }
  return value;
}

function jsonObjectField(input: JsonObject, key: string): JsonObject | undefined {
  const value = input[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

function normalizeBatchConcurrency(value: number | undefined): number {
  if (value === undefined) {
    return 4;
  }
  if (!Number.isInteger(value) || value < 1 || value > 25) {
    throw new ValueError("recordSourceEvidenceBatch concurrency must be an integer from 1 to 25");
  }
  return value;
}

function batchItemResult(
  index: number,
  input: RecordSourceEvidenceInput,
  outcome: { readonly result: RecordSourceEvidenceResult } | { readonly error: MemoryWorkflowErrorData },
): RecordSourceEvidenceBatchItemResult {
  return {
    index,
    sourceType: input.sourceType,
    sourceId: input.sourceId,
    idempotencyKey: input.idempotencyKey,
    ok: "result" in outcome,
    ...("result" in outcome ? { result: outcome.result } : { error: outcome.error }),
  };
}

function workflowErrorData(error: unknown): MemoryWorkflowErrorData {
  const record = typeof error === "object" && error !== null ? error as Record<string, unknown> : {};
  const message = error instanceof Error ? error.message : String(error);
  const name = error instanceof Error ? error.name : "Error";
  const code = typeof record.code === "string" ? record.code : undefined;
  const statusCode = typeof record.statusCode === "number" ? record.statusCode : undefined;
  const retryable = typeof record.retryable === "boolean" ? record.retryable : undefined;
  const requestId = typeof record.requestId === "string" ? record.requestId : undefined;

  return {
    name,
    message,
    ...(code === undefined ? {} : { code }),
    ...(statusCode === undefined ? {} : { statusCode }),
    ...(retryable === undefined ? {} : { retryable }),
    ...(requestId === undefined ? {} : { requestId }),
  };
}

function workflowConflict(error: unknown): boolean {
  return error instanceof InfinityContextError && error.statusCode === 409;
}

function isDefined<TValue>(value: TValue | undefined): value is TValue {
  return value !== undefined;
}

function ratio(value: number, total: number): number {
  return total <= 0 ? 0 : value / total;
}

function incrementCount(counts: Record<string, number>, key: string): void {
  counts[key] = (counts[key] ?? 0) + 1;
}

function optional<TKey extends string, TValue>(
  key: TKey,
  value: TValue | undefined,
): { readonly [K in TKey]?: TValue } {
  return value === undefined ? {} : { [key]: value } as { readonly [K in TKey]: TValue };
}
