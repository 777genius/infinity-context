# Managed document replay completion plan

## Observed failure and scope

The frozen combined E2E run at `6fce8875ec8e0c2e13a8560cb312557bd67261ef`
prepared all 124,344 LongMemEval operations, sealed writer authority, recovered
document authority, and wrote its first authenticated document. Its immediate
idempotent replay failed with `Legacy document source cannot be verified exactly`.
The retained expected index records two fragments and four source references for
operation zero. Managed writes intentionally retain the existing legacy content
digest, while replay sends every such record through the ordinary legacy policy,
which deliberately accepts only one complete fragment. The ingestion, replay and
E2E test source blobs are unchanged from pre-wave-two `b0b87bd7`.

This direction repairs authenticated managed replay. Ordinary modern identity and
conservative ordinary legacy identity remain unchanged. No digest migration,
admission bypass, relaxed authority/receipt guard, shortened corpus, fixture update
or new dependency is proposed.

The same failure was independently reproduced through the existing real SQLite
managed-admission fixture with only its source text changed to five fragments.
This diagnostic is recorded separately from the eventual regression tests.

## Proposed change — round two

1. Keep fresh managed admission before every initial lookup and conflict recovery.
   Return the key tuple and `managed_key is not None` together from the existing
   private key/admission helper. Carry that successful admission result explicitly
   into all three receipt-replay calls and both duplicate lookups. The nested
   conflict-recovery UoW must use its own fresh key and mode. The namespace or
   digest alone is not authority to choose this policy or skip admission.
2. In the bounded legacy application replay adapter, add a separate managed policy:
   require the expected legacy digest, exact canonical document scope/thread,
   normalized title/source identity and classification, and every fragment from
   the original deterministic fragmenter, in order, with exact source text, kind,
   sequence and character spans. Fragment the original `command.text`, retaining
   canonical sorting of repository results: changed/duplicate sequence assignments
   fail, while harmless fetch ordering does not. Missing/extra fragments fail.
   Managed thread identity is exact; ordinary thread fallback stays unchanged.
   Match document title/source strings using the existing write-time stripping
   and classification rules. Keep existing ownership/active-state checks, and
   require managed receipt fingerprints to retain their written legacy digest.
3. Verify projection-owned metadata (`source_refs`, `source_ref_count`, `title`,
   `node_kind`, `heading`, `ordinal_in_heading`) against the same write projection.
   Move the existing three metadata-projection helpers unchanged into one bounded
   application owner, used by ingestion and replay. Retain the old private names
   as direct aliases. This avoids copying source-reference clipping rules or a
   reverse import from replay into its caller. Arbitrary unrelated user metadata
   is outside this identity proof and retains existing JSON storage behavior.
   Compare owned key presence, list ordering and JSON types, using strict canonical
   JSON serialization so `True` cannot equal `1`. Missing fields differ from
   present null/empty fields. Preserve all existing clipping/cardinality rules.
4. Preserve the ordinary modern and legacy branches and all frozen inventories.
   The managed adapter uses existing feature public identity contracts and the
   existing application fragmenter; no feature/domain reverse dependency or new
   public root/application export is introduced.

## Required proof

- A deterministic regression through `IngestDocumentUseCase` reproduces the old
  failure for an admitted multi-fragment document and passes with this repair.
  Replays are read-only: same document/chunk IDs, no extra receipts/outbox rows.
  Preserve the existing duplicate path's legitimate creation of a missing receipt;
  steady-state same-key replay remains fully read-only, and recovery never creates
  extra documents/chunks/outbox rows or duplicate receipts.
- Exercise both direct receipt and content-duplicate/conflict recovery routes.
  Admission must execute on every route and reject changed/unauthorized commands
  before returning stored evidence. Unit doubles are explicitly unit evidence;
  the original full real-PostgreSQL E2E remains the acceptance gate.
- Negative cases cover legacy-hash case/whitespace collisions, missing/extra or
  corrupt fragments, wrong spans/order/kind, source/scope/classification drift,
  and changed owned metadata/source references.
- Existing ordinary document identity/replay/admission tests remain unchanged and
  pass, including an explicit ordinary legacy multi-fragment rejection. Record AST
  identity and referenced helper/global bindings of the moved metadata helpers.
- Ruff, diff/size checks, affected architecture boundaries, and focused tests run
  on committed source. Then rerun the original full LongMemEval E2E, including
  its tampered-command rejection and exact final canonical row counts.

## Exact file scope

Production: the existing `application/document_ingestion_replay.py` and
`application/use_cases/ingest_document.py`, plus a bounded shared
`application/document_fragment_metadata.py` containing the three unchanged
metadata helpers. No other production owner or public export changes.

Tests: one new `tests/unit/test_managed_document_replay.py` with a small shared
fixture helper if needed; existing ordinary identity/admission tests remain
unchanged. No original E2E test changes belong to this direction. Each file stays
below 1,000 lines. Run Ruff and the frozen size gate, ordinary/managed document
identity and admission suites, relevant feature-boundary tests, and the original
full LongMemEval selector. Reuse the two unchanged pure Docling extractor proofs;
rerun the affected HTTP and multimodal paths on the combined production candidate.

## Critic responses

Round one, finish_units: accepted the direction with required fresh-admission
selection in every replay/recovery path, a negative ordinary legacy multi-fragment
case, complete exact fragments/metadata, unchanged IDs/counts, and helper AST/global
equivalence. All are incorporated above.

Round one, finish_architecture: required enumeration of all three receipt and two
duplicate call sites, original source text, exact managed thread/canonical document
normalization, metadata key presence and JSON type/order checks, harmless fetch
ordering compatibility, unchanged ordinary policies and explicit file bounds.
All are incorporated above. Both critics independently approved round two with
no design blocker. The architecture critic clarified the legitimate missing-
receipt recovery accounting above. Production files were not edited before both
round-two approvals. The implementation and exact code remain subject to review.

## Workflow

Focused worktree `managed-document-replay-fix`, branch
`fix/managed-document-replay-20261024`, based on published main `35ea68be`.
Two independent critics review two plan rounds before production edits. Publish a
plan-only draft PR, then commit implementation promptly, obtain two independent
code reviews, fix findings, validate a combined candidate, and merge normally.
The original full-run failure remains in the evidence; targeted and corrected
E2E runs are reported separately, not added as new unique cases.
