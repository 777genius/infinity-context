# Immutable retrieval-intent ownership oracle

Captured against unchanged production at base
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` before the benchmark ownership move.
The generator refuses capture if the original policy source differs from that base blob.

`cases.json.gz` losslessly preserves complete intent fields, ordered diagnostics and query profiles for
326 real test questions across five benchmark categories (1,630 consumer cases). Coverage
includes all 31 configured relation facets plus temporal and visual facets. `roles.json`
independently covers every evidence-need role and benchmark-category branch; `times.json`
covers time-kind precedence; `risks.json` covers entity/expansion/query breadth boundaries.

`ownership.json` pins each original namespace binding, exact final owner, visibility,
signature/docstring/evaluated annotation, and actual callable/property global binding.
`contract.json` preserves public names, registry order and historical DTO/function pickles.
The case payload uses deterministic gzip (`mtime=0`); its decompressed SHA-256 is pinned in
`contract.json` and checked before replay. Compression changes no inputs or expected outputs.

Capture procedure: `scripts/freeze_benchmark_retrieval_intent.py --base-sha <above SHA>
--output tests/fixtures/benchmark_retrieval_intent` with this repository's package paths.
The committed expectations are not regenerated from relocated production to fix failures.
