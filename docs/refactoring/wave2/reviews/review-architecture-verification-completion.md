# Combined architecture verification completion

Decision: **accepted after verification-only repairs; no production or inventory change.**
Final owner source: `4ae37097cf770690db396cb80c010440f8e2ef81`.
This record documents fresh combined execution and the independently reviewed corrections;
it does not reuse the earlier Core-B implementation approval as architecture acceptance.

## Initial findings and bounded plan review

The first complete architecture run on frozen combined source
`6fce8875ec8e0c2e13a8560cb312557bd67261ef` returned **233 passed, 4 failed**.
Three unchanged ownership inventories lost symbol resolution because the static index read
only top-level imports, while the preserved compatibility exports now declare their exact
original routes inside `TYPE_CHECKING` blocks. The fourth failure scanned the coordinator's
copied public-benchmark dependency environment as repository source. Neither finding required
a product behavior change or an inventory deletion.

Root and an independent unit reviewer each reviewed the bounded plan twice. Required boundaries
were current sequential import bindings, explicit non-star imports and pure name/attribute
aliases only, no flattening of arbitrary blocks or declarations, preserved overwrite order,
and exclusion of the exact known benchmark dependency path. The second critic additionally
required the guard root to be bound, rather than accepting an unbound module spelling.

The implemented static declaration handling does not execute imports or evaluate manifests.
Classes, functions, calls, nested blocks and star imports inside the guarded declaration block
do not become export bindings. The locator scan excludes exactly the existing public-benchmark
`.venv` directory, using the same explicit-path mechanism as the root environment. Regression
fixtures prove deployment, vendor and unrelated nested environment paths remain scanned,
including archive filtering and forbidden-source detection.

## Review corrections and final source

Root's implementation review caught a forbidden identifier embedded in the new scan regression
itself. The fixture now derives its hostile import from the guard's existing central constant;
no new file exemption or forbidden-identifier allowance was introduced.

An intermediate complete run passed **247 tests**. A subsequent concrete counterexample showed
that the index's old unresolved-assignment fallback could turn a literal/call shadow of the
typing module back into its bare spelling. Unbound name/attribute aliases had the same risk.
Both reviewers reviewed the narrow followup plan twice before implementation.

The followup computes each module assignment's right-hand side once, accepts pure aliases only
when their root is currently bound, and represents unresolved assignments as qualified local
symbols. It preserves per-target router handling and leaves general dotted resolution, call
traversal and all ownership inventories unchanged. New examples cover literal/call shadows,
unbound and chained aliases, captured aliases before a later shadow, and genuine reimports.
The full existing mutation file and three real unchanged inventory checks passed **121 tests**.

Root and the independent unit reviewer approved exact source `4ae37097` with no remaining
blocking findings. The unit reviewer separately executed six direct shadowing, unbound-alias,
capture and reimport counterexamples. These review checks are not added to suite totals.

## Final combined execution and unchanged-source proof

The isolated combined candidate contained frozen `6fce8875` plus the three verification commits:

- Owner commits: `2c2dc504`, `35f58bcc`, `4ae37097`.
- Executed candidate HEAD: `a5333eb2f719f2fca4a29d046a836861a65daa9c`.
- Executed candidate tree: `df9791250b25024ad0be3ed075717e6fad2d2878`.

Using the frozen Python interpreter, unset `PYTHONPATH`, disabled bytecode and pytest cache,
and actual process execution, the complete architecture suite returned
**259 passed in 117.74 seconds**, with no failure. The exact immutable-base size command passed
with **99 frozen legacy ceilings**. Both the candidate and original frozen main stayed clean.

The executed candidate differs from frozen `6fce8875` in exactly four architecture verification
files. All **3,715 other tracked entries** are identical; their sorted Git manifest SHA-256 is
`658b554ccae8e4e01324e28b6ace1e1903c0682e950deccf3ff0665a20356eec`.
Production packages, build/configuration files, fixtures, frozen ownership inventories, debt
budgets and runtime/static export-equality guards therefore remain unchanged. Server benchmark
debt remains **483 files / 203,082 lines**.

All seven deterministic CLI suites passed on frozen `6fce8875` with exact baseline equality for
`suite`, `ok`, `metrics`, `gates` and `checks`, including the prompt snapshot command. Their
product, evaluation and fixture blobs are identical in the corrected candidate, so those results
are reused with their original source provenance. Coordinator evidence retains every full log,
the initial failures, the intermediate 247-pass record marked superseded, and final source-bound
acceptance. The final unique architecture count is **259**; earlier counts are not additive.

Installed-wheel, full-unit and real-service E2E results are separate coordinator-owned gates.
This documentation-only acceptance record is added after the tested candidate.
