# Round 1 lifecycle plan critique — runtime owner

Reviewed lifecycle-plan.md, actual UoW/repository definitions, package lazy exports, schema callers,
focused schema/batching tests and accepted canonical-boundary ADRs at
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. Read-only; no tests/source changes.
Decision: **revise before round 2**, with both architectural directions supported.

## Verified architectural value

L1 separates schema/bootstrap compatibility from per-transaction UoW ownership. These have
different lifecycle/release reasons to change despite the present file being just below 1,000 LOC.
The proposed dependency direction is appropriate: UoW -> schema runtime -> compatibility helpers,
never a runtime schema owner importing UoW. Keeping PostgreSQL migration dispatch lazy and
preserving the ordered SQLite legacy bootstrap avoids expanding this into a migration redesign.
The ledger matches the actual `_ensure_runtime_schema` order, including the non-obvious fairness
index nested in duplicate-suggestion expiry. Engine/session/UoW methods remain unchanged.

L2 assigns actual repository capability owners rather than wiring unfinished feature placeholders.
Documents/chunks remain cohesive because they share canonical source/evidence/parent locking and
deletion. Anchor/capture/suggestion/episode repositories have distinct APIs and can be independent
owners without a base-class framework. Direct UoW construction from those owners plus old class
aliases preserves a clean composition boundary. Existing no-commit/session lifetime guarantees
are stated correctly. Serializing both changes to UoW is prudent.

## Required plan fixes

### L-C1 — source AST equivalence must include executable global-binding proof

Both slices rely heavily on exact moved body/AST comparison. The bodies resolve imported helpers,
ORM rows, mappers, SQLAlchemy functions and constants through their defining module globals.
Moving an AST unchanged but missing or rebinding one of those globals still changes behavior.
Examples include runtime `_column_names`/`load_schema_metadata`/benchmark writer statements and
repository `lock_document_deletion_evidence`, mapper and SQL construction helpers. Aliasing an
export in the facade does not prove the moved callable uses the intended owner at execution time.

Required addition: name a bounded pre-source audit artifact/script and final-owner manifest for
all moved functions/classes/constants. Inventory each moved callable's loaded free globals against
its original binding and require final bound identity/value equivalence (allow only documented
module ownership changes). For class methods include annotation resolution and constructor
session contracts. Verify there is one implementation per moved definition and no hidden reverse
UoW/repository dependency. Add an executable schema operation-order trace against the real callback
using a recording/fake connection or prove an existing test observes the full ordered bootstrap.
This complements existing SQLite behavioral tests; it need not duplicate every SQL statement in
new brittle snapshots or provision a live database for a mechanical relocation.

### L-C2 — define repository class metadata and historical class-reference compatibility

L1 explicitly permits moved functions to gain canonical modules. L2 says class objects are identical
between old/new imports but does not state that moving the class definitions changes their
`__module__` from `.repositories` to the new capability owners. There is no way to preserve both
the old module metadata and natural new ownership without a deliberate policy. Alias identity
alone does not document that choice.

Required addition: declare canonical class/function module changes, unchanged names/qualnames,
signatures/defaults/hints/docstrings, and an explicit complete compatibility export inventory.
Capture old class-reference pickles and representative top-level function references before the
move; these are safe and meaningful even though live AsyncSession repository instances need not
be pickleable. Verify old pickles resolve to the exact new canonical objects through old aliases
in fresh interpreters. Include newly defined owner imports and old package/module order in the
cycle test. Do not expand arbitrary private-global monkeypatch forwarding into an API promise.

## Advisory validation notes

* Actual `tests/unit/test_postgres_benchmark_run_repository.py` imports UoW benchmark error helpers.
  Include it explicitly in L1 focused gates or document why the current benchmark-writer suite
  fully substitutes its wrapped-driver/cause behavior; it is cheap and directly relevant.
* The document/fact PostgreSQL race suites are relevant regression evidence when a configured DSN
  already exists (`test_document_delete_fact_concurrency_postgres.py`,
  `test_multi_document_fact_deletion_postgres.py`, `test_fact_source_ref_completeness_postgres.py`).
  They need not block a body/global-equivalent relocation when no DSN exists, and skipping them
  must not be described as concurrency proof. The plan already states this distinction correctly.
* `_ensure_runtime_schema` alias identity should be checked against
  `create_schema.__globals__["_ensure_runtime_schema"]`, not merely equality of two imports;
  otherwise a stale callback binding could pass the check. The text intends this; make it executable.
* Keep PostgreSQL's local `upgrade_schema` import in the moved create_schema branch exactly lazy.
  Schema registry and existing installer imports inspected here do not require a reverse UoW edge.

After concrete binding/metadata evidence is added, these are feasible bounded slices with useful
SRP/Clean Architecture value, appropriate local HTTP/worker composition proof, and no ADR relaxation.
