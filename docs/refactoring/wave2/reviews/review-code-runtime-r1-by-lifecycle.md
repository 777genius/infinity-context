# Runtime R1 implementation review — lifecycle owner

Reviewed `arch-runtime` HEAD `89e2a7ad`, including the installed-real-consumer correction, against
pinned base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` and the twice-approved plan. Decision:
**source approved; no blocking finding**. Root still owns scheduled wheel/architecture/integration
acceptance before merge.

## Independent source and contract evidence

- Independently parsed all **49 original function/class definitions** and compared their entire
  ASTs with the new final-owner definitions. Every body, signature, decorator and docstring matches.
- Inspected the split facet-data composition, explicit 31-key order, shared predicate imports,
  ten-module dependency direction and narrow public API. No server/core-application dependency,
  reverse facade import, dynamic forwarding, copied algorithm or hand-set metadata found.
- Inspected both real consumer changes: only imports move to benchmark public API; query-term,
  rerank and evidence orchestration remains server-owned and unchanged.
- Inspected the frozen capture source-byte guard, ownership/signature/hint/property/global
  manifest, legacy references/instance pickles, lossless gzip/hash replay and real-server plus
  lower-level replay paths. Expected output still originates from unchanged production. Registry
  ordering and all configured facet coverage have separate assertions.
- Independently ran the frozen contract, ownership guard and runtime identity tests:
  **13 passed in 4.13s**. This replays the full **1630-case** direct/real-consumer corpus, temporal,
  role/risk boundaries, supported legacy exports/hints/globals/pickles, acyclic ownership and
  source/installed RECORD mutation behavior. Temporary data is task-owned and bounded.

## Installed gate inspection

The final wheel probe now actually imports installed `query_retrieval_intent` in server/bundle
contexts and compares all frozen intent/profile/diagnostic outputs. Standalone replays canonical
lower-level public policy while requiring server/adapters absence. All loaded Infinity module
origins must be inside the target installation; old references/pickles and DTO round trips are
also checked. Source-tree replay alone cannot satisfy this gate. Execution remains root-scheduled
because package staging/installations share limited disk; this review does not claim it ran.

The evidence consumer's one import-group blank line is documented, no oversized ceiling grows,
and actual aggregate server benchmark debt decreases by 2835 lines. Root-owned exact ratchets
remain necessary; no accepted ADR or lifecycle policy changes are present.
