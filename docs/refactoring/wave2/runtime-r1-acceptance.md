# R1 final review and acceptance

Source head: `89e2a7ade9104561f63193f93fa5369d4e76da89`.

Two independent GPT-6.1 Sol xhigh agents reviewed the implementation after the two-round plan review. Their full reports are in `reviews/review-code-runtime-r1-by-core.md` and `reviews/review-code-runtime-r1-by-lifecycle.md`. These are agent review records, not separate human GitHub approvals.

The core reviewer identified a missing installed real-consumer check. The final wheel probe now invokes installed `query_retrieval_intent` for all 1,630 frozen inputs in both server and bundle installations, compares complete intent/profile/diagnostics, and checks every loaded Infinity module originates inside the installation. Both reviewers approved the correction.

## Executed release gates

- 377 affected behavior tests passed.
- 13 ownership, frozen-contract and runtime-identity tests passed.
- Full architecture suite: 221 passed.
- Source audit: all 49 relocated original class/function ASTs match.
- Five actual wheels built and installed in three isolated `python -I -S` contexts: standalone benchmarks, server, and bundle. Every context passed the frozen replay, legacy references/pickles, type and namespace-origin checks. Standalone requires server and adapters absence. Server and bundle additionally execute the real installed consumer.
- Focused Ruff, diff whitespace and exact file-size ratchets passed.

The server benchmark line budget falls from 208,182 to 205,347 with the file cap unchanged at 483. The 2,925-line legacy intent exception is removed, leaving 101 frozen oversized exceptions at this slice. No accepted ADR, process identity or installed RECORD guard was changed.

The wheel harness used the preinstalled build interpreter because the project's frozen dependency venv intentionally has no pip. Its report SHA-256 is `bc49936a966cd42b1f16aeea2c92c01018174bb47352328cadcf7a68c74710cc`. The local source-tree tests and wheel checks are executed evidence; this document does not claim a completed GitHub Actions run.
