import { InfinityContextClient } from "./infinity-context-client.js";
import type { ContextBundleData, ContextDiagnostics, ContextEnvelope } from "./context-types.js";
import {
  healthyRetrievalComponents,
  retrievalDiagnostics,
  usedDerivedRetrieval,
  type ContextRetrievalDiagnostics,
} from "./diagnostics.js";
import { copyInfinityContextError, type InfinityContextError, networkError } from "./errors.js";
import { ReadScope } from "./payload.js";
import {
  summarizeSourceEvidenceBatch,
  type RecordSourceEvidenceBatchSummary,
} from "./workflows/memory.js";
import type { OutboxDrainDiagnostics } from "./resources/diagnostics.js";
import type {
  AnchorRecord,
  DocumentRecord,
  FactRecord,
  InfinityContextCapabilities,
  JsonObject,
} from "./types.js";

export interface FullMemoryProofOptions {
  readonly client: InfinityContextClient;
  readonly runId?: string | undefined;
  readonly requireFullMemory?: boolean | undefined;
  readonly pollAttempts?: number | undefined;
  readonly pollDelayMs?: number | undefined;
  readonly outboxDrainAttempts?: number | undefined;
  readonly outboxDrainDelayMs?: number | undefined;
  readonly sleep?: ((ms: number) => Promise<void>) | undefined;
  readonly now?: (() => Date) | undefined;
}

export interface FullMemoryProofReport {
  readonly ok: boolean;
  readonly runId: string;
  readonly spaceSlug: string;
  readonly memoryScopeExternalRefs: readonly string[];
  readonly checks: {
    readonly capabilitiesFullMemory: boolean;
    readonly contextReturnedEvidence: boolean;
    readonly searchReturnedEvidence: boolean;
    readonly digestReturnedEvidence: boolean;
    readonly contextLinkCreated: boolean;
    readonly captureCreated: boolean;
    readonly suggestionBatchCreated: boolean;
    readonly sourceEvidenceBatchRecorded: boolean;
    readonly sourceEvidenceBatchSummarized: boolean;
    readonly anchorCreated: boolean;
    readonly anchorBackfillReadable: boolean;
    readonly memoryBrowserReadable: boolean;
    readonly memoryInspectionReadable: boolean;
    readonly maintenancePlanReadable: boolean;
    readonly operationsConsoleReadable: boolean;
    readonly outboxDrained: boolean;
    readonly usageReadable: boolean;
    readonly snapshotPreviewSucceeded: boolean;
    readonly derivedRetrievalUsed: boolean;
    readonly vectorHealthy: boolean;
    readonly graphHealthy: boolean;
  };
  readonly created: {
    readonly spaceId: string;
    readonly memoryScopeIds: readonly string[];
    readonly factIds: readonly string[];
    readonly documentId: string;
    readonly episodeId: string;
    readonly contextLinkId: string;
    readonly captureId: string;
    readonly anchorId: string;
  };
  readonly observed: {
    readonly suggestionsCreated: number;
    readonly anchorBackfillCreated: number;
    readonly anchorMergeSuggestionCount: number;
    readonly memoryBrowserStats: JsonObject;
    readonly memoryInspectionIssueCount: number;
    readonly memoryInspectionSections: readonly string[];
    readonly maintenanceActionableCount: number;
    readonly maintenanceIssueCount: number;
    readonly operationsDiagnostics: JsonObject;
    readonly outboxDrainDiagnostics: OutboxDrainDiagnostics;
    readonly usageResourceCount: number;
    readonly snapshotPreview: JsonObject;
    readonly sourceEvidenceBatchSummary: RecordSourceEvidenceBatchSummary;
  };
  readonly capabilities: {
    readonly enabledAdapters: readonly string[];
    readonly supportsQdrant: boolean;
    readonly supportsGraphiti: boolean;
  };
  readonly retrieval: {
    readonly vector: ContextRetrievalDiagnostics;
    readonly graph: ContextRetrievalDiagnostics;
    readonly rag: ContextRetrievalDiagnostics;
  };
  readonly contextDiagnostics: ContextDiagnostics;
  readonly searchDiagnostics: ContextDiagnostics;
  readonly digestDiagnostics: JsonObject;
}

const defaultPollAttempts = 6;
const defaultPollDelayMs = 2_000;
const defaultOutboxDrainAttempts = 12;
const defaultOutboxDrainDelayMs = 1_000;

export async function runFullMemoryProof(options: FullMemoryProofOptions): Promise<FullMemoryProofReport> {
  const now = options.now ?? (() => new Date());
  const runId = safeRunId(options.runId ?? `sdk-${now().toISOString()}`);
  const spaceSlug = `sdk-full-memory-proof:${runId}`;
  const memoryScopeExternalRefs = [
    "workspace-global",
    "topic:full-memory-proof:feedback",
    "source:full-memory-proof-transcript",
  ] as const;
  const readScope = ReadScope.external({
    spaceSlug,
    memoryScopeExternalRefs,
  });
  const capabilities = await options.client.system.capabilities();
  const capabilitiesFullMemory = hasFullMemoryCapabilities(capabilities);
  const topology = await options.client.workflows.ensureMemoryTopology({
    spaceSlug,
    spaceName: `SDK full memory proof ${runId}`,
    memoryScopes: memoryScopeExternalRefs.map((externalRef) => ({ externalRef, name: externalRef })),
  });
  const space = topology.space;
  const scopes = topology.memoryScopes;

  const facts = await Promise.all([
    options.client.facts.rememberFact({
      spaceSlug,
      memoryScopeExternalRef: "workspace-global",
      text: `${runId}: Qdrant owns vector recall, Graphiti owns temporal graph memory, and OpenAI embeddings create derived retrieval vectors.`,
      kind: "architecture_decision",
      category: "full_memory_proof",
      tags: ["full-memory-proof", "qdrant", "graphiti", "openai-embeddings"],
      ttlPolicy: "durable",
      sourceRefs: [{ source_type: "sdk-full-memory-proof", source_id: `${runId}:architecture` }],
      idempotencyKey: `${runId}:fact:architecture`,
    }),
    options.client.facts.rememberFact({
      spaceSlug,
      memoryScopeExternalRef: "topic:full-memory-proof:feedback",
      text: `${runId}: User prefers concise summaries that call out source freshness, degraded retrieval, and missing evidence.`,
      kind: "user_preference",
      category: "summary_preference",
      tags: ["full-memory-proof", "summary-feedback"],
      ttlPolicy: "durable",
      sourceRefs: [{ source_type: "sdk-full-memory-proof", source_id: `${runId}:feedback` }],
      idempotencyKey: `${runId}:fact:feedback`,
    }),
    options.client.facts.rememberFact({
      spaceSlug,
      memoryScopeExternalRef: "source:full-memory-proof-transcript",
      text: `${runId}: Source transcript says Qdrant handles semantic recall while Graphiti preserves temporal updates.`,
      kind: "note",
      category: "source_evidence",
      tags: ["full-memory-proof", "source-evidence"],
      ttlPolicy: "durable",
      sourceRefs: [{ source_type: "sdk-full-memory-proof", source_id: `${runId}:source-fact` }],
      idempotencyKey: `${runId}:fact:source`,
    }),
  ]);
  const document = await options.client.documents.ingestDocument({
    spaceSlug,
    memoryScopeExternalRef: "source:full-memory-proof-transcript",
    title: `${runId} full memory source note`,
    text: [
      `${runId}: Durable source note for full memory proof.`,
      "The monitoring product should retrieve daily social intelligence through Qdrant vector recall and Graphiti temporal graph recall.",
      "The summary should mention freshness, degraded provider evidence, and concise operator action.",
    ].join("\n"),
    sourceExternalId: `${runId}:document`,
    sourceType: "sdk-full-memory-proof",
    classification: "internal",
    sourceRefs: [{ source_type: "sdk-full-memory-proof", source_id: `${runId}:document` }],
    idempotencyKey: `${runId}:document`,
  });
  await options.client.documents.processDocument(document.data.id, {
    idempotencyKey: `${runId}:document:process`,
  });
  const episode = await options.client.documents.ingestEpisode({
    spaceSlug,
    memoryScopeExternalRef: "source:full-memory-proof-transcript",
    threadExternalRef: `${runId}:source-thread`,
    sourceExternalId: `${runId}:episode`,
    sourceType: "sdk-full-memory-proof",
    text: `${runId}: Later update: Graphiti should preserve temporal changes while Qdrant handles semantic document recall.`,
    occurredAt: now().toISOString(),
    speaker: "assistant",
    trustLevel: "high",
    kindHint: "fact_evidence",
    metadata: { run_id: runId },
    idempotencyKey: `${runId}:episode`,
  });
  const contextLink = await options.client.contextLinks.createContextLink({
    spaceSlug,
    memoryScopeExternalRef: "source:full-memory-proof-transcript",
    sourceType: "document",
    sourceId: document.data.id,
    targetType: "fact",
    targetId: facts[2]?.data.id ?? "unknown",
    relationType: "supports",
    confidence: "high",
    reason: `${runId}: SDK proof links document evidence to durable architecture fact.`,
    metadata: { run_id: runId, proof: "full-memory" },
  });
  const capture = await options.client.captures.createCapture({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    threadExternalRef: `${runId}:feedback-thread`,
    sourceAgent: "infinity-context-ts-sdk",
    sourceKind: "hook",
    eventType: "sdk.full_memory.feedback_recorded",
    actorRole: "system",
    text: `${runId}: Capture proof says daily summaries should show citations, freshness and retrieval degradation.`,
    sourceEventId: `${runId}:capture:feedback`,
    clientInstanceId: "infinity-context-ts-sdk",
    evidenceRefs: [{ source_type: "fact", source_id: facts[1]?.data.id ?? "unknown" }],
    trustLevel: "high",
    sourceAuthority: "tool_verified",
    sensitivity: "medium",
    dataClassification: "internal",
    occurredAt: now().toISOString(),
    metadata: { run_id: runId, proof: "full-memory" },
    traceId: `${runId}:trace`,
    idempotencyKey: `${runId}:capture:feedback`,
    consolidate: false,
  });
  const suggestions = await options.client.suggestions.createSuggestionsBatch({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    continueOnError: false,
    items: [
      {
        candidateText: `${runId}: Summaries should prioritize primary-source citations and stale-source markers.`,
        safeReason: `${runId}: full memory proof suggestion from captured feedback`,
        kind: "user_preference",
        sourceRefs: [{ source_type: "capture", source_id: capture.data.id }],
        trustLevel: "high",
        confidence: "high",
        operation: "add",
        category: "summary_preference",
        tags: ["full-memory-proof", "summary-feedback"],
        candidateFingerprint: `${runId}:suggestion:summary-preference`,
        reviewPayload: { run_id: runId, proof: "full-memory" },
        autoApprove: false,
      },
    ],
  });
  const sourceEvidenceBatch = await options.client.workflows.recordSourceEvidenceBatch({
    concurrency: 1,
    continueOnError: false,
    items: [
      {
        spaceSlug,
        memoryScopeExternalRef: "source:full-memory-proof-transcript",
        threadExternalRef: `${runId}:provider-scan`,
        sourceAgent: "infinity-context-ts-sdk",
        sourceType: "sdk-full-memory-proof",
        sourceId: `${runId}:workflow-source:1`,
        title: `${runId} workflow source evidence 1`,
        text: `${runId}: Workflow batch evidence says provider scans should keep per-item retry diagnostics and citations.`,
        occurredAt: now().toISOString(),
        idempotencyKey: `${runId}:workflow-source:1`,
        metadata: { run_id: runId, proof: "source-evidence-batch", item: 1 },
        episode: { trustLevel: "high", kindHint: "fact_evidence" },
        capture: {
          eventType: "sdk.full_memory.source_evidence_recorded",
          actorRole: "tool",
          trustLevel: "high",
          sourceAuthority: "tool_verified",
          consolidate: true,
        },
        linkSuggestions: { persist: true, limit: 5 },
      },
      {
        spaceSlug,
        memoryScopeExternalRef: "source:full-memory-proof-transcript",
        threadExternalRef: `${runId}:provider-scan`,
        sourceAgent: "infinity-context-ts-sdk",
        sourceType: "sdk-full-memory-proof",
        sourceId: `${runId}:workflow-source:2`,
        title: `${runId} workflow source evidence 2`,
        text: `${runId}: Workflow batch evidence says summaries should expose source freshness and degraded retrieval state.`,
        occurredAt: now().toISOString(),
        idempotencyKey: `${runId}:workflow-source:2`,
        metadata: { run_id: runId, proof: "source-evidence-batch", item: 2 },
        episode: { trustLevel: "high", kindHint: "fact_evidence" },
        capture: {
          eventType: "sdk.full_memory.source_evidence_recorded",
          actorRole: "tool",
          trustLevel: "high",
          sourceAuthority: "tool_verified",
          consolidate: true,
        },
        linkSuggestions: { persist: true, limit: 5 },
      },
    ],
  });
  const sourceEvidenceBatchSummary = summarizeSourceEvidenceBatch(sourceEvidenceBatch);
  const anchor = await ensureAnchor(options.client, {
    spaceSlug,
    memoryScopeExternalRef: "workspace-global",
    kind: "project",
    label: `${runId} full memory proof`,
    aliases: [`${runId} memory graph`],
    description: "SDK full memory proof anchor.",
    confidence: "high",
    evidenceRefs: [{ source_type: "document", source_id: document.data.id }],
    metadata: { run_id: runId, proof: "full-memory" },
  });
  const anchorBackfill = await options.client.anchors.backfillAnchors({
    spaceSlug,
    memoryScopeExternalRef: "workspace-global",
    limitPerSource: 25,
  });
  const anchorMergeSuggestions = await options.client.anchors.listAnchorMergeSuggestions({
    spaceSlug,
    memoryScopeExternalRef: "workspace-global",
    kind: "project",
    limit: 10,
  });
  const outboxDrain = await options.client.diagnostics.waitForOutboxDrain({
    limit: 100,
    maxAttempts: positiveIntegerOr(options.outboxDrainAttempts, defaultOutboxDrainAttempts),
    pollIntervalMs: positiveIntegerOr(options.outboxDrainDelayMs, defaultOutboxDrainDelayMs),
    throwOnFailure: true,
    ...(options.sleep !== undefined ? { sleep: options.sleep } : {}),
  });
  const memoryBrowser = await options.client.readModels.getMemoryBrowser({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    limit: 50,
    captureStatus: "active",
    suggestionStatus: "pending",
  });
  const operationsConsole = await options.client.readModels.getOperationsConsole({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    limit: 25,
  });
  const memoryInspection = await options.client.workflows.inspectMemory({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    limit: 25,
    continueOnError: true,
  });
  const maintenancePlan = await options.client.workflows.planMemoryMaintenance({
    spaceSlug,
    memoryScopeExternalRef: "topic:full-memory-proof:feedback",
    limit: 25,
    continueOnError: true,
  });
  const usage = await options.client.usage.summary({ spaceSlug });
  const snapshotTransfer = await options.client.workflows.transferMemorySnapshot({
    sourceSpaceSlug: spaceSlug,
    sourceMemoryScopeExternalRef: "topic:full-memory-proof:feedback",
    mode: "preview",
    redacted: true,
    mergeStrategy: "fail_on_conflict",
  });

  const query = `${runId} Qdrant Graphiti OpenAI embeddings concise summary freshness degraded retrieval`;
  const context = await pollContext(options, () =>
    options.client.context.buildContext({
      query,
      readScope,
      tokenBudget: 1800,
      maxFacts: 20,
      maxChunks: 20,
      maxEvidenceItems: 5,
      consistencyMode: "best_effort",
      includeStale: false,
    }),
  );
  const search = await options.client.context.search({
    query,
    readScope,
    tokenBudget: 1200,
    maxFacts: 20,
    maxChunks: 20,
    maxEvidenceItems: 5,
    consistencyMode: "best_effort",
    includeStale: false,
  });
  const digest = await options.client.context.buildDigest({
    topic: `${runId} full memory product summary`,
    readScope,
    tokenBudget: 2200,
    maxFacts: 20,
    maxChunks: 20,
    maxSuggestions: 5,
    includeRelated: true,
    format: "markdown",
  });
  const contextDiagnostics = context.data.diagnostics;
  const durableChecks = {
    contextReturnedEvidence: context.data.items.length > 0 || context.data.rendered_text.includes(runId),
    searchReturnedEvidence: search.data.items.length > 0,
    digestReturnedEvidence: digest.data.rendered_markdown.includes(runId) || digest.data.sections.length > 0,
    contextLinkCreated: contextLink.data.id.length > 0,
    captureCreated: capture.data.id.length > 0,
    suggestionBatchCreated: suggestions.data.created + suggestions.data.existing > 0,
    sourceEvidenceBatchRecorded: sourceEvidenceBatch.succeeded === 2 && sourceEvidenceBatch.failed === 0,
    sourceEvidenceBatchSummarized: sourceEvidenceBatchSummary.completed === 2 &&
      sourceEvidenceBatchSummary.bySourceType["sdk-full-memory-proof"] === 2,
    anchorCreated: anchor.id.length > 0,
    anchorBackfillReadable: Array.isArray(anchorBackfill.data.sources),
    memoryBrowserReadable: memoryBrowser.data.memory_scope?.external_ref === "topic:full-memory-proof:feedback",
    memoryInspectionReadable: memoryInspection.memoryBrowser.data.memory_scope?.external_ref ===
      "topic:full-memory-proof:feedback" && !memoryInspection.inspection.partial,
    maintenancePlanReadable: maintenancePlan.diagnostics.issues.length === 0,
    operationsConsoleReadable: operationsConsole.data.scope !== null,
    outboxDrained: outboxDrain.diagnostics.blocking_count <= outboxDrain.diagnostics.max_blocking_items &&
      outboxDrain.diagnostics.failure_count === 0,
    usageReadable: usage.data.space_id === space.id,
    snapshotPreviewSucceeded: jsonObjectField(snapshotTransfer.preview, "data") !== undefined,
  };
  const fullMemoryChecks = {
    capabilitiesFullMemory,
    derivedRetrievalUsed: usedDerivedRetrieval(contextDiagnostics),
    vectorHealthy: healthyRetrievalComponents(contextDiagnostics, ["vector"]),
    graphHealthy: healthyRetrievalComponents(contextDiagnostics, ["graph"]),
  };
  const checks = {
    ...fullMemoryChecks,
    ...durableChecks,
  };
  const requireFullMemory = options.requireFullMemory ?? true;
  const durableOk = Object.values(durableChecks).every(Boolean);
  const fullMemoryOk = Object.values(fullMemoryChecks).every(Boolean);

  return {
    ok: durableOk && (requireFullMemory ? fullMemoryOk : true),
    runId,
    spaceSlug,
    memoryScopeExternalRefs,
    checks,
    created: {
      spaceId: space.id,
      memoryScopeIds: scopes.map((scope) => scope.id),
      factIds: facts.map((fact) => fact.data.id),
      documentId: document.data.id,
      episodeId: stringField(episode.data, "id") ?? stringField(episode.data, "episode_id") ?? "unknown",
      contextLinkId: contextLink.data.id,
      captureId: capture.data.id,
      anchorId: anchor.id,
    },
    observed: {
      suggestionsCreated: suggestions.data.created + suggestions.data.existing,
      anchorBackfillCreated: anchorBackfill.data.created,
      anchorMergeSuggestionCount: anchorMergeSuggestions.data.length,
      memoryBrowserStats: memoryBrowser.data.stats,
      memoryInspectionIssueCount: memoryInspection.inspection.issues.length,
      memoryInspectionSections: memoryInspection.inspection.optionalSections,
      maintenanceActionableCount: maintenancePlan.summary.totalActionable,
      maintenanceIssueCount: maintenancePlan.diagnostics.issues.length,
      operationsDiagnostics: operationsConsole.data.diagnostics,
      outboxDrainDiagnostics: outboxDrain.diagnostics,
      usageResourceCount: usage.data.resources.length,
      snapshotPreview: jsonObjectField(snapshotTransfer.preview, "data") ?? {},
      sourceEvidenceBatchSummary,
    },
    capabilities: {
      enabledAdapters: capabilities.enabled_adapters ?? [],
      supportsQdrant: capabilities.supports_qdrant === true,
      supportsGraphiti: capabilities.supports_graphiti === true,
    },
    retrieval: {
      vector: retrievalDiagnostics(contextDiagnostics, "vector"),
      graph: retrievalDiagnostics(contextDiagnostics, "graph"),
      rag: retrievalDiagnostics(contextDiagnostics, "rag"),
    },
    contextDiagnostics,
    searchDiagnostics: search.data.diagnostics,
    digestDiagnostics: digest.data.diagnostics,
  };
}

async function ensureAnchor(
  client: InfinityContextClient,
  input: {
    readonly spaceSlug: string;
    readonly memoryScopeExternalRef: string;
    readonly kind: string;
    readonly label: string;
    readonly aliases?: readonly string[];
    readonly description?: string;
    readonly confidence?: string;
    readonly evidenceRefs?: readonly { readonly source_type: string; readonly source_id: string }[];
    readonly metadata?: JsonObject;
  },
): Promise<AnchorRecord> {
  const existing = await client.anchors.listAnchors({
    spaceSlug: input.spaceSlug,
    memoryScopeExternalRef: input.memoryScopeExternalRef,
    kind: input.kind,
    limit: 500,
  });
  const found = existing.data.find((anchor) => anchor.label === input.label);
  if (found !== undefined) {
    return found;
  }

  try {
    return (await client.anchors.createAnchor(input)).data;
  } catch (error) {
    if (!isConflict(error)) {
      throw copyInfinityContextError(error) ?? networkError(error);
    }
    const afterConflict = await client.anchors.listAnchors({
      spaceSlug: input.spaceSlug,
      memoryScopeExternalRef: input.memoryScopeExternalRef,
      kind: input.kind,
      limit: 500,
    });
    const created = afterConflict.data.find((anchor) => anchor.label === input.label);
    if (created === undefined) {
      throw copyInfinityContextError(error) ?? networkError(error);
    }
    return created;
  }
}

async function pollContext(
  options: FullMemoryProofOptions,
  build: () => Promise<ContextEnvelope<ContextBundleData>>,
): Promise<ContextEnvelope<ContextBundleData>> {
  const attempts = positiveIntegerOr(options.pollAttempts, defaultPollAttempts);
  const delayMs = positiveIntegerOr(options.pollDelayMs, defaultPollDelayMs);
  const sleep = options.sleep ?? defaultSleep;
  let latest: ContextEnvelope<ContextBundleData> | undefined;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    latest = await build();
    if (latest.data.items.length > 0 || latest.data.rendered_text.trim().length > 0) {
      return latest;
    }
    if (attempt + 1 < attempts) {
      await sleep(delayMs);
    }
  }

  return latest ?? await build();
}

function hasFullMemoryCapabilities(capabilities: InfinityContextCapabilities): boolean {
  const enabled = new Set(capabilities.enabled_adapters ?? []);

  return capabilities.supports_qdrant === true &&
    capabilities.supports_graphiti === true &&
    enabled.has("qdrant") &&
    enabled.has("graphiti");
}

function isConflict(error: unknown): boolean {
  return copyInfinityContextError(error)?.statusCode === 409;
}

function safeRunId(value: string): string {
  const sanitized = value.toLowerCase().replace(/[^a-z0-9._:-]+/gu, "-").replace(/^-+|-+$/gu, "");

  return sanitized.length === 0 ? "sdk-proof" : sanitized.slice(0, 80);
}

function positiveIntegerOr(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value > 0 ? value : fallback;
}

function stringField(value: JsonObject, key: string): string | undefined {
  const item = value[key];

  return typeof item === "string" ? item : undefined;
}

function jsonObjectField(value: JsonObject | undefined, key: string): JsonObject | undefined {
  const item = value?.[key];

  return isJsonObject(item) ? item : undefined;
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
