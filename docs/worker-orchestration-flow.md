# Worker orchestration flow

This flow is for long-running Infinity Context memory-quality work on the shared DigitalOcean host.

## Roles

- Upper-level operator: monitors only Infinity Context jobs, handles recovery, reviews completed work, integrates clean commits, and pushes safe changes to `main`.
- Host orchestrator worker: runs as a Codex worker on the host, decomposes the active goal into focused child jobs, tracks capacity, and keeps work moving.
- Child workers: each owns one narrow lane in an isolated worktree and produces a reviewed, tested commit or an explicit blocker.

## Parallelism model

- Prefer 3-5 active Infinity workers when CPU, memory, account capacity, and other host workloads allow it.
- Worker count is not limited to account count. Accounts are capacity slots, not one-to-one worker identities.
- Each child worker must use a separate workspace under `/var/data/workspaces`.
- Enforce one writer per workspace. Never recover or continue a job into a workspace with an active writer.
- Keep lanes independent: retrieval ranking, temporal reasoning, entity/person aliases, evidence bundling, query decomposition, benchmark preflight, and focused diagnostics should not edit the same files unless explicitly sequenced.

## Safety gates

Every cycle starts read-only:

1. `subscription-runtime-codex-goal overview --registry-root /var/data/worker-jobs/registry --job-prefix infinity-context`
2. `subscription-runtime-codex-goal brief <jobId> --registry-root /var/data/worker-jobs/registry`
3. tmux/process status
4. git status and recent log for relevant Infinity workspaces
5. safe artifact listings only

Continue or recover only when `safeToContinue=true`, or when diagnostics prove a known clean infra/runtime guard with no active writer and a clean or fully understood workspace.

Never print secrets, auth payloads, API keys, token contents, raw provider payloads, or private auth files.

## Child worker contract

Each task prompt must define:

- one small ownership boundary
- expected files or subsystem
- behavior-preserving constraints
- required targeted tests or lint/type checks
- no full/long LoCoMo unless explicitly authorized
- no push from child worker
- self-review before handoff
- clean commit or explicit blocker summary

Workers should prefer focused tests, preflight checks, compile/lint for touched files, and short `locomo-fast` style checks.

## Integration flow

1. Inspect the child result, changed files, commit, and test output.
2. Reject dirty, untested, broad, or unrelated changes.
3. Use a fresh integration worktree from `origin/main`.
4. Cherry-pick or merge only reviewed commits.
5. Run targeted verification for the touched area.
6. Push safe integrated commits to `main` periodically so GitHub reflects current progress.
7. Mark the worker reviewed with a short marker or result note.

## Recovery rules

- Heartbeat-only with no log, no diff, idle process, and stale runtime events can be stopped after read-only inspection.
- Stale locks from a reboot may be quarantined only after proving the owner process is gone and no active writer exists.
- Dirty workspaces owned by running workers are not touched.
- Failed workers are forensic references only unless their changes are revalidated from current `main`.

## Quality goal

The objective is real memory-quality improvement, not benchmark overfitting. Changes should improve retrieval evidence, temporal grounding, entity/person matching, list/count support, and answer support in ways that generalize beyond LoCoMo.
