# Memory quality, integrity and scheduling verification — 2026-10-22

Experimental base revision: `85619a89847a2ec850978fb68140e38678a0570b`.
Final integration base: `9669200b7bcd45e9955e3217b1b83601977774a4` (the
independently merged PRs #87 and #88). Their production/probe code is retained;
this work also qualifies interpretations in PR #88's report.
The work prioritizes faithful stored evidence and measurable retrieval outcomes,
then request latency. A more complex retrieval mechanism is not accepted merely
because it uses a learned model.

## Independent planning and review

Three parallel directions used GPT-6.1 Sol at xhigh effort: retrieval scheduling,
quality experiments, and canonical-data/outbox integrity. The coordinator owned
evaluation artifacts and integration. Each production plan received an
independent critique before implementation; requested revisions were reviewed
again. Implementation review was separate from authorship.

| Direction | Plan decision | Material correction from independent review |
| --- | --- | --- |
| Outbox ownership | Revision 2 approved | Use a fresh claim token, not retry count; fence all lifecycle writes and check queued work before dispatch. Implementation review also found a stale administrative replay race. |
| Document identity | Revision 2 approved | Separate new document digests from legacy lowercased inputs; accept legacy reuse only when complete original content can be proved. No guessed reconstruction or canonical-ID backfill. |
| Derived retrieval scheduling | Revision 2 approved | Private lane diagnostics, parent-owned timing spans, stable merge order, joined cancellation, real database visibility/resource tests, and bounded measurements. |
| Paired answer evaluator | Revision 2 approved | Bind runs to actual inputs/configuration/source bytes; retain private candidates; distinguish resolved pairs from failed or missing observations. Implementation review rejected malformed explicit verdicts that could be counted as correct. |
| Optional residual reranker | Feasibility only approved | Test a real model through the actual packer before adding product machinery; preserve reserved evidence and redact model inputs. The measured gate failed, so the adapter was not implemented. |
| Person-anchor prefix hypothesis | Scratch counterfactual approved | Preserve the following full name, correct ambiguous labels before outcomes, and check actual newly selected distractors. The held-out gate failed; production extraction remains unchanged. |

The separately owned PR #87 and its term-frequency/cache changes are outside
this work. The scheduling measurements use experimental base `85619a89`, not
that PR's patch.

## Faithful document identity

Previously, ordinary document identity used the shared lowercase/whitespace-folded
digest. A mounted HTTP reproduction showed that `return UserID` followed by
`return userid` could return the same document ID and the first document's
chunks. Case and indentation can change the meaning of stored code, so this is
an evidence-integrity defect even when retrieval finds that document correctly.

Ordinary and projected document ingestion now use a document-only, versioned
SHA-256 domain with the existing document-text normalization. Internal case,
indentation and spacing remain significant; line-ending and outer-whitespace
normalization remain supported. The shared hash used by episodes and managed
benchmark protocols is unchanged. Existing canonical IDs, hashes, receipts and
locator ownership are retained.

Legacy reuse is conservative: one complete, owned, active, full-span chunk
must prove the original source. An unprovable legacy retry with an existing
explicit key conflicts; an ordinary content-only import can create one new
versioned document and subsequently deduplicate against it. Lossy or
multi-fragment historical source is not reconstructed from guesses. Projected
locators cannot be rebound. The strict managed-writer protocol keeps its
existing digest/key format and rejects collisions or unprovable replay.

Every successful replay validates the receipt type, canonical scope/status,
chunk ownership, source identity and complete expected fragment projection.
Modern ranges must be real integers, nonnegative, ordered and long enough
for the stored chunk. Absolute positive offset shifts cannot be authenticated
when the original full-source layout was not retained; equivalent retries
preserve stored citation offsets. Legacy full-source proof is stricter.

Conflict recovery uses fresh transactions. In particular, two concurrent
requests with different explicit keys but the same body bind both keys to the
winning document before reporting success; subsequent different-body reuse
of either key conflicts. A bounded further fresh read handles a race while
saving that receipt, with the same admission and replay validation.

Focused domain/API tests and real PostgreSQL HTTP tests cover case and
indentation distinctions, exact and line-ending retries, legacy lossy source,
receipt/canonical corruption, invalid ranges, concurrent same-key writes,
different-key receipt binding, projected locators and authenticated strict-v4
writer behavior. Same-key/same-body concurrent requests leave one document
and one set of projection jobs; different bodies with one key produce a
creation and a conflict. These are storage and replay correctness results,
not measured improvements in generated-answer accuracy.

## Outbox claim ownership

A worker can outlive its lease. Previously its acknowledgement, retry or
heartbeat could still mutate a job already reclaimed by another worker.
Retry counters alone cannot identify ownership because resets and deferrals
can reuse the same value.

Migration `0061_outbox_claim_ownership` adds a nullable claim token. Each
claim receives a fresh token; heartbeat, acknowledgement and retry writes
atomically require the same running row and token. Pre-dispatch refresh
prevents queued work from starting under an expired claim, and interrupted
handler/heartbeat tasks are cancelled and joined. Completion and rescheduling
clear the token. Administrative dead-job replay now locks eligible rows with
`FOR UPDATE SKIP LOCKED`, so a stale selection cannot overwrite a newly
running job. The independently authenticated projection-receipt protocol
retains its own authorization checks while clearing generic claim state.

The real PostgreSQL test upgrades an existing schema from 0060 to 0061 and
uses blocked statements and competing transactions to verify stale-worker
acknowledgement, retry and heartbeat, reused retry counts, and overlapping
administrative replays. SQLite compatibility and cancellation/resource tests
cover the local runtime as well. These checks fence canonical job state;
external provider operations still need deterministic IDs and idempotent
handlers. The change does not promise exactly-once external effects.

Deployment requires draining older unfenced workers and older document
writers before routing work to the new binaries. Existing running rows with
no token age out through the normal lease timeout. The detailed compatibility
and rollout limits are in the
[self-hosted deployment guide](../self-hosted-team-deployment.md).

## Trustworthy answer-quality experiments

The paired runner now uses a schema-2 manifest binding the selected pack
contents, model/runner configuration, prompts, and evaluator/helper source
bytes. Compatible resumes retain completed arms. Changed inputs, duplicate
records, incompatible metadata, malformed complete lines, and unbound old
directories are rejected before provider calls. Only a broken unterminated
final line is eligible for repair. A process lock prevents two writers from
using the same directory.

Full candidate answers remain in private mode-0600 records inside a mode-0700
directory. The aggregate uses a fixed projection without questions, reference
answers, context, candidates, or case IDs. Expected/resolved denominators,
missing observations, unresolved verdicts, and resolved paired improvements or
regressions are explicit. Invalid, truncated, duplicate-key, contradictory, or
wrong-shaped structured verdicts remain unresolved. A run with unresolved
outcomes exits nonzero; resuming does not silently erase its failed records.

If submission or result handling fails or is interrupted, the evaluator cancels
queued arms and joins already-running work before releasing the run directory
lock. This cleanup does not terminate active provider subprocesses or recover
results that were never written.

The original 74 focused tests cover real CLI subprocesses with a local deterministic
runner, manifest mismatches, concurrent locking, partial writes, corruption,
permissions, public-output privacy, and paired accounting. They test the
measurement machinery; they are not a live answer-model quality experiment.

Historical reports were corrected without inventing new observations:

- [Paired answer evaluation r1](answer-quality-paired-eval-r1.md) distinguishes
  frozen-context replay from a fresh ingestion/retrieval/answer chain. Main-100's
  historical paired counters include unresolved arms; corrected resolved-pair
  counts require the original private records.
- [Answer-failure map r1](answer-failure-vein-map-r1.md) treats gold-string/token
  matches as lexical diagnostics. They do not prove the requested subject,
  relation, time, or polarity is supported, or classify all 42 matched failures
  as answerer failures. Unparsed judgments are not confirmed regressions.
- [Competitor-lever probes r1](competitor-levers-requery-temporal-r1.md) retains
  its historical counters while qualifying causal and method-wide conclusions.
  The committed mixed-token probe matches space-joined bigrams against unigram
  sets, so its rows do not establish that correct bigram matching is ineffective.
  Missing time fields are an evaluation limitation, not a measured rejection
  of temporal filtering. No private-host experiment was rerun for this review.

The private frozen Main-100/held-48 inputs and their original measurement host
were not available in this workspace. No fresh score on those sets is claimed.

## Real learned reranker feasibility: rejected

A fresh authored English corpus was frozen before outcomes: 16 questions and
64 documents, SHA-256
`b1dc2b1c6dee32aa8ce0ce3f68940a832325d2d1699c61f5fc6c8754b84b1c23`.
Every document entered through the HTTP ingestion route. All three arms used
the actual context route and packer with a 220-token budget, zero facts and a
maximum of 12 chunks. The optional embedding/vector/graph providers were
disabled so the experiment isolated residual ordering.

The real local model was `Xenova/ms-marco-MiniLM-L-6-v2`, revision
`a09144355adeed5f58c8ed011d209bf8ee5a1fec`, through FastEmbed 0.8.0 on CPU. Its
ONNX file SHA-256 was
`c623d0bcb99f4622beb413eaef00cfbe5db20df9f1dd982da4b4f26022881870`.
Scratch instrumentation exposed the packer's residual candidates after its
existing reservations. Learned ordering was limited to those residuals and
existing source-diversity partitions. Protected evidence, original text,
legacy scores, citations and authority were retained.

| Arm | Complete authored supporting evidence selected | Previously reserved evidence preserved |
| --- | ---: | ---: |
| Baseline | 12/16 | 16/16 |
| Baseline order with the same protection | 12/16 | 16/16 |
| Real learned residual order with protection | 12/16 | 16/16 |

There were zero improvements, zero regressions, and identical final selected
item keys on every case. The model changed residual order on two cases but did
not change selected evidence. Nine actual model calls scored two candidates
each; inference p50 was 27.2 ms and maximum was 99.3 ms. This is not a
48-candidate latency qualification. The complete successful experiment took
11.28 seconds, including document ingestion and 48 HTTP context calls.

Three missing target sources were rejected before residual selection by
anchor-conflict admission. In the fourth miss, two protected chunks consumed
the budget before the desired residual evidence could be selected. The
experiment therefore provides no reason to ship a residual reranker adapter.
The authored scorer checked the full supporting sentence on the labeled
canonical source; it did not generate or grade answers. These results do not
measure Russian quality, a public benchmark, or competitor performance.

The original counts are retained in
[the feasibility aggregate](data/residual-reranker-feasibility-20261022.json).

## Anchor-prefix follow-up: rejected after held-out evaluation

The reranker experiment exposed an earlier admission failure: English person
extraction can include the preposition in `For Beacon`, producing a conflicting
anchor. A narrow scratch counterfactual kept the match start at the prefix
while excluding `For` from the captured name. It preserved the following
two-token names and initials; it did not disable anchor conflict checks.

The 16 previously examined feasibility cases became development data. On
those cases the counterfactual changed complete supporting evidence from
12/16 to 13/16, with no loss. That was a mechanism check, not held-out evidence.

A separate 24-question/48-document authored set contained eight positive
cases, eight adversarial controls and eight Russian controls. Independent
review corrected three ambiguous labels before any held-out outcomes, then
the revised set was frozen with SHA-256
`f818843e06f25912c24ebd729c278f44ae9671f5bf2e20d3e64b79ff8f276b0a`.
The single held-out comparison used the same canonical store, populated
through HTTP under the original extraction pattern, and the same 220-token
context budget. No production source was edited.

| Held-out measure | Baseline | Counterfactual |
| --- | ---: | ---: |
| Complete required supporting evidence selected | 18/24 | 22/24 |
| Positive cases with complete supporting evidence | 2/8 | 6/8 |
| Adversarial controls retaining required evidence | 8/8 | 8/8 |
| Russian controls retaining required evidence | 8/8 | 8/8 |
| Cases with newly selected labeled distractors | — | 4 |

There were four evidence improvements and no loss of required evidence, but
the counterfactual newly admitted and selected distractors about a draft
form, a rejected bypass proposal, a search workshop and a UI pause. The
rejected proposal may partly support a negative answer; the unrelated search
and UI material still violates the predeclared zero-new-unrelated-selection
gate. Required-evidence recall alone would conceal this tradeoff.

An additional development compatibility case improved with nine previously
persisted anchor rows remaining byte-identical; it also newly admitted an
unselected distractor. That check does not establish historical-corpus
compatibility in general. The complete held-out run took 8.05 seconds. The
conservative gate failed, and the person-extraction implementation remains
unchanged. Counts are retained in
[the held-out aggregate](data/anchor-prefix-holdout-20261022.json).

## Derived retrieval scheduling

Canonical collection still runs first. The existing vector, graph and RAG
collectors then run as at most three owned tasks. Results and flat diagnostics
merge in their previous vector/graph/RAG order. Timing spans are recorded on
the parent dictionary. Every child is joined on success, unexpected failure,
or cancellation, including repeated cancellation during cleanup. Existing
provider deadlines and final canonical visibility checks remain in place.

The focused validation comprises 10 helper/BuildContext tests and three real
PostgreSQL/Qdrant tests. It covers exact stable output, reverse completion,
canonical-only behavior, timeout fallback, request-cache lifetime, a canonical
deletion committed after early vector hydration, and cancellation while three
UoWs await one database connection. The real Qdrant smoke compares populated
index results and confirms a stale hit is removed after canonical deletion.
The existing 128 provider/collector tests and 50 relevant architecture tests
also passed.

### Controlled scheduling measurement

The actual FastAPI route was mounted through HTTPX ASGI transport, with real
PostgreSQL 18.4 canonical reads/hydration. The I/O workload injected one
40/80/120 ms delay per vector/graph/RAG lane; the disabled workload used the
normal disabled adapters. This includes parsing, authentication, canonical
reads, packing and response serialization, but excludes TCP transport and
does not model a real provider's latency distribution.

The comparison replaces only scheduling inside the same loaded application:
the baseline awaits the existing lanes sequentially, and the candidate uses
the new helper. Run 1 used ten warmups plus 120 measured requests per
configuration; run 2 counterbalanced arm order with ten warmups plus 100
measured requests. There were 1,760 measured requests in total.

| Run | Workload | Clients | p95 baseline → candidate, ms | Change | Throughput baseline → candidate, requests/s |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Controlled I/O | 1 | 368.8 → 284.0 | −23.0% | 2.87 → 4.23 |
| 2 | Controlled I/O | 1 | 418.3 → 266.3 | −36.3% | 2.76 → 4.42 |
| 1 | Controlled I/O | 8 | 1064.8 → 1185.3 | +11.3% | 9.19 → 8.48 |
| 2 | Controlled I/O | 8 | 1102.0 → 1134.7 | +3.0% | 8.73 → 8.92 |
| 1 | Disabled providers | 1 | 115.7 → 132.3 | +14.3% | 10.88 → 10.38 |
| 2 | Disabled providers | 1 | 233.1 → 149.7 | −35.8% | 6.77 → 9.17 |
| 1 | Disabled providers | 8 | 973.2 → 1103.5 | +13.4% | 11.69 → 11.02 |
| 2 | Disabled providers | 8 | 883.7 → 794.7 | −10.1% | 10.97 → 11.76 |

All measured responses matched their paired semantic digest after removing
request/bundle IDs and timing fields. No errors, timeouts, or checked-out
connections remained. Lane spans overlap and must not be summed into total
request time. The sequential oracle did not instrument individual lane spans;
whole-request elapsed time is the comparison metric.

The single-client controlled-I/O improvement repeated. Eight-client speed and
deployment tail non-inferiority are unestablished: p95 was higher in both I/O
runs, while throughput and disabled-provider direction changed substantially.
Unrelated shared-host CPU activity was observed even during a coordinated
quiet window. That explains the measurement limitation but does not prove all
differences are environmental. No production pool, common deadline, hybrid
flag or global concurrency policy was changed to chase these samples.

The original [run-1](data/derived-context-scheduling-20261022-run1.json) and
[run-2](data/derived-context-scheduling-20261022-run2.json) aggregates are retained.
Their `patch_sha256` is an end-of-run tracked-diff digest, excluding newly
created files and potentially including unrelated concurrent edits; it is not
a complete pre-run executed-source attestation. The helper retained after
measurement has SHA-256
`0ca0decfb6c63400b631b030c599a05edf74d8aa074266d8bc256ae5633fefc3`.

## Runtime baseline and remaining qualification

The locked local runtime used Python 3.12.14, PostgreSQL 18.4 and Qdrant 1.18.0.
The initial representative memory/provider/API regression selection passed
100 tests with two skips. All seven existing deterministic memory evaluations
passed. The unmodified base's complete real-Qdrant locator acceptance passed
all four tests in 183.34 seconds, including the 16,385-point profile and a
fresh process with separated runtime identity.

That last suite ran from a readable disposable checkout: the application
intentionally drops privilege, whereas this workspace's parent directory is
private. Moving the test environment preserved the identity boundary; no
production permission or identity check was relaxed. Changed generic-context
code also has its own three passing real PostgreSQL/Qdrant cases described
above. All seven deterministic evaluations passed again after the production
changes and again after integrating PRs #87 and #88. The latter combined-head
check also passed 21 lexical/scheduling coexistence tests. Final lint,
file-size boundaries and the repository secret scan passed locally. Repository
CI is the final integration gate on the combined published revision.

These experiments establish specific correctness and scheduling results.
They do not establish a general answer-accuracy gain, production saturation
capacity, or superiority over competing memory systems. Such claims require
complete matched end-to-end experiments on representative, separately held
questions, with errors and unresolved outcomes included.
