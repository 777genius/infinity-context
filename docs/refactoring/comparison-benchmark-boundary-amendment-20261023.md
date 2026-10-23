# Amendment: evidence policies belong in the benchmark bounded context

Status: both independent critics approved amendment round 2 after round-one fixes; awaiting exact plan publication and coordinator production release. Preserve the existing uncommitted exact-body extraction as a checkpoint. Do not relocate or expand production scope until the same two critics complete two independent review/fix rounds and the coordinator releases this amendment.

## Discovered architectural requirement

The original seven-leaf split passes all 251 frozen invocation replays and all 115 original class/function AST comparisons. The combined final gate reports 900 passing tests and one failure: `test_benchmark_debt_cannot_grow_inside_product_packages` counts 490 server benchmark files against the accepted maximum 483. ADR-0008-benchmark-runtime-bounded-contexts requires a genuine benchmark package and non-growing product debt. The initial plan missed this gate. No ceiling increase, marker renaming, import hook, test exclusion or alternate classification is permitted.

Pinned original planner SHA256: `f2cd20e94fba4427d7646cccbd9631445b8a06b050b4b68ac37da128da027f50`. The frozen scratch corpus has 251 unique invocations, SHA256 `507e6882e8d7d148d98b9bf924aa0386df1334fba3239528b344212b967c4006`. The already committed 20 permanent complete-output goldens, signature/DTO metadata and old-module pickles remain unchanged. Before supporting source moves, 61 source-identity/partial/sensitive-text function signatures and four actual original-module function pickle references were also captured from unchanged source; add this small compatibility fixture without regenerating existing expectations.

## Options

**A — recommended: coherent benchmark package and provenance authority.** Place the proven seven policy leaves in a standalone `infinity_context_benchmarks` package. Move the unchanged 1,655-line source-identity policy into three cohesive package modules and move the unchanged 107-line partial-role helper there as well. Keep original server modules as explicit compatibility facades. Expose the existing 39-line sensitive-text policy as a tiny public core safety module, retaining the old application module exports. The benchmark package imports that public core contract only; no server, adapters or core-application internals. This moves one coherent evidence/provenance boundary, removes another oversized legacy source exception and provides independent wheel installation.

**B — narrower migration.** Move only the three source-identity entrypoints consumed by planner leaves and their complete dependency closure (70 declarations / 1,175 body LOC) into the benchmark package, retaining remaining output/audit policy in the server with explicit imported helper aliases. This moves fewer lines but splits one provenance authority across package ownership and complicates future public contracts. It still requires packaging, public core safety and independent wheel proof. Prefer A because the full policy is pure and its internal dependency graph has clear seams.

Request independent critics to judge A versus B and the public safety boundary. Scope below is A; B requires updating this amendment before approval.

## Exact new/changed production paths under A

New standalone project `packages/infinity_context_benchmarks/pyproject.toml`: setuptools build metadata, project name `infinity-context-benchmarks`, version `0.1.0`, Python >=3.11, explicit internal dependency `infinity-context-core==0.1.0`, no new third-party runtime dependency. Package path `packages/infinity_context_benchmarks/infinity_context_benchmarks/`.

| Path relative to benchmark package | Responsibility | Target LOC |
| --- | --- | ---: |
| `__init__.py` | Package identity/documented benchmark evidence surface; no eager product imports | <30 |
| `evidence_bundle/__init__.py` | Narrow stable benchmark-owned contract exports | <35 |
| `evidence_bundle/models.py` | Existing candidate/item contracts, canonical benchmark defining-module identity; original server aliases and old-pickle loading preserved | 192 |
| `evidence_bundle/source_policy.py` | Existing source/locality policy | 293 |
| `evidence_bundle/candidate_policy.py` | Existing candidate role/support policy | 766 |
| `evidence_bundle/role_support.py` | Existing selection-level role/bridge policy | 428 |
| `evidence_bundle/ordering.py` | Existing ordering tuples | 276 |
| `evidence_bundle/role_repair.py` | Existing bounded repair | 212 |
| `evidence_bundle/quality.py` | Existing full quality projection | 941 |
| `evidence_bundle/partial_support.py` | Entire existing partial-role helper, unchanged | 107-130 |
| `source_identity_safety.py` | 16 functions /194 body LOC: safe source/turn/item/label validation, private-reference filtering, normalized primitive refs and the associated safety constants; imports only public core safety + stdlib | 300-400 |
| `source_identity_parsing.py` | 23 functions /653 body LOC: structured turn/session/dialogue parsing, textual session/turn parsing, mismatch/count/identity primitive helpers; associated parsing regexes; depends only on safety | 800-950 |
| `source_identity.py` | 18 functions /496 body LOC: recursive ref-value normalization, source/dedupe identity projections, ordered output sanitization and audit gaps; depends on safety + parsing | 600-750 |

The existing seven uncommitted new files under `infinity_context_server` are not retained. This is a real namespace/distribution move, with standalone dependency metadata and zero imports back into the server, not a renamed product directory to bypass the gate.

Existing server files:

- `memory_comparison_bundle_planner.py` retains original planner/plan class definitions and all original helper/constant imports, now explicitly importing the benchmark package; target <=900.
- `memory_comparison_source_identity.py` becomes a <=250-line explicit compatibility facade re-exporting EVERY original public/private function and constant from the three cohesive source modules. Preserve old import names and current call signatures; no duplicate implementations.
- `memory_comparison_bundle_partial_support.py` becomes a <=35-line explicit compatibility facade, preserving its function/helper/constants. Source-window policy remains unchanged in server and used by the unchanged coordinator.

Public core safety:

- New `packages/infinity_context_core/infinity_context_core/sensitive_text.py` owns the existing 39 lines, unchanged regexes/functions. This is an explicit public deterministic safety contract, not benchmark logic.
- Existing `application/sensitive_text.py` becomes a small explicit compatibility facade retaining both functions, both regex constants and the old imported `re` name. No second regex authority and no core dependency on benchmark/contracts/server.
- Add old/public import identity assertions and run all existing `tests/unit/test_sensitive_text.py` plus current source-identity/diagnostic-safety coverage. Preserve signatures and legacy function pickle lookup through original exports; no generalized sanitization interface.

## Deliberate DTO metadata decision after amendment round 1

The coordinator selected canonical benchmark ownership for `EvidenceBundleCandidate` and `PlannedEvidenceItem`: their `__module__` becomes `infinity_context_benchmarks.evidence_bundle.models`. Keeping the old server module as defining identity makes standard standalone pickle and forward-reference type hints fail when server is absent. No import-order mutation, hidden server dependency, shim or duplicate class is allowed.

Original server exports MUST alias the exact same benchmark classes. ORIGINAL baseline pickle bytes already committed before production movement MUST deserialize through the original server facade into those classes. Constructors, frozen fields/defaults/equality/repr, callable signatures, item/diagnostic JSON and all 251 replay outputs remain unchanged. New benchmark-only pickle round-trips and `typing.get_type_hints` for both DTOs must work with server absent. `EvidenceBundlePlan` and `EvidenceBundlePlanner` retain their old server defining modules.

Among the frozen DTO/class contracts, this intentionally changes only the two moved DTOs' defining-module metadata. Relocated source-identity/sensitive-text functions naturally acquire new defining modules too; their old import names, signatures and original function-pickle lookups remain available through explicit aliases, without artificial module mutation. Keep contract.json unchanged as historical evidence; the contract test separately asserts the explicit new canonical module for those two names and the historical old module value, while comparing every other baseline field/default/signature without normalization. Do not edit any expected scoring/item/diagnostic output. The PR must disclose this narrow metadata impact and preserved old-pickle readability.

## Import direction

`core public sensitive_text -> stdlib`.

`benchmark source_identity_safety -> core public sensitive_text + stdlib`.

`benchmark source_identity_parsing -> source_identity_safety + stdlib`.

`benchmark source_identity -> source_identity_safety + source_identity_parsing + stdlib`.

`benchmark evidence models/source_policy -> benchmark source identity`; the already approved seven-leaf graph is unchanged, and role_support consumes benchmark partial_support.

`server old planner/source_identity/partial_support facades -> benchmark public modules`. No benchmark import of server/adapters or core.application. No product core -> benchmark import. No dynamic forwarding, dependency bag, callback injection, duplicated source policy or new framework.

All original source-identity and partial-support declaration ASTs must also match exactly and uniquely across their new homes; preserve function conditions, arithmetic, source order, regex flags, fallbacks and exception behavior. Original policy composition and all 251 baseline outputs remain the decisive behavioral check.

## Packaging/discovery and execution paths

- Root `pyproject.toml`: add `packages/infinity_context_benchmarks` to setuptools package-discovery roots and pytest pythonpath. No root third-party dependency changes.
- `packages/infinity_context_server/pyproject.toml`: declare `infinity-context-benchmarks==0.1.0` for the now-explicit import. This does not change root bundled distribution dependency resolution.
- `Makefile`: append the new source package path to INFINITY_CONTEXT_PYTHONPATH so ordinary commands import this checkout.
- `Dockerfile`: existing `COPY packages ./packages` and root `pip install .` already include all package sources; verify discovery through built wheel instead of an unnecessary image edit. Inspect any explicit build manifest path inventory and include the new package if required.
- Build wheels without network/dependency resolution for core, the new benchmark distribution and the root bundled distribution; install into an isolated temporary target/environment. From a working directory outside the checkout with PYTHONPATH cleared, import the benchmark public contracts and source identity from the standalone package, then import original server facades from the root wheel. Assert import identity, run one frozen nonempty planner case and source-sensitive-label rejection there. This catches missing package discovery and unintended checkout fallback.
- Do not change unrelated CI or lock third-party packages merely to add an internal source package. If package metadata needs a lock update, record only the necessary internal metadata change and obtain review; no broad dependency refresh.

### Exact source/runtime inventory closure

Only source-path entries and directly associated assertions change in these existing path inventories; no launcher behavior, provider configuration or test isolation assertions change:

- `scripts/install.sh` generated launcher; `docker-compose.yml` source PYTHONPATH; the nine generated `plugins/infinity-context-agent-plugin*/bin/infinity-context-{mcp,mcp-doctor,plugin-hook}` wrappers (three plugin variants).
- `tests/e2e/infinity_context_server_harness.py`; all four explicit subprocess path lists in `tests/unit/test_memory_comparison_lightweight_imports.py`; `tests/unit/test_memory_comparison_latency_contracts.py`; `tests/unit/test_multimodal_live_provider_canary.py`.
- `benchmarks/mem0-oss-adapter-v5/pyproject.toml` and its `tests/test_package_import_boundary.py`, including the actual package-file-origin assertion.
- `scripts/mem0_v5_live_micro_canary.py`, `scripts/mem0_v5_live_project_one_unit.py`, `scripts/obsidian_connector_live_smoke.py`, and `scripts/obsidian_mcp_smoke.py`, only where they construct checkout package paths.
- `packages/infinity_context_obsidian_plugin/test/fixtures/real-infinity-context-obsidian.cjs` and the explicit pythonpath arrays in `test/specs/{full-stack-helpers.ts,full-stack-path-safety.e2e.ts,full-stack-churn.e2e.ts,full-stack-frontmatter.e2e.ts,plugin-install.e2e.ts,full-stack-import-toggle.e2e.ts,full-stack-race.e2e.ts,full-stack-plugin-lifecycle.e2e.ts,plugin-settings-recovery.e2e.ts,full-stack-prepare.e2e.ts,full-stack-settings-rotation.e2e.ts,full-stack-scope-bulk.e2e.ts,full-stack-batch.e2e.ts,full-stack-friendly-names.e2e.ts,full-stack-control-center.e2e.ts,full-stack-root-control.e2e.ts,full-stack-conflict-ux.e2e.ts}`. These start the real product server, whose router composition imports the compatibility source policy. No unrelated TypeScript behavior edits.
- `packages/infinity_context_server/infinity_context_server/build_identity.py`: add benchmark package to `_RUNTIME_PACKAGES`. This existing inventory controls source runtime hashing and installed runtime-root/RECORD/shadow-import checks; moved executed code must remain measured. The file is 295 lines, well below the cap. Add <=180-line `tests/unit/test_benchmark_build_identity.py`: changing a benchmark source changes source runtime digest; changing an installed benchmark module changes installed runtime digest; missing/out-of-root benchmark RECORD identity remains rejected. Keep existing identity checks intact.

`Dockerfile` already copies all packages; `scripts/build_manifest.py` already includes the entire packages tree, so neither needs a semantic change. Verify rather than duplicate their inventories. For any inventory above whose actual transitive import does not reach moved policy, record the reason and avoid its edit. New/repartitioned modules and existing non-legacy modules remain <=1,000 lines. The existing 1,649-line test_multimodal_live_provider_canary.py receives only its required source-path list update and must keep or lower its frozen legacy ceiling; no fixture rewrite or ceiling increase.

### Mandatory offline distribution proof

Add a <=350-line `scripts/smoke_benchmark_package_wheels.py` with the explicit build/install contexts below. Use the primary runtime Python (pip/setuptools/wheel available); the shared frozen pytest interpreter intentionally has none of these build tools. No resolver, downloads, editable installs or shared site packages in child smoke interpreters.

Executable command:

```bash
python scripts/smoke_benchmark_package_wheels.py --output /tmp/infinity-context-benchmark-wheel-smoke
```

The script first creates a clean staging copy of the necessary root metadata, packages and deployment-package sources under its temporary output, excluding .git, virtual environments, caches, node_modules and prior build/dist artifacts. Build that copy so setuptools build/egg-info output cannot contaminate checkout source-runtime identity hashing. It executes the equivalent of these exact commands from the staging copy, with absolute project/output paths:

```bash
python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir WHEELS \
  packages/infinity_context_core packages/infinity_context_benchmarks \
  packages/infinity_context_runtime_bridge packages/infinity_context_server .
python -m pip install --no-index --no-deps --target CORE_BENCH_TARGET \
  WHEELS/infinity_context_core-0.1.0-py3-none-any.whl \
  WHEELS/infinity_context_benchmarks-0.1.0-py3-none-any.whl
python -m pip install --no-index --no-deps --target SERVER_TARGET \
  WHEELS/infinity_context_core-0.1.0-py3-none-any.whl \
  WHEELS/infinity_context_benchmarks-0.1.0-py3-none-any.whl \
  WHEELS/infinity_context_runtime_bridge-0.1.0-py3-none-any.whl \
  WHEELS/infinity_context_server-0.1.0-py3-none-any.whl
python -m pip install --no-index --no-deps --target BUNDLE_TARGET \
  WHEELS/infinity_context-0.1.0-py3-none-any.whl
python -I -S SMOKE_SCRIPT CORE_BENCH_TARGET standalone
python -I -S SMOKE_SCRIPT SERVER_TARGET server
python -I -S SMOKE_SCRIPT BUNDLE_TARGET bundle
```

All child commands run from an external temporary cwd. `-I -S` excludes user/shared sites, .pth processing and cwd/PYTHONPATH; the smoke code adds exactly its isolated target to sys.path. Assert every imported owned module's __file__ lies inside that target and outside checkout. In standalone context explicitly assert server/adapters cannot be found, construct both DTOs, resolve both type hints, pickle-round-trip both, execute a nonempty candidate/quality projection and reject sensitive source labels. In server and bundle contexts assert exact old/new class alias identity, load unchanged original pickle fixtures, and run one complete frozen nonempty planner case. The server context must inspect installed Requires-Dist for benchmark and the benchmark Requires-Dist for core; runtime-bridge wheel supplies the existing internal server dependency. Facade smoke needs no third-party imports, so no undeclared shared runtime fallback is allowed.

Build core/server independent wheels using their actual default setuptools backend; if a required metadata correction is discovered, keep it limited to making these declared local projects build. Record all five wheel names/hashes and smoke import locations. Root bundled discovery alone cannot satisfy this gate.


### Bounded plugin authoring decision

Read all three plugin AGENTS.md and GENERATED.md before planning wrapper edits. Their managed guidance says edit only plugin/; listed managed outputs exclude bin wrappers, and the referenced plugin/README.md does not exist. The actual launcher.yaml points to shell wrappers; wrappers execute infinity_context_mcp entrypoints. Audit of MCP/CLI/Obsidian Python sources finds no imports from infinity_context_server (only Docker service-name strings). Thus these client launchers do not transitively load moved benchmark policy. Leave all nine plugin bin wrappers and all managed generated plugin files unchanged; no generator workflow or user exception is needed for a nonexistent dependency. Verify their relevant entrypoint imports with a guard rejecting server/benchmark imports, and document this closure rather than adding every package to unrelated clients.

## Architecture bookkeeping and tests

- Keep `SERVER_DEBT_MAX_FILES` <=483; old facades remain, new benchmark files live outside product package. Ratchet `SERVER_DEBT_MAX_LINES` DOWN to measured actual server benchmark debt after migration. Core benchmark counts/lines do not increase because the safety policy is product-owned and does not contain benchmark behavior.
- Retain all existing no-growth checks; strengthen the bounded-context architecture test to forbid benchmark imports from server/adapters/core.application and product core imports of benchmark. Include standalone package discovery under this check.
- Remove the now-repaired source_identity entry as well as planner from file_size_legacy_baseline; preserve other entries and all monotonic checks. Every new/changed code file remains <=1,000 lines.
- Update the approved bundle import-boundary test's physical roots/module names to the new package, keeping the same permitted DAG.
- Keep all permanent expected fixtures unchanged. Rerun the 251 frozen invocations and complete focused/composition/architecture suites from the original plan. Add sensitive-text tests and isolated wheel smoke. Record exact counts, actual source sizes, debt ceilings, package import locations and wheel artifact hashes.

## Review gate

- Amendment round 1 core critic: preferred A; blocking standalone DTO module/pickle/type-hint conflict and mandatory exact real server-wheel proof. Full review: plans/review-amendment-r1-server-by-core.md.
- Amendment round 1 lifecycle critic: preferred A; same DTO conflict, separate isolated install contexts and explicit runtime identity/path closure. Full review: plans/review-amendment-r1-server-by-lifecycle.md.
- Owner fixes after amendment round 1: coordinator selected explicit canonical benchmark module identity with old alias/old-pickle compatibility and unchanged baseline outputs. Added exact isolated three-context wheel commands, source/launcher/harness inventory and build_identity runtime measurement regression. No amended production edits.
- Amendment round 2 core critic: approved; plans/review-amendment-r2-server-by-core.md. Canonical DTO metadata and exact isolated packaging proof resolve R1. Bounded notes: retain existing oversized path-test ceiling and reconcile plugin authoring guidance.
- Amendment round 2 lifecycle critic: approved; plans/review-amendment-r2-server-by-lifecycle.md. All R1 DTO, isolation and runtime-identity/path findings resolved; no substantive blocker remains.
- Owner fixes after amendment round 2: clarify the existing 1,649-line path-test exception cannot grow; audited all three plugin guidance/inventories and concrete MCP import closure, so unrelated client bin/generated files remain unchanged. Scoped metadata wording correctly distinguishes DTO contracts from naturally relocated function defining modules. No production scope expansion after review.
- Coordinator release: awaiting exact plan-tree publication. All supporting source/safety/packaging relocation remains untouched.

No relocation or public safety/packaging edits before this amended gate is complete.
