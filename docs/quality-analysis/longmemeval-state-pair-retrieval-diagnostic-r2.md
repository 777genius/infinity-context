# LongMemEval state-pair retrieval diagnostic R2

Analysis date: 2026-07-19. This is a diagnostic-only, one-case trace. No source,
test, or configuration file was changed; no dataset was downloaded; and no
benchmark was run.

## Decision

For LongMemEval `031748ae`, both expected state facts exist in the dataset, the
seeded canonical store, and the canonical keyword candidate pool. The first
named boundary missing one side is **source identity/dedup**. More precisely,
the previous-state chunk is discarded immediately before item construction and
therefore arrives at dedup already absent; dedup itself does not merge the two
states.

The rejecting condition is an anchor-identity conflict, not low relevance. The
question-only anchor extractor misclassifies the occupational title “Senior
Software Engineer” as two `person` hints, `senior software` and `engineer`.
`chunk_689a0117b52b4acdb010a815c633db3e`, which contains the previous value,
passes `is_chunk_candidate_relevance_sufficient` but returns `true` from
`query_anchor_intent_text_conflicts`; the narrow conflict exception returns
`false`, so `BuildContextUseCase` skips it before `_chunk_context_item` and
before the first `dedupe_rank_items` call. The current-state chunk does not
conflict and survives.

This places the repair upstream of packing. A rank/reservation or packed-evidence
change cannot reserve a previous-state item that never reaches those seams.

## Scope and method

- Case: `031748ae`
- Question: “How many engineers do I lead when I just started my new role as
  Senior Software Engineer? How many engineers do I lead now?”
- Expected previous state: **4 engineers** from `answer_8748f791_1`, dated
  `2023/05/11 (Thu) 02:02`.
- Expected current state: **5 engineers** from `answer_8748f791_2`, dated
  `2023/10/24 (Tue) 13:53`.
- Runtime contract: canonical main commit
  `0e98a30a96937ae6c64393f04f641de80f2d0f5d`, local in-process profile,
  `token_budget=4000`, `max_facts=20`, `max_chunks=50`, and provider adapters
  disabled.
- The current worktree and `/var/data/workspaces/infinity-context` have the same
  commit and identical relevant `context_query_intent_extraction.py` and
  `build_context.py` files.
- The trace read the existing dataset and shard-1 canonical database. Runtime
  probes wrapped stage functions in memory and wrote no artifact or database
  state.
- Stop rule: stop boundary analysis at the first missing state; downstream rows
  are deliberately not independently traced.

## Boundary trace

| Ordered boundary | Previous: 4 engineers | Current: 5 engineers | Direct evidence | Result |
| --- | --- | --- | --- | --- |
| Dataset sessions | Present | Present | Dataset row maps `_1` at index 0 to the user statement “I lead a team of 4 engineers” and `_2` at index 6 to “I now lead a team of five engineers.” | Both present |
| Seeded canonical records | Present | Present | Active documents `doc_7e23226b449b42fda897ea54a533986d` (`_1`) and `doc_5bafd104b07d46a7a88811d959bff3a4` (`_2`); 17 and 18 active chunks respectively. Direct-value chunks are `chunk_689a0117b52b4acdb010a815c633db3e` and `chunk_25dedaae763845cea1878e9d5327eb77`. | Both present |
| Retrieval candidates | Present | Present | The fused canonical keyword pool contains 180 chunks. The direct previous-value chunk is pool rank 2 and the direct current-value chunk is pool rank 5. | Both present |
| Source identity/dedup | **Absent** | Present | Only four chunks pass into keyword prompt selection; the two case-support chunks among them are both source `_2`. The input and output of the first `dedupe_rank_items` contain `_2` and no `_1`. The `_1` direct chunk was relevant (`sufficient=true`) but was skipped on `anchor_conflict=true`; `_2` had `anchor_conflict=false`. | **First failing boundary**; loss is before, not inside, dedup |
| Rank/reservation | Not traced | Not traced | Stop rule applied after the first failing boundary. | Downstream / not independently assessed |
| Packed evidence | Not traced | Not traced | Stop rule applied after the first failing boundary. | Downstream / not independently assessed |
| Requirement coverage/hydration/final rendering | Not traced | Not traced | Stop rule applied after the first failing boundary. The existing baseline report already records the downstream symptom (`covered_terms=[answer_8748f791_2]`, `missing_terms=[answer_8748f791_1]`), but it is not used to relocate the first loss. | Downstream / not independently assessed |

## Bounded cause trace

The two derived retrieval queries were the generic temporal-event bridge and
quantity-enumeration bridge. The canonical collector retained both sources, so
query fanout and canonical keyword fusion are not the failing boundary.

For the previous-value chunk, the best expansion was
`general_temporal_event_bridge`. Its relevance values included 8 unique hits,
7 distinctive hits, a `0.2051` hit ratio, and `sufficient=true`. For the
current-value chunk, the best expansion was `decomposition_temporal_answer`,
with 5 unique hits, 5 distinctive hits, a `0.2273` hit ratio, and
`sufficient=true`.

The divergence occurs in this existing application flow:

1. `CanonicalContextCollector.collect` returns both direct-value chunks.
2. `BuildContextUseCase.execute` computes best query relevance for each.
3. `query_anchor_intent_text_conflicts` returns `true` only for the previous
   chunk because the role title became person identity intent.
4. `_keyword_anchor_conflict_allowed` does not apply: it is restricted to the
   unrelated `travel_country_inventory_bridge` exception.
5. The `continue` executes before `_chunk_context_item`; the previous source
   identity cannot reach keyword prompt selection, hydration, or dedup.

The safe conclusion is limited to this bounded trace: occupational-role text is
being applied as a person-identity exclusion at candidate admission. It does
not establish that every state-pair failure shares this cause.

## Recommended generic Clean Architecture slice

Implement one pure application-policy slice: **role descriptors are not person
identities**. Derive it only from question text and candidate text. Do not use
the case id, answer text, answer-session ids, or evaluation markers as runtime
inputs.

Exact production files:

- `packages/infinity_context_core/infinity_context_core/application/context_query_intent_extraction.py`:
  identify first-person occupational-role spans such as “my role as <title>”
  and exclude title tokens from `person` anchor hints while preserving real
  named-person hints.
- `packages/infinity_context_core/infinity_context_core/application/context_query_intent_matching.py`:
  ensure an occupational role descriptor cannot make otherwise relevant
  before/current evidence an identity contradiction.
- `packages/infinity_context_core/infinity_context_core/application/use_cases/build_context.py`:
  expose separate safe counts for anchor-conflict drops and relevance drops so
  a future canary identifies this boundary without text logging.

Exact tests:

- `tests/unit/test_context_query_intent.py`: assert that generic “my role as
  Senior Software Engineer” text creates no `senior software`/`engineer`
  person intent, both previous/current role-state snippets are non-conflicting,
  and genuine named-person mismatches remain conflicting.
- `tests/unit/test_context_relevance.py`: retain the existing relevance
  admission contract for both earlier and current numeric-state wording; do
  not weaken relevance globally.
- `tests/unit/test_context_state_pair_retrieval.py` (new): an application-level
  fixture with two distinct canonical sources must show both source identities
  at the input and output of dedup for a generic before/now role-state query.
  A mirrored chunk from either source must not count as the other state.

Do not start this slice in `context_packer.py` or the archived r3 paired-evidence
reservation code. Those are downstream of the observed loss. Archived r3 was
not needed for causal comparison because canonical main proved the item absent
before its reservation seam.

## One-case canary

After the deterministic tests pass, run only this local case against the
already staged dataset:

```bash
python -m infinity_context_server.eval public-benchmark \
  --dataset /var/data/workspaces/infinity-context/.e2e-artifacts/public-datasets/longmemeval_s_cleaned.json \
  --benchmark longmemeval \
  --min-accuracy 1.0 \
  --case-id 031748ae \
  --report-out /tmp/longmemeval-031748ae-role-state-canary.json

/usr/bin/jq -e '
  .metrics.case_count == 1 and
  .metrics.accuracy == 1 and
  (.failures | length) == 0 and
  .cases[0].covered_terms == ["answer_8748f791_1", "answer_8748f791_2"]
' /tmp/longmemeval-031748ae-role-state-canary.json
```

The session ids remain post-hoc canary labels only. Unit/application tests must
prove visible semantic evidence and distinct canonical sources without those
labels entering production selection.

## Evidence provenance, verification, and blockers

Authoritative local inputs:

- Dataset:
  `/var/data/workspaces/infinity-context/.e2e-artifacts/public-datasets/longmemeval_s_cleaned.json`
- Existing shard report:
  `/var/data/workspaces/infinity-context/.e2e-artifacts/quality-baseline-current-20260718/shards/longmemeval-100/shard-1/report.json`
- Existing canonical snapshot:
  `/var/data/workspaces/infinity-context/.e2e-artifacts/quality-baseline-current-20260718/shards/longmemeval-100/shard-1/state/memory.db`
- Dataset SHA-256 recorded by the existing report:
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- Baseline generator commit recorded by that report:
  `d6a856549329fd4ca1986bd86ddb0581d80c8fc4`
- Diagnostic code commit:
  `0e98a30a96937ae6c64393f04f641de80f2d0f5d`

No blocker prevented the bounded diagnosis. The existing report does not store
per-stage candidate identities, so the first-loss claim was established by a
read-only one-case replay over the existing canonical snapshot with in-memory
stage probes. No medium/full benchmark or provider call was made.
