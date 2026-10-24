# Evidence/provenance policy refactor: final verification

Direction: server comparison policies, [PR #93](https://github.com/777genius/infinity-context/pull/93).
Pinned original base: `44ac164a8395c5847ae8792dded95d0dfe4526dd`.
Reviewed published production source: [`2736456a`](https://github.com/777genius/infinity-context/commit/2736456a4fe45a62535e60c9cbb4813fc5f53b74);
distribution/runtime regressions: [`2cbd369b`](https://github.com/777genius/infinity-context/commit/2cbd369b125ed0b88018c20cf2a1aa9b015d71f8);
fake installed-RECORD fixture correction: [`079bef8d`](https://github.com/777genius/infinity-context/commit/079bef8d3eb1f61663561bc96202bbe973a19260).
Final combined source after merging the other two refactoring directions:
[`611929d8`](https://github.com/777genius/infinity-context/commit/611929d861db5ad21cffc00b3622b88774eaec09), tree
`fc2b67c91c5d3e58e1e60e1af7ab81669360776f`.

The implementation establishes a real benchmark-owned evidence/provenance boundary while retaining the server planner coordinator and compatibility imports. Candidate support, role satisfaction, ordering, bounded repair, source identity and quality projection now have explicit one-way dependencies. No ranking conditions, score arithmetic, regexes, source-safety checks, selection ordering or result payloads were rewritten. No third-party runtime dependency was added.

## Measured ownership and debt

| Existing server module | Before | After | Remaining responsibility |
| --- | ---: | ---: | --- |
| `memory_comparison_bundle_planner.py` | 3,521 | 822 | Original planner/plan classes and orchestration; explicit compatibility exports |
| `memory_comparison_source_identity.py` | 1,655 | 102 | Explicit aliases to the one benchmark-owned source authority |
| `memory_comparison_bundle_partial_support.py` | 107 | 13 | Explicit aliases to the unchanged partial-role policy |

The actual server benchmark file count and its accepted ceiling both remain **483**. Actual measured server benchmark lines decrease by **4,346**, from **212,528 to 208,182**, and `SERVER_DEBT_MAX_LINES` is lowered to 208,182 to prevent refilling the freed space. The planner and source-identity legacy file-size exceptions are removed. Combined with the other two directions, the original 107 frozen legacy ceilings become 102; this direction removes only its own two entries. No legacy ceiling increases.

The standalone distribution is `infinity-context-benchmarks==0.1.0`. It depends only on the existing internal `infinity-context-core==0.1.0`. The server declares its new internal benchmark dependency. The root bundled wheel continues to contain the packages together.

| New benchmark module | Lines | Policy authority |
| --- | ---: | --- |
| `evidence_bundle/models.py` | 187 | Immutable candidate/item contracts and serialization |
| `evidence_bundle/source_policy.py` | 293 | Locality, grounding and overlap facts |
| `evidence_bundle/candidate_policy.py` | 766 | Candidate role, support and eligibility |
| `evidence_bundle/role_support.py` | 428 | Selection-level required-role and bridge satisfaction |
| `evidence_bundle/ordering.py` | 276 | Existing stable ordering tuples |
| `evidence_bundle/role_repair.py` | 212 | Existing bounded missing-role repair |
| `evidence_bundle/quality.py` | 941 | Complete existing post-selection diagnostic projection |
| `evidence_bundle/partial_support.py` | 107 | Existing partial-role helper |
| `source_identity_safety.py` | 340 | Safe primitive refs, labels and private-reference filtering |
| `source_identity_parsing.py` | 847 | Structured/text turn and session parsing |
| `source_identity.py` | 644 | Recursive normalization, ordered projections and audit gaps |

All new/repartitioned production modules are at most 941 lines. Shared sensitive-text regexes and functions move unchanged to the 39-line public core module `infinity_context_core.sensitive_text`; the old application module aliases the same objects. Core has no benchmark dependency. Benchmark modules import only stdlib, their own package and that public core safety contract, with no server, adapters or `core.application` imports. Existing source-window orchestration remains in the server.

## Compatibility and exact behavior

Original planner, source-identity and partial-support module names remain explicit compatibility entrypoints, including original private helper and constant import names. `EvidenceBundlePlan` and `EvidenceBundlePlanner` remain defined in the original server module with unchanged bodies. Existing coordinator method patch points remain on those classes. No dynamic forwarding, `sys.modules` shim, duplicate implementation or patch-routing mechanism was added.

The deliberate metadata change is that `EvidenceBundleCandidate` and `PlannedEvidenceItem` are now canonically defined in `infinity_context_benchmarks.evidence_bundle.models`. Keeping their old server `__module__` would make normal standalone pickle and forward-reference type hints depend on an absent server package. Original server exports alias the exact same canonical class objects. Constructors, dataclass fields/defaults/order, frozen behavior, equality, repr and payloads remain unchanged. Actual pre-move pickle bytes resolve through the original facade into those canonical classes; standalone new pickle round-trips and `typing.get_type_hints` work with the server absent. Relocated functions naturally have new defining modules, while their original import/signature/function-pickle lookups remain available through aliases.

Historical `contract.json`, its original DTO module metadata, old pickle bytes and all permanent expected output fixtures remain unchanged. Tests separately assert the two reviewed canonical-module exceptions and compare every other historical contract field directly. The source/safety compatibility fixture adds 61 original callable signatures and four original-function pickle references captured before those sources moved.

Independent AST audits by the coordinator and core critic confirm that all **226 original declarations** occur exactly once with identical bodies: 129 planner declarations, 90 source-identity declarations, three partial-support declarations and four sensitive-text declarations. This includes all 115 original planner functions/classes. The core critic also compared runtime global bindings, including nested function code: preserved bodies resolve their helpers/constants to the exact objects exported through the compatibility facade.

### Frozen output evidence

Before production edits, a temporary recorder captured **251 unique planner invocations** from 468 existing tests plus explicit boundary cases. It records raw and normalized configuration, original tuple/list sequence kinds, all candidate fields, ordered item payloads and complete diagnostics. Replay reconstructs tuple fields from original dataclass annotations and checks runtime tuples as well as complete ordered serialized output. Cases include clamped 0/-1 caps, caps of one, tied-input permutations, empty/unknown/missing roles, source diversity, temporal/count/list support, participant repair and chained/complementary bridges.

All **251/251** invocations match exactly after extraction, including an independent critic replay. The complete scratch corpus is verification evidence, while the repository keeps 20 readable complete-output cases and the historical compatibility fixtures. No expected output was regenerated from the new implementation.

| Baseline evidence | SHA256 |
| --- | --- |
| Original planner source | `f2cd20e94fba4427d7646cccbd9631445b8a06b050b4b68ac37da128da027f50` |
| Full 251-invocation corpus | `507e6882e8d7d148d98b9bf924aa0386df1334fba3239528b344212b967c4006` |
| Historical DTO/signature/pickle contract | `ad86d4808c1231c49a30ce5ca5cd902c572a149f32e1d7acd39f0f30e6746eb0` |
| Added pre-move source/safety signature/pickle contract | `bb6262f3f355bd226628ce7e20ef3d53fcf5cf749c862fffc2e203125d6b91c5` |

## Independent installation proof

Run the committed proof from the checkout with a Python containing pip, setuptools and wheel:

```bash
python scripts/smoke_benchmark_package_wheels.py \
  --output /tmp/infinity-context-benchmark-wheel-smoke-final
```

It stages clean source outside the checkout; excludes hidden, build, dist, cache and node_modules trees; builds offline with `--no-index --no-deps --no-build-isolation`; and installs with `--no-index --no-deps` into three separate targets. The root bundle is built before per-project `build/lib` directories exist, preventing intermediate namespace discovery from contaminating the bundled wheel. Child probes run from an external cwd with `python -I -S` and exactly the relevant installation target added to `sys.path`. Every loaded owned module origin must be inside that target.

All five final combined-source wheels build, and all three isolated contexts pass:

| Installed artifacts | Result |
| --- | --- |
| Core + benchmark only | PASS; server/adapters not importable; both DTOs construct, resolve type hints and pickle; nonempty role/quality projection and sensitive-label rejection pass; 514 owned module origins inside target |
| Actual server + core + benchmark + runtime-bridge wheels | PASS; declared `Requires-Dist` chain verified; old/new class identity and actual historical pickles pass; complete frozen nonempty planner output matches; 519 origins inside target |
| Root bundled wheel only | PASS; same old-facade/pickle/full-output checks, with 519 origins inside target |

The core initializer already eagerly imports core-owned public internals. The isolated proof verifies their origins as well; there is no shared editable-install, checkout, `.pth`, user-site or third-party provider fallback. These installation checks exercise the policy/facade boundary; real HTTP/worker integration is covered by the separate combined E2E gate.

Final combined-source artifacts, recorded in the smoke `report.json`:

| Wheel | SHA256 |
| --- | --- |
| `infinity_context-0.1.0-py3-none-any.whl` | `fd0de99afb24a6dfc3f92018b3a74c942e7ffd2a1564fe61755ec2cdc2cb2d9a` |
| `infinity_context_benchmarks-0.1.0-py3-none-any.whl` | `343ae8e149aa57343957ad532096e58984dbb1418eb94dc3cdbc4cb6527c38de` |
| `infinity_context_core-0.1.0-py3-none-any.whl` | `525e0a80d1c8045b9ee43a0b8be6ab06519aa776047e81b5b774f6e6ee73c0c2` |
| `infinity_context_runtime_bridge-0.1.0-py3-none-any.whl` | `4c3379ec667a9d169cdb475cc00bc5fa11912b5a7c5dc8273ab198cf86c687ee` |
| `infinity_context_server-0.1.0-py3-none-any.whl` | `e60b26119d88541090b63ba29056c8cbe01b208bd4a3dc2d94cc7ca447bc3472` |

The lifecycle critic independently inspected the initial source-only five-wheel build, checked module bytes and metadata against the reviewed source, and reran all three probes. The combined-source five-wheel build above was repeated after merging the other two directions.

## Runtime identity and source launchers

`build_identity._RUNTIME_PACKAGES` now includes benchmarks. Every other production identity-check AST is unchanged. Four new semantic regressions prove that benchmark edits alter source/installed runtime digests and that missing RECORD identity or out-of-installation shadow modules are rejected. The final focused run exposed one old fake installation fixture whose static RECORD list still contained four roots while its module generator already used all five. Published commit `079bef8d` adds only the correct benchmark `__init__.py` RECORD entry. Production guards and existing assertions remain unchanged; the serving-profile and four negative/digest regressions then pass 12 tests, independently rerun by the lifecycle critic.

Root discovery, pytest/Makefile/Compose source roots, real-server harnesses, required benchmark scripts and actual server-starting Obsidian specifications include the new package. The large multimodal path-list test retains its original 1,649-line legacy ceiling. Dockerfile already copies all packages and build_manifest already includes the packages tree, so neither receives an unnecessary inventory edit.

The separate client closure audit found eight plugin wrappers (main three, Cursor two, Gemini three), rather than the initial estimated nine. Wrappers, managed plugin outputs, the generated install CLI shim and the direct Obsidian CLI fixture remain unchanged. MCP, plugin-hook, CLI and Obsidian CLI entrypoint imports passed with a guard rejecting server/benchmark imports; the doctor inline Python is stdlib-only. Their Docker service-name strings do not create a Python benchmark dependency.

## Test and review results

| Gate | Result |
| --- | --- |
| Untouched-base focused planner/source/answer/quality suites plus benchmark file | 655 passed |
| Final independent source/contract/safety/architecture selection | 99 passed |
| Full frozen invocation replay | 251/251 exact, independently repeated |
| Final combined full unit suite | 11,134 passed, 40 skipped, six subtests passed; all eight shard exits zero |
| Final combined architecture suite | 219 passed |
| Final combined real HTTP/worker E2E | 3 passed |
| Deterministic evaluation suites | Seven pass; complete metrics and gate dictionaries equal the untouched baseline |
| Isolated distribution checks | Five wheels build; three isolated contexts pass |
| Serving-profile plus new runtime-identity regressions | 12 passed, independently repeated |
| Repository Ruff, base-ref file-size ratchet, secret scan and diff whitespace | Pass; 102 combined frozen legacy ceilings |

The seven deterministic evaluation suites are small-golden, quality-golden, semantic-linking-golden, long-memory-golden, auto-memory-golden, graph-native-golden and prompt-contract. They use the existing local evaluation configuration. The required benchmark composition suites exercise the real comparison entrypoint, evidence planner, report and answer-context consumers with local fake providers.

These are local gates using the frozen Python 3.12 environment. GitHub Actions is queued/pending as of this finalization and is not claimed green. Unit skips are existing environment/optional-provider skips. PostgreSQL/Qdrant service jobs and the CI Python 3.13.5 matrix remain unconfirmed until remote execution; local passing results do not substitute for those jobs.

The separate optional mem0 adapter boundary suite has three passing cases and one environment failure because the frozen environment lacks optional `mem0`. The identical case fails on the untouched original base. The new physical source-package-origin assertion passes. No dependency refresh or test weakening was used to conceal this preexisting limitation; no credentialed cloud evaluation is claimed.

Both the original plan and the architectural amendment received **two independent critics, two review/fix rounds each**, before their respective implementation releases. The amendment explicitly resolved standalone DTO identity/pickle behavior, actual server-wheel dependency proof, runtime trust inventory and client source-path closure. The final core-owner review approves the policy/DTO/import scope after independently confirming all 226 declarations, global bindings, historical fixtures and all 251 replays. The final lifecycle-owner review approves packaging/public safety/runtime identity/source-launcher scope, including the later one-entry fake RECORD correction. Neither final review requests substantive source changes. Their complete review records are [published on PR #93](https://github.com/777genius/infinity-context/pull/93#pullrequestreview-5631687280).

## Reproducible gates

Use the repository's frozen Python with imports pointed to this checkout:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_memory_comparison_bundle_policy_contract.py \
  tests/unit/test_memory_comparison_source_identity.py \
  tests/unit/test_memory_comparison_diagnostic_safety.py \
  tests/unit/test_sensitive_text.py \
  tests/unit/test_serving_profile.py tests/unit/test_benchmark_build_identity.py
.venv/bin/python -m pytest -q \
  tests/unit/test_memory_comparison_bundle_planner*.py \
  tests/unit/test_memory_comparison_evidence.py \
  tests/unit/test_memory_comparison_benchmark.py \
  tests/unit/test_memory_comparison_answer_context.py \
  tests/unit/test_memory_comparison_quality_diagnostics.py \
  tests/unit/test_memory_comparison_quality_bundle_support_gaps.py \
  tests/unit/test_memory_comparison_quality_bundle_gap_report.py
.venv/bin/python -m pytest -q tests/architecture
FILE_SIZE_BASE_REF=44ac164a8395c5847ae8792dded95d0dfe4526dd \
  make infinity-context-lint PYTHON=.venv/bin/python RUFF=.venv/bin/ruff
```

The full combined unit suite executes every collected `tests/unit` case with the committed helper:

```bash
.venv/bin/python scripts/pytest_ci_shard.py --shard-index INDEX --shard-total 8 \
  tests/unit -q -ra --maxfail=3
```

Replace `INDEX` with each integer zero through seven exactly once, with at most two processes running concurrently. Every shard's complete output and exit status is captured separately. Scheduling the longest shard first changes no selection semantics.

The original environment's sandbox exposes inconsistent process namespace identities; tests that exercise process attestation/server construction use the approved real-process execution mode rather than changing production runtime checks. No paid provider, live multimodal service or full Obsidian application run is required or claimed for this extraction.
