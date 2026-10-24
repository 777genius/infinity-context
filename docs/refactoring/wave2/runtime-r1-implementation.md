# Runtime R1: benchmark-owned question intent

## Result

The complete question-only intent policy now belongs to
`infinity_context_benchmarks.retrieval_intent`: contracts, temporal policy, profile/event/comparison
predicates, facet data, relation inference and evidence requirements. The public capsule exposes
four immutable DTOs and six existing inference functions. Internal modules import only stdlib and
their own capsule; the dependency graph is acyclic.

The old server intent module is an explicit compatibility export surface, reduced from 2,925 to
89 lines. Both real consumers import the canonical public API. Their server-owned query-term,
rerank and evidence orchestration remains in place. Functions/classes now have natural canonical
benchmark module metadata; exact old imports, evaluated annotations, properties and historical
DTO/class/function pickles remain supported. There is no dynamic forwarding or copied algorithm.

Ten bounded production modules have a maximum of 587 lines. Source relocation preserves every
original function/class body; facet data retains all 31 entries and their exact iteration order.
The server benchmark debt stays 483 files and decreases from 208,182 to 205,347 lines: 2,835 fewer.
The evidence consumer grows by one required import-group separator (877 -> 878); the oversized
rerank consumer stays 3,209 lines. The original aggregate estimate required nonpositive caller
deltas; this one formatting line is explicitly accepted because the actual aggregate decreases
and no frozen individual ceiling grows. Shared ratchets are committed by the coordinator.

## Immutable evidence

Pre-source evidence was committed before production relocation. It captures 326 real test
questions across five categories, 1,630 complete consumer/policy results, all 31 configured facets
plus temporal/visual facets, every evidence-role/category branch, temporal precedence and risk
boundaries. The ownership manifest records supported namespace, signatures, docstrings, fields,
evaluated annotations and actual function/property global bindings. Legacy references and DTO
instances are recorded as pickles from unchanged base
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.

The complete 4,349,419-byte case payload is losslessly stored as deterministic gzip (96,590 bytes,
mtime 0); SHA-256 of decompressed bytes is
`3686c8dde6292e4ee7004685f2dd1d89537d165649f08f9f095348d5db2660c4`.
Replay verifies the hash before reading expected results. Expectations are not regenerated after
source moves. One stdlib-only replay helper serves source tests and isolated installed-wheel
probes without importing server question-term machinery.

## Verification at source-stage commit

* Frozen contract plus all exact affected relation/query-plan/evidence/source-grounding/benchmark
  tests: **377 passed**. The benchmark collector needs the real process namespace, so this exact
  suite ran with escalation after the existing guard rejected the sandbox PID view. No guard changed.
* New ownership DAG/definition guards, complete frozen replay and nested source/installed RECORD
  identity tests: **13 passed**.
* Focused Ruff and `git diff --check`: passed.

The existing five-wheel/three-context harness now replays all 1,630 cases from installed canonical
modules, verifies type hints/legacy aliases/pickles and namespace origins, and requires standalone
server/adapters absence. Execution is coordinated after the root's broad real E2E run. Independent
implementation review, root-owned ratchets and full architecture gate remain release requirements.
