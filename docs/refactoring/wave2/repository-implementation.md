# Canonical repository ownership — L2 implementation evidence

L2 was released by the coordinator after two independent critics completed two plan rounds.
It is a separate branch/PR based on L1 commit `72df6f13`; only the approved repository partition
is implemented here. The plan and its reviews are in the neighboring lifecycle documents.

## Before production changes

The bounded shared executable audit (348 LOC) records all six repository classes, the keyword
SQL helper, and the existing outbox/idempotency compatibility aliases. Its frozen L2 contract
pins the original source at `b0b87bd7` and checkout base at `72df6f13`, complete class/function
ASTs, final owners, method/global bindings, signatures/defaults/evaluated hints, docstrings and
legacy reference pickles. The UoW check proves one session and one captured clock value. L1
audit remains valid; its comparison explicitly recognizes the seven approved L2 dependency
module relocations, while actual live identity checks still require each canonical object.

The approved focused repository/API suite passed against unchanged L2 production:
**91 passed, 1 skipped in 65.38s**. The skip is the optional PostgreSQL trigram-plan case because
this invocation did not take the shared Postgres DSN. One existing Starlette/httpx deprecation
warning remains. Coordinator reserves PostgreSQL for the broader baseline E2E; mandatory
post-change real-PG acceptance will run when it is available.

## Production partition and audit

`repositories.py` becomes a **29-line** explicit compatibility facade (was 988). Complete classes
move without body/signature/SQL changes to document/chunk (**556 LOC**), anchor (**121**), episode
(**60**), capture (**132**) and suggestion (**182**) owners. UoW changes only imports, passing
the same session to every owner. Outbox/idempotency implementations remain unchanged.

The L2 executable audit verifies all nine definition bodies/contracts/aliases/old reference
pickles, fresh import orders and session/clock behavior. Inherited L1 audit remains applicable.
Repository Ruff, pinned L1-base monotonic file-size gate (**102 unchanged ceilings**) and diff
whitespace checks pass. Post-change focused/HTTP/worker, full architecture, mandatory PostgreSQL
and independent code reviews are still pending at this checkpoint.

The first cross-process L2 check exposed one audit serialization defect: four method-global
entries described SQLAlchemy's `func` singleton by a repr containing a process memory address.
Their provenance fields alone now name the exact `sqlalchemy.func` singleton and the audit
requires identity with that object. Original binding was independently checked in the unchanged
`arch-lifecycle` repository namespace at `72df6f13`; all six classes share that original namespace.
The correction is recorded in the fixture metadata. No AST, global inventory, signature/hint,
pickle or behavior output was regenerated or changed to match moved production.

## L2 final acceptance

The post-change focused repository/API suite plus real HTTP/worker E2E passed **92 tests in
54.21s**, with one initially skipped DSN-gated trigram case and the existing Starlette/httpx
deprecation warning. Full architecture passed **219 tests in 69.61s**. The exact audit verifies
all nine L2 bodies/bindings/aliases/hints/reference pickles and the same-session/one-clock
contract; the inherited L1 audit also passes all 31 definitions and actual callback ordering.

With the isolated official PostgreSQL 18.6 DSN, all four required repository/CodeScope, concurrent
review replay and ordinary/managed document-identity cases passed. The separately executed
trigram-plan/scalar-batch case also passed, covering the earlier skip: **5 passed in 15.29s**,
no skips. The direct trigram case exercises the relocated keyword SQL and canonical hydration
semantics on actual PostgreSQL.

Both independent implementation reviewers approved source commit `48e91379` without blockers,
inspected unchanged SQL/locks/mapping/error behavior and the four-field singleton-provenance
correction, and independently reran the live audit. Their reports are under
`reviews/review-code-l2-by-{core,runtime}.md`. Repository-wide Ruff, diff whitespace and exact
base-ref monotonic size checks pass; all **102** existing ceilings remain unchanged. All L2
acceptance gates are complete. Coordinator owns publication, combined verification and merge.
