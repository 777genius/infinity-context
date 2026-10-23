# Evidence bundle planning: policy boundaries with identical results

Status: both independent critics approved round 2 after round 1 fixes; awaiting coordinator release. No production implementation is authorized until the coordinator releases the review gate.

Base: `44ac164a8395c5847ae8792dded95d0dfe4526dd` (`main`). Direction: server comparison policies. Worktree: `worktrees/server`; branch: `refactor/comparison-policies-20261023`.

## Why this scope

`memory_comparison_bundle_planner.py` has 3,521 lines, three immutable DTOs, a 349-line selection coordinator, and 112 policy/serialization helpers. Its public output serialization calls the same module's 543-line quality aggregator. Required-role repair consumes selection ordering, which consumes role-satisfaction policy; keeping them in one namespace obscures this dependency direction. Candidate support, source-turn locality, bridge sufficiency, ordering, repair, and quality explanations are different change responsibilities. The existing six planner test files exercise those responsibilities independently but import the same module.

This is the largest identified server comparison policy hotspot. Decomposing it is higher priority than separating the 2,798-line report-wide quality_diagnostics module: the planner directly determines selected evidence and its quality explanations. This direction will eliminate one legacy file-size exception completely and establish explicit one-way policy dependencies for every function in that hotspot. It is not a rename or a line-count slice. Rerank (3,209), intent (2,925), and report-wide quality diagnostics remain separate follow-up work, not hidden additions to this PR.

## Scope and exact files

All production paths below are relative to `packages/infinity_context_server/infinity_context_server/`.

| File | Responsibility and contents | Estimated final LOC |
| --- | --- | ---: |
| `memory_comparison_bundle_planner.py` (existing) | Compatibility entry point; `EvidenceBundlePlanner` and `EvidenceBundlePlan` retain their methods and orchestration. `_reason_codes` and `_max_item_drop_counts` remain coordinator-local. Explicitly re-export moved contracts/helpers. | 800-950 |
| `memory_comparison_bundle_models.py` (new) | `EvidenceBundleCandidate`, `PlannedEvidenceItem`, `BundleRole`, and the two source-label serialization helpers. Immutable fields and item serialization only. | 190-230 |
| `memory_comparison_bundle_source_policy.py` (new) | Source identity, turn-ref parsing/proximity/compactness, person-grounding terms, measured-versus-unmeasured locality/answerability checks, and source-overlap risks. Existing source_identity module remains authoritative for canonical identity and output sanitization. | 280-350 |
| `memory_comparison_bundle_candidate_policy.py` (new) | Candidate role assignment, typed temporal/relation/answer-unit support predicates, primary eligibility, answer-evidence buckets, candidate bridge grounding/complementary-value checks. Owns role taxonomy constants. | 740-850 |
| `memory_comparison_bundle_role_support.py` (new) | Selection-level bridge sufficiency, required-role satisfaction, participant-sensitive grounding, partial support; consumes candidate/source facts without sorting or selecting replacements. | 420-500 |
| `memory_comparison_bundle_ordering.py` (new) | Stable primary/candidate/planned ordering tuples, coverage/precision/source/person sort keys, and explicit role-grounding ordering. Consumes role support without invoking repair. | 280-350 |
| `memory_comparison_bundle_role_repair.py` (new) | Existing bounded missing-role repair algorithm and replacement/candidate preference rules. Consumes ordering and role support; no new planner framework. | 220-280 |
| `memory_comparison_bundle_quality.py` (new) | Post-selection quality projection: all existing counters, confidence/reason codes, source-proximity diagnostics, and bounded diagnostic samples. Owns positive-score averaging and quality-only sample limits. | 930-990 |

The AST function inventory assigns every existing function exactly once: model bodies 157 LOC; source policy 212; candidate policy 579; role support 343; ordering 214; role repair 173; quality including samples 866; coordinator/plan/reasons 639. Estimates include imports, spacing, constants, docstrings, and compatibility exports; every changed or new production file must be <=1,000 lines. If quality would exceed the cap after imports, move its self-contained 157-line `_bundle_quality_reason_codes` with `_confidence_band` into `memory_comparison_bundle_quality_reasons.py`; this is the only pre-authorized contingency, and it keeps confidence/reason projection separate from aggregation.

Other changes:

- `tests/unit/test_memory_comparison_bundle_policy_contract.py` (new, <=300 LOC): baseline golden replay and contract/identity compatibility.
- `tests/fixtures/memory_comparison_bundle_policy/` (new): small synthetic golden input/output JSON scenarios captured on the untouched base. Keep each fixture <=1,000 lines; scenarios capture complete ordered item payloads and complete diagnostics.
- `tests/architecture/test_memory_comparison_bundle_policy_boundaries.py` (new, <=160 LOC): policy dependency direction, no facade back-imports, and no infrastructure imports.
- `tests/architecture/file_size_legacy_baseline.json`: delete only the existing bundle-planner exception after it passes the hard cap. Preserve all unrelated entries.
- `tests/architecture/test_file_size_boundaries.py`: remove the brittle assertion that the baseline always has exactly 107 entries; retain actual filesystem ceilings, monotonic baseline checks, and CI base-ref checks. Other direction branches make the same deletion; root reconciles JSON keywise.
- This plan/review record under `docs/refactoring/`.

No core/adapters, HTTP/provider transport, lifecycle, CI, new dependencies, scoring weights, public report schema, or unrelated PR #91 files are in scope.

## Intended dependencies

`models -> existing source_identity` for source-label sanitization.

`source_policy -> models + existing source_identity`.

`candidate_policy -> models + source_policy`.

`role_support -> models + candidate_policy + source_policy + existing bundle_partial_support`.

`ordering -> models + candidate_policy + role_support + source_policy`.

`role_repair -> models + role_support + ordering`.

`quality -> models + candidate_policy + role_support + ordering + source_policy`.

`planner facade -> all of the above + existing bundle_source_windows`.

No policy imports the planner facade at runtime or for typing. No wildcard re-exports, sys.modules shims, global patch forwarding, class hierarchy, registry, or configurable policy framework. Tests exercise policy boundaries directly where useful, while existing tests keep their public imports.

## Contracts preserved

1. `EvidenceBundleCandidate`, `PlannedEvidenceItem`, `EvidenceBundlePlan`, `EvidenceBundlePlanner`, and `BundleRole` remain importable from the original module. Constructor signatures, dataclass field ordering/defaults, frozen behavior, equality/repr, method signatures, and return shapes are unchanged.
2. Keep `EvidenceBundlePlan` and `EvidenceBundlePlanner` defined at the original path. For moved dataclasses, preserve their original `__module__` compatibility path explicitly so pickle/introspection continues to resolve through the old export. Add pickle round-trip/import-identity tests, not new wrapper types.
3. Preserve all original private helper import names as explicit facade aliases, including helpers not currently imported by repository code. The repository search found no monkeypatch of planner module helper globals. Existing planner methods stay on the same class, preserving method-level patch points. This PR does not introduce patch forwarding for unsupported cross-helper monkeypatches.
4. Selection order, tie breaks, dedupe identity, max-item/diversity counters, bounded repair passes, participant-sensitive roles, tuple/list distinctions, numerical arithmetic/rounding, source-reference output safety, reason order, and diagnostic sample bounds remain byte-for-byte equivalent after JSON serialization.
5. Existing `evidence_bundle_planner.v1` and bundle-quality schema keys, confidence thresholds, measured-vs-zero semantics, and empty-input behavior remain unchanged. No new normalization or sanitization is introduced.
6. Existing `memory_comparison_evidence.py` and its output consumers continue to use the old imports without edits. No golden fixture is regenerated from the refactored implementation.

## Plan and validation sequence after the review gate

1. Before edits, record targeted baseline test results and capture synthetic input/output goldens at the pinned base. Capture empty input; duplicate/tied candidates; direct vs broad primary; source type/retrieval diversity; session-qualified turn refs; diffuse/noisy overlap; count/list support; typed temporal support; participant-sensitive role repair; complementary and chained bridges; measured zero vs positive answerability/locality; and missing/partial required roles. Explicitly include `max_items=1`, raw `max_items=0/-1`, each per-source/per-retrieval cap at 1 and 0/-1, and both input permutations of candidates with equal sort keys. Freeze the baseline insertion-order behavior rather than assuming permutation invariance. Include empty and unknown required roles. Full payload snapshots detect lost diagnostics and ordering changes.
2. Add a differential recorder outside the deliverable to run existing planner/evidence tests on the untouched source and record every planner invocation's candidate inputs, configuration, case group, required roles, ordered item payloads, and diagnostics. Replay against the refactor and compare complete payloads. This uses existing semantic scenarios as an independent baseline rather than copying the algorithm into tests. Record raw constructor kwargs before clamping plus resulting normalized configuration. Candidate tuple fields are encoded as JSON arrays and reconstructed as tuples using the original dataclass annotations; reconstruct the candidate sequence and required_roles as tuples. The derived required_terms frozenset is recomputed by the original DTO property, not serialized into mutable input. Assert dataclass field equality/types before replay, retain numeric values exactly, and compare serialized complete output plus the runtime ordered item tuples. Do not turn output JSON into candidate inputs or infer field types from refactored results.
3. Extract neutral DTOs/output-label helpers, then source policy, candidate support, selection-level role satisfaction, ordering, bounded repair, and quality. Move function bodies without rewriting conditions or arithmetic. Introduce only explicit imports, definitions' new home, module docstrings, and compatibility aliases. Keep the actual coordinator and method bodies intact.
4. Add/replay permanent golden scenarios and compatibility assertions. Run the existing focused suites: all six `test_memory_comparison_bundle_planner*.py`, `test_memory_comparison_evidence.py`, source-identity and diagnostic-safety tests, report quality/bundle support tests, and benchmark integration tests. Run architecture tests, Ruff on changed Python, and file-size checks against the root-provided pinned base.
5. Inspect actual diffs for accidental policy edits. The existing provider-free benchmark and answer-context integration tests below are mandatory composition gates: they call run_memory_comparison_benchmark through the actual evidence planner and report/answer-context consumers with local fake providers. Record the untouched-base result and rerun the same commands after extraction. This is separate from recorder replay and from direct planner characterization. No credentialed/cloud evaluation is required for a pure extraction; if deterministic replay reveals any output change, fix it before publication.
6. Update the plan with exact sizes, commands/results, limitations, and reviews; commit the completed direction in its own worktree. Parent handles push/PR publication. No unrelated changes.

## Exact mandatory validation commands

Run these inside the server worktree with the shared frozen interpreter (the pytest configuration resolves imports to this checkout):

```bash
/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python -m pytest -q \
  tests/unit/test_memory_comparison_bundle_planner*.py \
  tests/unit/test_memory_comparison_evidence.py \
  tests/unit/test_memory_comparison_source_identity.py \
  tests/unit/test_memory_comparison_diagnostic_safety.py

/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python -m pytest -q \
  tests/unit/test_memory_comparison_benchmark.py \
  tests/unit/test_memory_comparison_answer_context.py \
  tests/unit/test_memory_comparison_quality_diagnostics.py \
  tests/unit/test_memory_comparison_quality_bundle_support_gaps.py \
  tests/unit/test_memory_comparison_quality_bundle_gap_report.py

/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python -m pytest -q \
  tests/unit/test_memory_comparison_bundle_policy_contract.py \
  tests/architecture/test_memory_comparison_bundle_policy_boundaries.py

/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python -m pytest -q tests/architecture
FILE_SIZE_BASE_REF=44ac164a8395c5847ae8792dded95d0dfe4526dd make infinity-context-lint \
  PYTHON=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python \
  RUFF=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/ruff
```

The first two commands run on the unchanged base and again after implementation; the new-test command starts once its baseline expectations are captured. In the benchmark file, `test_memory_comparison_benchmark_builds_multi_hop_evidence_bundle`, `test_memory_comparison_benchmark_answers_from_planned_evidence_context`, and the evidence-bundle primary/order/dedupe tests explicitly exercise planner composition and downstream prompt/report behavior. Do not replace this command with only direct leaf tests or an optional benchmark lookup.

## Acceptance and risks

Acceptance: complete baseline golden equality and differential replay; existing focused tests pass; dataclass/import/pickle compatibility; acyclic narrow imports; all changed/new source files <=1,000 LOC; owned legacy exception removed; Ruff clean; relevant architecture tests pass. Expected patch: roughly 3,000 moved production lines, 150-300 import/documentation/compatibility lines, 200-350 test lines plus reviewable synthetic golden fixtures; net production growth should remain small.

Primary risks are hidden ordering dependence, cycles between ordering and role satisfaction, source-identity sanitization drift, serialization type changes, and compatibility after moving dataclasses. The one-way graph resolves the observed ordering/satisfaction cycle by keeping `_item_can_satisfy_required_role*` in role_support and `_required_role_candidate_sort_key` in role_repair. Shared source helpers remain single definitions. Full output replay and stable `__module__` address the remaining risks. Arbitrary private monkeypatch routing is not claimed as a supported external API; all repository patch points remain preserved.

## Required review record

- Round 1 critic 1: core direction owner reviewed source/DTO/coordinator/roles/quality seams. Requested executable mandatory composition tests and explicit boundary configuration/tie permutations.
- Round 1 critic 2: lifecycle direction owner independently reviewed source/import graph and requested exact mandatory consumer test commands plus type-faithful recorder reconstruction. Full review: `plans/review-r1-server-by-lifecycle.md`.
- Round 1 fixes: exact commands and named composition scenarios added; base/post composition gates mandatory; raw and normalized constructor config recorded; tuple fields explicitly reconstructed and types checked; clamped caps/max_items, empty/unknown roles and tied-input permutations added to characterization. No production scope expansion.
- Round 2 critic 1: core direction owner approved the revised plan after independently rechecking actual composition scenarios, tuple/config restoration and policy graph. Full review: `plans/review-r2-server-by-core.md`.
- Round 2 critic 2: lifecycle direction owner independently approved exact mandatory consumers and type-faithful recorder reconstruction. Full review: `plans/review-r2-server-by-lifecycle.md`.
- Round 2 fixes: no additional blocking or medium findings; production scope unchanged. Parent implementation release: pending.

Read-only baseline before release: 349 focused planner/evidence/source/answer-context/quality tests passed in 7.24s; the mandatory benchmark file then passed 306 tests in 8.57s (655 total). The default sandbox first blocked benchmark collection because `/proc/{os.getpid()}/stat` exposes mismatched namespace PIDs. Running the identical authorized local pytest command with sandbox escalation resolved the environment issue without any code changes or runtime-identity policy patches. Use the same supported execution mode for final composition/architecture tests. The benchmark run emitted only an existing Starlette TestClient deprecation warning.
