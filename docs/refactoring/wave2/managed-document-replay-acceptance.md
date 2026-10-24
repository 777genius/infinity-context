# Authenticated managed-document replay acceptance

## Official-data result and exact source

The original full official LongMemEval E2E passed on the pre-classification-follow-up candidate:

- HEAD: b230f59bc2643605b777cb253d0122c188b12cd8.
- Tree: 7f77f9be4822e2b147b6b3e24f64f3c1c69c9a07.
- Published tree-equivalent verification commit: 2ec3843594b7f45e4bbfe4a972a0b720a1f392c8.
- Result: **1 passed in 986.33 seconds**, no failures, errors or skips.
- Candidate HEAD, tree and clean status were unchanged before and after execution.

This is the original test, complete official input and all original assertions. It prepares all
124,344 operations, then proves the authenticated canonical document write, idempotent replay,
tampered-operation rejection and exact canonical row counts. It does not claim that 124,344
documents were written: the full preparation precedes the original selected canonical write.
Actual PostgreSQL 18.6 and UTC were used. The official input is 277,383,467 bytes with SHA-256
d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442.

## Defect and bounded correction

Managed writes intentionally preserve the existing legacy-format digest. Replay previously
interpreted that digest as an ordinary legacy document and required a single complete fragment.
The first original official operation has multiple fragments, so its legitimate replay failed
with Legacy document source cannot be verified exactly after successful real admission.
The affected ingestion, replay and E2E files were unchanged from the pre-refactor baseline.

The separate managed verification mode is selected only by successful fresh managed admission.
It is carried through all three receipt and both duplicate exits; nested conflict recovery uses
its own newly admitted key and mode. Namespace or digest alone cannot enable this mode.

Managed replay verifies the written legacy fingerprint, exact canonical scope/thread/source,
title stripping and classification, the complete original fragment projection, and the owned
metadata. Fragment count, sequence, kind, text and spans must match. Owned metadata preserves
key presence, array order and JSON scalar types, including boolean/integer and integer/float
distinctions. Harmless fetch ordering remains acceptable. Unrelated user metadata is outside
this declared identity projection.

Ordinary modern and conservative ordinary legacy behavior remains the default. In particular,
ordinary legacy multi-fragment replay is still rejected. No hash migration, broadened admission,
provider dependency, schema change, runtime identity relaxation or fixture rewrite is included.

The three metadata helpers moved into one shared application owner with complete AST and
loaded-name equivalence to the original definitions. Their former private names remain direct
aliases. The production files are 67, 229 and 297 lines; the final focused regression file is 513 lines.

## Tests and independent reviews

Plan ac2152a3 records two critics and two rounds before product b1daf352. The final regression
commit is f971807da5cbf39b87125836251c40122b508a0a, published with an identical tree at
e4a27a2bfba578f9dd243548aff504fd1e7b8e9c. Both independent GPT-6.1 Sol xhigh source reviewers
approved the complete implementation and tests with no blocking finding.

The initial committed focused gate passed **77 tests**: 30 new authority/replay/corruption cases and
47 existing ingestion, admission, server and adapter contracts. The exact new positive receipt
regression was copied outside the frozen pre-fix repository and failed through the authentic
old legacy-replay error; it did not fail because a new API was missing. The earlier development
75-pass/1-failure run is preserved separately: its sole failure was a new negative test's error
message expectation, corrected without changing production code.

The new cases cover receipt replay, legitimate missing-receipt duplicate recovery, actual flush
and nested receipt conflicts, fresh nested admission denial/key drift, namespace-only rejection,
digest-format rejection, raw-text hash collisions, changed commands, sixteen projection
corruptions, stable canonical IDs and row counts, and explicit ordinary legacy rejection.

The affected real Docling HTTP and multimodal E2E paths also passed on b230f59b: **2 passed in
168.15 seconds** with the original assertions and process timeouts. A real standalone core wheel
built from this candidate contained the exact new helper bytes and passed all 298 frozen public
exports, three historical instance pickles and 519 verified installed module origins under
isolated Python without source fallback. Combined lint and all 99 frozen file-size ceilings passed.

## Subsequent HTTP conflict regression and final correction

Hosted CI exposed an additional error-contract regression after the initial source review:
the unchanged PostgreSQL HTTP identity node expected 409 for a case-changed v1-digest collision,
but the new managed projection verifier raised an invariant error and the public mapper returned
500. The same original node failed locally on clean b230f59b. Both failures remain retained;
the initial 77-test proof did not establish this mounted HTTP contract.

Two critics completed two additional plan rounds before the bounded correction. Product
ce66157889094faeb577acb8a13e90167b5d26bb changes exactly one production exception name from
MemoryInvariantError to MemoryConflictError at the managed projection comparison, preserving
its message, predicate and every rejection. Reversing that one name restores the whole module
byte-for-byte and AST-for-AST. Common ownership/impossible-span invariants, the global HTTP
mapper, the original PostgreSQL test and its authority double remain unchanged.

The final focused gate passed **80 tests in 66.20 seconds** on committed ce661578: 33 new cases
and 47 existing contracts. Its tracked production/test source was unchanged; three untracked
acceptance-document drafts were present and are not represented as a clean owner worktree.
The strengthened text-mismatch assertion requires the conflict class, two structural cases
require the invariant class, and a real-storage negative proves two distinct fresh admission
UoWs, unchanged document/chunk/outbox/receipt counts and unchanged corrupted text after denial.

The complete original PostgreSQL HTTP identity file then passed **2 tests in 8.85 seconds** on
clean final composed HEAD 437796a5785aa39c8c3a04c8d7ff5c991588d63e, tree
e5f5e09339af4c1bd9b927460125cf94ba69773d. This includes ordinary compatibility, both collision
header modes, original receipt fingerprint and 409 rejection. Published verification commit
472ee06add689c5ec9e80ee7245eddabf7f4ff05 has that exact final tree.

Both independent final source reviewers approved ce661578 and its scoped reuse proof. The
prior full LongMemEval and Docling executions retain their actual b230 pins: successful exact
projections do not execute the changed raise; the original LongMemEval tamper is rejected by
its upstream strict admission; ordinary Docling paths do not select managed replay. They are
not relabeled as fresh executions on 437796a5. The original failed CI run, local 500 reproduction,
strict one-name proof and corrected PG result are in the final evidence index.

## Cleanup and evidence

After the full LongMemEval run, an independent catalog check found no leftover test database,
runtime login role or other PostgreSQL 18 test client. The shared capability-role attributes and
memberships exactly matched their pre-test baseline. No new OOM event occurred during this run;
ambient earlier counters are preserved rather than described as a globally OOM-free session.

The coordinator retained full JUnit, logs, commands, source pins and phase/resource samples:
managed-replay-final-focused.*, managed-replay-prefixtest.*, e2e-final-lme-final-composed.*,
e2e-final-lme-resource-samples.json, post-final-lme-role-and-database-cleanup.json, and
e2e-final-core-wheel-*.json. Their compact hashes and source records are committed in
[the final evidence index](evidence/e2e-final-acceptance-summary.json).

Independent reviews are recorded in
[the architecture review](reviews/review-code-managed-document-replay-by-architecture.md) and
[the unit review](reviews/review-code-managed-document-replay-by-units.md).
The repository-wide result and its two external blockers are described separately in
[final E2E acceptance](e2e-final-acceptance.md).
