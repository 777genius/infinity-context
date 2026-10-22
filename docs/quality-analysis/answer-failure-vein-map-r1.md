# Answer-failure vein map r1 (post snippet-edge fix)

Analysis date: 2026-10-21. Read-only analysis of the frozen paired-eval artifacts
on the measurement host; no benchmark rerun and no provider call. All numbers are
counters and opaque 12-hex case hashes — no question, gold answer or context text
appears here. Private inputs stay on the host.

Interpretation reviewed on 2026-10-22 without rerunning the private artifacts.
The containment ladder below is a lexical diagnostic, not a semantic evidence
audit. Historical aggregates and flip counts are retained; unresolved judge or
provider outcomes must be separated before interpreting paired quality gains.

## Decision summary

This maps where the remaining with-arm answer failures live after the
snippet-edge-extension fix (PR 80) and which of those veins have a cheap,
regression-safe lever. The ladder runs on item texts **rebuilt from the seeded
stores** (frozen pickles carry ingestion-time snippets; packing never recomputes
them), with the same rebuild path on both sides: `before` = the installed main
snippet module, `after` = the PR 80 file overlaid byte-identical.

Findings:

- PR 80 rescues exactly the class it targets: `absent_snippet_cut` failures on
  Main-100 drop 4 -> 1 (controls 9 -> 7 absent overall), gold-visible
  (normalized gold contained in the rendered pack) rises 56 -> 59 by the A/B
  `gold_in` counter (4 up-flips, 1 down), coverage stays flat (86/100, 34/48).
  held-48 is unchanged — the edge extension never fires there (no query-hit
  clusters past the window).
- The ladder partitions 94 historical non-correct or unresolved with-arm
  cases across both sets: 42 are `in_rendered` (gold-string or token matches in
  the packed context; 39/42 have gold of only 1-2 content tokens), 29 are
  `scattered` (gold tokens split across the store; no single chunk or adjacent
  pair holds the span), 9 `dropped_by_pack`, 8 `not_retrieved`, 6 remaining
  `snippet_cut` (1 Main-100, 5 held-48; gold beyond the window without query
  hits). These buckets do not establish which component caused an answer
  failure, or whether a matching span expresses the required fact.
- The packer-side dropped class is governed by a 43-component bespoke
  answer-support family key; the gold-bearing chunk typically ranks 1-2 within
  its family and loses to a sibling. Reworking representative choice has a
  ceiling of ~5-7 cases and a high regression risk — not a close lever.
- Neighbor expansion does not rescue the scattered class: adjacent chunks of
  already-selected items contain only 26% of the missing gold tokens (66% for
  neighbors of all retrieved candidates), not enough to complete the fact in
  most cases.
- Recall misses (`not_retrieved`, 8 cases; plus the known 10 uncovered sources
  on Main-100) were measured with the replay harness (PR 82): the lexically
  near tail reaches the SQL pool and dies on admission, the far tail is
  unreachable by deeper SQL or a plain lexical union — measured and rejected
  (keyword-lane depth A/B below).
- The answerer-side short-gold hint was compared on 85 lexically matched
  cases with an identical-prompt repeat. Two apparent hint down-flips are
  `unparsed`, so they are unresolved, not demonstrated answer regressions.
  The aggregate is insufficient to recompute the resolved-pair effect.

These probes do not justify shipping the tested heuristics. They also do not
exhaust recall, context presentation, or answerer guidance as whole categories.
Further work needs a distinct, testable mechanism and complete paired outcomes;
candidate directions are listed at the end.

## Method

Scripts (committed in this PR): `scripts/answer_bucket_ladder_ab.py` (rebuild +
nested containment ladder), `scripts/answer_no_carrier_probe.py` (store-side
token analysis for `absent_no_carrier`), `scripts/answer_recall_lexical_probe.py`
(lexical-rank headroom for `absent_not_retrieved`). Ad-hoc one-off probes
(family-key competition, neighbor recoverability, packer drop diagnostics) ran
on the host against the same artifacts; their per-case counters are quoted
inline in the sections below.

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

Containment can match a common token, a different subject, an obsolete state,
or a negated claim. A semantic audit must inspect the requested subject,
assertion, time/version, polarity, and the supporting passage. A short gold
match is especially weak evidence of answer sufficiency. The historical
candidate answers were stored only as hashes, so this audit cannot be
reconstructed from those records alone.

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
26 -> 28, `dropped_by_pack` 1. The ladder flips 3 failure cases and 2 controls
into `in_rendered` (54 -> 59); the A/B `gold_in` counter — a slightly
different containment predicate on a differently-built pack — counts a
different flip set (4 up, 1 down) and lands on the same after-total of 59.
Those 4 up-flips plus the 1 down are among the mini-pack cases below.

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

All 37 (26 Main incl. controls, 11 held) are "scattered", none missing —
re-measured after the probe matching fixes (whole-token membership instead of
substring hits, adjacency grouped by source owner):

- gold-token union over the whole store is exactly 1.0 in every case;
- best single chunk covers 38-89% of gold tokens (median ~0.60);
- no adjacent chunk pair (same owner: scope + document/episode, sorted by
  char_start) contains the full normalized gold span.

Failure-only rendered-context coverage of gold tokens: Main-100 21 cases span
0.30-0.87 (none reach 1.0); held-48 8 cases span 0.0-1.0 (one reaches 1.0).
Some gold tokens are absent from these packs. This locates lexical gaps, but
does not by itself prove which passage would support the requested fact.

Neighbor-recoverability (Main-100, 26 cases, 112 missing tokens):

| Reach | Missing tokens recovered |
|---|---:|
| neighbors (±1 chunk, same scope) of selected items | 29 (26%) |
| neighbors of all retrieved candidates | 74 (66%) |

Even the optimistic bound cannot complete the gold span in most cases, so
neighbor expansion is not a lever here; this class needs evidence aggregation,
which is a design-level feature, not a patch. The oracle answer test below
measures that ceiling.

## Oracle aggregation answer test (2026-10-21, paired eval)

The scattered class is the only remaining mass that needs a *design* lever, so
it got an answer-level ceiling test rather than another packer patch: 36 of
the 37 scattered cases were scored (all 26 Main-100 incl. controls, 10 of 11
held-48; the pools include the scattered controls, so base has 6 correct).
For each case the base packed context was replayed through the production
packer, then the best non-adjacent carrier chunks were appended greedily
until the gold-token union over the pack reached 1.0 (K cap 6). The resulting
oracle pack was scored against the same base pack in the paired harness
(answerer gpt-5.6-terra, judge gpt-6-luna), arms blinded as usual.

| Arm | correct | incorrect | missing |
|---|---:|---:|---:|
| base packed context | 6 | 11 | 19 |
| oracle-aggregated context | 12 | 10 | 14 |

Paired on the same 36 cases: **6 missing/incorrect -> correct** (5 Main-100,
1 held-48), **0 correct -> not**. Median added chars 4268 (max 6815); base
contexts sit at the 18000-char cap (median 17612), and 29/36 oracle contexts
exceed it — including 5 of the 6 converting cases (the sixth converts at 17798
chars, inside the cap).

Verdict: the scattered class has a **real answer-level ceiling** — aggregation
converts roughly a fifth of its failures with zero regressions — but the
measured path to it is not shippable as-is: it appends ~4k chars past the
production budget. A lever here means redesigning what the packer *displaces*
to make room (in-budget set-cover), not raising the budget. Worth starting;
the ceiling is now measured, not assumed.

### In-budget variant (same 36 cases)

The follow-up question is whether that ceiling survives inside the production
budget: the oracle arm appends carriers on top of a full pack, so it breaks the
18000-char cap. The in-budget arm instead **evicts tail-ranked items** from the
rendered pack until the carriers fit: 29/36 cases need 1-7 evicted items (118
total, median 4), 7 fit untouched, every context lands under 18000 (max 17979).

| Arm | correct | incorrect | missing |
|---|---:|---:|---:|
| base packed context | 6 | 11 | 19 |
| in-budget aggregation | 11 | 9 | 16 |
| oracle (over-budget) | 12 | 10 | 14 |

Paired against base: **6 missing/incorrect -> correct, 1 correct -> missing**
(4 of the 6 oracle flips reproduce in-budget; 2 do not). One honest noise
floor: 7 cases have byte-identical contexts between the oracle and in-budget
arms, and 2 of those 7 disagree in verdict — the paired harness has a few
verdicts of run-to-run slack at this sample size, so the 1-2 case differences
between arms are inside noise; the 5-6 case conversion over base is not.

Also measured: eviction is not free — 108 of the 118 evicted items carry at
least one gold token (they are scattered-class packs, gold is everywhere in
diluted form). What the carriers buy is *completeness*, not more gold tokens.

Verdict: the scattered class converts **inside the budget** — ~+5 correct of
36 with ~1 regression-equivalent, so in-budget aggregation is a real, shippable
lever worth designing (displacement policy, not budget increase).

### Does a production signal find the carriers?

Both arms above pick carriers with **gold-token overlap** — available to an
oracle, not to a packer. The obvious production stand-in is query-token
overlap, so that was measured: same 36 cases, carriers picked by query-token
overlap from the seeded store (6 chunks cap, no gold anywhere), tail items
evicted until the pack fits the cap (31/36 evict, 137 items total, all
contexts under 18000).

| Arm | correct | incorrect | missing |
|---|---:|---:|---:|
| base packed context | 6 | 11 | 19 |
| query-token carriers, in-budget | 8 | 9 | 19 |
| gold-token carriers, in-budget | 11 | 9 | 16 |

Paired against base: **3 up, 1 down** — inside the measured noise floor, and
the mechanism explains why: the query-carrier arm adds a mean of **7.3% of
gold tokens** (31 of 36 cases add exactly zero), against 98.6% for the oracle
arm. The carriers are not duplicates of what the pack already holds (66 of 71
are new chunks) — but they fail to supply the oracle gold tokens in most
cases. This rejects the tested query-token-overlap rule; it does not rule out
semantic query-driven retrieval.

Verdict: the in-budget aggregation ceiling is real, but the naive production
instantiation of it is dead. The missing piece is a **carrier-identification
signal that reaches tokens absent from the query** (embedding similarity,
decomposition expansion, chunk-graph neighbours — each its own experiment and
its own cost), plus the displacement policy. It is a feature, not a patch,
and the cheap version of it does not exist.

Two more gold-free signals were measured against the same oracle carriers
(149 carriers over the 36 cases), and both are cheap-and-dead:

- **Same-document siblings, uncapped**: 34 of 149 carriers (23%) belong to a
  document already represented in the rendered pack, and adding *every* chunk
  of those documents completes the gold span in **9/36** cases — but at 6379
  extra chunks total (~177 per case), which no budget tolerates.
- **Same-document siblings, proximity-ranked** (nearest `sequence` neighbours
  of the packed chunks, K = 1/2/4/6/10): full coverage in **1/36 at every K**.
  The fact-bearing chunk sits far from the packed ones *inside the same
  document*, so sequence proximity carries no signal.

Between them the two probes also bound where a future signal has to look: the
fact is reachable through documents the pack already touches, but only by
ranking chunks by something other than query overlap or sequence distance.

A third candidate signal — the chunk graph in the seeded store — does not
exist to measure: `memory_context_links`, `memory_facts` and
`memory_source_refs` are empty (0 rows) in all 8 frozen stores (8305–17451
chunks each), and `memory_chunks` carries no embedding column. Any
graph- or embedding-based carrier identification would have to be built and
seeded first, which is exactly the feature-level cost noted above.

## The dropped class (`dropped_by_pack`, 8 Main-100 cases)

Of the 8 cases (7 with-arm failures + 1 correct control), 7 die on the
answer-support family key: the gold-bearing chunk's family **is** represented
in the pack — a sibling chunk of the same family was selected and the bearing
item was counted in `dropped_by_answer_support_family_duplicate` (per-case
sums 21-33 in the worst cases). The eighth dies on `dropped_by_source_cap` +
`dropped_by_char_cap` with no family bearing.

Key competition inside the family (probed on the 5 cases where a bearing
member resolves under the rebuilt snippets): the bearing item ranks 1, 1, 2,
2, 5 of the family; the deciding key components are bespoke
per-question-category ranks inside a 43-component tuple
(`_answer_support_family_item_key_for_query`). A principled minimal change is
not identifiable without displacing deliberately chosen winners — ceiling ~5-7
cases, high regression risk. Not taken.

## Lexically present gold with undetermined cause (`in_rendered`, 42 cases)

| Set | Cases | information_extraction | knowledge_update | multi_session_reasoning | temporal_reasoning | Gold 1-2 tokens | Gold 3-4 tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main-100 | 31 | 5 | 8 | 12 | 6 | 29 | 2 |
| held-48 | 11 | 1 | 3 | 6 | 1 | 10 | 1 |

The containment predicate matches gold strings or tokens in the packed
context, while the historical with-arm outcome is non-correct or unresolved.
For 39/42 cases the gold has only 1-2 content tokens. This can reflect a valid
supporting fact, but can also match the wrong owner, relation, time, or polarity.
It therefore cannot classify these cases as predominantly answerer failures.
The PR 79 sample found 20/20 agreement between two judges, one also the
answerer; it neither establishes independent judge correctness nor bounds
noise for these 42 cases. Historical `results.jsonl` retained candidate hashes
only, preventing a retrospective candidate-level semantic audit. The current
paired runner retains private candidate text for future audits.

## Recall headroom probe (`absent_not_retrieved`, 10 cases)

`scripts/answer_recall_lexical_probe.py` ranks every store chunk by a naive
query-token overlap (no IDF — headroom estimation, not production ranking) and
records the best rank of a gold-bearing chunk. Equal-score chunks form one tie
block, so ranks are tie-aware: each cell is **possible / guaranteed** (block
start / block end — store order inside a block carries no lexical signal).
Re-measured after the tie-aware fix:

| Set | Cases | top-3 | top-25 | top-75 | deeper than 150 (possible ranks) |
|---|---:|---:|---:|---:|---:|
| Main-100 | 5 | 0 / 0 | 3 / 1 | 3 / 2 | 2 / 2 (514, 1106) |
| held-48 | 5 | 3 / 2 | 3 / 2 | 3 / 2 | 1 / 2 (1617) |

Zero-overlap gold chunks are counted separately and never set the best rank
here: 2 Main-100 and 1 held-48 case carry at least one. 3 of 10 cases are
guaranteed in the lexical top-25 (6 of 10 possible); the rest need semantic
recall or query rewriting.

**Superseded by the replay-harness measurement below (same day):** the
lexically-near cases are exactly the ones the SQL keyword lane already brings
into the pool (they die later, on anchor-conflict admission, rejected at the
answer level); the lexically-far tail is unreachable by both rankings. A
plain lexical recall union therefore adds nothing — see the depth A/B
section. Caveat: two of the top-ranked cases
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
two match gold text and fail under both answerers except one flip under sol.
The lexical match does not resolve whether those contexts express sufficient
support for the requested fact.

On this 12-case probe the tested visibility and trimming changes showed no
net gain, and aggressive trimming lost correct answers. This small result
does not exclude other ordering or evidence-selection approaches.

## Answerer-side short-gold hint (2026-10-21, paired eval)

The answerer-side candidate (ranked lever 2) was measured at full class scale.
Scope: the 85 cases whose rebuilt pack renders gold (in_rendered pools of both
sets, `gold_in` filtered), one pack used by all runs. Knob: three lines added
to the answerer prompt only — the answer may be a short fragment, quote the
matching line instead of replying "I don't know". Judge prompt untouched,
same answerer (`gpt-5.6-terra`) and judge (`gpt-6-luna`). Three chained runs:
baseline, hint, and an identical-prompt baseline repeat as the noise floor.
Counters only; packs stay on the host.

| Run | correct | missing | incorrect | unparsed |
|---|---:|---:|---:|---:|
| baseline | 46 | 19 | 17 | 3 |
| + short-gold hint | 50 | 14 | 16 | 5 |
| baseline repeat (noise) | 48 | 18 | 15 | 4 |

Historical paired counters, with-arm: baseline -> hint flips 6 up / 2 down;
baseline -> baseline repeat flips 3 up / 1 down. Three of the six hint up-flips
(2be5717c5d05, 692ee11054a8, 9059026c41b5) also flip in the identical-prompt
repeat. The remaining reported differences were 3 up
(46f7649eb078, 98f3c0474251, db53edc0aa81) / 2 down (both `unparsed` rows)
= an old net counter of +1. Both down-flips are unresolved judge outcomes,
not confirmed answer regressions. Overlap with a repeated run is also
insufficient to assign a causal label to an individual flip. Corrected paired
effects require per-case resolved verdicts and appropriate uncertainty, which
cannot be recovered from the summary alone. The empty arm has 82/79/84 missing
answers of 85, with the other outcomes unresolved; it has no reported correct
answer.

The available evidence is insufficient to adopt this hint. Repeated-prompt
variation and unresolved verdicts require a fresh, complete paired experiment
before attributing an improvement. This probe does not classify the entire
`in_rendered` class as answerer-limited.

## Keyword-lane depth A/B (2026-10-21, replay probe)

Knob: `max_chunks` 30 -> 60 doubles keyword-lane depth (per-query SQL limit
90 -> 180, fused pool cap 180 -> 360). Replay probe (PR 82 harness), both
frozen sets, `--scope-set all`, identical code on both arms.

| Set | Targets recovered | pool_truncated | admit_anchor_conflict | Controls positive | Regressions |
|---|---|---|---|---|---|
| Main balanced (5 targets, 10 controls) | 1 -> 2 (+1) | 2 -> 2 | 1 -> 1 | 0 -> 0 | 0 |
| held-48 (5 targets, 10 controls) | 0 -> 0 | 1 -> 1 | 0 -> 0 | 0 -> 1 | 0 |

The rescued balanced case flipped `lost_after_admit` -> `recovered` with a
stable keyword rank (124) and more rendered gold (41 -> 69). The held-48
change is a control flipping `lost_after_admit` -> `recovered` (positive,
not a target).

The 3 persistent `pool_truncated` cases match gold under a limit=10000
direct-SQL probe (1753-1967 hits), but their best gold rank in that deep
result is 223, 1361, 1539: one case sits just past the doubled per-query
limit (180), two sit an order deeper. Doubling again would catch the 223
case at ~2x SQL cost and still miss the other two.

All 10 target cases were ranked by a plain token-overlap lexical scorer over
all in-scope chunks (probe-side counters). The lexically-near tail (gold in
top-4) is the `admit_anchor_conflict` class — gold already reaches the SQL
pool; its failure is admission, not recall. The lexically-far tail (gold at
ranks 725-3488 of 4k-16k scored) is the `pool_truncated` class — deeper than
the SQL term-variant ranking too. The single `never_matched` case has zero
token overlap with the query, consistent with its gold sharing no SQL term
variant at all. So a plain lexical recall union would surface only chunks
the SQL lane already brings: it rescues nothing new. The unreachable-by-both
tail would need query rewriting or semantic recall; the anchor-conflict
class was already rejected at the answer level (anchor-bypass probe).

Verdict: depth is a cheap but saturating recall lever (+1 target, zero
regressions). The persistent tail needs a distinct lexical/semantic channel,
not deeper SQL. No answer-level A/B on the rescued case: n=1 cannot
discriminate against the measured base rate (PR 80: 4 gold-visibility flips,
0 answer conversions), so the default `max_chunks` stays 30.

## Ranked next levers

1. **Recall harness for the frozen sets** — delivered (PR 82 replay probe +
   ladder scripts). With it, `never_matched` was diagnosed as scope
   partitioning (server-side lever closed by contract) and `admit_*` layers
   were measured; the anchor-bypass fix was evaluated at the answer level and
   rejected (0 conversions, 1 crowding regression). The depth A/B (section
   above) bought +1 target at zero regressions but saturates; what remains
   open on the recall side was a **plain lexical recall channel** — measured
   and rejected: the replay tail's gold ranks 725-3488 under naive lexical
   scoring (deeper than SQL), so that lexical union adds nothing. These
   probes reject those particular depth and token-overlap choices, while a
   different semantic recall signal remains an open experiment.
2. **Short-gold presentation** (the 39 short-gold `in_rendered` failures):
   the tested context-side changes did not show a reliable gain in the small
   probe. The hint's old net counter mixes unresolved outcomes; a semantic
   audit and complete paired accounting are required before choosing a
   further intervention for this class.
3. **In-budget evidence aggregation** for the scattered class (29 cases):
   ceilings measured on both sides — gold-token carriers convert +6/-1 inside
   the cap, but the production-realistic stand-in (query-token carriers)
   adds 7.3% gold tokens and reports 3 up / 1 down. These token-overlap rules
   supply little of the oracle signal. A production proposal needs a
   carrier-identification signal beyond query overlap; that signal is the
   real cost, not the displacement. Deprioritized until such a signal has its
   own cheap experiment.

Packer family-key rework, neighbor expansion, snippet visibility (PR 80
answer-level: 0 conversion), context trimming and gold repositioning are
explicitly deprioritized (ceilings, regressions or negative results above).

## Reproduction

Host-side (paths are host-local, inputs are private and never leave it).
All three scripts import shared helpers (`answer_snippet_rebuild_ab`,
`answer_failure_diagnosis`) that ship with PR 80 (`fix/snippet-edge-extension`),
so run them from a tree where PR 80 is merged or checked out, not from main
alone:

```
# ladder, Main-100, after arm (drop --snippet-overlay for the before arm;
# repeat with --set-dir for the held-48 set)
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
