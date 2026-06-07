# Memo Stack Docs

This folder contains the platform planning documents moved out of Client App.

## Reading Order

1. [Core Lite implementation plan](memo-stack-core-lite-plan.md)
2. [Global architecture plan](memo-stack-architecture-plan.md)
3. [MCP memory foundation plan](mcp-memory-foundation-plan.md)
4. [Auto-memory capture platform plan](auto-memory-capture-platform-plan.md)
5. [Client compatibility notes](client-integration/interview-memo-stack-clean-architecture-plan.md)
6. [Client integration run notes](client-integration/current-integration-run-notes.md)

## Architecture Decisions

- [ADR-0001 - Memo Stack Core Lite Boundaries](adr/ADR-0001-memo-stack-core-lite-boundaries.md)
- [ADR-0002 - Postgres Is Canonical Truth](adr/ADR-0002-postgres-canonical-truth.md)
- [ADR-0003 - Canonical Fact Lifecycle](adr/ADR-0003-canonical-fact-lifecycle.md)
- [ADR-0004 - Derived Retrieval Adapters](adr/ADR-0004-derived-retrieval-adapters.md)
- [ADR-0005 - Capability Ports For Cognee And Graphiti](adr/ADR-0005-capability-ports-cognee-graphiti.md)

## Ownership

These docs now belong to:

```text
/Users/belief/dev/projects/ai/memo-stack
```

Client App should keep only integration notes and pointers to this project.

## Local Docker Runbook

Start the local platform stack through explicit profiles:

```bash
make memo-stack-up-lite
make memo-stack-up-full
```

`lite` runs Postgres plus the Memo Stack Server and worker with provider adapters
disabled. `full` also runs Qdrant, Neo4j and the outbox worker, and requires
`OPENAI_API_KEY` plus `MEMORY_OPENAI_API_KEY`.

Local smokes:

```bash
make memo-stack-smoke
make memo-stack-smoke-full
make memo-stack-mcp-smoke
```

Quality gates:

```bash
make memo-stack-test-quality
make memo-stack-plugin-test
.venv/bin/python -m memo_stack_server.eval run --suite quality-golden
```

`quality-golden` is the prompt-impacting memory benchmark. It checks recall,
precision, stale update filtering, delete filtering, restricted-memory hiding,
profile and thread isolation, document chunk recall, prompt-injection evidence rendering
and tiny token-budget safety. Reports are redacted and contain case ids,
item ids, gates and aggregate metrics, not raw memory text.

Fresh full-provider canary with isolated Docker volumes:

```bash
make memo-stack-clean-full-smoke
make memo-stack-clean-full-mcp-smoke
make memo-stack-full-provider-canary-interactive
```

This is a manual paid canary. It requires Docker plus `MEMORY_OPENAI_API_KEY`
or `OPENAI_API_KEY`, starts isolated Postgres, Qdrant and Neo4j containers,
uses OpenAI embeddings, and tears the stack down unless
`MEMORY_CLEAN_SMOKE_KEEP_STACK=true`.
Use `memo-stack-full-provider-canary-interactive` when the key is not already
exported; it reads the key with terminal echo disabled and passes it only via
process environment.

`memo-stack-clean-full-smoke` now runs the real stdio MCP canary by default. To
run only the historical HTTP/API full-provider smoke, set:

```bash
MEMORY_CLEAN_SMOKE_SKIP_MCP=true make memo-stack-clean-full-smoke
```

Publishable top-library evidence should use the stricter bundle gate:

```bash
make memo-stack-top-evidence-preflight
MEMORY_AGENT_BENCH_MODEL="$MODEL" \
MEMORY_OPENAI_API_KEY="$KEY" \
MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET=/path/to/locomo.json \
MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET=/path/to/longmemeval.json \
make memo-stack-top-evidence-bundle
```

The preflight fails before Docker/OpenAI work if the worktree is dirty, Docker
is unavailable, the key/model is missing, representative public datasets are
missing, `MEMORY_AGENT_BENCH_SCENARIO_SET` is not `all`,
`MEMORY_PUBLIC_BENCHMARK_NAME` is not `all`, or the public benchmark is configured
below 600 cases / 0.902 minimum accuracy. The top-evidence bundle defaults the
agent benchmark to `all`, which runs core, realistic, live-session and transcript
corpus scenarios so live/transcript/adversarial pass rates cannot be satisfied by
zero-case metrics. It also parses the LoCoMo and LongMemEval dataset files
through the same normalizer used by the benchmark runner and rejects empty,
invalid or under-sized datasets before paid provider work starts. It prints only
safe diagnostics and never echoes API keys.
`MEMORY_QUALITY_EVIDENCE_ALLOW_DIRTY_TOP=true` is accepted only for local
diagnostics; publishable evidence should stay clean. Floor overrides such as
`MEMORY_TOP_EVIDENCE_MIN_PUBLIC_CASES` and
`MEMORY_TOP_EVIDENCE_MIN_PUBLIC_ACCURACY` can only make the gate stricter than
the defaults, not weaker.

Local smoke variables:

```text
MEMORY_SMOKE_API_URL=http://127.0.0.1:7788
MEMORY_SMOKE_AUTH_TOKEN=(set via environment; Makefile supplies local dev fallback)
```

The smoke script uses only the public SDK and verifies the Phase 7 path:
health, space/profile creation, remember, update, document ingest, search,
context and forget.

The MCP smoke starts a real stdio MCP client and verifies status, search,
remember, update and forget through MCP tools. `memo_stack_server` runs database
upgrade and `seed-defaults` during Docker startup. The Compose file waits for
Postgres health before starting the server and exposes a server healthcheck on
`/v1/health`.

The plugin gate validates repo-local agent packaging for Codex, Claude, Gemini,
OpenCode, Cursor package config and Cursor workspace config:

```bash
make memo-stack-plugin-test
make memo-stack-prod-confidence
make memo-stack-prod-confidence-strict-preflight
make memo-stack-prod-confidence-strict
```

It runs `plugin-kit-ai generate --check`, strict target validation and generated
MCP e2e coverage. Use `make memo-stack-plugin-doctor` after
`make memo-stack-up-lite` for the live API readiness check.
`memo-stack-prod-confidence` is the one-command unpaid release gate. It runs plugin
validation/e2e, the full deterministic memory quality suite, install doctor,
isolated live MCP smoke, advisory real-agent smoke, advisory auth doctor,
`git diff --check` and a repository secret scan. It also installs a cleanup trap
and runs `memo-stack-down` on exit.
`memo-stack-prod-confidence-strict` is the paid/local-auth hard gate for a fully
green release. It runs the strict top-evidence bundle, which requires
`MEMORY_OPENAI_API_KEY` or `OPENAI_API_KEY`, `MEMORY_AGENT_BENCH_MODEL`,
representative LoCoMo and LongMemEval dataset files, a clean worktree, the
isolated Graphiti/Qdrant/OpenAI MCP canary, real agent-behavior evidence and the
public benchmark evidence bundle. It also treats real
Codex/Claude/Gemini/OpenCode CLI auth failures as hard failures.
`memo-stack-prod-confidence-strict-preflight` runs first and fails before paid
provider/model work when top-evidence config or real-agent auth is missing.
`memo-stack-prod-confidence-full` is an alias for the strict gate.

Agent install verification is separate from package validation because
`plugin-kit-ai validate` and `plugin-kit-ai add` use different target names:

```bash
make memo-stack-agent-install-dry-run
make memo-stack-agent-install
make memo-stack-agent-install-doctor
make memo-stack-agent-live-smoke
make memo-stack-agent-live-smoke-agents
make memo-stack-agent-live-smoke-agents-strict
make memo-stack-agent-auth-doctor
make memo-stack-agent-auth-doctor-strict
make memo-stack-agent-auth-repair
make memo-stack-prod-confidence-strict-preflight
```

The managed install targets are `codex`, `claude`, `gemini`, `opencode` and
`cursor`. Cursor workspace config remains a generated workspace-copy lane and
is covered by plugin e2e, not by `plugin-kit-ai integrations`.
`memo-stack-agent-live-smoke` is the stable hard gate for generated MCP configs. It
starts the local lite stack and verifies stdio `memory_status` through the
package, Gemini, OpenCode and Cursor workspace generated configs. Real agent
CLI evidence is separated into `memo-stack-agent-live-smoke-agents`; that target
reports missing Claude/Gemini/OpenCode/Codex auth/session state as advisory
blocked evidence. Use `memo-stack-agent-live-smoke-agents-strict` only on a machine
where every local agent CLI is authenticated and expected to pass.
The live-smoke targets use isolated default host ports
`MEMORY_AGENT_SMOKE_SERVER_PORT=17788` and
`MEMORY_AGENT_SMOKE_POSTGRES_PORT=55429`, so they do not accidentally verify
against another local Memo Stack Server already running on `7788`.
Gemini installed extensions persist MCP env inside the extension config. The
real-agent smoke keeps that persisted config intact and passes
`MEMORY_MCP_RUNTIME_*` overrides through the repo-local wrapper, so an installed
extension can still target the default `127.0.0.1:7788` while the isolated smoke
stack is verified on `17788`. Without these runtime overrides, a mismatched
persisted Gemini URL remains a blocked preflight.
Gemini CLI can inject a `wait_for_previous` sequencing argument into MCP tool
calls. The MCP adapter ignores only that known host argument before strict input
validation; arbitrary unknown arguments remain rejected.
`memo-stack-agent-auth-doctor` runs plain agent prompts without Memo Stack MCP. If it
reports Claude or OpenCode 401, fix the local agent credentials before blaming
the Memory plugin or MCP transport. `memo-stack-agent-auth-repair` is an
interactive helper for the local machine; it runs the official Claude and
OpenCode login flows and then re-runs the strict auth doctor.
Run `memo-stack-prod-confidence-strict-preflight` before paid canaries on a fresh
machine; it catches missing OpenAI env and local agent auth problems before the
Graphiti/Qdrant/OpenAI full-provider stack starts.
`memo-stack-agent-install-doctor` also treats `plugin-kit-ai integrations list` and
`plugin-kit-ai integrations doctor` failures as hard failures, even when the
local structured state file still looks valid.

Auto-memory capture quality has its own deterministic gate:

```bash
make memo-stack-auto-memory-eval
make memo-stack-auto-memory-quality
```

The eval suite runs against public server APIs and verifies that review-gated
captures do not become active facts before approval, `auto_apply_safe` does not
promote medium-confidence extractor output, prompt-injection captures are not
promoted, secrets are redacted on safe surfaces, replay is idempotent and
approved facts block duplicate pending suggestions.

The clean full MCP canary uses the same isolated full-provider stack and
verifies MCP status/readiness, fact lifecycle, document chunk recall through
Qdrant, Graphiti projection updates/deletes, outbox drain, provider
diagnostics and token redaction. It is intentionally not part of
`make memo-stack-test-quality`. `make memo-stack-full-provider-canary` is an alias for
the same paid gate.

For production-like scale, chaos and load coverage:

```bash
MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-prod-load-canary
```

This uses the same clean Docker full stack, then adds concurrent fact writes,
idempotent retry races, multi-profile corpus growth, document ingest, auth and
validation floods, worker drain checks, API and stdio MCP retrieval, update,
delete, Qdrant/Graphiti recall and context latency p95. The regular free e2e
gate also covers concurrent document idempotency, outbox backpressure, mutation
storms, stale outbox lag alerting with worker drain recovery, dead outbox
runbook recovery through `memo_stack_server.admin replay-outbox`, expired worker
lease recovery through the worker CLI, and poison outbox handling where an
unknown projection job must become `dead`, raise a safe alert, fail
`memo_stack_server.doctor` as degraded without leaking payload, and leave canonical
read/write paths available. The same free gate also verifies Memo Stack Server
process restart continuity: canonical facts/documents survive restart,
idempotency retries do not create duplicates, updated/deleted facts stay
filtered and restricted facts remain hidden. Maintenance coverage includes
`memo_stack_server.admin compact-outbox`: dry-run stays non-mutating, actual
compaction redacts done-job payloads, diagnostics stay safe and canonical
context retrieval still works.
The paid full-stack canary additionally verifies thread-scoped isolation, large
multi-chunk document recall, Memo Stack Server restart continuity, Qdrant/Neo4j
provider restart recovery, and provider outage recovery where projection jobs
must enter retry and drain after providers return. It is paid/manual and does
not run in `make memo-stack-test-quality`.

Useful knobs for larger runs:

- `MEMORY_CLEAN_SMOKE_LOAD_PROFILES` - default `3`, max `12`.
- `MEMORY_CLEAN_SMOKE_LOAD_FACTS_PER_PROFILE` - default `8`, max `100`.
- `MEMORY_CLEAN_SMOKE_LOAD_DOCUMENTS` - default `3`, max `30`.
- `MEMORY_CLEAN_SMOKE_LOAD_LARGE_DOC_SECTIONS` - default `18`, max `80`.
- `MEMORY_CLEAN_SMOKE_LOAD_CONCURRENCY` - default `6`, max `24`.
- `MEMORY_CLEAN_SMOKE_LOAD_CHAOS_REQUESTS` - default `16`, max `200`.
- `MEMORY_CLEAN_SMOKE_LOAD_CONTEXT_REQUESTS` - default `10`, max `200`.
- `MEMORY_CLEAN_SMOKE_LOAD_MAX_P95_MS` - default `15000`.
- `MEMORY_CLEAN_SMOKE_LOAD_RESTART_SERVER` - default `true`.
- `MEMORY_CLEAN_SMOKE_LOAD_RESTART_PROVIDERS` - default `true`.
- `MEMORY_CLEAN_SMOKE_LOAD_PROVIDER_OUTAGE` - default `true`.

The real LLM agent-behavior benchmark is a stricter paid/manual gate. It uses
the same fresh full-provider stack, exposes `memo_stack_mcp` tools to an OpenAI
Responses API model as function tools, executes chosen calls through real stdio
MCP, then scores whether the model searched before writes, updated instead of
duplicating, avoided secrets, respected scope isolation and treated retrieved
memory as evidence.

```bash
MEMORY_AGENT_BENCH_MODEL="$MODEL" MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-agent-behavior-bench
```

For noisier, more production-like scenarios:

```bash
MEMORY_AGENT_BENCH_MODEL="$MODEL" MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-agent-realistic-bench
```

The realistic suite covers noisy transcripts, semantic duplicates, similar
project scopes, neighboring thread scopes, ambiguous deletes, long notes with
secrets, prompt-injected retrieved memory and immediate recall after writes.

For long live-agent sessions and adversarial transcript tails:

```bash
MEMORY_AGENT_BENCH_MODEL="$MODEL" MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-agent-live-session-bench
```

The live suite covers long transcript rollups, update plus delete chains,
review-gated uncertain claims, cross-profile meeting noise, credential traps and
long-tail transcript recall. The report includes `live_session_pass_rate` and
`adversarial_pass_rate`.

For transcript-corpus driven long conversation checks:

```bash
MEMORY_AGENT_BENCH_MODEL="$MODEL" MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-agent-transcript-corpus-bench
```

This runs `MEMORY_AGENT_BENCH_SCENARIO_SET=transcript`. The built-in corpus
models long agent handoffs, architecture drift, rejected approaches, precise
deletes, hostile tool output and credential traps. To measure anonymized real
conversation logs without changing code, set
`MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR` to a directory containing `.json`,
`.jsonl` or `.txt` fixtures. JSON fixtures may provide `turns`, `transcript`,
`expected_tools`, `expected_answer_contains`, `expected_memory_contains`,
`forbidden_contains`, `required_memory_checks` and `tags`. File count and size
are bounded by `MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_MAX_FILES` and
`MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_MAX_BYTES`.

To build a safe corpus from local agent logs, first redact them into fixtures:

```bash
MEMORY_AGENT_TRANSCRIPT_INPUT=/path/to/raw-agent-logs \
MEMORY_AGENT_TRANSCRIPT_OUTPUT=/path/to/redacted-corpus \
make memo-stack-agent-transcript-corpus-redact
```

The redactor reads explicit files or a non-recursive directory, masks common
API keys, bearer tokens, passwords, emails and home paths, hashes source ids and
does not write raw source paths into fixtures. Manual annotation is still
recommended for high-signal expected memory checks before treating a corpus as a
release gate.

Then audit the redacted corpus before running it as evidence:

```bash
MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR=/path/to/redacted-corpus \
make memo-stack-agent-transcript-corpus-audit
```

Use `MEMORY_AGENT_TRANSCRIPT_CORPUS_AUDIT_STRICT=true` when a corpus must be
release-gate ready. Strict mode fails fixtures that are safe but still lack
high-signal expected checks such as `required_memory_checks`,
`expected_answer_contains` or `expected_memory_contains`.

For the broad paid/manual "real memory in battle" gate:

```bash
MEMORY_AGENT_BENCH_MODEL="$MODEL" MEMORY_OPENAI_API_KEY="$KEY" make memo-stack-real-memory-confidence
```

That gate runs the full-provider MCP canary, prod-load canary, live-session
agent benchmark and transcript-corpus benchmark before `git diff --check` and
secret scan. It uses `memo-stack-top-evidence-bundle` for the full-provider plus
public benchmark path, so the scorecard only becomes top-library-comparison-ready
when strict provenance, Graphiti/Qdrant/OpenAI, agent behavior and public
benchmark evidence are all present. Paid agent benchmark targets default
`MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR=true`, so provider projection worker
failures after mutating MCP tools fail the benchmark instead of being treated as
soft warnings.

The benchmark now models a minimal host-side memory orchestrator instead of a
totally raw model call. It still uses `tool_choice=auto`, but it allows one
corrective turn if the model answers without required memory tools, blocks
mutating tools until a memory read/search has happened, and allows one
final-answer repair if the model quotes excluded secret/hostile/scratchpad text.
Projection worker catch-up errors are reported as optional diagnostics in this
agent-behavior block; provider correctness remains a hard gate in the full MCP
canary checks.
Blocked mutating calls are not treated as invisible successes: if a blocked
call targets a forbidden tool or contains secret-like input, the benchmark
counts a safety failure while keeping the raw value out of the report. Blocked
write attempts also count against search-before-write and update-vs-duplicate
metrics, even when the model later recovers and completes the operation safely.
The paid report includes `metric_failures` so non-perfect aggregate metrics point
to the exact scenario, tool sequence and reason. The hard gates include safety
leaks, search-before-write, answer support and a minimum update-vs-duplicate
rate.

Read the agent-behavior result separately from the storage result. MCP canary
success means the memory stack and projections work. Agent-behavior failures
usually mean the model skipped a required tool call or stopped after
`memory_status`. Production agents should wrap raw MCP tools with a host-side
memory policy/orchestrator when correctness matters. Direct `memory_remember_fact`
has a server-side duplicate/conflict preflight, but no server can fix a request
where the agent never calls a memory tool.

`MEMORY_AGENT_BENCH_OPENAI_API_KEY` may be used for the agent model key. The
full stack still needs `MEMORY_OPENAI_API_KEY` or `OPENAI_API_KEY` for
embeddings. `MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS`,
`MEMORY_AGENT_BENCH_LLM_TIMEOUT_RETRIES`,
`MEMORY_AGENT_BENCH_OPENAI_HTTP_TIMEOUT_SECONDS`,
`MEMORY_AGENT_BENCH_OPENAI_MAX_RETRIES`,
`MEMORY_AGENT_BENCH_SCENARIO_TIMEOUT_SECONDS` and
`MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS` can tune the paid/manual gate. The
benchmark prints one redacted JSON report and is intentionally not part of
`make memo-stack-test-quality`.
