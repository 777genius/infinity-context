# Generic Retrieval evaluation

Status: deterministic provider-free evaluation tooling. This is not production
qualification evidence and does not mount or call a retrieval service.

## Boundary

The scoring domain in
`infinity_context_core.features.context_building.domain.retrieval_evaluation`
accepts only ranked opaque locator identities, explicit integer ranks through 10,
graded gold locator relevance, forbidden-scope locator identities, outcome status,
integer microsecond latency, and integer byte counts. It has no server, database,
provider, clock, model, answer, prompt, claim, citation, or client-specific types.

The frozen fixture at
`tests/fixtures/retrieval_eval/locator-eval-synthetic-v1.json` is deliberately small
and synthetic. It contains generic records with opaque locator IDs, natural query
text, explicit attributes, hard filters, one-hop relations, graded gold sets,
same-scope filter exclusions, unsupported cases, and separate true cross-scope
attacks. A deterministic topology validator proves the expected locators obey the
declared scope, filter, and neighbor rules; it is not a retrieval engine.

The loader accepts only the exact `generic-retrieval-v2-dataset.v1` shape. It rejects
unknown or missing fields, duplicate JSON keys and IDs, floats, malformed values,
invalid relevance, nonexistent references, conflicting filter authority, and scope
authority substitution. Schema, records, queries, filters, relations, and expected
sets are all part of the dataset digest.

## Deterministic metrics

Recall@5 and Recall@10 are micro-averaged over all gold locator identities. MRR@10
and nDCG@10 are macro-averaged over cases that have at least one gold locator. A
failed or timed-out gold-bearing case remains in every relevant denominator with
zero retrieved gain. A no-gold case is excluded from ranking denominators and is
reported separately, including whether it unexpectedly returned any locator.
When a dataset has no gold-bearing cases, each ranking metric is represented as
`0/0` and cannot pass a positive qualification gate.

Cross-scope leakage counts each explicitly forbidden locator and every corpus or
unknown locator that violates the case's exact scope. The separate topology count
is stricter: every returned locator must be in the canonical corpus and match every
hard filter, or be an allowed one-hop neighbor when the case enables expansion.
Every neighbor must independently satisfy the exact scope, source, time, attribute,
and other filter values of the seed request. Expansion cannot launder a hard-filter
failure. Explicit filter exclusions remain excluded even when adjacent to a legal
seed. Filter-excluded, unlisted wrong-scope, unknown/stale, and illegal-neighbor
locators are zero-tolerance qualification failures, even when they were not
hand-listed as forbidden.
Duplicate returned locators are invalid. Equal ranks use competition ranking (for
example `1, 1, 3`); overlapping ranks such as `1, 1, 2` fail closed. Missing ranks
are allowed. Tie rows are canonically ordered by opaque locator.

nDCG uses gain `2^relevance - 1` and the frozen integer discount table documented in
the module. Each discount is `round(10^12 / log2(rank + 1))`. This makes the defined
evaluation policy an exact rational calculation. Tied items receive the mean of the
integer discounts for the positions they occupy.

Latency p50, p95, and p99 use the nearest-rank method over every request outcome.
Request and response byte totals and maxima also include successes, failures, and
timeouts. Evaluation does not measure time itself; a runner must supply measurements
from a monotonic clock and exact serialized byte counts.

## Canonical evidence and binding

Evidence JSON is UTF-8, compact, and lexicographically key-sorted. Dataset cases,
corpus locator IDs, query/filter IDs, gold rows, forbidden locators, observations,
ties, and gate rows have canonical ordering. Hashed evidence rejects floating-point
and non-JSON values. Metrics use integer values or `{numerator, denominator}`
rationals. The bundle exposes immutable canonical JSON and immutable SHA-256 entries
for binding, dataset, observations, metrics, qualification profile, qualification,
and the complete manifest. Mandatory verification re-canonicalizes retained bytes,
parses the strict dataset and observations into domain values, independently
recomputes metrics and gates, and compares every semantic payload plus every
component and root digest. Ranked failure rows, substituted gold, false gates,
changed accounting, mismatched identities, and consistently rehashed forgeries fail.
Verification returns a newly constructed immutable canonical snapshot.
Retained observations occur exactly once each and in registered dataset case order.
Builders emit that order regardless of caller input order; verification rejects
duplicate or reordered arrays even when every component and root hash was
consistently recomputed.

A qualification binding contains all of:

- service revision;
- core revision;
- Retrieval contract and ranking policy;
- capability fingerprint;
- retrieval profile;
- index identity;
- dataset digest;
- cleanup receipt.

Scoring may run for any caller-created dataset, binding, or custom profile, but it
remains explicitly unqualified. `qualified=true` resolves an exact preregistered
package-owned specification containing dataset ID, schema, committed dataset
digest, immutable profile and thresholds, and every authoritative binding field
above. The certification API accepts only the registered specification ID plus
strict dataset, observation, and binding domain values. It recomputes metrics from
those observations and evaluates the package-owned profile internally. It has no
parameters for caller metrics, profiles, alleged fingerprints, or alternate
registries. An ordinary request cannot register an anchor: a digest-shaped string,
caller-created expected binding, or matching custom-profile fingerprint conveys no
authority. The separate custom-profile reporting API always records
`missing:trusted_qualification_spec` and can never certify.
Adding a trusted specification requires a code/fixture release or a real verifier
adapter with separately established authority.

## Consumer qualification profile

`consumer-retrieval-qualification.v1` supplies reporting defaults requested by the
current consumer:

- Recall@5 at least `9/10`;
- MRR@10 at least `4/5`;
- cross-scope leakage count at most `0`;
- topology violation count at most `0`;
- p95 latency at most `3,000,000` microseconds;
- failure count at most `0`;
- timeout count at most `0`;
- unsupported-case unexpected-result count at most `0`.

These are a **consumer qualification profile**, not universal Infinity Context
product truth. The named default ID is inseparable from this exact canonical
threshold fingerprint and rejects substitution. Custom thresholds require a custom
profile ID and receive their own fingerprint, but remain scoring-only without a
future package release or verifier adapter. Recall@10 and nDCG@10 are always
reported and become gates only in a distinctly named custom profile. Certification
always requires exactly zero failures and zero timeouts.

Dataset construction recursively detaches and freezes record objects, attribute
maps, and nested arrays. Mutating caller-owned input cannot alter digest, topology,
or results, and mutation through the domain snapshot fails. Certification
recomputes both retrieval metrics and the current dataset digest instead of
accepting caller-scored metrics or a retained caller digest.

## Residual live gates

The sole package anchor is synthetic and cannot qualify a deployment. Production
evidence still requires a mounted Retrieval route; real Postgres canonical writes
and hydration; exercised lexical/vector and neighbor adapters against actual
indexes; server-owned deadline and exact serialized-byte measurement; independently
verified service/core revisions, capabilities, retrieval profile, and index identity;
a cleanup receipt verified against canonical lifecycle state; isolation/leakage
probes under concurrent traffic; repeated production-bound runs; and representative
latency/load measurements. Qdrant, Graphiti, provider behavior, and failure recovery
remain external runtime gates and are not demonstrated here.
