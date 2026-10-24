# Multimodal E2E completion acceptance

Status: **accepted on the final composed production candidate**. Reviewed test source is
`65bd882e3a5c076d8fcf52dd3e9d2b2dd71b55a2`; its test and plan remain the only implementation
changes in this focused direction. This record and the two code-review summaries add documentation only.

## Cause and preserved behavior

The initial genuine optional Docling run returned three passes and one failure: the second of
five queued same-scope assets was still pending after one `--once` worker invocation. Retained
canonical state showed the first extraction complete and four pending. The existing worker
claims only the first active job per fairness key in each cycle; its `--limit 20` is a batch
ceiling. This worker and the original test were unchanged from the pre-wave-two baseline.

The repair moves the original worker subprocess block into the existing ordered per-asset
verification loop. All five uploads stay queued first. Command, environment, `--once`, limit,
180-second per-process timeout, captured diagnostics, and every existing success/artifact/text/
modality/reason/link/anchor assertion are unchanged. There is no retry, drain loop, sleep, new
helper, fairness change or production change in this PR.

Both independent critics reviewed two plan rounds and the exact committed implementation.
The architecture reviewer separately proved subprocess/assertion AST identity and unchanged
production worker bytes. The unit reviewer reversed the relocation and proved complete original
file AST equality. Their source-stage reports are retained alongside this acceptance record;
they do not imply runtime results before those results were executed.

## Actual final runtime proof

The exact corrected multimodal node and the directly affected structured-artifact HTTP node ran
serially with actual Docling 2.102.1, cached real models, ffmpeg/ffprobe, the locked dedicated
Python environment, CPU/single-thread settings and normal pytest file-descriptor capture.
Existing per-process timeouts and provider-disabled test settings remained intact. Heavy
LongMemEval and the controlled unit repeat were not overlapped with ML initialization.

Executed combined HEAD: `b230f59bc2643605b777cb253d0122c188b12cd8`.
Executed combined tree: `7f77f9be4822e2b147b6b3e24f64f3c1c69c9a07`.
It contains the reviewed heartbeat persistence and managed replay corrections as well as this
exact test change, so the affected HTTP paths were validated against the final production behavior.

**2 passed in 168.15 seconds**, with zero failure, error or skip. The corrected five-asset
multimodal node took 134.273 seconds. Wrapper elapsed time was
169.277 seconds. Candidate source and frozen main `6fce8875ec8e0c2e13a8560cb312557bd67261ef` remained clean and unchanged before/after execution.

A separate post-run read-only canonical inspection confirmed all **five** multimodal extraction
jobs succeeded and their five `asset.extract` outbox jobs were done. The structured-artifact
node likewise left one succeeded extraction and one done extraction outbox job. Test success
also includes every original artifact, text and evidence-link assertion, rather than only these counts.

## Honest coverage accounting and retained evidence

The original strict PDF fixture check and direct real Docling extraction test remain two prior
passes with their original source provenance. The reuse map proves 24 complete file blobs and
eight exercised extraction DTO/protocol definitions unchanged. It explicitly records two
containing-module differences limited to unused repository-progress/helper declarations instead
of claiming those whole module blobs are identical. The HTTP extraction node was rerun because
its persistence/ingestion path changed. Thus the combined Docling evidence covers **four distinct
pytest nodes: two retained pure tests and two final affected tests**. Earlier three-pass and
new two-pass counts are not added as five unique nodes; five asset cases belong to one node.

Coordinator evidence retains full logs, JUnit, source/command/environment metadata, resource
clearance snapshots, final canonical counts and the reuse map:
`e2e-corrected-docling.*`, `e2e-corrected-docling-final-state.json`, and
`docling-pure-tests-reuse-map.json` under `evidence/wave2/`.
Log SHA-256: `31ad01f36444ff8014a29e128df64b103578fb015b2f9bb5c8ee4a141b9554cc`.
JUnit SHA-256: `14e814b5bb23062d7b979163f852cc1fc04e4489daa79922f458d9d0de1531d2`.
The original failing run remains preserved as `e2e-final-docling.*`.

The ML wrapper exited successfully and released the next heavy gate immediately. Full official
LongMemEval and other independent service gates remain separate coordinator acceptance records.
