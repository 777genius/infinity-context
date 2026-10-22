# Competitor levers r1: lexical re-query and temporal SQL filter

Analysis date: 2026-10-22. Measurement-only follow-up to the competitive
research (Mem0/Zep/Letta/LangMem/Memobase/HippoRAG2): two LongMemEval-inspired
levers were tested against the frozen paired-eval artifacts on the measurement
host. Counters and opaque 12-hex case hashes only; questions, gold answers and
chunk text stay on the host (private inputs, packs not exfiltrated).

Interpretation reviewed on 2026-10-22 without rerunning the private artifacts.
The token-coverage counters below are lexical diagnostics; they do not
establish semantic evidence sufficiency or answer-level quality gains.

## Decision summary

The tested lexical re-query variants do not justify a production change on
these frozen cases. The temporal check identifies missing evaluation data;
it does not measure a temporal filter's effectiveness.

- **Lexical re-query** (Letta-style second hop with terms taken from the
  first-hop fragments) adds a mean of **7.0% of gold tokens** with 24 unigram
  terms, versus 7.3% for the previously tested query-token carriers and 98.6%
  for the gold-token oracle comparison. These are descriptive coverage
  counters; no statistical-equivalence test or new answer-level comparison
  was performed. The mixed unigram/bigram variants have the implementation
  limitation described below.
- **Temporal SQL filter** was not evaluated before and after. In a
  representative seeded store, none of 17,451 chunks carried the checked
  time fields or metadata hints. The seven temporal cases in the
  `in_rendered` bucket (6 Main-100 + 1 held-48) have gold-string or token
  matches in the pack. Such matches do not establish support for the correct
  subject, relation, time or polarity, or identify the answerer as the cause.

Semantic carrier retrieval is one candidate for a separate experiment. The
frozen stores lack the populated embedding, graph-link and fact data needed
for the corresponding probes described in the [failure map](answer-failure-vein-map-r1.md).
The tested rules do not exhaust lexical re-query, temporal retrieval, or
other carrier-identification methods.

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

The mixed unigram/bigram variants recorded zero added gold-token coverage,
but the committed probe does not test bigram matching correctly: it constructs
space-joined bigram terms and scores them against unigram-only chunk-token
sets. Those bigram entries cannot match under this scorer. Their historical
rows are retained as results of that implementation, not evidence against a
correctly matched bigram method. Full coverage includes the original render,
so it can be recorded even when a variant adds no gold tokens.
This limitation follows from committed-source inspection; the external
historical host's helper bytes were not independently re-attested here.

The unigram variants add some gold tokens in more cases than the historical
query-token rule (19 versus 31 cases with zero added), while mean added
coverage is 7.0% or 6.7% versus 7.3%. Two cases reach full token coverage.
These counters do not determine whether the added passages support the
requested fact or improve generated answers.

Boundary of this result: the first hop here is lexical. When enabled and
populated, the production vector lane could supply different first-hop
vocabulary. The frozen harness has no populated vector lane, so a re-query
using semantically retrieved first-hop chunks was not evaluated. These
results apply to the tested unigram rules and the mixed implementation
above; they do not reject semantic re-query or other lexical formulations.

## Method: temporal filter feasibility

A temporal SQL filter (LongMemEval: +11.4% on the temporal subset) would
filter or re-rank the keyword pool by time metadata using
`TemporalQueryIntent` (already computed per request:
`context_temporal_query.py`). Two checks against the frozen harness:

- **Data**: a representative seeded store (17,451 chunks) has
  `retrieval_start_at`/`retrieval_end_at` NULL for **all** chunks and **zero**
  chunks with `event_temporal_hint_code` or `event_date` in metadata. The
  ingestion extraction code exists (`anchor_event_extraction.py`), but the
  inspected frozen store lacks these populated fields. A filter on those
  fields cannot provide the intended discrimination in that store.
- **Failure shape**: the replay probe reports `pool_truncated` cases with
  gold-bearing chunks at naive lexical ranks 725-3488, and one
  `never_matched` case with zero query-token overlap. These observations
  diagnose lexical access limits in those cases; they do not exclude a
  contribution from temporal ambiguity. The seven `temporal_reasoning`
  cases in `in_rendered` are lexical matches with undetermined cause, as
  described in the [failure map](answer-failure-vein-map-r1.md).

A temporal-filter implementation remains deferred because these checks do
not provide a discriminating before/after effectiveness measurement. A
populated temporal harness would be needed to evaluate it. The present
feasibility limit does not establish that temporal filtering would help or
harm the production pipeline.

## Verdict

The tested unigram re-query rules added little gold-token coverage relative
to the historical gold-token oracle, and no new answer-level gain was
measured. The mixed variants are limited by their unigram-only matcher; the
temporal filter was not evaluated because the inspected store lacked the
required time data. These results do not justify shipping the tested rules,
and do not show that the pipeline lacks query-rewriting or temporal failure
modes. The earlier in-budget gold-token oracle reported 11 correct answers
versus 6 of 36 at baseline, with six improvements and one regression; that
is a historical oracle comparison, not a deployable mechanism or a general
quality ceiling. No production code changed.
