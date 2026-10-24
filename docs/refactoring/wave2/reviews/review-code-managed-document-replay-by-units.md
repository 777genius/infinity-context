# Independent unit-owner review: managed-document replay

This is the coordinator's recorded summary of the independent unit owner's source review, not
an additional runtime-execution claim. The reviewer is separate from the implementation owner.

Decision: **approved, no blocking finding**, at f971807da5cbf39b87125836251c40122b508a0a,
with product b1daf352 unchanged by the test commit.

The reviewer inspected all three production-file changes and the complete 450-line regression
file. Fresh successful admission reaches all three receipt and both duplicate exits, including
the nested recovery's own fresh key and mode. Ordinary modern and legacy policies remain the
default. The managed branch keeps the persisted legacy fingerprint and verifies complete
canonical scope/thread/source/classification, original fragments and owned JSON metadata.
Missing keys, changed array order and scalar-type substitutions cannot compare equal.

The regression design was reviewed for all four successful routes, real uniqueness conflicts,
fresh nested admission denial/key drift, namespace-only rejection, normalized-hash collisions,
sixteen canonical-evidence corruptions, harmless fetch ordering and ordinary legacy
multi-fragment rejection. Stable IDs, row counts and steady-state read-only replay are asserted.

The reviewer independently compared all three moved helper definitions to the original 35ea68be
ASTs, including loaded names. Every body is identical; dependencies remain builtins and direct
aliases to the same moved helpers. No duplicated implementation or new provider dependency
was introduced.

No additional pytest process was launched by this reviewer during the shared-memory investigation.
The coordinator's committed 77-test gate, authentic pre-fix regression failure, and subsequent
full original LongMemEval and affected Docling executions provide the separately source-bound
runtime evidence. Those actual results are recorded in the acceptance documents.

## Historical scope and final follow-up

The approval above concerns the initial f971807 source. Subsequent CI and a local original PG test found the HTTP 409-to-500 regression; this history remains explicit. The unit critic separately approved the twice-reviewed ce661578 one-raise correction, its 80 focused passes, the original clean 437796a5 PostgreSQL two-node pass, fresh read-only recovery and source-qualified heavy-gate reuse. The exact final record is [the HTTP conflict review](review-code-managed-replay-http-conflict-by-units.md).
