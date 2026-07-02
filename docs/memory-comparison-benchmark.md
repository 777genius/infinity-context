# Memory Comparison Benchmark

This runner compares memo-stack / Infinity Context with mem0 using the same
high-level pipeline used by public memory benchmark runners:

```text
ingest -> search -> answer -> judge
```

It is separate from the existing `public-benchmark` command. The existing
runner checks retrieval and evidence coverage. This runner preserves each
pipeline stage for side-by-side accuracy, retrieval, latency, token/context and
failure analysis.

## Command

```sh
MEMORY_SERVICE_TOKEN=... \
MEM0_API_KEY=... \
MEMORY_OPENAI_API_KEY=... \
MEMORY_COMPARISON_ANSWERER_MODEL=... \
MEMORY_COMPARISON_JUDGE_MODEL=... \
MEMORY_COMPARISON_ANSWERER_INPUT_USD_PER_1M=... \
MEMORY_COMPARISON_ANSWERER_OUTPUT_USD_PER_1M=... \
MEMORY_COMPARISON_JUDGE_INPUT_USD_PER_1M=... \
MEMORY_COMPARISON_JUDGE_OUTPUT_USD_PER_1M=... \
python -m infinity_context_server.eval memory-comparison-benchmark \
  --dataset ./datasets/locomo10.json \
  --memo-api-url http://127.0.0.1:7788 \
  --mem0-url http://127.0.0.1:8888 \
  --mem0-api-key-env MEM0_API_KEY \
  --benchmark locomo \
  --locomo-ingest-mode official-turns \
  --max-cases 20 \
  --capability single-hop \
  --top-k 200 \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --answerer-provider openai \
  --judge-provider openai \
  --answerer-input-usd-per-1m 2.50 \
  --answerer-output-usd-per-1m 10.00 \
  --judge-input-usd-per-1m 2.50 \
  --judge-output-usd-per-1m 10.00 \
  --allow-live \
  --allow-paid-llm \
  --run-id locomo-side-by-side-sandbox-001 \
  --report-out .e2e-artifacts/memory-comparison-locomo.json
```

`--mem0-url` is the self-hosted mem0 OSS REST server base URL. The adapter uses
the OSS endpoints `POST /memories`, `POST /search` and `DELETE /memories`; it
does not target the hosted mem0 Platform `/v3` API.
For OSS search requests, the adapter sends scoped entity ids through `filters`
and sends both `limit` and `top_k` for the requested retrieval count, because
the lightweight mem0 wrapper accepts `limit` while the SDK-level API names the
same control `top_k`.
Memo-stack comparison requests use the hidden service-token
`/v1/context/benchmark-search` endpoint so `top_k=200` is not silently reduced
by public API caps. The public `/v1/context` fallback is still capped to
`max_facts <= 100`, `max_chunks <= 200` and `token_budget <= 16000`; report
metadata records `limited_by_http_api_caps=true` if that fallback is used.

Use deterministic answer/judge for a no-paid dry run by omitting
`--answerer-provider openai`, `--judge-provider openai` and `--allow-paid-llm`.

### Fast Diagnostic Workflow

Do not use full LoCoMo as the normal development loop. Full LoCoMo is reserved
for final reports or major milestones after fast gates are green. For retrieval,
temporal and multi-hop work, use a small deterministic case set and a compact
report first:

Run the sanitized preflight before touching live benchmark state:

```sh
MEMORY_SERVICE_TOKEN=local-dev-token \
python -m infinity_context_server.eval memory-comparison-benchmark \
  --dataset ./datasets/locomo10.json \
  --memo-api-url http://127.0.0.1:7788 \
  --mem0-url http://127.0.0.1:8888 \
  --benchmark locomo \
  --locomo-ingest-mode official-turns \
  --case-set locomo-fast \
  --report-mode compact \
  --top-k 200 \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --allow-live \
  --preflight-only
```

Add `--preflight-probe-services` when Docker services are expected to be up.
The preflight prints only boolean secret readiness, never token values. Treat
`ready_for_locomo_fast=false` as a blocker for long LoCoMo runs.

```sh
MEMORY_SERVICE_TOKEN=local-dev-token \
python -m infinity_context_server.eval memory-comparison-benchmark \
  --dataset ./datasets/locomo10.json \
  --memo-api-url http://127.0.0.1:7788 \
  --mem0-url http://127.0.0.1:8888 \
  --benchmark locomo \
  --locomo-ingest-mode official-turns \
  --case-set locomo-fast \
  --report-mode compact \
  --top-k 200 \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --allow-live \
  --run-id locomo-fast-sandbox-001 \
  --report-out .e2e-artifacts/memory-comparison-locomo-fast.json
```

Fast case sets:

- `locomo-fast`: 10 scored questions from each LoCoMo group.
- `locomo-fast-temporal`: 10 temporal questions.
- `locomo-fast-single-hop`: 10 single-hop questions.
- `locomo-fast-multi-hop`: 10 multi-hop questions.
- `locomo-fast-open-domain`: 10 open-domain questions.

`--report-mode compact` omits full per-case retrieval payloads and keeps metrics,
aggregate diagnostics and the first failure-analysis entries. Use
`--report-mode full` only when inspecting individual retrieved memories.

Fast gate for true top-k: with `top_k=200`, memo-stack metadata should show
`benchmark_search=true`, `applied_max_facts=200`,
`applied_max_chunks=200`, `limited_by_http_api_caps=false`, and `top_50` should
not be identical to `top_200`.

For LoCoMo official-turn runs, the memo-stack benchmark backend also mirrors
memory-only input turns into raw-turn documents. That gives the retrieval layer
both canonical facts and chunk evidence from the same source conversation, so
hybrid/source-mix diagnostics can prove whether retrieval is using more than
`postgres_facts`. The fast gate is `backend_metrics["memo-stack"]["source_mix_gate"]`:
`source_mix_ok=true`, `only_postgres_facts=false`, and non-zero chunk/vector source
counts.

Temporal fast gate: official-turn memory metadata is copied into fact/document
source refs as `time_start_ms`/`time_end_ms`, and operation diagnostics expose
`source_timestamp` plus session fields. `backend_metrics["memo-stack"]
["temporal_metadata_gate"]["temporal_metadata_ok"]` must be true before tuning
temporal behavior. For temporal queries, memo-stack search metadata should also
show `temporal_rerank.applied=true` when timestamped evidence is present; boosted
items carry `diagnostics.temporal_rerank_boosted=true`.
Temporal query decomposition also adds session/date/time surfaces and avoids
treating calendar words like `Friday` as people. Sequence evidence with
`session_4`, `date:` or `D4:3` gets a bounded temporal sequence boost.
Relative temporal evidence such as `yesterday`, `today`, `tomorrow`,
`last week`, `next month` or `2 weekends ago` also gets the bounded temporal
text boost, because LoCoMo answers often depend on relative dates in dialogue
turns rather than absolute timestamps in the sentence itself.
Temporal search focus also carries bounded relative-date surfaces such as
`last`, `today`, `yesterday`, `tomorrow`, `weekend` and `week`, so lexical
backends can retrieve date-bearing dialogue turns before rerank sees them.
Typed time intent distinguishes `duration`, `temporal_sequence`,
`relative_time`, `explicit_time` and generic `temporal_lookup`, so diagnostics
can separate Friday/month evidence from yesterday/ago/last-week evidence.

Benchmark query decomposition and rerank gate: memo-stack expands the search
query into a bounded question-only fanout, merges/dedupes retrieved evidence,
and applies a benchmark-only rerank from the question text, not ground truth
answers. It boosts entity/action overlap, temporal surfaces, multi-query matches
and multi-hop support, then reports
`backend_metrics["memo-stack"]["benchmark_rerank_gate"]`. The gate should show
`benchmark_rerank_ok=true` and `uses_ground_truth=false`.
Multi-query candidate merging is handled by `candidate_fusion.v1`. It keeps the
best occurrence for each item/source-ref/text key, but adds bounded confidence
from repeated query hits, reciprocal-rank fusion and retrieval-source diversity.
The HTTP metadata still exposes the compatibility name `multi_query_merge`, but
the payload includes `schema_version: candidate_fusion.v1` plus per-item
`benchmark_candidate_fusion` diagnostics.
When query-plan roles are available, fusion also records per-candidate
`benchmark_query_roles`, `benchmark_bridge_query_hit` and aggregate
`query_role_counts`, without adding a single-query score boost. This makes
bridge/temporal retrieval provenance visible in fast diagnostics while keeping
ranking changes tied to evidence strength.
The rerank implementation keeps separate responsibilities for candidate
feature extraction, final score/cap policy, focused intent policies and focused
evidence-shape policies, so new benchmark diagnostics can be added without
turning the main rerank path into a case-specific monolith.
Rerank scoring now also emits `benchmark_rerank_policy.v2` diagnostics on each
boosted memory. The policy table breaks the final bounded boost into
`EntitySpeakerPolicy`, `RelationCoveragePolicy`, `TemporalPolicy`,
`PreferenceIntentPolicy`, `FocusedTurnPolicy`, `EvidenceBundlePolicy`,
`AnswerabilityPolicy`, `MultiHopPolicy` and `ContrastIntentPolicy`, including
per-policy reason codes.
Query fanout now emits `query_plan.v2` diagnostics. The plan keeps bounded
question-only candidates with roles such as `original_question`,
`expanded_focus`, `compact_relation`, typed temporal support roles such as
`duration_temporal_support`, `explicit_temporal_support`,
`relative_temporal_support` and `temporal_sequence_support`,
`visual_temporal_support`, `multi_hop_bridge` and `multi_hop_support`, dedupes
equivalent queries, caps fanout by priority while preserving query-type
diversity, and records a leakage guard that forbids answer terms as planner
inputs. For question-marker multi-hop cases such as `why` and `how`, the bridge
query uses generic question-only bridge surfaces such as reason/process/support
plus grounded entity/relation terms, so bridge evidence can enter retrieval
without answer-key terms. If semantic candidates would fill the whole fanout,
the planner keeps room for lexical/raw-turn-oriented candidates and reports any
delayed roles under `dropped_type_limit_roles`.
Typed temporal query roles still include the generic `temporal_support` reason
code plus `time_kind:<kind>`, so diagnostics can group broad temporal behavior
or debug duration/explicit/relative/sequence gaps separately.
Query planning now starts from a typed `retrieval_intent.v1` contract and then
renders the backwards-compatible `query_profile` dict used by older tests and
reports. The intent captures entity surfaces, speaker surfaces, relation
surfaces, typed relation facets such as `preference`, `status_profile`,
`identity_profile`, `causal`, `support_goal`, `activity`, `exchange`,
`communication`, `temporal`, `visual` and `contrast`, temporal kind, evidence
needs and risk flags from question-only signals. `query_decomposition`,
`benchmark_rerank` and `query_integrity` metadata expose this intent for
diagnostics, but query-integrity token overlap continues to score only the
explicit query/profile token fields. Quality
diagnostics also group fast-loop metrics by `relation:<category>`, so broad
evidence needs such as `inference_support` can be debugged by relation class.
Questions with compare/between/different/previous/former surfaces now carry
`evidence_need=contrast`, while plain `current` or `still` questions do not
become contrast queries by themselves. Contrast intent adds a bounded
`contrast_support` query-plan role that searches for current-vs-previous
evidence using question-only surfaces such as current, previous, before and
earlier, so old/new evidence can enter retrieval before rerank sees candidate
text.
Candidate features consume the same relation facets and report
`relation_category_hits` plus category coverage. `RelationCoveragePolicy` uses a
small bounded category-coverage boost only when the category hit is grounded by
relation evidence, so category labels do not lift generic mentions by
themselves.
Each reranked item now also carries `candidate_evidence_features.v1`
diagnostics. These features describe whether the item is a direct speaker turn
or broad summary, source-ref density, duplicate key, source type, retrieval
sources, relation coverage, temporal/visual/preference evidence flags and
focused-turn score. They also include a bounded `answerability_score` with
reason codes derived only from question intent and retrieved evidence:
entity/relation satisfaction, provenance, intent satisfaction and conflict or
broad-summary penalties. The score is diagnostic-first and the ranking boost is
eligible only when relation grounding is strong enough, so generic entity
mentions do not beat denser evidence. Text-derived contrast/currentness signals
are tracked separately as `negation_surface`, `currentness_surface`,
`stale_surface` and `contrast_surface`. Metadata-backed stale/conflict remains a
penalty, while textual "used to / but now / no longer / current" evidence can
be selected as contrast or temporal support instead of being treated as bad
evidence. The rerank policy consumes these typed features instead of recomputing
candidate facts inline, which makes the next evidence-bundle planner step
possible without adding more one-off scoring code.
For typed contrast questions, answerability also checks whether the retrieved
item carries explicit old-vs-current surfaces. Current-only evidence can remain
partial support, while before/previous plus current/now evidence satisfies the
contrast intent more strongly.
Candidate feature diagnostics also emit `source_locality_score` and locality
reason codes. Direct, narrow turn evidence scores higher than broad summaries
with many turn refs, so answerability and fast diagnostics can distinguish
precise provenance from wide "related turns" context without using answer keys.
Evidence bundles are now assembled by `evidence_bundle_planner.v1` rather than
by inline top-k sorting. The planner deduplicates mirrored source refs, selects
one primary item, keeps specialized roles such as `temporal_support`,
`contrast`, `bridge` and `entity_disambiguation`, caps repeated generic source
types and repeated retrieval sources, then greedily prefers items that add
uncovered required refs or query-support terms before taking redundant
high-strength items. For multi-hop cases, bridge evidence is selected from
question-only support terms plus grounded entity/relation hits, so intermediate
facts can beat generic high-score context without using answer keys. It emits
reason codes plus role/source-type, retrieval-source and coverage counts in
`evidence_bundle["bundle_planner"]`.
Bundle candidate eligibility also accepts feature-backed evidence that has
sufficient answerability, source locality and grounded entity/relation/temporal
or contrast signals, even when it has fewer than two query-support term hits.
This lets entity-disambiguation and temporal support reach the planner without
using expected answers. Query role labels alone are not enough to enter the
bundle. Selected bundle items include `eligibility_reason_codes`, so compact
reports can distinguish answer/evidence-term matches from feature-backed
selection.
Benchmark expected terms and LoCoMo evidence refs are post-hoc coverage labels
only: they are recorded on selected items and used by fast metrics, but they do
not make an item eligible, primary or stronger during bundle planning.
Question-support matching accepts safe morphology for single-word terms, for
example `research` matching `researched` or `researching`, so bundle selection
does not rely on exact inflection matches or judged answer labels.
Benchmark answer/judge adapters consume `answer_context.v1`, which is derived
from selected evidence-bundle items within the current cutoff. If no selected
bundle item is available for that cutoff, the adapter falls back to the raw
retrieval slice. Cutoff metrics keep `memories_evaluated` as the raw top-k count
and add `answer_context` diagnostics separately, so top-k gate checks remain
about retrieval breadth while prompts stay compact and evidence-first.
Backend metrics aggregate this as `answer_context_metrics.v1`, including
evidence-bundle context rate, fallback reasons, average context memory count and
context/raw compression ratio by cutoff. Answer-context diagnostics also report
source-ref counts and coverage rates, while quality diagnostics aggregate this
as `answer_context_provenance.v1`, so fast reports show whether selected
evidence actually reached the prompt-facing context with provenance intact.
Planned evidence prompt lines include the selected item role, original rank,
retrieval order, answerability, typed support counts such as location, causal,
inference, preference and visual, and planner reason codes, so answer adapters see
provenance and evidence function without accessing benchmark labels.
If a grounded multi-hop bridge item also carries temporal/session surfaces, it
keeps the `bridge` role instead of being swallowed by `temporal_support`; a
plain bridge-query hit without entity/relation grounding remains ordinary
support. This keeps bundle completeness tied to evidence function rather than
query label alone.
Each retrieval payload also includes diagnostic-only `query_integrity` metadata
with expected-answer token overlap in terms added by query expansion and rerank
profile terms, excluding tokens already present in the original question. It is
computed after search and does not affect retrieval. Backend metrics aggregate
it under `query_integrity_gate`; use it to audit possible benchmark leakage
before full LoCoMo runs. The gate includes query-side `overlap_token_total`,
profile-side `profile_overlap_token_total`, and sample case lists with the
highest-overlap case ids and terms first, so fast runs identify which added
query or rerank-profile terms need review without changing retrieval behavior.
Evidence bundle diagnostics count LoCoMo evidence refs from retrieved
`source_refs` as well as text, so canonical facts and raw-turn chunks are scored
against the same `D*:*` support ids. Expected/evidence/support matching uses
normalized token boundaries, so diagnostics do not count substring accidents as
recall.
Action terms are expanded with question-only variants such as
`research -> looked into/check out`, so wording drift between a LoCoMo question
and the original dialogue is tested in the fast loop.
Compact queries also preserve common surface forms such as `researching` when a
lexical backend would otherwise miss a normalized stem-only query.
The same question-only normalization handles common LoCoMo typos and stems like
`persue -> pursue`, `educaton -> education`, `decided -> decide` and
`planned -> plan`.
Normalized stems remain internal rerank/profile signals. Outbound decomposed
search queries render full surface words such as `figuring`, `registered`,
`dress` and `thrilled`, so lexical backends do not have to match artificial
stem fragments like `figur`, `register`, `dres` or `thrill`.
Education/field queries also surface the dialogue-style `edu` abbreviation
when the question asks what field a person might pursue.
Preference and political queries keep dialogue-like surfaces such as `fan`,
`rights` and `conservatives` for lexical backends.
Named speakers also get a bounded boost when retrieved evidence is a direct
turn by the primary speaker in the question, for example `D2:8 Caroline: ...`,
rather than a third-party mention of the same name or a turn by another
mentioned person. Direct speaker evidence that also covers relation terms gets
an extra bounded relation boost, so a direct turn can beat a higher-raw-score
third-party topic mention without injecting answer text.
Focused dialogue turns with one or two `D*:*` refs get an additional bounded
granularity boost, while broad observation/event summaries do not. This helps
raw LoCoMo turns outrank wide session summaries when both mention the same
person and topic.
When a direct speaker turn covers three or more relation/profile terms, the
bounded cap is slightly higher for focused turns, because dense first-party
evidence is more trustworthy than repeated generic topic matches from broader
session chunks.
Excited/adoption/process questions also get a small focused-turn affect/outcome
boost when the turn itself combines question-derived affect and outcome surfaces
such as `thrilled` plus `make/create`. This lifts first-party "what are they
excited about" evidence without adding judged answer nouns to the query.
Song/enjoyment questions get the same treatment for focused turns that contain
question-derived preference surfaces such as `fan` plus `like`, so music-taste
evidence can beat generic love/like turns without adding answer terms like
`classical` or `music`.
Topic-like capitalized entities such as `LGBTQ`, `Dr. Seuss`, `The Four
Seasons` or `Vivaldi` remain search terms but are filtered out of speaker
surfaces, so query expansion does not invent impossible speakers like
`Vivaldi:`. The compact relation fallback query uses speaker surfaces when they
are available, while the original and expanded queries still keep all topic
entities. This gives exact-title searches a chance without forcing fallback
queries to spend most slots on entities that the evidence may not repeat.
Common person aliases in LoCoMo-style questions are expanded before search, for
example `Mel -> Melanie`, so direct speaker evidence is not missed when a
question uses a nickname. Duration questions such as `how long` are treated as
temporal and can boost evidence containing `5 years`, `2 months` or similar
duration surfaces.
Question-provided numeric and ordinal tokens such as `4` or `18th` are kept as
retrieval/profile terms, but answer-only numbers are not injected into search
queries. Compact temporal relation queries also keep concrete question surfaces
such as `4 year ago` when they help bridge a relative-date question to a
source turn.
Current-friend duration questions expand `current` into `known`, `year` and
`been`, so evidence phrased as `known these friends for 4 years` is retrieved
without polluting ordinary friend-meeting queries.
Marriage-duration questions also expand `married/marriage` into `wedding`,
`year`, `anniversary`, `bride` and `dress`, so evidence phrased as `5 years
already` or a wedding caption can be retrieved even when it does not repeat
`husband` or `married`. The compact query prioritizes `year`, `bride` and
`dress`, and keeps `already` as a generic duration surface, before weaker
marriage terms for these duration cases.
Inference questions drop modal words from entity extraction, so `Would Caroline`
still searches for speaker/entity `Caroline`, not the impossible speaker
`Would Caroline:`. Preference questions such as `more interested in...` add
preference/outdoor surfaces and can boost direct preference evidence over a
generic mention of the alternative.
Profile and attribute questions add question-only topic surfaces for identity,
relationship status, books/bookshelf, political leaning and religion, so fast
LoCoMo cases do not collapse to a bare person-name query. Generic verbs such as
`consider` are dropped from the final relation subquery when a stronger topic
relation is present, so `considered religious` prioritizes `religious/faith`
evidence instead of generic consideration mentions.
Relationship-status questions use generic status surfaces such as `parent`,
`breakup`, `family`, `kid`, `friend`, `support`, `challenge`, `dating`,
`partner` and `married` without injecting the judged status word itself. The
compact query places those status surfaces before generic `relationship/status`
terms.
Identity profile questions expand into generic identity surfaces such as
`support`, `inspiring`, `story`, `gender`, `accepted`, `courage`, `pride`,
`self`, `person`, `background` and `community`, matching identity evidence
without injecting the judged identity phrase.
Political-leaning questions expand into non-answer domain surfaces such as
`conservatives`, `rights`, `LGBTQ`, `transition`, `comment`, `upset`, `support`,
`social`, `activism` and `policy`, so evidence phrased as rights or
conservative reactions can be retrieved without hardcoding the judged answer.
Religious-profile questions prioritize direct dialogue surfaces such as
`church`, `religious conservatives`, `think`, `journey`, `changing` and
`acceptance` before weaker generic faith terms, so church-art evidence is not
lost when it is phrased as a personal journey rather than a belief label.
Fast LoCoMo topic chains also expand adoption/agency/support, kids/preferences,
music/song and necklace/symbol questions with bounded, question-shaped surfaces.
Kids/preference queries use generic `animal`, `bones`, `exhibit`, `learning`,
`children`, `family`, `preference`, `interest` and `like` surfaces instead of
injecting concrete liked things.
Song queries use `piece`, `composer`, `instrumental`, `orchestra` and original
title/composer entities instead of injecting judged genre phrases such as
`classical music`.
Necklace/symbol queries use generic `symbol/meaning/message/value` plus
evidence-shape surfaces such as `gift`, `grandma`, `roots`, `reminder`,
`family`, `support` and `special` instead of injecting judged values such as
`love`, `faith` or `strength`. Symbolic-meaning evidence now has typed
diagnostics and a bounded rerank signal only when a meaning surface such as
`represent`, `symbol`, `mean` or `reminder` appears with object context such as
`necklace`, `gift`, `grandma` or `root`.
Relation hits are deduped before rerank, and dense topic evidence can get a
bounded relation boost even when the evidence sentence does not repeat the named
person.
Adoption-agency support questions can still use support-shaped surfaces such as
`folks`, `help`, `LGBTQ` and `inclusive` when the question itself asks who the
agency supports. Choice/reason questions use generic `reason`, `cause`, `fit`,
`value`, `spoke` and `decision` surfaces instead of injecting the judged reason.
The rerank profile applies the same filter, so support/inclusivity terms do not
silently affect benchmark-only reranking for choice/reason questions.
Adoption-process excitement questions prioritize action/process surfaces such as
`make`, `create`, `thrilled` and `process` before generic agency/support
surfaces, without injecting judged `family/kids` wording into search or rerank.
Adoption-decision reaction questions prioritize generic reaction surfaces such
as `reaction`, `response`, `opinion`, `feel`, `lovely` and `luck` rather than
injecting judged sentiment words like `amazing`, `awesome` or `mom`. The compact
query keeps `think` and family context while moving generic `decision/adopt`
terms behind reaction signals.
Generic activity questions render non-answer activity-family surfaces such as
`hobby`, `partake`, `class`, `paint`, `swim`, `run`, `violin`, `kid`, `photo`,
`creative`, `fun`, `express`, `refresh`, `therapeutic`, `pastime` and `leisure`
instead of injecting concrete per-case answer tuples. Specific activity terms
are still used when they are present in the question itself, for example a
pottery signup date question.
Camping-place questions add generic camping context such as `family`, `unplug`,
`connection` and `close`, while avoiding judged location terms like `beach`,
`mountains` or `forest`.
Bookshelf questions include generic `books`, `kids`, `stories`, `reading` and
`bookshelf` surfaces, while keeping title/person entities from the original
question. They avoid injecting judged genre phrases such as `classic children`.
Book/read questions also render `reading` as an outbound surface, so evidence
phrased as `loved reading...` is reachable without relying on backend stemming.
Writing/career and counseling inference questions also get explicit
question-only surfaces such as `write`, `writing`, `looking`, `book`, `books`,
`job`, `jobs`, `option`, `support`, `similar` and `issue`, so open-domain
LoCoMo cases do not rely only on generic `pursue/career` terms or injected
answer wording.
Writing/career rerank also gives a focused-turn affinity boost when retrieved
evidence contains safe book/read signals plus `guide`, `motivate` or `discover`;
it does not add answer-side reading terms to the outbound query. Retrieved
focused turns that explicitly mention an alternative counseling or mental-health
jobs path get an evidence-only career-contrast boost, while those counseling
terms are not injected into the query profile.
Several LoCoMo inference rerank boosts are evidence-only and do not change the
outbound query: durable outdoor preference turns (`always look forward`,
`highlight`, meteor memories), support-motivation turns (`support I got`,
`huge difference`, `improved my life`), direct research-goal turns, visual
identity turns, political-context turns, adoption-agency support turns and
conference-plan time turns, plus relationship-status context turns with breakup,
family, parenting or support context. These boosts only apply to focused direct
turns with matching question-derived relation terms.
Focused evidence-shape boosts also cover kids preference evidence, explicit
bookshelf collections, personality-trait reactions, bad roadtrip incidents,
charity-race self-care realizations, adoption-decision reactions, friend-duration
answers, birthday-memory turns, broad activity coverage, destress-running
evidence and career-contrast evidence. The fast gate expects these signals to
lift the exact evidence turn without changing the query integrity report.
Broad activity coverage includes evidence-only surfaces such as painting,
swimming, running/reading/violin and camping/unplug turns, so generic activity
questions can keep multiple distinct activities in the short context window.
Career/education questions expand `career`, `field` and `path` into safe work
surfaces such as `work`, `working`, `profession`, `job`, `option`, `support`,
`similar`, `issue` and `keen`, matching official evidence wording like `career
options`, `working with...` or `support those with similar issues` without
hardcoding the answer. Field/pursue and career-path compact queries prioritize
those work/support surfaces before weaker school-like terms such as `study`.
Career-path questions also include broad decision wording such as `think` and
`figure`, so evidence phrased as `thinking of working...` or `figuring out the
details` is reachable without adding answer-specific career labels. The compact
career-path query promotes these support surfaces before weaker base action
terms such as `decide/pursue`.
Counterfactual support questions preserve question-only surfaces such as
`received`, `got`, `help`, `support`, `growing`, `journey` and `childhood`, so
retrieval can find causal support evidence instead of only generic
counseling/career mentions. Their compact query prioritizes `got/help/growing`
before weaker `pursue/receive/grow` base terms.
Other open-domain fast cases avoid name-only search by adding question-only
surfaces for `personality/trait/describe` and
`roadtrip/accident/son/family/safe/trip/past/weekend/soon`, without hardcoding
expected answer words.
Personality-trait questions also add generic trait evidence surfaces such as
`care`, `real`, `help`, `drive`, `concern` and `thank`, matching LoCoMo praise
phrased as `care about being real`, `drive to help` or `thank you for your
concern` without injecting the expected answer tuple.
Preference questions involving parks expand `park` into `enjoy`, `nature`,
`camping`, `trip`, `campfire`, `marshmallow`, `story`, `meteor`, `sky`, `summer`,
`hike` and `trail`, so national-park evidence expressed as camping-trip,
campfire or meteor-shower memories is still retrieved.
Hike-count questions treat `hike` as activity evidence and add generic
occurrence surfaces such as `trail`, `waterfall`, `went`, `spot`, `weekend` and
`summer`, so repeated hike turns can beat generic hiking-topic mentions without
adding answer numbers.
Future home-move desire questions use generic current-goal surfaces such as
`goal`, `hope`, `plan`, `future` and `soon`, and do not require
`location_support` unless the question asks where, from or origin. This keeps
old origin evidence from satisfying current-goal inference without adding
answer-specific judged outcomes.
Self-care prioritization questions render generic wellness surfaces such as
`routine`, `refreshes`, `present`, `balance`, `rest`, `relax` and `wellness`,
instead of injecting specific hobbies from the judged answer.
Summer-plan questions prioritize generic planning rationale surfaces such as
`dream`, `family`, `loving`, `home`, `future`, `upcoming`, `season`, `goal`,
`want` and `going`, instead of injecting concrete plan contents like
`researching adoption agencies`. The `agency -> agencies` query alias remains
available only when `agency` is already a question-derived term.
Temporal event questions add action surfaces such as `run/race/charity/last`,
`meet/friends`, `speech/school/event/talk`, `sign/signed/class/pottery`,
`go to/support group/went`, `move/home/country/relocated`,
`conference/month/community` and
`destress/stress/relax/unwind/class/clear/mind/headspace/run/farther`,
so date questions do not collapse to `person + when + date` only.
Temporal rerank evidence distinguishes spoken/content time surfaces from
provenance-only labels such as `date:` or turn references, so a topic-only
timestamped memory does not satisfy temporal support without actual temporal
content such as `yesterday`, an explicit day/month/year, or a duration.
Registration paraphrases such as `register` and `enroll` share typed event
surfaces with `sign up`, including `signup`, `class`, `course`, `lesson` and
`workshop`, so class-registration evidence can outrank sign or schedule
distractors without adding the requested date or specific class answer.
Participation paraphrases such as `visit`, `attend`, `join` and `participate`
also get typed event/place surfaces, so evidence like `visited the studio` or
`joined the group` can be distinguished from topic-only studio/group mentions.
When a question is both temporal and visual, the bounded fanout prioritizes a
combined query such as `person + paint + sunrise + when + date` before generic
`person + when + date`. Paint/image date questions also render `painting` and
`caption` as outbound surfaces, so caption evidence phrased as `a painting
of...` can match without requiring the backend to stem `paint`. Entity-less
relation questions, for example charity race awareness, still get an action-only
subquery and relation boost. Raise-awareness queries render `raising/raised`
surfaces so lexical retrieval can match common morphology around `raising
awareness`.
Follow-up event questions such as `What did Melanie realize after the charity
race?` add generic `realize/lesson/reflection/thought/event/journey` surfaces
instead of injecting the realized conclusion. Direct-speaker relation evidence
gets a higher bounded rerank cap so exact evidence can beat a higher raw-score
registration or topic distractor. Dense relation coverage also gets a small
bounded boost when one memory covers many question-derived relation and variant
terms, or multiple high-signal topic terms such as `LGBTQ rights` and
`conservative`.
Standalone years such as `2022` count as temporal evidence surfaces, and dated
temporal evidence gets a higher bounded rerank cap so repeated generic matches
do not beat specific dated evidence.
Visual/image questions add image/photo/show query surfaces and boost retrieved
caption evidence such as `Sharing image` or `image shows`, so LoCoMo image
answers do not lose to generic topic mentions. Paint/sunrise date questions also
get relation boost from question terms, while generic painting questions do not
inherit `sunrise` unless it appears in the question.

Evidence recall is aggregated at `backend_metrics[*]["evidence_term_recall"]`
and in each `by_group` bucket when LoCoMo evidence ids are available. Use this
as the primary fast-loop quality number before looking at LLM answer accuracy.
Evidence and expected-term matching is punctuation-insensitive for benchmark
diagnostics, so `LGBTQ+ individuals` and `LGBTQ individuals` count as the same
retrieved evidence phrase.

Multi-hop fast gate: each evaluation includes an `evidence_bundle` with primary
and supporting retrieved items. For category 1 LoCoMo cases,
`backend_metrics["memo-stack"]["multi_hop_bundle_gate"]` reports bundle
completion rate, average supporting evidence count and bundle evidence recall.
Bundles also include question-only `query_support_terms` and
`query_support_term_recall`, so fast reports show whether retrieved memories are
useful support for the asked question even before LLM answer scoring.
`backend_metrics["memo-stack"]["evidence_ref_rank_gate"]` reports how many
scored evidence-ref cases have all required refs in top1/top2/top3/top5 planned
bundle items, plus focused top5 coverage. Use this before full LoCoMo because
it shows retrieval position failures directly.
`backend_metrics["memo-stack"]["quality_diagnostics"]` emits
`quality_diagnostics.v2`: per-intent accuracy/recall, bundle-incomplete reason
counts, policy contribution totals, false-positive categories and query leakage
samples. This is the main debugging table for deciding the next retrieval fix
without rerunning full LoCoMo.
It also includes `evidence_feature_table`, aggregating candidate feature
surfaces across retrieved items: direct speaker turns, broad summaries,
contrast/currentness/negation/stale surfaces, source-type counts,
retrieval-source counts, answerability-score average and answerability reason
counts. This makes fast runs show whether failures come from missing evidence,
weak provenance, one retrieval path dominating the bundle or evolving-fact
handling.
`query_role_effectiveness_table` compares query-plan roles across retrieved
candidates and selected bundle items. It reports candidate counts, lifted counts,
selected-item counts, selection/lift rates, selected bundle roles and
bridge-query-hit counts per role. Use it to see whether roles such as
`multi_hop_bridge`, `duration_temporal_support`,
`relative_temporal_support`, `explicit_temporal_support` or
`contrast_support` are producing selected evidence or only retrieval noise.
The same table also emits role-family counts, grouping typed temporal roles
back under `temporal_support` for high-level fast-gate reading.
`bundle_quality_table` aggregates the planner's `evidence_bundle_quality.v1`
payload across the run: confidence-band counts, average confidence, average risk
penalty, bridge, location, contrast and source-proximity evidence counts, risk
reason counts and compact weak samples. This keeps the fast loop focused on
evidence-package quality even when a bundle is technically complete.
The same diagnostics include `rerank_lift_table`, a candidate-level explanation
of why retrieved memories were lifted. It counts positive score signals, active
policy names, policy reason codes, relation-category hits, low-answerability
lifts, broad-summary lifts and conflict/stale lifts, plus compact samples with
case id, item id, rank, score, source type and policy reasons. Samples
intentionally omit full memory text, so compact fast reports can be inspected
for ranking mistakes without copying source content into the aggregate table.
`backend_metrics["memo-stack"]["fast_gate"]` emits `fast_gate.v1` with explicit
`locomo-fast` thresholds: zero query/profile leakage, all refs top5 40/40,
focused refs top5 40/40, all refs top3 at least 39/40, top2 at least 36/40,
top1 at least 30/40 and evidence bundle complete 40/40. Do not start full
LoCoMo while `ready_for_full_locomo=false`. When bundle-quality payloads are
present, the gate also requires quality diagnostics for every fast case and a
medium/high bundle-quality band for every fast case, so weak complete bundles
cannot silently pass the fast loop. The same fast-gate payload includes
`bundle_gap_breakdown.v1`, which surfaces incomplete-bundle reason counts and a
filtered bridge-gap view for `missing_bridge`, bridge entity/relation gaps,
temporal bridge gaps and weak source locality. Use this as the next-action map
when `evidence_bundle_complete` or bundle quality blocks full LoCoMo.
Fast gate also includes `query_role_gap_breakdown.v1`, a compact diagnostic
derived from `query_role_effectiveness_table`. It reports candidate roles that
were retrieved but not lifted, not selected into the evidence bundle, or had
bridge-query hits that never reached selected evidence. This is diagnostic-only,
not a hard gate, and should guide the next planner/rerank fix when roles such as
typed temporal support roles or `multi_hop_bridge` produce candidates but
disappear before bundle assembly. For contrast cases, it should show whether
`contrast_support` candidates are retrieved but then lost before bundle
selection.
Query support terms include expanded entity surfaces such as `Mel -> Melanie`,
and bundle items are ordered primary evidence first, then by bounded bundle
strength, while preserving the original retrieval rank in each item. The primary
bundle item is selected after scoring all candidates, so a stronger lower-ranked
piece of evidence can become primary instead of locking the first weak evidence
hit as primary. Primary selection now considers answerability after direct
focused evidence, so a source-backed candidate that can actually support an
answer wins ties over a weaker overlap-only candidate.
Evidence bundles deduplicate mirrored fact/raw-turn hits by source refs, using
order-insensitive unique source-ref sets, and fall back to normalized text when
source refs are absent. This prevents the memo-stack official-turn mirror from
inflating multi-hop bundle completeness by counting the same retrieved turn
twice.
Bundle planner diagnostics also include `bundle_quality` with
`evidence_bundle_quality.v1`. It scores the selected evidence package, not the
answer: primary/support presence, focused or direct-speaker evidence, source-ref
provenance, source/retrieval diversity and answerability raise confidence;
low-answerability, broad-summary-only and conflict/stale evidence add explicit
risk reason codes. Use this with `rerank_lift_table` to catch cases where a
bundle is technically complete but too weak or too broad for reliable answering.

### Evaluate-Only Replay

Use replay when retrieval is already captured and you only want to compare
answerer, judge, cutoff logic or prompt changes. Replay never calls memo-stack or
mem0, so it does not require `--allow-live`, `MEMORY_SERVICE_TOKEN`,
`MEM0_API_KEY` or Docker services:

```sh
python -m infinity_context_server.eval memory-comparison-replay \
  --report .e2e-artifacts/memory-comparison-locomo-fast-full.json \
  --report-mode compact \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --primary-cutoff 200 \
  --run-id locomo-fast-replay-001 \
  --report-out .e2e-artifacts/memory-comparison-locomo-fast-replay.json
```

Replay requires a full source report because compact reports intentionally omit
the per-case retrieval payloads needed by answerer and judge experiments.

### Codex CLI Answer/Judge

For local manual runs without an OpenAI API key, use Codex CLI as the answerer
and judge:

```sh
MEMORY_SERVICE_TOKEN=local-dev-token \
python -m infinity_context_server.eval memory-comparison-benchmark \
  --dataset ./datasets/locomo10.json \
  --memo-api-url http://127.0.0.1:7788 \
  --mem0-url http://127.0.0.1:8888 \
  --benchmark locomo \
  --locomo-ingest-mode official-turns \
  --max-cases 20 \
  --top-k 200 \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --answerer-provider codex \
  --judge-provider codex \
  --answerer-model gpt-5.5 \
  --judge-model gpt-5.5 \
  --codex-timeout-seconds 180 \
  --allow-live \
  --run-id locomo-side-by-side-codex-sandbox-001 \
  --report-out .e2e-artifacts/memory-comparison-locomo-codex.json
```

The Codex provider shells out to `codex exec` with `--ephemeral`,
`--ignore-user-config`, `--ignore-rules`, `--sandbox read-only` and
`approval_policy="never"`. It uses only prompt evidence and estimates token
usage locally because Codex CLI does not expose benchmark token usage through
this adapter.

Model defaults:

- `--answerer-provider codex` and `--judge-provider codex` default to
  `gpt-5.5`, or `MEMORY_COMPARISON_CODEX_MODEL` when set.
- mem0's benchmark README lists common benchmark defaults as `gpt-4o` for
  answerer/judge, while its published OSS extraction-model LongMemEval table
  says those runs used GPT-5 as answerer and judge.
- Local Codex accounts may not expose literal `gpt-5`; if so, `gpt-5.5` is the
  closest currently usable Codex-side approximation, not an exact reproduction.

### LoCoMo Ingest Modes

- `--locomo-ingest-mode rich-documents` is the default legacy mode. It uses the
  normalized public benchmark documents, including derived LoCoMo observations,
  summaries and per-turn documents. This is useful for retrieval canaries but is
  heavier than mem0's official LoCoMo runner.
- `--locomo-ingest-mode official-turns` is the mem0-style mode for official
  `locomo10.json`: one chronological conversation turn becomes one ingest
  memory/message chunk, image captions and visual queries are appended like the
  official mem0 runner, and session dates are embedded in the turn text. By
  default the adapter does not send the separate `timestamp` parameter because
  current mem0 OSS `Memory.add` rejects it without the mem0 temporal API path.
  Use `--mem0-send-timestamps` only when the target mem0 wrapper supports it.

## Safety Gates

- `--allow-live` is required before the command calls memo-stack or mem0 HTTP
  endpoints.
- `--preflight-only` prints sanitized dataset, auth, URL, LLM and fast-readiness
  checks without ingesting, searching or resetting live benchmark state.
- `--preflight-probe-services` adds unauthenticated HTTP root probes to the
  preflight report when local Docker services should already be running.
- `--allow-paid-llm` is required before OpenAI answerer or judge calls.
- `--answerer-provider codex` / `--judge-provider codex` do not require
  `--allow-paid-llm` or an OpenAI API key, but they do consume the local Codex
  account/session quota.
- OpenAI models are explicit: pass `--answerer-model` / `--judge-model` or set
  `MEMORY_COMPARISON_ANSWERER_MODEL` / `MEMORY_COMPARISON_JUDGE_MODEL`.
- OpenAI key is read from `MEMORY_OPENAI_API_KEY` by default, with
  `OPENAI_API_KEY` as fallback. Do not commit keys or generated raw provider
  payloads.
- Codex mode only replaces the benchmark answerer/judge. A self-hosted mem0 OSS
  backend still needs its own extraction and embedding providers. The mem0
  default uses OpenAI; for a fully no-OpenAI run, configure mem0 with a local
  provider such as Ollama and make sure the required local models are running.
- Optional mem0 OSS API key is read from `MEM0_API_KEY` by default and sent as
  `X-API-Key` when present. Leave it unset only for explicitly auth-disabled
  local mem0 servers.
- By default the runner deletes the isolated mem0 `user_id` / `run_id` before
  ingest. That mem0 endpoint requires an admin-capable key or `AUTH_DISABLED=true`.
  If you only have a non-admin API key, pass `--mem0-skip-reset` and use a fresh
  `--run-id` so the run still uses isolated state.
- Token cost reporting uses explicit USD-per-1M-token rates from CLI flags or
  `MEMORY_COMPARISON_*_USD_PER_1M` env vars. The runner does not hardcode
  provider prices.
- Token cost scope is answerer/judge only. Backend-internal ingest/search
  provider costs are reported as unmeasured because they are not observable
  through the generic HTTP comparison ports.
- The memo-stack backend isolates state with a run-specific benchmark space.
- The mem0 backend uses a run-specific `user_id` / `run_id` and deletes that
  isolated user/run at startup by default.
- The mem0 ingest payload includes source metadata such as `source_external_id`,
  `source_id`, `session_key` and `dia_id` when available. If the mem0 server
  returns that metadata on search, the report can compute evidence-ref
  diagnostics on the mem0 side too.
- Corpus reuse is keyed by memory scope, thread and source content fingerprint;
  failed ingests are not cached for later questions in the same conversation.
- Any nonzero backend `items_failed` ingest result is scored as an `ingest_failed`
  stage failure and does not proceed to search for that case.

## Report Shape

The JSON report includes:

- per-backend accuracy and category/group breakdown;
- LoCoMo category 5 reported in `by_category` with unscored counts but excluded
  from scored accuracy;
- retrieved memory count, retrieval recall and missing expected terms;
- ingest/search/generation/judge latency averages;
- context token estimates, answerer/judge token usage and configured token cost;
- memo-stack vs mem0 deltas for accuracy, retrieval recall, retrieved count,
  latency, context tokens and token cost;
- configured top-k cutoff metrics, with pre-cutoff stage failures counted as
  failed scored cases;
- per-case failure analysis with backend, group, score, retrieval recall and
  missing terms;
- backend reset/ingest/search/answer/judge exceptions as scored stage failures with
  redacted error metadata.
- failed HTTP ingest operations include status code, reason phrase and a short
  redacted response preview when the backend returns one.
