# E2E verification-oracle repair — plan review record

Source baseline for focused PR: `35ea68beab8407995a45683d9592c052f65ed7f4`.
Combined acceptance source before these test repairs: `6fce8875ec8e0c2e13a8560cb312557bd67261ef`.

## Two independent critics, two plan rounds

| Critic | Round 1 | Round 2 |
| --- | --- | --- |
| Root coordinator | Accepted direction; required an anchored exact collision message, complete normalized semantic ACL/owner comparison, unchanged topology proof, and a specific function-only cleanup branch. | Approved plan v2 with no outstanding conditions beyond the recorded validation gates. |
| Architecture reviewer | Accepted two-test-only direction; required exact earlier error boundary, original non-grantable canonical EXECUTE restoration, full ACL/owner equality and topology reject-before/pass-after proof using only task-owned objects. | Independently approved plan v2; no blockers. |

## Dispositions incorporated in v2

- The poisoned-registration assertion will match only `^projection_receipt\.context_authority_collision$`, preserving the exception class, poisoning/restoration, all other tamper assertions and all four recovery calls.
- The ownership cleanup will use only the existing `function-capability-owner` case, after restoring the original owner. It will restore the original canonical EXECUTE privilege without grant option; no PUBLIC, registrar, sealer, arbitrary function or production guard change is permitted.
- The minimal PostgreSQL proof must compare owner and sorted `aclexplode` rows including grantor, grantee, privilege type and grantability. It must show the broken owner-only roundtrip is rejected, then exact ACL restoration passes the unchanged production topology checker.
- The PR remains two E2E test files plus its plan/review documentation. Actual original full official LoCoMo selectors, all 5,882 canonical ingests/replays and row-count checks remain mandatory.

## State at this commit

Plan v2 and both review dispositions are recorded before implementation. No production or test source has changed in this commit. Implementation, catalog proof, full-data reruns and two independent code reviews follow on this branch. GitHub publication/integration is root-owned.
