# Independent code review: authenticated managed document replay

Decision: **APPROVED; no blocking code finding** at `f971807da5cbf39b87125836251c40122b508a0a`, with production commit `b1daf352a285ada6516b24fe7c340eae3d9b7aa7` unchanged by the test commit. Root owns final real official-data acceptance; this review does not imply that full LongMemEval replay has already passed.

## Trust boundary and scope

Reviewed all three production files and the complete new 450-line regression file against the twice-reviewed plan. The separate managed policy is selected only from the result of fresh successful admission. Independently audited all three receipt-replay calls and both duplicate lookups; each receives that result, and nested conflict recovery uses its own freshly admitted key and mode. A namespace or old digest alone cannot select the managed policy. Existing authority, scope/ownership, active-state and receipt checks remain intact. Managed receipts retain their written legacy fingerprint.

The managed verifier matches exact canonical scope/thread, existing document title/source stripping and classification, the original raw-text fragmenter's sequence/kind/text/span projection, and exactly the projection-owned metadata. Stored chunk text is compared using the existing write-time strip. Metadata comparison retains key presence, array order and JSON scalar types, so missing/null/empty, boolean/integer and integer/float substitutions cannot silently compare equal. Canonical sequence sorting permits harmless fetch order while altered/duplicate sequence assignments and wrong cardinality fail.

Ordinary modern and conservative ordinary legacy branches remain unchanged. No digest migration, expanded ordinary legacy multi-fragment policy, feature reverse dependency, provider dependency, public root/application export, source fixture or frozen inventory change appears. Unrelated user metadata remains outside this identity proof as explicitly planned.

## Independent relocation and call-site proof

Parsed original and current sources independently and proved complete AST identity for all three metadata helper definitions, including their loaded names. Their dependencies remain builtins plus the same two moved helper bindings. The original private names are direct aliases to the shared owner, without copied implementations. No existing test monkeypatch contract for those helpers was found. The original future-annotation behavior is retained.

The five replay call sites use `managed_admitted` or the nested `replay_managed`; no stale outer key/mode is used by the nested fresh UoW. Normal key order and ordinary receipt behavior remain the same.

## Regression assessment and execution evidence

The new tests exercise real canonical SQLite writes and four receipt/duplicate/conflict paths. Read-routing doubles force real uniqueness conflicts and are identified as unit instrumentation rather than full official authority proof. They verify stable document/chunk IDs, unchanged canonical row counts after replay, fresh admission on every recovery UoW, changed-key/denial rejection, receipt digest-format rejection, case/whitespace collisions, scope/source changes, fragment corruption and complete owned-metadata type/order/presence failures. An explicit ordinary legacy multi-fragment negative case preserves that boundary.

Reviewed the recorded original-function pre-fix failure: the new positive receipt regression reaches the authentic `Legacy document source cannot be verified exactly` error. Root's committed-source focused gate passed **77 tests in 77.24 seconds**. No duplicate broad pytest or ML process was started by this reviewer while memory was under investigation; independent execution here was bounded stdlib AST/call-site verification.

The original full real-PostgreSQL LongMemEval E2E, tampered-command rejection and exact final canonical row counts remain required runtime release evidence. Affected real Docling HTTP/multimodal acceptance also remains pending on the final composed production candidate.

## Subsequent CI finding — prior approval is historical

Exact-head CI run `40087556960`, job `120854051391`, subsequently exposed an existing mounted PostgreSQL HTTP collision assertion returning 500 instead of its original 409. The same test file passes on #101 without this managed-policy delta, on the same baseline/Python version. This is a new error-contract regression; the source-stage approval above is historical and is not an unconditional current release approval.

Both critics approved two rounds of a narrow amendment: retain every rejection predicate/message, change only the managed projection-mismatch raise from invariant to conflict, preserve common structural invariant errors/global HTTP mapping/original test double, and validate fresh read-only recovery plus the original PostgreSQL file. Final corrected code and actual PostgreSQL success remain pending. Prior full LongMemEval/Docling executions retain their original source pins and require explicit exception-path impact review for reuse.
