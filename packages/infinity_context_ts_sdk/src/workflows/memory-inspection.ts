import type { RequestControls } from "../client.js";
import { ValueError, type SingleScopeInput } from "../payload.js";
import type { DiagnosticsClient } from "../resources/diagnostics.js";
import type { ExportsClient } from "../resources/exports.js";
import type { MemoryBrowserData, OperationsConsoleData, ReadModelsClient } from "../resources/read-models.js";
import type { SystemClient } from "../resources/system.js";
import type { UsageClient } from "../resources/usage.js";
import type { ApiEnvelope, InfinityContextCapabilities, JsonObject, UsageSummaryData } from "../types.js";
import type { MemoryWorkflowErrorData } from "./memory-source-evidence.js";
import {
  jsonObjectField,
  optional,
  singleScopeInput,
  workflowControls,
  workflowErrorData,
} from "./workflow-helpers.js";

export interface MemoryInspectionResourceOptions {
  readonly diagnostics?: DiagnosticsClient;
  readonly exports?: ExportsClient;
  readonly readModels?: ReadModelsClient;
  readonly system?: SystemClient;
  readonly usage?: UsageClient;
}

interface MemoryInspectionResources {
  readonly diagnostics: DiagnosticsClient;
  readonly exports: ExportsClient;
  readonly readModels: ReadModelsClient;
  readonly system: SystemClient;
  readonly usage: UsageClient;
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

interface MemorySnapshotPreviewBundle {
  readonly snapshot: JsonObject;
  readonly snapshotPreview: JsonObject;
}

export async function inspectMemory(
  resourceOptions: MemoryInspectionResourceOptions,
  input: InspectMemoryInput = {},
): Promise<InspectMemoryResult> {
  const resources = inspectionResources(resourceOptions);
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

export function memoryBrowserScopeInput(input: SingleScopeInput): Omit<SingleScopeInput, "threadId" | "threadExternalRef"> {
  return {
    ...optional("spaceId", input.spaceId),
    ...optional("memoryScopeId", input.memoryScopeId),
    ...optional("spaceSlug", input.spaceSlug),
    ...optional("memoryScopeExternalRef", input.memoryScopeExternalRef),
  };
}

export async function optionalInspectionSection<TValue>(
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

function inspectionResources(resources: MemoryInspectionResourceOptions): MemoryInspectionResources {
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
