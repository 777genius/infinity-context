# Unique E2E outcome accounting — final source-qualified disposition

**235 unique logical E2E nodes have confirmed passing observations, two remain externally blocked, and none is pending. The inventory contains 237 nodes.** The corrected final candidate is `437796a5785aa39c8c3a04c8d7ff5c991588d63e`, tree `e5f5e09339af4c1bd9b927460125cf94ba69773d`. This ledger combines retained source-bound execution evidence with explicitly scoped source-impact reviews. It does not claim that all 237 nodes were run together on that candidate. The separately published composed commit `472ee06add689c5ec9e80ee7245eddabf7f4ff05` has the same tree according to the coordinator's publication record.

## Inventory and unique counts

The original JUnit file contains 236 records: **233 individual cases** (214 passed, 16 failed, three skipped) and **three module-level collection skips**. Those three module records hide four actual Docling functions, confirmed from source and later individual execution records. Thus the logical inventory is **233 + 4 = 237**, rather than 236 or 240. Collection-module skips are not counted as individual test cases.

The current 235 passing nodes reconcile through these disjoint groups:

| Group | Unique nodes |
| --- | ---: |
| Original individual passes retained or revalidated | 214 |
| Original fd-capture failures corrected | 10 |
| UTC materializer and crash/replay corrections | 2 |
| Reviewed LoCoMo oracle corrections | 2 |
| Real Neo4j/Qdrant service skip recovered | 1 |
| Hosted PostgreSQL 16 → 18 restore skip recovered | 1 |
| Four Docling functions hidden by module skips | 4 |
| Actual full LongMemEval acceptance | 1 |
| **Passing unique nodes** | **235** |

The real Docling records contain five successful observations across four unique functions because the HTTP case passed in both its initial and corrected runs. The two corrected PostgreSQL identity passes are repeat observations of two members of the original 214, not additional nodes. Repeated failures and targeted unit gates also add no E2E nodes. The genuine adapter suite passed **40 separate tests**; it is outside the 237-node inventory.

## Late managed replay regression and actual repair proof

The unchanged node `tests/e2e/test_document_content_identity_postgres.py::test_managed_document_identity_preserves_strict_v4_receipts_postgres` has a preserved history:

| Observation | Source | Outcome |
| --- | --- | --- |
| Original full-suite observation | `6fce8875ec8e0c2e13a8560cb312557bd67261ef` | Passed |
| Coordinator-reported CI regression, run 40087556960 / job 120854051391 | `7ef7e4788ba5d40f49328ed07a7fa55fb06239fc` | HTTP 500 instead of the existing HTTP 409 contract |
| Actual real PostgreSQL 18 reproduction | Clean `b230f59bc2643605b777cb253d0122c188b12cd8`, tree `7f77f9be4822e2b147b6b3e24f64f3c1c69c9a07` | One failed in 10.45 seconds; initial creation 201 and unchanged replay 200 succeeded, then case-changed content returned 500 |
| Actual complete unchanged original PostgreSQL identity file after repair | Clean `437796a5785aa39c8c3a04c8d7ff5c991588d63e`, tree `e5f5e09339af4c1bd9b927460125cf94ba69773d` | Both original nodes passed in 8.85 seconds, zero failures/errors/skips, exit 0 |

The late failure invalidated the earlier carry-forward while the repair was pending. It is retained in the matrix and in the pending-regression snapshot. The corrected result now restores this node's current passing disposition without erasing the failed CI/local observations or adding new unique tests.

The bounded amendment at `ce66157889094faeb577acb8a13e90167b5d26bb` changes only the existing managed projection mismatch raise from `MemoryInvariantError` to `MemoryConflictError`. Independent whole-module byte and AST reversal proofs preserve the predicate, message, ordinary branches and common ownership/span invariants. The original PostgreSQL file, its authority double and global HTTP mapper are unchanged. Both independent critics approved the committed code and scoped reuse. The separate focused amendment gate passed 80 tests in 66.20 seconds; these unit results are not added to E2E totals.

## Selected observation sources and reuse limits

Source categories were recomputed after selecting both actual corrected PostgreSQL observations; the earlier blanket prior-source count is not retained.

| Selected passing-observation category | Nodes |
| --- | ---: |
| Prior-source observations retained with explicit source/scope qualification | 227 |
| Actual b230 LongMemEval and corrected Docling successes, with reviewed path reuse | 3 |
| Pure Docling parser observations with dependency/unused-addition proof | 2 |
| Actual corrected final candidate PostgreSQL identity observations | 2 |
| Hosted restore observation with test/provisioning/migration dependency proof | 1 |
| **Total** | **235** |

The actual selected execution HEADs are: **227 at `6fce8875`**, **three at `b230f59b`**, **two at `437796a5`**, **two at `72b20297`**, and **one hosted restore at `440c0d53`**. Categories and HEAD counts describe different dimensions: for example, the two pure Docling observations are among the 227 observations executed at 6fce.

The full LongMemEval run remains an actual **one pass in 986.33 seconds**, and corrected real Docling remains **two passes in 168.15 seconds**, both at clean b230/tree7f77. No new corpus or ML execution on 437 is claimed. Both critics and the E2E owner approved the bounded impact analysis: valid managed projection replay never executes the changed rejecting raise; LongMemEval's tamper case fails at strict authority admission upstream; ordinary Docling does not select managed replay mode. The original runtime pins remain intact. Earlier pure Docling and hosted restore dependency maps remain transitively unchanged by the one-raise amendment. The 227 other observations remain explicitly qualified as prior-source evidence rather than relabeled as fresh corrected-candidate execution.

## Two distinct external blockers

- **Custom Mem0 loopback recovery harness:** the required authentic pinned Phase-C/custom runtime artifact bundle is unavailable. Failure occurs during Phase-C binding **before its embedded adapter gate executes**. The separate genuine adapter suite passed all 40 tests; this blocker is not an adapter-gate failure.
- **Managed production PostgreSQL 16 live harness:** after real PostgreSQL 16 provisioning, the retained command is stale against the current canary CLI, missing `--max-extraction-tokens` and `--managed-v5-config-json`, and it requires a modern authentic runtime bundle. No successful live scenario has been observed. This is a distinct node from the custom harness.

Neither blocked node is reported as passing or silently removed. Their original skips/failures and later attempts remain attached.

## Review artifacts and checks

The matrix is `e2e-unique-outcome-matrix.json`. Source-impact evidence is in `e2e-corrected-candidate-exception-path-reuse-map.json`, the three whole-module reversal proof files, and `managed-replay-http-conflict-e2e-impact-review.json`. Independent final code/reuse decisions are recorded in `plans/wave2/review-code-managed-replay-http-conflict-by-units.md` and `plans/wave2/review-code-managed-replay-http-conflict-by-architecture.md`. Earlier dependency maps cover pure Docling, hosted restore, and the unchanged node in an edited E2E module.

The accounting review checked 237 unique IDs, exact disjoint coverage of 235 passing IDs, both blockers, selected-source/category totals, and the hashes of all recorded JUnit files. There are zero unmapped observations, zero missing-node accounting gaps and zero pending validation items. The regression's historical snapshots remain preserved. This update reads existing evidence only; the accounting/review agent launched no runtime tests and did not rerun the old ledger builder.
