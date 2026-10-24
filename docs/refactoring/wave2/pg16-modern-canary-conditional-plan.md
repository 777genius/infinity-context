# PG16 managed-canary harness migration — conditional plan v2

## Status and scope

**Blocked before implementation by unavailable authentic runtime assets.** This plan describes
the bounded test-harness migration required by
`tests/e2e/test_managed_production_live_app_e2e.py::test_verified_managed_production_runs_through_live_subprocess_and_postgres16`.
It does not claim that test passed. No source change or extra empty PR is proposed while the
asset prerequisite is unavailable. Root and the architecture reviewer must complete two plan
review rounds before any eventual implementation.

This gate is distinct from the custom Mem0 process-recovery E2E, although both require the same
authentic pinned external runtime deployment bundle.

## Read-only diagnosis and provenance

The exact frozen source is `6fce8875ec8e0c2e13a8560cb312557bd67261ef`; the canary test, public CLI,
managed-v5 filesystem validator and public composition have byte-identical Git blobs at the
pre-refactor `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` baseline. This is pre-existing test drift.
Full blob IDs and actual trace evidence are recorded in
`evidence/wave2/pg16-managed-live-stale-cli-diagnosis.json`.

Three genuine runs established separate facts:

1. The fresh task-owned PG16 cluster initially lacked the repository's administrative strict-v4
   capability-role prerequisite. Applying unchanged `provisioning/strict_v4_roles.sql` created
   the three safe NOLOGIN roles.
2. The test's plain `CREATE DATABASE` helper bypasses the standard E2E database provisioning
   helper. Applying the same unchanged administrative SQL to the owned PG16 template, and
   inspecting a fresh disposable clone, proved exact direct schema USAGE without CREATE.
   The server and projection worker then started successfully under unchanged guards.
3. The real CLI subprocess exited 2 before any bridge/provider/Mem0 call. Its parser requires
   `--max-extraction-tokens` and `--managed-v5-config-json`; the old test supplies neither.
   Its loopback Mem0 bridge implements legacy `/memories` and `/search`, while the public CLI
   intentionally runs the authenticated durable managed-v5 path. Adding two flags alone is
   insufficient. The private `_run_managed_live_legacy` function is not an acceptable route.

Retained evidence: `e2e-final-pg16-live-canary.*`, `e2e-final-pg16-provisioned.*`,
`e2e-final-pg16-template-provisioned.*`, `postgres16-capability-provisioning.json`, and
`postgres16-template-provisioning.json`, all under `evidence/wave2/`.

## Non-negotiable authentic prerequisites

- Subscription-runtime source commit `e904ec95fda4b04c333e5a7613c7729bf7abb125` and its genuine
  deployed runtime/dist files, not a different release or an unverified local rebuild.
- Exact deployed `artifact-manifest.json` SHA-256
  `789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850` and `release.json` SHA-256
  `8854ae10ea450fc615af251cdd5eef8812f928b458f710bb84b0cdbdde92fceb`.
  A deterministic rebuild is acceptable only if genuine pinned source/tools produce both
  exact original hashes and all referenced artifact bytes pass the existing verifier.
- Reviewed Node `v24.16.0`, executable SHA-256
  `b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
- Exact reviewed Phase-C Python tree
  `911b85ca131cea7f8150456ba122730ec768ddc2c2d6869453071aa5029cef18`, the frozen adapter runtime
  pin and extraction-contract bytes, genuine runtime-authority fields and all source/path/
  mode/owner constraints already required by production composition.
- All immutable paths and origins must satisfy the existing production checks. Only
  task-owned listeners may be used; an occupied required origin is a blocker, not permission
  to target an existing service. Keep the official complete LongMemEval bytes and their
  pinned full digest, selected case `852ce960`, and an actual PostgreSQL 16 server.

GitHub source/release/CI searches and personal-context retrieval did not recover the exact
deployment bundle. See `evidence/wave2/pinned-runtime-artifact-search.json`. No manifest,
runtime identity, receipt or reviewed hash may be invented to make preflight accept.

## Mandatory go/no-go gates before any future source edit

**Gate A — authentic public trust inputs.** Record the verified exact bundle and every referenced
artifact byte, source revision, Node executable, Phase-C origin/tree, canonical path, owner and
file mode. Validate with the existing production preflight, not a newly invented verifier.
Required pinned origins must be unused before the test creates its own listeners. Preserve a
requested/opted-in failed preflight as a failure; do not add a broad skip for missing assets.
No public CLI/provider dispatch may occur before this gate and the owned PG16 database's exact
administrative provisioning have succeeded.

**Gate B — concrete supported harness design.** After authentic assets arrive, identify and
document the exact already-supported provider-free production composition seam, v5 protocol,
argv, strict config schema and real identity/receipt bindings. Commit an assertion/contract
inventory mapping **every existing semantic oracle** to its retained v5 equivalent, including
the version check, corpus/case, CLI process, token limits, readiness/answer/judge order,
extraction operation counts, scoped read/search results, no secret leakage, physical absence,
terminal deletion and independent canonical registry receipt. Derive all extraction/provider
call expectations and budget bounds from the sealed reviewed contract **before execution**;
never derive acceptance expectations from observed output. Re-review unresolved protocol,
assertion or budget mappings with both critics before editing. Approval of this conditional
plan is not authorization for an unknown harness implementation.

**Gate C — owned execution and cleanup.** Check the actual server reports version 16 before
provisioning the test's fresh task-owned database. All config, trust-input and unused-origin
checks must precede dispatch, and local providers must use supported real production bindings
with egress/paid credentials prevented. Failed or cancelled runs clean up only their own
processes, listeners, databases and temporary authority state; they do not change or remove
the authentic bundle, another namespace, shared role configuration or user credentials.

## Bounded eventual implementation

Only after the prerequisites are supplied and verified:

1. Keep the original test node, actual CLI entrypoint/subprocess, PG16 version check, official
   dataset, explicit authorization flags, canary/non-publishable scope, selected-case count,
   independently observed terminal cleanup and canonical PostgreSQL registry receipt checks.
2. Update the test's argv with an explicit bounded extraction-token ceiling and a strict
   managed-v5 JSON config built from the actual verified assets. Keep real production config
   loading, identity validation, typed composition and sealed authority issuance intact.
3. Use the existing `PostgresTestDatabase` administrative provisioning path for the test's
   own fresh PG16 database after checking the actual server version. Do not weaken the
   role, schema, migration or version guards or rely on the temporary template repair as an
   undisclosed test behavior.
4. Replace the legacy test-only Mem0 lifecycle plumbing with the supported reviewed v5
   composition and its durable authenticated protocol. Prefer the genuine frozen adapter
   with its existing supported provider-free composition seams. Keep answer/judge/extraction
   provider responses local and controlled, without paid calls or model downloads. Do not
   forge runtime/adapter identity attestations or route the public CLI through private legacy
   code. If no supported provider-free composition can preserve real identity verification,
   stop and re-plan rather than add a production escape hatch.
5. Retain the original readiness/answer/judge and cleanup meanings. Derive any new extraction
   operation/call counts and budget bounds from the real reviewed v5 contract; do not suppress
   them or retain obsolete legacy endpoint assertions. Prove no secret leakage, no foreign
   namespace access, no unexpected provider attempts, terminal deletion and durable cleanup
   evidence. The genuine adapter's independent 40-test proof remains separate and is not
   substituted for the canary.
6. Preserve the exact existing node identity and all frozen repository size ceilings. The
   existing file is 622 lines at the frozen source and must not grow; extract focused support
   responsibilities as needed. Any legacy oversized file may shrink but may not exceed its
   frozen ceiling. Bound code to the existing test plus at most two focused E2E support modules for config/
   service lifecycle and the local protocol harness, each below 1,000 lines. Production
   packages, manifests, pins, fixtures and security checks remain unchanged. Re-review the
   plan if that bound or a genuine identity prerequisite cannot be met.

## Validation after prerequisites

- First validate strict config parsing and real immutable asset preflight, including rejection
  of a tampered pin, without opening providers. Prove actual PG16 and exact administrative
  schema/role prerequisites in a fresh owned database.
- Run the original selected E2E node with standard fd capture, actual PG16, full official
  input and fresh private state. Preserve exact source HEAD/tree/origins, JUnit, command,
  process logs and the actual cleanup/registry/identity evidence.
- Obtain two independent code reviews and retain all original semantic assertions. No skip
  weakening, fake artifacts, synthetic replacement dataset, private legacy route, monkeypatch
  of production composition, or manufactured green result is permitted.

## Review state

Both independent round-1 critics accepted the blocked direction and required explicit authentic
asset verification, a concrete reviewed v5 seam/config/argv/assertion inventory before edits,
pre-execution sealed expectations/budgets, strict ceilings and owned-only cleanup. Conditional
v2 incorporates those requirements and is submitted for round-2 review. This review covers the
conditional go/no-go controls; no implementation or acceptance is authorized without authentic
assets and a concrete reviewed harness design. All unaffected gates continue.

## Final conditional review record

Both independent critics completed both rounds. Architecture approved version 2; the root coordinator independently read and approved its complete Gate A/B/C controls in round 2. No conditional-control blocker remains. The 622-line non-growth requirement is this bounded plan's chosen scope, not a newly invented global legacy ceiling. This approves only the conditional go/no-go plan: authentic runtime assets and a concrete reviewed supported V5 seam, config, argv and every-oracle mapping remain prerequisites. No test-harness implementation or passing outcome is claimed.
