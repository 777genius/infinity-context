# Independent code review: fair multimodal worker cycles

Decision: **APPROVED; no blocking findings.** Reviewed exact commit `65bd882e3a5c076d8fcf52dd3e9d2b2dd71b55a2` against `35ea68be` in the dedicated E2E completion worktree. Only the multimodal acceptance test and its plan/documentation change.

The original single worker subprocess block moves to the beginning of the existing ordered `(case, extraction_id)` verification loop. All five uploads remain queued before any worker cycle. Each cycle retains the exact `--once --limit 20` arguments, environment, text/capture behavior, 180-second timeout, check=False and return-code/stdout/stderr assertion. A brief comment explains the already-existing one-claim-per-fairness-key behavior. There is no retry/drain loop, sleep, helper, scheduling change or production edit.

Independently compared parsed ASTs: the complete original subprocess assignment and failure assertion are identical after relocation; every original per-case success/artifact/text/link/reason/anchor assertion and all other surrounding test statements remain identical and ordered. The five `_FixtureCase` inputs and upload loop are unchanged, so processing the wrong queued asset still fails that case's original success oracles.

The production `worker.py` blob is byte-identical to the base (SHA-256 `2560d5049b03ba1e986194f7cd10c3a8a14fc9652b226bb7cb23afe8a67ad687`). Its existing predecessor filtering and `--once` return behavior justify one bounded invocation per queued case. Compact independent AST/blob evidence is saved in `evidence/wave2/review-e2e-fairness-by-architecture.json`.

Root's real Docling/ffmpeg five-case acceptance rerun remains the required execution evidence; this read-only code review does not claim that test has already passed. Prior passing tests can be reused only where their relevant product/test blobs remain identical.
