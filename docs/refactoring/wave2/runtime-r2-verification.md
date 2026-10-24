# R2 verification and Python compatibility

The complete scoring capsule is published in PR #99. It moves the unchanged scoring bodies and DTOs into nine bounded benchmark modules, preserving explicit old imports and four typed delegates where protocol/concrete annotations differ. The server score/policy facades contain 39/97 lines; the largest new owner has 623 lines. Exact debt is 483 server benchmark files and 203,082 lines.

## Immutable behavior evidence

The original 213 frozen score vectors remain byte-identical to the before-source evidence. Another 28 activation/boundary vectors were obtained from a separate interpreter against the retained original source, with loaded paths, source hashes and actual globals checked. Together all 241 vectors activate all 15 policies; three complete real consumer/tie outcomes are frozen too. No expectation was generated from moved production to repair a failure.

Two independent implementation reviewers approved the source before the execution filesystem reset. They inspected 84 complete original definitions, four explicit typed delegates, aliases, type hints, historical references, global bindings and the actual installed-consumer probe. Their conclusions are retained in the session record; this document does not recreate missing verbatim review files. The prior focused acceptance covered 444 distinct tests across an initial run and a bounded 306-test rerun after temporary-storage exhaustion, plus 222 architecture tests. Those are historical executions, not a claim that the final combined tree has already passed.

## Resolved hosted CI finding

GitHub Actions run 40024650602, job 120677635219, found one verification failure on Python 3.13.5; the job otherwise passed 1,616 tests and skipped seven. Python's AST dump omitted empty list fields while the immutable fingerprints use the Python 3.12 format. The bad hash was reproduced exactly from the unchanged class AST.

Commit d593ae82 changes only the shared inventory serializer, its freezer call sites and the matching ownership assertion. It explicitly retains empty fields on Python 3.13 and reconstructs absent empty generic-parameter fields on copied Python 3.11 nodes. It leaves input nodes, global AST schemas, all production packages and all frozen fixtures unchanged.

All 84 original fingerprints were independently matched under actual isolated Python 3.11.15, 3.12.14 and 3.13.5 interpreters. The seven focused scoring contracts and changed-file Ruff passed. The independent review is in reviews/review-ci-ast-fix-by-architecture.md; no finding remains in that delta.

Final full unit, E2E, seven-suite deterministic comparison and actual five-wheel/three-context installation acceptance are coordinated on one combined, frozen source tree before merge. This record does not substitute a source-layout probe for installed-wheel proof.
