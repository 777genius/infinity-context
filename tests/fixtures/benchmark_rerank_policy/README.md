# Immutable benchmark scoring ownership evidence

Captured before production changes from original scoring modules at
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`, in the independently reviewed R1 integration branch.
The generator refuses changed production and refuses overwriting an existing output directory.

The capture ran 100 existing candidate score/source-grounding/evidence tests while recording real
feature inputs and complete score, contribution and signal outputs. Explicit threshold, boolean,
rounding, unmeasured-locality and grounding vectors extend this to 213 unique cases. All fifteen
policies are also frozen individually with their exact ordered default registry. Three complete
real rerank consumer examples preserve memory fields, ties, diagnostics and metadata.

`cases.json.gz` is lossless deterministic gzip (`mtime=0`); its decompressed SHA-256 is pinned in
`contract.json`. `ownership.json` records each original symbol's final owner, original source and
AST hashes, supported namespace, signatures/docstrings/evaluated hints and actual free globals.
Contract data includes historical class/function references and DTO instance pickles.

All five duplicated helpers have equal arithmetic bodies and original runtime global bindings.
Four concrete/protocol feature annotations differ; their declared typed compatibility delegates
preserve that difference while one canonical body owns computation. Only `_rounded_boosts` has
an identical contract suitable for a direct shared alias. No expected behavior was regenerated
from moved production.
