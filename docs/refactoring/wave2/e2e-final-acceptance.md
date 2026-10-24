# Final E2E acceptance and remaining external prerequisites

## Outcome

The independently joined ledger contains **237 logical E2E cases: 235 unique passing
observations, two explicitly blocked cases and no pending case**. The separate genuine
Python 3.11 Mem0 adapter suite passed 40 cases and is not added to that E2E count.

This is a source-bound ledger of the full original run and focused corrected-source reruns.
It is **not** a claim that all 237 cases ran together on one final commit or that every gate is
green. Both blocked scenarios remain unresolved and retain their unsuccessful histories.

The full ledger, including original failures/skips and repeated observations, is committed as
[compressed JSON](evidence/e2e-unique-outcome-matrix.json.gz). The readable
[evidence index](evidence/e2e-final-acceptance-summary.json) records hashes, source pins and
independent accounting. Source metadata, actual successful outputs and retained failure records
are in the [execution evidence archive](evidence/e2e-execution-evidence.json.gz); raw diagnostics
with credential-shaped test URLs are explicitly hash-only. The initial JUnit had 236 records: 233 individual cases plus three
module-level skips. Those modules contain four Docling functions, producing the 237-case
logical inventory when the real optional dependencies are available.

## Disjoint reconciliation of the 235 passing cases

| Group | Unique cases | Actual execution or correction |
| --- | ---: | --- |
| Original broad passing cohort | 214 | Original 6fce8875; two document-identity nodes finally rechecked on 437796a5 |
| MCP and agent subprocess recoveries | 10 | Original source; standard fd capture replaced the runner's invalid tee-sys capture |
| Receipt/materializer and crash-replay recoveries | 2 | Original source; recovered task-owned PostgreSQL clusters restored to UTC |
| Full official LoCoMo verification | 2 | Reviewed two-test correction, clean combined source 72b20297 |
| Real Neo4j/Qdrant contract | 1 | Actual Neo4j 5.26 and Qdrant 1.18 |
| PostgreSQL 16-to-18 restore | 1 | Genuine Docker CI job 120845704649, exact checkout 440c0d53 |
| Real Docling functions | 4 | Two retained pure functions plus two final affected functions on b230f59b; HTTP repetition deduplicated |
| Full original LongMemEval | 1 | Final clean b230f59b; 124,344-operation preparation and original canonical replay/tamper/count assertions |
| **Total** | **235** | No repeated observation is counted as another case |

The original individual result remains 214 passed, 16 failed and three skipped, plus the three
separate module-skip records. Corrected outcomes replace final dispositions without erasing
those histories. No supplemental observation failed to join the inventory.

## Final product source and focused evidence

The final composed implementation is 437796a5785aa39c8c3a04c8d7ff5c991588d63e, tree
e5f5e09339af4c1bd9b927460125cf94ba69773d. Published verification commit
472ee06add689c5ec9e80ee7245eddabf7f4ff05 has that exact tree. It combines the reviewed
architecture work, the four bounded E2E/production repairs and the final HTTP conflict correction.
The full LongMemEval and affected Docling runs retain their earlier actual b230f59b/tree7f77
execution pins under the strictly bounded one-raise reuse proof below.

| Gate | Recorded result and source |
| --- | --- |
| Full official LongMemEval | 1 passed in 986.33 s on b230f59b, clean before/after |
| Final affected Docling HTTP/multimodal | 2 passed in 168.15 s on b230f59b, clean before/after; all five multimodal jobs and the HTTP job completed |
| Final managed replay and ingestion contracts | 80 passed on ce661578; original 77-pass gate retained separately |
| Original PostgreSQL HTTP identity file | 2 passed in 8.85 s on clean 437796a5, including restored 409 conflict semantics |
| Heartbeat repair affected files | 57 passed on afde2d95, unchanged five-second completion assertion |
| Real SQLite/PostgreSQL progress contracts | Expanded 44-case matrix and final 10 explicit/missing cases passed; their overlap is documented, not summed |
| Final standalone core wheel | All 298 exports, three instance pickles and 519 installed origins passed on b230f59b; exact new helper included |
| Combined lint and file sizes | Passed; all 99 existing legacy ceilings retained |

The original complete unit run has its own provenance: 12,301 unique nodes in 696 files,
12,277 passed, 23 skipped and one failed, with six passing subtests separately. The diagnosed
heartbeat failure was repaired and passed the focused gate above. That earlier whole run is
not relabeled as green.

Similarly, the 259-test architecture run belongs to a5333eb2, before the final heartbeat/replay
product changes. All seven deterministic evaluations matched the pre-wave-two baseline on
6fce8875; five actual wheels and three installation contexts were proved on that source.
The additional b230 standalone-wheel probe and focused product tests are recorded separately.

## Coordinator's bounded impact review and reuse limits

The final source manifest preserves every unchanged tracked entry and names all 26 differences
from 6fce8875. Only eight production files change: five for running extraction progress and
supervision, and three for authenticated managed-document replay and shared metadata helpers.
The remaining differences are reviewed tests or documentation. Frozen contracts, dependency
locks, official corpora, runtime/RECORD/origin checks, accepted ADRs and size inventories are intact.

The extraction change has one real repository implementation and two affected test doubles;
all were updated. The dedicated four-column compare-and-set operation preserves cancellation,
running-attempt ownership and newer times, while general save/retry/terminal reset behavior
stays unchanged. Deterministic real SQLite/PostgreSQL interleavings, the original API assertion,
the 57-test affected gate and final real HTTP/multimodal execution cover that changed behavior.

Managed replay selects its new verifier only after fresh successful admission. All recovery
exits carry their own admission result. Ordinary modern/legacy branches remain the default;
three moved helper bodies and their globals are unchanged and their old names are direct aliases.
The final 80-test gate covers ordinary and managed paths, and full official PostgreSQL LongMemEval
proves the admitted multi-fragment replay, tamper rejection and original canonical counts.

A subsequent CI and local real-PostgreSQL check exposed a missed contract in the initially
carried document-identity case: b230 returned 500 instead of 409 on a rejected managed text
collision. Its earlier pass was invalidated, the ledger marked the regression, and a separately
twice-reviewed one-raise correction was made. The whole original two-node PostgreSQL file
passed on 437796a5 before the final passing disposition was restored. Neither failure is erased.

The final correction changes only the exception class of one managed projection mismatch.
Both reviewers independently proved whole-module byte/AST identity after reversing that one
name, with every predicate/message/other branch unchanged. The new negative integration test
proves fresh read-only conflict recovery, while common structural errors retain invariant/500
semantics. This precise proof supports reuse of b230 success and upstream-admission paths;
it is not a claim of new LongMemEval or Docling execution.

This impact review supports carrying prior observations forward within those stated boundaries.
It does not turn them into executions on a different source. Two original document-identity
functions executed on the final 437796a5 candidate. The three heavy LongMemEval/Docling functions
retain b230 provenance; the two pure Docling functions and hosted restore have separate
structural reuse proofs. Every other selected pass retains its actual execution source in the
ledger rather than being represented as a fresh final-head run.

The pure Docling map independently proves 24 whole-file identities and eight exercised
definition identities; two containing modules have only explicitly unused additions. The hosted
restore map proves the test/workflow/lock and 186 of 187 PostgreSQL files identical, with the sole
changed repository containing only unused progress additions for that scenario. A retained ACL
test in an edited test module has an unchanged function/import/global/helper closure; the edited
adversarial helper is not called by it. None of these maps falsely labels a changed whole module
as byte-identical. The detailed maps are in
[the source-reuse evidence archive](evidence/e2e-source-reuse-proofs.json.gz).

The unit owner independently derived the inventory and joins; the E2E owner independently
reviewed the completed ledger and corrected the custom-runtime blocker wording. The
coordinator reviewed the bounded production impacts and these source distinctions.

## Two unresolved scenarios

### Custom Mem0 process recovery

The custom loopback process-recovery harness fails during Phase-C binding because the exact
authentic deployed subscription-runtime artifact is unavailable. It does so before its embedded
actual-adapter gate executes. The separate genuine adapter's 40 passing tests are valid
independent evidence, not a replacement for the blocked process scenario.

### PostgreSQL 16 managed live canary

Actual PostgreSQL 16 provisioning and server/worker startup succeeded. The retained test still
uses an obsolete CLI invocation, missing the mandatory extraction-token ceiling and managed-v5
config, and its legacy bridge does not implement the current durable V5 protocol. A valid
migration also requires the same authentic runtime bundle. Supplying a bundle alone will not
make the old command correct: the bounded test-harness migration and both real executions
remain work to perform after authentic prerequisites are available.

Required runtime source commit: e904ec95fda4b04c333e5a7613c7729bf7abb125.

- artifact-manifest.json SHA-256:
  789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850.
- release.json SHA-256:
  8854ae10ea450fc615af251cdd5eef8812f928b458f710bb84b0cdbdde92fceb.

The expected deployed root is
/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95.
The existing Node, Phase-C tree, file-mode/owner/origin and referenced-artifact checks also
remain mandatory. Public source/releases/CI and the connected prior-work/file searches did
not provide the exact deployed bundle. No replacement manifest, fake identity, broad skip or
private legacy execution path was introduced.

Both critics completed two rounds on the
[conditional PG16 migration plan](pg16-modern-canary-conditional-plan.md). Its go/no-go controls
are approved; it does not claim implementation or acceptance while the assets and exact
supported harness design remain unavailable.

## Reviewed pull requests

- [#99](https://github.com/777genius/infinity-context/pull/99): benchmark scoring owners and compatibility.
- [#100](https://github.com/777genius/infinity-context/pull/100): explicit lazy core exports and verification repairs.
- [#101](https://github.com/777genius/infinity-context/pull/101): preserve real worker fairness in multimodal acceptance.
- [#102](https://github.com/777genius/infinity-context/pull/102): atomic heartbeat progress and correct fixture loop ownership.
- [#103](https://github.com/777genius/infinity-context/pull/103): strict authority oracle and exact ACL cleanup.
- [#104](https://github.com/777genius/infinity-context/pull/104): authenticated complete managed-document replay.

Each implemented direction had two critics and two plan rounds, independent code reviews,
review fixes and source-bound acceptance. The unrelated #91 is excluded from this work.
After integration, the coordinator compares all non-documentation entries of main against the
verified 437796a5 tree; merge history and publication commit identities are kept distinct from tree identity.
