# Answer-quality paired eval r1

Measurement dates: 2026-10-18 to 2026-10-20. This is a frozen-candidate
context-to-answer replay of the production context packer: one answerer LLM
receives the packed memory context (or an empty context) and answers the
question; a blind judge grades the answer against the official gold answer.
It does not rerun ingestion and retrieval for each question. The interpretation
and artifact contract below were reviewed on 2026-10-22; the historical model
outputs were not rerun or retrospectively relabelled.

## Decision summary

Two frozen question sets and two answerer models provide evidence of useful
packed context, with limits on the historical paired accounting:

- With the real packed context the answerer answers **36/100** questions
  correctly on Main-100 (Qwen3.8-Flash) and **18/48** on held-48
  (gpt-5.6-terra); with an empty context it answers **0/100** and **0/48**. In
  Main-100, eight arm records are unresolved. Its historical `helped=36` and
  `hurt=0` treated unresolved arms as non-correct; corrected resolved-pair
  counts cannot be recovered from the aggregate alone. Held-48 reports no
  unresolved arms, with 18 improvements and zero regressions in that run.
  These observations support a contribution from supplied context under the
  tested prompts; they do not prove exclusive causal provenance of each answer.
- Every correct answer in these runs is among the coverage-complete cases;
  none of the 7 + 9 coverage-incomplete cases was marked correct. This is an
  observed association, not a general proof that source coverage bounds answer
  accuracy. A coverage gain still needs an answer-level measurement.
- Many coverage-complete cases remain incorrect, missing, or unresolved.
  Merely including a source does not establish that the rendered passage
  supports the requested entity, relation, time, and polarity. Evidence
  selection and faithful derivation both remain possible failure causes.

## Why answer quality on top of source coverage

The frozen-148 harness (README "Memory evaluation snapshot") scores whether the
rendered context contains every gold source. That is a retrieval-completeness
metric: it records expected-source inclusion but does not establish whether an
LLM can actually derive the answer from the rendered evidence. This eval closes
that gap with a paired ablation on the same cases:

- **with arm** — the answerer sees the real packed context (production
  `ContextPacker` output, `bundle.rendered_text`).
- **without arm** — the same answerer, same question, empty context
  (`(empty: no memory retrieved)`).

The paired comparison estimates the effect of supplying the packed context
under these prompts and models. The empty arm checks observed success without
that context; a zero result on these cases does not rule out memorization or
guessing generally, or establish the provenance of every with-arm answer.

## Method

- **Cases.** The frozen Main-100 pack (100 cases, 25 per question type) and the
  held-48 pack (48 cases, 12 per question type), the same frozen inputs as the
  coverage snapshot. Cases are identified only by opaque hashes
  (`sha256(stem)[:12]`).
- **Context.** For every case the frozen pickle's `kwargs` are re-packed through
  the production `ContextPacker`, so the answerer sees exactly what production
  would render: median 17,557 chars on Main-100 and 17,444 on held-48, largest
  rendered context 17,997 chars — inside the frozen harness's
  `max_rendered_chars=18000` budget.
- **Gold answers.** The pickles carry no gold answers; they were recovered by
  joining the case question text against the official LongMemEval dataset file
  (sha256 `d6f21ea9d60a0d56f34a…`, the same hash pinned in
  `longmemeval-failure-slice-map-r1.md`). 100/100 and 48/48 matched.
- **Answerer.** Main-100 ran with `qodercli -m Qwen3.8-Flash --reasoning-effort
  xhigh`; held-48 ran with `gpt-5.6-terra` through the codex CLI
  (`codex exec`, read-only sandbox) after the Qwen daily usage limit
  and a mimo outage blocked the original plan (see the incident section). Both
  answerers were instructed identically: one short line, reply exactly `I don't
  know` when the context lacks the answer.
  The qodercli command explicitly disables tools. The committed codex command
  does not establish a no-tools boundary: read-only filesystem access alone is
  insufficient to make that claim.
- **Judge.** `qodercli -m mimo-v2.6-flash` for Main-100; `gpt-6-luna` through
  the codex CLI for held-48 — a different model from that pack's answerer, and
  blind to the arm (it sees question, gold, candidate only). Verdicts:
  `correct` (factually equivalent to gold), `missing` (refuses while gold has
  an answer), `incorrect` (everything else, including contradicting gold). On
  a 20-case sample a second judge model grades fresh candidates from the same
  answerer to measure verdict agreement — which models, and why that check is
  imperfect, in the judge-agreement section.
- **Privacy.** Question texts and gold answers were sent only to the providers
  this measurement answers through: qodercli (authorized in this project) for
  Main-100, and the codex/ChatGPT account opened for this run for held-48. All
  artifacts in the repo contain case hashes and counts only.

## Results: Main-100

Answerer `Qwen3.8-Flash` (xhigh effort), judge `mimo-v2.6-flash`, 100 cases × 2
arms, all numbers from the frozen `run100/aggregate.json`:

| Arm | correct | incorrect | missing | call failed | correct rate |
| --- | --- | --- | --- | --- | --- |
| With packed memory context | 36 | 24 | 37 | 3 | 36 (36.0%) |
| Empty context | 0 | 0 | 95 | 5 | 0 (0.0%) |

Historical paired counters: `helped=36`, `hurt=0`, `both_correct=0`,
`neither_correct=64`. The old calculation treated all non-correct outcomes,
including `call_failed`, alike. Eight unresolved arms affect between five and
eight distinct cases; their overlap and the corrected resolved-pair help/hurt
counts require the private per-case records. These old counters are not an
error-free paired quality estimate.

By question type (with / without correct, 25 cases each): information
extraction 14/0, knowledge update 11/0, multi-session reasoning 7/0, temporal
reasoning 4/0. These are arm-level correct counts, not corrected resolved-pair
counts.

By source coverage: all 36 correct answers are among the 93 coverage-complete
cases (36/93 correct there); none of the 7 coverage-incomplete cases was
answered (0/7).

Hygiene and latency: median answer time 6.65 s with context vs 4.37 s empty
(context is bigger to process, as expected), median judge time 6.56 s; 32
retry-level call failures were absorbed across answering and judging, the
largest repeated long candidate is 2 (no service-error blob counted as an
answer), and 8 arms remain honestly recorded as `call_failed` (3 with, 5
without) rather than being graded.

## Results: held-48

Answerer `gpt-5.6-terra` (codex CLI), judge `gpt-6-luna` (codex CLI), 48 cases
× 2 arms, all numbers from the frozen `run48codex/aggregate.json` (zero
unresolved verdicts):

| Arm | correct | incorrect | missing | call failed | correct rate |
| --- | --- | --- | --- | --- | --- |
| With packed memory context | 18 | 11 | 19 | 0 | 18 (37.5%) |
| Empty context | 0 | 0 | 48 | 0 | 0 (0.0%) |

Paired per case: memory **helped on 18**, hurt on **0**, both arms correct on
0.

By question type (with / without correct, 12 cases each): information
extraction 5/0, knowledge update 7/0, multi-session reasoning 2/0, temporal
reasoning 4/0.

By source coverage: all 18 correct answers are among the 39 coverage-complete
cases (18/39 correct there); none of the 9 coverage-incomplete cases was
answered (0/9).

Hygiene and latency: 56 retry-level call failures were absorbed (codex HTTP
429 bursts under sustained load, see the incident section) and the aggregate
reports zero unresolved verdicts; the largest repeated long candidate is 1. The
median answer time is 3.94 s with context vs 3.64 s empty; median judge time
4.44 s.

## Judge agreement (luna vs terra)

The planned cross-provider check (a mimo model as the second judge) was
blocked by the provider outage described below, so the sample ran with the only
two reachable models, both from the codex account. On 20 sampled held-48 cases
a fresh candidate from `gpt-5.6-terra` — same answerer and settings as the
main run — was graded blindly by `gpt-6-luna` (the held-48 judge) and by
`gpt-5.6-terra`:

| | luna correct | luna missing | luna incorrect |
| --- | --- | --- | --- |
| terra correct | 9 | 0 | 0 |
| terra missing | 0 | 8 | 0 |
| terra incorrect | 0 | 0 | 3 |

Agreement **20/20 (100%)**, both judges marked exactly the same 9 candidates
correct, zero unresolved verdicts. Read this with two limitations: the
account had no third model, so one judge grades candidates it also produced —
this measures agreement in that sample, not independent correctness or
cross-provider agreement, and shared model lineage can correlate errors; and
the sample is small (20 cases).

## Provider incident and mitigations

During the first run, concurrent load tripped the provider's rate limiter, which
printed a short error blob on stdout; the blob was initially accepted as an
answer text (one identical 126-char candidate across many records). After
detection:

- the runner now rejects service/error messages matching a service-error
  pattern and retries (3 attempts per call, failures are recorded honestly as
  `call_failed`, never as answers);
- a `largest_repeated_long_candidate` dedup counter surfaces any future
  identical-long-candidate contamination;
- the pipeline runs sequentially through a retry driver (`workers=2`), and
  contaminated records were dropped and re-run;
- the Qwen3.8-Flash daily usage limit ("come back tomorrow") interrupted the
  run at 192/200 Main-100 arms; a quota-aware driver resumed automatically
  after the limit reset and finished all stages.
- the first held-48 attempt was discarded and re-run: its answers were
  implausible (both arms had nearly identical median answer times, no case was
  answered correctly in either arm), which is the signature of provider
  service-error output being accepted as answer text. The held-48 numbers
  reported below come from the clean rerun.
- on 2026-10-20 a second Qwen3.8-Flash daily limit closed the original
  answerer for the held-48 rerun, and the custom mimo provider (both flash and
  pro, used for judging) began answering "the current model is busy" for the
  rest of the window; every other named model in the account was
  quota-walled. The
  held-48 rerun therefore used the codex CLI as the runner, with
  `gpt-5.6-terra` answering and `gpt-6-luna` judging. Under sustained load the
  codex endpoint answers with HTTP 429 bursts; the runner now gives the codex
  path five retries with a longer cooldown (10 s × attempt), and arms whose
  judge verdict could not be resolved are dropped and re-run by the driver
  until the aggregate reports zero unresolved verdicts. This describes the
  historical driver. The current runner preserves unresolved records as
  terminal observations; a retry experiment must use a new output directory.
- the mimo outage was not a blip: both mimo models kept answering "the current
  model is busy" from 15:14 UTC through at least 18:33 UTC (probed every 10
  minutes), and the qodercli `Fast` alias began answering "Queuing failed", so
  no qodercli model stayed reachable. The cross-provider second judge could
  not run; the judge-agreement sample therefore used the codex account's two
  models (see the judge-agreement section).

## Caveats

- Each pack uses a single answerer model for both of its arms (Main-100:
  Qwen3.8-Flash at xhigh effort; held-48: gpt-5.6-terra), so each pack's paired
  delta is internally consistent — but the two packs used different answerers,
  and their absolute rates must not be compared against each other.
- Verdicts come from an LLM judge, not human labels; the judge differs per pack
  (mimo-v2.6-flash for Main-100, gpt-6-luna for held-48). The second-judge
  sample could only run within the codex account (luna vs terra, terra also the
  answerer), so it bounds the verdict protocol's label consistency, not
  cross-provider agreement.
- LongMemEval is public, so parametric memorization is possible; the without
  arm measures observed answers without supplied context, not memorization
  itself.
- This measures the packer's rendered context only; ingest of the frozen
  sessions is taken as given.

## Reproduce

Measurement-only scripts (no production code paths):

- `scripts/answer_quality_pack_builder.py` — builds the private pack (frozen
  pickles + gold join) from local inputs.
- `scripts/answer_quality_paired_eval.py` — paired runner (both arms + blind
  judge), resume-safe, writes per-case records and an aggregate.
- `scripts/answer_quality_judge_check.py` — judge agreement sample: re-runs the
  answerer on a sampled subset and grades each fresh candidate with two judge
  models (`--judge-a`/`--judge-b`, runners selectable per judge).

The following describes the historical r1 scripts, before the 2026-10-22
artifact-contract revision. Main-100 ran before the additive CLI options
landed; those options (`--answerer-model`, `--answerer-runner`,
`--judge-model`, `--judge-runner`, the `codex exec` runner and its longer
retry/cooldown policy) leave the default qodercli/Qwen path behavior-identical
to what ran Main-100. Held-48 was produced by these scripts apart from two
review fixes that landed afterwards and cannot change a recorded verdict:
closing an unused file descriptor in the codex runner, and narrowing the
service-error filter to service phrasings so ordinary answer prose containing
words like "quota" or "exceeded" is no longer rejected. Filtering changes
which responses are accepted for grading and can therefore affect a future
retry sequence; it does not relabel already recorded historical verdicts.
Prompt templates and the verdict parser were unchanged across those two
historical stages. `answer_quality_pack_builder.py` is
the committed form of the build code. The pack rows match its output schema
exactly except one vestigial `duplicated_question` field, false on every row
and read by no script. The built packs were re-verified directly on the
measurement host: 100/100 and 48/48 rows carry a non-empty gold answer, all
case hashes distinct, 93/100 and 39/48 rows flagged coverage-complete.

### Current paired-run artifact contract (2026-10-22)

The current `answer_quality_paired_eval.py` uses schema version 2 and a private
output directory. Start a fresh experiment outside the repository, for example:

```bash
python scripts/answer_quality_paired_eval.py \
  --pack /private/measurement/pack.jsonl \
  --out-dir /private/measurement/run-v2 \
  --answerer-model Qwen3.8-Flash --answerer-runner qodercli \
  --judge-model mimo-v2.6-flash --judge-runner qodercli --workers 2
```

The runner validates the complete input schema and unique case IDs before
provider calls. `manifest.json` binds the selected input contents, answerer and
judge configuration, prompt templates, and the actual runner/helper source
bytes to one SHA-256 run identity. Changing any bound input requires a new
output directory. Worker count can change on a compatible resume. Historical
directories without this manifest are rejected rather than silently adopted.

One process owns the directory through a nonblocking POSIX file lock. Completed
arms are validated and durably appended as they finish. Resume repairs only an
incomplete, syntactically broken final line without a terminating newline; it
rejects malformed complete lines, incompatible records, and duplicate arms.
A valid final record without a newline is retained and delimited before the
next append. `call_failed` and `unparsed` records remain terminal observations
on resume; use a new directory for a retry experiment.

`results.jsonl` retains the full candidate answer for a private semantic audit,
along with its digest and measurement counters. The directory is mode 0700 and
artifact files are mode 0600; existing unsafe final symlinks and files owned by
another user are rejected. Do not commit the private pack, candidate records,
or provider logs. These local protections do not control a provider's retention
or a CLI's logs; qodercli also receives the prompt in its process arguments.

`aggregate.json` is atomically published from a fixed projection of counters,
run identity, and declared model configuration. It contains no questions,
gold answers, context, candidate text, or case IDs. Question-type group keys
are hashed because input labels are not assumed public. For each arm it reports
expected, observed, resolved, and absent counts. Rates carry an explicit
numerator and denominator, including correct per expected arm and correct per
resolved arm. Paired help/hurt counts include only cases whose two verdicts
are both `correct`, `incorrect`, or `missing`; unresolved and incomplete pairs
are separate counters. The CLI exits zero only for a complete run with no
unresolved verdicts, and exits 2 for unresolved or rejected runs.

This revision makes future experiments auditable. It does not regenerate the
private r1 candidates or establish fresh ingestion-to-answer quality. When
auditing a short gold match, check the candidate and cited passage for the
requested subject, asserted relation, time/version, and negation; token
containment alone is not sufficient evidence.

## Review round

An automated review pass over the measurement scripts found six findings; five
were fixed before the final measurement stages ran, one was rejected:

- **Verdict fallback substring collision (fixed).** When a judge reply did not
  match the required JSON format, the fallback matched the label `correct`
  inside `incorrect`. The JSON path (the overwhelmingly common one) was never
  affected. Parsing now uses word-boundary matching with longest-first
  alternation; the fix was in place for the final stages of the run, and the
  judge-agreement sample cross-checks verdicts with a second judge model.
- **Resume crash on torn trailing line (historical mitigation).** The r1
  runner skipped unparsable lines. That could also hide interior corruption
  and leave a torn tail in front of the next appended record. The current
  artifact contract below replaces that behavior with strict validation and
  narrowly scoped trailing-byte repair.
- **Case-hash collision across question-type directories (fixed).** The pack
  builder now fails loudly on a duplicate case hash; the built packs were
  re-verified to contain only distinct hashes.
- **Private pack file permissions (fixed).** The pack builder now enforces
  mode 0600 on the pack it writes; the packs on the measurement host were
  tightened to 0600.
- **Judge-agreement rate counted unresolved pairs (fixed).** Pairs where a
  judge produced no valid verdict are excluded from the agreement rate and
  reported separately.
- **Rejected:** a claim that `coverage_complete` derives from a covered-source
  count. The flag is read from the frozen coverage report per case; the
  reviewed code does not compute it that way.

A second automated pass (PR 79, `gpt-6-luna`) found four more findings, all
fixed after the measurement and none capable of changing a recorded verdict:

- **codex runner leaked the `mkstemp` descriptor (fixed).** The temporary
  last-message file's descriptor was never closed; it is now closed
  immediately after creation.
- **Service-error filter rejected ordinary prose (fixed).** The filter used to
  reject any answer containing bare words like `quota`, `exceeded` or `error`;
  it is now anchored to service phrasings (`too many requests`, `come back
  tomorrow`, `model is busy`, …). This affects retry selection and which
  responses reach the judge, without relabelling past recorded verdicts.
- **Memorization claim overstated (clarified again 2026-10-22).** The empty
  arm reports no correct answer without supplied context on these sets. It
  does not directly measure memorization or bound it generally.
- **Packer attribution (fixed).** The paired ablation establishes a gain from
  the packed context under these prompts and models; the decision summary now
  attributes the gain to the packed memory context, not to the packer alone.
