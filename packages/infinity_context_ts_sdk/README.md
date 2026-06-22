# @infinity-context/sdk

TypeScript SDK for the Infinity Context memory API.

The SDK is intentionally HTTP-first. Qdrant, Graphiti, OpenAI embeddings and Postgres stay behind the Infinity Context service boundary; Node/Nest clients should depend on this SDK contract instead of importing server adapters directly.

## Install

```bash
npm install @infinity-context/sdk
```

## Usage

```ts
import {
  InfinityContextClient,
  ReadScope,
  healthyRetrievalComponents,
  retrievalDiagnostics,
  usedDerivedRetrieval,
} from "@infinity-context/sdk";

const memory = new InfinityContextClient({
  baseUrl: process.env.INFINITY_CONTEXT_URL ?? "http://127.0.0.1:7788",
  token: () => process.env.INFINITY_CONTEXT_TOKEN,
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
  sourceKind: "summary_feedback",
  eventType: "summary.feedback.recorded",
  actorRole: "user",
  text: "User says Reddit source freshness matters for AI agent summaries.",
  evidenceRefs: [{ source_type: "summary", source_id: "summary:1" }],
  idempotencyKey: "feedback:1",
  consolidate: true,
});

await memory.captures.consolidateCapture(capture.data.id, { force: false });
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

For beta-grade proof, run a loop that writes feedback, builds context, ingests documents or episodes, verifies vector/graph diagnostics, then builds a digest from the same scopes.

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

The report fails when full mode is required and Qdrant/Graphiti are not enabled or context diagnostics do not show healthy vector/graph retrieval.
