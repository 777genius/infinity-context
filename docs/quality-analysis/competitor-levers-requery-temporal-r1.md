# Competitor levers r1: lexical re-query and temporal SQL filter

Analysis date: 2026-10-22. Measurement-only follow-up to the competitive
research (Mem0/Zep/Letta/LangMem/Memobase/HippoRAG2): two LongMemEval-inspired
levers were tested against the frozen paired-eval artifacts on the measurement
host. Counters and opaque 12-hex case hashes only; questions, gold answers and
chunk text stay on the host (private inputs, packs not exfiltrated).

## Decision summary

Both levers are **measured and rejected** on our frozen sets, for reasons the
vein map already bounded:

- **Lexical re-query** (Letta-style second hop with terms taken from the
  first-hop fragments) adds a mean of **7.0% of gold tokens** to the scattered
  class — statistically the same signal as the already-rejected query-token
  carriers (7.3%), against the oracle ceiling of 98.6%. The re-query terms are
  still lexical-overlap terms; the defining property of the scattered class is
  that the decisive tokens share no vocabulary with the query *or* the pool.
- **Temporal SQL filter** is **not measurable** on the frozen harness: the
  seeded stores populate no time data at all (0 of 17,451 chunks in a
  representative store carry `retrieval_start_at` or any temporal metadata
  hint). Our remaining recall failures are vocabulary-shaped, not
  time-shaped, and the temporal failures that do exist (`in_rendered`,
  6 Main-100 + 1 held-48) are answerer-limited with gold already in the pack.

The only carrier-identification signal left is semantic (embedding
similarity over store chunks), which the frozen stores cannot host: no
embedding column, no graph links, no facts rows (vein map r1). That is
feature-level infrastructure, not a patch — consistent with the vein map's
"deprioritized until such a signal has its own cheap experiment": the cheap
lexical experiments are now exhausted.

## Method: lexical re-query probe

`scripts/requery_carriers.py` (host run, both frozen sets, the 36 scattered
cases scored in the oracle aggregation test). Per case:

1. first hop — store chunks ranked by naive query-token overlap, top 360
   (mirrors the production keyword pool cap);
2. re-query terms — pool tokens absent from the query, scored by
   `pool_df / store_df` (distinctiveness), caps 24 and 48; a mixed variant
   interleaves adjacent bigrams of pool chunks under the same cap;
3. carriers — store chunks ranked by overlap with the re-query term set,
   top K=6, chunks already fully present in the rendered pack skipped;
4. metric — gold-token coverage of the carrier tail beyond the base render,
   the exact metric of the query-carrier and oracle arms.

| Arm (K=6, same metric) | mean gold coverage added | cases with zero added | cases reaching full coverage |
|---|---:|---:|---:|
| query-token carriers (rejected, vein map r1) | 7.3% | 31/36 | — |
| re-query, unigrams 24 | **7.0%** | 19/36 | 2/36 |
| re-query, unigrams 48 | 6.7% | 19/36 | 2/36 |
| re-query, unigram+bigram 24 | 0.0% | 36/36 | 1/36 |
| re-query, unigram+bigram 48 | 0.0% | 36/36 | 1/36 |
| oracle gold-token carriers | 98.6% | — | — |

The bigram-mixed variants are strictly worse: exact bigram matches almost
never co-occur across chunks, so the cap budget is spent on terms that match
nothing. The unigram variants add small amounts to more cases than
query-carriers (19 vs 31 zero-added) but never reach the decisive tokens —
mean coverage lands at the query-carrier baseline.

Boundary of this rejection: the first hop here is lexical. In production the
first hop would also contain semantically-retrieved chunks (vector lane),
whose vocabulary could feed a richer re-query. The frozen stores carry no
embeddings (0 rows with any embedding column; the vector lane is empty in the
harness), so the semantic version is not measurable today — the same
infrastructure gap the vein map recorded for the graph/embedding signals.

## Method: temporal filter feasibility

A temporal SQL filter (LongMemEval: +11.4% on the temporal subset) would
filter or re-rank the keyword pool by time metadata using
`TemporalQueryIntent` (already computed per request:
`context_temporal_query.py`). Two checks against the frozen harness:

- **Data**: a representative seeded store (17,451 chunks) has
  `retrieval_start_at`/`retrieval_end_at` NULL for **all** chunks and **zero**
  chunks with `event_temporal_hint_code` or `event_date` in metadata. The
  ingestion extraction code exists (`anchor_event_extraction.py`) but the
  frozen pickles predate or bypass that metadata population — a time filter
  has nothing to filter on in the harness.
- **Failure shape**: the remaining recall failures are `pool_truncated` and
  `never_matched` classes driven by lexical distance (vein map r1, replay
  harness: gold ranks 725-3488 under naive scoring, or zero overlap) — not by
  time confusion. The `temporal_reasoning` failures that exist are
  `in_rendered` (gold verbatim in the pack), i.e. answerer-limited.

Shipping a temporal filter would therefore mean changing production behavior
without the project's required discriminating measurement (the frozen sets
cannot host the before/after). Rejected until a harness populates chunk time
metadata; if that ingestion gap is closed as part of future semantic
infrastructure, the temporal filter can be re-evaluated on the same sets.

## Verdict

Competitor research confirmed direction but moved no numbers on our sets:
the cheap levers it suggests (query rewriting, temporal filtering) target
failure classes our pipeline does not have. The remaining quality mass
(scattered class, measured ceiling ~+5 correct in-budget) is gated on a
semantic carrier signal and on store-side metadata (embeddings, time windows)
that the frozen harness does not model. No production code changed.
