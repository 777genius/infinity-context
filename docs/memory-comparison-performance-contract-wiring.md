# Performance contract wiring status

The performance/session contract slice is provider-neutral and intentionally not
wired into HTTP, CLI, benchmark methodology, or provider adapters yet.

Every standalone artifact reports `publishable: false` and
`publication_status: pending_composite_wiring`. A later integration change must
compose all of these live gates before publication:

1. retrieval completeness for both frozen backend roles and every expected case;
2. adapter-authenticated evidence for requested, returned, and available counts;
3. exhaustive evidence when at most 200 results are available, or trusted
   continuation evidence when more than 200 are available;
4. the run-scoped HMAC session-isolation verifier with the exact expected mapping;
5. the token-budget and latency contracts.

Serialized `matches` or `status` markers are reporting data only. They must not
authorize publication without re-running the live completeness and session
verifiers. The HMAC key, HMAC proofs, adapter attestations, and continuation
proofs must remain in memory and must never be copied into report artifacts.
