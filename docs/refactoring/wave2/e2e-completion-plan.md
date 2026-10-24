# Complete multimodal E2E acceptance with fair worker claims

## Observed failure

The real optional Docling run on the combined refactoring candidate
`6fce8875ec8e0c2e13a8560cb312557bd67261ef` completed three tests successfully and
failed `test_multimodal_asset_memory_acceptance_flow`. The second asset still had
status `pending` after one worker invocation.

Inspection of the retained SQLite database showed the first extraction outbox
row as `done` and the other four as `pending`. All five extraction jobs shared
the same scope fairness key. The worker deliberately excludes jobs with an
earlier active predecessor on the same key, and `--once` processes one claim
cycle. Its `--limit 20` limits the batch size; it does not drain subsequent
same-key jobs.

Both this test and `infinity_context_server/worker.py` were unchanged between
the pre-wave2 baseline `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` and the failing
combined candidate. This repair keeps the existing worker scheduling contract.

## Plan and two rounds of independent criticism

The proposed change was reviewed before implementation by the
`finish_architecture` and `finish_units` agents (GPT-6.1 Sol, xhigh).

Round 1 required retaining the original five queued uploads, their order, and
every existing outcome assertion. Both critics rejected an unbounded drain or
retry loop as unnecessary: the test knows that it has queued five same-key
extraction jobs. Each next asset must be processed by the next fair claim, and a
wrong ordering must still fail the per-asset assertion.

Round 2 approved this precise implementation:

1. Keep all five uploads queued before verification starts.
2. Move the existing worker subprocess block to the beginning of each existing
   ordered `(case, extraction_id)` verification iteration.
3. Keep the command, environment, `--once`, `--limit 20`, 180-second per-process
   timeout, captured output, and return-code assertion unchanged.
4. Keep all status, artifact, extracted-text, modality, reason-code, link, and
   anchor assertions unchanged.
5. Add a brief explanation of the fair claim cycle. Add no retry, sleep,
   polling helper, production change, or scheduling bypass.

## Verification and publication

The change belongs in a dedicated E2E pull request. Independent code review
follows the committed implementation and all findings are fixed before merge.

Required runtime evidence is the exact previously failing test against the
combined refactoring source plus this test-only change, using real Docling,
model assets, and ffmpeg. The separate environment resolves the repository's
unchanged lockfile, including Docling 2.102.1 and Torch 2.12.0.

The three previously passing Docling tests may be reused only with unchanged
production, build/configuration, and relevant test blobs. Report unique tests
and the corrected retry separately instead of adding overlapping run counts.

At the implementation commit, Ruff and whitespace validation pass. Runtime
acceptance and final review results will be recorded after they complete.
