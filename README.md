# Infinity Context

**Reliable memory and context infrastructure for AI coding agents.**

Infinity Context helps AI coding agents keep project knowledge across sessions
without turning random chat history into permanent truth. It captures decisions,
documents, tasks, source references, agent events and reviewable suggestions,
then serves compact, cited context back through HTTP, SDK, MCP and a local UI.

The difference is trust. Every durable memory has a canonical lifecycle in
Postgres: source evidence, versions, scopes, deletes, idempotency and review
state. Vector and graph engines make recall better, but they never become hidden
truth. If Qdrant, Graphiti or an LLM returns something stale, Infinity Context
revalidates it before it reaches the agent prompt.

This is not a demo memory store. The repo already includes the reusable core,
FastAPI server, Postgres lifecycle, optional Qdrant and Graphiti adapters, SDK,
MCP adapter, CLI, local memory browser, service-token auth, workers, diagnostics,
smoke flows and prompt-impacting quality evals.

## What You Get

- **Cited agent memory** for architecture decisions, docs, tasks, captures and
  transcripts.
- **Scoped recall** across spaces, memory scopes and threads, so one project does
  not leak into another.
- **Review-gated learning** where agents can suggest memories and relations, but
  humans control what becomes canonical.
- **Current-state filtering** for updates, deletes, restricted data and stale
  derived indexes.
- **Self-hosted runtime** with local Docker profiles, service tokens, CLI,
  browser UI, SDK and MCP adapter.
- **Replaceable retrieval** with Postgres as the source of truth and Qdrant,
  Graphiti, Cognee or provider adapters behind ports.

## Why Teams Choose It

- **Safer than plain vector memory.** A vector hit is only a candidate until it is
  hydrated through canonical facts, source refs and visibility rules.
- **More controllable than automatic chat memory.** Prompt memory is evidence,
  not instruction, and suggested memory can be reviewed before it affects future
  agents.
- **Better fit for coding work.** The model is built around projects, documents,
  decisions, source evidence, thread cleanup, digest reports and agent tooling.
- **Stable enough for real workflows.** Additive migrations, transactional
  outbox, token hashing, circuit diagnostics, import-boundary tests, API tests,
  worker tests and golden evals are part of the shipped system.

## Positioning

Use [Mem0](https://github.com/mem0ai/mem0)-style tools when you mostly need
quick personalization memory. Use [Zep](https://www.getzep.com/) when you want a
managed enterprise context graph. Use
[LangGraph memory primitives](https://docs.langchain.com/oss/python/concepts/memory)
when your memory should stay inside one agent framework.

Use Infinity Context when the hard problem is **trustworthy project memory for
coding agents**: source-backed facts, scoped recall, current-state filtering,
review workflows, self-hosted data and portable adapters.

## Project State

Infinity Context is a working standalone service and library stack. It supports
local developer setups, self-hosted team deployments and client integrations
through HTTP, SDK or MCP.

Runtime architecture:

```text
Infinity Context = Postgres canonical truth + Qdrant RAG + optional Graphiti graph + SDK/MCP/UI
```

Trust model:

- Clean Architecture;
- SOLID;
- simple DDD;
- port/adapter boundaries;
- Postgres as canonical truth;
- Qdrant and Graphiti as derived indexes;
- prompt memory is evidence, never instruction.

## Docs

- [Core runtime implementation plan](docs/infinity-context-core-lite-plan.md)
- [Local install and Memory Digest plan](docs/local-install-and-memory-digest-plan.md)
- [Global architecture plan](docs/infinity-context-architecture-plan.md)
- [Client compatibility notes](docs/client-integration/interview-infinity-context-clean-architecture-plan.md)
- [Client integration run notes](docs/client-integration/current-integration-run-notes.md)

## Package Layout

```text
packages/
  infinity_context_core/
  infinity_context_server/
  infinity_context_adapters/
  infinity_context_sdk/
  infinity_context_mcp/
  infinity_context_cli/

tests/
  unit/
  integration/
  e2e/
  fixtures/
```

Client applications should consume this project through HTTP or SDK, not by importing provider-specific adapters.

## What Ships Today

Infinity Context ships as a reusable service and library stack:

- `infinity_context_core` owns domain entities, application use cases and ports only;
- `infinity_context_server` owns FastAPI routes, composition root, auth, config, admin CLI, worker CLI and eval CLI;
- `infinity_context_server` also serves the optional local memory browser at `/ui/`;
- `infinity_context_adapters` owns Postgres, optional Qdrant/OpenAI/Graphiti adapters and disabled noop adapters;
- `infinity_context_sdk` owns HTTP client calls and typed error handling for other apps;
- `infinity_context_mcp` owns the agent-facing MCP adapter over the HTTP API;
- `infinity_context_cli` owns local install/runtime UX and calls the HTTP API instead of importing server internals;
- Postgres is canonical truth for spaces, memory_scopes, facts, source refs, fact versions, episodes, documents, chunks, suggestions, outbox and idempotency;
- Qdrant vectors and Graphiti graph memory are derived projections behind ports;
- Qdrant adapter creates its collection on first upsert/search when enabled;
- Graphiti adapter is optional and requires Neo4j credentials when enabled;
- context/search hydrate graph/vector candidates through Postgres before rendering;
- prompt memory is rendered as evidence, never as instructions.
- prompt context is grouped by memory_scope id and caps chunk evidence per source so
  one long document cannot consume the whole memory block;
- document/chunk classification is enforced in the prompt path: `restricted`
  memory is stored canonically but excluded from context by default, and
  `unknown` documents are not embedded until reclassified.

Implemented API surface:

- `/v1/health`, `/v1/capabilities`;
- `/v1/spaces`, `/v1/memory-scopes`;
- `/v1/facts` remember/list/get/versions/update/forget;
- `/v1/documents` ingest/get/chunks/process/delete;
- `/v1/episodes` transcript/event ingest for app or agent sessions;
- `/v1/search`, `/v1/context` with cited `top_evidence` and `answer_support`
  diagnostics for source-grounded chat answers;
- `/v1/digest` for source-bound Memory Digest reports;
- `/v1/thread-memory/status`, `/v1/thread-memory` delete for thread-scoped cleanup;
- `/v1/suggestions` create/list/approve/reject/expire for review-gated memory;
- `/v1/link-suggestions`, `/v1/context-link-suggestions`, `/v1/context-link-suggestions/review-batch`, `/v1/context-links` for reviewable memory relations and status-filtered review history;
- `/v1/diagnostics/adapters`, `/outbox`, `/memory-scope/{memory_scope_id}` with production-safe metadata only;
- optional client-compatible `/api/v1/interview-memory/ingest`, `/context`, session status and delete routes when `MEMORY_LEGACY_CLIENT_ENABLED=true`.

Local browser UI:

- open `http://127.0.0.1:7788/ui/` after the server starts;
- enter the service token from local config, for example `~/.infinity-context/.env`;
- browse graph nodes for facts, suggestions, sources, kinds, tags and statuses;
- review pending suggestions and relation suggestions with approve/reject/edit actions;
- build source-bound digest and recall results through the existing `/v1` API;
- disable with `MEMORY_UI_ENABLED=false`.

Operational pieces:

- transactional outbox for derived graph/vector side effects;
- outbox worker that re-reads canonical rows and handles disabled adapters safely;
- idempotency keys are scoped by operation and memory_scope/thread boundary, so
  client-provided retry keys cannot collide across memory scopes;
- admin commands for doctor, invariant check, projection repair dry-run and dead-job replay;
- admin service-token create/list/revoke stores token hashes only; raw token is printed once on creation;
- database service tokens support expiry and last-used tracking without storing raw tokens;
- `infinity_context_server.db upgrade`, `admin seed-defaults` and guarded `admin reset-local`;
- schema upgrade is additive for local databases and repairs missing
  fact/document/chunk classification columns without dropping canonical data;
- document delete hides chunks immediately and also deletes active facts whose
  current evidence only points to the deleted document or its chunks;
- redacted memory_scope export removes fact/chunk text and source quote previews;
- small golden eval for prompt-impacting context behavior;
- quality golden eval for recall, precision, stale/delete filtering, memory_scope/thread
  isolation, restricted-memory hiding, prompt-injection evidence handling and token budget safety;
- import-boundary, API, worker, SDK and review-gated suggestion tests.

## Local Run

One-command local install:

```bash
curl -fsSL https://raw.githubusercontent.com/777genius/infinity-context/main/scripts/install.sh | bash
```

Safer inspectable install:

```bash
curl -fsSL https://raw.githubusercontent.com/777genius/infinity-context/main/scripts/install.sh -o install.sh
bash install.sh --no-start
```

After install:

```bash
export PATH="$HOME/.infinity-context/bin:$PATH"
infinity-context quickstart --agent codex --open-ui
```

Manual local controls remain available:

```bash
infinity-context up --lite
infinity-context status
infinity-context doctor
infinity-context mcp-config --agent codex
infinity-context digest "current architecture decisions" --space default --memory_scope default
```

`infinity-context quickstart` initializes local config, starts the lite Docker
runtime, waits for readiness and writes an MCP config under
`~/.infinity-context/generated/`. `quickstart` and `mcp-config` keep the local
service token out of generated agent config by default and point the MCP adapter
at the private `~/.infinity-context/.env` token file instead. Use
`--include-token` only when intentionally writing a private local config file.
`infinity-context ui` prints the local memory browser URL,
`infinity-context ui --open` opens it in your browser, and
`quickstart --open-ui` opens the visual memory browser immediately after setup.
`infinity-context doctor` also verifies the generated MCP config and `/ui/`
browser entrypoint. The browser starts with a quick Capture panel for text notes
and file evidence, including a first-memory rail for the current memory scope,
capture count, file count, pending reviews and graph nodes. Direct local browser
links are available as `/ui/#capture` and `/ui/#review`, then the browser shows
overview, graph, review, operations and timeline.
Both `quickstart --json` and `doctor --json` include a `local_experience`
summary with `status`, `ui_url`, `visual_memory_ready`, `mcp_ready`,
`ready_agents`, a first-use readiness score, the first Capture surface and a
`one_minute_path` checklist with human labels, short descriptions,
`blocked_by` or `degraded_reason` diagnostics, and Capture/Review deep links.
When the runtime is available, the Capture summary is derived from
`/v1/capabilities`, so it only advertises active modalities: for example, local
audio/video metadata is shown separately from API-backed transcription. A fresh
local setup should reach `status=ready`;
`configured_not_started` means the MCP config was generated but the local runtime
still needs `infinity-context up --lite`. If Docker is running on a different
published port than the configured API URL, `status --json` and `doctor --json`
include `docker_published_api_urls` and `suggested_api_url` diagnostics instead
of silently failing with only `ConnectError`.

The fastest local proof for the first-memory flow is:

```bash
make infinity-context-local-visual-smoke
```

It starts the lite stack if needed, writes a Codex MCP config without embedding
the raw token, checks MCP `memory_status`, saves a sandbox Capture, waits for
consolidation, and verifies that pending review plus the Capture are visible in
the local memory browser.

Agent-assisted local setup is also available through MCP, but it is off by
default so agents do not create files or start background services unexpectedly:

```bash
export MEMORY_MCP_LOCAL_RUNTIME_ENABLED=true
export MEMORY_MCP_LOCAL_RUNTIME_HOME="$HOME/.infinity-context"
export MEMORY_MCP_LOCAL_RUNTIME_REPO_DIR="$(pwd)"
```

Then an agent can call `memory_obsidian_prepare` for the safe first-use flow:
dry-run local config, vault folders and plugin install, then apply after user
approval. It never starts Docker or runs mutating sync. Lower-level
`memory_local_runtime_status`, `memory_local_runtime_init`,
`memory_local_runtime_doctor` and dry-run `memory_local_runtime_start` remain
available for diagnostics. A real Docker start still requires a separate
explicit gate:

```bash
export MEMORY_MCP_LOCAL_RUNTIME_START_ENABLED=true
```

Obsidian connector verification:

```bash
make infinity-context-obsidian-test
make infinity-context-obsidian-ui-e2e
```

`infinity-context-obsidian-test` covers the Python connector, live HTTP sync smoke,
MCP stdio setup/sync smoke, and plugin typecheck/build without opening Obsidian.
`infinity-context-obsidian-ui-e2e` opens the real desktop Obsidian app and runs the
full WDIO plugin suite. Vaults with a custom Obsidian config folder are supported
through `--obsidian-config-dir` or `MEMORY_MCP_OBSIDIAN_CONFIG_DIR`.

Install once:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,qdrant,openai,graphiti,mcp]'
```

The Docker compose file has two practical profiles:

```text
lite           Postgres + Infinity Context Server, provider adapters disabled.
full           Postgres + Qdrant + Neo4j + Infinity Context Server + workers, with OpenAI embeddings and Graphiti enabled.
```

Both profiles run separate projection and extraction workers. The extraction
worker only claims `workload_class=extraction` jobs, so file parsing can be
scaled independently from vector, graph and auto-memory projection work.
`MEMORY_EXTRACTION_WORKER_LIMIT` controls how many outbox jobs are claimed per
poll. `MEMORY_EXTRACTION_WORKER_CONCURRENCY` controls how many claimed
extraction jobs run at once in one process, and defaults to `1` for conservative
parser/provider resource isolation.

Recommended local proof:

```bash
make infinity-context-up-lite
make infinity-context-smoke
make infinity-context-mcp-smoke
make infinity-context-local-visual-smoke
```

`infinity-context-smoke` covers the SDK lifecycle path plus MemoryScope snapshot thread transfer.

Full provider mode needs OpenAI for embeddings and Graphiti. Do not paste the
key into commands that will be saved in shell history. Read it silently or use
an ignored local env file:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY
export MEMORY_OPENAI_API_KEY="$OPENAI_API_KEY"
make infinity-context-up-full
make infinity-context-smoke-full
```

Small-team self-hosting uses a production-oriented Compose file with a built
image, server deploy profile, explicit migrations and persistent volumes:

```bash
cp .env.selfhost.example .env.selfhost
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml up -d --build
make infinity-context-selfhost-smoke
```

See `docs/self-hosted-team-deployment.md` for the runbook, full provider mode
and backup notes.

`MEMORY_OPENAI_API_KEY` is used by the Infinity Context embeddings adapter.
`OPENAI_API_KEY` is also required because Graphiti reads the standard OpenAI
environment variable internally.

For a fully isolated paid canary, use a fresh Compose project and temporary
Docker volumes. The script starts isolated Postgres, Qdrant and Neo4j, runs
migrations, seeds defaults, starts the server, verifies Graphiti/Qdrant/OpenAI
behavior, then tears everything down:

```bash
make infinity-context-clean-full-smoke
```

If the key is not already exported in the current shell, use the interactive
wrapper. It reads the key with terminal echo disabled and passes it only through
the canary process environment:

```bash
make infinity-context-full-provider-canary-interactive
```

For local defaults, copy `.env.example` to `.env` and adjust non-secret provider
flags. Secrets should stay in your shell, `.env.local`, `.env.full`, or another
ignored file. Cognee is available as an optional adapter boundary, while the
default RAG path is Qdrant directly and the default temporal fact path is
Graphiti directly.

Common local targets are available in `Makefile`, for example `make infinity-context-lint`,
`make infinity-context-test-unit`, `make infinity-context-eval`, `make infinity-context-db-upgrade`,
`make infinity-context-seed-defaults`, `make infinity-context-doctor`, `make infinity-context-up`,
`make infinity-context-server`, `make infinity-context-up-lite`, `make infinity-context-up-full`,
`make infinity-context-clean-full-smoke`, `make infinity-context-auto-memory-eval`,
`make infinity-context-auto-memory-quality` and `make infinity-context-mcp-smoke`.

Memory Digest can be called through API, SDK, MCP or CLI. It is derived evidence,
not canonical memory, and pending suggestions are clearly marked as non-canonical.
For exact lookups or write/update/forget flows, agents should still call
`memory_search` or `memory_get_fact`.

GitHub Actions runs the same prompt-impacting gate on push and pull requests:
`make PYTHON=python RUFF=ruff infinity-context-test-quality`. Keep quality changes green
there before relying on memory in an agent prompt path.

Policy modes:

```text
MEMORY_POLICY_MODE=disabled       # no server writes or retrieval
MEMORY_POLICY_MODE=manual_only    # explicit API writes, retrieval for reviewed/manual memory
MEMORY_POLICY_MODE=suggestions    # review-gated memory mode
MEMORY_POLICY_MODE=active_context # active prompt-context mode
```

Auto-memory capture defaults are conservative:

```text
MEMORY_CAPTURE_MODE=retrieve_only              # no automatic capture writes
MEMORY_CAPTURE_MODE=capture_only               # store captures, no suggestions
MEMORY_CAPTURE_MODE=suggest                    # captures can become pending suggestions
MEMORY_AUTO_APPLY_SAFE_ENABLED=false           # separate switch for direct safe apply
MEMORY_CAPTURE_EXTRACTOR_PROVIDER=rule_based   # rule_based, noop, or openai
MEMORY_CAPTURE_EXTERNAL_AI_ENABLED=false       # external extractor egress kill switch
MEMORY_CAPTURE_EXTRACTOR_MODEL=gpt-4.1-mini    # used only by the OpenAI extractor
MEMORY_MAX_PENDING_CAPTURES_PER_MEMORY_SCOPE=5000   # hook-loop ingress guard
MEMORY_MAX_PENDING_SUGGESTIONS_PER_MEMORY_SCOPE=500 # review queue ingress guard
```

`MEMORY_AUTO_MEMORY_MODE` is accepted as a compatibility alias for
`MEMORY_CAPTURE_MODE` on both Infinity Context Server and plugin hooks. When both are set,
`MEMORY_AUTO_MEMORY_MODE` wins.

Media extraction has product-plan usage guards in addition to parser limits:

```text
MEMORY_PRODUCT_PLAN_TIER=free
MEMORY_PLAN_MEDIA_ANALYSIS_SECONDS_PER_MONTH=36000 # 10 hours
```

Audio/video uploads can pass `estimated_media_seconds` so Infinity Context can reserve
monthly media-analysis quota before enqueueing extraction. Clients can poll
`/v1/asset-extractions/{job_id}` for `progress` and `/v1/usage?space_slug=...`
for the current plan meter.
Long extraction jobs refresh their lease while parsing and honor cancellation
requests through `MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS` plus
`MEMORY_EXTRACTION_HEARTBEAT_SECONDS`; these values are also exposed by
`/v1/capabilities`.

`rule_based` keeps consolidation local and deterministic. `openai` is available
behind `MemoryExtractorPort`, but it requires both
`MEMORY_CAPTURE_EXTERNAL_AI_ENABLED=true` and `MEMORY_OPENAI_API_KEY`; otherwise
startup or consolidation fails closed without sending capture text to a provider.
Auto-memory quality is checked by `make infinity-context-auto-memory-quality`, which
includes deterministic golden capture metrics for review gating, redaction,
duplicate suppression, replay idempotency and `auto_apply_safe` safety.
The Python SDK exposes `create_capture`, `get_capture`, `list_captures`,
`consolidate_capture`, `purge_capture` and `capture_diagnostics`, so clients
should not hand-roll capture payloads.

Data classification:

```text
public      # embeddable and renderable evidence
internal    # embeddable and renderable evidence
unknown     # canonical storage and keyword recall, no embeddings by default
restricted  # canonical storage only, excluded from context by default
```

Worker and operational commands:

```bash
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.worker --once
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.doctor
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.admin repair-projections --space project-alpha --memory_scope default --dry-run
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.admin import-memory_scope --space project-alpha --memory_scope default --file memory_scope-export.json --dry-run
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.eval run --suite small-golden
MEMORY_SERVICE_TOKEN=local-dev-token .venv/bin/python -m infinity_context_server.eval run --suite quality-golden
```

Service tokens:

```bash
MEMORY_SERVICE_TOKEN=root-token .venv/bin/python -m infinity_context_server.admin token create --description app
MEMORY_SERVICE_TOKEN=root-token .venv/bin/python -m infinity_context_server.admin token create --space space_project_alpha --description project-alpha --expires-at 2026-12-31T23:59:59+00:00
MEMORY_SERVICE_TOKEN=root-token .venv/bin/python -m infinity_context_server.admin token create --space space_project_alpha --memory_scope memory_scope_default --description project-alpha-default
MEMORY_SERVICE_TOKEN=root-token .venv/bin/python -m infinity_context_server.admin token list
MEMORY_SERVICE_TOKEN=root-token .venv/bin/python -m infinity_context_server.admin token revoke --token-id tok_...
```

The static `MEMORY_SERVICE_TOKEN` is a root token. Database service tokens are
stored as hashes only. A token created with `--space` is scoped to that space
id or slug and cannot access another space or unscoped diagnostics/list routes.
Add repeatable `--memory_scope` values to restrict a token to specific memory_scope ids
or external refs inside the allowed space.
Expired or revoked database tokens are rejected immediately. Token list output
contains ids, descriptions, scope, timestamps and status, never raw token values.

Graphiti local enablement requires Graphiti runtime dependencies plus Neo4j:

```bash
MEMORY_GRAPHITI_ENABLED=true \
MEMORY_GRAPHITI_NEO4J_URI=bolt://127.0.0.1:7687 \
MEMORY_GRAPHITI_NEO4J_USER=neo4j \
MEMORY_GRAPHITI_NEO4J_PASSWORD=<password> \
MEMORY_GRAPHITI_BUILD_INDICES=true \
MEMORY_SERVICE_TOKEN=local-dev-token \
.venv/bin/python -m infinity_context_server.main
```

The client compatibility gateway is opt-in for older client integrations that
still call `/api/v1/interview-memory/*`. New integrations should prefer the
canonical `/v1/*` API or `infinity_context_sdk`.

```bash
MEMORY_DEFAULT_SPACE_SLUG=client-app \
MEMORY_LEGACY_CLIENT_ENABLED=true \
make infinity-context-up-lite
```

Smoke the client compatibility gateway directly:

```bash
curl -X POST http://127.0.0.1:7788/api/v1/interview-memory/context \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session-123",
    "current_request": {
      "id": "req-1",
      "label": "request",
      "text": "What memory is available for this session?"
    }
  }'
```

Other apps can use canonical ids or external scope refs. External refs are the
recommended integration shape for app sessions because the server resolves them
to canonical `space_id/memory_scope_id/thread_id` behind the API boundary:

```bash
curl -X POST http://127.0.0.1:7788/v1/episodes \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "space_slug": "project-alpha",
    "memory_scope_external_ref": "default",
    "thread_external_ref": "session-123",
    "source_type": "system_audio",
    "source_external_id": "event-123",
    "text": "Candidate prefers FIFO queue for event processing.",
    "idempotency_key": "event-123"
  }'

curl -X POST http://127.0.0.1:7788/v1/context \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "space_slug": "project-alpha",
    "memory_scope_external_ref": "default",
    "thread_external_ref": "session-123",
    "query": "What did the candidate prefer for event processing?",
    "token_budget": 512
  }'
```

SDK example:

```python
from infinity_context_sdk import InfinityContextClient

client = InfinityContextClient(token="local-dev-token")
client.remember_fact(
    space_id="space_project_alpha",
    memory_scope_id="memory_scope_default",
    text="Postgres is canonical truth.",
    kind="architecture_decision",
    source_refs=[{"source_type": "manual", "source_id": "note-1"}],
)

client.ingest_episode(
    space_slug="project-alpha",
    memory_scope_external_ref="default",
    thread_external_ref="session-123",
    source_type="system_audio",
    source_external_id="event-123",
    text="Candidate prefers FIFO queue for event processing.",
    idempotency_key="event-123",
)

context = client.build_context(
    space_slug="project-alpha",
    memory_scope_external_ref="default",
    thread_external_ref="session-123",
    query="event processing preference",
    token_budget=512,
)

typed_context = client.build_typed_context(
    space_slug="project-alpha",
    memory_scope_external_ref="default",
    thread_external_ref="session-123",
    query="event processing preference",
    token_budget=512,
)
assert typed_context.answer_support.status in {"strong", "partial", "missing"}

suggestion = client.create_suggestion(
    space_id="space_project_alpha",
    memory_scope_id="memory_scope_default",
    candidate_text="Qdrant is a derived index.",
    kind="architecture_decision",
    safe_reason="review_required",
    source_refs=[{"source_type": "manual", "source_id": "note-2"}],
)
client.approve_suggestion(suggestion["data"]["id"], reason="reviewed")
```

## Local Verification

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m infinity_context_server.eval run --suite small-golden
.venv/bin/python -m infinity_context_server.eval run --suite quality-golden
```
