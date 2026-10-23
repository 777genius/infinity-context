# Runtime R2: complete benchmark candidate scoring owner

## Result

`infinity_context_benchmarks.rerank_policy` owns the complete provider-free candidate scorer:
feature/protocol and result/contribution contracts, grounding/common primitives, evidence,
temporal, intent, answer-shape and typed relation policies, ordered composition and final caps.
All nine modules import only stdlib and their own acyclic capsule. The largest is 623 lines.

The old score module shrinks from 675 to 39 lines; the old contribution-policy module shrinks
from 1,726 to 97. Both are explicit compatibility exports. The actual rerank consumer imports the
canonical public API and stays 3,209 lines. Server benchmark debt stays 483 files and decreases
from 205,347 to 203,082 lines, a further reduction of 2,265. The policy oversized-file entry can
be removed; the coordinator owns exact shared ratchets and installation/integration gates.

Five duplicated helpers now have one computational body each. Their original arithmetic and
actual global bindings were proven equal before moving source. Four feature parameter annotations
were intentionally different (concrete DTO versus protocol), so canonical scoring retains tiny
typed delegates with those original signatures, and both old modules expose exact corresponding
aliases. `_rounded_boosts` has an identical contract and is one direct alias. Tests require typed
delegates to contain only the single canonical call, and original canonical body ASTs stay exact.

Class/function canonical modules change openly; names/qualnames, fields/defaults, docstrings,
evaluated annotations, structural feature input, custom ordered policy injection, empty-sequence
fallback, duplicate signal overwrite and historical imports/pickles stay covered. No scoring
arithmetic, threshold, cap, reason, schema, provider call or engine changed.

## Immutable evidence and supplemental activation proof

Commit `bdb443b9` captured original source before production changes. Its producer ran 100
existing scorer/source-grounding/evidence tests, then froze 213 unique full score/contribution/
signal vectors, all fifteen policies individually and three complete actual rerank/tie results.
The primary case payload is deterministic gzip (55,484 bytes), with decompressed SHA-256 checked
before replay. Ownership evidence records original source/definition AST hashes, complete old
namespaces, actual globals, signatures/hints/docstrings and historical DTO/function pickles.

An activation inventory then found two policies needed additional positive examples. The original
main checkout remained untouched at `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. A separate fresh
interpreter verified original module file origins, both source hashes and the exact original
namespace/global inventory, then captured 28 independent negative-absence/value-shape locality
and broad-summary cases. Commit `7817fd24` records that supplement separately. Original 213 gzip
bytes are unchanged from their evidence commit. The combined 241 cases activate all fifteen
default policies. No expected score was generated from relocated implementation.

The wheel harness replays all primary/supplement scorer outputs in standalone, server and bundle
installs, alongside the existing 1,630 intent outputs. Server/bundle branches also decode legacy
score imports/pickles and replay the three complete installed real-consumer results. Target-only
namespace origin checks run after those imports; standalone server/adapters absence remains required.

## Source-stage verification

* Complete scoring contracts, R1 regression contracts, ownership and nested runtime identity:
  **23 passed**; supplemental scoring replay: **7 passed**.
* Approved affected suite: **420 passed**, with **24 benchmark report tests blocked by ENOSPC**
  during temporary file writes. These are not recorded as passed; a bounded failing-file rerun
  is still required after coordinator storage recovery.
* Focused Ruff and `git diff --check`: passed.

Independent source review, exact shared ratchets, final affected-file rerun, full architecture and
the coordinator's real five-wheel/three-installation proof remain release gates at this checkpoint.
Process-identity guards were preserved; required tests use the real namespace through escalation.
