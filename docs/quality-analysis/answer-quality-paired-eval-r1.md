# Answer-quality paired eval r1

Measurement dates: 2026-10-18 to 2026-10-20. This is the first end-to-end
answer-quality measurement of the production context packer: one answerer LLM
receives the packed memory context (or an empty context) and answers the
question; a blind judge grades the answer against the official gold answer.

## Decision summary

Two frozen question sets, two answerer models, one consistent picture:

- With the real packed context the answerer answers **36/100** questions
  correctly on Main-100 (Qwen3.8-Flash) and **18/48** on held-48
  (gpt-5.6-terra); with an empty context it answers **0/100** and **0/48**. In
  both sets every correct answer comes from the memory context — memory helped
  36 and 18 cases respectively and hurt none — so on these sets the packer
  contributes real, exclusively memory-derived answer accuracy and introduces
  no regressions against the empty baseline.
- Answer accuracy is bounded by source coverage: every correct answer in both
  sets is among the coverage-complete cases, and none of the 7 + 9
  coverage-incomplete cases was answered. Raising coverage (the README
  snapshot's remaining gaps) is a direct lever on answer accuracy.
- With the full source set in context the answerer still fails on roughly 60%
  of questions (incorrect or "I don't know"): source coverage is necessary but
  not sufficient — evidence selection and derivation inside the rendered
  context is the next quality frontier.

## Why answer quality on top of source coverage

The frozen-148 harness (README "Memory evaluation snapshot") scores whether the
rendered context contains every gold source. That is a retrieval-completeness
metric: it is necessary for a correct answer but says nothing about whether an
LLM can actually derive the answer from the rendered evidence. This eval closes
that gap with a paired ablation on the same cases:

- **with arm** — the answerer sees the real packed context (production
  `ContextPacker` output, `bundle.rendered_text`).
- **without arm** — the same answerer, same question, empty context
  (`(empty: no memory retrieved)`).

The paired delta isolates the memory contribution and bounds the effect of
LongMemEval being a public dataset: anything the answerer answers in the
without arm comes from parametric knowledge (memorization or guessing), not
from the memory system.

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
  (`codex exec`, read-only sandbox, no tools) after the Qwen daily usage limit
  and a mimo outage blocked the original plan (see the incident section). Both
  answerers were instructed identically: one short line, reply exactly `I don't
  know` when the context lacks the answer.
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

Paired per case: memory **helped on 36**, hurt on **0**, both arms correct on
0, neither on 64 (the "neither" bucket includes the 8 arms that ended
`call_failed`).

By question type (with / without correct, 25 cases each): information
extraction 14/0, knowledge update 11/0, multi-session reasoning 7/0, temporal
reasoning 4/0 — every gain over the empty arm comes from memory.

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
correct, zero unresolved verdicts. Read this with two honesty notes: the
account had no third model, so one judge grades candidates it also produced —
this bounds the verdict protocol's label consistency, not cross-provider
agreement, and shared model lineage can only inflate it; and the sample is
small (20 cases).

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
  until the aggregate reports zero unresolved verdicts.
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
- LongMemEval is public, so parametric memorization is possible; the without arm
  measures it directly (see paired table).
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

The committed copies of the two runner scripts are byte-identical (md5) to the
ones on the measurement host. Main-100 ran before the additive CLI options
landed; those options (`--answerer-model`, `--answerer-runner`,
`--judge-model`, `--judge-runner`, the `codex exec` runner and its longer
retry/cooldown policy) leave the default qodercli/Qwen path behavior-identical
to what ran Main-100, and the held-48 numbers were produced by exactly these
committed scripts. Prompt templates, the service-error pattern and the verdict
parser are unchanged across both stages. `answer_quality_pack_builder.py` is
the committed form of the build code. The pack rows match its output schema
exactly except one vestigial `duplicated_question` field, false on every row
and read by no script. The built packs were re-verified directly on the
measurement host: 100/100 and 48/48 rows carry a non-empty gold answer, all
case hashes distinct, 93/100 and 39/48 rows flagged coverage-complete.

## Review round

An automated review pass over the measurement scripts found six findings; five
were fixed before the final measurement stages ran, one was rejected:

- **Verdict fallback substring collision (fixed).** When a judge reply did not
  match the required JSON format, the fallback matched the label `correct`
  inside `incorrect`. The JSON path (the overwhelmingly common one) was never
  affected. Parsing now uses word-boundary matching with longest-first
  alternation; the fix was in place for the final stages of the run, and the
  judge-agreement sample cross-checks verdicts with a second judge model.
- **Resume crash on torn trailing line (fixed).** A killed run could leave a
  partial JSONL line that broke resume; such lines are now skipped.
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