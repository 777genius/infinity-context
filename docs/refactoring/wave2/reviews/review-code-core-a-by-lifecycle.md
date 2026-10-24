# Core-A implementation review — lifecycle owner

Reviewed actual source commit `e4ce8443` and final contract-test correction `3f64371c` in
`arch-core`, against the immutable pre-source evidence and twice-approved plan. Decision:
**approved; the one discovered blocker is fixed and independently verified**.

## Source and architectural review

Inspected the bounded owners, 942-line compatibility facade, retained batch orchestration,
explicit lexical/relevance/normalization callback plumbing, shared cached facade query terms,
DTO alias metadata, richer plan-aware selector versus basic canonical selector, direct dedupe
consumer, and the transitive facade/artifact dependency guard. Existing shadow modules are
reconciled to current-main behavior rather than substituted blindly. No generic registry,
mutable global forwarding, unsupported provider dependency or accepted ADR change was found.

Independently ran `scripts/check_context_ranking_ownership.py` with explicit worktree core/tests
paths: **127 original callable bodies and 267 actual global bindings verified**. I reviewed its
callback/name normalization against the actual thin delegates and propagated relevance callbacks,
including source-quote and citation paths. Its comparisons are supported by the immutable full
670-case output/identity corpus and actual consumer tests rather than used as the sole proof.

The basic query selector keeps its distinct real canonical-fact use; strict false-friend/visual/
count plan-aware logic is separately named. Dedupe source-body and role merge, requirement typed
unit policy, rank fusion, malformed diagnostics and deterministic normalization retain current
behavior. One coverage DTO is canonical with the previously approved private name/module/new
pickle policy; old references and values remain supported.

## Discovered and resolved blocker

The new contract test initially imported `context_ranking_contract_support` as a bare module.
Standard pytest could not collect it because repository `pythonpath` includes the repository
root and packages, not `tests/`; the owner's explicit path setup masked this test dependency.
I reproduced `ModuleNotFoundError` in an isolated standard invocation and requested a package
import. Commit `3f64371c` now uses `tests.context_ranking_contract_support`; production and
frozen oracle bytes are unchanged.

Independently reran with **PYTHONPATH unset**: pinned original contract, one complete frozen case,
all six historical private DTO pickle cases, and all local ownership/DAG guards:
**11 passed in 2.79s**. Owner additionally reports the full contract/direct canonical/direct
paired-dedupe invocation under the same standard environment: **825 passed in 8.73s**. The
previous collection blocker is closed. No remaining substantive finding.

The owner's broader 1147 focused and 639 integration results, exact shared size ratchet and
root-owned combined eval/process evidence remain separately reported acceptance gates. This
review does not claim I reran those complete suites. Publication/merge remain root-owned.
