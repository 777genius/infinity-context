# Lifecycle L2 code review — core owner

Reviewed arch-repositories HEAD `48e91379` against approved L1 base `72df6f13` and evidence `fd067180`. Inspected all five capability owners, the29-line explicit compatibility facade, UoW import-only change, pinned contract correction and audit mechanics. Independently ran bounded audit: **9 original bodies/bindings/aliases/hints and same-session lifetime verified**.

Decision: **source approved; no blocking finding**. Mandatory root PostgreSQL and shared integration evidence remain merge gates.

The six classes/keyword SQL retain exact AST bodies, session/lock/mapper/batching bindings and old reference-pickle paths. Documents and chunks share one owner for their canonical evidence/parent-lock capability; other repositories remain separate concrete capabilities without a common framework. UoW changes only its import targets. Outbox/idempotency stay aliases to record repositories. No reverse facade import or new commit/transaction owner appears.

Reviewed the four fixture `func` correction sites: the old capture contained a process-specific SQLAlchemy `_FunctionGenerator` memory address; the new description is accepted only when the object `is sqlalchemy.func`. Original repositories import that exact singleton directly from SQLAlchemy. This strengthens provenance identity across processes; no source body, SQL value, hint, old pickle or behavioral expected output was changed. The correction is documented explicitly rather than silently regenerating evidence.

No additional testing expansion or implementation change requested. Preserve exact results/skips for root's mandatory PG repository/replay/document identity gates; local SQLite HTTP/worker results cannot replace them.
