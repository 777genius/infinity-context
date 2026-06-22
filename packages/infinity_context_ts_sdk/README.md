# @infinity-context/sdk

TypeScript SDK for the Infinity Context memory API.

The SDK is intentionally HTTP-first. Qdrant, Graphiti, OpenAI embeddings and Postgres stay behind the Infinity Context service boundary; Node/Nest clients should depend on this SDK contract instead of importing server adapters directly.

## Install

```bash
npm install @infinity-context/sdk
```

Stable entry points:

- `@infinity-context/sdk`: full SDK.
- `@infinity-context/sdk/instrumentation`: request instrumentation types.
- `@infinity-context/sdk/runtime`: runtime readiness guards.
- `@infinity-context/sdk/canary`: non-mutating runtime canary reports.
- `@infinity-context/sdk/pagination`: reusable cursor helpers.
- `@infinity-context/sdk/workflows`: workflow facade types and classes.

## Usage

```ts
import {
  InfinityContextClient,
  ReadScope,
  assertFullMemoryReady,
  healthyRetrievalComponents,
  retrievalDiagnostics,
  runRuntimeCanary,
  summarizeSourceEvidenceBatch,
  usedDerivedRetrieval,
  waitForRuntimeCanary,
} from "@infinity-context/sdk";

const memory = new InfinityContextClient({
  baseUrl: process.env.INFINITY_CONTEXT_URL ?? "http://127.0.0.1:7788",
  token: () => process.env.INFINITY_CONTEXT_TOKEN,
  instrumentation: {
    onResponse: (event) => {
      console.log("memory api", event.method, event.path, event.statusCode, event.durationMs);
    },
  },
});

const space = await memory.spaces.createSpace({
  slug: "social-monitor:tenant_1:workspace_1",
  name: "Social Monitor workspace",
});

await memory.facts.rememberFact({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  text: "User prefers concise daily AI agent summaries with links to primary sources.",
  kind: "preference",
  sourceRefs: [{ source_type: "social-monitor", source_id: "feedback:1" }],
  idempotencyKey: "feedback:1",
});

const context = await memory.context.buildContext({
  query: "What should the next AI agents digest prioritize?",
  readScope: ReadScope.external({
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["workspace-global", "user:user_1", "topic:ai-agents:feedback"],
  }),
  tokenBudget: 1800,
  maxFacts: 20,
  maxChunks: 30,
});

console.log(context.data);

if (usedDerivedRetrieval(context.data.diagnostics)) {
  console.log(retrievalDiagnostics(context.data.diagnostics, "vector"));
}

if (!healthyRetrievalComponents(context.data.diagnostics, ["vector", "graph"])) {
  throw new Error("Expected healthy Qdrant and Graphiti retrieval for full memory mode");
}
```

## Workflow facade

Use `client.workflows` for product integrations that should not hand-build low-level capture enums, source refs and idempotency keys.

```ts
await memory.workflows.ensureMemoryTopology({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  spaceName: "Social Monitor workspace 1",
  memoryScopes: [
    { externalRef: "workspace-global", name: "Workspace global memory" },
    { externalRef: "user:user_1", name: "User 1 preferences" },
    { externalRef: "topic:ai-agents:preferences", name: "AI agents preferences" },
    { externalRef: "source:reddit:ai-agents", name: "Reddit AI agents source memory" },
  ],
  users: [{
    externalRef: "user:user_1",
    displayName: "User 1",
    role: "owner",
  }],
});

await memory.workflows.recordFeedback({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  threadExternalRef: "digest-run:2026-06-22",
  sourceAgent: "social-monitor",
  sourceId: "feedback:1",
  sourceActorExternalRef: "user_1",
  text: "User wants Reddit freshness and primary citations in daily summaries.",
  idempotencyKey: "feedback:1",
  factMemoryScopeExternalRef: "topic:ai-agents:preferences",
  factTags: ["summary", "freshness"],
});

const brief = await memory.workflows.buildMemoryBrief({
  query: "What should today's AI digest prioritize?",
  topic: "AI digest",
  readScope: ReadScope.external({
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["workspace-global", "user:user_1", "topic:ai-agents:preferences"],
  }),
  tokenBudget: 1800,
  maxFacts: 20,
  maxChunks: 30,
});

console.log(brief.context.data.rendered_text);
console.log(brief.digest?.data.rendered_markdown);
console.log(brief.diagnostics);
```

Use `recordSourceEvidence` for provider ingestion loops that need durable source memory, reviewable capture history and graph-aware link suggestions.

```ts
await memory.workflows.recordSourceEvidence({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "source:reddit:ai-agents",
  threadExternalRef: "scan:2026-06-22",
  sourceAgent: "social-monitor",
  sourceType: "reddit",
  sourceId: "reddit:t3_abc",
  title: "Reddit discussion on agent memory",
  text: "Operators want Reddit freshness, citations and source scoring in summaries.",
  occurredAt: "2026-06-22T10:00:00.000Z",
  idempotencyKey: "reddit:t3_abc",
  metadata: { provider: "reddit", subreddit: "LocalLLaMA" },
  document: { process: true, classification: "public" },
  fact: {
    memoryScopeExternalRef: "topic:ai-agents:preferences",
    category: "source_signal",
    tags: ["reddit", "freshness"],
  },
  linkSuggestions: { persist: true, limit: 5 },
});
```

For provider scans, batch items with bounded concurrency and keep per-item errors inspectable.

```ts
const batch = await memory.workflows.recordSourceEvidenceBatch({
  concurrency: 4,
  continueOnError: true,
  signal: scanAbortController.signal,
  headers: { "x-trace-id": "scan:2026-06-22" },
  items: redditPosts.map((post) => ({
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRef: "source:reddit:ai-agents",
    threadExternalRef: "scan:2026-06-22",
    sourceAgent: "social-monitor",
    sourceType: "reddit",
    sourceId: post.id,
    title: post.title,
    text: post.selftext,
    occurredAt: post.createdAt,
    idempotencyKey: `reddit:${post.id}`,
    metadata: { subreddit: post.subreddit },
    episode: true,
    capture: true,
    linkSuggestions: { persist: true, limit: 5 },
  })),
});

const batchSummary = summarizeSourceEvidenceBatch(batch);
console.log(batchSummary.succeeded, batchSummary.failed, batchSummary.retryableFailures);
```

For product loops that should bootstrap memory, check runtime readiness, ingest provider evidence and return a readable summary in one call, use `runMemorySummaryLoop`.

```ts
const loop = await memory.workflows.runMemorySummaryLoop({
  headers: { "x-trace-id": "scan:2026-06-22" },
  topology: {
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    spaceName: "Social Monitor workspace 1",
    memoryScopes: [{ externalRef: "topic:ai-agents", name: "AI agents" }],
  },
  readiness: {
    query: "runtime readiness before AI agents digest",
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["topic:ai-agents"],
  },
  sourceEvidence: {
    concurrency: 4,
    continueOnError: true,
    items: providerItems,
  },
  outboxDrain: {
    limit: 100,
    pollIntervalMs: 1000,
    maxAttempts: 60,
    throwOnFailure: true,
  },
  brief: {
    query: "What matters most in AI agents today?",
    topic: "AI agents digest",
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["topic:ai-agents"],
  },
});

console.log(loop.sourceEvidenceSummary?.successRate, loop.brief.digest?.data.rendered_markdown);
```

Use `inspectMemory` when an operator, beta smoke or backend job needs one typed view over read models, usage, runtime diagnostics and optional graph/snapshot checks.

```ts
const inspection = await memory.workflows.inspectMemory({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:preferences",
  limit: 25,
  includeGraph: true,
  includeSnapshotPreview: true,
  continueOnError: true,
  signal: scanAbortController.signal,
  headers: { "x-trace-id": "inspect:2026-06-22" },
});

if (inspection.inspection.partial) {
  console.warn(inspection.inspection.issues);
}

console.log(inspection.memoryBrowser.data.stats);
console.log(inspection.operationsConsole?.data.diagnostics);
console.log(inspection.snapshotPreview?.data);
```

`inspectMemory` keeps browser, operations, usage, capabilities and runtime diagnostics enabled by default. Graph export and snapshot preview are opt-in because they are heavier and snapshot preview requires `spaceSlug` plus `memoryScopeExternalRef`.

Use `planMemoryMaintenance` to turn pending review queues into one operator-ready plan without mutating memory state.

```ts
const maintenance = await memory.workflows.planMemoryMaintenance({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:preferences",
  limit: 25,
  continueOnError: true,
  headers: { "x-trace-id": "maintenance:2026-06-22" },
});

for (const action of maintenance.summary.suggestedActions) {
  console.log(action.priority, action.kind, action.count, action.reason);
}

console.log(maintenance.diagnostics.issues);
```

The maintenance workflow reads operations, pending context link suggestions, memory suggestions, anchor merge candidates, capture consolidation diagnostics and extraction jobs. It returns suggested actions only; applying merges, retries or approvals stays explicit.

## Runtime readiness

Use runtime guards in CI, beta smoke tests or app boot checks before relying on full memory retrieval.

```ts
const readiness = await memory.workflows.checkFullMemoryReadiness({
  query: "runtime readiness probe",
  readScope: ReadScope.external({
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["workspace-global"],
  }),
  includeSearchProbe: true,
  assertReady: true,
});

console.log(readiness.readiness.mode, readiness.readiness.enabledAdapters);
console.log(readiness.diagnostics);

const capabilities = await memory.system.capabilities();
const context = await memory.context.buildContext({
  query: "runtime readiness probe",
  readScope: ReadScope.external({
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRefs: ["workspace-global"],
  }),
});

assertFullMemoryReady(capabilities, context.data.diagnostics);
```

Use the canary when CI or deploy smoke tests need a non-mutating full-memory gate without running the heavier proof loop.

```ts
const canary = await runRuntimeCanary({
  client: memory,
  query: "runtime readiness probe",
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRefs: ["workspace-global"],
  includeSearchProbe: true,
});

if (!canary.ok) {
  console.error(canary.errors);
  process.exitCode = 1;
}

const ready = await waitForRuntimeCanary({
  client: memory,
  query: "runtime readiness probe",
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRefs: ["workspace-global"],
  maxAttempts: 12,
  pollIntervalMs: 5000,
});

console.log(ready.mode, ready.attempts);
```

Or run the packaged CLI:

```bash
INFINITY_CONTEXT_URL=http://127.0.0.1:7788 \
INFINITY_CONTEXT_TOKEN=... \
INFINITY_CONTEXT_CANARY_SPACE_SLUG=social-monitor:tenant_1:workspace_1 \
INFINITY_CONTEXT_CANARY_MEMORY_SCOPE_EXTERNAL_REFS=workspace-global \
INFINITY_CONTEXT_CANARY_WAIT=true \
INFINITY_CONTEXT_CANARY_MAX_ATTEMPTS=12 \
INFINITY_CONTEXT_CANARY_POLL_INTERVAL_MS=5000 \
npm run canary:runtime
```

Set `INFINITY_CONTEXT_CANARY_REQUIRE_READY=false` to write/read the report in lite/local mode without failing the process.

## Pagination helpers

Cursor endpoints expose typed helpers so integrations can scan memory scopes without hand-rolling cursor loops.

```ts
for await (const fact of memory.facts.iterateFacts(
  {
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRef: "topic:ai-agents:preferences",
    tag: "summary",
  },
  { pageLimit: 100, maxItems: 1000 },
)) {
  console.log(fact.id, fact.text);
}

const chunks = await memory.documents.listAllDocumentChunks("doc_123", {
  pageLimit: 100,
});

const outboxItems = await memory.diagnostics.listAllOutboxItems({
  pageLimit: 100,
  maxItems: 1000,
});
console.log(outboxItems.filter((item) => item.status !== "done").length);

const drained = await memory.diagnostics.waitForOutboxDrain({
  limit: 100,
  pollIntervalMs: 1000,
  maxAttempts: 60,
  throwOnFailure: true,
});
console.log(drained.diagnostics.attempts, drained.diagnostics.blocking_count);
```

## Per-request controls

Every high-volume memory read/write surface accepts scoped request controls. Use them for cancellation, worker tracing and request correlation without changing the shared client.

```ts
const controller = new AbortController();

const facts = await memory.facts.listAllFacts(
  {
    spaceSlug: "social-monitor:tenant_1:workspace_1",
    memoryScopeExternalRef: "topic:ai-agents:preferences",
  },
  {
    pageLimit: 100,
    maxItems: 1000,
    signal: controller.signal,
    headers: {
      "x-trace-id": "digest-run:2026-06-22",
    },
  },
);

console.log(facts.length);
```

## Context links

Use context links when source evidence, documents, assets or facts should be explicitly connected for graph-aware retrieval and review workflows.

```ts
const suggested = await memory.contextLinks.suggestContextLinks({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  text: "User feedback says Reddit source freshness matters for the AI agents digest.",
  sourceType: "summary_feedback",
  sourceId: "feedback:1",
  persist: true,
});

const suggestionId = suggested.data.candidates[0]?.suggestion_id;
if (suggestionId) {
  await memory.contextLinks.approveContextLinkSuggestion(suggestionId, {
    reason: "reviewed source relevance",
    relationType: "supports",
    confidence: "high",
  });
}
```

## Captures

Captures are the canonical ingestion surface for agent hooks, app events and feedback that may later consolidate into suggestions or durable facts.

```ts
const capture = await memory.captures.createCapture({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  sourceAgent: "social-monitor",
  sourceKind: "hook",
  eventType: "summary.feedback.recorded",
  actorRole: "user",
  text: "User says Reddit source freshness matters for AI agent summaries.",
  evidenceRefs: [{ source_type: "summary", source_id: "summary:1" }],
  sourceAuthority: "user_statement",
  idempotencyKey: "feedback:1",
  consolidate: true,
});

await memory.captures.consolidateCapture(capture.data.id, { force: false });
```

## Asset extraction lifecycle

Use extraction lifecycle helpers when documents, screenshots, PDFs or transcripts need asynchronous parsing before retrieval.

```ts
const extraction = await memory.assets.requestAssetExtraction(assetId, {
  parserProfile: "markdown-strict",
});

const completed = await memory.assets.waitForAssetExtraction(extraction.data.id, {
  pollIntervalMs: 1000,
  maxAttempts: 60,
  throwOnFailure: true,
});

const pending = await memory.assets.listScopeAssetExtractions({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  status: "failed",
  limit: 25,
});

for (const job of pending.data) {
  await memory.assets.retryAssetExtraction(job.id);
}

const artifact = completed.data.artifacts[0];
if (artifact) {
  await memory.assets.downloadExtractionArtifact(artifact.id);
}
```

## Graph maintenance and suggestions

Use anchor maintenance and advanced suggestion resolution when the memory graph needs reviewable cleanup instead of one-off fact edits.

```ts
const mergeCandidates = await memory.anchors.listAnchorMergeSuggestions({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  kind: "project",
});

for (const candidate of mergeCandidates.data) {
  if (candidate.score > 0.9) {
    await memory.anchors.mergeAnchor(candidate.source_anchor.id, {
      targetAnchorId: candidate.target_anchor.id,
      reason: "high-confidence duplicate anchor",
    });
  }
}

await memory.suggestions.resolveSuggestionConflict(suggestionId, {
  action: "approve",
  reason: "latest explicit user feedback wins",
});

await memory.suggestions.approveSuggestionsBatch(
  ["suggestion_1", { suggestionId: "suggestion_2", reason: "reviewed as durable preference" }],
  { reason: "weekly memory review", continueOnError: true },
);

await memory.suggestions.rejectSuggestionsBatch(
  [{ suggestionId: "suggestion_3", reason: "temporary task detail" }],
);
```

## Read models

Use read models to inspect the memory browser projection and operations queue from a typed SDK surface.

```ts
const browser = await memory.readModels.getMemoryBrowser({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  captureStatus: "active",
  linkStatus: "active",
  suggestionStatus: "pending",
});

const operations = await memory.readModels.getOperationsConsole({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  limit: 25,
});

console.log(browser.data.visual_summary, operations.data.link_suggestion_status_counts);
```

## Thread memory and usage

Thread memory helpers make ephemeral session cleanup explicit. Usage summaries expose the current quota window for a space.

```ts
const threadScope = {
  spaceSlug: "social-monitor:tenant_1:workspace_1",
  memoryScopeExternalRef: "topic:ai-agents:feedback",
  threadExternalRef: "digest-run:2026-06-22",
};

const threadStatus = await memory.threadMemory.status(threadScope);
if (threadStatus.data.pending_jobs === 0) {
  await memory.threadMemory.delete(threadScope);
}

const usage = await memory.usage.summary({
  spaceSlug: "social-monitor:tenant_1:workspace_1",
});
console.log(usage.data.plan.tier, usage.data.resources);
```

## Snapshot portability

Use `transferMemorySnapshot` for safe backup, restore and migration workflows. The default mode exports a redacted snapshot and previews import safety without mutating memory state.

```ts
const preview = await memory.workflows.transferMemorySnapshot({
  sourceSpaceSlug: "social-monitor:tenant_1:workspace_1",
  sourceMemoryScopeExternalRef: "topic:ai-agents:preferences",
  targetSpaceSlug: "social-monitor:tenant_1:workspace_1",
  targetMemoryScopeExternalRef: "topic:ai-agents:preferences-copy",
});

console.log(preview.diagnostics.warnings);
console.log(preview.preview?.data);
```

Confirmed imports require an explicit mode and confirmation flag.

```ts
await memory.workflows.transferMemorySnapshot({
  sourceSpaceSlug: "social-monitor:tenant_1:workspace_1",
  sourceMemoryScopeExternalRef: "topic:ai-agents:preferences",
  targetSpaceSlug: "social-monitor:tenant_1:workspace_1",
  targetMemoryScopeExternalRef: "topic:ai-agents:preferences-copy",
  mode: "confirmed_import",
  confirmed: true,
  redacted: false,
  mergeStrategy: "fail_on_conflict",
});
```

## Recommended Social Monitor mapping

- `spaceSlug`: `social-monitor:{tenantId}:{workspaceId}`
- workspace memory scope: `workspace-global`
- user preference scope: `user:{userId}`
- topic preference scope: `topic:{topicId}:preferences`
- topic feedback scope: `topic:{topicId}:feedback`
- source scope: `source:{sourceBindingId}`

Keep operational state in Social Monitor Postgres. Store only reusable semantic memory, preferences, feedback lessons, topic ranking hints and digest style in Infinity Context.

## Full memory mode

To exercise the full memory stack, run Infinity Context with Postgres + Qdrant + Neo4j/Graphiti + OpenAI embeddings. The SDK does not change between lite and full profiles; the service capability payload should show healthy `qdrant` and `graphiti` adapters.

```ts
const capabilities = await memory.system.capabilities();

if (!capabilities.enabled_adapters?.includes("qdrant")) {
  throw new Error("Expected full memory mode with qdrant enabled");
}
```

For beta-grade proof, run a loop that writes facts, captures, suggestions, anchors, documents and episodes, exercises source evidence batch workflows, inspects read models and operational projections, verifies vector/graph diagnostics, previews snapshot import safety, then builds a digest from the same scopes.

## Full memory proof script

Run the SDK proof against a live Infinity Context service:

```bash
INFINITY_CONTEXT_URL=http://127.0.0.1:7788 \
INFINITY_CONTEXT_TOKEN=... \
npm run proof:full-memory
```

Useful optional env:

- `INFINITY_CONTEXT_PROOF_RUN_ID`: stable run id for repeatable idempotency keys.
- `INFINITY_CONTEXT_PROOF_OUTPUT`: write the JSON evidence report to a file.
- `INFINITY_CONTEXT_PROOF_REQUIRE_FULL_MEMORY=false`: allow lite/local mode while still proving the SDK write/read loop.
- `INFINITY_CONTEXT_PROOF_OUTBOX_DRAIN_ATTEMPTS`: override attempts for waiting on projection/outbox drain.
- `INFINITY_CONTEXT_PROOF_OUTBOX_DRAIN_DELAY_MS`: override delay between projection/outbox drain checks.

The report fails when the durable SDK loop cannot prove write/read/workflow/operations/export coverage or when outbox projections do not drain before read-model checks. In full mode it also fails when Qdrant/Graphiti are not enabled or context diagnostics do not show healthy vector/graph retrieval.

## Maintainer parity check

Run the parity guard after adding server endpoints:

```bash
npm run check:parity
```

The guard scans FastAPI v1 routes and TypeScript SDK paths, then fails when a server endpoint is neither covered nor documented as an explicit exception.
