# Answer-failure vein map r1 (post snippet-edge fix)

Analysis date: 2026-10-21. Read-only analysis of the frozen paired-eval artifacts
on the measurement host; no benchmark rerun and no provider call. All numbers are
counters and opaque 12-hex case hashes — no question, gold answer or context text
appears here. Private inputs stay on the host.

## Decision summary

This maps where the remaining with-arm answer failures live after the
snippet-edge-extension fix (PR 80) and which of those veins have a cheap,
regression-safe lever. The ladder runs on item texts **rebuilt from the seeded
stores** (frozen pickles carry ingestion-time snippets; packing never recomputes
them), with the same rebuild path on both sides: `before` = the installed main
snippet module, `after` = the PR 80 file overlaid byte-identical.

Findings:

- PR 80 rescues exactly the class it targets: `absent_snippet_cut` failures on
  Main-100 drop 4 -> 1 (controls 9 -> 7 absent overall), gold-visible rises
  56 -> 61, coverage stays flat (86/100, 34/48). held-48 is unchanged — the
  edge extension never fires there (no query-hit clusters past the window).
- The remaining failure mass is **not** dominated by packer or snippet defects.
  Of 94 failures across both sets: 42 are `in_rendered` (evidence verbatim in
  the packed context; 39/42 have gold of only 1-2 content tokens), 29 are
  `scattered` (gold tokens split across the store; no single chunk or adjacent
  pair holds the span), 9 `dropped_by_pack`, 8 `not_retrieved`, 6 remaining
  `snippet_cut` (held-48, gold beyond the window without query hits).
- The packer-side dropped class is governed by a 43-component bespoke
  answer-support family key; the gold-bearing chunk typically ranks 1-2 within
  its family and loses to a sibling. Reworking representative choice has a
  ceiling of ~5-7 cases and a high regression risk — not a close lever.
- Neighbor expansion does not rescue the scattered class: adjacent chunks of
  already-selected items contain only 26% of the missing gold tokens (66% for
  neighbors of all retrieved candidates), never enough to complete the fact.
- Recall misses (`not_retrieved`, 8 cases; plus the known 10 uncovered sources
  on Main-100) cannot be measured further with the frozen pickles: they carry
  pack kwargs only, no retrieval configuration. A retrieval-side harness is
  required before any recall lever can be evaluated.

Conclusion: the cheap, safe veins are mined out. The next levers, ranked by
cost, are listed at the end.

## Method

Scripts (committed in this PR): `scripts/answer_bucket_ladder_ab.py` (rebuild +
nested containment ladder), `scripts/answer_no_carrier_probe.py` (store-side
token analysis for `absent_no_carrier`). Ad-hoc one-off probes (family-key
competition, neighbor recoverability, packer drop diagnostics) ran on the host
against the same artifacts and are reproducible from the snippets below.

Ladder buckets, applied to rebuilt candidate texts and the production packer:

- `in_rendered` — normalized gold (substring or all content tokens) in
  `rendered_text`;
- `truncated_in_pack` — gold in a selected item but not in the render;
- `dropped_by_pack` — a gold-bearing candidate exists but none was selected;
- `absent_from_candidates` — no rebuilt candidate contains gold; sub-split by
  store analysis: `absent_snippet_cut` (the retrieved chunk id is among the
  candidates but its snippet drops gold), `absent_not_retrieved` (a
  gold-bearing store chunk exists but was never a candidate),
  `absent_no_carrier` (no store chunk contains gold).

Known approximation: the rebuild applies `query_focused_snippet` to the raw
store text, while production snippets the enriched retrieval projection. The
path is identical on both A/B sides, so the comparison is valid; absolute
bucket counts may shift slightly in production.

Store-join integrity: 6332/6332 Main-100 and 3192/3192 held-48 candidate items
resolve to store chunks by id.

## Bucket ladder (Main-100)

With-arm failures (64 of 100), before -> after PR 80:

| Bucket | Before | After |
|---|---:|---:|
| `in_rendered` | 28 | 31 |
| `absent_snippet_cut` | 4 | 1 |
| `absent_not_retrieved` | 4 | 4 |
| `absent_no_carrier` | 21 | 21 |
| `dropped_by_pack` | 7 | 7 |

Correct controls (36): absent 9 -> 7 (snippet_cut 3 -> 1), `in_rendered`
26 -> 28, `dropped_by_pack` 1. The three failure cases flipped by PR 80 and the
two control flips match the +5 gold-visible A/B exactly.

## Bucket ladder (held-48)

With-arm failures (30 of 48), identical before and after:

| Bucket | Both sides |
|---|---:|
| `in_rendered` | 11 |
| `absent_snippet_cut` | 5 |
| `absent_not_retrieved` | 4 |
| `absent_no_carrier` | 8 |
| `dropped_by_pack` | 2 |

The overlay is confirmed applied (6 modules rebound); the extension simply
never triggers on this set. The 5 remaining `snippet_cut` cases have gold past
the window with no query hits there — unreachable by the same trick.

## The scattered class (`absent_no_carrier`, 37 cases)

All 37 (26 Main incl. controls, 11 held) are "scattered", none missing:

- gold-token union over the whole store is exactly 1.0 in every case;
- best single chunk covers 42-100% of gold tokens (median ~0.73);
- no adjacent chunk pair (same scope, consecutive char_start) contains the
  full normalized gold span.

Failure-only rendered-context coverage of gold tokens: Main-100 21 cases span
0.30-0.87 (none reach 1.0); held-48 8 cases span 0.0-1.0 (one reaches 1.0).
The decisive fact tokens are simply not in the pack.

Neighbor-recoverability (Main-100, 26 cases, 112 missing tokens):

| Reach | Missing tokens recovered |
|---|---:|
| neighbors (±1 chunk, same scope) of selected items | 29 (26%) |
| neighbors of all retrieved candidates | 74 (66%) |

Even the optimistic bound cannot complete the gold span in most cases, so
neighbor expansion is not a lever here; this class needs evidence aggregation,
which is a design-level feature, not a patch.

## The dropped class (`dropped_by_pack`, 8 Main-100 cases)

For 7 of 8 cases (7 failures + 1 control) the gold-bearing chunk's
answer-support family **is** represented in the pack — a sibling chunk of the
same family was selected and the bearing item was counted in
`dropped_by_answer_support_family_duplicate` (per-case sums 21-33 in the
worst cases). One case dies on `dropped_by_source_cap` + `dropped_by_char_cap`
with no family bearing; one case has no bearing item even under the rebuilt
snippets at probe time.

Key competition inside the family (5 cases with a bearing member): the bearing
item ranks 1, 1, 2, 2, 5 of the family; the deciding key components are bespoke
per-question-category ranks inside a 43-component tuple
(`_answer_support_family_item_key_for_query`). A principled minimal change is
not identifiable without displacing deliberately chosen winners — ceiling ~5-7
cases, high regression risk. Not taken.

## The answerer-limited class (`in_rendered`, 42 cases)

| Set | Cases | information_extraction | knowledge_update | multi_session_reasoning | temporal_reasoning | Gold 1-2 tokens | Gold 3-4 tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main-100 | 31 | 5 | 8 | 12 | 6 | 29 | 2 |
| held-48 | 11 | 1 | 3 | 6 | 1 | 10 | 1 |

The gold fact is verbatim in the packed context, yet the judge returned
missing/incorrect. 39/42 answers are 1-2 content tokens — presentation-fragile
short answers, not evidence gaps. Judge noise was already bounded separately
(PR 79 judge-agreement sample: 20/20 across two independent judges), so these
are predominantly answerer failures. The answerer's candidate text is not
retained in `results.jsonl` (sha only), so no further local split is possible.

## Recall headroom probe (`absent_not_retrieved`, 10 cases)

`scripts/answer_recall_lexical_probe.py` ranks every store chunk by a naive
query-token overlap (no IDF — headroom estimation, not production ranking) and
records the best rank of a gold-bearing chunk:

| Set | Cases | Gold chunk in lexical top-3 | top-25 | top-75 | deeper than 150 |
|---|---:|---:|---:|---:|---:|
| Main-100 | 5 | 0 | 3 | 3 | 2 (ranks 1095, 5788) |
| held-48 | 5 | 2 | 2 | 3 | 2 (ranks 468, 5165) |

5 of 10 cases would be reachable by a plain lexical recall union; the other 5
need semantic recall or query rewriting. Caveat: two of the top-ranked cases
have hundreds of gold-bearing chunks (short, common gold), so their containment
signal is weak. The core's BM25 boosts (`context_bm25_ranking.py`) only rerank
already-retrieved candidates — no lexical recall channel exists today. The
original ingestion harness lives in a root-owned host bundle
(`/srv/worker-state/...`) that the measurement account cannot read, so any
recall A/B needs either that access or a rebuilt ingestion harness.

## Answer-level presentation probes (2026-10-21, mini paired eval)

Three context-side presentation hypotheses were measured at the answer level
on a 12-case mini-pack (the four PR 80 gold-visibility flips, one non-flipping
target, one down-flip, six stable controls; all with `coverage_complete`),
rebuilt through the production packer on both sides. Answerer `gpt-5.6-terra`,
judge `gpt-6-luna`, both via `codex exec`; paired with/without arms. Counters
only; packs stay on the host.

| Probe | With-arm correct (of 12) | Verdict |
|---|---:|---|
| Baseline pack (all items) | 7 (1 incorrect, 4 missing) | reference |
| PR 80 snippet overlay | 7 (1 incorrect, 4 missing) | no conversion |
| Top-K trim, K=35 | 7 (1 incorrect, 4 missing) | neutral, per-cid identical |
| Top-K trim, K=20 | 4 (1 incorrect, 7 missing) | **harmful** — trims gold-bearing items |
| Stronger answerer (`gpt-6.1-sol`) on the baseline pack | 7 (1 incorrect, 4 missing) | 1 missing→correct (gold visible), 1 correct→missing |

Without-arm stayed 12/12 missing in every run (clean discrimination, no
parametric leakage). Gold first-hit offset in the rendered context sits at
0.01–0.11 of context length for the near misses — the short-gold answers are
**not** buried at the end of long contexts, so ordering/reordering is not the
lever either. Two of four missing cases have gold absent from the context
altogether (already counted in `not_retrieved`/`snippet_cut` veins); the other
two carry gold verbatim and fail under both answerers except one flip under
sol, consistent with the `in_rendered` answerer-limited class.

Conclusion: at the answer level, context-side presentation knobs (visibility,
trimming, ordering) are mined out — they either do nothing or actively hurt.
The remaining mass is answerer-side (short-gold extraction) or recall-side.

## Ranked next levers

1. **Recall harness for the frozen sets** — delivered (PR 82 replay probe +
   ladder scripts). With it, `never_matched` was diagnosed as scope
   partitioning (server-side lever closed by contract) and `admit_*` layers
   were measured; the anchor-bypass fix was evaluated at the answer level and
   rejected (0 conversions, 1 crowding regression). What remains open on the
   recall side is a **plain lexical recall channel** for the 5 of 10
   lexically-reachable probe cases — unmeasured, needs a recall A/B first.
2. **Short-gold presentation** (touches the 39 short-gold `in_rendered`
   failures): answerer-side formatting guidance, not memory. Context-side
   presentation knobs were probed and rejected (section above).
3. **Evidence aggregation design** for the scattered class (29 cases): a
   design-level feature; only worth starting with the recall harness in place
   (now true).

Packer family-key rework, neighbor expansion, snippet visibility (PR 80
answer-level: 0 conversion), context trimming and gold repositioning are
explicitly deprioritized (ceilings, regressions or negative results above).

## Reproduction

Host-side (paths are host-local, inputs are private and never leave it):

```
# ladder, both sides, both sets
python scripts/answer_bucket_ladder_ab.py --pack pack.jsonl \
  --results run100/results.jsonl --inputs-root $INPUTS \
  --set-dir balanced-frozen-20261011 --store-root $STORES \
  --out ladder100_after.jsonl --snippet-overlay $PR80_SNIPPET_FILE

# no-carrier store analysis
python scripts/answer_no_carrier_probe.py --pack pack.jsonl \
  --ladder ladder100_after.jsonl --inputs-root $INPUTS \
  --set-dir balanced-frozen-20261011 --store-root $STORES \
  --out nocarrier100.jsonl
```

`--snippet-overlay` accepts the PR 80 `context_snippets.py`; without it the
installed module (main) is used. The overlay mechanism is
exec-into-module-dict + `sys.modules` rebind because the host test environment
uses an editable install that ignores `PYTHONPATH`.
