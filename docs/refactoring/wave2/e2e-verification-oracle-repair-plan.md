# E2E verification-oracle repairs — plan v2

## Scope and source

Frozen broad acceptance source: `6fce8875ec8e0c2e13a8560cb312557bd67261ef`.
This direction repairs two pre-existing test-harness/oracle defects exposed by genuine
official-data PostgreSQL E2E execution. It changes **only two E2E test files**, in a separate
worktree and focused PR based on published `35ea68be`; validation uses a separate combined
tree containing frozen `6fce8875` plus only this test delta. No production code, database migrations, immutable fixture bytes,
identity/fence/security checks, accepted architecture, or source data will change.

## Causal evidence

1. `test_strict_v4_cleanup_derivation_postgres.py` deliberately poisons the canonical
   `registered_at` year. Recovery first re-registers/readbacks the context authority; the
   existing registry rejects the altered canonical registration with
   `projection_receipt.context_authority_collision`. The test incorrectly expects a later
   `preparation_registration_invalid` boundary that cannot be reached. Both source and test
   are byte-identical to pre-refactor `b0b87bd7`; the existing fail-closed guard is correct.
2. `test_strict_v4_writer_authority_adapter_postgres.py` completes initial sealing, genuine
   5,882-fact ingestion, exact replay and canonical row counts. Its later adversarial
   function-owner roundtrip in `_assert_multirole_canonical_rejected` restores ownership but
   omits the original canonical-writer EXECUTE grant. PostgreSQL's ACL owner rewrite merges
   that grant with the temporary owner's implicit rights; restoring ownership therefore
   leaves the accepted baseline topology damaged. The unchanged production topology guard
   correctly raises `projection_receipt.writer_fence_invalid` on the subsequent replay.
   The adjacent table-owner fixture already restores its explicit grants.

Evidence: `evidence/wave2/e2e-final-pg18-full.{log,xml}`,
`evidence/wave2/e2e-final-initial-failure-skip-details.json`, and
`plans/wave2/writer-adapter-failure-diagnosis.md`.

## Exact implementation

- In `tests/e2e/test_strict_v4_cleanup_derivation_postgres.py`, change only the poisoned
  registration assertion's regex to the anchored exact existing reason
  `r"^projection_receipt\.context_authority_collision$"`.
  Keep `ProjectionReceiptError`, timestamp poisoning/restoration, writer-MAC tampering,
  missing-writer checks, final recovery-call count, full official LoCoMo data and all other
  assertions. Add a short explanatory comment at the assertion if helpful.
- In `tests/e2e/test_strict_v4_writer_authority_adapter_postgres.py`, extend the existing
  `finally` ownership restoration with the exact existing
  `key == "function-capability-owner"` case, not a grant for arbitrary functions. After restoring the
  function's original owner, restore only the existing baseline privilege:
  `GRANT EXECUTE ON FUNCTION public.memory_comparison_is_strict_v4_canonical_writer()
  TO infinity_context_canonical_writer`.
  This restores the original **non-grantable** EXECUTE privilege. Keep the adversarial owner
  change and rejection assertion intact. Do not grant PUBLIC,
  registrar, sealer, or any additional privilege, and do not change the topology checker.

## Validation and sequencing

1. Obtain two independent plan critiques in round 1, record dispositions, then obtain both
   round-2 approvals before implementation.
2. Use an isolated worktree; the coordinator-owned main source remains frozen. Confirm a
   two-test-file-only delta, `git diff --check`, Ruff, and the 1,000-line file cap.
3. Before expensive official-data replay, use a small task-owned PostgreSQL 18 database to
   verify catalog behavior using the actual migrated function and unchanged production
   topology checker. Capture the owner and full sorted semantic `aclexplode` rows before
   perturbation, including **owner, grantor, grantee, privilege type and is_grantable**.
   Demonstrate that the uncorrected owner-only roundtrip loses canonical EXECUTE and the
   unchanged topology checker rejects it. Apply the proposed exact cleanup; require full
   owner/semantic-ACL equality to the original baseline and a passing unchanged topology
   checker. Explicitly prove no PUBLIC, registrar or sealer EXECUTE grants are added and
   canonical EXECUTE remains non-grantable. Use only task-owned database objects and the
   established existing capability roles; do not mutate shared role attributes/memberships,
   another database, or cluster configuration. Record catalog proof before expensive replay.
4. Run both exact original full-data E2E selectors with standard fd capture, real task-owned
   PostgreSQL 18 in UTC, exact official LoCoMo bytes and fresh database isolation. Retain
   JUnit, source HEAD, command and logs. No cache injection, sampled corpus, skipped
   assertion, or identity/security-guard relaxation is permitted.
5. Obtain two independent code reviews, resolve findings, then provide the focused commit
   and evidence for root-owned publication/integration. Keep this direction separate from
   the Docling worker-cycle test repair and production heartbeat/replay fixes.

## Stop conditions

Stop and return to the coordinator if the production registry/topology behavior must change,
the intended baseline ACL cannot be proved from existing migrations and catalog state, or a
full-data rerun exposes a separate failure. Do not broaden exception matching to cover new
failures, remove a tamper case, suppress a rejection, or alter data/identity guards.

## Review state

Both round-1 critiques accepted the two-test-only direction and requested precise anchored
error matching, full semantic ACL equality and unchanged topology verification. Plan v2
incorporates all requests and is submitted to both critics for round-2 approval. Implementation
has not started.
