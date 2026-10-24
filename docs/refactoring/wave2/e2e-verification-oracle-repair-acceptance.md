# E2E verification-oracle repair acceptance

## Reviewed implementation

- Focused branch base: `35ea68beab8407995a45683d9592c052f65ed7f4`.
- Plan and two-round review record committed before implementation: `2b2ea9fc`.
- Exact two-test implementation reviewed by both independent critics:
  `20395a91de23ac151d088c888af8acc71c3d9e15`.
- Root coordinator and architecture reviewer both approved that implementation without
  findings. They inspected the anchored exception boundary, specific function-case cleanup,
  complete semantic ACL proof and unchanged original acceptance assertions.

Only the following test behavior changes:

1. The deliberately poisoned canonical registration must fail at the exact existing
   `projection_receipt.context_authority_collision` boundary. The regex is escaped and
   anchored; the exception class, all other tamper cases, timestamp restoration and four
   recovery calls remain unchanged.
2. The adversarial function-owner test restores the original non-grantable canonical-writer
   EXECUTE privilege after restoring the original function owner. The conditional is the
   existing specific `function-capability-owner` case. No PUBLIC/registrar/sealer privilege,
   production guard, migration, fixture, dataset or runtime behavior changes.

The implementation delta is two E2E files, 12 inserted lines and one deleted line. The files
remain 441 and 927 lines, below the 1,000-line hard cap. Changed-file Ruff and `git diff --check`
passed. Documentation changes record the plan, reviews and this acceptance only.

## Minimal actual PostgreSQL catalog proof

Before the expensive full-data rerun, an isolated task-owned PostgreSQL 18.6 database was
created and migrated using unchanged production schema/topology code. The proof captured
the function owner and sorted semantic ACL rows, including grantor, grantee, privilege type
and grantability.

| Stage | Result |
| --- | --- |
| Original migrated baseline | Original owner and intended non-grantable canonical EXECUTE; unchanged topology checker passed |
| Owner change followed by owner-only restoration | Canonical EXECUTE was lost; unchanged topology checker rejected it with `projection_receipt.writer_fence_invalid` |
| Specific EXECUTE restoration after original owner restoration | Full owner/semantic-ACL equality to the original baseline; unchanged topology checker passed |
| Shared capability-role attributes and memberships | Unchanged |
| Test database | Dropped after proof |

No PUBLIC, registrar or sealer grant was added, and canonical EXECUTE did not acquire grant
option. This verifies fixture cleanup rather than relaxing a production security check.

Coordinator evidence:

- `evidence/wave2/writer-adapter-exact-acl-pg18-proof.json`
- `evidence/wave2/writer-adapter-exact-acl-pg18-proof.log`

## Complete original official-data acceptance

The coordinator's frozen six-refactor source `6fce8875` was combined with exactly this
two-test delta in a separate verification worktree:

- Combined source: `72b20297d41bfb8c74db52be4fb819de1b5bc7b0`.
- Combined tree: `35f93690a62d4cd4e6166d5b69e52bd62d34bf35`.
- Source HEAD/tree and clean status were identical before and after execution.
- Actual task-owned PostgreSQL 18.6, standard fd capture and UTC defaults were used.
- Complete official LoCoMo bytes were unchanged: 2,805,274 bytes, SHA-256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.

Both exact original selectors passed in one sequential run:

```text
tests/e2e/test_strict_v4_cleanup_derivation_postgres.py::test_cleanup_derivation_requires_recovered_and_sealed_evidence_when_configured
tests/e2e/test_strict_v4_writer_authority_adapter_postgres.py::test_real_recovery_seals_postgres_writer_authority_when_configured
2 passed in 348.06s
```

All 5,882 initial fact ingests, all 5,882 exact replays, the ten-corpus result, canonical
scope/thread/fact/version/source-ref/outbox/receipt counts, tamper cases, role separation,
hostile shadows, writer-fence rejection cases and sealed-authority replay assertions remain
in the original tests. No corpus sampling, cache injection, skip weakening or removed
assertion was used. The fixed tests completed their original cleanup successfully.

After the run, a separate catalog snapshot proved the three shared capability roles'
attributes and outbound memberships exactly matched the pre-test baseline, so subsequent
authority checks do not inherit an adversarial role perturbation.

Coordinator evidence:

- `evidence/wave2/e2e-final-verification-oracles-combined.log`
- `evidence/wave2/e2e-final-verification-oracles-combined.xml`
- `evidence/wave2/e2e-final-verification-oracles-combined-metadata.json`
- `evidence/wave2/shared-role-baseline-after-verification.json`

## Accounting boundary

These two passing nodes replace their earlier failed outcomes in the unique E2E matrix;
they are not added to the broad run as extra tests. The initial broader run and all original
failure traces remain preserved. This acceptance concerns the exact combined source above;
root owns final integration and source-reuse accounting for independently reviewed repairs.
