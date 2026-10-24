# Managed replay HTTP conflict amendment — independent review

Reviewer: architecture/evaluation owner, acting as critic 1.

## Verdict and exact source

**APPROVED — code and scoped reuse.** No blocking findings remain in committed source `ce66157889094faeb577acb8a13e90167b5d26bb`, compared with `f971807da5cbf39b87125836251c40122b508a0a`. Parent owns publication and merge. This review started no application runtime or additional test process.

Both plan rounds were reviewed before implementation. Round 1 requested an actual admitted, persisted corruption case through the newly entered conflict-recovery path, rather than relying only on direct validator tests. Round 2 approved the bounded amendment with that case, common structural invariant counterexamples, exact one-raise reversal proof, unchanged original PostgreSQL test, and source-qualified reuse.

## Code inspection and independent proof

The only production change is the exception class at the existing managed projection mismatch raise: `MemoryInvariantError` becomes `MemoryConflictError`. Its predicate and message remain identical. Common ownership/span validation and the global HTTP mapping are unchanged. Replacing that one target raise back to its prior class reproduces the entire previous module byte for byte and as an AST; I independently executed both comparisons from exact Git blobs.

The strengthened text-corruption negative requires `MemoryConflictError`. Two new counterexamples require the original common `MemoryInvariantError` for foreign chunk ownership and an impossible span. The persistent SQLite negative first creates a legitimately admitted document, corrupts only stored chunk text, then repeats the unchanged legitimate command. Its wrapper invokes real admission and checks two distinct fresh unit-of-work instances. The operation raises the exact conflict, preserves the corrupted text, and preserves all four canonical counts. Inspection of recovery confirms the repeated first-key receipt conflict rethrows before duplicate receipt writes.

I independently compared executed composed source `b230f59bc2643605b777cb253d0122c188b12cd8` with corrected candidate `437796a5785aa39c8c3a04c8d7ff5c991588d63e`, tree `e5f5e09339af4c1bd9b927460125cf94ba69773d`. The exact changed paths are the amendment plan, this one production module, and the managed replay unit-test file. The composed old and new production bytes match the reviewed old and new blobs. Original PostgreSQL identity tests, their authority double, HTTP error mapper, and LongMemEval execution test remain unchanged.

The owner worktree has three untracked acceptance drafts. This approval concerns exact committed Git blobs and does not assert that the owner worktree is clean.

## Actual verification inspected

| Evidence | Actual result and source |
| --- | --- |
| Focused amendment gate | 80 passed in 66.20 seconds on committed `ce661578` |
| Unchanged full PostgreSQL identity test file | 2 passed in 8.85 seconds on clean corrected `437796a5`; PostgreSQL 18.6, UTC, normal fd capture |
| Corrected runtime source preservation | Before/after HEAD and tree identical; source status empty; process exit 0 |
| Independent reviewer proof | Whole-module byte and AST reversal; composed exact-path and production-byte comparison; no additional runtime |

The original real-PostgreSQL `b230` failure (HTTP 500 rather than the required 409) remains part of acceptance history. The corrected two-node pass supersedes that current failure; it does not erase or relabel the failed attempt.

## Scope of earlier expensive proof reuse

Prior LongMemEval and real Docling runs retain their actual `b230` execution identities. Reuse is approved for the following demonstrated paths only:

- A valid managed projection never enters the rejecting raise; its successful replay computation and all validation predicates remain byte-identical.
- The original LongMemEval tamper case expects rejection by strict authority admission upstream of replay. That validation error is outside the changed conflict path.
- Ordinary Docling ingestion does not select the managed replay policy. Its exercised successful paths are unaffected by this one raise-class amendment.

This is source-impact evidence, not a claim that those expensive tests were rerun on `437796a5`. The new actual recovery negative and unchanged PostgreSQL HTTP file cover the affected rejection/recovery behavior.

## Evidence locations

- `evidence/wave2/managed-replay-http-conflict-independent-ast-proof.json`
- `evidence/wave2/managed-replay-http-conflict-ast-proof.json`
- `evidence/wave2/managed-replay-http-conflict-focused.log` and `.xml`
- `evidence/wave2/e2e-final-managed-document-identity-postfix.log`, `.xml`, and `-metadata.json`
- `evidence/wave2/managed-replay-http-conflict-e2e-impact-review.json`

Separately, exact PR #101 head `a284c5620991378ed3ab0f9800880cd637cb24a8` has a fully successful required CI run `40110819531`; Quality Gate job `120926306296` completed successfully. The optional synthetic run is skipped. This reviewer performed no GitHub write, workflow rerun, or merge.
