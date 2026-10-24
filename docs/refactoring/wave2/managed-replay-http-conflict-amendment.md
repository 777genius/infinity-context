# Managed replay HTTP conflict amendment — plan v2

## Concrete regression

The original managed PostgreSQL/HTTP identity test passed before #104 and fails after its new
managed policy. CI run 40087556960, shard 120854051391, and an unchanged local real-PG18 run on
clean b230f59b both observe HTTP 500 instead of the original 409 for a case-changed v1-digest
collision. Its deliberately permissive admission double returns the same key for both claims.
The new verifier still rejects the mismatch, but classifies it as an invariant failure. The
public error mapper therefore reports an internal error.

This is a product error-contract regression. Do not repair it by tightening that old double,
changing the original test/HTTP mapper, broadening admission, accepting a divergent projection,
or hiding the failed CI/local result. The earlier 235-observation ledger now marks this carried
case pending correction and retains the prior passing history.

## Proposed bounded change

1. Keep the entire managed projection comparison predicate and every rejection unchanged.
   Change only the exception type raised by that comparison from MemoryInvariantError to
   MemoryConflictError, retaining the existing message. A request that cannot prove identity
   against a valid canonical record is a conflict, including when a v1 digest collides.
2. Preserve the common structural ownership/impossible-span errors as MemoryInvariantError,
   and preserve every ordinary modern/legacy branch and all fresh admission/recovery checks.
   Do not change the global mapping of invariant errors to 500.
3. Strengthen the existing new text-corruption test to require MemoryConflictError, not either
   rejection class. Add bounded explicit ownership and intrinsically impossible-span cases
   requiring MemoryInvariantError. Use a foreign chunk document parent and an intrinsically
   impossible span so both fail the existing COMMON structural guard, not a valid-but-different
   projection or a document-scope conflict. These protect the error-category boundary.
4. Changing the raised class also enters the existing MemoryConflictError recovery path.
   Review its fresh admission, read-only duplicate lookup and propagation; verify unchanged
   canonical counts in the existing focused tests and unchanged original HTTP receipt proof.
   Add one real-storage negative integration case: first persist a legitimately admitted
   managed document, deliberately corrupt a stored chunk's text without changing its valid
   ownership/span, then execute the unchanged original command through IngestDocumentUseCase
   and the real admission operation. Require MemoryConflictError, exactly two distinct fresh
   admission UoWs (initial and recovery), unchanged document/chunk/outbox/receipt counts and
   unchanged corrupted text after rejection. No permissive admission replacement is needed
   for this new regression; the original HTTP test's existing double remains untouched.
5. Prove the production-module AST becomes exactly the preceding source after reversing
   this one raise-name change. Assert exactly one targeted Raise function Name changes and
   that its message, predicate and the remainder of the module stay identical.
   No predicate, admission, helper, call site, HTTP mapping,
   test-authority, corpus, timeout, fixture or size ceiling may change.

## Acceptance and review

- Before implementation, root's two independent critics review this amendment twice.
- Retain the already completed authentic failing PostgreSQL HTTP node on clean b230f59b.
- Run the complete original two-node PostgreSQL document-identity file after the change,
  including ordinary compatibility, both collision header modes and the persisted v1 receipt.
- Rerun the bounded managed replay/ingestion contract gate on committed corrected source,
  including the strengthened error-category cases and canonical identity/count checks.
- Obtain both independent code reviews. Publish the correction promptly in existing #104;
  inspect its CI and retain the preceding CI failure.
- Update the final composed verification source by this exact committed delta. The prior
  full LongMemEval and Docling results keep their actual b230 source pins. Reuse them only
  after both critics approve the strict one-raise AST proof and path impact: successful exact
  projections do not execute the changed raise, and the original LongMemEval tamper fails at
  its preceding admission boundary. Do not label them new executions or blindly repeat
  expensive ML/full-corpus preparation when the remaining error path is directly verified.
- Restore the case's final passing disposition only from the actual corrected PostgreSQL
  result, retain all observations, and record the scoped exception-path impact review.

## Round-one review and round-two submission

Both independent critics approved the direction and required exact structural-guard cases,
one real-storage negative proving fresh read-only conflict recovery, the strict one-name AST
reverse proof, unchanged original PostgreSQL assertions, and source-qualified success-path
reuse. Version 2 incorporates each point. Both critics are asked for round-two approval before
implementation; no production or test edit has been made for this amendment.

## Round-two approvals before implementation

The independent architecture critic and unit critic both approved version 2 with no remaining design blocker. Both explicitly accepted the real-admission negative recovery proof, the unchanged common structural guard and exact one-raise AST reversal, the original PostgreSQL file and header/receipt assertions, and source-pinned reuse of successful or upstream-rejected prior E2E paths. No production or test edit preceded either approval. The earlier CI and local HTTP failure remain evidence.
