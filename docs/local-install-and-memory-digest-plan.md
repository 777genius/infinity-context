# Memo Stack Local Install And Memory Digest Plan

## Status

Implemented.

Current implementation evidence:

- `scripts/install.sh` provides the curl/local installer path.
- `memo-stack` CLI provides `init`, `up`, `down`, `restart`, `status`, `doctor`, `logs`,
  `mcp-config` and `digest`.
- `POST /v1/digest` exposes Memory Digest over HTTP.
- `MemoStackClient.build_digest` exposes the SDK contract.
- `memory_digest` exposes the read-only MCP tool.
- `make memo-stack-test-quality` passes with the digest/API/SDK/MCP/CLI implementation.

This plan is intentionally narrower than the global SaaS/platform plan. It focuses on two product
surfaces that make Memo Stack usable by real users quickly:

1. One-command local install through `curl`.
2. Local mode that starts a usable Memo Stack runtime on a developer machine.
3. A `Memory Digest` style tool that gives agents and humans a compact, source-bound summary of
   relevant memory.

The implementation must keep the existing Clean Architecture shape:

- domain and application code do not know about Docker, curl, shell installers, MCP clients or CLI
  file paths;
- delivery adapters call application use cases through stable contracts;
- Graphiti, Qdrant, Cognee, Postgres and future engines remain replaceable adapters;
- prompt-facing outputs are evidence, not instructions.

## Current Repo State

Observed current state:

- `pyproject.toml` exposes MCP scripts only:
  - `memo-stack-mcp`
  - `memo-stack-mcp-bench`
  - `memo-stack-mcp-agent-bench`
- `Makefile` already has local runtime targets:
  - `memo-stack-up-lite`
  - `memo-stack-up-full`
  - `memo-stack-smoke`
  - `memo-stack-mcp-smoke`
  - plugin/agent validation and smoke targets
- `BuildContextUseCase` already composes:
  - `CanonicalContextCollector`
  - `VectorContextCollector`
  - `GraphContextCollector`
  - `RagContextCollector`
  - `ContextHydrator`
  - `ContextPacker`
- API already exposes:
  - `POST /v1/context`
  - `POST /v1/search`
- MCP already exposes:
  - `memory_search`
  - fact create/update/forget tools
  - suggestion/capture tools
  - resources including `memory://scope/{space}/{memory_scope}/summary`
- The existing scope summary resource is only a preview of facts and suggestions. It is not a
  first-class digest product surface.

Important conclusion:

`Memory Digest` must not be implemented as MCP-only glue. It should be an application use case with
API, SDK, MCP and CLI adapters.

## Product Target

### One-Command Local Install

Target UX:

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/memo-stack/main/scripts/install.sh | bash
```

Safer documented UX:

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/memo-stack/main/scripts/install.sh -o install.sh
bash install.sh
```

After install:

```bash
memo-stack up
memo-stack status
memo-stack doctor
memo-stack mcp-config --agent codex
memo-stack digest "current architecture decisions" --space default --memory_scope hackinterview
```

The first version is local-only. It does not need OAuth, hosted billing, multi-tenant cloud, remote
MCP auth or team admin.

### Memory Digest

Target UX through CLI:

```bash
memo-stack digest "Graphiti and Qdrant decisions" \
  --space hackinterview \
  --memory_scope engineering \
  --format markdown
```

Target UX through MCP:

```text
memory_digest(topic="Graphiti and Qdrant decisions", space_slug="hackinterview")
```

The digest should answer:

- What do we currently know about this topic?
- Which facts are canonical and active?
- Which decisions were superseded?
- Which pending suggestions need review?
- Which source snippets support the answer?
- Were vector, graph or RAG providers degraded?
- What was truncated?

The digest is evidence-only. It must not produce commands for the agent to follow.

## Options Considered

### Installer

| Option | Score | Approx LOC | Notes |
| --- | --- | ---: | --- |
| A. `curl install.sh` clones repo and uses docker compose | 🎯 10 🛡️ 8 🧠 4 | 700-1500 | Recommended now. Fastest path to real local usage. |
| B. `pipx install memo-stack` with bundled CLI and compose templates | 🎯 8 🛡️ 8 🧠 6 | 1200-2500 | Good later when packaging is stable. |
| C. Homebrew/tap/native binary | 🎯 7 🛡️ 8 🧠 7 | 1500-3000 | Good distribution UX, but release ops are not needed yet. |

Decision: implement A first, but design the CLI so B/C can reuse it later.

### Local Runtime

| Option | Score | Approx LOC | Notes |
| --- | --- | ---: | --- |
| A. CLI wraps existing `docker compose` profiles | 🎯 10 🛡️ 8 🧠 4 | 800-1800 | Recommended. Reuses existing runtime and Make targets. |
| B. CLI launches Python server directly with local SQLite/Postgres | 🎯 6 🛡️ 6 🧠 7 | 2500-5000 | More custom runtime work, weaker parity with prod. |
| C. Installer writes only docs/configs, user runs Make manually | 🎯 5 🛡️ 7 🧠 2 | 200-500 | Too manual for broad usage. |

Decision: implement A.

### Memory Digest

| Option | Score | Approx LOC | Notes |
| --- | --- | ---: | --- |
| A. `BuildMemoryDigestUseCase` reuses context collectors/hydration | 🎯 10 🛡️ 9 🧠 5 | 900-1800 | Recommended. Clean, testable, reusable across API/SDK/MCP/CLI. |
| B. Add `digest_mode` to `/v1/context` | 🎯 6 🛡️ 6 🧠 3 | 300-700 | Mixes prompt context and product digest concerns. |
| C. Build digest inside MCP by composing existing tools | 🎯 5 🛡️ 5 🧠 3 | 300-900 | Business logic leaks into adapter. Harder to expose via API/SDK/CLI. |

Decision: implement A.

## Architecture

### Boundary Diagram

```text
scripts/install.sh
  -> local files, git, docker, shell

memo_stack_cli
  -> local runtime adapter
  -> HTTP API client
  -> generated MCP config helpers

memo_stack_mcp
  -> HTTP gateway
  -> memory_digest tool

memo_stack_sdk
  -> HTTP API client

memo_stack_server
  -> FastAPI delivery adapter
  -> BuildMemoryDigestUseCase

memo_stack_core
  -> domain entities
  -> application DTOs
  -> BuildMemoryDigestUseCase
  -> MemoryDigestPacker / MemoryDigestRenderer
  -> ports only

memo_stack_adapters
  -> Postgres repositories
  -> Graphiti graph adapter
  -> Qdrant vector adapter
  -> Cognee RAG adapter
  -> noop adapters
```

### SOLID Rules

SRP:

- `install.sh` installs and delegates. It does not implement domain behavior.
- `memo_stack_cli` owns local UX and process orchestration.
- `BuildMemoryDigestUseCase` owns digest assembly.
- `MemoryDigestRenderer` owns output formatting.
- `ContextCollector` classes continue to own retrieval candidate collection.

OCP:

- Adding Homebrew/pipx later adds a distribution adapter, not changes to application use cases.
- Adding another vector DB or graph engine adds an adapter behind existing ports.
- Adding another digest format adds a renderer, not changes to retrieval.

LSP:

- Noop, Qdrant, Graphiti and Cognee adapters must preserve port contracts under degraded states.
- Missing providers return degraded diagnostics, not incompatible payloads.

ISP:

- Do not create one giant `MemoryEnginePort`.
- Reuse narrow ports: unit of work, vector memory, graph memory, RAG recall, embedding.
- Add a digest renderer interface only if there are two real implementations.

DIP:

- Core depends on ports and DTOs.
- Server, MCP, CLI and installer depend inward.
- Shell/Docker/git never appear in core.

## Local Install Design

### Files To Add

```text
scripts/install.sh
packages/memo_stack_cli/memo_stack_cli/__init__.py
packages/memo_stack_cli/memo_stack_cli/__main__.py
packages/memo_stack_cli/memo_stack_cli/cli.py
packages/memo_stack_cli/memo_stack_cli/config.py
packages/memo_stack_cli/memo_stack_cli/runtime.py
packages/memo_stack_cli/memo_stack_cli/doctor.py
packages/memo_stack_cli/memo_stack_cli/mcp_config.py
tests/unit/test_cli_config.py
tests/unit/test_cli_runtime.py
tests/unit/test_install_script_contract.py
tests/e2e/test_cli_local_mode_e2e.py
```

Also update:

```toml
[project.scripts]
memo-stack = "memo_stack_cli.cli:main"
```

And package discovery:

```toml
[tool.setuptools.packages.find]
where = [
  "packages/memo_stack_core",
  "packages/memo_stack_server",
  "packages/memo_stack_adapters",
  "packages/memo_stack_sdk",
  "packages/memo_stack_mcp",
  "packages/memo_stack_cli",
]
```

### Install Home

Default:

```text
~/.memo-stack
```

Layout:

```text
~/.memo-stack/
  config.toml
  .env
  src/
  logs/
  run/
```

Do not write secrets into shell history or stdout.

### `install.sh` Responsibilities

The script should:

1. Detect OS and architecture.
2. Verify required commands:
   - `bash`
   - `git`
   - `docker`
   - `docker compose`
   - `python3` only if local CLI bootstrap needs it.
3. Resolve:
   - repo URL
   - install ref
   - install dir
4. Clone or update repo into `~/.memo-stack/src`.
5. Create local config if missing.
6. Generate a local service token if missing.
7. Avoid overwriting existing `.env` unless `--force`.
8. Install or expose the CLI.
9. Optionally start local lite stack.
10. Run health checks.
11. Print next commands and MCP config paths.

Supported flags:

```bash
scripts/install.sh --dry-run
scripts/install.sh --prefix "$HOME/.memo-stack"
scripts/install.sh --ref main
scripts/install.sh --repo https://github.com/<org>/memo-stack.git
scripts/install.sh --no-start
scripts/install.sh --force
scripts/install.sh --reset
```

`--reset` must be explicit and scary. It may stop containers, but must not delete volumes unless
`--reset-data` is also passed.

### Installer Pseudocode

```bash
#!/usr/bin/env bash
set -euo pipefail

main() {
  parse_args "$@"
  require_command git
  require_command docker
  require_docker_compose
  prepare_home
  clone_or_update_repo
  ensure_local_env
  install_cli_shim
  if [ "$NO_START" != "1" ]; then
    memo-stack up
    memo-stack doctor
  fi
  print_next_steps
}
```

### Idempotency

Running install twice should:

- keep the existing token;
- keep existing data volumes;
- update code only if requested or if default update mode is enabled;
- not duplicate shell profile entries;
- not duplicate agent MCP configs;
- not restart containers unless `--start` or runtime is unhealthy.

### Local CLI Contract

```bash
memo-stack init
memo-stack up [--lite|--full]
memo-stack down
memo-stack restart
memo-stack status [--json]
memo-stack doctor [--json]
memo-stack logs [--service server|worker|postgres|qdrant|neo4j]
memo-stack mcp-config --agent codex|claude|cursor|gemini|opencode [--print|--write]
memo-stack digest <topic> [--space <slug>] [--memory_scope <ref>] [--format json|markdown]
```

For v1:

- `up` wraps docker compose.
- `status` calls `/v1/health` and `/v1/capabilities`.
- `doctor` checks Docker, ports, token, server health, capabilities and MCP command.
- `digest` calls `POST /v1/digest`.

### Runtime Adapter

CLI runtime should be hidden behind a small adapter:

```python
class RuntimePort(Protocol):
    def up(self, compose_profile: str) -> RuntimeResult: ...
    def down(self) -> RuntimeResult: ...
    def status(self) -> RuntimeStatus: ...
    def logs(self, service: str, tail: int) -> str: ...
```

First adapter:

```python
class DockerComposeRuntime(RuntimePort):
    ...
```

This keeps future local runtimes open:

- Docker Compose
- Colima/Lima
- remote API only
- native process mode

### Config Model

```toml
[local]
home = "~/.memo-stack"
repo_dir = "~/.memo-stack/src"
api_url = "http://127.0.0.1:7788"
service_token_env = "MEMORY_SERVICE_TOKEN"
default_memory_scope = "default"

[runtime]
mode = "docker_compose"
compose_profile = "lite"
compose_project_name = "memo_stack"

[mcp]
write_mode = "suggest"
delete_mode = "off"
ingest_mode = "small_docs"
```

## Memory Digest Design

### Concept

`Memory Digest` is a read-only, source-bound memory report for one topic/scope.

It is not:

- a canonical fact;
- a replacement for `/v1/context`;
- a source of higher confidence;
- a prompt instruction block;
- a mutating consolidation job.

It is:

- a compact read model;
- derived from visible canonical sources;
- safe for agents to inspect;
- useful for humans reviewing project state;
- deterministic enough for tests.

### Domain Model

Initial DTOs in `memo_stack_core.application.dto`:

```python
@dataclass(frozen=True)
class BuildMemoryDigestQuery:
    space_id: SpaceId
    memory_scope_ids: tuple[MemoryScopeId, ...]
    thread_id: ThreadId | None
    topic: str
    consistency_mode: ConsistencyMode
    token_budget: int
    max_facts: int
    max_chunks: int
    max_suggestions: int
    include_pending_suggestions: bool
    include_superseded: bool
    include_related: bool
    max_rendered_chars: int


@dataclass(frozen=True)
class MemoryDigestSection:
    title: str
    items: tuple[ContextItem, ...]
    truncated: bool


@dataclass(frozen=True)
class MemoryDigest:
    digest_id: str
    topic: str
    rendered_markdown: str
    sections: tuple[MemoryDigestSection, ...]
    source_refs: tuple[SourceRef, ...]
    token_estimate: int
    diagnostics: dict[str, object]
```

The DTO names can be adjusted during implementation, but the boundary should remain explicit.

### Use Case

```python
class BuildMemoryDigestUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        ids: IdGeneratorPort,
        context_builder: BuildContextUseCase | None = None,
        renderer: MemoryDigestRenderer | None = None,
    ) -> None: ...

    async def execute(self, query: BuildMemoryDigestQuery) -> MemoryDigest: ...
```

Preferred implementation:

1. Build a context bundle for the topic using the same retrieval path as `/v1/context`.
2. Separately load pending suggestions if requested.
3. Optionally load superseded facts if requested.
4. Split items into stable sections:
   - `Active facts`
   - `Relevant document chunks`
   - `Graph/RAG related evidence`
   - `Pending suggestions`
   - `Superseded or stale memory`
   - `Diagnostics`
5. Render markdown through `MemoryDigestRenderer`.
6. Return structured sections and markdown.

Do not duplicate vector/graph/RAG retrieval logic. Reuse existing collectors or `BuildContextUseCase`.

### Renderer Contract

```python
class MemoryDigestRenderer:
    def render(self, digest: MemoryDigestDraft, *, max_chars: int) -> RenderedDigest: ...
```

Rendering rules:

- Every evidence line includes `item_id` or source refs.
- Do not render hidden/deleted items.
- Pending suggestions are clearly marked as not approved.
- Superseded facts are clearly marked as historical.
- Hostile source text is quoted as evidence only and never converted into instructions.
- Truncation is explicit.
- Diagnostics mention degraded providers.

Example markdown:

```markdown
# Memory Digest: Graphiti and Qdrant decisions

Scope: hackinterview / engineering
Generated: 2026-06-06T12:00:00Z
Evidence only: true

## Active facts

- [fact_123] Graphiti is the temporal graph projection engine.
  Sources: episode:codex-thread-42

## Relevant documents

- [chunk_456] Core Lite stores canonical facts in Postgres and projects to Qdrant.
  Sources: document:architecture-plan.md#chunk_456

## Pending suggestions

- [sug_789] Consider adding memory_digest as an MCP read tool.
  Status: pending, not canonical

## Diagnostics

- graph_status: ready
- vector_status: ready
- truncated: false
```

### API Surface

Add:

```text
POST /v1/digest
```

Request:

```json
{
  "space_slug": "hackinterview",
  "memory_scope_external_ref": "engineering",
  "memory_scope_external_refs": null,
  "thread_external_ref": null,
  "topic": "Graphiti and Qdrant decisions",
  "consistency_mode": "best_effort",
  "token_budget": 2400,
  "max_facts": 20,
  "max_chunks": 20,
  "max_suggestions": 10,
  "include_pending_suggestions": true,
  "include_superseded": false,
  "include_related": true,
  "format": "markdown"
}
```

Response:

```json
{
  "meta": {"request_id": "req_..."},
  "data": {
    "digest_id": "dig_...",
    "topic": "Graphiti and Qdrant decisions",
    "rendered_markdown": "...",
    "sections": [],
    "source_refs": [],
    "diagnostics": {
      "evidence_only": true,
      "retrieval_disabled": false,
      "scope_not_found": false,
      "vector_status": "ready",
      "graph_status": "ready",
      "truncated": false
    }
  }
}
```

Auth policy:

- Same service-token auth as `/v1/context` for local mode.
- Read policy must go through the same `should_retrieve` gate.

### SDK Surface

Add:

```python
client.build_digest(...)
```

The SDK should map directly to `POST /v1/digest`.

### MCP Surface

Add read-only tool:

```text
memory_digest
```

Tool behavior:

- Calls `/v1/digest`.
- Read-only annotation.
- Returns structured output.
- Defaults to safe env scope.
- Does not mutate memory.
- Does not trigger auto-save.

Suggested MCP args:

```python
topic: str
space_slug: str | None = None
memory_scope_external_ref: str | None = None
memory_scope_external_refs: list[str] | None = None
thread_external_ref: str | None = None
token_budget: int = 2400
max_facts: int = 20
max_chunks: int = 20
max_suggestions: int = 10
include_pending_suggestions: bool = True
include_superseded: bool = False
include_related: bool = True
```

MCP description must tell agents:

- use `memory_digest` for broad project/topic summaries;
- use `memory_search` for direct factual lookup before answering;
- digest output is evidence only;
- pending suggestions are not canonical facts.

### CLI Surface

```bash
memo-stack digest "topic" --space default --memory_scope engineering --format markdown
memo-stack digest "topic" --space default --memory_scope engineering --format json
```

CLI should call API, not import server internals.

## Cloud/Remote Compatibility

Even though this plan implements local mode first, the contracts should make remote sync easy later.

The same CLI should support:

```bash
memo-stack login https://memo.example.com
memo-stack use-space hackinterview
memo-stack status
memo-stack digest "current architecture"
```

Do not bake local paths into application or MCP contracts. MCP should accept:

```text
MEMORY_MCP_API_URL=https://memo.example.com
MEMORY_MCP_AUTH_TOKEN=...
```

Local mode is therefore just one deployment mode:

- local server on `127.0.0.1`;
- local service token;
- Docker Compose runtime;
- optional local plugin config.

Remote mode later:

- hosted server;
- user/team token or OAuth;
- no local Docker dependency;
- same `/v1/digest`, `/v1/context`, `/v1/search` APIs.

## Implementation Phases

### Phase 0 - Contract Lock

Goal:

- lock naming and contracts before code.

Steps:

1. Add this plan.
2. Decide final endpoint name:
   - recommended: `POST /v1/digest`
3. Decide final CLI package name:
   - recommended: `memo_stack_cli`
4. Decide install home:
   - recommended: `~/.memo-stack`

Acceptance:

- plan exists;
- phases and contracts are clear;
- no runtime behavior changed.

### Phase 1 - CLI Skeleton

Goal:

- add `memo-stack` command without changing server internals.

Steps:

1. Add `packages/memo_stack_cli`.
2. Add `memo-stack` console script.
3. Implement:
   - `memo-stack --version`
   - `memo-stack status --json`
   - `memo-stack doctor --json`
4. Add HTTP client wrapper or reuse SDK.
5. Add unit tests for config/env resolution.

Acceptance:

```bash
memo-stack --version
memo-stack status --json
memo-stack doctor --json
```

### Phase 2 - Local Runtime Mode

Goal:

- make local start/stop/status ergonomic.

Steps:

1. Add `RuntimePort`.
2. Add `DockerComposeRuntime`.
3. Implement:
   - `memo-stack init`
   - `memo-stack up --lite`
   - `memo-stack down`
   - `memo-stack logs`
4. Reuse existing compose profiles.
5. Add doctor checks:
   - Docker installed
   - Docker daemon available
   - compose available
   - port 7788 availability or health
   - token present
   - `/v1/health`
   - `/v1/capabilities`

Acceptance:

```bash
memo-stack init
memo-stack up --lite
memo-stack doctor
memo-stack down
```

### Phase 3 - Curl Installer

Goal:

- one-command local install.

Steps:

1. Add `scripts/install.sh`.
2. Add flags:
   - `--dry-run`
   - `--prefix`
   - `--repo`
   - `--ref`
   - `--no-start`
   - `--force`
3. Add token generation without token echo.
4. Add idempotent clone/update.
5. Add CLI shim installation.
6. Add shell contract tests:
   - `bash -n scripts/install.sh`
   - dry-run does not write files;
   - existing config is preserved.

Acceptance:

```bash
bash scripts/install.sh --dry-run
bash scripts/install.sh --prefix /tmp/memo-stack-test --no-start
```

### Phase 4 - Digest Core

Goal:

- implement digest use case in application layer.

Steps:

1. Add DTOs:
   - `BuildMemoryDigestQuery`
   - `MemoryDigest`
   - `MemoryDigestSection`
2. Add `BuildMemoryDigestUseCase`.
3. Add `MemoryDigestRenderer`.
4. Reuse `BuildContextUseCase` or existing collectors.
5. Add suggestions/superseded loading through repositories/use cases.
6. Add unit tests:
   - active facts included;
   - deleted facts excluded;
   - superseded facts excluded by default;
   - pending suggestions marked as non-canonical;
   - prompt injection remains quoted/evidence-only;
   - degraded providers appear in diagnostics;
   - token/max char budget truncates predictably.

Acceptance:

```bash
pytest tests/unit/test_memory_digest_use_case.py -q
```

### Phase 5 - API And SDK

Goal:

- expose digest to clients.

Steps:

1. Add `memo_stack_server/api/v1/digest.py`.
2. Register router.
3. Add OpenAPI contract tests.
4. Add SDK method `build_digest`.
5. Add API unit tests.

Acceptance:

```bash
curl -X POST http://127.0.0.1:7788/v1/digest \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"space_slug":"default","memory_scope_external_ref":"default","topic":"architecture"}'
```

### Phase 6 - MCP Tool

Goal:

- agents can request broad memory summaries.

Steps:

1. Add HTTP gateway method.
2. Add `MemoryToolService.digest`.
3. Add `memory_digest` tool in MCP server.
4. Add structured response schema.
5. Update skill/docs to teach when to use digest vs search.
6. Add MCP unit tests.
7. Add MCP e2e with a local server.

Acceptance:

```bash
make memo-stack-mcp-smoke
pytest tests/e2e/test_memo_stack_mcp_e2e.py -q
```

### Phase 7 - CLI Digest

Goal:

- humans can run digest locally.

Steps:

1. Add `memo-stack digest`.
2. Support `--format markdown|json`.
3. Support scope flags.
4. Add CLI tests.

Acceptance:

```bash
memo-stack digest "architecture decisions" --format markdown
```

### Phase 8 - Docs And Release Hardening

Goal:

- make it usable by someone who just found the repo.

Steps:

1. Update README quickstart.
2. Add local install docs.
3. Add uninstall docs.
4. Add troubleshooting docs.
5. Add plugin setup docs.
6. Add secret-scan gate.

Acceptance:

```bash
make memo-stack-test-quality
git diff --check
make memo-stack-secret-scan
```

## Edge Cases

### Installer Edge Cases

- Docker is missing.
- Docker daemon is not running.
- Docker Compose v2 is missing.
- Port 7788 is already used.
- Existing install dir contains a different repo.
- Existing `.env` contains a user token.
- User runs install twice.
- User interrupts install halfway.
- Network is unavailable during clone.
- GitHub raw URL is unreachable.
- macOS/Linux path differences.
- Shell is `zsh`, but script must run under bash.
- `curl | bash` hides script path. The installer must resolve paths after clone.
- Token generation command differs across platforms.
- User wants no startup, only install.
- User wants update without deleting data.
- User wants uninstall without deleting volumes.
- User wants full provider mode but has no OpenAI key.
- Script output must not print tokens.

### Local Runtime Edge Cases

- Server container is healthy but worker failed.
- Postgres is up but schema is missing.
- Old containers from previous project name exist.
- Compose project name changed.
- Full profile starts Qdrant/Neo4j but embeddings key is missing.
- `memo-stack down` must not remove data by default.
- `memo-stack doctor` should return machine-readable JSON for support.

### Digest Edge Cases

- Scope does not exist.
- Retrieval disabled by policy.
- Topic is too broad.
- Topic is empty or only whitespace.
- Query contains secrets.
- No results found.
- Duplicate facts and chunks.
- Vector result points to deleted canonical chunk.
- Graphiti result mentions superseded fact.
- Pending suggestion contradicts active fact.
- Multiple memory scopes are requested.
- Thread scope exists but memory scope does not.
- Source refs are missing.
- Source was hard-deleted.
- Prompt injection is present in source text.
- Provider degraded:
  - vector disabled;
  - graph disabled;
  - RAG disabled;
  - embedder timeout.
- Token budget is too small.
- Digest is truncated.
- Unicode and long document titles.
- Concurrent update/delete while digest is built.
- Results must be deterministic enough for snapshot tests.

## Test Plan

### Unit

```bash
pytest tests/unit/test_cli_config.py -q
pytest tests/unit/test_cli_runtime.py -q
pytest tests/unit/test_memory_digest_use_case.py -q
pytest tests/unit/test_memory_digest_renderer.py -q
pytest tests/unit/test_digest_api.py -q
pytest tests/unit/test_sdk_contract.py -q
pytest tests/unit/test_mcp_adapter.py -q
```

### E2E

```bash
make memo-stack-smoke
pytest tests/e2e/test_cli_local_mode_e2e.py -q
pytest tests/e2e/test_memory_digest_e2e.py -q
pytest tests/e2e/test_memo_stack_mcp_e2e.py -q
```

### Full Provider Canary

Run only when API key is explicitly provided through env:

```bash
MEMORY_OPENAI_API_KEY=... make memo-stack-full-provider-canary
```

This verifies Graphiti/Qdrant/OpenAI wiring, but digest must also pass in lite mode with degraded
provider diagnostics.

### Release Gate

```bash
make memo-stack-test-quality
git diff --check
make memo-stack-secret-scan
```

## Acceptance Criteria

The feature is done when all of this is true:

- A fresh user can install locally with one curl command.
- The install is idempotent.
- Local data is preserved by default.
- `memo-stack up` starts the lite stack.
- `memo-stack doctor` diagnoses common setup problems.
- `memo-stack mcp-config` prints or writes agent config safely.
- `POST /v1/digest` returns a structured evidence-only digest.
- SDK exposes the same digest operation.
- MCP exposes `memory_digest`.
- CLI exposes `memo-stack digest`.
- Digest excludes deleted facts.
- Digest marks pending suggestions as non-canonical.
- Digest does not leak secrets from env/config.
- Digest handles degraded Graphiti/Qdrant/Cognee providers.
- Tests cover unit, API, SDK, MCP and local CLI paths.

## Recommended First Implementation Slice

Do this first:

1. `memo_stack_cli` package with `status`, `doctor`, `up`, `down`.
2. `scripts/install.sh --dry-run` and idempotent local config.
3. `BuildMemoryDigestUseCase` using existing `BuildContextUseCase`.
4. `POST /v1/digest`.
5. `memory_digest`.
6. `memo-stack digest`.

Expected first slice size:

- CLI/local mode: 1000-1800 LOC.
- installer: 500-1000 LOC.
- digest core/API/SDK/MCP/CLI: 1200-2400 LOC.
- tests: 1000-2200 LOC.

Total realistic first slice:

```text
3700-7400 LOC
```

Complexity:

```text
🎯 9   🛡️ 8   🧠 6
```

This is meaningfully smaller than the full SaaS/cloud plan, but it creates the right foundation for
future hosted/team sync mode.
