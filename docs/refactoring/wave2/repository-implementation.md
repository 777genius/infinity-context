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

Production relocation, post-change gates and independent implementation reviews remain pending
at this evidence checkpoint. No behavior output will be regenerated from changed production.
