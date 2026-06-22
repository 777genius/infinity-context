import type { RequestControls } from "../client.js";
import type { ContextEnvelope, ContextBundleData, MemoryDigestData, SearchMemoryData } from "../context-types.js";
import {
  healthyRetrievalComponents,
  usedDerivedRetrieval,
  type ContextRetrievalComponent,
} from "../diagnostics.js";
import { ValueError, type ReadScope, type ReadScopeInput, type SingleScopeInput } from "../payload.js";
import type { AnchorsClient } from "../resources/anchors.js";
import type { AssetsClient } from "../resources/assets.js";
import type { CapturesClient, CreateCaptureData, CreateCaptureInput } from "../resources/captures.js";
import type { ContextLinksClient } from "../resources/context-links.js";
import type { BuildContextInput, BuildDigestInput, ContextClient } from "../resources/context.js";
import type { DiagnosticsClient, OutboxDrainResult, WaitForOutboxDrainInput } from "../resources/diagnostics.js";
import type { DocumentsClient } from "../resources/documents.js";
import type { ExportsClient } from "../resources/exports.js";
import type { FactsClient, RememberFactInput } from "../resources/facts.js";
import type { ReadModelsClient } from "../resources/read-models.js";
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
  FactRecord,
  InfinityContextCapabilities,
  JsonObject,
  SourceRef,
} from "../types.js";
import {
  isEnabled,
  optional,
  requiredStepOptions,
  requiredWorkflowText,
  singleScopeInput,
  stepOptions,
  uniqueStrings,
  workflowControls,
  withWorkflowControls,
  type WorkflowStepOptions,
} from "./workflow-helpers.js";
import {
  assertMemoryBriefQuality,
  summarizeMemoryBriefEvidence,
  type MemoryBriefEvidenceSummary,
  type MemoryBriefQualityPolicy,
  type MemoryBriefQualityReport,
} from "./memory-brief-quality.js";
import {
  ensureMemoryTopology as ensureMemoryTopologyWorkflow,
  type EnsureMemoryTopologyInput,
  type EnsureMemoryTopologyResult,
  type MemoryTopologyResources,
} from "./memory-topology.js";
import {
  transferMemorySnapshot as transferMemorySnapshotWorkflow,
  type TransferMemorySnapshotInput,
  type TransferMemorySnapshotResult,
} from "./memory-snapshot-transfer.js";
import {
  inspectMemory as inspectMemoryWorkflow,
  type InspectMemoryInput,
  type InspectMemoryResult,
} from "./memory-inspection.js";
import {
  planMemoryMaintenance as planMemoryMaintenanceWorkflow,
  type PlanMemoryMaintenanceInput,
  type PlanMemoryMaintenanceResult,
} from "./memory-maintenance.js";
import {
  recordSourceEvidence as recordSourceEvidenceWorkflow,
  recordSourceEvidenceBatch as recordSourceEvidenceBatchWorkflow,
  summarizeSourceEvidenceBatch,
  type RecordSourceEvidenceBatchInput,
  type RecordSourceEvidenceBatchResult,
  type RecordSourceEvidenceBatchSummary,
  type RecordSourceEvidenceInput,
  type RecordSourceEvidenceResult,
  type MemoryWorkflowErrorData,
} from "./memory-source-evidence.js";

export {
  assertMemoryBriefQuality,
  evaluateMemoryBriefQuality,
  summarizeMemoryBriefEvidence,
} from "./memory-brief-quality.js";
export {
  summarizeSourceEvidenceBatch,
} from "./memory-source-evidence.js";
export type {
  InspectMemoryDiagnostics,
  InspectMemoryInput,
  InspectMemoryIssue,
  InspectMemoryResult,
  InspectMemoryRuntimeDiagnostics,
} from "./memory-inspection.js";
export type {
  MemoryMaintenanceAction,
  MemoryMaintenanceActionKind,
  MemoryMaintenanceDiagnostics,
  MemoryMaintenanceQueues,
  MemoryMaintenanceSummary,
  PlanMemoryMaintenanceInput,
  PlanMemoryMaintenanceResult,
} from "./memory-maintenance.js";
export type {
  EnsureMemoryScopeInput,
  EnsureMemoryTopologyCreated,
  EnsureMemoryTopologyDiagnostics,
  EnsureMemoryTopologyInput,
  EnsureMemoryTopologyResult,
  EnsureMemoryUserInput,
} from "./memory-topology.js";
export type {
  MemorySnapshotTransferDiagnostics,
  MemorySnapshotTransferEndpoint,
  MemorySnapshotTransferMode,
  TransferMemorySnapshotInput,
  TransferMemorySnapshotResult,
} from "./memory-snapshot-transfer.js";
export type {
  MemoryBriefEvidenceSourceRef,
  MemoryBriefEvidenceSummary,
  MemoryBriefEvidenceSurface,
  MemoryBriefQualityMetrics,
  MemoryBriefQualityPolicy,
  MemoryBriefQualityReport,
} from "./memory-brief-quality.js";
export type {
  MemoryWorkflowErrorData,
  RecordSourceEvidenceBatchFailure,
  RecordSourceEvidenceBatchInput,
  RecordSourceEvidenceBatchItemResult,
  RecordSourceEvidenceBatchResult,
  RecordSourceEvidenceBatchSummary,
  RecordSourceEvidenceCaptureOptions,
  RecordSourceEvidenceDocumentOptions,
  RecordSourceEvidenceEpisodeOptions,
  RecordSourceEvidenceFactOptions,
  RecordSourceEvidenceInput,
  RecordSourceEvidenceLinkSuggestionOptions,
  RecordSourceEvidenceResult,
} from "./memory-source-evidence.js";
export type {
  WorkflowStepOptions,
} from "./workflow-helpers.js";

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

export interface SeedMemoryFactInput extends SingleScopeInput, RequestControls {
  readonly text: string;
  readonly sourceRefs?: readonly SourceRef[];
  readonly idempotencyKey?: string;
  readonly kind?: string;
  readonly classification?: string;
  readonly category?: string;
  readonly tags?: readonly string[];
  readonly ttlPolicy?: string;
}

export interface SeedMemoryAndBuildBriefInput extends SingleScopeInput, RequestControls {
  readonly facts?: readonly SeedMemoryFactInput[];
  readonly idempotencyKeyPrefix?: string;
  readonly sourceType?: string;
  readonly sourceIdPrefix?: string;
  readonly topology?: WorkflowStepOptions<EnsureMemoryTopologyInput>;
  readonly outboxDrain?: WorkflowStepOptions<WaitForOutboxDrainInput>;
  readonly brief: BuildMemoryBriefInput;
}

export interface SeedMemoryDiagnostics {
  readonly total: number;
  readonly remembered: number;
  readonly factIds: readonly string[];
  readonly warnings: readonly string[];
}

export interface SeedMemoryAndBuildBriefDiagnostics {
  readonly ok: boolean;
  readonly seededFactsOk: boolean;
  readonly outboxDrainOk: boolean | null;
  readonly warnings: readonly string[];
}

export interface SeedMemoryAndBuildBriefResult {
  readonly topology?: EnsureMemoryTopologyResult;
  readonly facts: readonly ApiEnvelope<FactRecord>[];
  readonly outboxDrain?: OutboxDrainResult;
  readonly brief: BuildMemoryBriefResult;
  readonly seed: SeedMemoryDiagnostics;
  readonly diagnostics: SeedMemoryAndBuildBriefDiagnostics;
}

export interface RunMemorySummaryLoopInput extends RequestControls {
  readonly topology?: WorkflowStepOptions<EnsureMemoryTopologyInput>;
  readonly readiness?: WorkflowStepOptions<CheckFullMemoryReadinessInput>;
  readonly sourceEvidence?: RecordSourceEvidenceBatchInput;
  readonly outboxDrain?: WorkflowStepOptions<WaitForOutboxDrainInput>;
  readonly brief: BuildMemoryBriefInput;
  readonly qualityPolicy?: MemoryBriefQualityPolicy;
  readonly stopOnSourceEvidenceFailure?: boolean;
}

export interface RunMemorySummaryLoopDiagnostics {
  readonly ok: boolean;
  readonly readinessOk: boolean | null;
  readonly sourceEvidenceOk: boolean | null;
  readonly outboxDrainOk: boolean | null;
  readonly qualityOk: boolean | null;
  readonly warnings: readonly string[];
}

export interface RunMemorySummaryLoopResult {
  readonly topology?: EnsureMemoryTopologyResult;
  readonly readiness?: CheckFullMemoryReadinessResult;
  readonly sourceEvidence?: RecordSourceEvidenceBatchResult;
  readonly sourceEvidenceSummary?: RecordSourceEvidenceBatchSummary;
  readonly outboxDrain?: OutboxDrainResult;
  readonly brief: BuildMemoryBriefResult;
  readonly quality?: MemoryBriefQualityReport;
  readonly evidenceSummary: MemoryBriefEvidenceSummary;
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
    return recordSourceEvidenceWorkflow(this.resources, input);
  }

  async recordSourceEvidenceBatch(
    input: RecordSourceEvidenceBatchInput,
  ): Promise<RecordSourceEvidenceBatchResult> {
    return recordSourceEvidenceBatchWorkflow(this.resources, input);
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

  async seedMemoryAndBuildBrief(input: SeedMemoryAndBuildBriefInput): Promise<SeedMemoryAndBuildBriefResult> {
    const topology = isEnabled(input.topology, false)
      ? await this.ensureMemoryTopology(withWorkflowControls(
          input,
          requiredStepOptions(input.topology, "seedMemoryAndBuildBrief topology requires options"),
        ))
      : undefined;
    const facts = await this.seedMemoryFacts(input);
    const outboxDrain = isEnabled(input.outboxDrain, false)
      ? await diagnosticsResource(this.resources, "seedMemoryAndBuildBrief outboxDrain")
        .waitForOutboxDrain(withWorkflowControls(input, stepOptions(input.outboxDrain)))
      : undefined;
    const brief = await this.buildMemoryBrief(withWorkflowControls(input, input.brief));
    const outboxDrainOk = outboxDrain === undefined
      ? null
      : outboxDrain.diagnostics.blocking_count <= outboxDrain.diagnostics.max_blocking_items;
    const seed = seedMemoryDiagnostics(input, facts);
    const warnings = uniqueStrings([
      ...(topology?.diagnostics.warnings ?? []),
      ...seed.warnings,
      ...(outboxDrain !== undefined && !outboxDrainOk
        ? [`outbox still has ${outboxDrain.diagnostics.blocking_count} blocking item(s)`]
        : []),
      ...brief.diagnostics.warnings,
    ]);

    return {
      ...(topology ? { topology } : {}),
      facts,
      ...(outboxDrain ? { outboxDrain } : {}),
      brief,
      seed,
      diagnostics: {
        ok: seed.remembered === seed.total && (outboxDrainOk ?? true),
        seededFactsOk: seed.remembered === seed.total,
        outboxDrainOk,
        warnings,
      },
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

    const outboxDrain = isEnabled(input.outboxDrain, false)
      ? await diagnosticsResource(this.resources, "runMemorySummaryLoop outboxDrain")
        .waitForOutboxDrain(withWorkflowControls(input, stepOptions(input.outboxDrain)))
      : undefined;
    const brief = await this.buildMemoryBrief(withWorkflowControls(input, input.brief));
    const quality = input.qualityPolicy === undefined
      ? undefined
      : assertMemoryBriefQuality(brief, input.qualityPolicy);
    const evidenceSummary = summarizeMemoryBriefEvidence(brief);
    const readinessOk = readiness?.readiness.ok ?? null;
    const sourceEvidenceOk = sourceEvidenceSummary === undefined
      ? null
      : sourceEvidenceSummary.failed === 0 && !sourceEvidenceSummary.stopped;
    const outboxDrainOk = outboxDrain === undefined
      ? null
      : outboxDrain.diagnostics.blocking_count <= outboxDrain.diagnostics.max_blocking_items;
    const qualityOk = quality?.ok ?? null;
    const warnings = uniqueStrings([
      ...(readiness?.diagnostics.warnings ?? []),
      ...(sourceEvidenceSummary !== undefined && !sourceEvidenceOk
        ? [`source evidence batch has ${sourceEvidenceSummary.failed} failed item(s)`]
        : []),
      ...(outboxDrain !== undefined && !outboxDrainOk
        ? [`outbox still has ${outboxDrain.diagnostics.blocking_count} blocking item(s)`]
        : []),
      ...brief.diagnostics.warnings,
    ]);

    return {
      ...(topology ? { topology } : {}),
      ...(readiness ? { readiness } : {}),
      ...(sourceEvidence ? { sourceEvidence } : {}),
      ...(sourceEvidenceSummary ? { sourceEvidenceSummary } : {}),
      ...(outboxDrain ? { outboxDrain } : {}),
      brief,
      ...(quality ? { quality } : {}),
      evidenceSummary,
      diagnostics: {
        ok: (readinessOk ?? true) && (sourceEvidenceOk ?? true) && (outboxDrainOk ?? true) && (qualityOk ?? true),
        readinessOk,
        sourceEvidenceOk,
        outboxDrainOk,
        qualityOk,
        warnings,
      },
    };
  }

  private async seedMemoryFacts(input: SeedMemoryAndBuildBriefInput): Promise<readonly ApiEnvelope<FactRecord>[]> {
    const seeds = [...(input.facts ?? [])];
    if (seeds.length > 100) {
      throw new ValueError("seedMemoryAndBuildBrief supports at most 100 seed facts");
    }

    const remembered: ApiEnvelope<FactRecord>[] = [];
    for (const [index, seed] of seeds.entries()) {
      const scopedSeed = withWorkflowControls(input, seed);
      remembered.push(await this.resources.facts.rememberFact({
        ...seedFactScopeInput(input, seed),
        ...workflowControls(scopedSeed),
        text: seed.text,
        kind: seed.kind ?? "memory_seed",
        classification: seed.classification ?? "internal",
        category: seed.category ?? "memory_seed",
        tags: seed.tags ?? ["memory_seed"],
        ttlPolicy: seed.ttlPolicy ?? "durable",
        sourceRefs: seed.sourceRefs ?? seedMemorySourceRefs(input, index),
        idempotencyKey: seedMemoryIdempotencyKey(input, seed, index),
      }));
    }

    return remembered;
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
    return ensureMemoryTopologyWorkflow(topologyResources(this.resources), input);
  }

  async inspectMemory(input: InspectMemoryInput = {}): Promise<InspectMemoryResult> {
    return inspectMemoryWorkflow(this.resources, input);
  }

  async planMemoryMaintenance(input: PlanMemoryMaintenanceInput = {}): Promise<PlanMemoryMaintenanceResult> {
    return planMemoryMaintenanceWorkflow(this.resources, input);
  }

  async transferMemorySnapshot(input: TransferMemorySnapshotInput): Promise<TransferMemorySnapshotResult> {
    return transferMemorySnapshotWorkflow(snapshotResources(this.resources), input);
  }
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

function diagnosticsResource(resources: MemoryWorkflowResources, operationName: string): DiagnosticsClient {
  if (resources.diagnostics === undefined) {
    throw new ValueError(`${operationName} requires MemoryWorkflowResources: diagnostics`);
  }
  return resources.diagnostics;
}

function snapshotResources(resources: MemoryWorkflowResources): ExportsClient {
  const exportsClient = resources.exports;
  if (exportsClient === undefined) {
    throw new ValueError("transferMemorySnapshot requires MemoryWorkflowResources: exports");
  }
  return exportsClient;
}

function feedbackSourceRefs(input: RecordMemoryFeedbackInput): readonly SourceRef[] {
  if (input.sourceRefs && input.sourceRefs.length > 0) {
    return input.sourceRefs;
  }
  return [{ source_type: input.sourceAgent, source_id: input.sourceId ?? input.idempotencyKey }];
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

function seedMemoryDiagnostics(
  input: SeedMemoryAndBuildBriefInput,
  facts: readonly ApiEnvelope<FactRecord>[],
): SeedMemoryDiagnostics {
  const total = input.facts?.length ?? 0;
  return {
    total,
    remembered: facts.length,
    factIds: facts.map((fact) => fact.data.id),
    warnings: total === 0 ? ["no seed facts provided"] : [],
  };
}

function seedFactScopeInput(
  input: SeedMemoryAndBuildBriefInput,
  seed: SeedMemoryFactInput,
): SingleScopeInput {
  return {
    ...optional("spaceId", seed.spaceId ?? input.spaceId),
    ...optional("memoryScopeId", seed.memoryScopeId ?? input.memoryScopeId),
    ...optional("threadId", seed.threadId ?? input.threadId),
    ...optional("spaceSlug", seed.spaceSlug ?? input.spaceSlug),
    ...optional("memoryScopeExternalRef", seed.memoryScopeExternalRef ?? input.memoryScopeExternalRef),
    ...optional("threadExternalRef", seed.threadExternalRef ?? input.threadExternalRef),
  };
}

function seedMemoryIdempotencyKey(
  input: SeedMemoryAndBuildBriefInput,
  seed: SeedMemoryFactInput,
  index: number,
): string {
  if (seed.idempotencyKey !== undefined) {
    return seed.idempotencyKey;
  }

  return `${requiredWorkflowText(
    input.idempotencyKeyPrefix,
    "seedMemoryAndBuildBrief seed facts require idempotencyKey or idempotencyKeyPrefix",
  )}:fact:${index}`;
}

function seedMemorySourceRefs(
  input: SeedMemoryAndBuildBriefInput,
  index: number,
): readonly SourceRef[] {
  const sourceIdPrefix = input.sourceIdPrefix ?? input.idempotencyKeyPrefix ?? "seedMemoryAndBuildBrief";
  return [{
    source_type: input.sourceType ?? "memory_seed",
    source_id: `${sourceIdPrefix}:fact:${index}`,
  }];
}
