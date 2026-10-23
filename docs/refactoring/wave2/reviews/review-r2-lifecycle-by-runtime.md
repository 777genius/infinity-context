# Round 2 lifecycle plan critique — runtime owner

Reviewed revised `lifecycle-plan.md` against actual UoW/repository/schema callback sources and
direct tests inspected in round 1. No source edits or tests. Base:
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.

## L1 — approved

L-C1 is resolved: a named bounded executable audit and pinned `l1_contract.json` manifest cover
source definition -> final owner, supported namespace, original loaded globals, live post-move
binding identities/provenance, constant alias identity, evaluated annotations and old reference
pickles. The fifteen-step schema bootstrap is captured by executing the actual callback with
test-only recording globals, including the real metadata create_all position. The callback check
uses `create_schema.__globals__["_ensure_runtime_schema"]` so comparing two stale facade imports
cannot conceal an incorrect execution binding. Reverse UoW/repository imports are rejected.

The directly relevant benchmark repository error-helper test is added. Existing exact SQLite
upgrade/idempotent singleton and real HTTP/worker gates remain, with root-provisioned PostgreSQL
clean/legacy upgrade and writer-fence checks added as actual mandatory results when the DSN is
provided. Missing-DSN skips are not represented as successful PG evidence.

## L2 — approved

L-C1/C2 are resolved: the same audit's L2 manifest covers every moved class/method/helper's live
SQLAlchemy/ORM/mapper/lock/batching bindings, evaluated annotations, exact AST/SQL bodies, old/new
alias and import-order checks, shared UoW session/clock contract, and reverse-facade import absence.
Repository classes naturally acquire their new canonical owner modules while names/qualnames,
signatures/defaults/docstrings and evaluated hints stay preserved. Historical class/function
reference pickles are frozen and decode through explicit old aliases to canonical objects.
No session-instance pickle promise or unsupported global monkeypatch forwarding is introduced.

The direct focused tests and real upload/worker composition evidence are appropriate for the
relocation, and the four root-provisioned PG cases strengthen canonical evidence without changing
SQL/persistence policy. Exact bodies/global bindings plus existing application tests remain the
primary behavior proof; no newly designed repository framework or dormant feature placeholder is
introduced. Both slices provide actual SRP value despite the original files being below 1,000 LOC.

No unresolved blocking finding. Approval remains scoped to the stated ownership and exact
behavior preservation; a changed query/lock/transaction contract requires re-review. Root release,
pre-source evidence and independent implementation review are still required.
