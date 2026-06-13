# Obsidian Connector Implementation Plan

Status: implementation plan for the hybrid daemon-first, thin-plugin-later path.

Date: 2026-06-07.

## Summary

The Obsidian Connector should make Memo Stack usable as an editable Obsidian-facing
memory surface without letting Obsidian become the canonical memory database.

Recommended shape:

```text
Obsidian vault
  <-> memo_stack_obsidian daemon / CLI
  <-> memo_stack_sdk
  <-> memo_stack_server HTTP API
  <-> Postgres canonical lifecycle
  -> Qdrant / Graphiti derived indexes through existing outbox workers
```

The Obsidian plugin should be a later thin UX shell over the daemon/API. It should
not duplicate sync, conflict, idempotency or parsing policy.

Evaluation:

🎯 10   🛡️ 9   🧠 7
Approx changes for robust MVP: `3000-7000` lines.

## Five-Pass Design Review

### Pass 1 - Product And Onboarding

Goal: make first use simple for technical Obsidian users without waiting for
Community Plugin review.

First user flow:

```bash
memo-stack up
memo-stack-obsidian connect --vault ~/Notes --space default --memory_scope default
memo-stack-obsidian preview --vault ~/Notes --space default --memory_scope default
memo-stack-obsidian sync --vault ~/Notes --space default --memory_scope default --apply-import
memo-stack-obsidian watch --vault ~/Notes --space default --memory_scope default --apply-import
```

Later plugin flow:

```text
Install Memo Stack plugin -> connect local daemon or API -> choose memory scope -> start sync
```

MVP plugin flow:

```text
memo-stack-obsidian install-plugin --vault ~/Notes --enable --space default --memory_scope default
-> open Obsidian -> Connect this vault -> Preview sync -> Sync now
```

Plugin value:

- setup wizard;
- sync status;
- conflict review;
- `Sync now`;
- `Open in Memo Stack`;
- safe edit affordances.

Thin plugin boundary:

- the plugin can run `memo-stack-obsidian connect`, `preview` and `sync`;
- the plugin can call `/v1/health`;
- the plugin must not parse managed notes or implement merge policy;
- service token is passed to the CLI through environment variables, not command
  arguments.
- `install-plugin` copies the bundled plugin assets into
  `.obsidian/plugins/memo-stack`, can add the plugin id to
  `.obsidian/community-plugins.json`, and can prefill plugin settings.

Daemon value:

- testable sync engine;
- no Obsidian review delay;
- works with any folder sync layer;
- keeps domain rules in Python/application code.
- one-shot `sync` command for users who do not want a long-running watcher.

Onboarding invariant:

`connect` creates only guide notes and folder scaffolding. It must not export
facts, import inbox notes, create suggestions, or mutate backend memory. Users
run `preview` before any sync operation that can affect vault or backend state.

### Pass 2 - Domain And DDD

Connector bounded context:

```text
Obsidian Sync Context
  ManagedNote
  NoteIdentity
  SyncMode
  SyncState
  SyncConflict
  SyncChange
```

It is not part of `memo_stack_core`. It is an outer application over the public
Memo Stack API/SDK.

Canonical rule:

```text
Memo Stack Postgres remains source of truth.
Obsidian files are editable projections with optimistic write-back.
```

### Pass 3 - Clean Architecture And SOLID

Dependency direction:

```text
memo_stack_obsidian.domain
  stdlib only

memo_stack_obsidian.application
  domain + ports only

memo_stack_obsidian.ports
  Protocols over vault, state store and memory gateway

memo_stack_obsidian.adapters
  filesystem, sqlite, memo_stack_sdk

memo_stack_obsidian.cli
  composition root only
```

SRP:

- parser parses;
- renderer renders;
- vault adapter reads/writes files;
- memory gateway calls SDK;
- use cases coordinate one sync operation;
- state store persists sync cursors and hashes.

OCP:

- Obsidian plugin can be added as another adapter/UI;
- WebDAV/Headless Sync/LiveSync stay outside as file replication layers;
- another note format can be added without changing memory gateway.

ISP:

- `MemoryGatewayPort` exposes facts/suggestions only;
- `VaultPort` exposes markdown file operations only;
- `SyncStateStorePort` persists connector state only.

DIP:

- use cases depend on ports, not SDK, filesystem or sqlite.

### Pass 4 - Sync Semantics

Sync modes:

```text
direct    structured managed fact notes can update canonical facts
suggest   free-form notes create suggestions
readonly  generated digests/source previews never write back
conflict  connector could not safely apply a change
```

Inbox notes:

```text
Memo Stack/inbox/*.md
```

Inbox notes are free-form human input. They must not update canonical facts
directly. The daemon imports them as pending `MemorySuggestion` records and
stores a path/content hash in connector state so repeated watch loops do not
spam duplicate suggestions for unchanged notes.

Direct write is allowed only when:

- the note has a valid `memo_stack_id`;
- the note kind is `fact`;
- the note schema is supported;
- the managed text block parses cleanly;
- the backend fact version equals the note `memo_stack_version`;
- the connector-origin hash does not indicate its own last write;
- source refs can be attached.

Everything else becomes a dry-run report, conflict file, or suggestion depending
on mode.

Export write is allowed only when:

- the note does not exist yet; or
- the existing managed note parses cleanly and its managed text hash still matches
  the last exported hash.

Export must never overwrite unimported local edits. The daemon loop must run
inbound import before outbound export so user edits get a chance to become
canonical or conflict before fresh backend projections are written.

Conflict artifacts:

```text
Memo Stack/conflicts/import-<fact-id>.md
Memo Stack/conflicts/export-<fact-id>.md
```

The connector writes conflict artifacts for stale versions, invalid managed
notes, duplicate ids and export overwrite guards. These files are Obsidian-visible
review aids only; they are not imported back into canonical memory.

One-shot sync:

```text
import managed notes and inbox first
if import has conflicts, skip export
if direct note edits are pending dry-run, skip export and ask for --apply-import
otherwise export fresh backend projections
```

This keeps local Obsidian edits from being hidden by a fresh backend export and
gives users a practical command before running an always-on watcher.

### Pass 5 - Edge Cases And Verification

Must handle:

- first sync into non-empty vault;
- preview before first sync with no side effects;
- invalid or missing frontmatter;
- corrupted managed block markers;
- user edits generated metadata instead of text block;
- concurrent edit on two devices;
- stale `memo_stack_version`;
- deleted generated note;
- renamed generated note;
- duplicate `memo_stack_id` across files;
- Obsidian Sync / LiveSync conflict merge;
- daemon crash between API update and file rewrite;
- backend unavailable;
- Qdrant/Graphiti lag after canonical update;
- plugin/watcher loop on connector-origin writes;
- secrets in Obsidian notes;
- prompt injection text in notes;
- huge notes;
- path traversal and unsafe file names;
- schema migration from v1 to v2 note format.

Required tests:

- note render/parse roundtrip;
- invalid note parse diagnostics;
- preview has no vault/backend side effects;
- CLI smoke for `connect -> preview -> export -> import dry-run`;
- CLI smoke for one-shot `sync` dry-run guard and `sync --apply-import`;
- live HTTP smoke for server -> SDK -> connector CLI -> vault files;
- Obsidian runtime E2E via `wdio-obsidian-service` for command registration and
  connector delegation;
- export writes deterministic paths and hashes;
- import dry-run reports direct updates without side effects;
- direct import calls `update_fact` with `expected_version`;
- stale version becomes conflict;
- connector-origin hash suppresses loops;
- state store survives restart;
- CLI smoke with fake gateway or temp vault.

## MVP Cut

Allowed in MVP:

- vault connect/setup guide notes;
- side-effect-free sync preview;
- one-shot import-then-export sync;
- desktop Obsidian plugin shell over the local connector CLI;
- fact export to `Memo Stack/generated/facts/*.md`;
- inbox import from `Memo Stack/inbox/*.md` to pending suggestions;
- managed text block parsing;
- direct update dry-run and apply;
- Obsidian-visible conflict artifacts;
- sqlite sync state;
- polling watcher;
- CLI composition root.

Not in MVP:

- published Obsidian community plugin release;
- automatic destructive deletes;
- relation editing;
- full document round-trip;
- mobile support;
- background OS service installer;
- multi-user SaaS auth.

## UX Auto-Connect Research Plan

Status: product hardening plan after the first connector/plugin smoke.

Date: 2026-06-07.

### Research Snapshot

Current Obsidian constraints:

- A vault is a normal local folder with Markdown files and a config folder. This
  makes direct filesystem sync a good integration boundary.
- Obsidian refreshes vault content after external file changes, so connector
  writes can appear without a plugin-owned parser.
- Community plugin distribution requires publishing plugin assets through a
  GitHub release and passing Obsidian community directory review.
- A plugin that uses Node.js or Electron APIs must be desktop-only.
- Plugin settings should use `loadData` and `saveData`.
- Plugins should avoid hardcoded `.obsidian` config paths and use
  `Vault.configDir` where config access is needed.
- Obsidian URI is useful for opening or creating notes, but it focuses Obsidian,
  so it is not a good background sync mechanism.

### Product Goal

Target user flow:

```text
Install Memo Stack once
Open Obsidian
Enable Memo Stack plugin
Click Connect
Done
```

Target agent flow:

```text
User: connect this vault to Memo Stack
Agent calls memory_obsidian_status
Agent calls memory_obsidian_setup in dry-run mode
Agent shows planned folder/settings writes
User approves
Agent calls memory_obsidian_setup apply=true
Agent calls memory_obsidian_preview
```

No console commands should be required for the happy path after the package and
plugin are installed.

### Top 3 UX Architecture Options

1. Hybrid plugin-first plus MCP setup tools - Recommended

   🎯 9   🛡️ 8.5   🧠 6
   Approx changes: `900-1600` lines.

   Shape:

   - Obsidian plugin owns human UX: connect wizard, status, preview, sync now,
     open conflicts, choose space/memory scope/root folder.
   - MCP owns agent UX: `memory_obsidian_status`, `memory_obsidian_setup`,
     `memory_obsidian_preview`, `memory_obsidian_sync`.
   - Sync remains in `memo_stack_obsidian` use cases. Plugin and MCP call the
     same application layer, not separate merge code.
   - No always-on process by default. Commands run one-shot and exit.
   - Optional watcher is explicit: user toggles "watch this vault" or runs a
     daemon command.

   Why this is best:

   - It removes console steps for normal users.
   - It lets agents help without shell access.
   - It avoids surprise background processes.
   - It keeps conflict/idempotency policy in one tested connector layer.

2. MCP-first setup, plugin as optional viewer

   🎯 7.5   🛡️ 8   🧠 5
   Approx changes: `650-1100` lines.

   Shape:

   - Agents can fully connect and sync a vault through MCP.
   - Plugin is only a thin "status and sync now" button later.
   - Good for Codex/Cursor users, weaker for normal Obsidian users.

   Problem:

   - Users still need an agent configured first.
   - Non-agent Obsidian users do not get the simple one-click UX.

3. Full local desktop daemon with auto-discovery

   🎯 6.5   🛡️ 6   🧠 9
   Approx changes: `2500-5000` lines.

   Shape:

   - Background service discovers vaults, syncs continuously and exposes local
     control API.
   - Plugin and MCP talk to daemon.

   Problem:

   - More installer/permissions/support burden.
   - Higher chance of "why is this process running" user distrust.
   - Harder to make cross-platform and to avoid focus/background surprises.

### Recommended V2 Flow

#### First Run From Obsidian

1. User installs/enables Memo Stack plugin.
2. Plugin loads settings with defaults:
   - API URL: `http://127.0.0.1:7788`
   - space: `default`
   - memory scope: `default`
   - root folder: `Memo Stack`
   - sync mode: preview-first
3. Plugin runs a health check.
4. If backend is unavailable:
   - show "Memo Stack is not running";
   - offer "Start local stack" only if `memo-stack` CLI is available;
   - never auto-start Docker/server on plugin load.
5. User clicks "Connect".
6. Plugin runs connector setup dry-run.
7. User sees exact folders/settings that will be created.
8. User clicks "Apply".
9. Plugin writes setup files and opens `Memo Stack/README.md`.
10. Plugin runs `preview` and shows:
    - facts to export;
    - inbox notes to suggest;
    - conflicts;
    - backend health.

#### First Run From Agent MCP

1. Agent calls `memory_obsidian_status`.
2. If no vault path is configured, agent asks user for a vault folder.
3. Agent calls `memory_obsidian_setup(apply=false)`.
4. Agent reports exact planned writes.
5. After approval, agent calls `memory_obsidian_setup(apply=true)`.
6. Agent calls `memory_obsidian_preview`.

MCP setup tools must be disabled unless:

```text
MEMORY_MCP_OBSIDIAN_ENABLED=true
```

This prevents accidental filesystem writes in generic agent sessions.

### Folder Model V2

Current MVP layout:

```text
Memo Stack/
  generated/facts/*.md
  inbox/*.md
  conflicts/*.md
```

Recommended V2 layout:

```text
<root folder>/
  README.md
  spaces/
    <space slug>/
      memory scopes/
        <memory scope ref>/
          generated/
            facts/*.md
          inbox/*.md
          conflicts/*.md
```

Example:

```text
Memo Stack/
  spaces/
    memo-stack/
      memory scopes/
        belief/
          generated/facts/fact_123.md
          inbox/project-ideas.md
          conflicts/import-fact_123.md
```

Why:

- Users can visually separate projects and memory scopes.
- Multiple projects can live in one Obsidian vault without collisions.
- The same vault can hold personal memory, project memory and team memory.
- Backward compatibility can keep reading the current MVP path.

Path rules:

- `root_folder` must be relative to vault root.
- `space_slug` and `memory_scope_external_ref` must be slugified for paths.
- Original values stay in frontmatter metadata.
- Unsafe path segments, `..`, absolute paths and empty slugs are rejected.
- Connector writes only under the configured root folder.

### Knowledge Control Model

User controls where knowledge goes through three settings:

```text
vault path      - which Obsidian vault
root folder     - where inside the vault, default Memo Stack
space/memory scope   - which project and person/context namespace
```

Recommended UI labels:

```text
Vault: current vault
Folder: Memo Stack
Project: default
Memory Scope: default
```

Avoid exposing "space/memory scope" as the first words in UX. Keep them as advanced
or API names.

### MCP Tool Surface

Add four read/write scoped tools:

```text
memory_obsidian_status
memory_obsidian_setup
memory_obsidian_preview
memory_obsidian_sync
```

`memory_obsidian_status`:

- read-only;
- checks env config, backend health, vault path, plugin files, root folder and
  connector state;
- safe to call automatically.

`memory_obsidian_setup`:

- dry-run by default;
- creates folder scaffold only when `apply=true`;
- can install/update plugin settings only when explicitly requested;
- does not import or export facts.

`memory_obsidian_preview`:

- read-only for backend and vault;
- returns planned import/export/suggestion/conflict summary.

`memory_obsidian_sync`:

- mutating;
- disabled unless `MEMORY_MCP_OBSIDIAN_SYNC_ENABLED=true`;
- default mode is dry-run unless `apply_import=true`;
- skips export on import conflict.

MCP tools must not spawn arbitrary shell commands. They should call
`memo_stack_obsidian` application use cases directly or a narrow adapter with a
fixed command allowlist.

### Backend Start Policy

Do not start background services automatically on plugin load or MCP status.

Allowed start paths:

- user clicks "Start local stack" in plugin;
- user asks agent to start Memo Stack and MCP calls a future explicit local-stack
  tool;
- user runs `memo-stack up`.

Guardrails:

- only start when API URL is localhost;
- show exact command or planned action before running;
- never start full provider stack by default;
- do not start watcher automatically;
- record last start attempt and cooldown repeated failures.

### Plugin UX Upgrades

Add a connection panel:

```text
Status: connected / backend offline / conflicts / setup needed
Project: <space>
Memory Scope: <memory scope>
Folder: <root folder>
Buttons: Connect, Preview, Sync now, Open conflicts
```

Add command palette commands:

```text
Connect vault
Preview sync
Sync now
Open conflicts
Run doctor
Start local stack
```

Add protocol handler:

```text
obsidian://memo-stack?action=connect
obsidian://memo-stack?action=preview
obsidian://memo-stack?action=open-conflicts
```

Use protocol links only for deep-linking into Obsidian. Do not use them for
background automation because they can focus the app.

### Edge Cases To Cover

Onboarding:

- plugin enabled before Memo Stack backend exists;
- CLI package missing;
- backend offline;
- wrong token;
- wrong API URL;
- vault path cannot be resolved;
- custom Obsidian config folder;
- user has restricted mode/community plugins disabled.

Path/layout:

- root folder already exists with user files;
- root folder renamed;
- old MVP layout and new V2 layout both present;
- unsafe root folder path;
- space/memory scope with spaces, unicode, slashes or very long names;
- two memory scopes with same slugified path.

Sync:

- preview has no side effects;
- dry-run setup has no side effects;
- local generated note deleted;
- generated note renamed;
- duplicate `memo_stack_id`;
- stale backend version;
- corrupted frontmatter or managed block;
- Obsidian Sync creates conflict copies;
- huge inbox note;
- empty inbox note;
- repeated sync does not duplicate suggestions;
- backend update succeeds but note rewrite fails;
- backend unavailable mid-sync.

Process control:

- plugin health check does not start server;
- status tool does not start server;
- failed start does not loop;
- watcher cannot be enabled accidentally;
- UI E2E is opt-in only because it opens Obsidian.

Security:

- token never passed in command args;
- token not written into conflict files;
- source note text is treated as evidence, not instruction;
- path traversal rejected;
- MCP Obsidian tools off by default;
- mutating MCP sync requires explicit env enablement.

### Implementation Phases

1. Layout and config V2

   🎯 9   🛡️ 8.5   🧠 5
   Approx changes: `350-600` lines.

   - Add connector config model: `root_folder`, `layout_version`,
     `space_folder_mode`.
   - Add path builder for V1/V2 compatibility.
   - Add migration-safe tests.

2. Plugin connection panel and setup wizard

   🎯 8.5   🛡️ 8   🧠 6
   Approx changes: `300-650` lines.

   - Add doctor command to plugin. Done.
   - Add status/control panel. Done.
   - Add scoped README/Inbox/Conflicts open actions. Done.
   - Add panel setup checklist and busy-state disabled buttons. Done.
   - Add explicit `memo-stack init` local config action. Done.
   - Add setup dry-run/apply flow. Done via `memory_obsidian_prepare`, plugin
     Prepare action and real Obsidian prepare E2E.
   - Keep real Obsidian E2E opt-in.

3. MCP Obsidian tools

   🎯 8.5   🛡️ 8   🧠 6.5
   Approx changes: `450-900` lines.

   - Add env-gated Obsidian MCP settings.
   - Add status/setup/preview/sync tool wrappers.
   - Add fake vault unit tests and live non-UI smoke.

4. Optional local stack start

   🎯 7   🛡️ 7   🧠 7
   Approx changes: `250-500` lines.

   - Plugin can run `memo-stack status`, `memo-stack doctor` and explicit
     `memo-stack up --lite`. Done.
   - Never auto-start on load. Done.
   - Add cooldown and clear user notice. Done.

### Completion Gates

- `memo-stack-obsidian doctor --json` proves a connected vault.
- MCP `memory_obsidian_status` works with temp vault and disabled-gate cases.
- `scripts/obsidian_mcp_smoke.py` proves real stdio MCP Obsidian setup,
  plugin install/enable and sync gate behavior without opening Obsidian.
- `scripts/obsidian_mcp_smoke.py` also proves custom Obsidian config folder
  support through `MEMORY_MCP_OBSIDIAN_CONFIG_DIR`.
- Plugin can connect a fresh temp vault in Obsidian runtime E2E when opt-in.
- Non-UI live smoke covers V2 folder layout, edit import, deleted note recreate,
  stale conflict, inbox dedupe and plugin settings.
- Unit tests cover path safety, slug collisions, dry-run side effects and disabled
  MCP mutating tools.
