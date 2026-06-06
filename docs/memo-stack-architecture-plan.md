# Universal Memo Stack Architecture Plan

Статус: Draft architecture decision, готово к review перед реализацией.

Дата фиксации: 2026-05-24.

Цель документа: зафиксировать целевую архитектуру reusable memo stack, которую можно подключать к Client App и другим приложениям без привязки к Graphiti, Qdrant, Zep, Cognee или конкретному LLM provider.

Ключевое решение:

```text
Our Memo Stack Core + Postgres canonical truth + Graphiti adapter + Qdrant adapter
```

Оценка целевого v1:

🎯 9   🛡️ 9   🧠 7
Оценка объема: `15500-28500` строк для нормального vertical slice без UI и SaaS.

## Executive Summary

Мы не делаем "интеграцию с Graphiti" и не делаем "интеграцию с Qdrant". Мы делаем свою **Memo Stack**, где:

- `memo_stack_core` содержит domain, use cases и ports.
- `memo_stack_server` дает HTTP API, worker, migrations, auth, config.
- `memo_stack_adapters` подключают Postgres, Graphiti, Qdrant, LLM, embeddings, object storage.
- `memo_stack_sdk` дает удобный Python client, потом можно сгенерировать TypeScript/Rust clients из OpenAPI.
- `memo_stack_mcp` и UI добавляются позже поверх того же API.

Главный invariant:

```text
Postgres is source of truth.
Graphiti and Qdrant are derived indexes.
```

Graphiti нужен для temporal graph memory:

- facts;
- entities;
- relations;
- temporal validity;
- invalidation/superseding;
- graph-aware retrieval.

Qdrant нужен для vector/RAG memory:

- raw document chunks;
- transcript chunks;
- semantic search;
- source snippets;
- large file retrieval.

Postgres нужен для canonical lifecycle:

- profiles;
- facts;
- fact versions;
- documents;
- chunks metadata;
- source refs;
- tombstones;
- audit;
- outbox;
- permissions;
- retention.

Если Graphiti или Qdrant вернули stale item, canonical Postgres status wins.

## Non-Goals

V1 не должен превращаться в SaaS. В scope v1 входит reusable local/server module, а не marketplace, billing, teams UI и enterprise admin.

Не делаем:

- полноценный Zep competitor в первом этапе;
- UI memory studio;
- сложный multi-region sync;
- custom graph engine вместо Graphiti;
- custom vector DB вместо Qdrant;
- автогенерацию "истины" без source refs;
- хранение больших файлов в Graphiti;
- прямую зависимость Client App от Graphiti/Qdrant clients.

## Fixed Global Decisions

Эти решения считаем зафиксированными для v1 architecture baseline. Если меняем одно из них, нужен отдельный ADR/update этого документа.

### External Assumptions Checked

Checked on 2026-05-24:

- Graphiti currently supports multiple graph backends, including Neo4j, FalkorDB, Kuzu and Amazon Neptune variants. V1 still chooses Neo4j, but `GraphitiAdapter` must not assume Neo4j-only semantics internally.
- Graphiti defaults to OpenAI for LLM inference and embeddings, so local/private mode must explicitly configure providers and block accidental external calls.
- Graphiti telemetry is opt-out via `GRAPHITI_TELEMETRY_ENABLED=false`; local Docker and production examples should set it explicitly.
- Qdrant payload filters are central to our single-collection design, therefore payload indexes for filtered fields are not optional.
- Qdrant snapshots are the correct backup/restore mechanism for vector collections, but snapshots require a running Qdrant server/container rather than Python SDK local mode.

### Plan-Improve Review Findings

Weak spots found and fixed in this pass:

1. Graphiti external behavior was under-specified.
   - Risk: accidental OpenAI calls or telemetry in privacy-sensitive local mode.
   - Fix: explicit provider configuration, `GRAPHITI_TELEMETRY_ENABLED=false`, policy gate before external calls.

2. Qdrant filtered search performance was under-specified.
   - Risk: single collection works functionally but degrades badly with many profiles/documents.
   - Fix: payload indexes are now required for every field used in filters.

3. Derived index backup/restore was incomplete.
   - Risk: Postgres restore succeeds but vector index restore/rebuild story is unclear.
   - Fix: Qdrant snapshots and rebuild-from-Postgres remain both required paths.

4. Backend capabilities were too implicit.
   - Risk: adapter code silently assumes Neo4j semantics and becomes hard to swap later.
   - Fix: Graphiti adapter must expose capabilities and backend-specific guarantees.

5. Client App integration was too greenfield.
   - Risk: replacing the existing desktop bridge breaks `ActiveContext`, settings rollback, local fallback or production canaries.
   - Fix: add a client compatibility gateway and migration contract before changing prompt-impacting behavior.

6. Existing memory session ownership was under-specified.
   - Risk: current `session_id` JSON store and future `MemoryThread` ids diverge, causing imports into a session the desktop will not read.
   - Fix: define explicit mapping from legacy `session_id` to `MemoryThread.external_ref` and preserve companion-session import checks.

7. Existing mode precedence was not captured.
   - Risk: new platform ignores `INTERVIEW_MEMORY_FORCE_DISABLED`, Settings `interview_memory_enabled=false` or `INTERVIEW_MEMORY_FORCE_LOCAL_ONLY`.
   - Fix: preserve old mode resolution as a compatibility layer and map it to platform policy/capabilities.

8. Verification commands were too abstract for Client App rollout.
   - Risk: broad tests pass but production memory route, local canary or document recall path regresses.
   - Fix: add exact existing E2E/canary commands to the integration phase and acceptance criteria.

9. Tenancy and authorization were too coarse.
   - Risk: team mode, Slack/GitHub integrations or coding agents can read/write profiles they should not access.
   - Fix: add first-class principals, space membership, profile grants and authorization ports.

10. Outbox semantics were underspecified.
    - Risk: retries duplicate Graphiti/Qdrant writes, dead jobs are invisible, or delete races reintroduce old facts.
    - Fix: add idempotency keys, lease ownership, per-profile ordering keys and dead-letter handling.

11. Migrations and contract versioning were not operational enough.
    - Risk: local Docker, remote server and generated clients drift silently.
    - Fix: add migration runbook, contract test gates and explicit compatibility window.

12. Quota/backpressure model was incomplete.
    - Risk: large imports or auto-memory jobs starve prompt-time context requests.
    - Fix: add workload classes, queue budgets and per-space rate limits.

13. Data sensitivity was not modeled as a first-class domain concept.
    - Risk: raw source, embeddings, graph facts and exports get different privacy behavior accidentally.
    - Fix: add sensitivity levels, external-processing decisions and encryption/redaction requirements.

14. Document ingestion was still too optimistic.
    - Risk: parser bugs, hostile documents, partial extraction and OCR/image files create corrupted or unsafe memory.
    - Fix: add a staged document pipeline with validation, extraction, chunking, indexing and reviewable failure states.

15. Memory quality evaluation was too metric-only.
    - Risk: recall looks good while source attribution, stale-fact blocking or negative constraints regress.
    - Fix: add golden eval dataset schema, regression suites and quality gates.

16. Capacity/cost planning was not explicit enough.
    - Risk: auto-memory becomes expensive or slow after large imports and multi-app usage.
    - Fix: add sizing assumptions, cost budgets and load-test gates.

17. Execution scope was still too broad.
    - Risk: implementation starts with Graphiti/Qdrant/Client App at once and becomes unreviewable.
    - Fix: add MVP cutline, PR roadmap, stop conditions and spike gates.

18. First PR was too vague for a clean architecture foundation.
    - Risk: first PR accidentally includes adapter pressure or behavior changes before boundaries are locked.
    - Fix: define first PR acceptance criteria and forbidden changes.

19. Development/release governance was under-specified.
    - Risk: reusable platform becomes hard to extract, release or audit because tooling is implicit.
    - Fix: add CI gates, dependency governance, release process, ADR/PR templates and fixture rules.

20. Local Docker ergonomics were under-specified.
    - Risk: contributors cannot reliably reproduce Qdrant/Neo4j/Postgres state or diagnose failed setup.
    - Fix: add healthchecks, reset commands, seeded fixtures and deterministic diagnostics.

21. ADR/PR discipline was implicit.
    - Risk: major lifecycle/provider/API choices happen inside implementation PRs without reviewable decision records.
    - Fix: add ADR triggers and PR description requirements.

22. API/SDK behavior was underspecified.
    - Risk: different clients implement retries, pagination, idempotency and error handling differently.
    - Fix: add API envelope, typed errors, pagination, idempotency headers and SDK behavior rules.

23. Import/export and sync-readiness were too high-level.
    - Risk: future cloud sync or cross-project reuse cannot reconcile ids, tombstones and policy versions safely.
    - Fix: add portable bundle format, event cursor contract and conflict handling rules.

24. Memory ontology was implicit.
    - Risk: each client invents its own `kind`, `source_type`, entity naming and relation vocabulary, making search and auto-memory noisy.
    - Fix: add governed ontology/taxonomy, extension rules and compatibility tests.

25. Connector/MCP behavior was not formalized.
    - Risk: coding agents, Slack/GitHub integrations and future MCP tools write memory with inconsistent provenance or unsafe permissions.
    - Fix: add connector contract, source provenance and scoped connector capabilities.

26. Plan navigation was too weak for a 5000+ line architecture document.
    - Risk: implementation PRs satisfy one section while silently violating another section.
    - Fix: add an implementation navigation map and decision traceability matrix.

27. Only fact lifecycle was explicit.
    - Risk: documents, suggestions, imports, exports, outbox jobs and policies drift into ad hoc states.
    - Fix: add aggregate lifecycle state machines with allowed transitions and tests.

28. Contract compatibility was spread across API, SDK, migrations and Client App sections.
    - Risk: API, SDK, ontology, schema and legacy route versions evolve independently.
    - Fix: add a contract version compatibility matrix.

29. Done Definition did not explicitly bind lifecycle/state decisions to tests.
    - Risk: state-machine regressions ship because the plan has diagrams but no required checks.
    - Fix: add lifecycle transition tests, version compatibility checks and traceability gates.

30. Entity resolution was treated mostly as Graphiti behavior.
    - Risk: Graphiti or clients merge different people/projects/packages into one entity and corrupt canonical memory.
    - Fix: add canonical `MemoryEntity`, entity aliases, entity resolution port, merge/split rules and tests.

31. Temporal semantics were present as fields but not as a query contract.
    - Risk: current, expired, historical and source-observed facts get mixed in future chats.
    - Fix: define observation time, validity time, ingestion time, `as_of` retrieval and stale fact behavior.

32. Confidence/evidence was not strict enough for auto-memory.
    - Risk: repeated summaries or low-trust assistant text inflate confidence and auto-promote hallucinated memory.
    - Fix: add evidence grading rules, confidence update policy and negative tests.

33. Prompt-context safety was scattered across sections.
    - Risk: retrieved snippets can be treated by agents as instructions instead of evidence.
    - Fix: add context item trust boundaries and prompt-safe rendering contract.

34. AI provider governance was still too implicit.
    - Risk: Graphiti, classifier, embedder, OCR or reranker can call external providers with different redaction, cost and retry rules.
    - Fix: add an AI provider governance contract, provider registry, prompt/output versioning and circuit breakers.

35. Redaction was mentioned but not modeled as a pipeline.
    - Risk: redacted text loses source offsets, breaks citations or leaks secrets through embeddings/logs.
    - Fix: add redaction artifacts, offset mapping, sensitivity downgrade rules and remediation tests.

36. Structured LLM output was not a compatibility contract.
    - Risk: classifier prompt changes silently produce different candidates and corrupt auto-memory quality.
    - Fix: require versioned prompts, JSON schema validation, shadow eval and rollback for classifier changes.

37. Operational runbooks were scattered across deployment and recovery notes.
    - Risk: local/team self-hosting can work in happy path but fail during restore, provider outage or migration.
    - Fix: add operational runbook matrix, readiness states and incident drills.

38. Encryption/key management was too vague for a reusable memory service.
    - Risk: raw source, embeddings, exports and backups are encrypted inconsistently or cannot survive key rotation.
    - Fix: add key management, key versions, rotation rules and backup encryption requirements.

39. Token storage and service-token lifecycle were under-specified.
    - Risk: leaked token hashes or logs allow broad memory access, export or hard-delete.
    - Fix: add token hashing, token prefix display, rotation/revocation rules and scoped token tests.

40. Audit integrity was not strong enough.
    - Risk: destructive actions, exports or policy changes can be edited or deleted without detectable trace.
    - Fix: add append-only audit semantics, hash chaining and tamper-evidence tests.

41. Supply-chain/security gates were too high-level.
    - Risk: Graphiti/Qdrant/LLM/OCR parser dependencies introduce vulnerable packages or unsafe licenses unnoticed.
    - Fix: add dependency inventory, license/security gates and parser sandbox rules.

42. Connector lifecycle was too thin for multi-agent/team memory.
    - Risk: Slack/GitHub/Codex/Cursor connectors cannot be installed, paused, backfilled, rotated or deactivated consistently.
    - Fix: add connector installation lifecycle, sync state, webhook identity and connector health contracts.

43. Event delivery was only a cursor, not a subscription contract.
    - Risk: clients miss delete/update/policy events, reuse stale context, or implement incompatible polling/webhooks.
    - Fix: add event subscriptions, delivery lifecycle, replay/idempotency and cache invalidation rules.

44. MCP tool safety did not define approval boundaries deeply enough.
    - Risk: an agent can write, approve, forget or export memory through MCP without human review or explicit grants.
    - Fix: add MCP action classes, dangerous-operation confirmation and agent-origin restrictions.

45. Connector source authenticity and replay protection were implicit.
    - Risk: forged webhooks, duplicated imports or stale backfills create wrong memory or resurrect deleted facts.
    - Fix: add webhook signature verification, source sequence handling, connector cursor and replay-window tests.

46. Coding-agent repository scope was still mostly metadata.
    - Risk: a branch-local decision, dirty worktree note or repo-specific constraint becomes global advice in another repo/chat.
    - Fix: add `CodeRepository`, `CodeScope`, code-scope matching rules and branch/commit promotion semantics.

47. Code references were not durable enough.
    - Risk: file rename, line drift, symbol move or rebase makes source refs misleading while memory still looks precise.
    - Fix: add `CodeReference`, content hashes, symbol refs, line-range drift handling and resolver tests.

48. PR/branch lifecycle was under-specified for team memory.
    - Risk: rejected approaches and implementation notes from abandoned PRs keep influencing mainline agents.
    - Fix: add branch/PR lifecycle rules, stale branch review and release/promotion workflows.

49. Retention was present as a field but not as an executable lifecycle.
    - Risk: memory grows forever or retention jobs delete useful/held evidence unpredictably.
    - Fix: add `RetentionRule`, retention jobs, dry-run, grace periods and retention tests.

50. Legal/security hold behavior was only implied by sensitivity.
    - Risk: hard-delete/export/retention can violate hold requirements or block legitimate user deletion with no audit.
    - Fix: add `LegalHold`, hold precedence rules and explicit conflict handling with hard-delete.

51. Profile/thread deletion semantics were incomplete.
    - Risk: deleting a profile leaves derived indexes, object blobs, subscriptions or connector state orphaned.
    - Fix: add profile deletion lifecycle, cascade/deindex/orphan cleanup and verification gates.

52. Local-to-cloud sync was only an invariant list, not a contract.
    - Risk: future cloud sync will invent ids, cursors and conflict handling outside the domain model.
    - Fix: add `SyncPeer`, `SyncCheckpoint`, `SyncChangeSet` and `SyncConflict` as future-gated contracts.

53. Offline writes and remote writes had no explicit trust ordering.
    - Risk: local Docker and remote server can both accept writes, then silently pick the wrong winner.
    - Fix: define origin, principal, trust tier, operation kind and deterministic conflict resolution inputs.

54. Sync support could be accidentally marketed before it is safe.
    - Risk: API/schema is sync-ready, but users expect bidirectional cloud sync guarantees that v1 does not provide.
    - Fix: make sync exchange capability explicit, disabled by default and blocked from V1 Done Definition unless a later ADR enables it.

55. Long-term memory quality had no explicit consolidation owner.
    - Risk: memory works technically but degrades into duplicate facts, noisy suggestions and expensive context packing.
    - Fix: add `MemoryCluster`, `MemoryDigest` and `ConsolidationJob` as canonical quality-management contracts.

56. Summaries/digests were mentioned as evidence but not lifecycle-managed.
    - Risk: a generated summary outlives its sources, hides contradictions or becomes false primary evidence.
    - Fix: mark digests as derived, source-bound, refreshable and never confidence-increasing by themselves.

57. Deduplication was scattered across ingestion, suggestions and retries.
    - Risk: each pipeline suppresses duplicates differently, causing false merges or repeated review spam.
    - Fix: centralize dedupe/consolidation decisions behind repository ports, similarity ports and reviewable jobs.

58. Quota/backpressure was operational, not domain-owned.
    - Risk: large imports, sync, consolidation or provider calls can starve interactive context or create runaway cost.
    - Fix: add `UsageRecord`, `QuotaRule`, `QuotaReservation` and `AdmissionDecision` as first-class contracts.

59. Noisy-neighbor isolation was not explicit.
    - Risk: one connector/profile can consume worker slots, vector writes or AI budget for the whole space.
    - Fix: add fairness keys, workload classes, reserved interactive capacity and per-principal/connector/profile limits.

60. Quota reservation lifecycle was missing.
    - Risk: failed jobs leak reserved budget or retries double-count provider/storage usage.
    - Fix: make reservations idempotent, expiring, auditable and released/committed through lifecycle transitions.

61. Derived index state was implicit in outbox jobs and adapter behavior.
    - Risk: Graphiti/Qdrant can drift from Postgres and diagnostics cannot prove which aggregate/version is indexed.
    - Fix: add `ProjectionState`, `ProjectionMapping` and `ProjectionRebuildJob` as canonical derived-index contracts.

62. Rebuild/backfill lacked a precise watermark model.
    - Risk: rebuild while writes continue can miss updates, replay stale deletes or mix index generations.
    - Fix: define projection generation, canonical commit watermark, resume cursor and dual-read/activation rules.

63. Adapter id mappings were not first-class.
    - Risk: delete/update/rebuild cannot reliably find external graph/vector objects after adapter schema changes.
    - Fix: persist adapter object mappings with adapter version, projection version, canonical ids and safe metadata.

64. Idempotency was an API rule, not an operation ledger.
    - Risk: client timeout/retry creates duplicate facts, duplicate imports or ambiguous long-running operation state.
    - Fix: add `ClientOperation`, `IdempotencyRecord` and `OperationResultSnapshot` as shared API/use-case contracts.

65. Internal outbox jobs and client-visible jobs were mixed conceptually.
    - Risk: SDKs poll internal worker state or cannot understand import/rebuild/retention progress consistently.
    - Fix: separate public `ClientOperation` lifecycle from internal `OutboxJob` lifecycle.

66. Retry/replay behavior had no response snapshot contract.
    - Risk: same idempotency key can return different response shapes after partial success or server restart.
    - Fix: persist safe response snapshots, request fingerprints, operation ids and conflict behavior.

67. Public DTO/schema ownership was still implicit.
    - Risk: API routes, SDK models, event payloads, import/export bundles and MCP tools each serialize similar objects differently.
    - Fix: add a versioned `memo_stack_contracts` package with canonical public DTOs, JSON schemas, fixtures and schema registry.

68. Domain entities could leak into transport contracts.
    - Risk: FastAPI/Pydantic convenience turns internal aggregates into public API shape, making domain refactors breaking changes.
    - Fix: domain entities stay internal; every boundary uses explicit command/query/result DTOs and tested mappers.

69. Forward compatibility rules were present but not executable.
    - Risk: unknown enum values, null-vs-absent changes or new fields break generated TS/Rust clients after release.
    - Fix: add contract evolution rules, unknown-enum fixtures, schema roundtrip tests and supported-client-window checks.

70. First boot/bootstrap path was under-specified.
    - Risk: local Docker starts unusable, or worse, starts with open admin creation/auth bypass semantics.
    - Fix: add explicit bootstrap state, one-time setup token, first owner/space/profile provisioning and boot lock rules.

71. Runtime configuration was treated mostly as env variables.
    - Risk: API and worker run with different config, external AI/auth mode is enabled accidentally, or diagnostics cannot explain drift.
    - Fix: add config snapshots, precedence rules, startup validation, config fingerprinting and worker/API config compatibility checks.

72. Dev seed/reset could be unsafe outside local mode.
    - Risk: synthetic seed or destructive reset command runs against real/team data because deployment mode is ambiguous.
    - Fix: require deployment mode guard, explicit confirmation, synthetic-only fixtures and audit for reset/seed commands.

73. Migrations were described as tooling, not governed runtime state.
    - Risk: Alembic succeeds while data backfill, contract versions, workers or derived indexes are still incompatible.
    - Fix: add `SchemaMigrationRun`, `DataBackfillJob`, compatibility windows, migration locks and readiness gates.

74. Backfills could race with normal writes and retention/delete.
    - Risk: data backfill reintroduces deleted facts, skips new rows, or updates rows using stale policy/version assumptions.
    - Fix: add cursor/watermark rules, chunked idempotent backfills, policy re-check and tombstone-aware backfill tests.

75. Upgrade/rollback semantics were too optimistic.
    - Risk: a partial upgrade leaves API, worker, SDK and indexes in mixed versions with no safe read/write posture.
    - Fix: add expand/backfill/contract/cleanup phases, read-only fallback, rollback boundaries and upgrade dry-run.

76. Worker execution topology was under-specified.
    - Risk: multiple worker processes or old processes claim incompatible work, duplicate singleton jobs or leave stale leases after shutdown.
    - Fix: add `WorkerInstance`, `WorkerLease`, `ScheduledTask`, heartbeat, graceful shutdown and scheduler lease contracts.

77. Singleton maintenance tasks were implicit.
    - Risk: retention, quota cleanup, backfill scheduling or digest refresh runs twice and causes duplicate operations or noisy load spikes.
    - Fix: add scheduled task registry, singleton lease keys and idempotent scheduled-task run records.

78. Graceful shutdown and crash recovery were too shallow.
    - Risk: worker receives SIGTERM during adapter write, loses progress, holds quota reservation or reports operation status incorrectly.
    - Fix: add shutdown lifecycle, lease draining, external side-effect reconciliation and worker crash tests.

79. Object storage was treated as a thin adapter.
    - Risk: Postgres records point to missing blobs, hard-delete leaves raw files, or exports remain downloadable after permissions change.
    - Fix: add `StorageObject`, `UploadSession` and `MemoryArtifact` lifecycle contracts with checksums, ownership and retention rules.

80. Large upload integrity was under-specified.
    - Risk: partial multipart upload, mime mismatch, corrupted content or hostile archive becomes trusted document memory.
    - Fix: add upload completion validation, checksum verification, quarantine status and parser-safety gates before document processing.

81. Export/backup artifacts lacked access lifecycle.
    - Risk: sensitive bundle URLs outlive grants, hard-delete, legal hold or key rotation state.
    - Fix: make export/backup/import artifacts canonical records with TTL, sensitivity, key version, access checks and revocation.

82. Server-side cache behavior was implicit.
    - Risk: context/search/rerank caches can return deleted, superseded or newly unauthorized memory even when Postgres is correct.
    - Fix: add cache/freshness governance with canonical re-checks, invalidation records, bounded TTLs and forget/update/grant-change tests.

83. Cache keys did not include enough policy and authorization dimensions.
    - Risk: a context bundle cached for one principal/profile/policy state can leak into another request after grant, profile or policy changes.
    - Fix: require cache metadata for principal/profile hash, grant version, policy version, ontology version, temporal mode and canonical commit cursor.

84. Embedding/rerank/token caches were not separated by sensitivity and purpose.
    - Risk: derived model artifacts can cross privacy boundaries or survive provider/policy changes that should make them unusable.
    - Fix: define cache kinds, sensitivity/provider/purpose dimensions, invalidation triggers and diagnostics for blocked stale hits.

85. Backup/restore was a runbook, not a governed lifecycle.
    - Risk: restore can lose object blobs, mismatch derived indexes, skip key material or silently reintroduce deleted memory.
    - Fix: add backup policy, backup run, manifest and restore run contracts with validation gates and restore drills.

86. Point-in-time restore semantics were not tied to tombstones and hard-delete.
    - Risk: restoring to an old timestamp can resurrect facts or raw files that were later forgotten or hard-deleted.
    - Fix: require restore validation against retained deletion manifests, tombstone windows, hard-delete ledger and policy.

87. Backup security boundary was under-specified.
    - Risk: backup artifacts, snapshots and manifests can become a second data store with weaker auth, retention and key handling.
    - Fix: make backups governed artifacts with sensitivity, key versions, retention, access audit and current authorization checks.

88. Read-path authorization was a rule, not an enforceable contract.
    - Risk: one search/list/export/debug endpoint can forget the canonical visibility filter and leak cross-profile or deleted data.
    - Fix: add `ReadScope`, `VisibilityPredicate`, `VisibilityProof` and mandatory read-path guard checks.

89. Derived retrieval candidates and canonical read models lacked a shared filter proof.
    - Risk: Graphiti/Qdrant/cache/export/list code each implements slightly different visibility logic.
    - Fix: route every user-visible read through the same visibility guard and require proof in response diagnostics/tests.

90. Denied-read behavior was not explicit enough.
    - Risk: authorization failures reveal whether hidden memory exists, or diagnostics leak ids/text from forbidden profiles.
    - Fix: define denial-safe errors, safe audit, zero/empty behavior and negative tests for existence leakage.

91. Prompt-path latency was spread across quotas, cache and compatibility notes.
    - Risk: `/context` can become correct but too slow, blocking interviews or coding agents while Graphiti/Qdrant/rerank/import work waits.
    - Fix: add prompt-path SLO, deadline propagation, per-stage budgets and degradation decisions.

92. Fallback context behavior was not contractually typed.
    - Risk: clients cannot tell full context from partial/cache/local/no-memory fallback and may over-trust degraded evidence.
    - Fix: add `ContextDegradationDecision`, `PromptPathBudget` and `FallbackContextPlan` with response-safe diagnostics.

93. Adapter calls on the prompt path lacked a hard wait policy.
    - Risk: one slow graph/vector/rerank/provider call can consume the full desktop timeout or starve unrelated users.
    - Fix: require bounded parallel retrieval, cancellable adapter calls, reserved interactive capacity and stage timeout tests.

94. Fact currency and contradiction handling were scattered.
    - Risk: old, contradicted or environment-specific facts can remain active and keep influencing future chats.
    - Fix: add `FactCurrencyState`, `FactConflictRecord`, `SupersessionDecision` and review/apply rules.

95. Automatic updates lacked a conservative resolution contract.
    - Risk: classifier or import can silently overwrite a correct fact based on a newer but weaker source.
    - Fix: require source trust, temporal confidence, reviewer gates and conflict proof before auto-supersede.

96. Current-fact selection was not explicit enough.
    - Risk: context packing can mix current, disputed, stale and superseded facts because each query applies its own ranking.
    - Fix: define current fact resolver, disputed fact labels, source precedence and negative tests.

97. Write-path poisoning defenses were implicit.
    - Risk: prompt injection, malicious documents, assistant output or compromised connectors can become long-term memory before read-path safety gets a chance to help.
    - Fix: add `WriteIntent`, `MemoryWriteAdmission`, `PoisoningSignal` and quarantine/review decisions before fact creation.

98. Source trust was mostly a confidence input, not a write gate.
    - Risk: low-trust or provenance-less data still enters canonical memory and later competes with trusted facts.
    - Fix: make source trust, provenance, sensitivity and instruction-like content part of mandatory write admission.

99. Connector/agent self-poisoning needed a stronger boundary.
    - Risk: an agent can write a memory that later controls itself or another agent as if it were an instruction.
    - Fix: classify write origin, block self-approval, mark all memory as evidence and require review for instruction-like candidates.

100. Write admission existed as a model, but not every write use case called it explicitly.
    - Risk: document, episode, connector or classifier paths bypass the poisoning gate even though the architecture claims it is mandatory.
    - Fix: wire write admission into remember, ingest episode, ingest document, connector ingest, classifier candidate and review approval flows.

101. Data residency was not first-class.
    - Risk: local-to-remote migration, future team server or SaaS mode can move raw memory, embeddings, backups or exports to the wrong region/provider without a domain decision.
    - Fix: add `DeploymentRegion`, `DataResidencyPolicy`, `ProcessingLocationDecision` and region checks before storage, provider, backup, export and sync actions.

102. External processing had provider allowlists, but no placement proof.
    - Risk: a model call can be policy-approved by provider/model but still violate allowed processing location or subprocessor rules.
    - Fix: every external AI, embedding, OCR, rerank and managed storage action records a safe processing-location decision.

103. Backup/export/sync could become cross-region transfer paths.
    - Risk: even if live storage is correct, artifacts and future sync bundles can bypass residency constraints.
    - Fix: treat artifact creation, artifact download, backup restore, import and sync change-set apply as residency-checked use cases.

104. Repository/query isolation was not first-class.
    - Risk: one raw SQL, ORM repository method, worker scan or bulk admin action can forget `space_id`/`profile_id` and leak or mutate another memory space.
    - Fix: add `RepositoryScope`, `ScopedRepositoryContext`, `QueryScopeProof` and repository contract tests for scoped reads and writes.

105. Read visibility guards did not cover every write and maintenance path.
    - Risk: retention, backfill, projection rebuild, restore, export or delete jobs can bypass `ReadScope` because they are not user-visible reads.
    - Fix: make scoped repository context mandatory for normal repository calls and require explicit `MaintenanceScopeOverride` for broad operations.

106. Database-level defense-in-depth was only implicit.
    - Risk: application-level scope bugs or connection-pool session mistakes can return cross-tenant rows before canonical filters run.
    - Fix: design for optional Postgres RLS/transaction-scoped settings in remote/team mode and require unscoped-query negative tests in v1.

107. Supply-chain gates were checklists, not domain/ops contracts.
    - Risk: Graphiti, Qdrant, parser/OCR, LLM and storage SDK changes can alter behavior, introduce CVEs or unsafe licenses without visible rollout control.
    - Fix: add dependency inventory, risk findings, license policy and release attestation as governed deployment artifacts.

108. Parser sandboxing was not explicit enough.
    - Risk: hostile PDFs, archives, Office docs or OCR inputs can exploit parser bugs, fetch network resources or exhaust CPU/memory before write admission runs.
    - Fix: add `ParserSandboxPolicy`, `ParserExecutionRun`, resource limits, network-deny defaults and quarantine behavior before extraction.

109. Security waivers lacked lifecycle and audit.
    - Risk: a temporary CVE/license waiver becomes permanent and remote/team releases keep shipping with known risk.
    - Fix: make waivers expiring, scoped, reviewer-approved and visible in release gates.

### Local Code Assumptions Checked

Checked in Client App on 2026-05-24:

- `src-tauri/src/presentation/interview_memory_bridge.rs` already resolves `InterviewMemoryMode` with `disabled`, `shadow_ingest`, `shadow_retrieve`, `assistive_context`, `active_context` and `local_only`.
- The desktop bridge currently skips ingest for `AiResponse` timeline events. Universal auto-memory must preserve this unless a policy explicitly allows assistant-derived evidence.
- The desktop bridge currently calls `/api/v1/interview-memory/ingest` and `/api/v1/interview-memory/context`, not the new `/v1/*` platform API.
- `INTERVIEW_MEMORY_AUTH_TOKEN` is a memory-only auth override and must not change normal app auth.
- `src-tauri/src/infrastructure/interview_memory_session_store.rs` stores a persistent active profile/session JSON with schema version `1` and default profile id `default`.
- `src-tauri/src/infrastructure/local_interview_memory.rs` has a local Postgres fallback path and OpenAI embeddings can be enabled through env. New platform rollout must not create a second uncontrolled local memory path.
- Existing E2E scripts already verify canary, document recall, import and companion retrieval against `/api/v1/interview-memory/*`.

### Implementation Navigation Map

Use this map when implementing or reviewing a PR. A PR should explicitly state which rows it touches.

| Concern | Primary sections | Must not violate |
|---|---|---|
| Clean boundaries | Architectural Principles, Package Layout, Ports, First Concrete PR | `memo_stack_core` must not import infrastructure clients or FastAPI |
| Contract schemas | Contract and DTO Schema Layer, API Contract, SDK Contract, CI Gates | domain entities are never exposed directly as public DTOs |
| Bootstrap and runtime config | Bootstrap and Runtime Configuration Model, Deployment, Security and Privacy | first owner/token/config are provisioned once and cannot become auth bypass |
| Migration and upgrade safety | Migration and Upgrade Governance Model, Deployment, CI Gates | schema, data, contract and projection upgrades move through explicit phases |
| Worker and scheduler execution | Worker and Scheduler Orchestration Model, Consistency Model, Operational Runbooks | background work is leased, heartbeat-based, idempotent and safe with multiple processes |
| Blob and artifact lifecycle | Storage Object and Artifact Model, Document Processing Pipeline, Security and Privacy | raw files, uploads, exports and backups are governed canonical records |
| Backup and restore lifecycle | Backup, Restore and Disaster Recovery Model, Operational Runbooks, Security and Privacy | restore cannot resurrect hard-deleted data or bypass key/access policy |
| Canonical truth | Domain Model, Postgres Adapter, Consistency Model, Fact Lifecycle | Graphiti/Qdrant are never source of truth |
| Graph memory | Graphiti Adapter, Phase 3, Edge Cases, Evaluation Harness | backend-specific graph behavior stays behind `GraphMemoryPort` |
| Vector/RAG memory | Qdrant Adapter, Chunking, Document Processing Pipeline, Phase 2 | Qdrant payload filters and indexes are required |
| Derived projection state | Derived Index Projection Model, Consistency Model, Operational Runbooks | Graphiti/Qdrant indexing status is tracked by canonical aggregate version and rebuild generation |
| Policy and auto-memory | MemoryPolicy, ClassifyEpisodeUseCase, Review Workflow, Phase 4.5 | auto-memory cannot bypass source refs, grants or sensitivity rules |
| Write-path trust and poisoning defense | Memory Write Trust and Poisoning Defense Model, SourceProvenance, MemoryPolicy | untrusted or instruction-like input cannot become active memory without review |
| Entity resolution | MemoryEntity, EntityResolutionPort, Graphiti Adapter, Edge Cases | Graphiti candidate merges do not become canonical merges automatically |
| Temporal validity | Temporal Memory Semantics, MemoryFact, Retrieval and Context Packing | current context must not mix expired or historical facts silently |
| Fact currency and conflicts | Fact Currency and Conflict Resolution Model, Evidence and Confidence Model, Retrieval and Context Packing | old or contradicted facts do not remain silently active |
| Prompt-path SLO | Prompt-Path SLO and Degradation Model, Retrieval and Context Packing, Client App Compatibility Contract | context calls have explicit deadlines, stage budgets and safe degraded outputs |
| Evidence quality | Evidence and Confidence Model, SourceRef, MemoryPolicy | repeated derived summaries do not raise confidence by themselves |
| Memory consolidation | Memory Consolidation Model, ConsolidateMemoryUseCase, Evaluation Harness | dedupe and digest jobs preserve source refs and never turn derived summaries into primary evidence |
| AI provider governance | AI Provider Governance, Embedding Adapter, Classifier Adapter, Security and Privacy | external providers cannot bypass policy, redaction, budgets or audit |
| Usage and quota governance | Usage and Quota Governance Model, QuotaPort, Consistency Model | expensive work is admitted through policy, reservations and fairness, not best-effort guesses |
| Redaction and privacy transforms | Redaction Pipeline, DataSensitivity, SourceRef, Security and Privacy | redacted text keeps source mapping and raw secrets are not embedded/logged |
| Key and token security | Key Management, Token Storage and Audit Integrity, Security and Privacy | raw tokens are never stored and key rotation does not break recall/delete |
| Data residency and regional placement | Data Residency and Regional Placement, MemorySpace, MemoryPolicy, AI Provider Governance | storage, external processing, backup/export/import and sync cannot cross configured location boundaries silently |
| Supply-chain and parser sandbox | Supply Chain and Parser Sandbox Governance, Document Processing Pipeline, CI Gates | dependencies, parsers and release artifacts cannot drift into unsafe versions/licenses without audit |
| Audit integrity | Token Storage and Audit Integrity, AuditPort, Risk Register | destructive actions and exports are append-only and tamper-evident |
| Connector lifecycle | Connector Lifecycle, Connector and MCP Contract, API Contract | connectors can be installed, paused, backfilled, rotated and revoked safely |
| Event delivery | Event Delivery and Client Cache Contract, Consistency Model, SDK Contract | clients do not reuse stale context after update/delete/policy events |
| Cache/freshness governance | Cache and Freshness Governance Model, Retrieval and Context Packing, Consistency Model | server caches never bypass canonical filters, grants, policy versions or tombstones |
| Read-path visibility guard | Canonical Visibility and Read-Path Guard Model, API Contract, Security and Privacy | every search/list/context/export/debug read has explicit `ReadScope` and `VisibilityProof` |
| Repository/query isolation | Canonical Query and Repository Scope Model, Postgres Adapter, Worker and Scheduler Orchestration Model | every repository read/write/bulk path carries a scoped context or explicit audited override |
| Local-to-cloud sync readiness | Sync Readiness Model, Import/export, Consistency Model | sync uses canonical ids, checkpoints, tombstones and conflict records, not derived index ids |
| MCP agent safety | Connector and MCP Contract, MemoryPolicy, AuthorizationPort | agents cannot self-approve or perform destructive operations without explicit grants |
| Coding-agent scope | Coding Agent Memory Semantics, SourceProvenance, Retrieval and Context Packing | repo/branch/commit-scoped memory does not leak into unrelated code work |
| Code references | CodeReference, SourceRef, Evaluation Harness | file/symbol/line refs degrade safely after rename/rebase/line drift |
| Retention lifecycle | Retention and Legal Hold Model, MemoryPolicy, Aggregate Lifecycle State Machines | data expiry is dry-runnable, auditable and policy-aware |
| Legal hold | Retention and Legal Hold Model, Security and Privacy, Export/import | held records are preserved and clearly excluded from destructive cleanup |
| Documents and large files | Document, DocumentChunk, IngestDocumentUseCase, Document Processing Pipeline | large raw files do not go into Graphiti |
| Lifecycle correctness | Fact Lifecycle, Aggregate Lifecycle State Machines, Consistency Model | deleted/superseded/disabled records are filtered by canonical status |
| Operation/idempotency | Operation and Idempotency Model, API Contract, SDK Contract | retries and long-running operations return stable, safe, client-visible state |
| Compatibility | API Contract, SDK Contract, Client App Compatibility Contract | legacy `/api/v1/interview-memory/*` keeps desktop behavior stable |
| Security and tenancy | Principal, MemorySpace, ProfileGrant, AuthorizationPort, Security and Privacy | profile/space leakage is a release blocker |
| Operations | Deployment, Observability, Rollback, CI Gates | derived indexes must be rebuildable from Postgres |
| Release governance | Contract Version Compatibility Matrix, ADR and PR Discipline, Done Definition | breaking changes require explicit version/ADR/release note |

### Decision Traceability Matrix

| Decision | Why it exists | Code boundary | Required tests | Release risk if broken |
|---|---|---|---|---|
| Postgres is canonical truth | prevents stale Graphiti/Qdrant from becoming user-visible truth | `FactRepositoryPort`, `DocumentRepositoryPort`, `UnitOfWorkPort` | delete filters, supersede filters, rebuild from canonical data | stale or deleted memory leaks into context |
| Graphiti is a derived temporal graph | gives temporal facts, relations and entity memory without owning lifecycle | `GraphMemoryPort`, `GraphitiAdapter` | capability detection, temporal relation sync, stale graph result filtering | vendor/backend lock-in or wrong fact validity |
| Qdrant is a derived vector/RAG index | handles large docs, chunks and semantic retrieval | `VectorMemoryPort`, `QdrantAdapter` | payload indexes, chunk retrieval, stale vector result filtering | slow search or private chunk leakage |
| Projection state is canonical metadata | makes rebuild/drift/deindex observable and resumable | `ProjectionState`, `ProjectionMapping`, `ProjectionRebuildJob` | mapping, watermark, rebuild resume and drift tests | derived indexes silently drift from Postgres |
| Public operations are not outbox jobs | gives SDKs stable progress/retry semantics without leaking worker internals | `ClientOperation`, `IdempotencyRecord`, `OperationResultSnapshot` | timeout/retry, response snapshot, cancel and resume tests | retries duplicate data or clients poll unsafe internals |
| Canonical contract schemas | keeps API, SDK, events, bundles and MCP tools aligned | `memo_stack_contracts`, schema registry, DTO mappers | schema roundtrip, unknown enum and OpenAPI fixture tests | clients drift or import/export becomes incompatible |
| Bootstrap is explicit and locked | prevents open first-admin flows and config drift | `BootstrapState`, `RuntimeConfigSnapshot`, bootstrap CLI/API | first boot, token reuse, auth mode downgrade and worker config tests | server starts open or different processes run different policies |
| Upgrades are phased and observable | prevents mixed schema/worker/index states from corrupting memory | `SchemaMigrationRun`, `DataBackfillJob`, migration lock, compatibility window | upgrade dry-run, backfill resume, old worker guard tests | partial upgrade corrupts data or blocks safe rollback |
| Workers and schedulers are leased | keeps background work safe with one or many processes | `WorkerInstance`, `WorkerLease`, `ScheduledTask`, outbox claim | heartbeat, singleton scheduler, shutdown and crash recovery tests | duplicate maintenance jobs or stuck leases corrupt operations |
| Blobs are canonical metadata plus object storage | prevents missing/raw leaked files from bypassing policy | `StorageObject`, `UploadSession`, `MemoryArtifact`, object storage adapter | checksum, quarantine, hard-delete, artifact expiry tests | raw files leak or documents point to missing blobs |
| Backups are governed artifacts | prevents backups from becoming weaker hidden memory stores | `BackupPolicy`, `BackupRun`, `BackupManifest`, `RestoreRun` | backup manifest, PITR, hard-delete and key-availability tests | restore loses data or resurrects deleted memory |
| Policy-driven memory modes | supports manual, review-gated and future auto-memory safely | `MemoryPolicy`, `ClassifyEpisodeUseCase`, `ReviewMemorySuggestionUseCase` | policy mode matrix, auto_safe precision, assistant feedback loop negative test | accidental auto-persistence of noisy/private data |
| Source refs are mandatory for facts | makes memory auditable, removable and explainable | `SourceRef`, `SourceProvenance`, `RememberFactUseCase` | source ref validation, document delete cascade, provenance enforcement | hallucinated or orphaned facts |
| Write admission is mandatory | blocks memory poisoning before canonical fact creation | `WriteIntent`, `MemoryWriteAdmission`, `PoisoningSignal`, `WriteAdmissionPort` | prompt-injection, provenance-less, self-approval and quarantine tests | malicious source becomes long-term instruction-like memory |
| Canonical entity resolution | prevents graph/client merge errors from corrupting long-term memory | `MemoryEntity`, `EntityResolutionPort`, entity aliases | ambiguous entity test, merge/split audit, Graphiti candidate merge filtering | wrong person/project/package facts pollute context |
| Temporal query semantics | keeps current, historical and future-dated facts separate | `TemporalMemorySemantics`, fact validity fields, retrieval filters | `as_of` tests, expired fact tests, source time vs ingest time tests | obsolete decisions look current |
| Fact currency is explicit | makes update/actualize behavior safe and reviewable | `FactCurrencyState`, `FactConflictRecord`, `SupersessionDecision`, current fact resolver | stale/current/disputed/supersede tests | stale or contradicted facts keep influencing context |
| Prompt path has hard deadlines | keeps interviews/agents responsive even when indexes/providers are slow | `PromptPathBudget`, `ContextDegradationDecision`, `FallbackContextPlan`, deadline propagation | graph/vector/rerank timeout, degraded context and fallback tests | correct memory blocks the live workflow |
| Evidence confidence model | keeps auto-memory conservative and auditable | `SourceRef`, `EvidenceScoringPort`, `MemoryPolicy` | confidence monotonicity tests, derived-summary negative tests | hallucinations get promoted |
| Consolidation is a derived quality layer | keeps long-term memory compact without corrupting facts | `MemoryCluster`, `MemoryDigest`, `ConsolidationJob` | duplicate cluster, digest staleness, false-merge and source deletion tests | memory becomes noisy or summaries become fake facts |
| AI provider governance | prevents hidden external calls, cost spikes and prompt drift | provider registry, `RedactionPort`, prompt template/version store, quota/circuit breaker | external-call blocked tests, prompt schema tests, budget tests | private data or runaway cost leaks out |
| Admission control is domain-owned | protects prompt path and limits cost/noisy neighbors | `QuotaRule`, `QuotaReservation`, `AdmissionDecision`, workload queues | reservation lifecycle, fairness and quota exhaustion tests | one import/agent loop starves all users |
| Redaction pipeline | lets external processing use safer text without breaking citations | redaction artifacts, source offset maps, sensitivity downgrade rules | offset mapping tests, secret remediation tests, export tests | citations break or secrets are embedded |
| Key management | keeps raw memory/backups/export secure across local and team deployments | `KeyManagementPort`, encrypted storage metadata, key versions | key rotation tests, backup restore tests, hard-delete tests | data becomes unreadable or leaks from backups |
| Residency policy is explicit | keeps local, team and future SaaS deployments from silently moving memory across regions/providers | `DeploymentRegion`, `DataResidencyPolicy`, `ProcessingLocationDecision`, `ResidencyPolicyPort` | storage/provider/export/backup/sync region denial tests | private memory leaves the allowed deployment boundary |
| Supply-chain state is governed | keeps parser/provider/vector/graph dependencies and release artifacts reviewable | `DependencyInventory`, `DependencyRiskFinding`, `ParserSandboxPolicy`, `ReleaseArtifactAttestation` | CVE, license, parser sandbox and waiver expiry tests | vulnerable parser/provider dependency reaches team deployment |
| Token storage | prevents bearer-token database/log leaks from becoming full access | token hash store, scoped grants, audit | token rotation/revocation tests, prefix-only diagnostics | leaked DB/logs allow memory access |
| Audit integrity | makes destructive/admin events tamper-evident | append-only audit, hash chain, audit export | audit chain verification tests | exports/deletes/policy changes become unverifiable |
| Connector lifecycle | makes multi-client memory manageable and revocable | `ConnectorInstallation`, `ConnectorSyncState`, connector ports | install/pause/resume/backfill/deactivate tests | stale or rogue connector keeps writing memory |
| Event delivery and cache invalidation | keeps SDK/MCP/desktop clients from using stale context | event subscriptions, cursor, cache invalidation envelope | ordered event delivery, cursor expiry, cache bust tests | deleted/updated memory remains in client caches |
| Cache is derived and bounded | prevents stale/deleted/forbidden context leaks from server caches | `CachePolicy`, `CacheEntryMetadata`, `CacheInvalidationRecord`, cache repository port | forget/update/grant-change/policy-change cache-bust tests | old or forbidden memory reappears from cache |
| Read visibility is centrally guarded | prevents one endpoint from forgetting auth/status filters | `ReadScope`, `VisibilityPredicate`, `VisibilityProof`, `VisibilityGuardPort` | endpoint guard, denial leakage and export/list/context visibility tests | cross-profile or deleted data leaks from a side path |
| Repository queries are scoped | prevents a lower-level repository, worker or admin bulk query from bypassing profile/space filters | `RepositoryScope`, `ScopedRepositoryContext`, `QueryScopeProof`, `MaintenanceScopeOverride` | unscoped SQL, bulk delete, worker scan and RLS safety tests | one missed `space_id` leaks or mutates another tenant |
| Sync exchange is feature-gated | keeps v1 sync-ready without promising unsafe bidirectional sync | `SyncPeer`, `SyncCheckpoint`, sync ports and capabilities flag | bundle dry-run, conflict ordering, tombstone propagation tests | local and remote memory diverge silently |
| Webhook authenticity | prevents forged/duplicated connector events | signature verifier, replay window, external sequence | signature/replay/backfill tests | fake or replayed external events create memory |
| Coding-agent scope | keeps architecture decisions relevant to the correct repo/branch/commit | `CodeScope`, `CodeReference`, `SourceProvenance` | branch leakage tests, PR promotion tests, dirty worktree tests | wrong project/branch receives bad architectural advice |
| Durable code references | keeps source attribution useful after code moves | code reference resolver, content hashes, symbol refs | rename/line drift/symbol move tests | memory cites the wrong code |
| Retention lifecycle | prevents unbounded memory growth and accidental deletion | `RetentionRule`, `LegalHold`, retention jobs | dry-run, legal hold, profile delete and derived deindex tests | data is kept forever or deleted too early |
| Legal hold precedence | preserves held evidence while keeping deletion transparent | legal hold repository, tombstone/audit/export rules | hard-delete vs hold tests, export labeling tests | compliance/security hold is violated |
| Compatibility gateway first | lets Client App migrate without prompt-impacting regression | legacy route adapter over core use cases | existing canary, document recall, companion context, mode resolver tests | production desktop memory breaks |
| One Qdrant collection in v1 | keeps local Docker and operations simple | Qdrant collection config and payload filters | diagnostics check missing indexes, profile isolation tests | performance cliffs or cross-profile contamination |
| Neo4j first for Graphiti | pragmatic supported backend for v1 | Graphiti composition root and backend config | healthcheck, capability report, backend mismatch test | local stack becomes unreliable |
| Soft delete plus optional hard delete | supports normal recall removal and privacy/legal removal | `MemoryTombstone`, delete use cases, retention jobs | tombstone, hard-delete, backup/export edge tests | deleted memory resurrects or cannot be purged |
| Ontology is governed | keeps kinds, relations and source types portable across clients | `MemoryOntology`, ontology API, SDK enums | alias resolution, unknown enum behavior, ontology version tests | clients create incompatible memory vocabularies |
| Connectors use scoped principals | lets agents/Slack/GitHub write safely | connector auth, `AuthorizationPort`, `SourceProvenance` | scoped token tests, self-approval block, provenance-required tests | agent or integration writes outside allowed profile |

### Decision 1 - Server-first with local Docker, sync-ready later

🎯 9   🛡️ 8   🧠 6
Estimated changes: included in core `15500-28500` lines.

Выбираем:

```text
memo_stack_server first
local Docker for personal/dev usage
remote server later with same API
future sync supported by event/outbox schema, but not implemented in v1
```

Причина:

- проще подключать Client App, Codex, Claude, Slack, GitHub через один HTTP/SDK contract;
- server deployment можно переиспользовать между проектами;
- local Docker остается удобным personal mode;
- будущий local-first sync не блокируется, если outbox/event log сделаны аккуратно.

Не делаем в v1:

- multi-device CRDT;
- bidirectional cloud sync;
- conflict UI.

Но закладываем:

- stable ids;
- audit/outbox events;
- `updated_at`, `version`, tombstones;
- import/export;
- server capabilities endpoint.

### Decision 2 - Memory behavior is policy-driven, not hardcoded

🎯 10   🛡️ 9   🧠 7
Estimated changes: `800-1800` lines across policy model, classifier orchestration and tests.

Архитектура обязана поддерживать разные режимы памяти:

```text
manual_only
explicit_only
suggestions
auto_safe
auto_aggressive
shadow
disabled
```

Default v1:

```text
explicit facts save immediately
classifier-extracted facts become suggestions
auto promotion is supported by policy model but conservative by default
```

Future target:

```text
auto-memory can be enabled per space/profile/source/kind
```

Это важно: автозапоминание мощное и нужно проектировать его сразу как first-class capability, а не как будущий хак поверх ручного remember.

### Decision 3 - CLI/admin diagnostics in v1, full UI later

🎯 9   🛡️ 8   🧠 5
Estimated changes: `600-1200` lines.

V1 должен иметь:

- fact history;
- search diagnostics;
- source refs;
- outbox status;
- index lag;
- profile stats;
- production-safe mode.

Full Memory UI откладываем. Но без inspector вообще нельзя, иначе memory bugs станут неотлаживаемой магией.

### Decision 4 - Graphiti backend starts with Neo4j

🎯 8   🛡️ 8   🧠 6
Estimated changes: `300-700` lines.

Выбираем Neo4j first:

- зрелее tooling;
- проще graph debugging;
- лучше для первых integration tests;
- меньше риска при сложных temporal/fact graph investigations.

FalkorDB оставляем later adapter/config option, когда core будет стабилен.

### Decision 5 - Qdrant one collection plus payload filters in v1

🎯 8   🛡️ 8   🧠 5
Estimated changes: `500-1000` lines.

Выбираем одну collection:

```text
memory_chunks
```

С обязательными payload filters:

```text
space_id
profile_id
thread_id
document_id
chunk_id
status_hint
embedding_model
schema_version
```

Per-space/per-profile collections возможны позже, если появится реальная проблема масштаба или isolation.

### Decision 6 - Forget supports both tombstone and hard delete

🎯 9   🛡️ 9   🧠 7
Estimated changes: `600-1400` lines.

Нужны оба режима:

```text
soft_forget:
  mark deleted, create tombstone, keep audit/minimal metadata

hard_delete:
  physically delete raw content and derived records where policy allows
```

Default:

```text
soft_forget for normal product operations
hard_delete for privacy/legal/user explicit purge
```

Hard delete должен быть аккуратным:

- source text удаляется;
- Qdrant chunks удаляются;
- Graphiti data deindexed best-effort;
- audit keeps minimal non-sensitive event if policy allows;
- search must hide immediately even before deindex completes.

## Architectural Principles

### Clean Architecture

Dependency rule:

```text
domain -> no dependencies
application -> domain + ports
adapters -> ports + external libraries
server -> application + adapters composition
sdk -> HTTP client only
```

Allowed dependency direction:

```text
memo_stack_server
  -> memo_stack_adapters
  -> memo_stack_core.application
  -> memo_stack_core.domain

memo_stack_sdk
  -> HTTP API
```

Forbidden:

```text
domain imports graphiti
domain imports qdrant_client
domain imports sqlalchemy
application imports fastapi
Client App imports graphiti/qdrant
```

### SOLID

SRP:

- `MemoryFact` отвечает за fact lifecycle invariants.
- `IngestEpisodeUseCase` отвечает за ingestion orchestration.
- `GraphMemoryPort` отвечает только за graph index operations.
- `VectorMemoryPort` отвечает только за vector index operations.
- `ContextBuilderUseCase` отвечает только за retrieval normalization and packing.

OCP:

- новый graph engine добавляется новым adapter;
- новый vector DB добавляется новым adapter;
- новый LLM/classifier добавляется новым adapter;
- core use cases не меняются ради конкретного provider.

LSP:

- любой `GraphMemoryPort` adapter обязан поддерживать same behavior contract: upsert, search, delete/deindex best-effort, health.
- если adapter не поддерживает feature, он явно возвращает capability flag, а не имитирует успех.

ISP:

Не делаем один жирный `MemoryProvider`.

Вместо этого:

```text
FactRepositoryPort
EpisodeRepositoryPort
DocumentRepositoryPort
ProfileRepositoryPort
PrincipalRepositoryPort
AuthorizationPort
UnitOfWorkPort
GraphMemoryPort
VectorMemoryPort
EmbeddingPort
ClassifierPort
RerankerPort
ObjectStoragePort
OutboxPort
AuditPort
QuotaPort
CacheRepositoryPort
```

DIP:

- use cases зависят от ports;
- adapters реализуют ports;
- composition root живет в `memo_stack_server`.

### Simple DDD

Используем DDD pragmatically, без тяжелого ceremony.

Bounded contexts:

```text
Workspace Context
  Principal, MemorySpace, SpaceMember, ProfileGrant, MemoryProfile, MemoryThread

Knowledge Context
  MemoryFact, FactVersion, FactRelation, MemoryTombstone, MemorySuggestion, MemoryKind, RelationType

Fact Currency Context
  FactCurrencyState, FactConflictRecord, SupersessionDecision, CurrentFactSet

Write Trust Context
  WriteIntent, MemoryWriteAdmission, PoisoningSignal, QuarantinedMemoryCandidate

Ingestion Context
  MemoryEpisode, Document, DocumentChunk, SourceRef, SourceProvenance

Retrieval Context
  SearchQuery, RetrievedMemory, ContextBundle

Governance Context
  MemoryPolicy, MemoryOntology, DataSensitivity, AuditEvent, RetentionRule, QuotaRule

Regional Governance Context
  DeploymentRegion, DataResidencyPolicy, ProcessingLocationDecision, CrossRegionTransferRequest

Access Context
  ReadScope, VisibilityPredicate, VisibilityProof, DeniedReadPolicy

Query Isolation Context
  RepositoryScope, ScopedRepositoryContext, QueryScopeProof, MaintenanceScopeOverride

Supply Chain Context
  DependencyInventory, DependencyRiskFinding, LicensePolicy, ParserSandboxPolicy, ParserExecutionRun, ReleaseArtifactAttestation

Prompt Runtime Context
  PromptPathBudget, ContextStageBudget, ContextDegradationDecision, FallbackContextPlan

Cache/Freshness Context
  CachePolicy, CacheEntryMetadata, CacheInvalidationRecord, CacheFreshnessDecision

Operations Context
  BackupPolicy, BackupRun, BackupManifest, RestoreRun, RestoreValidationReport
```

## High-Level Architecture

```mermaid
flowchart TD
  A["Client App: Client App, Codex, Claude, Slack"] --> B["memo_stack_sdk or HTTP API"]
  B --> C["memo_stack_server: FastAPI"]
  C --> D["application use cases"]
  D --> E["domain model"]
  D --> F["ports"]
  F --> G["Postgres Adapter: canonical DB"]
  F --> H["Graphiti Adapter: temporal graph index"]
  F --> I["Qdrant Adapter: vector/RAG index"]
  F --> J["Object Storage Adapter: files"]
  F --> K["LLM/Embedding/Classifier Adapters"]
  F --> N["Cache Adapter: derived freshness-bounded cache"]
  G --> L["Outbox"]
  L --> M["Worker"]
  M --> H
  M --> I
```

Request path:

```text
client -> memo_stack_server API -> use case -> canonical Postgres transaction -> outbox -> async indexes
```

Search path:

```text
client -> search/context API -> vector/graph adapters -> canonical filter in Postgres -> pack context
```

Important:

- Writes should not fail just because Graphiti/Qdrant is temporarily down.
- Search can degrade when indexes are down, but must never return deleted/superseded facts.
- All context returned to clients must include source refs and memory ids.

## Package Layout

Recommended Python workspace:

```text
memo_stack/
  pyproject.toml
  README.md
  docker-compose.yml
  .env.example

  packages/
    memo_stack_contracts/
      pyproject.toml
      memo_stack_contracts/
        commands/
        responses/
        events/
        bundles/
        schemas/
        fixtures/
        registry.py

    memo_stack_core/
      pyproject.toml
      memo_stack_core/
        domain/
          entities/
          value_objects/
          events/
          errors.py
        application/
          use_cases/
          services/
          policies/
        ports/
        dto/
        contracts/

    memo_stack_adapters/
      pyproject.toml
      memo_stack_adapters/
        postgres/
        graphiti/
        qdrant/
        llm/
        embeddings/
        classifier/
        storage/
        cache/
        observability/

    memo_stack_server/
      pyproject.toml
      memo_stack_server/
        api/
        workers/
        migrations/
        auth/
        config/
        composition.py
        main.py

    memo_stack_sdk/
      pyproject.toml
      memo_stack_sdk/
        client.py
        models.py
        errors.py

    memo_stack_mcp/
      pyproject.toml
      memo_stack_mcp/
        server.py

  scripts/
    dev_up.sh
    dev_down.sh
    dev_reset.sh
    check_openapi.py
    check_import_boundaries.py

  tests/
    fixtures/
      small_golden/
      compatibility/
      documents/

  docs/
    adr/
    runbooks/
```

Shorter v1 layout is acceptable:

```text
memo_stack_contracts/
memo_stack_core/
memo_stack_adapters/
memo_stack_server/
memo_stack_sdk/
```

But keep imports and boundaries as if packages were split.

### Developer Tooling Baseline

Recommended Python tooling:

```text
uv or poetry for dependency locking
ruff for lint/format
mypy or pyright for type checks
pytest for tests
pytest-asyncio for async use cases
testcontainers or docker compose for adapter integration tests
alembic for Postgres migrations
```

Rules:

- dependencies must be locked;
- adapter dependencies stay out of `memo_stack_core`;
- generated OpenAPI is checked in or compared deterministically in CI;
- no CI step should require real external AI credentials;
- tests that need external providers are opt-in and skipped by default;
- fixture data must be synthetic or explicitly sanitized.

## Contract and DTO Schema Layer

This layer exists because reusable memory is an integration product. The public contract must be more stable than the internal domain model.

Key rule:

```text
Domain entities are not API models.
API models are not database rows.
Database rows are not SDK models.
```

Recommended package:

```text
memo_stack_contracts/
  commands/
    remember_fact.py
    update_fact.py
    forget_fact.py
    ingest_document.py
    build_context.py
  responses/
    fact.py
    document.py
    context.py
    operation.py
    error.py
  events/
    memory_event.py
    cache_invalidation.py
  bundles/
    export_bundle.py
    import_report.py
    sync_change_set.py
  schemas/
    json_schema/
    openapi_overrides/
  fixtures/
    requests/
    responses/
    events/
    bundles/
  registry.py
```

Ownership:

- `memo_stack_contracts` owns public DTOs, JSON schema ids, fixture examples and version metadata;
- `memo_stack_core` owns domain entities, value objects, use-case commands and domain errors;
- `memo_stack_server` maps HTTP requests into application commands and maps results into public DTOs;
- `memo_stack_sdk` consumes generated or shared contract models, but does not import domain entities;
- import/export, event cursor, MCP tools and legacy compatibility routes use the same public DTO families where possible.

Contract families:

```text
Command DTOs:
  external request intent, validated before use-case call

Result DTOs:
  response-safe canonical output, never raw database rows

Context DTOs:
  prompt-safe evidence items with source/confidence/temporal labels

Event DTOs:
  cache invalidation and sync hints, no raw private text by default

Bundle DTOs:
  export/import/sync payloads with schema, ontology, policy and tombstone versions

Error DTOs:
  typed errors with safe details and stable machine behavior

Capability DTOs:
  server-supported versions, features, limits and adapter modes
```

Schema registry fields:

```text
schema_id
schema_version
contract_family
owner_package
introduced_in
deprecated_in?
removed_in?
json_schema_hash
openapi_component_name?
fixture_paths[]
compatibility_notes
```

Mapping rules:

- every public DTO has an explicit mapper from use-case result or domain projection;
- mapper code must live outside domain entities;
- no ORM model, Graphiti object, Qdrant payload or FastAPI request model is returned directly to SDKs;
- mappers must preserve ids, versions, status, source refs, sensitivity labels and operation ids;
- mappers must redact or omit raw text according to caller scope and DTO purpose;
- legacy Client App envelope mappers are adapters over the same result DTOs, not a forked contract;
- failed mapping is a typed internal error and must be observable without logging raw payloads.

Evolution rules:

- adding optional fields is allowed when default behavior is unchanged;
- renaming fields requires alias/deprecation window and fixtures for both names when supported;
- removing fields requires new major route or contract version;
- enum additions must be handled as opaque/unsupported values by SDKs;
- `null`, missing field and empty list must have documented distinct meaning when all three are possible;
- timestamps are UTC ISO 8601 strings at API boundary and timezone-aware values internally;
- ids are opaque strings; clients must not parse ids for tenant/profile/type behavior;
- cursors are opaque and may expire with typed `memory.conflict` or cursor-expired code;
- large text/blob fields use object storage references or chunk APIs, not inline event payloads.

Required artifacts:

- deterministic OpenAPI artifact;
- JSON schema files for import/export/event/context payloads;
- golden request/response fixtures for every public endpoint family;
- unknown-field and unknown-enum fixtures for generated SDKs;
- mapper roundtrip tests for source refs, status, versions, sensitivity and operation ids;
- changelog entry for every contract change.

Hard boundary:

```text
memo_stack_core/domain imports memo_stack_contracts: forbidden
memo_stack_contracts imports FastAPI/SQLAlchemy/Graphiti/Qdrant: forbidden
memo_stack_server imports memo_stack_contracts: allowed
memo_stack_sdk imports memo_stack_contracts or generated models: allowed
```

## Bootstrap and Runtime Configuration Model

Bootstrap and config are part of the architecture, not deployment trivia. A reusable memory service must be safe on the first local Docker run and still strict enough for future team/remote usage.

Core invariant:

```text
No memo_stack_server process accepts normal mutating/read API traffic until bootstrap, migrations and runtime config validation are complete.
```

### DeploymentInstance

Represents one running logical memory deployment.

Fields:

```text
id
deployment_mode: local_single_user | team_self_hosted | managed_remote_later
environment: local | test | staging | production | unknown
server_instance_id
lineage_id
status: initializing | bootstrap_required | ready | degraded | read_only | maintenance | misconfigured | locked
bootstrap_state_id
active_config_snapshot_id
created_at
updated_at
metadata
```

Rules:

- `lineage_id` is stable across restarts and backups of the same logical server;
- deployment mode is explicit and cannot be inferred only from host/port;
- production/team mode cannot use dev seed, dev reset or unauthenticated bootstrap endpoints;
- status is reported through health/capabilities without raw secrets.

### BootstrapState

Tracks first setup and recovery state.

Fields:

```text
id
deployment_id
state: uninitialized | bootstrap_pending | bootstrapped | recovery_required | locked
owner_principal_id?
default_space_id?
default_profile_id?
bootstrap_token_hash?
bootstrap_token_expires_at?
recovery_token_hash?
last_bootstrap_attempt_at?
created_at
updated_at
metadata
```

Rules:

- fresh DB starts as `uninitialized`;
- first bootstrap creates owner principal, default space, default profile, default policy and scoped local token when requested;
- bootstrap token is shown once, stored only as hash and expires quickly;
- successful bootstrap deletes or invalidates the one-time bootstrap token;
- bootstrap is idempotent only for the same request fingerprint before completion;
- after `bootstrapped`, first-admin endpoint is disabled unless recovery mode is explicitly enabled by local filesystem/KMS proof;
- bootstrap never grants cross-space or hard-delete/export by accident.

### RuntimeConfigSnapshot

Immutable snapshot of effective runtime configuration.

Fields:

```text
id
deployment_id
config_version
config_hash
source_hashes
auth_mode
external_ai_mode
graph_engine
vector_engine
embedding_provider
enabled_adapters
feature_flags
limits_hash
policy_defaults_hash
created_at
created_by_process
metadata
```

Rules:

- API and worker processes record the effective config hash at startup;
- workers refuse to process jobs requiring capabilities not present in their config snapshot;
- config changes that affect auth, external AI, deletion, export, sync, providers or contract versions require audit;
- capabilities expose config version and safe feature flags, not secrets;
- config snapshots are safe metadata, not a place to store raw keys or tokens.

Config precedence:

```text
CLI explicit flags
environment variables
mounted config file
local dev defaults
hardcoded safe defaults
```

Rules:

- secrets are read from env/file/KMS adapters, not committed config;
- `MEMORY_ALLOW_EXTERNAL_AI=false` is the local default;
- team/remote mode requires explicit auth mode and key provider;
- auth mode cannot be downgraded from JWT/gateway to local token without explicit maintenance command and audit;
- unknown config keys fail startup in strict mode and warn in local dev mode;
- config validation runs before opening normal API routes.

Bootstrap commands:

```text
memo_stack_server bootstrap status
memo_stack_server bootstrap init-local --owner-name ... --space-name ... --profile-name ...
memo_stack_server bootstrap create-token --scope local_setup --ttl 10m
memo_stack_server config doctor
memo_stack_server dev seed --synthetic-only
memo_stack_server dev reset --confirm-local-lineage ...
```

Optional API endpoints:

```text
GET  /v1/bootstrap/status
POST /v1/bootstrap/local-init
GET  /v1/config/status
```

Rules:

- `/v1/bootstrap/status` returns only safe state: required, complete, locked or misconfigured;
- `/v1/bootstrap/local-init` is available only when uninitialized and protected by one-time bootstrap token plus local/private deployment guard;
- CLI bootstrap is preferred for local Docker because it avoids exposing setup semantics publicly;
- config status returns hashes, modes and capability flags, never raw env values.

Required tests:

- first local bootstrap creates owner, default space, default profile, default policy and scoped token;
- second bootstrap attempt after success is rejected;
- expired or reused bootstrap token is rejected;
- team mode cannot use local bootstrap defaults;
- API and worker with different config hash surface degraded/misconfigured status;
- dev seed/reset refuses non-local lineage and non-synthetic fixtures.

## Migration and Upgrade Governance Model

Schema migration is only one part of upgrade safety. The platform also has public contracts, workers, derived indexes, background jobs, SDKs, import/export bundles, policy versions and legacy compatibility routes.

Core invariant:

```text
An upgrade is not complete until schema, data backfill, contract compatibility, worker compatibility and derived index readiness are all verified.
```

### SchemaMigrationRun

Tracks database and contract migration state.

Fields:

```text
id
deployment_id
target_version
from_schema_version
to_schema_version
from_contract_version
to_contract_version
status: planned | dry_run | running | backfill_required | verifying | succeeded | failed | rolled_back | blocked
phase: expand | backfill | dual_read | contract_switch | cleanup
lock_owner
started_at?
finished_at?
safe_rollback_until?
requires_read_only
requires_worker_pause
created_by_principal_id?
metadata
```

Rules:

- migration lock prevents two schema/data upgrade flows from running at once;
- expand phase adds nullable/additive structures first;
- backfill phase is chunked, resumable and idempotent;
- contract switch happens only after old and new DTO/SDK fixtures pass compatibility gates;
- cleanup phase that removes old fields/routes requires compatibility window expiry and ADR;
- failed migration moves deployment to `read_only` or `misconfigured`, not silent partial-ready.

### DataBackfillJob

Represents data migration that can outlive one process.

Fields:

```text
id
migration_run_id
space_id?
profile_id?
backfill_type: schema_default | denormalized_field | contract_projection | ontology_alias | policy_version | projection_metadata | redaction_metadata
status: pending | running | paused | succeeded | failed | dead
source_watermark
resume_cursor?
chunk_size
processed_count
changed_count
skipped_count
blocked_count
last_error_safe?
created_at
updated_at
metadata
```

Rules:

- backfill reads by stable canonical ordering and records cursor/watermark;
- every chunk re-checks canonical status, tombstones, legal holds and current policy;
- backfill writes are idempotent by target aggregate id and migration version;
- backfill never calls Graphiti/Qdrant directly; it updates canonical metadata or schedules projection jobs;
- backfill can pause for interactive capacity or quota constraints;
- dry-run reports counts and blocked reasons without mutating.

### CompatibilityWindow

Defines how long old clients/contracts remain supported.

Fields:

```text
id
contract_family
old_version
new_version
status: active | expiring | expired | extended
supported_client_min_version
supported_client_max_version?
starts_at
expires_at
reason
metadata
```

Rules:

- old SDK/client minor version remains supported during the active window;
- Client App legacy routes have their own compatibility window;
- expired window does not remove behavior automatically; cleanup still requires migration run and ADR;
- capabilities report active compatibility windows and pending expiry dates.

Upgrade phases:

```text
1. dry_run:
   inspect schema, contract versions, active jobs, old clients and derived index drift

2. expand:
   add additive schema/DTO fields, keep old reads/writes working

3. backfill:
   populate new data in chunks with watermark/cursor and tombstone checks

4. dual_read:
   read old and new paths, compare safe ids/counts/results in diagnostics

5. contract_switch:
   make new DTO/path/default active after fixture and SDK checks pass

6. cleanup:
   remove old structures only after compatibility window and rollback boundary expire
```

Runtime rules:

- workers check migration run status before claiming jobs affected by schema or contract changes;
- prompt-time context can keep using old safe read path during expand/backfill;
- destructive cleanup is never part of expand/backfill transaction;
- projection rebuild can be required by migration, but remains a separate operation with generation activation;
- rollback is allowed only before destructive cleanup or irreversible data transformation;
- rollback never deletes newly created canonical audit records.

CLI/API:

```text
memo_stack_server migrate plan
memo_stack_server migrate dry-run
memo_stack_server migrate apply --phase expand
memo_stack_server migrate backfill --job ...
memo_stack_server migrate verify
memo_stack_server migrate cleanup --after-compat-window

GET  /v1/admin/migrations
GET  /v1/admin/migrations/{migration_run_id}
POST /v1/admin/migrations/{migration_run_id}/pause
POST /v1/admin/migrations/{migration_run_id}/resume
```

Required tests:

- expand migration keeps old API/SDK fixtures passing;
- backfill resumes after crash without duplicate changes;
- backfill skips deleted, held or unauthorized records;
- old worker refuses incompatible job claim after migration starts;
- dual-read detects mismatch and blocks contract switch;
- cleanup is blocked before compatibility window expiry.

## Worker and Scheduler Orchestration Model

Workers are part of the domain reliability boundary. Outbox idempotency reduces damage, but safe execution still needs process identity, leases, heartbeats, singleton scheduled tasks and graceful shutdown semantics.

Core invariant:

```text
Every background side effect is owned by a live WorkerInstance lease or is safely reclaimable.
```

### WorkerInstance

Represents one API, worker, scheduler or CLI process that can own work.

Fields:

```text
id
deployment_id
process_kind: api | worker | scheduler | cli
worker_group
hostname_hash
process_id_hash?
binary_version
supported_job_versions[]
config_snapshot_id
status: starting | active | draining | stopped | stale | quarantined
started_at
last_heartbeat_at
stopped_at?
metadata
```

Rules:

- worker identity is generated on start and never reused after process exit;
- process reports supported job/schema/contract versions at registration;
- stale heartbeat marks instance `stale` and makes its leases reclaimable after grace period;
- `quarantined` worker cannot claim new work until manual/admin recovery;
- diagnostics never expose hostnames or process ids raw by default.

### WorkerLease

Short-lived ownership claim for outbox jobs, backfill chunks, scheduled tasks or long maintenance work.

Fields:

```text
id
worker_instance_id
lease_key
work_type: outbox_batch | backfill_chunk | scheduled_task | projection_rebuild | retention_job | export_job | import_job
target_type?
target_id?
status: active | released | expired | stolen | failed
expires_at
heartbeat_at
attempt
created_at
updated_at
metadata
```

Rules:

- lease key is unique while active;
- lease renewal is bounded and cannot hide a permanently stuck job;
- expired lease can be reclaimed only after the job handler proves idempotency or recovery behavior;
- long jobs checkpoint progress before lease renewal;
- releasing lease is idempotent.

### ScheduledTask

Registry entry for recurring or singleton maintenance work.

Fields:

```text
id
task_key
task_type: quota_cleanup | retention_scan | projection_verify | digest_refresh | backfill_dispatch | token_expiry | audit_verify | object_orphan_scan
schedule_kind: interval | cron_like | manual_only
enabled
singleton: true | false
lease_key
last_started_at?
last_completed_at?
last_status?
next_run_at?
metadata
```

Rules:

- scheduled tasks create normal operations/jobs and use normal admission/authorization rules;
- singleton tasks use stable lease keys and cannot run concurrently for the same deployment/scope;
- schedule jitter prevents many deployments from doing expensive work at the same second;
- task failures are visible in diagnostics and do not silently disable future runs unless configured.

Worker lifecycle:

```text
starting -> active -> draining -> stopped
starting -> quarantined
active -> stale
active -> quarantined
draining -> stopped
stale -> stopped
```

Graceful shutdown rules:

- stop claiming new work immediately;
- finish current safe chunk if it fits shutdown budget;
- checkpoint progress before releasing lease;
- release quota reservations when work did not start external side effects;
- leave operation status as `waiting` or `running` with safe reason when another worker can resume;
- do not mark job succeeded until canonical/projection state is durably recorded.

Required tests:

- two schedulers do not run the same singleton task concurrently;
- stale worker heartbeat makes lease reclaimable after grace period;
- graceful shutdown releases claim or checkpoints progress safely;
- worker with unsupported job version cannot claim work;
- repeated scheduler tick creates one logical operation/job due to idempotency;
- external side effect reconciliation prevents duplicate adapter write after crash.

## Cache and Freshness Governance Model

Server-side cache is allowed for latency and cost, but it is a derived performance layer. It must never become an authority for visibility, authorization, policy, lifecycle or deletion.

Core invariant:

```text
Cache may make reads faster, but cannot make forbidden or deleted memory visible.
```

This section covers server-side caches. Client SDK caches are covered by event delivery and TTL rules, but the same freshness ideas apply.

### CachePolicy

Profile or deployment-level policy that defines which cache kinds are allowed and how fresh they must be.

Fields:

```text
id
space_id
profile_id?
policy_version
cache_kind
enabled
ttl_seconds
max_stale_seconds?
allow_stale_on_provider_outage: true | false
requires_canonical_recheck: true | false
stores_raw_text: true | false
stores_response_safe_dto: true | false
stores_ids_only: true | false
sensitivity_max
provider_id?
model_id?
purpose?
created_at
updated_at
metadata
```

Rules:

- `requires_canonical_recheck=true` for every cache that can affect user-visible context/search;
- context/search caches should prefer candidate ids or response-safe DTOs over raw unrestricted text;
- raw text cache is disabled by default for secret/restricted sensitivity;
- provider/model/purpose-specific caches are not reusable across provider, model, prompt schema, redaction or purpose versions;
- TTL is a backstop, not the main correctness mechanism;
- stale cache may degrade latency or recall, but never deletion, authorization or privacy correctness.

### CacheEntryMetadata

Canonical metadata for one server-side cache entry. The cached payload can live in Postgres, Redis, local memory, object storage or another adapter, but metadata is domain-owned.

Fields:

```text
id
space_id
cache_kind:
  context_bundle
  search_result
  candidate_ids
  embedding_vector
  rerank_result
  token_count
  capabilities
  schema_metadata
  diagnostics_summary
profile_ids_hash
principal_id?
connector_id?
grant_version
policy_version
ontology_version
contract_schema_version
query_hash?
query_intent_hash?
temporal_mode: current | as_of | history | future_aware
as_of?
source_commit_position
event_cursor
projection_generation?
adapter_version?
provider_id?
model_id?
prompt_template_version?
redaction_version?
embedding_model_version?
sensitivity_max
payload_storage: postgres | redis | local_memory | object_storage | external_cache
payload_ref?
payload_hash
contains_raw_text: true | false
contains_response_safe_dto: true | false
contains_ids_only: true | false
ttl_seconds
created_at
expires_at
invalidated_at?
invalidation_reason?
metadata
```

Rules:

- every context/search cache key includes `space_id`, profile set, principal or grant version, policy version, ontology version, temporal mode and query hash;
- every context/search cache entry records the canonical commit position or event cursor that it was built from;
- every cached candidate id must be canonical-filtered again before returning user-visible text;
- cached response-safe DTOs can be returned only if their `source_commit_position` is at or after the last relevant invalidation cursor and the DTO still passes current grant/policy/status checks;
- embedding, token-count and rerank caches include provider/model/purpose/schema/redaction dimensions;
- cache payloads must never contain object storage raw keys, bearer tokens, raw secrets or unredacted restricted text;
- cache metadata is safe enough for diagnostics, but payloads may still be sensitive.

### CacheInvalidationRecord

Append-only record that explains why a cache entry or cache family is no longer trusted.

Fields:

```text
id
space_id
profile_id?
principal_id?
cache_kind?
target_type:
  fact
  document
  document_chunk
  digest
  cluster
  profile
  policy
  grant
  ontology
  provider_config
  redaction_rule
  projection_generation
  storage_object
target_id?
reason:
  fact_updated
  fact_deleted
  source_deleted
  source_redacted
  profile_deleted
  grant_changed
  policy_changed
  ontology_changed
  provider_changed
  redaction_changed
  projection_rebuilt
  legal_hold_changed
  retention_applied
  manual_admin
commit_position
event_cursor
created_at
created_by
metadata
```

Rules:

- invalidation is written in the same canonical transaction or immediately after it through the outbox when a direct transaction is impossible;
- invalidation payloads contain ids, versions and reasons, not raw private text;
- server reads compare cache metadata against invalidation cursor before trusting cached payload;
- invalidation records are retained long enough to cover max cache TTL plus client cursor replay window;
- if invalidation retention is too short to prove freshness, cache lookup fails closed and recomputes.

### Cache Kinds

Context bundle cache:

- stores a complete response-safe context bundle or ids needed to rebuild one quickly;
- allowed only for short TTLs;
- must re-check fact/document/digest status, grants, profile membership and policy before return;
- must be invalidated by forget, update, delete, policy change, grant change, profile deletion, legal hold visibility change and source redaction.

Search result cache:

- stores candidate canonical ids and ranking metadata;
- should not store raw snippets unless response-safe DTO rules pass;
- must re-run canonical visibility filtering and may rerank only visible candidates.

Candidate id cache:

- caches expensive graph/vector candidate lookup by query hash and filters;
- safe only when canonical id filtering is mandatory after cache hit;
- can survive derived index lag but cannot outrank newer canonical invalidations.

Embedding vector cache:

- caches embeddings for chunks, queries or redacted artifacts;
- keyed by model, dimensions, provider, redaction version, text hash, sensitivity and purpose;
- invalidated when secret detection, redaction, provider config or embedding model changes;
- cannot be used to reconstruct raw secret text in diagnostics.

Rerank result cache:

- caches model ranking over candidate ids, not raw candidate text by default;
- keyed by query hash, candidate id/version list, reranker model, prompt template and policy version;
- invalidated by candidate update/delete, policy/grant changes or reranker prompt/schema changes.

Token count cache:

- caches tokenizer/model-specific token counts;
- keyed by tokenizer/model version, text hash and rendering template version;
- safe to keep longer, but must not contain raw secret text if text hash is sufficient.

Capabilities/schema cache:

- caches server capability and contract schema metadata;
- invalidated by deployment config, adapter capability, contract schema and policy engine version changes;
- SDKs must treat capability cache as short-lived because feature gates are security-sensitive.

Diagnostics summary cache:

- caches counts and health summaries only;
- never includes raw memory text;
- invalidated by relevant state changes or bounded by short TTL.

### Freshness Decision Algorithm

Every cache hit goes through a small use case before it can affect a response.

```text
lookup cache entry
verify entry not expired
verify entry dimensions match request
verify entry source_commit_position >= required freshness cursor when required
verify no newer invalidation record overlaps entry dimensions
if user-visible memory:
  reload canonical ids or DTO statuses from Postgres
  apply current authz, grant, policy, temporal and sensitivity filters
  drop blocked items
return hit only if remaining payload is safe
otherwise miss and recompute
```

Required freshness inputs:

```text
space_id
profile_ids
principal_id
grant_version
policy_version
ontology_version
temporal_mode
as_of
query_hash
minimum_commit_position?
minimum_event_cursor?
```

Rules:

- normal `build_context` reads require fresh-enough cache or recompute;
- admin diagnostics may show stale cache metadata, but must label it as stale;
- `forget`, `delete`, `policy update`, `grant revoke`, `profile delete`, `legal hold`, `source redaction` and `retention apply` force invalidation before success is reported;
- read-your-write after mutation should bypass stale context/search cache for affected profile/thread/source ids;
- cache stampede prevention is allowed, but waiting requests must still respect request timeout and safety filters.

### Cache Use Cases

```text
ResolveCacheFreshnessUseCase
  input: CacheLookupRequest, RequiredFreshness
  output: CacheFreshnessDecision

InvalidateMemoryCacheUseCase
  input: CacheInvalidationCommand
  output: CacheInvalidationResult

RecordCacheEntryUseCase
  input: CacheEntryMetadata plus payload ref/hash
  output: CacheEntryMetadata

PurgeExpiredCacheUseCase
  input: space/profile/cache_kind window
  output: safe counts
```

Use case rules:

- freshness decisions depend on ports and value objects, not infrastructure cache client APIs;
- invalidation is idempotent by target, reason and commit position;
- purge removes only cache payload/metadata, never canonical memory;
- purge can run as a scheduled task and must be safe under duplicate workers.

### Cache Adapter Boundary

Cache storage is an adapter detail.

Valid v1 implementations:

```text
Postgres table only for metadata plus small payloads
Redis-compatible cache for hot context/search entries
local in-process LRU for single-process dev mode
object storage for large response-safe artifacts when needed
```

Decision for v1:

🎯 8   🛡️ 9   🧠 5
Approx changes: `500-1000` lines.

Start with Postgres metadata and optional in-process LRU for dev. Add Redis adapter later only after freshness tests are stable.

Why:

- keeps Clean Architecture boundary clear;
- avoids making Redis an early operational dependency;
- still leaves a `CacheRepositoryPort` and `CacheStorePort` for future remote/server deployments;
- makes correctness tests independent of cache technology.

Alternative 1 - Redis from day one:

🎯 6   🛡️ 7   🧠 6
Approx changes: `900-1700` lines.

Pros: realistic production latency path earlier. Cons: more Docker/ops, invalidation bugs are harder to inspect, and v1 may optimize before correctness.

Alternative 2 - no server-side cache in v1:

🎯 7   🛡️ 8   🧠 2
Approx changes: `100-300` lines.

Pros: safest correctness. Cons: hides a critical future architecture problem and SDKs may invent incompatible cache behavior.

### Cache Invalidation Triggers

Must invalidate context/search/candidate/rerank caches when:

- fact is created, updated, superseded, disabled, deleted or hard-deleted;
- document or chunk is updated, redacted, deleted, reprocessed or hard-deleted;
- source ref visibility changes;
- digest becomes stale, superseded or deleted;
- cluster membership changes in a way that affects context packing;
- profile grant, space membership, connector token or principal role changes;
- policy, ontology, retention, legal hold or redaction rule changes;
- provider/model/prompt/schema version changes for model-derived cache kinds;
- projection generation is rebuilt or activated;
- profile/thread/space deletion starts or completes.

Must not rely only on TTL for:

- forget/delete;
- grant revoke;
- policy disable;
- secret detection and redaction;
- legal hold visibility changes;
- profile or space deletion.

### Cache Failure Modes

Cache backend down:

- context/search recomputes or degrades according to normal retrieval policy;
- remember/update/forget remain available;
- cache miss storm is visible through metrics but does not block lifecycle safety.

Cache metadata present, payload missing:

- treat as miss;
- record safe diagnostic count;
- optionally purge metadata.

Payload present, metadata missing:

- treat as unsafe orphan;
- never return it;
- purge through scheduled cleanup.

Cache entry fresh by TTL but stale by invalidation cursor:

- treat as miss;
- increment blocked stale-hit metric;
- do not return partial cached text.

Clock skew:

- freshness uses commit position/event cursor before wall-clock when correctness matters;
- wall-clock TTL only bounds storage and latency behavior.

Cache stampede:

- single-flight recompute is allowed per cache key;
- waiting callers use timeout and fallback;
- no request gets unfiltered stale data just because recompute is expensive.

### Required Tests

Unit:

- cache key includes principal/grant/profile/policy/ontology/temporal dimensions;
- `ResolveCacheFreshnessUseCase` rejects expired, invalidated and dimension-mismatched entries;
- invalidation command is idempotent by target/reason/commit position;
- embedding cache key changes with model, provider, purpose and redaction version;
- rerank cache key changes with candidate id/version list.

Application:

- forget fact invalidates context/search/rerank caches before success response;
- update fact bypasses old context bundle and returns current fact;
- grant revoke blocks cached bundle built under older grant version;
- policy disable prevents cached context injection immediately;
- legal hold visibility change invalidates affected context/search cache;
- secret redaction invalidates embedding/vector/rerank caches using old text hash/redaction version.

Integration:

- context cache hit still reloads canonical ids and filters deleted rows;
- search cache candidate ids from stale Qdrant/Graphiti cannot return deleted text;
- Redis or in-process cache backend outage falls back without data leakage;
- expired invalidation retention fails closed and recomputes;
- concurrent cache recompute is single-flight and preserves prompt timeout.

E2E:

- build context, forget fact, then repeat same query and verify old item is absent even with cache enabled;
- build context as admin, revoke reader grant, query as reader and verify cached bundle is blocked;
- update policy to disabled while context cache exists and verify prompt-time retrieval stops immediately;
- import document, detect secret later, verify old embedding/rerank cache cannot surface secret chunk.

## Prompt-Path SLO and Degradation Model

Prompt-time memory retrieval is a live workflow dependency. Client App interviews and coding-agent sessions should not wait for slow graph search, vector search, reranking, provider calls, imports, rebuilds or maintenance work.

Core invariant:

```text
Context quality may degrade under pressure, but the prompt path must return within its deadline or fail closed to a safe fallback.
```

This model applies to:

- `/v1/context`;
- legacy `/api/v1/interview-memory/context`;
- SDK `build_context`;
- MCP context tools;
- agent prompt assembly;
- compatibility gateway context reads.

### PromptPathBudget

Request-scoped deadline and stage allocation for prompt-impacting retrieval.

Fields:

```text
id
space_id
profile_ids[]
thread_id?
client_kind: client_app_desktop | sdk | mcp | agent | server_batch
request_id
total_deadline_ms
soft_deadline_ms
hard_deadline_ms
fallback_deadline_ms
stage_budgets[]
allow_rerank: true | false
allow_graph_search: true | false
allow_vector_search: true | false
allow_cache: true | false
allow_provider_call: false
minimum_context_mode:
  no_memory
  cached_only
  canonical_facts_only
  source_chunks_only
  facts_and_chunks
created_at
expires_at
metadata
```

Rules:

- budget is resolved at the start of every prompt-impacting context request;
- deadline is propagated to adapter calls and cancellation tokens;
- `allow_provider_call=false` for v1 prompt path unless a later ADR enables tightly bounded prompt-path rerank;
- budget is policy and client aware, but Client App compatibility defaults must stay close to the current desktop timeout budget;
- hard deadline returns degraded/fallback result rather than waiting for background work;
- budget diagnostics expose stage names, timings and degradation reason, not raw memory text.

### ContextStageBudget

Per-stage budget inside a context request.

Recommended v1 desktop budget example:

```text
total_deadline_ms: 2000
auth_config_ms: 50
cache_lookup_ms: 100
graph_search_ms: 350
vector_search_ms: 350
canonical_filter_ms: 250
rerank_ms: 0 by default
pack_render_ms: 200
diagnostics_ms: 50
fallback_buffer_ms: 300
```

Server/agent clients may request larger deadlines, but stage budgets still need explicit caps.

Rules:

- graph and vector retrieval run in parallel when both are enabled;
- canonical filter and visibility proof are not optional, even under timeout;
- rerank is skipped when its budget is zero or when candidate filtering consumes too much time;
- slow stages are cancelled or ignored after their deadline;
- no stage may borrow from fallback buffer without recording degradation reason;
- timeout in one stage must not poison cache or create partial unsafe state.

### ContextDegradationDecision

Typed decision explaining how context quality degraded.

Fields:

```text
id
prompt_path_run_id
mode:
  full_context
  partial_without_graph
  partial_without_vector
  partial_without_rerank
  cached_context_only
  canonical_facts_only
  source_chunks_only
  local_fallback_only
  no_memory
reason:
  deadline_exceeded
  graph_timeout
  vector_timeout
  cache_miss
  cache_unsafe
  provider_disabled
  rerank_skipped
  maintenance_mode
  degraded_adapter
  auth_missing
  policy_disabled
  quota_exhausted
stage_results[]
safe_user_message?
created_at
metadata
```

Rules:

- degraded context is labeled in response metadata and debug-safe diagnostics;
- degraded context still follows `ReadScope`, `VisibilityPredicate`, `VisibilityProof` and cache freshness rules;
- `local_fallback_only` and `no_memory` are valid safe outcomes when memo_stack_server cannot answer in time;
- no degraded mode may return stale/deleted/forbidden data for better recall;
- clients should avoid treating degraded context as complete project memory.

### FallbackContextPlan

Defines what to return when the full retrieval pipeline cannot complete.

Fallback order for Client App-compatible prompt path:

```text
safe server cache hit
canonical high-importance facts only
recent thread/local active context
minimal local fallback context
no memory with safe status
```

Fallback order for coding-agent context:

```text
safe server cache hit
repo/project critical constraints
canonical high-importance facts
recent task/thread notes
no memory with safe status
```

Rules:

- fallback output has the same prompt-safe rendering contract as full context;
- fallback must never skip canonical status/auth/policy filtering;
- fallback can omit lower-value sources but must preserve critical constraints when available;
- fallback status is machine-readable so SDK/MCP clients can decide whether to retry, warn or continue;
- local fallback is client-owned and must be clearly distinguished from memo_stack_server context.

### Prompt Path Execution

Recommended algorithm:

```text
resolve budget and deadline
resolve principal/config/policy
build ReadScope
try safe context cache
start graph and vector candidate retrieval in parallel with stage deadlines
cancel/ignore stages that miss deadline
hydrate candidates through VisibilityPredicate
skip rerank if budget is too small or provider disabled
pack context under token budget
attach VisibilityProof and degradation decision
return before hard deadline or return fallback-safe status
```

Rules:

- background queues, imports, rebuilds, consolidation and provider jobs cannot run in the prompt path;
- prompt path can observe existing projection/cache state but cannot wait for projection catch-up;
- if all derived indexes are down, canonical facts and recent thread fallback can still be used;
- readiness/capabilities must say whether prompt-impacting retrieval is full, degraded or disabled;
- timeout/cancellation must release quota reservations and single-flight waiters safely.

### SLO Options

Option A - Hard 2 second desktop budget, configurable agent budget.

🎯 9   🛡️ 9   🧠 5
Approx changes: `500-1000` lines.

Recommended for v1. It preserves current Client App ergonomics and still lets SDK/agent clients request larger budgets explicitly.

Option B - Fully configurable deadlines per profile/client from day one.

🎯 7   🛡️ 8   🧠 7
Approx changes: `900-1700` lines.

More flexible, but riskier because bad config can make interviews hang or return too little memory.

Option C - Best-effort context without hard SLO in v1.

🎯 4   🛡️ 5   🧠 2
Approx changes: `100-300` lines.

Simple, but it punts the main user-facing failure mode. Not recommended.

### Required Tests

Unit:

- stage budget split never exceeds hard deadline;
- degradation decision is deterministic for stage timeout combinations;
- fallback plan never allows raw or hidden memory;
- provider calls are disabled on v1 prompt path by default;
- graph/vector stage cancellation does not mark adapter unhealthy by itself.

Application:

- context request returns before deadline when Graphiti sleeps;
- context request returns before deadline when Qdrant sleeps;
- rerank is skipped when budget is exhausted;
- canonical visibility proof is still required in degraded modes;
- cache unsafe result falls back to recompute or minimal context, not stale content.

Integration:

- Graphiti timeout plus Qdrant success returns partial context labeled `partial_without_graph`;
- Qdrant timeout plus Graphiti success returns partial context labeled `partial_without_vector`;
- both indexes down returns canonical facts/local fallback within budget;
- large import running does not increase prompt-path latency beyond SLO;
- maintenance/rebuild mode returns degraded status without blocking.

E2E:

- Client App compatibility route returns context or fallback-safe status within current desktop budget;
- memo_stack_server down still produces local/minimal fallback in desktop flow;
- provider circuit breaker open does not block context;
- repeated context calls during import keep p95 under configured budget on local Docker test.

## Domain Model

### Principal

Actor that calls memo_stack_server.

Examples:

- human user;
- local desktop app token;
- coding agent token;
- Slack/GitHub integration token;
- background worker service identity.

Fields:

```text
id
space_id?
external_subject
kind: user | service_token | integration | worker
display_name
created_at
updated_at
status: active | disabled | deleted
sensitivity: public | internal | confidential | secret | restricted
external_processing: allowed | blocked | redacted_only | local_only
metadata
```

Rules:

- authorization decisions use `Principal`, not raw API keys;
- service tokens must be scoped to space/profile/action;
- worker principal can process jobs but cannot bypass canonical status checks;
- audit events always include principal id when available.

### MemorySpace

Top-level tenant/project boundary.

Examples:

- `client-app`
- `review-router`
- `personal-coding-agents`
- `team-platform`

Fields:

```text
id
owner_id
name
description
home_region_id?
residency_policy_id?
created_at
updated_at
status: active | archived | deleted
settings
```

Rules:

- every operation requires `space_id`;
- cross-space search is disabled unless explicitly authorized;
- deletion of space creates tombstones and schedules deindex jobs.
- remote/team deployments must resolve a home region before accepting raw memory, backup or export artifacts.

### DeploymentRegion

Named physical/logical location for storage and processing. Local Docker can use a single synthetic region such as `local`.

Fields:

```text
id
deployment_id
code: local | us | eu | uk | custom
display_name
storage_backend
object_storage_region?
postgres_region?
qdrant_region?
graph_region?
allowed_provider_regions[]
status: active | disabled | draining
created_at
updated_at
metadata
```

Rules:

- region is deployment metadata, not an authorization bypass;
- local mode can keep one region and no cloud provider metadata;
- remote/team mode must expose safe region capabilities without leaking secrets;
- disabling a region blocks new placements but does not delete existing data.

### DataResidencyPolicy

Domain policy that decides where memory may be stored, processed, backed up, exported and synced.

Fields:

```text
id
space_id?
profile_id?
name
policy_version
home_region_id
allowed_storage_region_ids[]
allowed_processing_region_ids[]
allowed_backup_region_ids[]
allowed_export_region_ids[]
allowed_provider_region_ids[]
allow_cross_region_transfer: true | false
allow_managed_provider_processing: true | false
require_local_processing_for_sensitivity[]
require_residency_decision_audit: true | false
status: active | disabled | deleted
created_at
updated_at
metadata
```

Rules:

- policy can be deployment default, space-specific or profile-specific;
- child policy can be stricter than parent, not broader, unless admin override is audited;
- `restricted` and `secret` sensitivity default to local/private processing unless explicitly relaxed;
- backup/export/import/sync are transfer actions and must pass the same policy, not only read authorization;
- changing residency policy requires admin grant, audit and cache invalidation for affected prompts/artifacts.

### ProcessingLocationDecision

Safe audit record produced before storage, external AI, artifact, backup, export, import or sync transfer work.

Fields:

```text
id
space_id
profile_id?
principal_id?
operation_id?
purpose:
  store_raw
  embed
  classify
  rerank
  ocr
  graph_index
  vector_index
  create_backup
  restore_backup
  create_export
  import_bundle
  sync_change_set
requested_region_id?
resolved_region_id
provider?
provider_region?
sensitivity
decision: allow | require_redaction | local_only | reject | require_review
reason_codes[]
policy_version
created_at
metadata
```

Rules:

- decision contains ids, purpose, regions and safe reason codes, not raw memory text;
- external provider calls require an allow decision before quota reservation and provider invocation;
- graph/vector indexing still needs a decision because managed backends can be outside the home region;
- failed residency decision blocks prompt-impacting side effects, not only logging.

### CrossRegionTransferRequest

Explicit reviewed request for a future transfer that crosses normal residency boundaries.

Fields:

```text
id
space_id
profile_id?
requested_by_principal_id
source_region_id
target_region_id
purpose: migration | backup_restore | export | sync | provider_processing
status: proposed | approved | rejected | expired | applied | cancelled
expires_at?
approved_by?
created_at
updated_at
metadata
```

Rules:

- not required for normal local v1;
- required before a remote/team deployment moves raw source, backup artifacts or embeddings outside allowed regions;
- approval does not bypass authorization, sensitivity, legal hold, hard-delete or write admission checks.

### SpaceMember

Membership and role assignment inside a `MemorySpace`.

Fields:

```text
id
space_id
principal_id
role: owner | admin | editor | reviewer | reader | ingestor
created_at
updated_at
status
```

Rules:

- `owner/admin` can manage policies and grants;
- `editor` can remember/update/forget facts if profile grants allow;
- `reviewer` can approve/reject suggestions;
- `reader` can search/build context;
- `ingestor` can write source episodes/chunks but cannot approve long-term facts.

### ProfileGrant

Optional finer-grained access control for profiles.

Fields:

```text
id
space_id
profile_id
principal_id
actions: read | ingest | suggest | approve | write_fact | forget | admin
created_at
updated_at
status
```

Rules:

- profile grant can narrow but not exceed space membership;
- every search/context request is filtered by both membership and profile grants;
- lack of grant returns empty/unauthorized, never partial raw adapter data;
- grants are checked after Graphiti/Qdrant candidate retrieval through canonical Postgres filtering.

### Canonical Query and Repository Scope Model

Read visibility prevents unsafe DTOs. Repository scope prevents unsafe queries from happening in the first place. The platform needs both because repositories are used by user reads, writes, workers, retention, backfills, restore, export, diagnostics and projection rebuilds.

Core invariant:

```text
No repository method may read or mutate scoped memory rows without RepositoryScope or an explicit audited maintenance override.
```

This model applies to:

- facts, versions, relations and currency records;
- documents, chunks, source refs and storage artifacts;
- suggestions, write admissions, quarantined candidates and redaction artifacts;
- clusters, digests and projection state;
- retention, legal hold, restore, import/export and sync tables;
- worker scans, backfills, rebuilds and bulk admin operations.

It does not apply to bootstrap-only deployment metadata before the first space exists, but those exceptions must be listed in adapter tests.

#### RepositoryScope

Low-level scope value object passed into repository methods and bound to a transaction.

Fields:

```text
id
request_id?
operation_id?
principal_id?
worker_id?
space_id
profile_ids[]
purpose:
  read
  write
  delete
  export
  backup
  restore
  import
  sync
  migration
  retention
  projection_rebuild
  diagnostics
allowed_statuses[]
include_deleted: true | false
include_superseded: true | false
allow_cross_profile: true | false
allow_cross_space: false
source: user_request | worker_job | admin_dry_run | admin_apply | migration | bootstrap_exception
created_at
expires_at
metadata
```

Rules:

- `space_id` is mandatory after bootstrap;
- `allow_cross_space=false` in v1 except explicitly reviewed deployment-level diagnostics that return counts only;
- `profile_ids` can be empty only for space-level metadata operations that never return row content;
- scope expires to prevent async jobs from reusing stale grants or policy state forever;
- `RepositoryScope` is internal and must not be returned directly to clients.

#### ScopedRepositoryContext

Request or worker-local wrapper that carries `RepositoryScope`, transaction id and optional visibility/read proof links.

Fields:

```text
scope_id
transaction_id
unit_of_work_id
visibility_proof_id?
maintenance_override_id?
policy_versions[]
grant_versions[]
created_at
```

Rules:

- every repository port method for scoped tables accepts this context or a stricter domain-specific scope;
- `UnitOfWorkPort` binds the scope once and repositories read it from explicit context, not global mutable state;
- raw SQL helpers require the context and compile scope predicates centrally;
- repository methods cannot accept naked `space_id`/`profile_id` as a replacement for scope context in new code.

#### QueryScopeProof

Safe diagnostic proof that a repository method applied the expected scope.

Fields:

```text
id
scope_id
request_id?
operation_id?
repository_name
method_name
table_family
operation_type: select | insert | update | delete | upsert | count | bulk
space_filter_applied: true | false
profile_filter_applied: true | false
status_filter_applied: true | false
deleted_filter_applied: true | false
row_count?
predicate_hash
maintenance_override_id?
created_at
metadata
```

Rules:

- proof stores hashes, ids, counts and filter flags, not raw SQL with private values;
- user-visible reads still need `VisibilityProof`; `QueryScopeProof` is lower-level and supports diagnostics/tests;
- write/delete/bulk operations record proof when they affect scoped memory rows;
- absence of proof for guarded repository methods is a test failure.

#### MaintenanceScopeOverride

Explicit, short-lived override for broad admin/worker operations.

Fields:

```text
id
space_id?
profile_ids[]
operation_type:
  migration
  backfill
  projection_rebuild
  retention_apply
  profile_delete
  restore_apply
  export_apply
  diagnostics_count
requested_by_principal_id?
reason_code
dry_run_count
confirmation_token_hash?
status: proposed | approved | applied | rejected | expired | cancelled
expires_at
created_at
approved_by?
metadata
```

Rules:

- override is not a permission grant and does not bypass auth, legal hold, residency, tombstones or write admission;
- broad destructive operations require dry-run count and explicit confirmation before apply;
- maintenance workers use override id in their `RepositoryScope`;
- override responses are production-safe by default and should expose counts, not row content.

### Query Isolation Options

Option A - Repository scope contract plus optional RLS-ready design.

🎯 9   🛡️ 8   🧠 5
Approx changes: `500-1000` lines.

Recommended for v1. It forces scope through ports, tests unscoped queries, and keeps Postgres RLS possible for remote/team deployments without making the first local slice too heavy.

Option B - Postgres RLS from day one for all scoped tables.

🎯 7   🛡️ 10   🧠 8
Approx changes: `1200-2500` lines.

Strongest isolation, but adds migration, connection-pool, background worker and debugging complexity before the repository contracts are stable.

Option C - Rely on code review and endpoint-level visibility guards.

🎯 4   🛡️ 4   🧠 2
Approx changes: `50-150` lines.

Not acceptable for a reusable team memo stack because one repository method or maintenance job can bypass endpoint-level guardrails.

Required tests:

- repository method without `RepositoryScope` fails in unit tests;
- raw SQL helper refuses scoped table access without context;
- search/list/context/export path records both query scope proof and visibility proof;
- worker retention scan cannot see rows outside its scoped profiles;
- projection rebuild for one profile cannot enumerate another profile's chunks;
- bulk delete requires dry-run count and maintenance override;
- optional RLS smoke test denies cross-space rows when transaction setting is missing or wrong;
- connection-pool checkout resets any previous scope settings.

### Canonical Visibility and Read-Path Guard Model

Authorization answers "can this principal perform this action?". Visibility answers "which exact records may this read path return right now?". The platform needs both because memory reads are spread across search, context, list APIs, export, diagnostics, cache hits, Graphiti candidates and Qdrant candidates.

Core invariant:

```text
No user-visible read returns memory content without a ReadScope and VisibilityProof.
```

This model applies to:

- `/v1/search`;
- `/v1/context`;
- list endpoints;
- export and backup previews;
- artifact download preparation;
- connector/MCP read tools;
- admin diagnostics when debug scope can expose raw text;
- cache hits that contain ids or response-safe DTOs;
- derived graph/vector candidate hydration.

#### ReadScope

Request-scoped value object created after authentication, membership resolution and profile grant checks.

Fields:

```text
id
request_id
principal_id
space_id
profile_ids[]
allowed_actions[]
grant_versions[]
membership_version
policy_versions[]
ontology_version
temporal_mode: current | as_of | history | future_aware
as_of?
include_statuses[]
include_deleted: false
include_superseded: false
include_diagnostics: true | false
include_raw_text: true | false
max_sensitivity
code_scope?
source_app_scope?
purpose: search | context | list | export | backup_preview | diagnostics | artifact_download | sync_dry_run
created_at
expires_at
metadata
```

Rules:

- `ReadScope` is built once per request or operation step and passed explicitly into read use cases;
- `ReadScope` cannot grant actions beyond `SpaceMember` and `ProfileGrant`;
- normal context/search uses `include_deleted=false` and `include_superseded=false`;
- raw text requires explicit purpose, sensitivity allowance and debug/export grant;
- temporal history reads require explicit `temporal_mode` and are labeled in result DTOs;
- `ReadScope` is response-safe only after redacting principal details and raw policy internals.

#### VisibilityPredicate

Canonical filter generated from `ReadScope` and attached to repository/query methods.

Fields:

```text
space_id
profile_ids[]
allowed_statuses[]
excluded_statuses[]
temporal_filter
sensitivity_filter
policy_filter
legal_hold_filter
source_visibility_filter
code_scope_filter?
grant_versions[]
commit_position?
```

Rules:

- repository methods that hydrate facts, chunks, documents, digests, clusters or source refs accept a `VisibilityPredicate` or return metadata-only diagnostics;
- predicates are composed by domain/application code, not hand-built inside each endpoint;
- every derived candidate id from Graphiti/Qdrant/cache is hydrated through a predicate before text leaves the server;
- list/export/debug endpoints cannot opt out, they can only request a broader predicate with stronger grant and audit;
- predicates should be inspectable in safe diagnostics as ids, counts and filter names, not raw SQL with private values.

#### VisibilityProof

Small response-side proof that the read path applied the expected guard.

Fields:

```text
id
read_scope_id
use_case_name
predicate_hash
filtered_candidate_count
returned_count
dropped_by_status_count
dropped_by_grant_count
dropped_by_policy_count
dropped_by_sensitivity_count
dropped_by_temporal_count
dropped_by_legal_hold_count
dropped_by_code_scope_count
generated_at
metadata
```

Rules:

- internal result objects carry `VisibilityProof` before mapping to public DTOs;
- public responses expose proof only as safe diagnostics or debug metadata;
- tests can assert that a proof exists for every search/context/export/list path;
- absence of proof is a programmer error and should fail tests before release;
- proof does not reveal hidden record ids by default.

#### DeniedReadPolicy

Defines safe behavior when a principal asks for memory they cannot access.

Modes:

```text
return_empty
return_not_found
return_forbidden
return_partial_without_hidden_counts
admin_safe_diagnostics
```

Rules:

- default for search/context is empty or forbidden without revealing hidden profile ids;
- direct `GET by id` returns not found or forbidden according to endpoint policy, but never includes hidden content;
- diagnostics may show denied counts only with admin/debug grant;
- denial logs use request id, principal id, space id and safe reason code, not raw memory text;
- rate limits can tighten on repeated denied probes.

#### Guarded Read Patterns

Search/context:

```text
resolve principal
build ReadScope
retrieve derived candidates
build VisibilityPredicate
hydrate canonical records through predicate
drop blocked candidates
pack/render result
attach VisibilityProof
```

List endpoints:

```text
resolve principal
build ReadScope for list purpose
query only through predicate-aware repository method
cursor encodes no hidden ids
attach VisibilityProof or safe list diagnostics
```

Export:

```text
resolve principal with export grant
build ReadScope for export purpose
dry-run counts through predicate
apply sensitivity/export policy
write artifact with manifest and VisibilityProof summary
```

Admin diagnostics:

```text
resolve admin/maintenance grant
build diagnostics ReadScope
return safe counts by default
require explicit debug scope for raw text
audit raw debug access
```

#### Required Tests

Unit:

- `ReadScope` cannot exceed membership/grant actions;
- visibility predicate excludes deleted, superseded and disabled records by default;
- temporal history predicate requires explicit mode;
- raw text predicate requires purpose and sensitivity grant;
- `VisibilityProof` redacts hidden ids and raw text.

Application:

- every search/context/list/export use case returns or records a `VisibilityProof`;
- direct get by id cannot distinguish hidden id from missing id unless endpoint policy allows forbidden;
- export dry-run uses same visibility predicate as export apply;
- admin diagnostics without debug grant returns counts only;
- grant revoke changes read scope version and blocks old cached results.

Integration:

- Graphiti/Qdrant candidate from another profile is dropped by predicate;
- stale deleted candidate from cache is dropped and counted without exposing text;
- list pagination cannot leak hidden ids through cursor;
- export with reader token is denied, export with admin token still respects sensitivity and legal hold;
- connector/MCP read cannot exceed connector principal grants.

E2E:

- same query as two users with different profile grants returns different safe context and no hidden-count leak;
- direct request for known forbidden memory id behaves like endpoint policy says and returns no text;
- revoked grant immediately blocks context, list and export reads;
- debug diagnostics require explicit grant and produce audit event.

### MemoryProfile

Logical memory category inside a space.

Examples:

- `client_app.interview_sessions`
- `client_app.architecture`
- `project.adr`
- `project.constraints`
- `personal.preferences`
- `team.decisions`

Fields:

```text
id
space_id
name
description
retention_policy_id
memory_policy_id
default_importance
default_scope: profile | thread
created_at
updated_at
status
```

Rules:

- profile is the primary user-facing memory grouping;
- profile carries the default memory behavior through `memory_policy_id`;
- source/app/thread-specific policy overrides are allowed only if the default profile policy permits them;
- ingestion and classification must read policy before storing, indexing or promoting anything;
- Graphiti `group_id` should map to `space_id + profile_id` or a stable profile namespace;
- Qdrant payload must include `space_id`, `profile_id`, `thread_id`, `document_id`, `status`.

### MemoryThread

Conversation/session/workflow boundary.

Examples:

- one interview;
- one coding-agent session;
- one Slack thread;
- one PR review.

Fields:

```text
id
space_id
profile_id
external_ref
title
started_at
ended_at
created_at
updated_at
status
```

Rules:

- episodes attach to a thread when available;
- facts may be promoted from thread scope to profile scope;
- thread deletion can delete only thread-derived memories or keep promoted facts, depending on policy.

### MemoryEpisode

Raw event or batch of events that entered memory.

Examples:

- transcript segment;
- user prompt;
- assistant final answer;
- file import event;
- code diff context;
- meeting note.

Fields:

```text
id
space_id
profile_id
thread_id
source_type: transcript | prompt | assistant_answer | document | code | slack | github | manual
source_external_id
text
content_hash
occurred_at
ingested_at
status: active | disabled | deleted
metadata
```

Rules:

- ingestion is idempotent by `(space_id, profile_id, source_external_id)` or content hash strategy;
- raw episode text may be stored in Postgres for small payloads;
- large raw payloads go to object storage with DB metadata;
- sensitivity classification is stored with the episode and inherited by chunks/facts unless overridden by stricter policy;
- episode deletion schedules Graphiti/Qdrant deindex.

### Document

Uploaded or imported file.

Fields:

```text
id
space_id
profile_id
thread_id
filename
mime_type
size_bytes
content_hash
storage_object_id
storage_uri
sensitivity: public | internal | confidential | secret | restricted
extraction_status: pending | extracting | chunking | indexed | processed_with_errors | failed
external_processing: allowed | blocked | redacted_only | local_only
status: active | processing | processed | failed | disabled | deleted
created_at
updated_at
metadata
```

Rules:

- raw file never goes to Graphiti;
- chunks go to Qdrant;
- extracted facts and summaries can go to Graphiti;
- duplicate document import should be idempotent by `content_hash`;
- extraction status is separate from document visibility status;
- restricted/secret documents cannot leave local/private processing unless policy explicitly allows redacted output.
- `storage_uri` is internal adapter metadata; public APIs expose `storage_object_id` or artifact ids, not raw object keys.

### DocumentChunk

Searchable piece of a document or transcript.

Fields:

```text
id
space_id
profile_id
thread_id
document_id
episode_id
chunk_index
text
text_hash
token_count
char_start
char_end
sensitivity
embedding_status: pending | embedded | skipped | failed | stale
status: active | superseded | disabled | deleted
created_at
updated_at
metadata
```

Rules:

- Qdrant point id should be `DocumentChunk.id`;
- chunk payload must include canonical ids and status hint;
- search must validate final status through Postgres;
- chunk text is evidence, not a fact;
- embedding status must be explicit so retrieval can explain why a chunk is missing from vector search.

### Storage Object and Artifact Model

Object storage holds raw files, large extracted text, redacted artifacts, export bundles, import packages and backup/snapshot references. Postgres owns the lifecycle metadata. Object storage is never the source of truth by itself.

#### StorageObject

Canonical metadata for a physical blob.

Fields:

```text
id
space_id
profile_id?
owner_principal_id?
bucket_alias
object_key_hash
purpose: raw_document | extracted_text | redacted_text | export_bundle | import_bundle | backup_reference | qdrant_snapshot | graph_snapshot | temp_upload
size_bytes
content_hash
checksum_algorithm
checksum_value
mime_type?
sensitivity: public | internal | confidential | secret | restricted
encryption_key_version
status: pending_upload | uploaded | verified | quarantined | active | delete_pending | deleted | missing | corrupted
retention_until?
legal_hold_count
created_at
updated_at
metadata
```

Rules:

- raw object keys are not exposed through public APIs or normal diagnostics;
- every blob has purpose, owner scope, sensitivity and key version;
- checksum verification is required before object becomes active;
- missing/corrupted object makes dependent document/artifact degraded, not silently valid;
- hard-delete marks DB state first, then schedules object deletion and verification;
- legal hold blocks physical deletion but does not force prompt-time visibility.

#### UploadSession

Resumable upload intent before a blob is trusted.

Fields:

```text
id
space_id
profile_id?
principal_id
purpose
expected_size_bytes?
expected_content_hash?
allowed_mime_types[]
status: created | uploading | uploaded | verifying | completed | failed | expired | aborted
storage_object_id?
expires_at
created_at
updated_at
metadata
```

Rules:

- upload session is scoped by principal, space/profile and purpose;
- session expiry aborts untrusted temporary objects;
- completion verifies size, checksum, mime and quota before creating dependent document/import artifact;
- multipart upload completion is idempotent by upload session id;
- failed verification quarantines or deletes temporary object according to policy.

#### MemoryArtifact

Governed downloadable or importable artifact.

Fields:

```text
id
space_id
profile_id?
artifact_type: export_bundle | import_report | backup_manifest | diagnostic_bundle | redaction_report
storage_object_id
created_by_principal_id
sensitivity
status: preparing | available | expired | revoked | deleted | failed
expires_at
download_count
max_downloads?
key_version
access_policy_snapshot
created_at
updated_at
metadata
```

Rules:

- artifact access re-checks current authorization and artifact policy at download time;
- export artifact inherits strictest sensitivity of included records;
- revoking grant or hard-deleting included source can revoke or mark artifact stale according to policy;
- artifact URLs are short-lived and never serve as authorization;
- backup artifacts require key metadata availability before restore.

Required tests:

- completed upload with wrong checksum never creates active document;
- expired upload session cleans temporary object;
- export artifact download fails after grant revoke;
- hard-delete schedules object delete and verifies object absence or held state;
- missing storage object degrades document/artifact diagnostics without leaking raw object key.

### Backup, Restore and Disaster Recovery Model

Backup/restore is not only ops. For memory, it is part of the data lifecycle because backup artifacts can contain raw source, deleted history, embeddings, graph snapshots, audit events and key-version metadata.

Core invariant:

```text
Restore may recover available memory, but must not bypass hard-delete, legal hold, key policy, authz or canonical lifecycle.
```

V1 should support local/self-hosted backup primitives and explicit restore validation. Fully managed cloud backup automation can come later, but the contracts should not be invented outside the domain model.

#### BackupPolicy

Defines what is backed up, how long backup artifacts are kept and which restore modes are allowed.

Fields:

```text
id
space_id?
profile_id?
policy_version
scope: deployment | space | profile
backup_mode: logical_export | physical_snapshot | hybrid
schedule_kind: manual | interval | cron_like
include_postgres: true | false
include_object_storage: true | false
include_qdrant_snapshot: true | false
include_graph_snapshot: true | false
include_audit_chain: true | false
include_deleted_metadata: true | false
include_hard_deleted_content: false
retention_days
minimum_tombstone_retention_days
encryption_key_purpose
allowed_restore_modes[]
requires_restore_dry_run: true | false
status: active | paused | disabled | deleted
created_at
updated_at
metadata
```

Rules:

- backup policy is explicit in team/remote deployments before enabling large imports or auto-memory;
- `include_hard_deleted_content` is false and cannot be enabled without a separate compliance ADR;
- backup retention must be at least as long as the tombstone/sync/import replay window when restore needs deletion safety;
- object storage and database backup must share a manifest-level consistency point or be marked partial;
- derived index snapshots are optional acceleration artifacts, never canonical restore authority;
- backup policy changes require admin grant, audit and safe diagnostics.

#### BackupRun

One execution of a backup policy.

Fields:

```text
id
policy_id
space_id?
profile_id?
started_by_principal_id
status:
  queued
  running
  completed
  completed_with_warnings
  failed
  cancelled
  expired
backup_mode
consistency_mode: offline | online_watermark | logical_only
source_commit_position
source_event_cursor
started_at
completed_at?
expires_at?
artifact_id?
manifest_id?
error_code?
safe_error?
metadata
```

Rules:

- backup run records the canonical commit position and event cursor used as the consistency point;
- online backups must either capture object storage at the same watermark or record exact missing/late objects;
- cancellation leaves either no artifact or a failed artifact that cannot be restored;
- completed backup artifacts are `MemoryArtifact` records and use normal artifact authorization;
- backup run never pauses forget/delete operations unless a later ADR explicitly chooses an offline backup window.

#### BackupManifest

Machine-verifiable description of what the backup contains and how it can be restored.

Fields:

```text
id
backup_run_id
manifest_schema_version
deployment_lineage_id
source_server_version
source_contract_versions
source_schema_version
source_commit_position
source_event_cursor
created_at
postgres_dump_ref?
postgres_wal_range?
object_storage_refs[]
qdrant_snapshot_refs[]
graph_snapshot_refs[]
audit_chain_head_hash
key_versions_required[]
redaction_versions[]
policy_versions[]
ontology_versions[]
tombstone_window_start?
tombstone_window_end?
hard_delete_ledger_hash
object_inventory_hash
payload_hash
signature?
metadata
```

Rules:

- manifest is required for every restoreable backup;
- manifest contains references and hashes, not raw private text inline;
- manifest must include enough key-version metadata to prove decryptability, but never raw key material;
- hard-delete ledger hash and tombstone window are mandatory for any restore path that could expose historical data;
- audit chain head is recorded so restore can prove audit continuity or clearly label a forked chain;
- manifest schema is public-contract governed and included in compatibility fixtures.

#### RestoreRun

Governed restore attempt from a backup manifest.

Fields:

```text
id
manifest_id
target_deployment_id
target_space_id?
target_profile_id?
started_by_principal_id
restore_mode:
  dry_run
  new_space
  replace_space
  point_in_time
  disaster_recovery
status:
  planned
  validating
  blocked
  ready
  applying
  completed
  completed_with_warnings
  failed
  cancelled
source_commit_position
target_commit_position?
validation_report_id?
started_at
completed_at?
safe_error?
metadata
```

Rules:

- restore starts as dry-run by default;
- destructive `replace_space` requires explicit admin grant, recent backup evidence, audit and rollback boundary;
- restore into an existing space must check id collisions, tombstones, legal holds, policy versions and grants before applying;
- point-in-time restore must preserve or replay later hard-delete/tombstone records when policy requires deletion safety;
- restoring derived Qdrant/Graphiti snapshots is allowed only after manifest validation and canonical Postgres restore;
- restore never trusts derived index snapshots over canonical rows and tombstones.

#### RestoreValidationReport

Safe report produced before apply and after restore.

Fields:

```text
id
restore_run_id
status: passed | warning | blocked | failed
checked_at
source_counts
target_counts
missing_key_versions[]
missing_object_refs[]
corrupted_object_refs[]
schema_compatibility_status
contract_compatibility_status
policy_compatibility_status
tombstone_conflicts[]
hard_delete_conflicts[]
legal_hold_conflicts[]
audit_chain_status
derived_snapshot_status
recommended_restore_mode?
safe_summary
metadata
```

Rules:

- report is production-safe by default and uses ids/counts, not raw memory text;
- missing key versions block restore of encrypted payloads instead of returning unreadable memory;
- missing object refs make dependent documents/artifacts degraded unless strict restore mode blocks;
- hard-delete conflicts block prompt-visible restore of affected content;
- warnings are acceptable only when user explicitly chooses a degraded restore mode.

#### Restore Modes

New space restore:

- safest default for local/personal recovery;
- creates a new `MemorySpace` or profile and imports records with provenance linking to backup manifest;
- does not overwrite current memory;
- still respects hard-delete ledger and destination policy.

Replace space restore:

- high-risk admin action;
- requires dry-run, backup manifest validation, explicit confirmation and audit;
- enters read-only or maintenance mode for affected space during apply;
- keeps previous state available only through a separate backup/rollback artifact if policy allows.

Point-in-time restore:

- restores canonical records to a past commit position or WAL timestamp;
- then replays retained delete/hard-delete/legal-hold events that must remain effective;
- derived indexes are rebuilt or validated after canonical restore;
- context/search stays disabled until leakage tests pass.

Disaster recovery restore:

- used for deployment loss or corrupted primary database;
- validates deployment lineage, server version, contract versions, keys, object inventory and audit chain;
- starts in maintenance/read-only until validation passes;
- only then enables normal writes and prompt-impacting retrieval.

#### Backup Consistency Strategy

Option A - Hybrid manifest with Postgres canonical export plus object inventory.

🎯 9   🛡️ 9   🧠 6
Approx changes: `600-1200` lines.

Recommended for v1. Store canonical logical export or physical DB backup metadata, object storage inventory, optional Qdrant/Graphiti snapshots and all hashes in a signed manifest. Rebuild derived indexes if snapshots are missing or stale.

Option B - Pure logical export/import only.

🎯 7   🛡️ 8   🧠 4
Approx changes: `300-700` lines.

Simpler and portable, good for profile transfer. Weaker for disaster recovery because it may miss DB internals, audit continuity, operation ledgers and large object consistency.

Option C - Physical snapshots for every backend.

🎯 6   🛡️ 7   🧠 8
Approx changes: `1000-2200` lines plus ops.

Fast for large deployments, but risks version/provider coupling and stale derived index snapshots. It should be optional acceleration, not the first correctness path.

#### Backup and Restore Use Cases

```text
PlanBackupUseCase
  input: BackupPolicy id and scope
  output: BackupRun

CreateBackupManifestUseCase
  input: completed backup artifacts and consistency metadata
  output: BackupManifest

ValidateRestoreUseCase
  input: manifest id, target scope and restore mode
  output: RestoreValidationReport

ApplyRestoreUseCase
  input: restore run id and explicit confirmation
  output: RestoreRun

VerifyRestoredMemoryUseCase
  input: restore run id and validation suite
  output: RestoreValidationReport
```

Use case rules:

- backup and restore are public `ClientOperation` records for progress, but admin-only by default;
- backup, restore and export-like backup artifacts call `ResolveProcessingLocationUseCase` before artifact creation or restore apply;
- restore apply uses normal repository/use-case paths or migration-safe bulk paths that preserve lifecycle rules;
- all restore-generated writes carry `SourceProvenance.source_type=backup_restore`;
- restore-created records carry `restored_from_manifest_id`;
- restore validation runs before prompt-impacting retrieval is re-enabled.

#### Hard-Delete and Backup Safety

Rules:

- hard-delete creates a deletion ledger record that survives at least the maximum backup retention window as minimal metadata;
- restore checks deletion ledger before making any historical content visible;
- backup artifacts containing pre-delete content become expired, revoked, redacted or held according to policy;
- legal hold can preserve raw content, but normal retrieval remains hidden when user-visible forget requires it;
- export/import cannot be used as a backup bypass for hard-deleted content.

#### Required Tests

Unit:

- backup policy rejects `include_hard_deleted_content=true` without compliance override;
- manifest hash verification fails on modified object reference;
- restore validation blocks missing key versions;
- restore validation blocks hard-delete conflicts;
- point-in-time restore plan includes later retained tombstones.

Application:

- backup run records commit position, event cursor, key versions and object inventory hash;
- cancelled backup cannot be restored;
- restore dry-run reports object/key/audit/tombstone blockers without mutation;
- apply restore into new space preserves source refs and provenance;
- replace-space restore requires explicit admin confirmation and audit.

Integration:

- restore Postgres backup with missing Qdrant snapshot and rebuild vectors from canonical records;
- restore with object blob missing marks document degraded and excludes it from context;
- restore after hard-delete does not return deleted raw content in search/context/export;
- restore after key rotation reads old encrypted records only when decrypt-only key is available;
- audit chain verification after restore either continues chain or reports forked chain explicitly.

E2E:

- create facts/documents, backup, delete one fact, restore into new space and verify deleted fact policy behavior;
- backup before hard-delete, hard-delete source document, restore and verify source chunk is not prompt-visible;
- simulate disaster recovery from manifest and verify context stays disabled until validation passes;
- restore profile bundle and verify Client App compatibility context still maps to correct profile/thread.

### MemoryEntity

Canonical entity identity used to prevent graph/client merge mistakes from becoming durable truth.

Fields:

```text
id
space_id
profile_id
entity_key
display_name
entity_type: person | organization | project | repository | package | service | feature | concept | custom
scope:
  repo_id?
  branch?
  package_name?
  source_app?
status: active | merged | split | disabled | deleted
canonical_entity_id
confidence
created_at
updated_at
metadata
version
```

Alias fields:

```text
id
space_id
profile_id
entity_id
alias
alias_type: exact | normalized | former_name | external_id | model_candidate
source_refs
confidence
status: active | rejected | superseded | deleted
created_at
metadata
```

Rules:

- canonical entity identity lives in Postgres, not Graphiti;
- Graphiti entity ids are candidate/mapping metadata, never canonical identity;
- entity key must include enough scope to distinguish same names across projects/repos/profiles;
- low-confidence entity matches create suggestions or `needs_review`, not automatic merges;
- merge/split operations are auditable and must preserve old aliases and affected fact ids;
- deleted/disabled entities hide associated facts unless the query explicitly asks for history.

Recommended entity key shape:

```text
profile:{profile_id}:type:{entity_type}:scope:{scope_hash}:name:{normalized_name}
```

Examples:

```text
project "Memo Stack" in Client App architecture profile
package "memo_stack_core" in repo Client App
person "Alex" in team profile vs interview candidate profile
```

### MemoryFact

Canonical durable fact.

Fields:

```text
id
space_id
profile_id
thread_id
entity_id
entity_key
kind
text
status: active | superseded | disabled | deleted
confidence
importance
valid_from
invalid_at
supersedes_fact_id
created_at
updated_at
deleted_at
metadata
version
```

Rules:

- fact update creates a new version or new fact linked by `supersedes_fact_id`;
- old fact becomes `superseded`;
- delete creates tombstone;
- every fact must have at least one `SourceRef` unless it is explicitly manual and low-confidence;
- active retrieval must exclude `superseded`, `disabled`, `deleted`;
- `entity_id` is preferred when known; `entity_key` is retained for compatibility and unresolved facts;
- unresolved or ambiguous entity facts can be stored only with lower confidence or review requirement;
- facts with conflicting active siblings should be marked `needs_review` or resolved by policy.

## Fact Currency and Conflict Resolution Model

Long-term memory must answer "what is current now?" without silently deleting history. Updates, contradictions and repeated meeting notes should produce an auditable currency decision, not ad hoc text replacement.

Core invariant:

```text
Only facts with current currency and no unresolved blocking conflict are eligible for normal context.
```

This model applies to:

- explicit `update_fact`;
- imported profile/document facts;
- auto-memory suggestions;
- connector backfills;
- branch/PR promotion;
- digest refresh;
- context packing;
- export/history/debug reads.

### FactCurrencyState

Canonical state of a fact in the current-fact resolver.

Fields:

```text
id
space_id
profile_id
fact_id
entity_id?
kind
scope_hash
currency_status:
  current
  disputed
  stale
  superseded
  historical
  future
  disabled
  deleted
reason:
  explicit_update
  newer_primary_evidence
  contradiction
  source_deleted
  temporal_expired
  branch_abandoned
  policy_changed
  reviewer_decision
  import_conflict
current_fact_group_id
source_fact_ids[]
valid_from?
invalid_at?
last_confirmed_at?
last_challenged_at?
decision_id?
created_at
updated_at
metadata
```

Rules:

- `MemoryFact.status` is lifecycle state, `FactCurrencyState.currency_status` is truth/currentness state;
- normal context includes only `current` unless request explicitly asks for disputed/history;
- `disputed` facts are excluded from normal prompt constraints and can appear only as labeled evidence when useful;
- `stale` facts are downranked and labeled, not silently treated as current;
- `superseded` and `historical` facts remain available for audit/history;
- currency state changes are auditable and do not erase source refs.

### FactConflictRecord

Reviewable record for contradiction or competing current facts.

Fields:

```text
id
space_id
profile_id
entity_id?
kind
scope_hash
fact_ids[]
candidate_fact_id?
conflict_type:
  direct_contradiction
  newer_value
  temporal_overlap
  scope_overlap
  duplicate_but_different_source
  source_trust_disagreement
  import_resurrection
  branch_vs_main
severity: low | medium | high | critical
status: open | auto_resolved | needs_review | resolved | rejected | expired
resolution:
  keep_existing
  supersede_existing
  keep_both_scoped
  mark_disputed
  mark_historical
  reject_candidate
  split_entity
  require_human_review
created_by
resolved_by?
created_at
resolved_at?
safe_summary
metadata
```

Rules:

- conflict records are safe diagnostics by default and do not include long raw text;
- unresolved high/critical conflicts block auto-promotion and normal constraint injection;
- conflicting branch/PR facts can coexist only with strict scope labels;
- entity ambiguity can convert conflict resolution into entity split/merge review;
- conflict expiration cannot promote a candidate silently.

### SupersessionDecision

Explicit decision that one fact replaces, narrows or invalidates another.

Fields:

```text
id
space_id
profile_id
old_fact_id
new_fact_id
decision_type:
  replace
  narrow_scope
  temporal_end
  mark_historical
  disable_old
  reject_new
  keep_both
decision_status: proposed | applied | rejected | rolled_back
evidence_grade
source_trust_delta
temporal_confidence
review_required: true | false
reviewed_by?
created_at
applied_at?
safe_reason
metadata
```

Rules:

- supersession sets `invalid_at` or status/currency state deliberately;
- auto-supersession requires stronger or newer evidence, compatible scope, entity confidence and no legal/policy blocker;
- weak newer evidence creates review suggestion instead of replacing a strong older fact;
- rollback creates a compensating decision and currency update, not a silent database revert;
- decisions are included in audit and source-ref diagnostics.

### CurrentFactSet

Derived read model for one entity/kind/scope that context packing can use.

Fields:

```text
id
space_id
profile_id
entity_id?
kind
scope_hash
current_fact_ids[]
disputed_fact_ids[]
historical_fact_ids[]
blocked_fact_ids[]
resolver_version
computed_at
source_commit_position
metadata
```

Rules:

- `CurrentFactSet` is derived and can be recomputed from canonical facts, conflicts and supersession decisions;
- context builder uses it as a convenience, but still canonical-filters every fact;
- multiple current facts are allowed only when scope or kind permits non-exclusive facts;
- exclusive kinds, such as "current framework choice", should have at most one current fact per scope unless disputed;
- resolver version changes can mark affected sets stale and schedule recompute.

### Conflict Detection Inputs

Signals:

- same entity/kind/scope but different normalized value;
- new primary source contradicts active fact;
- branch/PR note contradicts mainline decision;
- source timestamp says old fact stopped being valid;
- document import reintroduces tombstoned or disabled fact;
- reviewer rejects a suggestion that duplicates an active fact;
- code reference status becomes stale/deleted;
- repeated user correction says "actually/no longer/not anymore".

Rules:

- direct user correction can supersede faster than model-extracted evidence;
- assistant-generated text can propose conflict, but cannot resolve it as primary evidence by default;
- import/backfill conflict detection must be idempotent;
- detection can be async, but normal context must not include facts already known as disputed/high-risk.

### Currency Resolution Policy

Option A - Conservative review-gated conflict resolution.

🎯 9   🛡️ 10   🧠 6
Approx changes: `600-1200` lines.

Recommended for v1. Auto-resolve only clear, low-risk cases. Put most contradictions and high-impact replacements into review or suggestions.

Option B - Policy-driven auto-supersede for trusted sources.

🎯 8   🛡️ 8   🧠 7
Approx changes: `1000-1800` lines.

Useful later for ADR/main-branch docs or explicit user corrections. Needs stronger evals and rollback UX.

Option C - LLM decides current fact.

🎯 4   🛡️ 4   🧠 5
Approx changes: `500-1200` lines.

Not recommended. It will look smart in demos but is hard to audit and can silently replace correct memory.

### Required Tests

Unit:

- old fact becomes historical/superseded only through `SupersessionDecision`;
- conflict detection creates stable idempotent `FactConflictRecord`;
- current-fact resolver excludes disputed and stale facts from normal current set;
- weak derived evidence cannot supersede strong primary evidence;
- scoped branch fact does not supersede global fact without promotion evidence.

Application:

- explicit user correction proposes or applies supersession according to policy;
- import conflicting document creates conflict record instead of overwriting active fact;
- reviewer resolution updates currency state and audit;
- context builder excludes unresolved critical disputed facts;
- export/history can include disputed/superseded facts with labels.

Integration:

- Graphiti/Qdrant returns old fact, current resolver drops it from normal context;
- connector backfill with old value creates historical/disputed state, not active replacement;
- branch abandoned marks branch-scoped current facts stale outside branch context;
- digest refresh sees disputed sources and does not hide contradiction.

E2E:

- store architecture decision, store later explicit correction, verify old decision is not injected as current;
- import older document after newer manual fact, verify older fact becomes historical or disputed;
- ask history query and verify superseded fact appears with label;
- ask normal context and verify disputed conflict is not rendered as a current constraint.

### SourceRef

Evidence pointer.

Fields:

```text
id
space_id
profile_id
fact_id
episode_id
document_id
chunk_id
source_kind
quote
char_start
char_end
created_at
metadata
```

Rules:

- quote should be short and bounded;
- source ref must be resolvable through API;
- source ref can point to raw episode, document chunk, external URL, commit, PR, Slack message.

## Temporal Memory Semantics

Temporal behavior must be explicit because meetings/interviews/projects produce facts that become stale.

Time fields:

```text
observed_at:
  when the source claimed or showed the fact

valid_from:
  when the fact starts being true in the domain

invalid_at:
  when the fact stopped being true in the domain

last_seen_at:
  last primary evidence that confirmed the fact

ingested_at:
  when memo_stack_server stored the record

created_at/updated_at:
  database lifecycle timestamps
```

Rules:

- `ingested_at` is transaction time, not truth time;
- source-provided timestamps are evidence and may be wrong, so parser confidence matters;
- retrieval defaults to current facts: `valid_from <= now` and `invalid_at is null`, unless query requests history;
- future-dated facts are excluded from normal context unless explicitly relevant;
- expired facts can appear in history/debug/search with `historical` label, not in active context;
- update/supersede must set temporal relation, not only mutate text;
- Graphiti `reference_time` should use `observed_at` when trustworthy, otherwise `ingested_at` with low temporal confidence.

API implications:

```text
POST /v1/search:
  as_of?
  include_historical?
  temporal_mode: current | as_of | history | all

POST /v1/context:
  as_of?
  include_historical: false by default
```

Required tests:

- current search excludes invalidated facts;
- `as_of` search can retrieve facts active at that time;
- future-dated fact is not injected into normal context;
- source timestamp conflict creates lower temporal confidence or review;
- supersede creates correct `invalid_at`/`valid_from` relation.

## Evidence and Confidence Model

Confidence is not a generic float from an LLM. It is a policy-controlled score derived from evidence quality.

Evidence grades:

```text
primary:
  explicit user fact, repo doc, ADR, source document, commit, issue, PR

secondary:
  transcript, meeting note, Slack discussion, summarized source with refs

derived:
  assistant answer, generated summary, model-extracted paraphrase

untrusted:
  pasted unknown text, malicious document section, source without provenance
```

Confidence inputs:

```text
source_trust
source_count
source_independence
extraction_confidence
entity_resolution_confidence
temporal_confidence
conflict_status
review_status
policy_mode
```

Rules:

- repeated derived evidence does not increase confidence without new primary/secondary source refs;
- confidence can be raised automatically only by independent trusted evidence or human review;
- confidence can be lowered automatically by contradiction, stale source, deleted source or unresolved entity;
- auto-promotion requires confidence, source trust, entity confidence, temporal confidence and no unresolved conflict;
- manual facts may start high confidence only when the principal is trusted for that profile;
- classifier prompt/model version is stored with candidate facts to explain confidence changes later.

Recommended confidence bands:

```text
0.00-0.39:
  do not store as fact, maybe source chunk only

0.40-0.69:
  suggestion/review only

0.70-0.89:
  eligible for auto_safe only if source trust and policy allow

0.90-1.00:
  explicit trusted source or reviewed fact
```

Required tests:

- two assistant summaries do not auto-promote a fact;
- primary source plus matching transcript can raise confidence;
- unresolved entity blocks auto_safe promotion;
- deleted source lowers or disables derived facts;
- conflict creates suggestion/review instead of silent overwrite.

### SourceProvenance

Structured origin metadata for every imported event/fact/chunk.

Fields:

```text
source_app: client-app | codex | claude | cursor | slack | github | manual | api
source_connector_id
source_external_id
source_url
repo_id
branch
commit_sha
pull_request_id
slack_team_id
slack_channel_id
slack_thread_ts
actor_external_id
trust_level: highest | high | medium | low | untrusted
captured_at
metadata
```

Rules:

- provenance is required for connector writes;
- `source_external_id` is namespaced by `source_app` and connector id;
- assistant/generated text is low trust unless backed by primary source refs;
- coding-agent memories should include repo/branch/commit when available;
- provenance is used for idempotency, source trust, audit and debugging.

## Memory Write Trust and Poisoning Defense Model

Read-path guards prevent unsafe memory from being returned. Write-path trust prevents unsafe memory from becoming durable truth in the first place. This matters for coding agents because a malicious document, issue, Slack message, repo file or assistant answer can try to plant long-term instructions.

Core invariant:

```text
Untrusted or instruction-like input can become source evidence, but cannot become active long-term memory without admission, policy and review gates.
```

This model applies to:

- explicit fact writes;
- document imports;
- transcript ingestion;
- connector webhooks/backfills;
- MCP writes;
- classifier candidates;
- assistant-derived suggestions;
- import/restore-created records.

### WriteIntent

Normalized intent before any canonical fact/suggestion/chunk becomes trusted memory.

Fields:

```text
id
space_id
profile_id
principal_id
connector_id?
source_provenance_id?
source_type
write_kind:
  explicit_fact
  source_chunk
  extracted_fact
  suggestion
  correction
  import_item
  connector_event
  restore_item
target_kind?
raw_text_hash
redacted_text_ref?
source_refs[]
code_scope?
declared_sensitivity?
declared_importance?
requested_policy_mode?
idempotency_key?
created_at
metadata
```

Rules:

- write intent is created before fact/suggestion/document chunk materialization;
- raw text can be stored only according to sensitivity and object storage policy;
- provenance-less connector/API writes are rejected or quarantined;
- assistant output defaults to derived low-trust write intent;
- restore/import intents carry source manifest or bundle provenance.

### MemoryWriteAdmission

Decision record produced before creating active memory.

Fields:

```text
id
write_intent_id
space_id
profile_id
decision:
  allow_active
  allow_source_only
  create_suggestion
  require_review
  quarantine
  reject
reason_codes[]
trust_level
sensitivity
policy_version
admission_version
poisoning_signal_ids[]
review_required: true | false
safe_summary
created_at
metadata
```

Rules:

- `allow_active` requires policy allow, trusted provenance, source refs, no blocking poisoning signal and no unresolved high-risk conflict;
- `allow_source_only` can store searchable source chunks without promoting facts;
- `create_suggestion` is the default for medium/low trust extracted facts;
- `quarantine` prevents prompt-time visibility and derived indexing until reviewed or discarded;
- `reject` records safe diagnostics and optional audit, not raw rejected text;
- admission decisions are idempotent by write intent fingerprint.

### PoisoningSignal

Structured signal that input may be malicious, instruction-like or unsafe as memory.

Fields:

```text
id
write_intent_id
space_id
profile_id
signal_type:
  prompt_injection
  tool_instruction
  credential_or_secret
  provenance_missing
  connector_scope_mismatch
  self_approval_attempt
  source_impersonation
  hidden_instruction
  policy_bypass_request
  impossible_claim
  hostile_archive
  external_link_fetch_attempt
severity: low | medium | high | critical
detector: deterministic | classifier | reviewer | adapter
detector_version
safe_evidence
created_at
metadata
```

Rules:

- high/critical signals block active fact creation by default;
- deterministic detectors run before LLM/classifier extraction when possible;
- classifier can add signals but cannot downgrade deterministic critical signals;
- signals are safe diagnostics and should not store full malicious payload;
- repeated signals can tighten connector/profile policy.

### QuarantinedMemoryCandidate

Candidate held outside normal memory until reviewed or discarded.

Fields:

```text
id
write_intent_id
admission_id
space_id
profile_id
status: quarantined | released_as_source | released_as_suggestion | rejected | expired
reason_codes[]
expires_at?
reviewed_by?
reviewed_at?
created_at
metadata
```

Rules:

- quarantined candidates never appear in search/context/export as normal memory;
- reviewer can release as source-only or suggestion, not necessarily active fact;
- expiry rejects or archives candidate according to policy;
- release action creates audit and re-runs current policy checks.

### Write Admission Algorithm

```text
create WriteIntent
verify principal, connector and profile grant
validate SourceProvenance
detect sensitivity and secrets
run deterministic poisoning detectors
apply MemoryPolicy and source trust rules
detect obvious conflicts/currentness blockers
produce MemoryWriteAdmission
materialize active fact, suggestion, source-only chunk, quarantine or rejection
record safe audit and diagnostics
```

Rules:

- write admission runs before Graphiti/Qdrant indexing and before auto-promotion;
- write admission cannot be bypassed by import, restore, connector or MCP paths;
- agent-origin writes cannot approve themselves unless explicit policy allows and a separate reviewer principal is present;
- instruction-like text can be stored as quoted source evidence but never as `is_instruction=true`;
- low-trust writes can improve recall as source chunks while staying blocked from current constraints.

### Poisoning Defense Options

Option A - Deterministic detectors plus review-gated classifier signals.

🎯 9   🛡️ 9   🧠 6
Approx changes: `600-1200` lines.

Recommended for v1. Deterministic rules catch obvious prompt injection, secrets and missing provenance. Classifier signals can suggest review but do not directly allow active memory.

Option B - LLM-based poisoning classifier from day one.

🎯 6   🛡️ 6   🧠 7
Approx changes: `900-1800` lines.

Better coverage on subtle attacks, but adds cost, privacy and prompt/schema drift risk.

Option C - Trust policy only, no poisoning detectors.

🎯 5   🛡️ 5   🧠 3
Approx changes: `200-500` lines.

Too weak for agent/team memory because hostile content can enter through trusted connectors or docs.

### Required Tests

Unit:

- provenance-less connector write is rejected or quarantined;
- assistant output becomes low-trust suggestion/source-only unless backed by primary source refs;
- prompt-injection text triggers `PoisoningSignal` and cannot become active fact;
- critical deterministic signal cannot be downgraded by classifier;
- quarantine release re-runs policy and records audit.

Application:

- document with "ignore previous instructions" stores source chunk but no active instruction-like fact;
- MCP write from agent cannot self-approve generated suggestion;
- Slack/GitHub connector outside allowed profile is rejected before materialization;
- import bundle with suspicious source creates quarantined candidate;
- explicit trusted manual correction can pass admission and proceed to fact currency resolver.

Integration:

- Graphiti/Qdrant receive no active projection for quarantined candidates;
- quarantined candidates are absent from normal search/context/export;
- poisoning diagnostics expose counts and safe reasons, not raw malicious payload;
- repeated poisoning signals can pause or degrade connector according to policy.

E2E:

- import malicious markdown and verify no prompt instruction appears in context;
- compromised connector attempts to write global constraint and is quarantined/rejected;
- agent writes a memory that instructs future agents to bypass policy and it remains source-only or rejected;
- reviewer releases a quarantined candidate as suggestion and it still requires normal approval.

## Coding Agent Memory Semantics

Coding-agent memory needs stronger scope than generic notes. A fact can be true for one repository, branch, package or PR and false elsewhere.

### CodeRepository

Canonical repository/workspace identity.

Fields:

```text
id
space_id
provider: local | github | gitlab | bitbucket | manual
repo_key
remote_url_hash
default_branch
monorepo_root?
status: active | archived | deleted
created_at
updated_at
metadata
```

Rules:

- `repo_key` is canonical inside a space and should not depend on local absolute path;
- local path is client metadata, not canonical identity;
- remote URL is stored as normalized hash plus safe display label;
- archived repository facts can be searched by history/debug but are downranked in active context.

### CodeScope

Value object attached to facts, chunks, entities and queries.

Fields:

```text
repo_id?
branch?
commit_sha?
pull_request_id?
package_name?
module_path?
file_path_glob?
environment: local | test | staging | production | unknown
worktree_state: clean | dirty | unknown
scope_level: global | repo | branch | pr | commit | file | symbol
```

Rules:

- global/project facts require explicit promotion or trusted source such as ADR/main branch docs;
- branch/PR facts are not global constraints until merged/promoted;
- dirty worktree facts are low-trust and thread-local by default;
- retrieval prefers exact repo/branch/PR match, then repo/global, then space-level general memory;
- branch-local rejected approaches should not block unrelated branches unless promoted.

### CodeReference

Durable pointer to code evidence.

Fields:

```text
id
space_id
profile_id
source_ref_id
repo_id
commit_sha?
branch?
file_path
symbol_name?
symbol_kind?
line_start?
line_end?
content_hash?
language?
status: current | moved | stale | deleted | unknown
created_at
updated_at
metadata
```

Rules:

- commit sha plus content hash is preferred for durable evidence;
- branch-only references are accepted but less stable;
- line ranges are hints and must degrade to file/symbol/content search when they drift;
- file rename or symbol move updates `status`/metadata instead of silently changing evidence;
- code snippets are evidence, not instructions;
- generated code references should be marked if source generator is known.

Branch/PR promotion:

```text
branch/pr memory -> review/merge event -> promote to repo/global or mark stale
abandoned branch/pr -> expire/downrank branch-local facts
main branch ADR/doc -> eligible for high-trust repo/global fact
```

Required tests:

- branch-local decision is not returned for another branch by default;
- merged PR decision can be promoted to repo-level with audit;
- abandoned branch facts become stale/downranked;
- file rename preserves evidence through resolver or marks code ref stale;
- dirty worktree notes do not become team/global memory without explicit approval.

### ConnectorInstallation

Registered integration instance for an app/agent.

Fields:

```text
id
space_id
principal_id
source_app: client-app | codex | claude | cursor | slack | github | manual | api | mcp
display_name
status: active | paused | degraded | revoked | deleted
allowed_profiles
allowed_actions
default_policy_id
trusted_source_types
webhook_secret_version?
connector_version
created_at
updated_at
last_seen_at
metadata
```

Rules:

- connector installation is the lifecycle owner for connector tokens, webhook secrets and sync state;
- pausing a connector blocks new writes but keeps read/debug/admin visibility according to grants;
- revoking a connector invalidates tokens/webhook secrets immediately without deleting provenance history;
- connector version is stored to explain parsing/provenance changes later;
- every connector write must include `connector_id` and `source_external_id` or an explicit manual idempotency key.

### ConnectorSyncState

Tracks backfill, polling, webhook and replay progress per connector/source stream.

Fields:

```text
id
space_id
connector_id
source_stream
external_cursor
last_external_sequence
last_event_at
backfill_status: not_started | running | paused | completed | failed
replay_window_started_at
checkpoint_version
error_count
last_safe_error
updated_at
metadata
```

Rules:

- connector backfill is idempotent by source external ids and sequence/cursor metadata;
- stale backfill events must re-check tombstones and current policy before writing;
- external delete/update events become canonical update/delete requests, not direct derived-index mutations;
- sync state is production-safe and should not store raw source content;
- backfill can be paused/resumed without losing processed checkpoint.

### EventSubscription

Optional client-facing event delivery contract for SDKs, MCP servers and connectors.

Fields:

```text
id
space_id
principal_id
target_type: webhook | polling | local_sdk
target_url?
event_types[]
profile_filters[]
status: active | paused | failed | revoked
delivery_secret_version?
last_delivered_cursor
created_at
updated_at
metadata
```

Rules:

- event payloads are production-safe by default and contain ids/status/version, not raw memory text;
- clients must treat events as cache invalidation and refetch through authorized APIs;
- delivery is at-least-once, so clients must dedupe by event id/cursor;
- failed webhook delivery uses backoff and dead-letter diagnostics;
- subscriptions cannot grant access beyond principal/profile grants.

### Sync Readiness Model

V1 is sync-ready, not sync-complete. These contracts exist so local Docker, remote server and future SaaS sync can share the same domain language later.

Sync exchange must stay disabled unless `/v1/capabilities` exposes `supports_sync_exchange=true`.

#### SyncPeer

Registered local or remote participant in a future sync topology.

Fields:

```text
id
space_id
principal_id
peer_type: local_docker | desktop_app | remote_server | managed_cloud | import_bundle
display_name
trust_tier: owner_device | team_server | imported_bundle | untrusted_external
status: active | paused | revoked | deleted
client_version
api_version
schema_version
last_seen_at
created_at
updated_at
metadata
```

Rules:

- sync peer is an identity boundary, not an authorization bypass;
- every sync request still resolves a principal and profile grants through `AuthorizationPort`;
- revoked peers cannot pull or push changes, but their historical provenance remains auditable;
- peer trust tier participates in conflict scoring but never overrides explicit legal hold, tombstone or policy rules.

#### SyncCheckpoint

Per-peer progress record for canonical event exchange.

Fields:

```text
id
space_id
peer_id
direction: pull | push
last_sent_cursor
last_ack_cursor
last_received_cursor
last_applied_cursor
schema_version
status: active | paused | conflict_blocked | failed | revoked
error_count
last_safe_error
updated_at
metadata
```

Rules:

- cursors are opaque and scoped to `space_id` plus `peer_id`;
- checkpoint updates are idempotent and monotonic;
- a peer cannot acknowledge a cursor it was not sent;
- cursor expiry returns a typed conflict that requires full dry-run resync or export/import, not silent reset;
- checkpoints store ids and cursors only, not raw memory text.

#### SyncChangeSet

Portable batch of canonical changes, never Graphiti/Qdrant objects.

Fields:

```text
id
space_id
peer_id
base_cursor
target_cursor
change_count
operation_kinds[]
schema_version
ontology_version
policy_version
tombstone_window_until
status: prepared | dry_run | applied | rejected | expired
created_at
expires_at
metadata
```

Rules:

- change sets include canonical aggregate ids, versions, status, source refs and tombstones;
- large raw documents move through export/object storage references, not inline sync payloads;
- derived index ids are excluded;
- dry-run must report conflicts, missing profiles, stricter destination policy and legal hold blockers;
- apply is idempotent by change set id and aggregate version.

#### SyncConflict

Durable conflict record created by import/sync dry-run or future push apply.

Fields:

```text
id
space_id
profile_id?
aggregate_type
aggregate_id
local_version
incoming_version
local_origin_peer_id?
incoming_peer_id
conflict_type: version | delete_update | policy | ontology | legal_hold | permission | duplicate_identity
resolution_status: open | auto_resolved | needs_review | resolved | rejected
recommended_action: keep_local | apply_incoming | create_suggestion | fork_profile | block
safe_summary
created_at
resolved_at?
resolved_by?
metadata
```

Rules:

- unresolved conflicts cannot mutate active facts silently;
- delete/tombstone wins over generated updates unless an explicit admin restore is approved;
- manual user updates outrank classifier-generated updates when source trust is otherwise equal;
- destination stricter policy wins for export, external AI and retention behavior;
- conflict records are safe to show in diagnostics without raw private text.

### MemoryOntology

Governed vocabulary for memory kinds, relation types and source types.

Core memory kinds:

```text
architecture_decision
architecture_constraint
rejected_approach
implementation_note
bug_context
task
preference
meeting_summary
interview_context
code_pattern
api_contract
security_policy
operational_runbook
```

Core relation types:

```text
supersedes
contradicts
supports
depends_on
blocks
mentions
derived_from
alias_of
renamed_to
evidence_for
```

Core source types:

```text
manual
prompt
transcript
assistant_answer
document
code
git_commit
github_issue
github_pr
slack_message
meeting_note
api_import
```

Rules:

- unknown kind/source/relation values are accepted only as extension values with namespace, for example `custom.vendor.kind`;
- core retrieval and auto-memory policies use governed kinds, not free-form strings;
- ontology changes require ADR if they affect ranking, policy or auto-promotion;
- clients should display unknown kinds safely and avoid writing unknown core values;
- aliases map old kind names to current canonical names during migration.

### MemoryTombstone

Canonical forget/delete marker.

Fields:

```text
id
space_id
profile_id
target_type: fact | episode | document | chunk | profile | thread
target_id
reason
created_by
created_at
metadata
```

Rules:

- tombstone is append-only;
- deletion jobs use tombstones to deindex;
- search filters tombstones even if derived indexes still contain stale points.

### MemoryPolicy

First-class behavior contract for how memory is stored, classified, promoted, retained and externalized.

Fields:

```text
id
space_id
profile_id
name
scope_type: profile | thread | source_app | source_type | kind
scope_id
parent_policy_id
priority
mode: disabled | shadow | manual_only | explicit_only | suggestions | auto_safe | auto_aggressive
allowed_source_types
blocked_source_types
auto_promote_kinds
review_required_kinds
min_confidence_to_suggest
min_confidence_to_auto_promote
min_importance_to_store
allow_consolidation
allowed_consolidation_modes
min_cluster_cohesion_to_use
digest_refresh_after_days
require_source_refs
allow_assistant_answer_as_source
allow_external_processing
allowed_ai_purposes
allowed_ai_providers
allowed_ai_models
require_redaction_for_external
residency_policy_id?
allowed_processing_region_ids?
allowed_storage_region_ids?
allowed_backup_region_ids?
allowed_export_region_ids?
max_ai_tokens_per_day
secret_handling: block | redact | allow_local_only
retention_rule_id
created_at
updated_at
version
```

Rules:

- policy is evaluated before classifier promotion and before any external AI/embedding call;
- effective policy is resolved by profile default plus allowed overrides, ordered by priority and specificity;
- `disabled` rejects memory writes except minimal audit if configured;
- `shadow` ingests/classifies for diagnostics but does not affect retrieval/context;
- `manual_only` stores only explicit API/user-created facts;
- `explicit_only` stores explicit facts and explicit source chunks, but does not extract automatic facts;
- `suggestions` stores classifier candidates as inactive `MemorySuggestion` rows;
- `auto_safe` promotes only high-confidence allowed kinds with source refs, no conflict and no sensitive-source violation;
- `auto_aggressive` can promote more categories, but still blocks secrets, prompt injection, profile leakage and unresolved conflicts;
- consolidation is allowed only for configured modes and must preserve source refs;
- assistant answers are derived evidence, not primary source evidence by default;
- external AI permission is evaluated by purpose, provider, model, sensitivity and quota;
- residency permission is evaluated by purpose, sensitivity, provider region, storage region and artifact transfer kind;
- provider/model allowlists are inherited from parent policies but can only become stricter in child scopes;
- policy version must be recorded in async classification/promotion payloads.

Recommended v1 default:

```text
mode: suggestions
explicit user facts: create active MemoryFact immediately
classifier candidates: create MemorySuggestion
auto-promote: disabled by default except narrow allowlist if profile opts in
```

### MemorySuggestion

Inactive candidate fact produced by classifier or import pipeline.

Fields:

```text
id
space_id
profile_id
thread_id
candidate_text
kind
status: pending | approved | rejected | superseded | expired | auto_promoted
confidence
importance
source_refs
conflict_fact_ids
policy_snapshot
created_at
expires_at
reviewed_at
reviewed_by
metadata
```

Rules:

- suggestion is not returned as active memory unless request explicitly asks for suggestions;
- approval creates an active `MemoryFact` with source refs and audit event;
- rejection keeps audit but does not index into Graphiti/Qdrant as a fact;
- expiration hides stale candidates from normal review queues;
- superseded suggestion links to the accepted fact or newer suggestion.

### Memory Consolidation Model

Consolidation keeps long-term memory useful after many chats, meetings, imports and agent runs. It is a quality layer over canonical memory, not a separate truth store.

#### MemoryCluster

Canonical grouping of related memory items for dedupe, recurring themes and compact retrieval.

Fields:

```text
id
space_id
profile_id
cluster_key
cluster_type: duplicate_fact | recurring_preference | recurring_decision | topic | source_group | code_decision
status: proposed | active | split | merged | archived | deleted
member_fact_ids[]
member_suggestion_ids[]
member_document_chunk_ids[]
member_digest_ids[]
representative_fact_id?
confidence
cohesion_score
created_by_job_id?
created_at
updated_at
last_reviewed_at?
metadata
```

Rules:

- cluster membership is metadata and cannot make a deleted/disabled fact visible;
- `representative_fact_id` must point to an active canonical fact or be null;
- low-cohesion clusters stay `proposed` and require review before they affect context packing;
- cross-profile clusters are blocked in v1 unless a future space-level entity registry and grants allow it;
- split/merge operations are audited and must preserve old cluster ids for traceability.

#### MemoryDigest

Derived summary over a bounded source set.

Fields:

```text
id
space_id
profile_id
cluster_id?
digest_text
digest_type: topic_summary | meeting_rollup | decision_rollup | preference_rollup | code_context_rollup
status: active | stale | superseded | disabled | deleted
source_ref_ids[]
source_fact_ids[]
source_chunk_ids[]
coverage_start?
coverage_end?
prompt_template_version?
model_id?
redaction_version?
confidence
source_coverage_score
created_at
updated_at
invalidated_at?
metadata
```

Rules:

- digest is derived evidence, never primary evidence;
- digest can help ranking/context packing only together with source refs or canonical facts;
- deleting or hard-deleting any required source marks the digest stale or deleted;
- digest text cannot raise fact confidence unless a reviewer explicitly materializes a fact with source refs;
- digest generation follows `MemoryPolicy`, sensitivity, redaction and AI provider governance.

#### ConsolidationJob

Background quality job that deduplicates, clusters, refreshes stale digests and proposes merges.

Fields:

```text
id
space_id
profile_id?
mode: dedupe | cluster | digest | refresh_digest | split_cluster | merge_cluster | stale_review
status: pending | running | dry_run_ready | completed | failed | cancelled | blocked
target_scope
candidate_counts
false_merge_guardrail_score
created_at
started_at?
completed_at?
last_safe_error?
metadata
```

Rules:

- consolidation never runs synchronously in the prompt path;
- destructive consolidation, such as merging facts or deleting duplicate suggestions, requires dry-run or review;
- jobs re-check canonical status, policy and legal holds before materializing changes;
- recurring digests are invalidated by source delete/update, ontology changes, policy changes or redaction changes;
- consolidation output must be explainable by source refs and cluster membership.

Required tests:

- duplicate explicit facts become a proposed cluster, not an automatic destructive merge;
- digest becomes stale after source delete/update;
- digest cannot become primary evidence or raise confidence by repetition;
- low-cohesion cluster is excluded from context packing;
- consolidation job retry is idempotent.

### Usage and Quota Governance Model

Usage governance protects local and team deployments from runaway cost, large imports, agent loops and noisy neighbors. It is part of domain policy, not only infra rate limiting.

#### UsageRecord

Append-only accounting event for cost, storage and workload consumption.

Fields:

```text
id
space_id
profile_id?
principal_id?
connector_id?
reservation_id?
workload_class: interactive_context | ingest_hot_path | background_indexing | background_ai | background_quality | maintenance | sync
resource_type: api_request | document_bytes | extracted_chars | chunk_count | embedding_tokens | llm_tokens | vector_points | graph_edges | storage_bytes | worker_seconds | export_bytes
quantity
unit
provider?
model_id?
purpose?
occurred_at
idempotency_key
metadata
```

Rules:

- usage records are append-only and production-safe;
- provider/model/purpose metadata is stored without prompts or raw memory text;
- retries use the same idempotency key when they represent the same logical side effect;
- usage can be estimated before work and corrected after actual provider/storage response.

#### QuotaRule

Policy-owned limit for a scope and resource type.

Fields:

```text
id
space_id
profile_id?
principal_id?
connector_id?
scope_type: space | profile | principal | connector | workload_class | provider | purpose
resource_type
period: minute | hour | day | month | total | concurrent
limit
soft_limit?
hard_limit
action: allow | throttle | queue_later | store_without_ai | source_chunk_only | reject
priority
created_at
updated_at
version
metadata
```

Rules:

- most specific quota rule wins, then stricter hard limit wins;
- interactive context has reserved capacity and cannot be consumed by background jobs;
- local mode can default to generous storage limits but conservative external AI limits;
- remote/team mode must configure explicit limits before enabling auto-memory or large imports.

#### QuotaReservation

Short-lived claim for expensive work before the work starts.

Fields:

```text
id
space_id
profile_id?
principal_id?
connector_id?
workload_class
resource_type
estimated_quantity
actual_quantity?
status: reserved | committed | released | expired | rejected
idempotency_key
expires_at
created_at
updated_at
metadata
```

Rules:

- reservation is idempotent by logical work id;
- expired reservation releases capacity and does not block future work;
- actual usage can be lower or higher than estimate, but overage creates audit/diagnostics;
- delete/forget/export/status operations bypass normal AI quota but still record usage.

#### AdmissionDecision

Result of checking policy, quota, workload priority and system health before expensive work.

Fields:

```text
decision: allow | throttle | queue_later | degrade | reject
reason_code
safe_message
reservation_id?
retry_after?
degraded_mode?: no_ai | source_chunk_only | metadata_only | cached_context_only
matched_quota_rule_ids[]
workload_class
priority
```

Rules:

- API returns typed `memory.quota_exceeded` only for hard rejections;
- `queue_later` and degraded modes return accepted job/status when policy allows;
- decisions are production-safe and must not expose private text;
- admission control is checked before provider calls, large extraction, indexing, sync apply and consolidation.

Required tests:

- reservation commit/release/expiry lifecycle is idempotent;
- background AI cannot consume reserved interactive context capacity;
- one connector hitting quota does not block another connector with remaining quota;
- quota exhaustion can store source chunk without AI when policy allows;
- delete/forget remains available while embedding/LLM quota is exhausted.

### Derived Index Projection Model

Graphiti and Qdrant are derived indexes, but their operational state is canonical metadata in Postgres. This keeps drift, rebuild and deindex behavior observable.

#### ProjectionState

Per aggregate/adaptor indexing status.

Fields:

```text
id
space_id
profile_id?
aggregate_type: episode | fact | document | chunk | entity | digest | cluster
aggregate_id
aggregate_version
projection_type: graph | vector | search_metadata
adapter_name: graphiti | qdrant | postgres_search
adapter_version
projection_version
generation
status: pending | indexed | stale | deleting | deleted | failed | skipped
last_outbox_event_id?
last_indexed_at?
last_verified_at?
last_safe_error?
metadata
```

Rules:

- projection state is metadata only and never makes hidden/deleted records visible;
- status is always tied to canonical aggregate version;
- delete/deindex transitions outrank stale upsert transitions;
- failed/skipped projections are visible in diagnostics but canonical reads still work;
- adapter version/projection version changes can mark projections stale and schedule rebuild.

#### ProjectionMapping

Canonical mapping between our aggregate ids and external adapter object ids.

Fields:

```text
id
space_id
profile_id?
projection_state_id
aggregate_type
aggregate_id
aggregate_version
projection_type
adapter_name
adapter_object_type
adapter_object_id_hash
adapter_group_id_hash?
payload_hash?
created_at
updated_at
metadata
```

Rules:

- raw adapter ids are hashed or stored as safe opaque values when they could leak data;
- delete/update uses mapping plus canonical aggregate id, not fuzzy search in adapter;
- mapping must be idempotent for duplicate outbox delivery;
- mapping survives adapter retries and can be invalidated during projection migration.

#### ProjectionRebuildJob

Resumable rebuild or verification job for derived indexes.

Fields:

```text
id
space_id
profile_id?
projection_type: graph | vector | search_metadata | all
adapter_name?
mode: rebuild | verify | deindex | migrate_generation
status: pending | running | paused | completed | failed | cancelled
source_watermark
target_generation
resume_cursor?
processed_count
failed_count
skipped_count
started_at?
completed_at?
last_safe_error?
metadata
```

Rules:

- rebuild reads canonical Postgres records as of `source_watermark`;
- writes after watermark are captured through normal outbox and applied to the active generation;
- new generation is activated only after verification or explicit admin choice;
- partial rebuild can be paused/resumed without deleting active generation;
- verify mode checks projection mappings and canonical filters without printing raw text.

Required tests:

- duplicate outbox upsert creates one projection mapping;
- delete after upsert marks projection deleted even if stale upsert retries later;
- rebuild with concurrent writes reaches a consistent generation;
- projection version change marks old projections stale and schedules rebuild;
- diagnostics report projection drift by ids/counts only.

### Operation and Idempotency Model

Public operations are client-visible units of work. They are not outbox jobs. A single public operation can create canonical records, enqueue many outbox jobs and expose safe progress to SDKs.

#### ClientOperation

Client-visible operation for mutating requests and long-running workflows.

Fields:

```text
id
space_id
profile_id?
principal_id
connector_id?
operation_type: remember_fact | update_fact | forget_fact | ingest_document | import_bundle | export_bundle | retention_apply | projection_rebuild | consolidation | sync_apply | admin_task
status: accepted | running | waiting | succeeded | failed | cancelled | expired
idempotency_key?
request_fingerprint_hash
target_type?
target_id?
progress_current
progress_total?
safe_status
safe_error?
result_snapshot_id?
created_at
updated_at
expires_at?
metadata
```

Rules:

- operation is safe to expose to SDKs and admin UI;
- operation status is derived from use-case progress, not raw worker internals;
- `target_id` is filled when the canonical aggregate exists;
- cancelled operation stops future work when possible but never rolls back already committed canonical data silently;
- operation expiry removes replay/result details only after retention window, not audit.

#### IdempotencyRecord

Replay guard for mutating API calls.

Fields:

```text
id
space_id
principal_id
idempotency_key
request_method
request_path
request_fingerprint_hash
operation_id?
status: processing | completed | failed | conflict | expired
response_snapshot_id?
created_at
updated_at
expires_at
metadata
```

Rules:

- same key plus same request fingerprint returns the stored operation/result;
- same key plus different request fingerprint returns `memory.conflict`;
- record is created before side effects begin;
- processing record can be resumed or queried after server restart;
- expired record does not delete canonical data or audit.

#### OperationResultSnapshot

Production-safe response snapshot for idempotent replay.

Fields:

```text
id
space_id
operation_id
status_code
response_body_safe_json
api_version
created_at
expires_at
metadata
```

Rules:

- snapshot stores only response-safe DTOs, not raw prompts/documents unless endpoint would normally return them;
- replay returns the same status code and compatible response body inside the retention window;
- snapshot can point clients to `operation_id` when work is still running;
- schema version is stored so SDKs can handle replay across minor version updates.

Required tests:

- retry same idempotency key/fingerprint returns same result;
- retry same key/different fingerprint returns conflict;
- server crash after canonical commit but before response can recover operation result;
- cancelling operation does not delete already committed fact/document unless a use case explicitly supports rollback;
- expired idempotency record cannot resurrect or duplicate old side effects.

### DataSensitivity

Value object that controls external processing, export, logging and retention behavior.

Levels:

```text
public:
  safe for normal indexing and export

internal:
  default product/team memory, allowed inside configured deployment

confidential:
  private code, interview notes, customer/team data, external AI blocked by default

secret:
  credentials, tokens, keys, private personal data, embedding/classification blocked

restricted:
  legal/security hold, hard export restrictions, local-only processing
```

Rules:

- sensitivity can only become stricter automatically, not weaker;
- redaction can create a lower-sensitivity derived text, but raw source keeps original sensitivity;
- Graphiti/Qdrant payloads must include sensitivity hint for diagnostics, but authorization still comes from Postgres;
- normal logs and health endpoints never include raw confidential/secret/restricted text;
- export/hard_delete behavior must check sensitivity and policy together.

## Redaction Pipeline

Redaction is a first-class transform, not a string replace helper.

Redaction artifact fields:

```text
id
space_id
profile_id
source_ref_id
raw_text_hash
redacted_text_hash
redaction_version
sensitivity_before
sensitivity_after
rules_applied[]
offset_map[]
created_at
metadata
```

Rules:

- raw source remains canonical evidence unless policy requires hard delete;
- redacted text is derived evidence and must keep source refs to raw protected evidence;
- redaction can downgrade text only for a specific processing purpose, not mutate original sensitivity;
- offset maps must preserve citation ability from redacted snippets back to raw source ranges;
- secret-like values are replaced with typed placeholders, not generic blanks;
- redaction output can be embedded/classified only if `MemoryPolicy` allows that purpose;
- remediation deletes stale embeddings/vector points if secret detection happens after embedding.

Processing purposes:

```text
external_embedding
external_classification
external_summarization
local_embedding
export_redacted
debug_preview
```

Required tests:

- secret detector runs before external embedding/classification;
- redacted snippet keeps stable source offsets;
- redacted derived text cannot be exported as if it were raw evidence;
- late secret detection marks existing embeddings `stale_sensitive` and schedules deindex;
- logs and diagnostics show redaction ids/counts, not raw secret values.

## Retention and Legal Hold Model

Retention is an executable policy with dry-run and audit, not only a timestamp on records.

### RetentionRule

Fields:

```text
id
space_id
profile_id?
scope_type: space | profile | thread | source_type | sensitivity | kind | connector | code_scope
scope_id?
action: downrank | archive | disable | soft_delete | hard_delete | export_then_delete
after_days
grace_days
include_superseded: true | false
include_source_chunks: true | false
requires_dry_run: true | false
created_at
updated_at
version
metadata
```

Rules:

- stricter sensitivity can override normal retention with longer retention or local-only handling;
- `hard_delete` retention requires dry-run and admin grant by default;
- retention jobs operate on canonical Postgres records first, then derived indexes;
- retention never bypasses legal hold, tombstone rules or audit integrity;
- archive/disable can be reversible, hard delete is not normally reversible.

### LegalHold

Fields:

```text
id
space_id
profile_id?
target_type: space | profile | thread | document | episode | fact | source | connector | code_scope
target_id
reason
created_by
created_at
expires_at?
status: active | released | expired
metadata
```

Rules:

- active legal hold blocks retention hard-delete for held targets and derived evidence;
- user-visible forget can still hide held records from normal retrieval through disable/tombstone if policy allows;
- hold status is visible in diagnostics/admin APIs without raw content;
- release/expiry of hold schedules retention re-evaluation, not immediate blind deletion;
- export must label held records and apply the strictest sensitivity.

### RetentionJob

Fields:

```text
id
space_id
rule_id
dry_run: true | false
target_counts
blocked_by_hold_counts
status: pending | running | completed | failed | cancelled
started_at
completed_at
last_safe_error
metadata
```

Rules:

- dry-run returns counts by aggregate type, sensitivity and hold status;
- retention execution is idempotent and resumable;
- delete/deindex events use tombstones and outbox ordering;
- profile/thread deletion uses retention jobs to cascade across facts, chunks, documents, subscriptions and derived indexes;
- failed retention jobs never make partially deleted data visible again.

Required tests:

- retention dry-run reports affected facts/chunks/documents without deleting;
- legal hold blocks hard-delete but normal context hides forgotten records;
- profile delete cascades to derived indexes and object storage cleanup;
- retention job crash resumes without duplicate deletes;
- export after retention does not include hard-deleted raw content.

## Fact Lifecycle

State machine:

```mermaid
stateDiagram-v2
  [*] --> active
  active --> superseded: update_fact
  active --> disabled: disable_fact
  active --> deleted: forget_fact
  superseded --> deleted: forget_fact
  disabled --> active: enable_fact
  disabled --> deleted: forget_fact
  deleted --> [*]
```

Operations:

```text
remember_fact
update_fact
supersede_fact
disable_fact
enable_fact
forget_fact
get_fact_history
```

Important semantics:

- `update_fact` is not a blind SQL update.
- `update_fact` records old and new values.
- `forget_fact` must deindex from Graphiti/Qdrant asynchronously.
- `forget_fact` must immediately hide the fact from API reads by canonical filter.
- `disable_fact` is reversible.
- `deleted` is not reversible by default.

Conflict handling:

```text
new fact contradicts active fact
  -> classifier detects conflict
  -> old fact can be superseded automatically only if confidence/policy allows
  -> otherwise create MemorySuggestion or needs_review marker
```

## Aggregate Lifecycle State Machines

These state machines are part of the domain contract. Adapters may have internal states, but public API and canonical Postgres states must map to these transitions.

### Document Lifecycle

```mermaid
stateDiagram-v2
  [*] --> uploaded
  uploaded --> validating: validate_file
  validating --> rejected: invalid_or_forbidden
  validating --> extracting: accepted
  extracting --> extraction_failed: parser_failed
  extracting --> chunking: extracted_text
  extraction_failed --> extracting: retry_after_fix
  extraction_failed --> deleted: forget_document
  chunking --> indexing: chunks_created
  chunking --> partially_processed: partial_extraction
  partially_processed --> indexing: approve_partial
  partially_processed --> deleted: forget_document
  indexing --> processed: graph_and_vector_done
  indexing --> index_failed: index_error
  index_failed --> indexing: retry_index
  processed --> disabled: disable_document
  disabled --> processed: enable_document
  processed --> deleted: forget_document
  disabled --> deleted: forget_document
  rejected --> deleted: forget_document
  deleted --> [*]
```

Rules:

- `uploaded` stores metadata and object reference only, not trusted memory.
- `validating` checks size, mime, extension, parser support, sensitivity and policy.
- `partially_processed` is queryable only if policy allows partial sources and API marks it clearly.
- `index_failed` never blocks canonical reads of already accepted metadata, but search/context must show reduced index status.
- `deleted` hides document, chunks and derived facts from normal reads immediately through canonical filters.

Required tests:

- invalid file cannot reach `extracting`;
- parser failure does not create facts;
- partial extraction requires explicit approval or policy;
- deleting processed document hides chunks and source-derived facts;
- retrying `index_failed` is idempotent.

### Storage Object Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending_upload
  pending_upload --> uploaded: upload_complete
  uploaded --> verified: checksum_verified
  uploaded --> quarantined: validation_or_scan_failed
  verified --> active: linked_to_document_or_artifact
  active --> delete_pending: hard_delete_or_expiry
  active --> quarantined: late_integrity_or_security_failure
  delete_pending --> deleted: object_delete_verified
  delete_pending --> missing: object_missing_before_delete
  active --> corrupted: checksum_mismatch
  quarantined --> delete_pending: policy_delete
  deleted --> [*]
  missing --> [*]
  corrupted --> delete_pending: admin_delete
```

Rules:

- `active` requires verified checksum and canonical owner scope;
- `quarantined`, `missing` and `corrupted` objects are never used for prompt context;
- `delete_pending` is visible until physical deletion or legal hold status is resolved;
- object storage delete is verified asynchronously because DB transaction and blob delete are not atomic.

Required tests:

- checksum mismatch blocks activation;
- late corruption hides dependent document/artifact from normal reads;
- hard-delete reaches deleted or held delete_pending state with audit;
- object key never appears in normal diagnostics.

### Upload Session Lifecycle

```mermaid
stateDiagram-v2
  [*] --> created
  created --> uploading: first_part_received
  uploading --> uploaded: all_parts_received
  uploaded --> verifying: complete_requested
  verifying --> completed: checksum_size_mime_ok
  verifying --> failed: validation_failed
  created --> expired: ttl_elapsed
  uploading --> aborted: user_or_cleanup_abort
  failed --> [*]
  completed --> [*]
  expired --> [*]
  aborted --> [*]
```

Rules:

- completed upload can create document/import artifact only once;
- expired or aborted upload cannot be resumed without a new session;
- failed verification never leaves a trusted `StorageObject`.

### Suggestion Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> approved: approve
  pending --> rejected: reject
  pending --> expired: ttl_expired
  pending --> superseded: better_candidate
  pending --> auto_promoted: policy_auto_safe
  approved --> materialized: fact_created
  auto_promoted --> materialized: fact_created
  materialized --> superseded: source_fact_updated
  materialized --> deleted: source_deleted
  rejected --> [*]
  expired --> [*]
  superseded --> [*]
  deleted --> [*]
```

Rules:

- suggestions are not facts until `materialized`;
- `auto_promoted` must write audit with classifier version, policy version, source refs and confidence;
- connector-generated suggestions cannot be approved by the same connector unless policy explicitly allows it;
- source deletion cancels or deletes pending/materialized suggestions depending on whether a fact was created.

Required tests:

- approve creates exactly one fact with source refs;
- reject never indexes memory;
- auto promotion blocks low confidence, conflicts and low-trust sources;
- duplicate candidates collapse into the newest or strongest suggestion;
- self-approval is denied for agent connectors by default.

### Digest Lifecycle

```mermaid
stateDiagram-v2
  [*] --> active
  active --> stale: source_or_policy_changed
  active --> superseded: refreshed_digest_created
  active --> disabled: policy_disabled
  stale --> active: refresh_success
  stale --> deleted: source_hard_deleted
  stale --> superseded: replacement_created
  disabled --> active: policy_enabled
  disabled --> deleted: forget_or_retention
  superseded --> deleted: retention
  deleted --> [*]
```

Rules:

- digest lifecycle follows source refs, source versions, redaction version and policy version;
- stale digest is excluded from normal context unless explicitly requested for diagnostics;
- refreshed digest creates a new version or superseding row with audit;
- hard-delete of required source removes or disables derived digest according to policy.

Required tests:

- source update marks digest stale;
- stale digest is not packed into normal context;
- refresh creates superseding digest with source refs;
- hard-delete source removes digest from normal retrieval.

### Consolidation Job Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> running: worker_claim
  running --> dry_run_ready: candidates_found
  running --> completed: no_changes
  dry_run_ready --> completed: auto_safe_apply
  dry_run_ready --> blocked: review_required
  blocked --> running: reviewer_approves
  running --> failed: retryable_error
  running --> cancelled: cancel
  failed --> running: retry
  completed --> [*]
  cancelled --> [*]
```

Rules:

- `dry_run_ready` stores candidate counts, not raw private text;
- `auto_safe_apply` is limited to non-destructive metadata such as cluster creation or digest refresh;
- fact merge/delete requires review unless a later ADR defines stricter automatic rules;
- completed job records source coverage and false-merge guardrail score.

Required tests:

- consolidation job with no candidates completes without side effects;
- review-required candidates do not mutate active facts;
- auto-safe cluster creation does not hide or merge facts;
- retry after failure does not duplicate clusters or digests.

### Quota Reservation Lifecycle

```mermaid
stateDiagram-v2
  [*] --> reserved
  reserved --> committed: work_completed
  reserved --> released: work_cancelled_or_skipped
  reserved --> expired: ttl_elapsed
  reserved --> rejected: limit_rechecked_and_blocked
  expired --> reserved: retry_with_new_reservation
  committed --> [*]
  released --> [*]
  rejected --> [*]
```

Rules:

- reservation must be created before expensive provider/storage/worker work;
- commit records actual usage and idempotency key;
- release is safe to call multiple times;
- expired reservations are ignored by admission checks after cleanup grace period;
- rejected reservation must include safe reason code and matching quota rule ids.

Required tests:

- duplicate reservation request returns same active reservation;
- commit after release or expiry is rejected safely;
- provider timeout releases or expires reservation without double-counting usage;
- hard quota rejection creates no provider call.

### Projection State Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> indexed: adapter_upsert_done
  pending --> skipped: policy_or_capability_skip
  pending --> failed: adapter_error
  indexed --> stale: aggregate_or_projection_version_changed
  indexed --> deleting: canonical_delete
  stale --> pending: reindex_enqueued
  failed --> pending: retry_or_rebuild
  deleting --> deleted: adapter_delete_done
  deleting --> failed: adapter_delete_failed
  skipped --> pending: policy_or_capability_enabled
  deleted --> [*]
```

Rules:

- projection lifecycle is driven by canonical aggregate status and outbox events;
- stale/failed projections are never returned directly to clients without canonical filtering;
- delete/deindex can move from any non-deleted state to `deleting`;
- projection state transitions are idempotent by aggregate id/version/projection type.

Required tests:

- stale upsert after delete cannot move projection back to indexed;
- retry updates same projection state instead of creating duplicates;
- capability skip is visible but not an error;
- projection stale status appears in diagnostics.

### Projection Rebuild Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> running: worker_claim
  running --> paused: pause
  paused --> running: resume
  running --> verifying: source_watermark_processed
  verifying --> completed: verification_passed
  verifying --> failed: verification_failed
  running --> failed: unrecoverable_error
  running --> cancelled: cancel
  failed --> running: retry
  completed --> [*]
  cancelled --> [*]
```

Rules:

- rebuild job owns a target generation and source watermark;
- active generation is not replaced by failed rebuild;
- cancellation leaves canonical data untouched;
- verification failure keeps old generation active and reports safe counts.

Required tests:

- rebuild can pause/resume from cursor;
- failed rebuild does not change active generation;
- rebuild after adapter migration verifies projection mappings;
- cancel leaves canonical reads and previous projections available.

### Client Operation Lifecycle

```mermaid
stateDiagram-v2
  [*] --> accepted
  accepted --> running: processing_started
  accepted --> waiting: queued_or_rate_limited
  waiting --> running: resources_available
  running --> succeeded: result_committed
  running --> failed: safe_error
  running --> cancelled: cancel_requested
  waiting --> cancelled: cancel_requested
  succeeded --> expired: replay_window_elapsed
  failed --> expired: replay_window_elapsed
  cancelled --> expired: replay_window_elapsed
  expired --> [*]
```

Rules:

- operation lifecycle is public API state;
- internal outbox jobs can fail/retry while operation remains `running` or `waiting`;
- `succeeded` means canonical operation result is committed, not necessarily every derived index is up to date;
- cancellation is best-effort and must report what was already committed.

Required tests:

- operation status survives server restart;
- running operation can be polled without exposing internal worker errors;
- succeeded operation may still report projection/indexing pending;
- cancelled operation keeps audit and committed target ids.

### Idempotency Record Lifecycle

```mermaid
stateDiagram-v2
  [*] --> processing
  processing --> completed: response_snapshot_saved
  processing --> failed: safe_error_saved
  processing --> conflict: fingerprint_mismatch
  completed --> expired: replay_window_elapsed
  failed --> expired: replay_window_elapsed
  conflict --> expired: replay_window_elapsed
  expired --> [*]
```

Rules:

- idempotency record is created before side effects;
- completed replay returns stored response snapshot;
- processing replay returns operation status or retry-after;
- fingerprint mismatch is a conflict, never a second operation.

Required tests:

- processing replay does not start another operation;
- completed replay returns same response body;
- failed replay returns safe error consistently;
- expired record does not hide existing canonical records.

### Outbox Job Lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> leased: worker_claim
  leased --> succeeded: complete
  leased --> retry_pending: retryable_error
  leased --> dead_letter: non_retryable_or_max_attempts
  retry_pending --> pending: backoff_elapsed
  leased --> pending: lease_expired
  dead_letter --> pending: manual_requeue
  succeeded --> [*]
```

Rules:

- each job has `idempotency_key`, `aggregate_id`, `aggregate_version` and `ordering_key`;
- stale jobs must re-read canonical aggregate status before writing to Graphiti/Qdrant;
- delete/deindex jobs outrank upsert/index jobs for the same aggregate;
- manual requeue must preserve original causality metadata and append a new attempt record.

Required tests:

- duplicate delivery is idempotent;
- expired lease can be reclaimed;
- stale upsert after delete cannot resurrect memory;
- dead-letter appears in diagnostics with safe details;
- per-profile ordering key prevents out-of-order graph/vector writes for the same memory.

### Import and Export Lifecycle

```mermaid
stateDiagram-v2
  [*] --> requested
  requested --> validating: validate_bundle_or_scope
  validating --> rejected: invalid_or_forbidden
  validating --> dry_run_ready: dry_run_ok
  dry_run_ready --> running: apply_or_generate
  running --> completed: success
  running --> failed: error
  running --> cancelled: cancel
  failed --> running: retry
  completed --> expired: artifact_ttl_elapsed
  rejected --> [*]
  cancelled --> [*]
  expired --> [*]
```

Rules:

- import must run dry-run before applying by default;
- dry-run reports conflicts, tombstone collisions, unknown ontology entries and policy incompatibilities;
- export bundle includes schema version, ontology version, policy version, tombstones and source refs;
- completed export artifacts have TTL and sensitivity-aware access checks;
- import cannot resurrect a hard-deleted fact unless explicit admin override exists and is audited.

Required tests:

- import dry-run detects tombstone resurrection;
- import unknown ontology kind maps through alias or fails safely;
- export excludes raw secret/restricted text by default;
- cancelled job leaves no partially visible facts without audit;
- retry after failed import is idempotent.

### Sync ChangeSet Lifecycle

```mermaid
stateDiagram-v2
  [*] --> prepared
  prepared --> dry_run: validate_against_destination
  dry_run --> rejected: unsupported_or_policy_blocked
  dry_run --> conflict_blocked: unresolved_conflicts
  dry_run --> ready: no_blocking_conflicts
  ready --> applying: apply
  applying --> applied: canonical_commit_done
  applying --> failed: retryable_or_partial_failure
  failed --> applying: retry
  conflict_blocked --> ready: conflicts_resolved
  ready --> expired: ttl_elapsed
  rejected --> [*]
  applied --> [*]
  expired --> [*]
```

Rules:

- sync change sets are future-gated and disabled by default in v1;
- `dry_run` is mandatory before `applying`;
- `applied` means canonical Postgres commit succeeded, not that derived indexes are caught up;
- checkpoint advances only after canonical apply succeeds;
- failed apply must be resumable by change set id and aggregate version.

Required tests:

- unsupported sync endpoint does not mutate anything;
- dry-run detects policy, permission, tombstone and legal hold blockers;
- unresolved conflicts block apply;
- retrying failed apply does not duplicate facts or advance checkpoint twice;
- derived indexes are populated only through outbox after canonical apply.

### Policy Lifecycle

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> active: activate
  active --> superseded: replace_policy
  active --> disabled: disable_memory
  disabled --> active: enable_memory
  superseded --> archived: retention_elapsed
  disabled --> archived: delete_profile_or_retention
  archived --> [*]
```

Rules:

- active policy is versioned and copied into every suggestion/fact decision audit;
- changing policy does not mutate historical decisions silently;
- pending jobs must capture policy version and re-check current policy before promotion;
- disabling memory cancels prompt-time retrieval immediately and drains or pauses ingest according to mode.

Required tests:

- optimistic version conflict on concurrent policy update;
- pending auto-memory job re-checks policy before materializing;
- disabling memory blocks context and backend calls in compatibility mode;
- old policy versions remain queryable for audit.

## Ports

### Repository Ports

```python
class FactRepositoryPort:
    async def create(...)
    async def get_by_id(...)
    async def update_status(...)
    async def append_version(...)
    async def find_active_by_ids(...)
    async def search_metadata(...)
    async def find_current_candidates(...)
    async def mark_currency_state(...)

class FactConflictRepositoryPort:
    async def create_conflict(...)
    async def get_conflict(...)
    async def list_open_conflicts(...)
    async def resolve_conflict(...)
    async def record_supersession_decision(...)

class EpisodeRepositoryPort:
    async def create(...)
    async def get_by_id(...)
    async def mark_deleted(...)

class DocumentRepositoryPort:
    async def create_document(...)
    async def create_chunks(...)
    async def get_chunks_by_ids(...)
    async def mark_document_deleted(...)

class StorageObjectRepositoryPort:
    async def create_storage_object(...)
    async def mark_uploaded(...)
    async def mark_verified(...)
    async def mark_quarantined(...)
    async def mark_delete_pending(...)
    async def mark_deleted(...)
    async def get_by_id(...)
    async def list_orphans(...)

class UploadSessionRepositoryPort:
    async def create_upload_session(...)
    async def get_upload_session(...)
    async def complete_upload_session(...)
    async def expire_upload_sessions(...)
    async def abort_upload_session(...)

class ArtifactRepositoryPort:
    async def create_artifact(...)
    async def get_artifact(...)
    async def mark_available(...)
    async def revoke_artifact(...)
    async def expire_artifacts(...)
    async def record_download(...)

class BackupRepositoryPort:
    async def create_policy(...)
    async def get_policy(...)
    async def create_backup_run(...)
    async def update_backup_run(...)
    async def create_manifest(...)
    async def get_manifest(...)
    async def expire_backup_artifacts(...)

class RestoreRepositoryPort:
    async def create_restore_run(...)
    async def update_restore_run(...)
    async def attach_validation_report(...)
    async def get_restore_run(...)
    async def list_restore_blockers(...)

class EntityRepositoryPort:
    async def create_or_get(...)
    async def get_by_id(...)
    async def find_candidates(...)
    async def add_alias(...)
    async def merge_entities(...)
    async def split_entity(...)

class ProfileRepositoryPort:
    async def create(...)
    async def get(...)
    async def list(...)

class BootstrapRepositoryPort:
    async def get_bootstrap_state(...)
    async def begin_bootstrap(...)
    async def complete_bootstrap(...)
    async def lock_bootstrap(...)
    async def record_bootstrap_attempt(...)

class RuntimeConfigRepositoryPort:
    async def record_config_snapshot(...)
    async def get_active_config_snapshot(...)
    async def compare_process_config(...)
    async def mark_config_misconfigured(...)

class DataResidencyRepositoryPort:
    async def get_region(...)
    async def list_regions(...)
    async def get_effective_residency_policy(...)
    async def record_processing_location_decision(...)
    async def create_cross_region_transfer_request(...)
    async def update_cross_region_transfer_status(...)

class SupplyChainRepositoryPort:
    async def record_dependency_inventory(...)
    async def record_risk_finding(...)
    async def get_effective_license_policy(...)
    async def record_parser_execution_run(...)
    async def record_release_attestation(...)
    async def list_blocking_findings(...)

class MigrationRepositoryPort:
    async def create_migration_run(...)
    async def get_migration_run(...)
    async def acquire_migration_lock(...)
    async def update_migration_phase(...)
    async def mark_migration_failed(...)
    async def create_backfill_job(...)
    async def claim_backfill_chunk(...)
    async def update_backfill_progress(...)
    async def list_active_compatibility_windows(...)

class WorkerRepositoryPort:
    async def register_worker_instance(...)
    async def heartbeat_worker_instance(...)
    async def mark_worker_draining(...)
    async def mark_worker_stopped(...)
    async def mark_worker_stale(...)
    async def list_active_workers(...)

class WorkerLeaseRepositoryPort:
    async def acquire_lease(...)
    async def renew_lease(...)
    async def release_lease(...)
    async def expire_stale_leases(...)
    async def list_leases_by_worker(...)

class ScheduledTaskRepositoryPort:
    async def get_due_tasks(...)
    async def acquire_task_lease(...)
    async def record_task_started(...)
    async def record_task_finished(...)
    async def mark_task_failed(...)

class PrincipalRepositoryPort:
    async def resolve_principal(...)
    async def get_membership(...)
    async def list_profile_grants(...)

class AuthorizationPort:
    async def require_space_action(...)
    async def require_profile_action(...)
    async def filter_readable_profiles(...)
    async def build_read_scope(...)

class VisibilityGuardPort:
    async def build_predicate(...)
    async def filter_visible_ids(...)
    async def require_visibility_proof(...)
    async def explain_denial(...)

class RepositoryScopePort:
    async def build_repository_scope(...)
    async def bind_scope_to_unit_of_work(...)
    async def require_scoped_context(...)
    async def record_query_scope_proof(...)
    async def create_maintenance_override(...)
    async def explain_scope_denial(...)

class PromptPathBudgetPort:
    async def resolve_budget(...)
    async def split_stage_budgets(...)
    async def record_stage_result(...)
    async def decide_degradation(...)

class PolicyRepositoryPort:
    async def get_for_profile(...)
    async def get_effective_policy(...)
    async def update_policy(...)

class OntologyRepositoryPort:
    async def get_current(...)
    async def resolve_kind(...)
    async def resolve_relation_type(...)
    async def resolve_source_type(...)
    async def list_aliases(...)

class SuggestionRepositoryPort:
    async def create(...)
    async def get_by_id(...)
    async def list_pending(...)
    async def mark_approved(...)
    async def mark_rejected(...)

class WriteAdmissionRepositoryPort:
    async def record_admission(...)
    async def get_admission(...)
    async def create_poisoning_signal(...)
    async def quarantine_candidate(...)
    async def release_quarantined_candidate(...)

class ConsolidationRepositoryPort:
    async def create_cluster(...)
    async def update_cluster_status(...)
    async def add_cluster_members(...)
    async def create_digest(...)
    async def mark_digest_stale(...)
    async def create_consolidation_job(...)
    async def update_consolidation_job(...)
    async def find_duplicate_candidates(...)

class ConnectorRepositoryPort:
    async def create_installation(...)
    async def get_installation(...)
    async def update_status(...)
    async def get_sync_state(...)
    async def update_sync_state(...)

class CodeRepositoryPort:
    async def resolve_repository(...)
    async def get_repository(...)
    async def upsert_code_reference(...)
    async def mark_code_reference_status(...)

class CodeReferenceResolverPort:
    async def resolve_reference(...)
    async def detect_file_rename(...)
    async def detect_symbol_move(...)
    async def map_line_range(...)

class EventSubscriptionRepositoryPort:
    async def create_subscription(...)
    async def list_subscriptions(...)
    async def update_delivery_cursor(...)
    async def mark_failed(...)

class CacheRepositoryPort:
    async def get_entry_metadata(...)
    async def record_entry_metadata(...)
    async def find_overlapping_invalidations(...)
    async def record_invalidation(...)
    async def mark_entry_invalidated(...)
    async def purge_expired_entries(...)
    async def list_cache_diagnostics(...)

class UsageRepositoryPort:
    async def record_usage(...)
    async def get_usage_window(...)
    async def list_usage_by_scope(...)

class QuotaRepositoryPort:
    async def create_rule(...)
    async def get_effective_rules(...)
    async def create_reservation(...)
    async def commit_reservation(...)
    async def release_reservation(...)
    async def expire_reservations(...)

class OperationRepositoryPort:
    async def create_operation(...)
    async def get_operation(...)
    async def update_operation_status(...)
    async def attach_result_snapshot(...)
    async def cancel_operation(...)
    async def expire_operations(...)

class IdempotencyRepositoryPort:
    async def begin_request(...)
    async def get_record(...)
    async def mark_completed(...)
    async def mark_failed(...)
    async def mark_conflict(...)
    async def expire_records(...)

class ProjectionRepositoryPort:
    async def get_state(...)
    async def upsert_state(...)
    async def mark_stale(...)
    async def mark_deleted(...)
    async def upsert_mapping(...)
    async def get_mapping(...)
    async def create_rebuild_job(...)
    async def update_rebuild_job(...)
    async def list_projection_drift(...)

class SyncRepositoryPort:
    async def register_peer(...)
    async def revoke_peer(...)
    async def get_checkpoint(...)
    async def update_checkpoint(...)
    async def prepare_change_set(...)
    async def record_conflict(...)
    async def list_open_conflicts(...)

class RetentionRepositoryPort:
    async def create_rule(...)
    async def get_effective_rules(...)
    async def create_retention_job(...)
    async def update_retention_job(...)
    async def list_due_targets(...)

class LegalHoldRepositoryPort:
    async def create_hold(...)
    async def release_hold(...)
    async def list_active_holds(...)
    async def is_target_held(...)

class UnitOfWorkPort:
    async def __aenter__()
    async def __aexit__()
    async def commit()
    async def rollback()
```

### Engine Ports

```python
class GraphMemoryPort:
    async def upsert_episode(...)
    async def upsert_fact(...)
    async def search_facts(...)
    async def delete_fact(...)
    async def delete_episode(...)
    async def health()
    async def capabilities()

class VectorMemoryPort:
    async def upsert_chunks(...)
    async def search_chunks(...)
    async def delete_chunks(...)
    async def delete_document(...)
    async def health()
    async def capabilities()

class ProjectionAdminPort:
    async def verify_projection(...)
    async def rebuild_projection(...)
    async def activate_generation(...)
    async def delete_generation(...)
    async def capabilities()
```

### AI/Processing Ports

```python
class EmbeddingPort:
    async def embed_texts(texts: list[str]) -> list[list[float]]
    def dimensions() -> int

class ClassifierPort:
    async def classify_ingestion_item(...)
    async def extract_candidate_facts(...)
    async def detect_conflicts(...)
    async def score_importance(...)

class EntityResolutionPort:
    async def resolve_entity(...)
    async def propose_aliases(...)
    async def detect_ambiguous_match(...)

class EvidenceScoringPort:
    async def score_evidence(...)
    async def combine_confidence(...)
    async def explain_confidence(...)

class FactCurrencyResolverPort:
    async def detect_conflict(...)
    async def propose_supersession(...)
    async def resolve_current_fact_set(...)
    async def explain_currency(...)

class RedactionPort:
    async def detect_sensitivity(...)
    async def redact_for_purpose(...)
    async def build_offset_map(...)
    async def explain_redaction(...)

class WriteAdmissionPort:
    async def evaluate_write_intent(...)
    async def detect_poisoning_signals(...)
    async def decide_quarantine_or_review(...)
    async def explain_write_decision(...)

class PromptTemplatePort:
    async def get_template(...)
    async def get_output_schema(...)
    async def validate_structured_output(...)

class AIProviderGatewayPort:
    async def call_model(...)
    async def call_embedding_model(...)
    async def check_policy_and_budget(...)
    async def health()
    async def capabilities()

class RerankerPort:
    async def rerank(query, candidates) -> list[RankedCandidate]

class SemanticSimilarityPort:
    async def score_pair(...)
    async def cluster_candidates(...)
    async def explain_similarity(...)

class ObjectStoragePort:
    async def create_upload_url(...)
    async def complete_multipart_upload(...)
    async def verify_checksum(...)
    async def put(...)
    async def get(...)
    async def delete(...)
    async def exists(...)
    async def quarantine(...)
```

### Reliability Ports

```python
class OutboxPort:
    async def enqueue(event)
    async def claim_batch(...)
    async def mark_done(...)
    async def mark_failed(...)

class AuditPort:
    async def record(event)

class QuotaPort:
    async def check_and_reserve(...)
    async def admit_work(...)
    async def get_effective_limits(...)
    async def release(...)
    async def record_usage(...)

class ProjectionHealthPort:
    async def report_drift(...)
    async def report_generation_status(...)
    async def report_backlog(...)

class CacheStorePort:
    async def get_payload(...)
    async def put_payload(...)
    async def delete_payload(...)
    async def singleflight(...)
    async def health()

class BackupStoragePort:
    async def create_database_backup(...)
    async def create_object_inventory(...)
    async def create_qdrant_snapshot(...)
    async def create_graph_snapshot(...)
    async def verify_manifest_refs(...)
    async def restore_database_backup(...)
    async def fetch_object_ref(...)
```

### Security Ports

```python
class KeyManagementPort:
    async def get_active_key_version(...)
    async def encrypt(...)
    async def decrypt(...)
    async def rotate_key(...)
    async def reencrypt_batch(...)

class TokenStorePort:
    async def create_token_hash(...)
    async def verify_token(...)
    async def revoke_token(...)
    async def rotate_token(...)

class AuditIntegrityPort:
    async def append_event(...)
    async def verify_chain(...)
    async def export_chain_proof(...)

class WebhookSecurityPort:
    async def verify_signature(...)
    async def detect_replay(...)
    async def sign_delivery(...)

class BootstrapTokenPort:
    async def create_one_time_token(...)
    async def verify_one_time_token(...)
    async def revoke_one_time_token(...)

class RuntimeConfigPort:
    async def load_effective_config(...)
    async def validate_startup_config(...)
    async def fingerprint_config(...)
    async def safe_capabilities_from_config(...)

class ResidencyPolicyPort:
    async def resolve_policy(...)
    async def decide_processing_location(...)
    async def require_allowed_location(...)
    async def explain_location_denial(...)

class ParserSandboxPort:
    async def resolve_sandbox_policy(...)
    async def run_parser(...)
    async def enforce_resource_limits(...)
    async def quarantine_on_violation(...)

class SupplyChainSecurityPort:
    async def build_dependency_inventory(...)
    async def run_vulnerability_scan(...)
    async def run_license_scan(...)
    async def create_sbom(...)
    async def verify_release_attestation(...)
    async def evaluate_release_gate(...)
```

## Adapters

### Postgres Adapter

Responsibilities:

- canonical entities;
- transactions;
- optimistic locking;
- outbox;
- audit;
- status filtering;
- repository scope predicate compiler;
- optional RLS/session-scope enforcement for remote/team mode;
- migrations.

Recommended tables:

```text
memory_spaces
memory_deployment_instances
memory_bootstrap_states
memory_runtime_config_snapshots
memory_deployment_regions
memory_data_residency_policies
memory_processing_location_decisions
memory_cross_region_transfer_requests
memory_dependency_inventory
memory_dependency_risk_findings
memory_license_policies
memory_parser_sandbox_policies
memory_parser_execution_runs
memory_release_artifact_attestations
memory_schema_migration_runs
memory_data_backfill_jobs
memory_compatibility_windows
memory_worker_instances
memory_worker_leases
memory_scheduled_tasks
memory_scheduled_task_runs
memory_principals
memory_api_tokens
memory_key_versions
memory_connector_installations
memory_connector_sync_states
memory_event_subscriptions
memory_event_deliveries
memory_cache_entries
memory_cache_invalidations
memory_sync_peers
memory_sync_checkpoints
memory_sync_change_sets
memory_sync_conflicts
memory_code_repositories
memory_code_references
memory_retention_rules
memory_retention_jobs
memory_legal_holds
memory_space_members
memory_profile_grants
memory_repository_scope_proofs
memory_maintenance_scope_overrides
memory_read_access_audit
memory_prompt_path_runs
memory_prompt_path_stage_runs
memory_profiles
memory_threads
memory_episodes
memory_storage_objects
memory_upload_sessions
memory_artifacts
memory_backup_policies
memory_backup_runs
memory_backup_manifests
memory_restore_runs
memory_restore_validation_reports
memory_documents
memory_document_chunks
memory_entities
memory_entity_aliases
memory_facts
memory_fact_versions
memory_fact_relations
memory_fact_currency_states
memory_fact_conflicts
memory_supersession_decisions
memory_source_refs
memory_tombstones
memory_suggestions
memory_write_admissions
memory_poisoning_signals
memory_quarantined_candidates
memory_clusters
memory_cluster_members
memory_digests
memory_consolidation_jobs
memory_projection_states
memory_projection_mappings
memory_projection_rebuild_jobs
memory_client_operations
memory_idempotency_records
memory_operation_result_snapshots
memory_redaction_artifacts
memory_prompt_templates
memory_ai_call_audit
memory_provider_configs
memory_outbox
memory_audit_events
memory_audit_chain
memory_policies
memory_usage_records
memory_quota_rules
memory_quota_reservations
memory_ontology_versions
memory_ontology_aliases
```

Sync tables are contract tables, not a promise that bidirectional sync ships in v1. They can be introduced behind `supports_sync_exchange=false` until the sync ADR and tests are ready.

Indexes:

```text
(space_id, profile_id, status)
(space_id, profile_id, thread_id)
(space_id, profile_id, content_hash)
(deployment_id, status) on memory_deployment_instances
(deployment_id, state) on memory_bootstrap_states
(deployment_id, config_hash, created_at) on memory_runtime_config_snapshots
(deployment_id, code, status) on memory_deployment_regions
(space_id, profile_id, status, policy_version) on memory_data_residency_policies
(space_id, profile_id, purpose, decision, created_at) on memory_processing_location_decisions
(space_id, status, purpose, created_at) on memory_cross_region_transfer_requests
(release_version, package_name, package_version) on memory_dependency_inventory
(release_version, severity, status) on memory_dependency_risk_findings
(deployment_id, status) on memory_license_policies
(space_id, profile_id, parser_family, status) on memory_parser_sandbox_policies
(space_id, profile_id, document_id, status, started_at) on memory_parser_execution_runs
(release_version, artifact_type, scan_status) on memory_release_artifact_attestations
(deployment_id, target_version, status) on memory_schema_migration_runs
(migration_run_id, status, resume_cursor) on memory_data_backfill_jobs
(contract_family, old_version, new_version, status) on memory_compatibility_windows
(deployment_id, worker_group, status, last_heartbeat_at) on memory_worker_instances
(lease_key, status, expires_at) unique where status = active on memory_worker_leases
(task_key, enabled, next_run_at) on memory_scheduled_tasks
(task_key, started_at, status) on memory_scheduled_task_runs
(space_id, profile_id, purpose, content_hash) on memory_storage_objects
(space_id, status, expires_at) on memory_upload_sessions
(space_id, artifact_type, status, expires_at) on memory_artifacts
(space_id, scope, status) on memory_backup_policies
(policy_id, status, started_at) on memory_backup_runs
(backup_run_id, manifest_schema_version) on memory_backup_manifests
(target_deployment_id, status, started_at) on memory_restore_runs
(restore_run_id, status, checked_at) on memory_restore_validation_reports
(space_id, profile_id, entity_key) unique where status = active
(space_id, profile_id, alias) on memory_entity_aliases
(space_id, profile_id, entity_type, status) on memory_entities
(fact_id, version)
(entity_id, status) on memory_facts
(space_id, profile_id, entity_id, kind, currency_status) on memory_fact_currency_states
(space_id, profile_id, status, created_at) on memory_fact_conflicts
(space_id, target_fact_id, decision_status) on memory_supersession_decisions
(principal_id, token_prefix, status) on memory_api_tokens
(space_id, key_purpose, status) on memory_key_versions
(space_id, source_app, status) on memory_connector_installations
(connector_id, source_stream) unique on memory_connector_sync_states
(space_id, principal_id, status) on memory_event_subscriptions
(subscription_id, cursor, status) on memory_event_deliveries
(space_id, cache_kind, profile_ids_hash, query_hash, expires_at) on memory_cache_entries
(space_id, target_type, target_id, commit_position) on memory_cache_invalidations
(space_id, cache_kind, invalidated_at, expires_at) on memory_cache_entries
(space_id, principal_id, peer_type, status) on memory_sync_peers
(space_id, peer_id, direction, status) on memory_sync_checkpoints
(space_id, peer_id, base_cursor, target_cursor) on memory_sync_change_sets
(space_id, profile_id, aggregate_type, aggregate_id, resolution_status) on memory_sync_conflicts
(space_id, repo_key, status) on memory_code_repositories
(space_id, repo_id, commit_sha, file_path) on memory_code_references
(space_id, repo_id, symbol_name, status) on memory_code_references
(space_id, scope_type, scope_id, version) on memory_retention_rules
(space_id, rule_id, status) on memory_retention_jobs
(space_id, target_type, target_id, status) on memory_legal_holds
(space_id, principal_id, purpose, created_at) on memory_read_access_audit
(space_id, profile_id, status, started_at) on memory_prompt_path_runs
(prompt_path_run_id, stage, status) on memory_prompt_path_stage_runs
(target_type, target_id) on tombstones
(space_id, profile_id, status, created_at) on suggestions
(space_id, profile_id, decision, created_at) on memory_write_admissions
(space_id, profile_id, signal_type, severity) on memory_poisoning_signals
(space_id, profile_id, status, created_at) on memory_quarantined_candidates
(space_id, profile_id, cluster_type, status) on memory_clusters
(space_id, cluster_id, member_type, member_id) unique on memory_cluster_members
(space_id, profile_id, cluster_id, status) on memory_digests
(space_id, profile_id, mode, status) on memory_consolidation_jobs
(space_id, aggregate_type, aggregate_id, projection_type, adapter_name) on memory_projection_states
(space_id, projection_type, adapter_name, generation, status) on memory_projection_states
(space_id, aggregate_type, aggregate_id, adapter_name, adapter_object_id_hash) on memory_projection_mappings
(space_id, projection_type, adapter_name, status) on memory_projection_rebuild_jobs
(space_id, principal_id, status, created_at) on memory_client_operations
(space_id, operation_type, target_type, target_id, status) on memory_client_operations
(space_id, principal_id, idempotency_key) unique on memory_idempotency_records
(operation_id, created_at) on memory_operation_result_snapshots
(space_id, profile_id, source_ref_id) on redaction_artifacts
(purpose, version, status) on prompt_templates
(space_id, profile_id, provider, purpose, created_at) on ai_call_audit
(space_id, provider, status) on provider_configs
(space_id, sequence_no) unique on audit_chain
(space_id, profile_id, version) on policies
(space_id, profile_id, scope_type, scope_id, priority) on policies
(space_id, resource_type, occurred_at) on memory_usage_records
(space_id, profile_id, workload_class, resource_type, occurred_at) on memory_usage_records
(space_id, scope_type, resource_type, priority) on memory_quota_rules
(space_id, status, expires_at) on memory_quota_reservations
(space_id, idempotency_key) unique on memory_quota_reservations
(space_id, principal_id, role, status) on space_members
(space_id, profile_id, principal_id, status) on profile_grants
(space_id, table_family, operation_type, created_at) on memory_repository_scope_proofs
(space_id, operation_type, status, expires_at) on memory_maintenance_scope_overrides
(ontology_version, canonical_kind) on ontology_versions
(alias, target_kind) on ontology_aliases
(status, next_attempt_at) on outbox
(idempotency_key) unique on outbox
```

Concurrency:

- use optimistic `version` on facts;
- outbox claim uses `FOR UPDATE SKIP LOCKED`;
- delete/update returns conflict if expected version mismatches.
- use deterministic idempotency keys for outbox events and adapter writes;
- process ordering-sensitive events with a per-profile or per-aggregate ordering key;
- worker leases must expire and be safely claimable after crash.

### Graphiti Adapter

Role:

- derived temporal graph index for facts/entities/relations.

Use for:

- extracted facts;
- entity relationships;
- temporal invalidation;
- graph-aware search;
- profile separation by `group_id`.

Do not use for:

- raw large files;
- every document chunk;
- canonical deletion;
- user permissions source of truth;
- audit.

Mapping:

```text
MemoryProfile -> Graphiti group_id
MemoryEpisode -> Graphiti episode
MemoryEntity -> Graphiti entity candidate/mapping metadata
MemoryFact -> Graphiti triplet/edge or episode-derived edge
SourceRef -> Graphiti episode metadata + Postgres canonical source ref
```

Recommended `group_id`:

```text
space:{space_id}:profile:{profile_id}
```

Important Graphiti behavior:

- process episodes sequentially per group/profile;
- use `reference_time` from source event, not wall-clock ingestion time;
- resolve canonical `MemoryEntity` in Postgres before treating Graphiti entity matches as durable identity;
- use Graphiti search as candidate retrieval, then canonical filter through Postgres;
- do not trust Graphiti delete as immediate truth;
- keep Graphiti adapter idempotent;
- configure LLM and embedder providers explicitly, never rely on hidden defaults;
- set `GRAPHITI_TELEMETRY_ENABLED=false` in local/private deployments unless the operator opts in;
- expose backend capabilities because Neo4j, FalkorDB, Kuzu and Neptune-like backends may differ in search/index/delete behavior.

Adapter responsibilities:

```text
upsert_episode:
  call graphiti.add_episode(...)
  persist mapping episode_id -> graphiti_episode_uuid in Postgres metadata
  update ProjectionState graph/episode to indexed

upsert_fact:
  either add_triplet or add structured episode
  persist mapping fact_id -> graphiti edge/node ids when available
  update ProjectionMapping and ProjectionState

search_facts:
  graphiti.search_ or graphiti.search
  convert results to RetrievedMemory candidates
  include graph ids and possible fact ids

delete_fact/delete_episode:
  best-effort remove/deindex
  mark ProjectionState deleting/deleted or failed
  canonical status already hidden in Postgres
```

Open question for implementation spike:

- whether to use `add_episode` for all facts or `add_triplet` for manual/canonical facts.
- exact Graphiti delete/deindex guarantees per backend.
- telemetry opt-out should be verified in integration boot logs.

Recommended v1:

```text
episodes -> add_episode
manual canonical facts -> add_triplet where source/target are clear, otherwise structured episode
```

### Qdrant Adapter

Role:

- vector/RAG index for chunks and source text.

Use for:

- document chunks;
- transcript chunks;
- code snippets;
- semantic search;
- optional hybrid/sparse search later.

Do not use for:

- canonical status;
- permissions;
- fact lifecycle;
- audit.

Collections:

Option A:

```text
memory_chunks
```

with payload:

```text
space_id
profile_id
thread_id
document_id
episode_id
chunk_id
source_type
status_hint
created_at
valid_from
invalid_at
```

Option B:

```text
memory_chunks_{space_id}
```

Recommendation for v1: one collection with payload filters.

🎯 8   🛡️ 8   🧠 5
Why: simpler ops and enough isolation for local/server v1. Per-space collection can come later for huge tenants.

Required payload indexes:

```text
space_id
profile_id
thread_id
document_id
episode_id
chunk_id
source_type
status_hint
embedding_model
schema_version
```

Rules:

- create payload indexes before large imports;
- search/update/delete operations that filter on unindexed fields should fail fast in diagnostics/dev mode;
- adapter health must report missing payload indexes;
- never rely on payload filters alone for security, Postgres canonical authorization still wins.
- upsert/delete writes must update `ProjectionState` and `ProjectionMapping`;
- Qdrant point ids should be deterministic from canonical chunk id plus projection generation;
- collection schema/version changes mark affected projections stale before rebuild.

Qdrant deployment:

- local Docker in v1;
- remote Qdrant later;
- persistent volume required;
- never rely on in-memory Qdrant for durable memory;
- use Qdrant snapshots for vector backup/restore when running a server/container;
- include snapshot restore in disaster recovery tests before remote deployment.

Important note from spike:

- Cognee Qdrant community adapter source main targets Cognee `1.1.0`, but PyPI metadata previously showed drift risk.
- Do not depend on Cognee Qdrant adapter for our core.
- Write our own small Qdrant adapter against `VectorMemoryPort`.

### Embedding Adapter

Initial options:

1. OpenAI embeddings
   🎯 8   🛡️ 7   🧠 4
   Good quality, external cost/privacy.

2. Local fastembed/sentence-transformers
   🎯 7   🛡️ 8   🧠 6
   Good for local privacy, heavier runtime.

3. Noop/stub embedding for tests
   🎯 10   🛡️ 10   🧠 2
   Required for deterministic tests.

V1 should support:

```text
NoopEmbeddingAdapter
OpenAIEmbeddingAdapter
```

Local embedding can be v1.1.

### Classifier Adapter

Classifier decides:

- should this item be remembered;
- what profile/kind it belongs to;
- whether it is a fact, preference, decision, constraint, task, code pattern, meeting note;
- importance;
- confidence;
- conflict/supersede candidate.

V1 policy model:

```text
policy-gated async classification
manual/review/auto modes are domain policy, not adapter behavior
```

Pipeline:

```text
raw episode
  -> deterministic filters
  -> load effective MemoryPolicy
  -> classifier
  -> candidate facts
  -> policy decision
  -> MemorySuggestion or MemoryFact
```

Classifier output must be structured and side-effect free:

```text
candidate_text
kind
confidence
importance
source_refs
detected_entities
entity_resolution_confidence
evidence_grade
observed_at
valid_from
invalid_at
temporal_confidence
possible_conflicts
sensitivity_flags
recommended_action
```

Do not classify synchronously on hot path unless the user explicitly calls `remember_fact`.

## AI Provider Governance

All model calls must go through a governed provider path. This includes embeddings, classifier calls, reranking, summarization, OCR and Graphiti internal LLM/embedder usage.

Provider call envelope:

```text
request_id
space_id
profile_id
principal_id
purpose: embedding | classification | summarization | rerank | ocr | graph_indexing
provider
model
input_sensitivity
redaction_artifact_id?
prompt_template_id?
prompt_version?
output_schema_version?
token_budget
timeout_ms
idempotency_key
```

Rules:

- provider calls are denied by default when `MEMORY_ALLOW_EXTERNAL_AI=false`;
- `MemoryPolicy` must approve the specific purpose, not only "AI enabled";
- secret/restricted input requires local-only provider or approved redacted artifact;
- every prompt template and structured output schema is versioned;
- every classifier/reranker result stores provider, model, prompt version and schema version;
- retries must use the same idempotency key and must not duplicate suggestions/facts;
- provider failover cannot change privacy class or output schema silently;
- Graphiti must be configured with explicit LLM/embedder clients from the provider registry, never hidden defaults;
- hot prompt-time context path cannot perform slow model calls unless explicitly configured as a separate mode.

Structured output contract:

```text
schema_id
schema_version
purpose
json_schema
strict_validation: true
unknown_field_policy: ignore | reject
created_at
status: active | deprecated | disabled
```

Failure handling:

- schema validation failure creates safe diagnostic and no memory mutation;
- provider timeout returns retryable job failure for async work;
- provider outage degrades to source_chunk_only or suggestions depending on policy;
- repeated provider failures trip a circuit breaker per provider/purpose/space;
- circuit breaker never disables delete/forget/admin diagnostics.

Required tests:

- external model call is blocked when config or policy disallows it;
- redacted artifact is required for confidential external classification;
- classifier output with wrong schema does not create suggestions/facts;
- prompt version change requires eval fixture update;
- provider failover preserves privacy/purpose constraints;
- Graphiti adapter cannot boot with implicit external provider in local/private mode.

## Use Cases

### ValidateRuntimeConfigUseCase

Input:

```text
process_kind: api | worker | cli
deployment_mode
environment
raw_config_sources
```

Steps:

```text
load effective config by precedence
validate required auth, storage, provider and key settings
reject unsafe local defaults in team/remote mode
compute config hash and safe capability set
record RuntimeConfigSnapshot
return readiness state and safe diagnostics
```

Rules:

- runs before normal API routes and worker claims are enabled;
- does not print raw secrets or full env values;
- blocks startup when auth mode, schema version, migrations or provider policy are unsafe;
- allows read-only/admin diagnostics only when configured compatibility mode supports it.

### BootstrapLocalDeploymentUseCase

Input:

```text
deployment_id
bootstrap_token
owner_display_name
space_name
profile_name
requested_token_scopes
request_fingerprint_hash
```

Steps:

```text
load BootstrapState
verify deployment mode and one-time bootstrap token
create owner Principal
create default MemorySpace and owner SpaceMember
create default MemoryProfile and ProfileGrant
create default MemoryPolicy
create scoped local API token if requested
record audit event
lock bootstrap state
return token once and safe ids
```

Rules:

- valid only before the deployment is bootstrapped;
- repeated same in-flight bootstrap can replay safe result, but cannot mint extra owner tokens;
- token is returned once and stored only as hash;
- team/remote mode must use explicit auth gateway/JWT provisioning instead of local bootstrap defaults.

### PlanMigrationUseCase

Input:

```text
target_version
requested_phase?
dry_run: true | false
```

Steps:

```text
load current schema, contract, config and compatibility windows
inspect active operations, workers, outbox jobs and projection drift
compute required expand/backfill/dual_read/contract_switch/cleanup phases
estimate affected rows, indexes, contracts and SDK windows
return safe plan with blockers and verification commands
```

Rules:

- does not mutate in dry-run mode;
- blocks destructive cleanup when compatibility window is active;
- blocks prompt-impacting switch when old/new context fixtures disagree;
- reports counts and ids only by default.

### RunDataBackfillUseCase

Input:

```text
migration_run_id
backfill_job_id
chunk_size
resume_cursor?
```

Steps:

```text
claim migration/backfill work
load stable chunk by canonical ordering
re-check status, tombstone, legal hold and policy
apply idempotent transformation for migration version
record progress, skipped and blocked counts
enqueue projection jobs when needed
```

Rules:

- safe to retry after crash;
- never trusts derived indexes as source data;
- releases or pauses when interactive capacity is under pressure;
- failed chunk does not advance resume cursor.

### RegisterWorkerInstanceUseCase

Input:

```text
deployment_id
process_kind
worker_group
binary_version
supported_job_versions[]
config_snapshot_id
```

Steps:

```text
validate runtime config snapshot
register WorkerInstance as starting
verify migration/compatibility state allows this binary
mark active or quarantined
return worker id and heartbeat interval
```

Rules:

- old binary can remain active only for compatible job versions;
- worker cannot become active when deployment is locked/misconfigured for its work class;
- worker registration is safe to repeat after process restart because ids are new per process.

### ClaimWorkerBatchUseCase

Input:

```text
worker_instance_id
worker_group
workload_classes[]
max_items
shutdown_deadline?
```

Steps:

```text
verify worker active and config-compatible
respect migration, quota and admission constraints
claim outbox/backfill/scheduled work with WorkerLease
return bounded batch and lease metadata
```

Rules:

- no claim after worker enters draining state;
- unsupported job schema remains pending/blocked with diagnostics;
- claim order honors workload priority and fairness keys;
- every claimed item has idempotency/recovery contract.

### RunScheduledTaskUseCase

Input:

```text
worker_instance_id
task_key
due_at
```

Steps:

```text
load ScheduledTask
acquire singleton lease when required
create or reuse ClientOperation/job by idempotency key
record task run
enqueue normal work
release lease or mark failed with safe details
```

Rules:

- scheduler does not perform heavy work inline;
- repeated tick creates one logical operation for the same task window;
- disabled task does not enqueue work even if old scheduler wakes up.

### GracefulWorkerShutdownUseCase

Input:

```text
worker_instance_id
shutdown_reason
deadline
```

Steps:

```text
mark worker draining
stop new claims
checkpoint or finish current safe chunk
release leases that did not start external side effects
mark remaining leases resumable or let them expire
mark worker stopped
```

Rules:

- shutdown is best-effort and must be safe under process kill;
- operation status must remain client-safe;
- unfinished external adapter side effects require reconciliation before retry.

### ResolveIdempotencyUseCase

Input:

```text
space_id
principal_id
idempotency_key?
request_method
request_path
request_fingerprint_hash
operation_type
```

Steps:

```text
if no idempotency key, continue with endpoint-specific safeguards
load existing IdempotencyRecord
if same key and same fingerprint, return stored snapshot or operation status
if same key and different fingerprint, return memory.conflict
create processing IdempotencyRecord before side effects
create ClientOperation when endpoint is mutating or long-running
```

Rules:

- called at the start of every mutating API endpoint;
- request fingerprint excludes volatile headers and includes normalized body;
- response snapshot is saved before returning successful result;
- processing replay does not start another operation.

### UpdateOperationStatusUseCase

Input:

```text
operation_id
status
progress_current?
progress_total?
safe_status?
safe_error?
target_type?
target_id?
result_snapshot?
```

Steps:

```text
load ClientOperation
validate lifecycle transition
persist progress/status/result snapshot
publish safe operation update event if subscriptions allow
expire idempotency/result snapshots after retention window
```

Rules:

- internal worker errors are summarized into safe status/errors;
- operation can succeed while projection state is still pending;
- cancelled operation must state whether canonical target was committed;
- status update is idempotent by operation id and target version.

### CreateProfileUseCase

Input:

```text
space_id
name
description
retention policy
```

Output:

```text
MemoryProfileDTO
```

Rules:

- profile name unique per space;
- default retention is conservative;
- creates no Graphiti/Qdrant resources until first write unless adapter requires explicit setup.

### ResolveEntityUseCase

Input:

```text
space_id
profile_id
entity_text
entity_type?
scope?
source_refs?
allow_create: true | false
```

Steps:

```text
normalize entity text
load aliases and scoped candidates
score exact/alias/model candidates
if one high-confidence match exists, return canonical entity
if ambiguous, create review suggestion or return unresolved candidate
if no match and allow_create, create MemoryEntity
write audit for merge/split/create decisions
```

Return:

```text
entity_id?
entity_key
resolution_status: resolved | created | ambiguous | unresolved
confidence
candidate_entity_ids[]
```

Rules:

- Graphiti entity matches are inputs to resolution, not final identity;
- ambiguous entity resolution blocks auto-promotion by default;
- merge and split require reviewer/admin grant unless policy explicitly allows high-confidence automatic aliases;
- entity decisions are profile-scoped unless a space-level ontology/entity registry is explicitly introduced later.

### ResolveCodeScopeUseCase

Input:

```text
space_id
repo_hint?
remote_url?
local_path?
branch?
commit_sha?
pull_request_id?
file_path?
symbol_name?
line_start?
line_end?
content_hash?
```

Steps:

```text
resolve repository identity without trusting local path as canonical
normalize branch/commit/PR scope
create or update CodeReference when file/symbol evidence exists
detect dirty/unknown worktree state from connector metadata
return CodeScope and CodeReference ids
```

Rules:

- missing repo id lowers relevance and blocks global promotion by default;
- dirty worktree scope is local/thread-scoped unless explicit approval promotes it;
- code reference resolution is best effort and must not block canonical fact creation when source refs are present.

### RememberFactUseCase

Input:

```text
space_id
profile_id
thread_id?
text
kind?
entity_id?
entity_key?
code_scope?
code_reference_ids?
source_refs?
source_provenance?
confidence?
importance?
valid_from?
observed_at?
invalid_at?
```

Steps:

```text
resolve idempotency and create ClientOperation if needed
validate profile
normalize text
create or validate SourceProvenance
build WriteIntent for explicit fact
run WriteAdmissionPort and persist MemoryWriteAdmission
return source-only, suggestion, quarantine or rejection if admission does not allow active fact
resolve ontology kind
resolve entity if provided or detected
score evidence and confidence
apply temporal semantics
dedupe candidate
detect conflict/currentness candidates
create fact in Postgres
append source refs
create FactCurrencyState and optional FactConflictRecord
write audit
create ProjectionState pending for required graph/vector projections
enqueue graph upsert
optionally enqueue vector snippet upsert
enqueue duplicate detection/consolidation if policy allows
commit
save operation result snapshot
```

Rules:

- explicit trusted human facts can become active only after write admission allows active fact creation;
- medium/low trust explicit writes can become suggestions or source-only evidence according to policy;
- rejected/quarantined writes still return a typed operation result without indexing into Graphiti/Qdrant.

Return:

```text
fact_id
status
version
indexing_status: pending
entity_resolution_status
confidence_explanation
currency_status
conflict_ids[]
```

### UpdateFactUseCase

Input:

```text
fact_id
expected_version
new_text
source_refs
source_provenance?
reason
```

Steps:

```text
resolve idempotency and load/create ClientOperation
load fact
check expected_version
create or validate SourceProvenance
build WriteIntent for update/supersede attempt
run WriteAdmissionPort before currency mutation
evaluate currency/conflict policy
create SupersessionDecision or FactConflictRecord
create new fact version when allowed
mark old active fact as superseded or disputed according to decision
record relation supersedes or contradicts
create source refs
audit
mark previous ProjectionState stale/deleting as needed
enqueue graph update/deindex old edge
commit
save operation result snapshot
```

Return:

```text
new_fact_id or fact_id + version
old_status: superseded | disputed | unchanged
currency_status
conflict_id?
```

### ResolveFactConflictUseCase

Input:

```text
conflict_id
resolution:
  keep_existing
  supersede_existing
  keep_both_scoped
  mark_disputed
  mark_historical
  reject_candidate
  split_entity
review_note?
expected_conflict_version
```

Steps:

```text
authorize reviewer/admin or explicit trusted correction policy
load conflict and affected facts
check conflict version
validate source refs, temporal fields and entity scope
create SupersessionDecision when needed
update FactCurrencyState records
update MemoryFact status only when lifecycle changes
append audit
mark projections/cache/current sets stale
enqueue recompute_current_fact_set and cache invalidation
commit
```

Return:

```text
conflict_id
status
resolution
affected_fact_ids[]
current_fact_group_id
```

### ForgetFactUseCase

Input:

```text
fact_id
reason
scope: only_fact | fact_and_sources
```

Steps:

```text
resolve idempotency and load/create ClientOperation
mark fact deleted in Postgres
create tombstone
audit
mark related ProjectionState deleting
enqueue graph delete
enqueue vector delete if needed
commit
save operation result snapshot
```

Guarantee:

- API search immediately hides deleted fact.
- Physical deindex is eventually consistent.

### ConfigureMemoryPolicyUseCase

Input:

```text
space_id
profile_id
expected_version
patch:
  mode?
  allowed_source_types?
  blocked_source_types?
  auto_promote_kinds?
  review_required_kinds?
  thresholds?
  external_processing?
```

Steps:

```text
load current policy
check expected_version
validate transitions and safety constraints
persist new policy version
audit
commit
```

Rules:

- policy changes affect new ingestion immediately;
- pending async jobs must re-check current policy before promotion;
- diagnostics must show both current policy and policy snapshot used by old jobs.

### ApplyRetentionPolicyUseCase

Input:

```text
space_id
rule_id?
profile_id?
dry_run: true | false
requested_by
```

Steps:

```text
authorize admin or retention action
load effective retention rules
find due targets through canonical repositories
check legal holds and tombstones
produce dry-run report or create retention job
for execution, apply archive/disable/delete through normal lifecycle use cases
enqueue derived deindex/object cleanup events
write audit and retention job status
```

Rules:

- dry-run is required before hard-delete retention in team/remote mode;
- legal hold blocks hard-delete but can allow normal retrieval hiding through disable/tombstone;
- retention execution never deletes audit chain entries;
- retention can be paused/cancelled between batches.

### ManageLegalHoldUseCase

Input:

```text
space_id
target_type
target_id
action: create | release | expire
reason
expires_at?
```

Steps:

```text
authorize admin/security action
create/release/expire hold
audit high-value event
publish cache invalidation event
schedule retention re-evaluation when hold is released
```

Rules:

- legal hold state is checked by forget/hard-delete/export/retention use cases;
- release does not automatically hard-delete held data;
- hold metadata is production-safe and should not include raw sensitive text.

### BuildRepositoryScopeUseCase

Input:

```text
space_id
profile_ids?
principal_id?
operation_id?
worker_id?
purpose
include_deleted?
include_superseded?
maintenance_override_id?
```

Steps:

```text
resolve principal or worker identity
load membership, grants, policy versions and override when present
validate that requested scope fits the use-case purpose
create RepositoryScope
bind scope to UnitOfWork transaction
return ScopedRepositoryContext
```

Rules:

- called before repository reads/writes for scoped memory rows;
- user-facing reads still build `ReadScope` and `VisibilityProof` on top;
- worker jobs create scope from job payload plus current policy/grant state, not from stale enqueue-time assumptions;
- broad operations require `MaintenanceScopeOverride` and dry-run evidence before mutation;
- bootstrap/deployment metadata exceptions are explicit and covered by adapter tests.

### ResolveProcessingLocationUseCase

Input:

```text
space_id
profile_id?
principal_id?
purpose
sensitivity
requested_region_id?
provider?
provider_region?
artifact_id?
storage_object_id?
operation_id?
```

Steps:

```text
load MemorySpace home region and effective DataResidencyPolicy
load effective MemoryPolicy when profile or source kind is known
resolve requested storage/provider/backup/export region
compare purpose, sensitivity and provider region against allowed policy
produce ProcessingLocationDecision
audit reject, local_only, require_redaction and reviewed cross-region decisions
return allow, require_redaction, local_only, reject or require_review
```

Rules:

- called before raw storage placement, external AI, embedding, OCR, rerank, backup, export, import and sync apply;
- local Docker can return a single `local` allow decision without adding cloud complexity;
- remote/team mode must fail closed when provider region is unknown for sensitive or restricted data;
- residency denial must not reveal raw memory text or forbidden profile existence.

### RunParserSandboxUseCase

Input:

```text
space_id
profile_id
document_id
storage_object_id
mime_type
parser_family
requested_parser?
```

Steps:

```text
load document, StorageObject and effective ParserSandboxPolicy
verify parser dependency is enabled and release attestation is acceptable
prepare temp execution environment with network denied by default
run parser through ParserSandboxPort with CPU/memory/time/output limits
record ParserExecutionRun
return extracted text reference, partial result, quarantine or safe failure
```

Rules:

- parser execution never writes facts directly;
- parser output still passes write admission, redaction and residency checks before indexing/classification;
- parser failure keeps the raw document available only under normal authorization and policy;
- parser network or macro/script attempt is a security signal and quarantines the candidate by default.

### EvaluateReleaseArtifactUseCase

Input:

```text
release_version
artifact_type
artifact_hash
lockfile_refs[]
sbom_ref?
target_deployment_mode: local | remote | team
```

Steps:

```text
build or load DependencyInventory
run vulnerability, malware and license scans
evaluate LicensePolicy and active waivers
create ReleaseArtifactAttestation
return passed, warning, blocked or waived
```

Rules:

- local dev can proceed with warning when configured;
- remote/team release blocks on critical/high findings unless an unexpired scoped waiver exists;
- waiver records include owner/admin approval, reason, expiry and exact package/version/finding scope;
- attestation status is exposed through capabilities and diagnostics.

### AdmitWorkUseCase

Input:

```text
space_id
profile_id?
principal_id?
connector_id?
workload_class
resource_estimates:
  resource_type
  estimated_quantity
purpose?
provider?
model_id?
idempotency_key
```

Steps:

```text
load current policy and effective quota rules
check workload priority and system health
compute fairness key from space/profile/principal/connector/workload
reserve capacity for expensive resources
return AdmissionDecision
audit hard rejections and degraded modes
```

Rules:

- called before provider calls, large extraction, embedding, graph/vector indexing, sync apply and consolidation;
- interactive context can degrade to cached_context_only instead of waiting behind background work;
- background work can be queued later or degraded to source_chunk_only when policy allows;
- idempotent retries return the same reservation/decision for the same logical work.

### RecordUsageUseCase

Input:

```text
reservation_id?
space_id
profile_id?
principal_id?
connector_id?
resource_type
quantity
unit
provider?
model_id?
purpose?
idempotency_key
```

Steps:

```text
validate idempotency and matching reservation
append UsageRecord
commit or release reservation
update diagnostics counters
emit safe usage event if subscriptions allow operational events
```

Rules:

- usage recording never logs raw prompt, document or memory text;
- missing reservation is allowed only for cheap metadata operations or compatibility imports;
- overage is recorded and surfaced in diagnostics;
- failed provider calls record attempted usage only when provider actually charged or consumed quota.

### ClassifyEpisodeUseCase

Input:

```text
episode_id
policy_snapshot_version
```

Steps:

```text
load episode
load current effective policy
stop if episode/profile is deleted or disabled
apply deterministic safety filters
call classifier only if policy allows classification
dedupe candidates
build WriteIntent for each candidate
run WriteAdmissionPort for each candidate before suggestion or fact creation
detect conflicts
apply policy decision per candidate
create MemorySuggestion or MemoryFact
enqueue derived index jobs for approved/promoted facts
enqueue consolidation/dedupe job when policy allows
audit
commit
```

Policy decision outcomes:

```text
drop
keep_source_chunk_only
create_suggestion
auto_promote_fact
block_sensitive
needs_review_for_conflict
```

Rules:

- classifier output is never trusted directly, even when generated from trusted source text;
- candidates rejected or quarantined by write admission do not become suggestions, facts or derived index payloads;
- auto-promote can run only after write admission, confidence gates, source refs and fact currency checks all pass.

### ReviewMemorySuggestionUseCase

Input:

```text
suggestion_id
action: approve | reject | supersede | expire
edited_text?
target_fact_id?
reason
```

Steps:

```text
load suggestion
check profile authorization
build WriteIntent for approval/edit action
run WriteAdmissionPort for approved or edited text
if approve, create MemoryFact from suggestion
if reject, mark rejected and audit
if supersede, link to fact/update flow
enqueue graph/vector indexing only for approved fact
commit
```

Guarantee:

- pending/rejected suggestions never appear in normal context bundles.

### ConsolidateMemoryUseCase

Input:

```text
space_id
profile_id?
mode: dedupe | cluster | digest | refresh_digest | stale_review
scope:
  thread_id?
  document_id?
  entity_id?
  code_scope?
dry_run: true | false
requested_by
```

Steps:

```text
resolve idempotency and create/update ClientOperation for manual run
authorize read plus consolidation action
load effective MemoryPolicy
select canonical candidates from Postgres
exclude deleted, disabled, held or unauthorized sources
score exact duplicate, semantic similarity and temporal overlap
create dry-run candidate report
if allowed, create or update MemoryCluster metadata
if digest mode, generate MemoryDigest through provider governance
mark stale digests affected by source updates/deletes
audit and enqueue cache invalidation events
commit
save operation result snapshot when request was API-triggered
```

Rules:

- consolidation cannot mutate active fact text directly;
- duplicate facts become clusters or review suggestions before merge/delete;
- digest generation must preserve source refs and redaction versions;
- low confidence or contradictory candidates become review items, not summaries;
- consolidation runs in background workload queues, never on interactive context path.

### RefreshMemoryDigestUseCase

Input:

```text
digest_id
reason: source_changed | policy_changed | redaction_changed | scheduled_refresh | reviewer_request
dry_run: true | false
```

Steps:

```text
resolve idempotency and create ClientOperation when API-triggered
load digest and source refs
check every source is still visible and allowed
compare source versions, policy version and redaction version
mark stale, supersede or regenerate digest
audit model/prompt/redaction versions
commit
save operation result snapshot
```

Rules:

- missing source ref marks digest stale;
- hard-deleted source deletes or disables digest according to policy;
- regenerated digest supersedes the old digest instead of mutating it blindly;
- digest refresh never raises canonical fact confidence by itself.

### IngestEpisodeUseCase

Input:

```text
space_id
profile_id
thread_id
source_type
source_external_id
text
occurred_at
metadata
```

Steps:

```text
resolve idempotency and create ClientOperation
normalize
load effective MemoryPolicy
reject/drop early if mode is disabled
idempotency check
create or validate SourceProvenance
build WriteIntent for episode/source chunk
run WriteAdmissionPort before materializing prompt-visible memory
create MemoryEpisode
create optional chunks for retrieval
create ProjectionState pending for episode/chunk projections
enqueue vector upsert chunks if policy allows source chunks
enqueue graphiti add_episode if policy allows graph episode indexing
enqueue classification job if policy allows classification
enqueue consolidation/digest refresh job if policy allows and source is important enough
commit
save accepted operation snapshot with indexing/classification status
```

Rules:

- episode text can be stored as source evidence even when active fact extraction is blocked, if policy allows source-only storage;
- quarantined episodes are excluded from normal context/search and from classifier jobs until released;
- assistant/agent output episodes default to low-trust derived evidence.

### IngestDocumentUseCase

Input:

```text
space_id
profile_id
thread_id?
file
filename
mime_type
metadata
```

Steps:

```text
resolve idempotency and create ClientOperation
resolve or complete UploadSession
verify StorageObject checksum, size, mime and policy
resolve storage region and DataResidencyPolicy for raw file and extracted text
compute or validate content_hash
dedupe document
load effective MemoryPolicy
select ParserSandboxPolicy
run RunParserSandboxUseCase for extraction/OCR/archive handling
build WriteIntent for document/source chunks
run WriteAdmissionPort and poisoning detection before chunks are prompt-visible
resolve ProcessingLocationDecision before external OCR, embedding, classification or managed storage
chunk
create document + chunks in Postgres
create ProjectionState pending for chunk projections
enqueue qdrant chunk upsert if policy allows source chunks
enqueue summarization/fact extraction if policy allows classification
commit
save accepted operation snapshot with document id and processing status
```

Do not:

- push full file into Graphiti;
- keep only embeddings without raw source;
- block API request until all facts are extracted.
- trust object storage key without `StorageObject` verification.

Rules:

- document text with prompt-injection instructions can become quoted source evidence but not active memory;
- write admission and residency checks run before Graphiti/Qdrant indexing and before classifier extraction;
- if residency allows local storage but blocks external processing, document remains stored with derived processing disabled or local-only.
- parser sandbox failure creates safe diagnostics and does not create active facts or embeddings.

### CreateUploadSessionUseCase

Input:

```text
space_id
profile_id?
purpose
expected_size_bytes?
expected_content_hash?
mime_type?
```

Steps:

```text
authorize ingest/import/export purpose
check quota and sensitivity policy
resolve DataResidencyPolicy and target storage region
create StorageObject in pending_upload state
create UploadSession with expiry
create upload URL or upload instructions through ObjectStoragePort
return session id and safe upload target
```

Rules:

- upload target is scoped and short-lived;
- session does not create a trusted document/artifact until completed;
- raw object key is never returned as durable public identifier.

### CompleteUploadSessionUseCase

Input:

```text
upload_session_id
provided_checksum
provided_size_bytes
provided_mime_type?
```

Steps:

```text
load UploadSession and StorageObject
verify principal/scope
verify object exists and checksum matches
validate mime, size, quota and parser policy
verify StorageObject region still satisfies current residency policy
mark StorageObject verified or quarantined
complete UploadSession
return storage_object_id and next allowed action
```

Rules:

- completion is idempotent for the same uploaded object;
- mismatch never creates active document/import artifact;
- quarantined object is not visible to search/context.

### PrepareArtifactDownloadUseCase

Input:

```text
artifact_id
principal_id
purpose
```

Steps:

```text
load MemoryArtifact and StorageObject
re-check current authorization, sensitivity and legal hold state
verify artifact download does not violate current residency/export policy
verify artifact not expired/revoked/deleted
create short-lived download URL or streaming response
record download count and audit when required
```

Rules:

- artifact URL is not authorization;
- revoked grant blocks download even if URL was previously issued;
- expired artifact returns typed not-found/expired behavior without leaking object key.

### SearchMemoryUseCase

Input:

```text
space_id
profile_ids
query
types?
thread_ids?
as_of?
temporal_mode: current | as_of | history | all
include_historical?
limit
include_sources
```

Steps:

```text
query Graphiti for facts/entities
query Qdrant for chunks
merge candidates
canonical filter through Postgres
apply temporal filter
apply entity disambiguation
dedupe
rerank
return RetrievedMemory DTOs
```

### BuildContextUseCase

Input:

```text
space_id
profile_ids
query
token_budget
mode: answer | coding_agent | interview | meeting
as_of?
include_historical: false by default
```

Steps:

```text
search
score
label evidence grade and temporal status
bucket by memory kind
pack under budget
include source refs
emit diagnostics
```

Output:

```text
ContextBundle
  sections
  memories
  source_refs
  diagnostics
```

### RegisterConnectorUseCase

Input:

```text
space_id
source_app
display_name
allowed_profiles
allowed_actions
default_policy_id?
webhook_enabled?
```

Steps:

```text
authorize admin/integration action
create ConnectorInstallation
create scoped principal/token if requested
create webhook secret if requested
write audit event
return connector id, token once, webhook config
```

Rules:

- connector token is shown once and then stored only as hash;
- connector actions cannot exceed the installer principal's grants;
- webhook secret rotation must not change connector id or provenance.

### IngestConnectorEventUseCase

Input:

```text
connector_id
source_stream
source_external_id
external_sequence?
event_type
payload
signature?
```

Steps:

```text
verify connector active and token/signature
detect replay by external id/sequence/window
load connector sync state
normalize SourceProvenance
apply MemoryPolicy and sensitivity gates
build WriteIntent from connector event
run WriteAdmissionPort before translating into memory writes
resolve ProcessingLocationDecision before large payload storage or external processing
ingest episode/document/fact request through normal use cases
update sync state checkpoint
publish canonical events
```

Rules:

- forged/unsigned webhook events are rejected before parsing payload;
- duplicate webhook/backfill events return stable accepted/deduped result;
- external delete/update is translated into canonical use case call with audit;
- connector event ingestion never writes directly to Graphiti/Qdrant.
- connector payloads cannot self-approve generated facts or bypass residency/write-admission checks.

### PublishMemoryEventUseCase

Input:

```text
event_type
aggregate_type
aggregate_id
aggregate_version
space_id
profile_id?
```

Steps:

```text
append canonical event after transaction commit
fan out to subscriptions asynchronously
sign webhook delivery when configured
record delivery attempt and cursor
```

Rules:

- event publication happens after canonical commit;
- event payloads are safe by default and used for invalidation/refetch;
- delivery is at-least-once and ordered by canonical commit position per space;
- failed delivery cannot roll back canonical write.

### RebuildProjectionUseCase

Input:

```text
space_id
profile_id?
projection_type: graph | vector | search_metadata | all
adapter_name?
mode: rebuild | verify | deindex | migrate_generation
dry_run: true | false
requested_by
```

Steps:

```text
resolve idempotency and create ClientOperation
authorize admin/maintenance action
run admission check for maintenance workload
create ProjectionRebuildJob with source watermark and target generation
iterate canonical records through repositories
write adapter objects through ProjectionAdminPort or normal adapter ports
upsert ProjectionState and ProjectionMapping
verify counts, mappings and canonical filters
activate generation only after verification or explicit admin decision
audit and publish safe diagnostics event
save operation result snapshot with rebuild job id and generation
```

Rules:

- rebuild never uses Graphiti/Qdrant as source of truth;
- dry-run reports affected counts and estimated cost before writing;
- failed rebuild does not replace active generation;
- concurrent writes after watermark continue through normal outbox;
- rebuild can pause, resume and cancel without mutating canonical records.

### VerifyProjectionHealthUseCase

Input:

```text
space_id
profile_id?
projection_type?
adapter_name?
sample_size?
```

Steps:

```text
load projection states and mappings
sample canonical records by status/version
check adapter health/capabilities
verify mapped adapter objects exist where safe
report drift, stale states, missing mappings and orphan mappings
```

Rules:

- verification reports ids/counts only by default;
- health check can run without full adapter scan in prompt-time path;
- detected drift schedules rebuild/deindex jobs, not direct mutation.

### PrepareSyncChangeSetUseCase

Future-gated use case. It can be implemented after v1 without changing core ids or lifecycle semantics.

Input:

```text
space_id
peer_id
from_cursor
to_cursor?
profile_filters?
include_raw_documents: false by default
```

Steps:

```text
authorize peer and principal
load peer, checkpoint and capabilities
read canonical events after from_cursor
include tombstones before updates for the same aggregate
filter by profile grants and export policy
resolve ProcessingLocationDecision for sync bundle transfer
create SyncChangeSet metadata
return safe counts and opaque change_set_id
```

Rules:

- no raw text is included unless export policy and sensitivity allow it;
- legal hold and retention rules are represented as blockers, not ignored;
- change set preparation must be deterministic for the same cursor window;
- cursor expiry returns a typed conflict and suggests export/import resync.

### ApplySyncChangeSetUseCase

Future-gated use case for applying a dry-run-approved change set.

Input:

```text
space_id
peer_id
change_set_id
mode: dry_run | apply
resolution_policy: conservative | prefer_local | prefer_incoming | review_only
```

Steps:

```text
authorize sync apply
validate peer and change set signature/checksum
run import-like validation
resolve profile ids and ontology versions
check tombstones, legal holds and policies
resolve ProcessingLocationDecision for destination apply
write normal use-case commands or create SyncConflict records
update checkpoint only after successful canonical commit
append audit and event records
```

Rules:

- `dry_run` is mandatory before `apply` for remote/team mode;
- unresolved conflicts create `SyncConflict`, not silent active mutations;
- apply is idempotent by `change_set_id`, aggregate id and aggregate version;
- derived indexes are updated only through normal outbox jobs after canonical commit.

## API Contract

Base:

```text
/v1
```

Common response envelope:

```json
{
  "data": {},
  "meta": {
    "request_id": "req_123",
    "server_time": "2026-05-24T12:00:00Z",
    "api_version": "v1"
  }
}
```

Common error envelope:

```json
{
  "error": {
    "code": "memory.conflict",
    "message": "Conflict",
    "retryable": false,
    "safe_details": {
      "expected_version": 3,
      "actual_version": 4
    }
  },
  "meta": {
    "request_id": "req_123"
  }
}
```

Typed error codes:

```text
memory.validation
memory.unauthorized
memory.forbidden
memory.not_found
memory.conflict
memory.quota_exceeded
memory.policy_blocked
memory.sensitive_data_blocked
memory.residency_blocked
memory.unsupported
memory.index_unavailable
memory.unavailable
memory.provider_unavailable
memory.timeout
memory.operation_cancelled
memory.internal
```

Rules:

- all errors are production-safe by default;
- `retryable` is explicit;
- clients should not parse human messages for behavior;
- every response includes `request_id`;
- every mutating endpoint accepts an optional `Idempotency-Key` header;
- long-running mutating endpoints return or expose `operation_id`;
- list endpoints use cursor pagination, not offset pagination.

Cursor pagination:

```json
{
  "data": [],
  "meta": {
    "next_cursor": "cursor_abc",
    "has_more": true
  }
}
```

Capabilities:

```text
GET /v1/capabilities
```

Must return:

```text
api_version
schema_version
contract_schema_versions
min_supported_client_versions
enabled_adapters
supported_policy_modes
supported_currency_resolution_modes
supported_write_admission_modes
supported_embedding_models
supported_ai_purposes
supported_regions
supported_residency_policy_modes
provider_modes
prompt_schema_versions
redaction_versions
supported_connector_apps
supported_event_types
event_delivery_modes
supported_cache_kinds
cache_freshness_contract_version
repository_scope_contract_version
supply_chain_attestation_contract_version
supported_consolidation_modes
supported_quota_resources
supported_projection_types
active_projection_generations
supports_backup_restore
backup_manifest_contract_version
prompt_path_slo_contract_version
supported_context_degradation_modes
supports_legacy_client_routes
supports_export
supports_event_cursor
supports_sync_exchange
limits
```

Bootstrap and config:

```text
GET  /v1/bootstrap/status
POST /v1/bootstrap/local-init
GET  /v1/config/status
```

Rules:

- bootstrap status is production-safe and reveals only required, complete, locked or misconfigured state;
- local init works only for uninitialized local/private deployments with a valid one-time setup token;
- team/remote deployments use explicit auth/JWT/gateway provisioning, not local init defaults;
- config status returns hashes, versions, modes and feature flags, never raw secrets or env values.

Migration and upgrade diagnostics:

```text
GET  /v1/admin/migrations
GET  /v1/admin/migrations/{migration_run_id}
POST /v1/admin/migrations/{migration_run_id}/pause
POST /v1/admin/migrations/{migration_run_id}/resume
GET  /v1/admin/compatibility-windows
```

Rules:

- admin migration endpoints expose state, phases, blockers and safe counts;
- mutation endpoints require admin/maintenance grant and audit;
- normal users receive degraded/maintenance status only through capabilities/readiness;
- migration endpoints never expose raw memory text.

Worker and scheduler diagnostics:

```text
GET  /v1/admin/workers
GET  /v1/admin/workers/{worker_id}
POST /v1/admin/workers/{worker_id}/drain
GET  /v1/admin/worker-leases
GET  /v1/admin/scheduled-tasks
POST /v1/admin/scheduled-tasks/{task_key}/run
```

Rules:

- worker diagnostics are admin/maintenance only;
- responses expose ids, versions, status, heartbeat age, lease counts and safe errors;
- manual task run still uses singleton lease and normal idempotency;
- drain stops new claims but does not kill the process directly.

Cache diagnostics:

```text
GET  /v1/admin/cache
GET  /v1/admin/cache/{cache_entry_id}
POST /v1/admin/cache/invalidate
POST /v1/admin/cache/purge-expired
```

Rules:

- cache diagnostics are admin/maintenance only;
- responses expose keys, dimensions, payload hashes, freshness state and safe counts, not raw private text;
- manual invalidation requires audit and must use the same `InvalidateMemoryCacheUseCase` as automatic invalidation;
- purge deletes derived cache payloads only and cannot delete canonical facts, documents, chunks or tombstones.

Access/visibility diagnostics:

```text
GET /v1/admin/access/read-audit
GET /v1/admin/access/visibility-proofs/{request_id}
GET /v1/admin/access/query-scope-proofs
GET /v1/admin/access/query-scope-proofs/{proof_id}
GET /v1/admin/access/maintenance-overrides
POST /v1/admin/access/maintenance-overrides
POST /v1/admin/access/check
```

Rules:

- access diagnostics are admin/security only;
- default responses expose denied counts, purpose, safe reason codes and predicate/proof hashes, not raw memory text;
- raw debug access requires explicit debug grant and audit;
- `check` can explain whether a principal would see a record without returning the record content.
- query-scope proof diagnostics expose repository method, table family, operation type and filter flags, not raw SQL;
- maintenance overrides require dry-run count, expiry, reason code and explicit audit.

Write admission diagnostics:

```text
GET /v1/admin/write-admissions
GET /v1/admin/write-admissions/{admission_id}
GET /v1/admin/quarantined-candidates
POST /v1/admin/quarantined-candidates/{candidate_id}/release
POST /v1/admin/quarantined-candidates/{candidate_id}/reject
```

Rules:

- write admission diagnostics are reviewer/admin only;
- responses expose decision, safe reasons, detector versions and source ids, not full malicious payload;
- releasing quarantined candidate re-runs current policy and creates audit;
- rejection can keep minimal safe metadata for abuse/rate-limit diagnostics.

Residency diagnostics:

```text
GET /v1/admin/regions
GET /v1/admin/residency-policies
GET /v1/admin/processing-location-decisions
GET /v1/admin/processing-location-decisions/{decision_id}
POST /v1/admin/cross-region-transfer-requests
POST /v1/admin/cross-region-transfer-requests/{request_id}/approve
POST /v1/admin/cross-region-transfer-requests/{request_id}/reject
```

Rules:

- residency diagnostics are admin/security only;
- responses expose region ids, provider region, purpose, decision and safe reason codes, not raw memory text;
- cross-region approvals expire and never bypass auth, legal hold, sensitivity or write admission;
- `check` style dry-run must be available before a backup/export/import/sync operation mutates data.

Supply-chain and parser diagnostics:

```text
GET /v1/admin/supply-chain/inventory
GET /v1/admin/supply-chain/findings
GET /v1/admin/supply-chain/attestations
POST /v1/admin/supply-chain/evaluate-release
GET /v1/admin/parser-runs
GET /v1/admin/parser-runs/{parser_run_id}
GET /v1/admin/parser-sandbox-policies
PATCH /v1/admin/parser-sandbox-policies/{policy_id}
```

Rules:

- supply-chain diagnostics are admin/security only;
- findings expose package/version/severity/source id and safe summary, not private source code or secrets;
- parser diagnostics expose parser name/version/status/resource outcome and safe error, not raw document text;
- release evaluation can run in dry-run mode for local development and blocks remote/team release on configured findings.

Prompt-path diagnostics:

```text
GET /v1/admin/prompt-path/runs
GET /v1/admin/prompt-path/runs/{prompt_path_run_id}
GET /v1/admin/prompt-path/slo
```

Rules:

- prompt-path diagnostics expose request class, stage timings, timeout counts and degradation decisions;
- diagnostics never include raw prompt, raw memory text or hidden record ids by default;
- per-stage latency histograms are enough for SLO tuning without expensive full traces;
- admin can inspect failed/degraded context runs by safe ids and reason codes.

Backup and restore diagnostics:

```text
GET  /v1/admin/backups/policies
POST /v1/admin/backups/policies
POST /v1/admin/backups/runs
GET  /v1/admin/backups/runs/{backup_run_id}
GET  /v1/admin/backups/manifests/{manifest_id}
POST /v1/admin/restores/validate
POST /v1/admin/restores/apply
GET  /v1/admin/restores/{restore_run_id}
```

Rules:

- backup/restore endpoints are admin/maintenance only;
- backup artifacts and manifests are authorized through `MemoryArtifact` and current grants;
- restore apply requires prior validation report, explicit confirmation and audit;
- responses expose safe counts, hashes, ids and blockers, not raw memory text.

Ontology:

```text
GET    /v1/ontology
GET    /v1/ontology/history
```

Profiles:

```text
POST   /v1/spaces
GET    /v1/spaces
POST   /v1/profiles
GET    /v1/profiles
PATCH  /v1/profiles/{profile_id}
DELETE /v1/profiles/{profile_id}
```

Policies:

```text
GET    /v1/profiles/{profile_id}/policy
PATCH  /v1/profiles/{profile_id}/policy
GET    /v1/policies/{policy_id}/history
```

Retention and holds:

```text
GET    /v1/retention-rules
POST   /v1/retention-rules
PATCH  /v1/retention-rules/{rule_id}
POST   /v1/retention-rules/{rule_id}/dry-run
POST   /v1/retention-rules/{rule_id}/apply
GET    /v1/retention-jobs/{job_id}
POST   /v1/legal-holds
GET    /v1/legal-holds
POST   /v1/legal-holds/{hold_id}/release
```

Usage and quotas:

```text
GET    /v1/usage
GET    /v1/usage/summary
GET    /v1/quota-rules
POST   /v1/quota-rules
PATCH  /v1/quota-rules/{rule_id}
POST   /v1/quota/check
GET    /v1/quota/reservations/{reservation_id}
POST   /v1/quota/reservations/{reservation_id}/release
```

Rules:

- usage APIs return aggregate counts by default, not raw prompts/documents;
- quota check can be exposed to SDKs for dry-run/admission diagnostics;
- reservation release is idempotent;
- quota-rule changes require admin grant and audit.

Consolidation:

```text
POST   /v1/consolidation/jobs
GET    /v1/consolidation/jobs/{job_id}
POST   /v1/consolidation/jobs/{job_id}/cancel
POST   /v1/consolidation/jobs/{job_id}/apply
GET    /v1/clusters
GET    /v1/clusters/{cluster_id}
POST   /v1/clusters/{cluster_id}/split
GET    /v1/digests
GET    /v1/digests/{digest_id}
POST   /v1/digests/{digest_id}/refresh
```

Rules:

- consolidation job responses expose safe counts and ids, not raw private text by default;
- cluster split/merge requires review/admin grant unless policy allows non-destructive metadata-only changes;
- digest refresh follows provider governance and source visibility checks.

Projections and rebuilds:

```text
GET    /v1/projections
GET    /v1/projections/{projection_state_id}
POST   /v1/projections/verify
POST   /v1/projections/rebuild
GET    /v1/projection-rebuild-jobs/{job_id}
POST   /v1/projection-rebuild-jobs/{job_id}/pause
POST   /v1/projection-rebuild-jobs/{job_id}/resume
POST   /v1/projection-rebuild-jobs/{job_id}/cancel
POST   /v1/projection-rebuild-jobs/{job_id}/activate-generation
```

Rules:

- projection APIs are admin/diagnostic by default;
- rebuild dry-run reports counts, generation and estimated quota before mutation;
- verification results are id/count based unless debug scope allows details;
- activation of a new generation requires successful verification or explicit admin override with audit.

Facts:

```text
POST   /v1/facts
GET    /v1/facts/{fact_id}
PATCH  /v1/facts/{fact_id}
DELETE /v1/facts/{fact_id}
GET    /v1/facts/{fact_id}/history
GET    /v1/fact-conflicts
GET    /v1/fact-conflicts/{conflict_id}
POST   /v1/fact-conflicts/{conflict_id}/resolve
GET    /v1/current-facts?profile_id=...
```

Rules:

- fact update may create `SupersessionDecision` or `FactConflictRecord` instead of direct overwrite;
- direct conflict resolution requires reviewer/admin grant unless policy allows safe explicit user correction;
- current-facts endpoint returns only visibility-filtered facts and labels disputed/historical modes explicitly;
- conflict endpoints expose safe summaries and source ids by default, not long raw text.

Suggestions:

```text
GET    /v1/suggestions
GET    /v1/suggestions/{suggestion_id}
POST   /v1/suggestions/{suggestion_id}/approve
POST   /v1/suggestions/{suggestion_id}/reject
POST   /v1/suggestions/{suggestion_id}/expire
```

Episodes:

```text
POST   /v1/episodes
GET    /v1/episodes/{episode_id}
DELETE /v1/episodes/{episode_id}
```

Documents:

```text
POST   /v1/documents
GET    /v1/documents/{document_id}
GET    /v1/documents/{document_id}/chunks
DELETE /v1/documents/{document_id}
```

Uploads and artifacts:

```text
POST   /v1/uploads
POST   /v1/uploads/{upload_session_id}/complete
POST   /v1/uploads/{upload_session_id}/abort
GET    /v1/artifacts/{artifact_id}
GET    /v1/artifacts/{artifact_id}/download
POST   /v1/artifacts/{artifact_id}/revoke
```

Rules:

- upload complete verifies checksum, size, mime and policy before dependent documents/imports become trusted;
- artifact download re-checks authorization at download time;
- public responses expose storage/artifact ids, never raw object keys.

Import/export:

```text
POST   /v1/imports
GET    /v1/imports/{import_id}
POST   /v1/exports
GET    /v1/exports/{export_id}
GET    /v1/exports/{export_id}/download
```

Event cursor:

```text
GET    /v1/events?space_id=...&cursor=...
```

Sync exchange, future-gated:

```text
POST   /v1/sync/peers
GET    /v1/sync/peers
POST   /v1/sync/peers/{peer_id}/revoke
GET    /v1/sync/peers/{peer_id}/checkpoint
POST   /v1/sync/changes/prepare
POST   /v1/sync/changes/{change_set_id}/dry-run
POST   /v1/sync/changes/{change_set_id}/apply
GET    /v1/sync/conflicts
POST   /v1/sync/conflicts/{conflict_id}/resolve
```

Rules:

- these endpoints return `memory.unsupported` unless `supports_sync_exchange=true`;
- sync exchange is never implemented as direct database replication;
- every apply path goes through normal use cases, policy, authorization, tombstones and audit;
- derived Graphiti/Qdrant payloads are never accepted as sync input.

Connectors:

```text
POST   /v1/connectors
GET    /v1/connectors
GET    /v1/connectors/{connector_id}
PATCH  /v1/connectors/{connector_id}
POST   /v1/connectors/{connector_id}/rotate-token
POST   /v1/connectors/{connector_id}/rotate-webhook-secret
POST   /v1/connectors/{connector_id}/pause
POST   /v1/connectors/{connector_id}/resume
POST   /v1/connectors/{connector_id}/revoke
POST   /v1/connectors/{connector_id}/events
GET    /v1/connectors/{connector_id}/sync-state
```

Event subscriptions:

```text
POST   /v1/event-subscriptions
GET    /v1/event-subscriptions
PATCH  /v1/event-subscriptions/{subscription_id}
DELETE /v1/event-subscriptions/{subscription_id}
POST   /v1/event-subscriptions/{subscription_id}/test
```

Retrieval:

```text
POST   /v1/search
POST   /v1/context
```

Operations:

```text
GET    /v1/operations/{operation_id}
POST   /v1/operations/{operation_id}/cancel
GET    /v1/operations?space_id=...&status=...
GET    /v1/jobs/{job_id}
GET    /v1/health
GET    /v1/diagnostics/profile/{profile_id}
```

Rules:

- `/v1/operations/*` is public/client-safe progress;
- `/v1/jobs/*` is admin/diagnostic and may expose internal worker job ids safely;
- SDKs should poll operations, not internal outbox jobs;
- cancel is best-effort and must return committed target status when partial work already committed.

Legacy Client App compatibility:

```text
POST   /api/v1/interview-memory/ingest
POST   /api/v1/interview-memory/context
DELETE /api/v1/interview-memory/sessions/{session_id}
GET    /api/v1/interview-memory/sessions/{session_id}/status
```

Rules:

- these routes are compatibility adapters over core use cases, not a second memory implementation;
- they may be served by memo_stack_server during migration;
- response envelope must match existing desktop expectations;
- raw error bodies must stay production-safe because desktop diagnostics store sanitized errors.

### Contract Version Compatibility Matrix

Every externally visible contract must have an owner, compatibility rule and breaking-change process.

| Contract | Version owner | Compatibility rule | Breaking change requires |
|---|---|---|---|
| HTTP API routes | `api_version` in response meta and OpenAPI | `/v1` remains backward compatible inside v1 | new `/v2`, ADR, migration guide, dual-run window |
| Canonical DTO schemas | `memo_stack_contracts` schema registry | public DTOs are additive within supported version window | schema ADR, fixture update and SDK compatibility evidence |
| Domain-to-contract mappers | owning use-case/API adapter | domain refactors must not change public DTO shape silently | mapper tests and golden response diff |
| Bootstrap contract | bootstrap/config contract version | setup status/init shapes are additive and safe | bootstrap fixture update, auth review and setup migration note |
| Runtime config contract | config snapshot version | config status is safe metadata and additive | config doctor test, worker/API compatibility test and release note |
| Migration run contract | migration run version | phases are append-only and safe to inspect | migration plan fixture, dry-run evidence and rollback boundary note |
| Data backfill contract | backfill job version | chunk progress is resumable and idempotent | crash/resume test, tombstone skip test and old worker guard |
| Worker execution contract | worker protocol version | workers claim only compatible leased work | heartbeat, shutdown, lease reclaim and old-worker tests |
| Scheduled task contract | scheduled task version | task keys are stable and singleton leases are additive | duplicate scheduler and manual run idempotency tests |
| Storage object contract | storage object version | object metadata is additive and raw keys remain private | checksum, quarantine, delete verification and missing-object tests |
| Artifact contract | artifact schema version | downloads are governed by artifact status and current grants | expiry/revoke/download fixture and access-control tests |
| Backup manifest | backup manifest contract version | manifests are additive, signed/hash-verified and never inline raw private text | manifest hash, key availability, tombstone and restore dry-run fixtures |
| Restore run | restore run contract version | restore starts as dry-run and reports safe blockers before apply | restore validation, PITR and hard-delete resurrection tests |
| OpenAPI artifact | deterministic generated spec in CI | generated clients must match committed API contract | OpenAPI diff review and SDK release notes |
| Python SDK | package semver | minor versions may add fields/methods, not change defaults | major version or feature flag |
| Future TS/Rust SDKs | generated from OpenAPI plus hand-written ergonomics | unknown fields/enums are ignored or treated as unsupported | generated fixture update and contract tests |
| Postgres schema | migration version table | forward migrations are deterministic; rollback is documented when practical | migration ADR and backup/restore test |
| Qdrant collection schema | collection config version in diagnostics | payload fields may be added, not renamed without migration | reindex plan, snapshot/rebuild path, diagnostics update |
| Graphiti mapping | adapter mapping version | relation/entity mappings are additive by default | graph rebuild or migration job |
| Projection metadata | projection contract version | projection states/mappings are additive; generation activation is explicit | projection rebuild ADR, drift tests and generation migration plan |
| Operation/idempotency | operation contract version | operation statuses and replay snapshots are additive and safe | idempotency fixture update and SDK retry compatibility test |
| Ontology | ontology version and aliases | new kinds/relations are additive; rename uses alias/deprecation | compatibility alias, SDK enum update, eval update |
| Memory policy | policy version per profile | old decisions keep old policy version for audit | policy migration note and pending-job behavior test |
| Usage/quota governance | quota contract version | usage events are append-only; reservations are idempotent and bounded | reservation lifecycle tests, quota fixture update and admission-control tests |
| Consolidation and digests | consolidation contract version | clusters/digests are derived metadata and source-bound | false-merge eval, digest stale test and source-ref fixture update |
| Retention rules | retention rule version | rule changes affect future runs, not past audit reports | dry-run fixture update and retention ADR for destructive defaults |
| Legal holds | legal hold event version | active holds block destructive retention regardless of rule version | hold release/expiry test and audit chain proof |
| Prompt templates | prompt template id/version | new prompt versions run shadow eval before active use | eval update, rollback version, ADR for auto-promotion prompts |
| Structured model outputs | output schema id/version | schema changes are additive or disabled behind new version | contract fixture update and strict validation tests |
| Redaction rules | redaction version | rule additions can only make sensitivity stricter by default | offset-map regression tests and remediation note |
| Provider config | provider config version | provider/model/purpose allowlists are explicit capabilities | provider governance ADR and diagnostics update |
| Data residency | residency policy contract version | region/provider placement rules are additive and fail closed for unknown sensitive transfers | residency fixture update, provider region tests and transfer dry-run evidence |
| Export bundle | `bundle_schema_version` | import supports current and previous stable bundle version | migration transformer and dry-run test |
| Event cursor | cursor schema version | old cursor is accepted until configured expiry | cursor migration or explicit expired-cursor error |
| Cache freshness | cache freshness contract version | cache keys and invalidation dimensions are additive and fail closed | forget/grant/policy cache-bust tests and diagnostics update |
| Repository query scope | query scope contract version | scope proof fields are additive and safe, unscoped access fails closed | repository scope fixture update, unscoped SQL tests and maintenance override evidence |
| Supply-chain attestation | release attestation contract version | inventory/finding/waiver fields are additive and release gates fail closed | SBOM fixture update, CVE/license gate tests and parser sandbox evidence |
| Sync exchange | sync contract version and capabilities flag | disabled endpoints return `memory.unsupported`; enabled endpoints require dry-run and conflict fixtures | sync ADR, checkpoint migration and conflict-resolution tests |
| Client App legacy routes | compatibility adapter version | existing desktop envelope and mode precedence stay stable | desktop compatibility ADR and canary pass |
| MCP tool contract | tool schema version | tool inputs are additive and safe by default | MCP client migration note and safety review |

Compatibility window:

- V1 supports current and previous stable SDK minor version.
- Export/import supports current and previous stable bundle schema version.
- Legacy Client App routes remain until Client App has a released native `/v1` integration and rollback window has passed.
- Unknown enum values must not crash clients; they must be surfaced as unsupported capability or opaque string.

Release gates:

- OpenAPI deterministic diff must be reviewed in every API PR.
- Contract schema fixture diff must be reviewed with any public DTO change.
- SDK contract fixtures must be regenerated only in the same PR as the API contract change.
- Ontology changes must include alias/deprecation tests when renaming or replacing a kind.
- Migration PRs must include upgrade test and, when applicable, rebuild/backfill command.

### Example Requests

Remember fact:

```json
{
  "space_id": "space_client_app",
  "profile_id": "profile_architecture",
  "thread_id": "thread_123",
  "text": "Client App desktop memory defaults to active_context unless disabled by settings or env.",
  "kind": "architecture_decision",
  "source_refs": [
    {
      "source_kind": "document",
      "document_id": "doc_123",
      "chunk_id": "chunk_456"
    }
  ]
}
```

Search:

```json
{
  "space_id": "space_client_app",
  "profile_ids": ["profile_architecture"],
  "query": "как работает память интервью и какие есть rollback flags",
  "limit": 10,
  "include_sources": true
}
```

Context:

```json
{
  "space_id": "space_client_app",
  "profile_ids": ["profile_architecture", "profile_decisions"],
  "query": "объясни текущую архитектуру memory",
  "token_budget": 4000,
  "mode": "coding_agent"
}
```

## SDK Contract

Python:

```python
from memo_stack_sdk import MemoryClient

memory = MemoryClient(
    base_url="http://127.0.0.1:7788",
    api_key="local-dev-token",
)

fact = await memory.remember_fact(
    space="client-app",
    profile="architecture",
    text="Graphiti is used for temporal graph facts, Qdrant for document chunks.",
)

results = await memory.search(
    space="client-app",
    profiles=["architecture"],
    query="Graphiti Qdrant split",
)

bundle = await memory.build_context(
    space="client-app",
    profiles=["architecture"],
    query="what is our memory architecture?",
    token_budget=4000,
)

await memory.update_fact(
    fact.id,
    expected_version=fact.version,
    text="Postgres is canonical truth; Graphiti and Qdrant are derived indexes.",
)

await memory.forget_fact(fact.id, reason="obsolete")
```

SDK behavior rules:

- expose typed exceptions matching API error codes;
- retry only when server says `retryable=true` or on safe transient network failures;
- never retry non-idempotent mutating calls without `Idempotency-Key`;
- expose operation polling/cancel helpers and return `operation_id` for long-running methods;
- replay idempotent requests by returning stored result or operation status, not by issuing a second mutation;
- default timeouts are bounded and configurable;
- provide `with_options(timeout, retries, idempotency_key)` style override;
- support pagination helpers for list/search APIs;
- expose event cursor helpers and cache invalidation hooks;
- expose projection diagnostics/rebuild helpers only for admin/maintenance clients;
- expose usage/quota summary helpers for admin diagnostics;
- expose consolidation/digest helpers as admin or reviewer operations, not default prompt-path behavior;
- expose sync helper APIs only when capabilities report `supports_sync_exchange=true`;
- include connector helper APIs for registration, event ingest and sync state where the token has grants;
- expose raw `request_id` and diagnostics for support;
- never log raw memory text by default;
- treat unknown enum/capability values as unsupported, not fatal crashes.

Recommended SDK exceptions:

```text
MemoryValidationError
MemoryUnauthorizedError
MemoryForbiddenError
MemoryNotFoundError
MemoryConflictError
MemoryQuotaExceededError
MemoryPolicyBlockedError
MemoryUnsupportedError
MemoryProviderUnavailableError
MemoryTimeoutError
MemoryOperationCancelledError
MemoryServerError
```

## Connector and MCP Contract

Connectors are clients with explicit provenance and scoped permissions.

Connector examples:

```text
Client App desktop
Codex local agent
Claude desktop/project agent
Cursor extension
GitHub app
Slack app
manual CLI importer
future MCP server
```

Connector registration:

```text
connector_id
space_id
principal_id
source_app
allowed_profiles
allowed_actions
default_policy_id
trusted_source_types
created_at
status
```

Connector rules:

- connector writes require `SourceProvenance`;
- connector token is scoped to connector id, space, profiles and actions;
- connector cannot approve its own auto-generated suggestions unless policy explicitly allows;
- connector should use stable external ids for idempotency;
- connector must not send raw secret/restricted content unless policy and deployment allow it;
- connector should expose its own version in metadata for debugging.
- connector webhooks must be signed and checked for replay before payload processing;
- connector pause/revoke must stop new writes immediately while preserving provenance/audit history;
- connector backfill must write through normal ingest use cases and update sync state checkpoints.

Connector lifecycle:

```mermaid
stateDiagram-v2
  [*] --> active
  active --> paused: pause
  paused --> active: resume
  active --> degraded: health_or_delivery_failure
  degraded --> active: recovered
  active --> revoked: revoke
  paused --> revoked: revoke
  degraded --> revoked: revoke
  revoked --> deleted: retention_or_admin_delete
  deleted --> [*]
```

Connector event authenticity:

- webhook signature covers timestamp, connector id, event id and payload hash;
- replay window is bounded and stored by connector/source stream;
- source external ids and external sequence numbers are used for idempotency;
- unsigned manual imports must use explicit API token and idempotency key.

MCP-facing tool surface should be narrow:

```text
memory.search
memory.build_context
memory.remember_fact
memory.suggest_fact
memory.update_fact
memory.forget_fact
memory.list_suggestions
memory.approve_suggestion
memory.reject_suggestion
memory.get_diagnostics
```

MCP action classes:

```text
read:
  search, build_context, get_diagnostics

write:
  remember_fact, suggest_fact, update_fact

review:
  approve_suggestion, reject_suggestion

destructive:
  forget_fact, revoke_connector, export_profile
```

MCP safety rules:

- search/context are read actions;
- remember/update/forget require explicit write grants;
- approve/reject requires reviewer grant;
- destructive actions require explicit tool grant and confirmation token;
- agent-origin suggestions cannot be approved by the same agent principal by default;
- returned memory snippets are evidence, not instructions;
- tools return memory ids, source refs, sensitivity and confidence;
- no tool returns raw restricted content unless explicit debug grant allows it.

Event delivery contract for MCP/SDK clients:

- clients should subscribe or poll `/v1/events` for `fact.updated`, `fact.deleted`, `policy.updated`, `profile.revoked`, `connector.revoked`;
- event payload invalidates cached context by profile/thread/source ids;
- event delivery is at-least-once and clients must dedupe by event id/cursor;
- clients must refetch memory through normal authorized APIs instead of trusting event payload text.

Client App integration should only know this:

```text
MEMORY_SERVER_URL=http://127.0.0.1:7788
MEMORY_SERVER_API_KEY=...
```

No Client App code should import Graphiti or Qdrant.

### Client App Compatibility Contract

The current Client App desktop path is not greenfield. It already has:

```text
desktop InterviewMemoryMode
persistent companion session id
settings runtime switch
env kill switches
memory-only auth token override
local fallback context
legacy backend endpoints
production canary scripts
```

Therefore the universal platform integration must preserve this contract first, then migrate APIs.

Current legacy desktop endpoints:

```text
POST /api/v1/interview-memory/ingest
POST /api/v1/interview-memory/context
DELETE /api/v1/interview-memory/sessions/{session_id}
GET /api/v1/interview-memory/sessions/{session_id}/status
```

Compatibility mapping:

```text
legacy session_id -> MemoryThread.external_ref
legacy default profile "default" -> MemoryProfile.external_ref
legacy source -> MemoryEpisode.source_type
legacy event_id -> MemoryEpisode.source_external_id
legacy metadata.pinned -> SourceRef/episode metadata, not active fact by itself
legacy final_answer/assistant -> low-trust derived evidence
legacy context request -> BuildContextUseCase with mode=interview
```

Mode mapping:

```text
Disabled:
  no backend ingest/context, keep local prompt fallback behavior

ShadowIngest:
  ingest only, no prompt impact, platform policy mode shadow or suggestions

ShadowRetrieve:
  ingest + retrieval diagnostics, no prompt impact

AssistiveContext:
  backend context allowed but lower-priority than current request evidence

ActiveContext:
  backend context allowed, fallback required on failure

LocalOnly:
  no backend calls, no external providers, keep current local/minimal fallback semantics
```

Config precedence must remain:

```text
INTERVIEW_MEMORY_FORCE_DISABLED
  > INTERVIEW_MEMORY_FORCE_LOCAL_ONLY
  > INTERVIEW_MEMORY_MODE
  > legacy booleans INTERVIEW_MEMORY_ENABLED / INTERVIEW_MEMORY_ACTIVE_CONTEXT
  > Settings AppConfig.interview_memory_enabled
  > default active_context
```

Memory-only auth behavior:

- `INTERVIEW_MEMORY_AUTH_TOKEN` overrides only memory calls;
- it must not replace app auth, STT auth or normal backend auth;
- missing auth must degrade to fallback, not block chat/interview.

### Client App Integration Options

1. Compatibility gateway first
   🎯 9   🛡️ 9   🧠 6
   Approx changes: `900-1800` lines.

   Memo stack implements legacy `/api/v1/interview-memory/*` routes as an adapter over the new core. Client App can point `INTERVIEW_MEMORY_API_URL` to local platform without desktop bridge rewrite.

   Recommendation: choose this. It preserves existing E2E scripts, rollback flags and companion session behavior.

2. Rewrite desktop bridge directly to `/v1/*`
   🎯 6   🛡️ 6   🧠 5
   Approx changes: `500-1200` lines.

   Faster on paper, but high prompt-path blast radius. It risks breaking current canaries, session import behavior and fallback semantics.

3. Dual client inside desktop bridge
   🎯 7   🛡️ 8   🧠 8
   Approx changes: `1400-2600` lines.

   Desktop can call old and new APIs in shadow. Good for comparison, but too much complexity before the platform contract is stable.

Recommended migration sequence:

```text
1. Add compatibility routes in memo_stack_server.
2. Run existing Client App canary against memo_stack_server by changing only INTERVIEW_MEMORY_API_URL.
3. Add new SDK client behind the same desktop mode resolver.
4. Shadow compare old backend vs memo_stack_server retrieval with production-safe diffs.
5. Switch active context only after canary/document recall gates pass.
6. Remove legacy route dependency later, not in v1.
```

## Ingestion Pipeline

Full pipeline:

```text
receive input
  -> validate auth/scope/profile
  -> normalize
  -> load effective MemoryPolicy
  -> apply source/security gates
  -> detect sensitivity and required redaction
  -> run admission/quota check for expensive work
  -> idempotency check
  -> store canonical record
  -> chunk if needed
  -> resolve entities
  -> create redaction artifacts for external processing if allowed
  -> score evidence/confidence
  -> apply temporal semantics
  -> create outbox events
  -> return accepted
  -> worker indexes graph/vector
  -> worker updates ProjectionState and ProjectionMapping
  -> worker extracts/promotes facts
  -> worker consolidates duplicates/digests when policy allows
```

### Policy-Gated Classification

Not all text should become long-term memory.

The policy decision is first-class and mode-dependent:

```text
disabled:
  do not store memory content, optionally audit rejected request

shadow:
  store/process for diagnostics, never use in normal retrieval/context

manual_only:
  accept only explicit `POST /v1/facts`

explicit_only:
  accept explicit facts and explicit document/chunk storage, no automatic fact extraction

suggestions:
  classifier candidates become pending MemorySuggestion rows

auto_safe:
  high-confidence allowlisted candidates can become MemoryFact automatically

auto_aggressive:
  broader auto-promotion, still blocked by secrets/conflicts/profile/scope rules
```

Classification categories:

```text
ignore
short_term_only
source_chunk_only
candidate_fact
decision
constraint
preference
task
architecture_note
rejected_approach
bug_context
meeting_summary
```

Promotion rules:

- explicit user "remember this" can create fact immediately;
- detected architecture decisions can auto-promote only when policy allows the kind, confidence is high and source exists;
- personal preferences can auto-promote only in personal profile and only if source type is trusted;
- secrets/credentials should be blocked or redacted;
- conflicting facts require supersede policy or review;
- assistant answers must not become primary evidence unless backed by source refs or explicit user confirmation.
- unresolved entity identity blocks auto-promotion by default;
- uncertain temporal validity lowers confidence and can force review for decisions/constraints.
- repo/branch/PR-scoped facts cannot auto-promote to global memory without explicit promotion rule or trusted mainline source.

Recommended source trust levels:

```text
highest: explicit user/manual fact
high: repo docs, ADR, issue/PR, uploaded source document
medium: meeting transcript, interview transcript, Slack thread
low: assistant answer, generated summary, untrusted web paste
```

Auto-promotion should generally require `high` or `highest` trust in v1.

### Review Workflow

Review workflow is part of memory quality, not just UI.

Suggestion queues:

```text
needs_review
conflict
sensitive_blocked
low_confidence
auto_promote_candidate
stale_fact_review
```

Review actions:

```text
approve
approve_with_edit
reject
merge
supersede_existing
mark_stale
request_more_evidence
expire
```

Rules:

- every review action requires reviewer grant;
- approval creates source refs and audit event;
- edited approval keeps original candidate text in audit metadata;
- conflict review must show affected fact ids and source refs;
- bulk review is allowed only for low-risk categories and must be auditable;
- promotion from branch/PR scope to repo/global scope requires source event or reviewer action;
- rejected suggestions should train eval/heuristics later, but not automatically rewrite classifier behavior in v1.

### Chunking

Recommended defaults:

```text
chunk_size_tokens: 400-800
chunk_overlap_tokens: 60-120
max_single_episode_chars: bounded by config
```

Chunk metadata must include:

```text
source ids
char ranges
token count
hash
profile ids
thread id
status
```

For code:

- prefer structure-aware chunking later;
- v1 can use text chunking with file path/function hints;
- include language and file path in metadata.

### Document Processing Pipeline

Document ingestion is a staged, resumable pipeline:

```text
accept_upload
  -> validate size/mime/hash/quota
  -> resolve storage region/residency
  -> store raw file
  -> select parser sandbox policy
  -> classify sensitivity
  -> extract text
  -> normalize text
  -> run write admission and poisoning checks
  -> resolve processing location for embedding/classification/OCR
  -> chunk with source offsets
  -> create chunks
  -> embed chunks if policy allows
  -> classify/summarize if policy allows
  -> mark processed or processed_with_errors
```

Stage rules:

- every stage writes status and safe error details;
- raw file storage and DB metadata must be linked before extraction starts;
- extraction errors should not delete the original document unless hard-delete is requested;
- partial extraction can produce searchable chunks, but diagnostics must show missing pages/sections;
- parser/OCR/image extraction is a separate adapter family, not part of `ClassifierPort`;
- binary/image/OCR support is optional later and must be explicit because it changes cost/privacy.

Parser safety:

```text
max_file_bytes
max_extracted_chars
max_pages
max_archive_entries
max_nested_archive_depth
allowed_mime_types
blocked_mime_types
```

Never:

- execute document macros/scripts;
- fetch external URLs embedded in documents during extraction;
- send raw restricted documents to external OCR/LLM;
- treat generated summaries as primary source evidence.

## Supply Chain and Parser Sandbox Governance

Memo stack processes untrusted text and files. Dependency governance is therefore part of product safety, not a CI afterthought. This includes Graphiti, Qdrant client, Neo4j driver, FastAPI stack, LLM/provider SDKs, parser/OCR libraries, archive readers and object storage SDKs.

Core invariant:

```text
Remote/team releases cannot enable untrusted parsers, provider SDKs or adapters without dependency inventory, license/security gates and sandbox policy.
```

### DependencyInventory

Versioned inventory of runtime and build dependencies for a release artifact.

Fields:

```text
id
release_version
artifact_id?
package_name
package_version
package_manager: uv | poetry | pip | pnpm | docker | system
dependency_group: core | server | adapter_graph | adapter_vector | parser | ocr | provider_sdk | dev | transitive
source: lockfile | image_scan | manual
license_ids[]
hash?
is_direct: true | false
created_at
metadata
```

Rules:

- lockfile is source of truth for Python/Node dependencies;
- adapter dependencies stay out of `memo_stack_core`;
- optional heavy parser/OCR dependencies are grouped and disabled unless the adapter is enabled;
- inventory is attached to release artifacts and remote/team deployment diagnostics.

### DependencyRiskFinding

Normalized security/license finding produced by vulnerability, license or static analysis tools.

Fields:

```text
id
inventory_id?
release_version
package_name
package_version
finding_type: vulnerability | license | malware | abandoned | yanked | static_analysis | image_scan
severity: info | low | medium | high | critical
source_tool
source_id?
safe_summary
affected_components[]
status: open | accepted_risk | fixed | false_positive | expired
waiver_id?
created_at
resolved_at?
metadata
```

Rules:

- high/critical findings block remote/team release unless an expiring waiver exists;
- findings are production-safe and do not include secrets or private source;
- parser/provider findings are marked prompt-impacting when they can affect extraction, embedding or classification behavior.

### LicensePolicy

Deployment policy for acceptable dependency licenses.

Fields:

```text
id
deployment_id?
allowed_license_ids[]
blocked_license_ids[]
review_required_license_ids[]
allow_unknown_license: true | false
applies_to_groups[]
status: active | disabled
created_at
updated_at
metadata
```

Rules:

- unknown license is blocked for remote/team releases by default;
- local development can warn instead of block when configured;
- license waiver requires owner/admin approval and expiry.

### ParserSandboxPolicy

Policy for running document parsers, OCR and archive extractors on untrusted input.

Fields:

```text
id
space_id?
profile_id?
parser_family: text | pdf | office | archive | image_ocr | html | markdown | custom
allowed_mime_types[]
blocked_mime_types[]
allow_network: false
allow_macro_execution: false
max_cpu_ms
max_memory_mb
max_wall_time_ms
max_output_chars
max_files
max_archive_depth
filesystem_mode: none | temp_readonly | temp_writable
status: active | disabled
created_at
updated_at
metadata
```

Rules:

- network access is denied by default for parsers and OCR;
- macro/script execution is never enabled in v1;
- parser output is bounded before chunking, embedding or classification;
- parser timeout or resource violation quarantines the document or stores source-only metadata according to policy.

### ParserExecutionRun

Audit and diagnostics record for one parser execution.

Fields:

```text
id
document_id
storage_object_id
space_id
profile_id
parser_name
parser_version
sandbox_policy_id
input_mime_type
input_size_bytes
output_chars
status: succeeded | partial | failed | timed_out | resource_blocked | quarantined
safe_error?
started_at
completed_at?
metadata
```

Rules:

- parser run records parser version so upgrades can be audited;
- failed/partial extraction never creates active facts directly;
- parser run diagnostics expose counts/status/errors, not raw file text;
- parser upgrade can trigger reprocess jobs, but cannot silently rewrite active facts without policy/review.

### ReleaseArtifactAttestation

Safe release record that ties lockfiles, SBOM, scans and container image to a deployable artifact.

Fields:

```text
id
release_version
git_commit
artifact_type: wheel | docker_image | source_archive | local_dev
artifact_hash
sbom_ref?
lockfile_hashes[]
image_digest?
scan_status: passed | warning | blocked | waived
critical_findings_count
high_findings_count
waiver_ids[]
created_at
metadata
```

Rules:

- remote/team deployment should run only attested artifacts;
- local dev can run unattested artifacts but capabilities must report unsafe/local status;
- waiver ids must be scoped to package/version/finding and expire.

### Supply-Chain Options

Option A - Lockfile plus SBOM, vulnerability/license gates and parser sandbox policy.

🎯 9   🛡️ 9   🧠 5
Approx changes: `500-1000` lines.

Recommended. It is strong enough for local/team v1 without turning the memo stack into a full security product.

Option B - Full container sandbox for every parser/OCR job from day one.

🎯 7   🛡️ 10   🧠 8
Approx changes: `1500-3500` lines plus ops.

Safer for hostile documents, but heavy for v1. Keep the architecture compatible with it through `ParserSandboxPort`.

Option C - CI scan only, no domain records or parser sandbox policy.

🎯 4   🛡️ 4   🧠 2
Approx changes: `100-300` lines.

Too weak for a memo stack that ingests arbitrary files and routes content to AI providers.

Required tests:

- critical dependency finding blocks remote/team release without waiver;
- expired waiver blocks release again;
- blocked/unknown license fails remote/team release gate;
- parser sandbox denies network and macro/script execution;
- parser timeout/resource limit quarantines or fails document safely;
- parser run records parser version and safe error;
- optional parser dependency disabled by default cannot be used accidentally;
- release artifact attestation appears in diagnostics/capabilities.

## Retrieval and Context Packing

Retrieval sources:

```text
Graphiti facts/entities
Qdrant chunks
Postgres metadata filters
MemoryCluster metadata
MemoryDigest derived rollups
optional recent thread tail
```

Merge algorithm:

```text
collect candidates
canonical filter
dedupe by canonical id/source hash
collapse low-risk duplicates by reviewed clusters
score by relevance, code_scope match, recency, importance, confidence, profile priority
bucket by kind
pack under token budget
```

Context bundle sections:

```text
critical_constraints
active_facts
recent_thread_context
relevant_source_chunks
memory_digests
decisions
rejected_approaches
open_tasks
source_refs
```

Budget policy example:

```text
constraints: 20%
active facts: 25%
source chunks: 35%
recent context: 10%
citations/metadata: 10%
```

Rules:

- never include deleted/superseded memory unless user asks for history;
- prefer exact source chunks for code/document questions;
- prefer exact repo/branch/PR/commit scope for coding-agent questions;
- branch/PR-scoped facts are labeled and downranked outside their scope;
- prefer Graphiti facts for "what do we know/decided" questions;
- use digests only as compact derived context with visible source refs, never as standalone truth;
- clusters can collapse duplicates in context packing but cannot hide contradictory active facts;
- include source refs in debug mode;
- include no hidden chain-of-thought;
- prompt injection inside memory is treated as untrusted content.

Context quality gates:

```text
max_context_tokens
max_memory_share_of_prompt
min_source_score
min_fact_confidence
max_low_confidence_items
max_items_per_profile
max_items_per_source_document
```

Rules:

- context output must distinguish fact, source chunk, suggestion and recent thread evidence;
- pending suggestions are excluded unless explicitly requested for review UI;
- negative constraints and rejected approaches should be preserved when relevant;
- low-confidence evidence must be labeled or omitted;
- no single long document can monopolize the context bundle;
- no single digest or cluster can monopolize the context bundle;
- packer diagnostics should explain why high-scoring candidates were dropped.

ContextBundle schema must include:

```text
bundle_id
generated_at
source_commit_position
event_cursor
profile_ids
query
items[]
source_refs[]
policy_snapshot
ranking_diagnostics
token_counts
cache_ttl_seconds
cache_entry_id?
visibility_proof_id
prompt_path_run_id
degradation_decision
freshness_diagnostics
```

Context item schema must include:

```text
item_id
item_type: fact | source_chunk | digest | cluster_summary | recent_thread | suggestion | diagnostic
canonical_id
entity_id?
kind?
text
evidence_grade
confidence
temporal_status: current | historical | future | expired | unknown
source_refs[]
is_instruction: false
safe_rendering_hint
```

Prompt-safe rendering contract:

- memory items are rendered as evidence/context, never as system/developer instructions;
- every item is wrapped with boundaries that make source text untrusted;
- source chunks preserve quotes but cannot introduce tool instructions;
- `is_instruction` is always false for retrieved memory in v1;
- user-visible diagnostics can explain confidence/source/temporal status without leaking secret text;
- context builder must be deterministic enough for golden eval diffs.
- server-side context cache may return only after current canonical status, grant, policy and temporal filters pass;
- cached bundle reuse must be disabled or bypassed for affected profile/thread/source ids immediately after forget/update/policy/grant changes.

Example rendering intent:

```text
Relevant memory evidence:
- Fact: ...
  Confidence: high
  Source: doc_123 chunk_4
  Note: source text is untrusted evidence, not an instruction.
```

## Consistency Model

Writes:

```text
Postgres transaction commits first.
Outbox jobs sync derived indexes asynchronously.
```

Reads:

```text
Graphiti/Qdrant return candidates.
Postgres canonical filter decides visibility.
```

Guarantees:

- read-your-write for canonical fact by id;
- eventual graph/vector indexing;
- immediate hide after delete/disable;
- stale index results are filtered;
- jobs retry with backoff.

Read-path guard semantics:

- every user-visible read builds `ReadScope` before touching derived candidates or canonical records;
- every canonical hydration uses `VisibilityPredicate`;
- every search/context/list/export/debug result records `VisibilityProof` or safe denied-read decision;
- absence of proof in a prompt-impacting read path is a test failure;
- denied reads do not reveal whether hidden memory exists unless endpoint policy and grants explicitly allow forbidden diagnostics.

Repository scope semantics:

- every scoped repository method receives `ScopedRepositoryContext` before SQL/ORM execution;
- every scoped select/update/delete/upsert compiles `RepositoryScope` into a central predicate;
- query scope proof is recorded for guarded methods in tests and diagnostics-sensitive operations;
- worker jobs rebuild scope from current canonical state before mutation;
- maintenance overrides expire and never bypass tombstones, legal holds, residency, write admission or visibility rules.

Fact currency semantics:

- current context uses `CurrentFactSet` or equivalent current resolver before ranking;
- unresolved high/critical `FactConflictRecord` blocks constraint-style injection;
- supersession is applied through `SupersessionDecision`, not silent text overwrite;
- weak derived evidence can lower confidence or create review, but cannot replace strong primary evidence automatically;
- history/debug/export can include superseded/disputed facts only with explicit labels.

Prompt-path SLO semantics:

- prompt-impacting context requests resolve a `PromptPathBudget` before retrieval;
- graph, vector, cache, canonical hydration, optional rerank and packing have bounded stage budgets;
- slow derived adapters are cancelled or ignored after their stage deadline;
- degraded context still requires canonical visibility proof and prompt-safe rendering;
- hard deadline returns degraded/fallback-safe status instead of blocking the live workflow.

Write admission semantics:

- write admission decision is recorded before fact, suggestion, source chunk or index side effects;
- quarantine blocks graph/vector indexing, classifier promotion and normal context/search visibility;
- rejected writes can keep minimal safe audit only when policy allows;
- approval/release re-runs current policy instead of trusting an old admission decision blindly.

Residency semantics:

- processing-location decision is recorded before external provider calls, managed index writes, backup/export artifacts, import apply and sync transfer;
- region denial blocks side effects before quota is consumed or provider adapters are invoked;
- stricter destination residency policy wins during import/restore/sync;
- changing residency policy invalidates affected context/search/artifact caches before prompt-impacting reuse.

Outbox events:

```text
graph.upsert_episode
graph.upsert_fact
graph.delete_fact
graph.delete_episode
vector.upsert_chunks
vector.delete_chunks
projection.verify
projection.rebuild
projection.activate_generation
backup.plan
backup.create_manifest
backup.verify_manifest
restore.validate
restore.apply
restore.verify
cache.invalidate
cache.purge_expired
document.extract_text
memory.classify_episode
memory.create_suggestion
memory.promote_fact
memory.auto_promote_candidate
memory.detect_conflict
memory.resolve_conflict
memory.apply_supersession
memory.recompute_current_fact_set
memory.write_admission
memory.quarantine_candidate
memory.resolve_quarantine
memory.resolve_processing_location
memory.cross_region_transfer_request
memory.expire_suggestion
memory.consolidate_profile
memory.refresh_digest
memory.detect_duplicates
prompt_path.record_stage
prompt_path.record_degradation
quota.expire_reservations
quota.reconcile_usage
parser.run_extraction
parser.quarantine_violation
supply_chain.evaluate_release
supply_chain.refresh_inventory
sync.prepare_change_set
sync.apply_change_set
```

Outbox fields:

```text
id
event_type
aggregate_type
aggregate_id
idempotency_key
ordering_key
payload
status: pending | running | done | failed | dead
attempt_count
next_attempt_at
last_error
locked_by
locked_until
created_at
updated_at
```

Outbox semantics:

- `idempotency_key` is unique per logical side effect;
- adapter calls must be idempotent and guarded by `ProjectionMapping`;
- `ordering_key` serializes operations that can race, usually `space_id:profile_id` or aggregate id;
- worker claim sets `locked_by` and `locked_until` and creates a `WorkerLease`;
- expired locks can be reclaimed;
- delete/deindex events should outrank stale upserts for the same aggregate;
- `dead` jobs stay visible in diagnostics and never disappear silently;
- retry policy uses exponential backoff with jitter and max attempts per event type;
- promotion/classification jobs reload current canonical status and policy before writing.

Worker orchestration semantics:

- every worker process registers a `WorkerInstance` before claiming work;
- heartbeat age controls whether leases are active, stale or reclaimable;
- scheduler tick creates normal operations/jobs, not hidden side effects;
- singleton scheduled tasks use stable lease keys per deployment/scope/window;
- graceful shutdown moves worker to draining and stops new claims before releasing or checkpointing work;
- unsupported job schema or config mismatch blocks claim, not job visibility.

Object storage semantics:

- DB metadata is canonical for object visibility and authorization;
- object upload can complete before DB trust, but document/artifact visibility waits for `StorageObject.verified`;
- DB transaction and blob delete are not atomic, so hard-delete schedules verification work;
- object storage keys are treated as secrets and never as public ids;
- download authorization is checked through Postgres at request time, not delegated to presigned URL lifetime.

Backup/restore semantics:

- backup manifests are governed canonical metadata, while backup payloads live in object storage or external backup systems;
- backup and restore use canonical commit positions and event cursors to describe consistency;
- restore starts in dry-run and cannot make prompt-visible memory until validation passes;
- derived index snapshots are acceleration only and are discarded or rebuilt when they disagree with Postgres;
- point-in-time restore must preserve later hard-delete/tombstone/legal-hold effects when policy requires deletion safety;
- backup artifacts inherit strictest sensitivity and current download authorization rules.

Projection semantics:

- derived index write updates `ProjectionState` in the same logical worker operation;
- adapter object ids are recorded through `ProjectionMapping`;
- projection generation changes are explicit and visible through capabilities/diagnostics;
- rebuild uses canonical source watermark and does not replace active generation until verified;
- stale projection state lowers diagnostics/search confidence but never bypasses canonical filtering.

Cache/freshness semantics:

- cache entries are derived and never source of truth;
- context/search cache hits still run canonical Postgres status, authorization, grant, policy, temporal and sensitivity filters before returning user-visible content;
- forget/delete/policy/grant/legal-hold/source-redaction changes write cache invalidation records before success is reported or before prompt-impacting reads can reuse old cache;
- cache freshness uses canonical commit position or event cursor before wall-clock TTL;
- cache payload loss or cache backend outage degrades to recompute/miss, not stale unsafe data;
- server-side caches are scoped by space, profile set, principal or grant version, policy version, ontology version, temporal mode and source commit position.

Admission/backpressure semantics:

- expensive background jobs require an `AdmissionDecision` before running;
- worker claim respects workload class, fairness key and reserved interactive capacity;
- quota reservation is committed only after logical work succeeds or actual usage is known;
- failed/cancelled jobs release reservations or let them expire through cleanup;
- delete/forget/status/admin safety operations are not blocked by AI/embed quota exhaustion.

Sync-readiness semantics:

- canonical commit position is the only sync cursor source;
- sync cursors are not derived-index cursors;
- tombstone/delete events must be emitted before any later update candidate for the same aggregate;
- sync apply must call normal use cases rather than directly mutating repository tables;
- remote/team sync starts as dry-run-only until explicit ADR enables apply mode.

Workload classes:

```text
interactive_context:
  user waits, strict timeout, no heavy graph/vector writes

ingest_hot_path:
  best-effort, bounded request time, writes canonical/outbox only

background_indexing:
  graph/vector/document extraction, retryable

background_ai:
  classifier/summarizer/embedding, quota-limited and cancellable

background_quality:
  consolidation, duplicate detection, digest refresh, stale review

maintenance:
  rebuild, migration, cleanup, snapshot, export

sync:
  future local-to-cloud change sets, dry-run first, quota-limited
```

Queue priority:

```text
interactive_context > ingest_hot_path > delete/deindex > indexing > ai_extraction > background_quality > maintenance
```

## Deployment

Local Docker v1:

```text
memo_stack_server
postgres
qdrant
neo4j for graphiti
object_storage
worker
```

Recommended local ports:

```text
memo_stack_server: 7788
postgres: 54329
qdrant: 6333
neo4j: 7474/7687
object_storage: local filesystem or minio-compatible endpoint
```

Environment:

```text
MEMORY_DATABASE_URL=postgresql+asyncpg://...
MEMORY_QDRANT_URL=http://qdrant:6333
MEMORY_OBJECT_STORAGE_PROVIDER=local_filesystem
MEMORY_OBJECT_STORAGE_ROOT=./.memory-objects
MEMORY_GRAPH_ENGINE=graphiti
MEMORY_GRAPHITI_BACKEND=neo4j
MEMORY_GRAPHITI_NEO4J_URI=bolt://neo4j:7687
GRAPHITI_TELEMETRY_ENABLED=false
MEMORY_ALLOW_EXTERNAL_AI=false
MEMORY_EMBEDDING_PROVIDER=noop_or_local
# Enable only when policy allows external AI:
# MEMORY_EMBEDDING_PROVIDER=openai
# MEMORY_OPENAI_API_KEY=...
MEMORY_AUTH_MODE=local_token
MEMORY_DEPLOYMENT_MODE=local_single_user
MEMORY_BOOTSTRAP_TOKEN_FILE=/run/secrets/memory_bootstrap_token
MEMORY_TELEMETRY_DISABLED=true
```

Future remote:

```text
same API
same SDK
remote URL/token
managed Postgres/Qdrant/Neo4j optional
sync exchange disabled until ADR enables it
```

Migration rules:

- schema migrations are explicit and versioned;
- startup refuses unknown newer schema unless `read_only` compatibility mode is supported;
- migrations are backward-compatible across at least one released client/SDK version;
- destructive migrations require export/backup confirmation and documented rollback;
- derived index migrations must be rebuildable from Postgres;
- migrations follow expand/backfill/dual-read/contract-switch/cleanup phases when data or public contracts change;
- cleanup is blocked until compatibility window expires and rollback boundary is accepted;
- workers refuse jobs whose payload/schema version is incompatible with their runtime config snapshot;
- OpenAPI contract is generated in CI and client SDKs are regenerated from it.

Recommended migration tool:

```text
Alembic for Postgres schema
explicit index migration commands for Qdrant/Graphiti
contract tests for OpenAPI compatibility
```

Deployment modes:

```text
local_single_user:
  local token, local Docker, no external AI by default

team_self_hosted:
  auth gateway or JWT verification, scoped service tokens, backups required

managed_remote_later:
  organization billing/quotas, stronger audit/export, not v1
```

Local Docker requirements:

```text
docker compose up memo_stack_server postgres qdrant neo4j object_storage worker
docker compose ps shows health for every service
bootstrap command creates first owner/space/profile/token
dev_reset clears derived indexes and Postgres test data intentionally
dev_seed loads synthetic golden fixtures
diagnostics explains missing env, ports, migrations and index health
```

Rules:

- local startup should not require OpenAI or external provider credentials;
- fresh local startup should clearly report `bootstrap_required`, not accept unauthenticated normal API traffic;
- healthchecks must distinguish ready, degraded and misconfigured;
- `dev_reset` must be explicit and never run automatically;
- `dev_reset` and `dev_seed` require `deployment_mode=local_single_user` and lineage confirmation;
- seeded fixtures must be synthetic and safe to commit;
- runbook must include how to rebuild Qdrant/Graphiti from Postgres.
- runbook must include migration dry-run, backfill resume and cleanup confirmation flow.
- runbook must include object storage integrity check and hard-delete verification flow.

## Operational Runbooks and Readiness

Readiness states:

```text
ready:
  API, Postgres, auth, policy, outbox and enabled adapters are healthy

degraded:
  canonical API works but one or more derived indexes/providers are unavailable

misconfigured:
  required config, migrations, payload indexes or provider policy is invalid

read_only:
  writes disabled for migration/restore, reads/admin diagnostics allowed

maintenance:
  rebuild/export/import/migration in progress, prompt-impacting retrieval may be limited
```

Runbook matrix:

| Scenario | Required command/endpoint | Expected safe behavior |
|---|---|---|
| Rebuild Qdrant | `memo_stack_server rebuild vector --profile ...` | Postgres remains canonical, deleted chunks stay hidden |
| Rebuild Graphiti | `memo_stack_server rebuild graph --profile ...` | facts reindexed from active canonical records only |
| Create backup | `memo_stack_server backup create --policy ...` | manifest records commit cursor, key versions and object inventory hash |
| Validate restore | `memo_stack_server restore validate --manifest ...` | reports key/object/tombstone blockers without mutation |
| Restore Postgres | documented backup restore plus derived rebuild | derived indexes discarded or validated against commit position |
| Point-in-time restore | restore dry-run plus retained tombstone replay | later hard-delete/tombstone/legal-hold effects stay effective |
| Provider outage | diagnostics plus circuit breaker status | async jobs retry, prompt path uses fallback/context without model call |
| Prompt template rollback | activate previous prompt/schema version | new classifications use old version, existing facts unchanged |
| Secret remediation | `memo_stack_server remediate secrets --source ...` | stale embeddings deindexed, redacted artifacts created, audit safe |
| Migration failure | migration status and read-only fallback | no partial destructive migration without backup/export |
| Backfill crash | resume backfill job from cursor | no duplicate transformation and no skipped deleted/held rows |
| Contract switch mismatch | dual-read verification | block switch and keep old compatible route active |
| Worker crash | stale heartbeat and lease reclaim | retry only through idempotent handler and safe operation status |
| Duplicate scheduler | singleton task lease diagnostics | one logical scheduled run per task scope/window |
| Graceful shutdown | drain worker command or SIGTERM handler | no new claims, checkpoint/release current work safely |
| Object integrity failure | storage diagnostics and quarantine | dependent document/artifact degraded, raw key hidden |
| Artifact revoke | artifact revoke endpoint or grant change | old download links stop authorizing access |
| Cache safety incident | `/v1/admin/cache`, invalidate, purge-expired | cached payloads are invalidated/purged, canonical memory unchanged |
| Legacy compatibility outage | compatibility diagnostics | Client App falls back without blocking chat/interview |

Readiness rules:

- `/v1/health` is shallow and production-safe;
- `/v1/capabilities` reports enabled adapters, schema versions, provider modes and degraded features;
- `/v1/diagnostics/*` can explain misconfiguration without raw memory text;
- provider readiness is purpose-specific, for example embeddings can be down while canonical facts still work;
- startup fails closed when schema is newer than server unless read-only compatibility mode is explicitly supported;
- degraded mode must be visible to SDK clients so they can avoid unsafe retries.

Incident drills before remote/team usage:

- restore Postgres and rebuild Graphiti/Qdrant from canonical records;
- validate backup manifest with missing key/object fixtures and verify restore blocks safely;
- block all external AI and verify local canonical operations still work;
- rotate service token and verify old token cannot read/export/forget;
- revoke grant while cached context exists and verify stale server cache is blocked;
- simulate provider schema drift and verify classifier output is rejected;
- simulate secret discovered after embedding and verify remediation deindexes it.

## Security and Privacy

Principles:

- memory is sensitive;
- source text can contain private code, credentials, interview prompts;
- default local deployment should not call external LLM unless configured;
- external embedding/classification should be explicit.

Required controls:

- API auth token;
- space/profile authorization;
- principal resolution;
- space membership and profile grants;
- redaction hooks before external LLM/embedding;
- retention policies;
- delete/forget endpoint;
- audit log;
- production-safe diagnostics;
- cache payload governance and freshness checks;
- backup artifact governance and restore validation;
- no raw source text in normal health/status endpoints.

Authorization model:

```text
request token -> Principal -> SpaceMember -> ProfileGrant -> allowed action
```

Actions:

```text
read
ingest
suggest
approve
write_fact
forget
admin
export
hard_delete
```

Rules:

- every endpoint resolves principal before touching adapters;
- background workers use worker principal but must still respect canonical status/policy;
- service tokens should be scoped and rotatable;
- admin/export/hard_delete require explicit grants;
- cross-space search requires explicit multi-space authorization and must be off by default;
- cached context/search results go through the same authorization checks as uncached reads;
- authorization failures must not reveal whether a hidden memory exists.

## Data Residency and Regional Placement

V1 is not a multi-region SaaS, but region placement still needs to be a domain concept because local Docker, self-hosted team server and future cloud deployment must share the same API and policy language.

Core invariant:

```text
No raw memory, embedding, backup, export, sync bundle or external provider call may leave the configured residency boundary without an explicit ProcessingLocationDecision.
```

Where residency is checked:

- raw source storage;
- object storage and upload URLs;
- Graphiti/Neo4j backend placement;
- Qdrant backend placement;
- embedding, classifier, reranker, OCR and summarizer provider calls;
- backup artifact creation and restore apply;
- export artifact creation and download;
- import bundle apply;
- future sync change-set prepare/apply.

Decision options:

Option A - Single region in v1, first-class residency policy.

🎯 9   🛡️ 9   🧠 5
Approx changes: `500-1000` lines.

Recommended. Local mode uses `local`, remote/team mode chooses one home region per deployment/space, and every transfer/provider action records a decision.

Option B - Region fields only in config, no domain model.

🎯 6   🛡️ 5   🧠 3
Approx changes: `100-300` lines.

Simpler, but too easy for backup/export/provider adapters to drift and bypass the rule.

Option C - Full multi-region routing and sync from day one.

🎯 5   🛡️ 7   🧠 9
Approx changes: `2500-6000` lines plus ops.

Too much for v1. It should wait until core lifecycle, sync dry-run and conflict review are proven.

Rules:

- `MemorySpace.home_region_id` is required in remote/team deployments;
- local deployments can use synthetic `local` region and still exercise the same code path in tests;
- `DataResidencyPolicy` is resolved before quota/admission for external provider work;
- unknown provider region is a deny or local-only decision for `confidential`, `secret` and `restricted` data;
- backup/export artifacts inherit residency policy and strictest sensitivity from included records;
- import/restore cannot relax destination residency policy silently;
- future sync exchange advertises region capabilities before preparing change sets;
- diagnostics show decision id, purpose, region and safe reason codes, not raw text.

Required tests:

- local mode resolves `local` decision and does not call cloud region APIs;
- external embedding provider with unknown region is blocked for restricted document;
- export artifact creation is rejected when target region is not allowed;
- backup restore dry-run reports region mismatch without mutation;
- Qdrant/Graphiti managed backend outside allowed region blocks prompt-visible indexing;
- import bundle from another region requires dry-run conflict or review;
- changing residency policy invalidates affected caches and blocks stale artifact downloads.

## Key Management, Token Storage and Audit Integrity

Key purposes:

```text
raw_source
object_storage
export_bundle
backup_archive
token_hash_pepper
audit_chain
```

Key rules:

- every encrypted record stores `key_version` and encryption purpose;
- local mode can use local secret material, but team/remote mode should use configured KMS or secret manager;
- key rotation creates a new active key version and re-encrypts records in resumable batches;
- old key versions remain decrypt-only until all referenced data is re-encrypted or retention expires;
- hard-delete must remove encrypted payload and any key-wrapped object references allowed by policy;
- backups and exports are encrypted independently from live database encryption.

Token storage rules:

- bearer tokens are shown once and then stored only as salted hash plus optional pepper;
- diagnostics show token prefix and token id only;
- token scopes include space, profile, action, connector id and expiry;
- revoked tokens fail immediately without deleting principal/audit history;
- token rotation creates a new token id and keeps old token audit references immutable.

Audit integrity rules:

- audit events are append-only;
- admin/export/hard_delete/policy/provider/key changes are high-value audit events;
- each audit event stores previous hash and current hash for tamper-evident chain per space;
- chain verification is a diagnostics/admin operation and never prints raw memory text;
- audit retention can remove raw details only by replacing them with redacted/minimal records allowed by policy.

Required tests:

- token database leak does not reveal usable bearer token;
- revoked token cannot read, export or hard-delete;
- key rotation preserves read/search/delete for encrypted records;
- backup restore verifies key version availability before serving data;
- audit chain detects deleted/modified/reordered audit events;
- hard-delete leaves only allowed minimal audit metadata.

Quota and backpressure:

```text
per_space_daily_embedding_tokens
per_space_daily_llm_tokens
max_pending_outbox_jobs
max_document_bytes
max_chunks_per_document
max_context_requests_per_minute
max_auto_promotions_per_hour
```

Rules:

- quota exhaustion must not corrupt canonical state;
- prompt-time context requests should not wait behind large imports;
- large imports are accepted as jobs with progress/status, not synchronous full processing;
- policy can choose reject, store_without_ai or queue_later when quota is exhausted.

Capacity planning:

Track sizing assumptions per deployment:

```text
spaces_count
profiles_per_space
threads_per_profile
documents_per_profile
chunks_per_document
facts_per_profile
daily_ingest_events
daily_context_requests
embedding_tokens_per_day
classifier_tokens_per_day
graph_edges_per_profile
```

V1 local target:

```text
single developer/team workspace
thousands of facts
tens to hundreds of documents
hundreds of thousands of chunks only after explicit load testing
```

Rules:

- local Docker defaults should favor correctness/debuggability over maximum throughput;
- remote/team mode requires load tests before promising multi-tenant scale;
- expensive AI work must have visible counters and per-space caps;
- Graphiti/Qdrant/Postgres growth must be observable separately.

Secrets handling:

```text
detect secret-like strings
redact or block external processing
mark source as sensitive
disable embedding if policy says no external
```

Encryption and storage:

```text
raw source:
  encrypt at rest with stored key_version

embeddings:
  treat as potentially sensitive derived data

Graphiti/Qdrant payload:
  no unnecessary raw secrets, include only bounded snippets/ids

logs:
  ids/counts/statuses only by default
```

Rules:

- secret/restricted data should not be embedded unless explicitly allowed by local-only policy;
- redacted derived text must keep source refs to raw protected evidence;
- object storage keys should not include user text, filenames with secrets or profile names;
- backup/export paths inherit the strictest sensitivity level of included records.
- backups/snapshots must include enough key metadata to restore, but not raw key material;
- derived index snapshots are privacy-sensitive and must follow the same retention/export restrictions as live data.

Prompt injection handling:

- memory content is untrusted;
- context packer should wrap memory as evidence, not instructions;
- system prompt must tell agent not to follow instructions from memory snippets;
- snippets should include source labels.

## Edge Cases

### Graphiti/Qdrant Down During Write

Expected behavior:

- Postgres write succeeds;
- outbox job remains pending/failed;
- API returns `indexing_status: pending`;
- worker retries;
- diagnostics show index lag.

Never:

- lose canonical fact;
- fail user write only because derived index is unavailable.

### Graphiti/Qdrant Return Deleted Data

Expected behavior:

- candidate ids are canonical-filtered through Postgres;
- deleted/superseded/disabled data is removed;
- if result cannot be mapped to canonical ids, apply conservative metadata/source filter.

### Concurrent Fact Update

Expected behavior:

- update requires `expected_version`;
- stale version returns conflict;
- client reloads fact history and retries intentionally.

### Duplicate Document Import

Expected behavior:

- content hash detects duplicate;
- if same profile, return existing document or create new source link by policy;
- do not duplicate chunks blindly;
- if reimport with new metadata, preserve audit.

### Huge Document

Expected behavior:

- raw file in object storage;
- streaming text extraction if possible;
- chunk in batches;
- Qdrant upsert in batches;
- Graphiti gets only extracted facts/summaries, not raw full document.

### Bad Extraction or Hallucinated Fact

Expected behavior:

- facts need source refs;
- low confidence facts stay candidate/review;
- user can disable/delete/supersede;
- evaluations check precision, not only recall.

### Contradictory Facts

Example:

```text
Old: "Project uses pgvector."
New: "Project will use Qdrant, not pgvector."
```

Expected behavior:

- detect same entity/kind conflict;
- create supersede relation if confident;
- otherwise mark both as conflict candidates;
- retrieval should prefer latest active fact and surface source.

### Wrong Entity Merge

Example:

```text
"Alex" in an interview candidate profile vs "Alex" in a team Slack profile.
"memo_stack_core" package in Client App vs another repo with same package name.
```

Expected behavior:

- canonical entity key includes profile and scope;
- Graphiti entity merge is treated as candidate evidence only;
- ambiguous entity resolution blocks auto-promotion;
- merge/split operations are audited and can be rolled back by creating corrected aliases and supersede relations;
- eval includes same-name/different-scope fixtures.

### Historical Fact Leaks Into Current Context

Example:

```text
Old: "We use pgvector."
Current: "We use Qdrant."
```

Expected behavior:

- current context filters by `valid_from`, `invalid_at` and status;
- historical facts can appear only when `include_historical=true` or query asks for history;
- source timestamp and ingestion timestamp are not conflated;
- context item includes `temporal_status`;
- eval checks stale leakage rate separately from normal recall.

### Profile Leakage

Expected behavior:

- every query requires space/profile scope;
- Graphiti group id and Qdrant payload filter include profile;
- Postgres canonical filter enforces authorization;
- tests cover cross-profile and cross-space isolation.

### Thread vs Profile Scope

Expected behavior:

- short-term thread context does not automatically become long-term profile fact;
- classifier can promote selected facts;
- user can explicitly promote.

### Forget Only One Fact

Expected behavior:

- fact deleted;
- source document/chunk remains unless `scope=fact_and_sources`;
- Graphiti edge/triplet deindexed best-effort;
- history records tombstone.

### Forget Source Document

Expected behavior:

- document and chunks deleted/disabled;
- facts sourced only from that document are disabled or marked evidence_missing by policy;
- facts with other source refs remain active;
- vector chunks are deindexed.

### Adapter Schema Drift

Expected behavior:

- adapter capabilities/version exposed in health;
- migrations are explicit;
- index rebuild command exists;
- derived indexes can be dropped/rebuilt from Postgres.

### Critical Parser or Provider SDK CVE

Expected behavior:

- dependency scan creates `DependencyRiskFinding`;
- remote/team release is blocked unless an unexpired scoped waiver exists;
- affected parser/provider adapter can be disabled through config/capabilities;
- existing canonical memory remains readable/deletable in Postgres-only mode.

### Parser Sandbox Escape Attempt

Expected behavior:

- network, macro/script or filesystem policy violation stops parser run;
- document is quarantined or marked extraction_failed according to policy;
- no chunks, embeddings, facts or suggestions are created from unsafe output;
- diagnostics expose parser run id, status and safe reason code only.

### Multi-App Same Profile

Expected behavior:

- source refs include app/source;
- idempotency keys are namespaced by source;
- same profile can receive data from Codex, Client App, Slack, GitHub.

### Offline Local Mode

Expected behavior:

- local memo_stack_server can run in Docker;
- if remote unavailable, app can use configured local URL;
- sync to cloud later is out of v1 but schema should support event log/outbox.

### Prompt Budget Overflow

Expected behavior:

- context packer drops low-score candidates first;
- critical constraints and current query stay;
- diagnostics report dropped count and reason;
- no section can monopolize the whole prompt.

### Embedding Dimension Change

Expected behavior:

- embedding model stored in collection metadata/config;
- dimension mismatch blocks startup or creates new collection namespace;
- reindex job required.

### Partial Index Failure

Expected behavior:

- outbox records per-adapter failure;
- `indexing_status` can be `graph_done/vector_failed`;
- search degrades but canonical data remains.

### Memory Poisoning

Expected behavior:

- untrusted snippets cannot override system/developer instructions;
- sources can be marked suspicious;
- user can report/forget;
- classifier can block instructions like "ignore previous instructions".

### Auto-Memory Feedback Loop

Problem:

```text
assistant answer -> memory -> future assistant answer -> stronger memory
```

Expected behavior:

- assistant answers are low-trust derived evidence by default;
- auto-promotion from assistant output requires source refs or explicit user confirmation;
- classifier stores `source_type` and trust level;
- repeated derived summaries do not increase confidence unless new primary evidence appears.

### Auto-Promote During Delete Race

Example:

```text
user deletes fact/source
old classification job finishes later
job tries to promote candidate from deleted source
```

Expected behavior:

- async worker reloads current source/fact/profile status before promotion;
- tombstone check happens inside same transaction as promotion;
- promotion is blocked if source is deleted, disabled or hard-deleted;
- audit records skipped promotion reason.

### Policy Changed While Jobs Are Pending

Expected behavior:

- job payload keeps policy snapshot version for diagnostics;
- worker reloads current effective policy before irreversible promotion;
- if current policy is stricter than snapshot, stricter policy wins;
- if current policy is looser than snapshot, promotion can proceed only if job is still valid and source is active.

### Source Trust Levels

Expected behavior:

- trust level is part of classifier input and candidate output;
- `auto_safe` requires trusted source categories;
- `auto_aggressive` can use medium trust but still creates review for conflicts or sensitive data;
- low-trust sources can produce suggestions, not active facts.

### Branch-Aware Coding Memory

Problem:

```text
Decision is true for branch feature/memory, but false for main.
```

Expected behavior:

- coding memories can include `repo_id`, `branch`, `commit_sha`, `package`, `environment`;
- retrieval query can ask for branch-specific or global facts;
- branch-local facts are downranked outside their scope;
- merge/release events can promote branch facts to project/profile facts.

### Code Reference Line Drift

Problem:

```text
Fact cites src/memory.py:120, but the function moved after refactor.
```

Expected behavior:

- code reference stores commit sha and content hash when available;
- resolver tries commit/file/symbol/content hash before line range;
- if reference cannot be mapped, mark `CodeReference.status=stale`;
- stale code refs can remain evidence but are labeled and lower confidence;
- context should not claim stale line numbers as current code.

### Dirty Worktree Memory Becomes Team Fact

Expected behavior:

- connector marks `worktree_state=dirty` or unknown;
- dirty worktree facts default to thread-local or suggestion;
- team/global promotion requires explicit approval or later clean commit/PR evidence;
- eval covers local-only implementation note that must not affect team profile.

### PR Abandoned After Memory Was Stored

Expected behavior:

- GitHub/connector event marks PR/branch scope stale or abandoned;
- branch/PR facts are excluded from mainline context by default;
- useful rejected approaches can remain as historical/reviewable notes;
- promotion to repo/global requires merge/release/ADR evidence or reviewer action.

### Retention Job Deletes Useful Active Fact

Expected behavior:

- retention dry-run is required for destructive rules;
- active high-importance facts can require review before disable/delete;
- legal hold and source trust are checked before deletion;
- retention action creates audit and event payload for cache invalidation;
- restore is not assumed after hard-delete, so rules must be conservative by default.

### Legal Hold Conflicts With User Forget

Expected behavior:

- normal retrieval hides forgotten held record when policy allows;
- hard-delete is blocked while hold is active;
- response explains safe status without revealing raw held content;
- audit records both user forget and hold block;
- hold release triggers retention re-evaluation instead of automatic blind delete.

### Profile Deletion Leaves Orphans

Expected behavior:

- profile delete runs through retention/delete job with dry-run summary;
- facts, chunks, documents, subscriptions, connector grants, Qdrant points, Graphiti group mappings and object blobs are handled;
- failed cleanup remains visible in diagnostics;
- profile id tombstone prevents accidental reimport resurrection.

### Same Entity, Different Meaning

Examples:

```text
Router as app router
Router as review-router package
Memory as product module
Memory as human interview memory
```

Expected behavior:

- entity key includes profile, source domain and optional repo/package scope;
- Graphiti entity merges are treated as candidates, not canonical identity truth;
- ambiguous entity matches require canonical disambiguation before update/supersede;
- diagnostics expose entity ids and source refs.

### Ontology Drift Across Clients

Problem:

```text
Codex writes kind=adr, Slack writes kind=decision, GitHub writes kind=architecture_decision
```

Expected behavior:

- connector SDK validates known core kinds;
- unknown values require namespace and are mapped through ontology aliases;
- retrieval normalizes aliases before ranking;
- auto-promotion policies operate on canonical kinds only.

### Connector Writes Without Provenance

Expected behavior:

- write is rejected with `memory.validation`;
- SDK helpers require connector/source metadata;
- manual writes can use `source_app=manual`;
- diagnostics count rejected provenance-less connector writes.

### Agent Approves Its Own Hallucination

Expected behavior:

- connector principal cannot approve suggestions it created unless policy explicitly grants self-review;
- assistant/generated source remains low trust;
- approval UI/API shows candidate creator and source refs;
- tests cover generated false requirement -> cannot self-approve.

### Entity Rename

Expected behavior:

- rename creates alias relation rather than duplicating unrelated entities;
- old aliases remain searchable;
- canonical facts should point to stable ids, not only display names;
- retrieval can surface "formerly known as" only when useful.

### Memory Rot and Staleness

Expected behavior:

- facts can store `valid_from`, `invalid_at`, `expires_at`, `last_seen_at`;
- stale facts are downranked or marked `needs_review`;
- repeated recent evidence can refresh `last_seen_at`;
- old architectural decisions remain available as history but should not override current active constraints.

### Consolidation False Merge

Expected behavior:

- semantically similar facts from different entities, profiles, repos or time windows remain separate;
- false-merge guardrail uses entity, code scope, temporal and source trust signals;
- low-cohesion candidates create proposed clusters or review items, not automatic fact merges;
- reviewer split operation preserves original source refs and cluster history.

### Digest Outlives Deleted Source

Expected behavior:

- source delete/update marks dependent digest stale immediately through canonical event handling;
- hard-delete of source removes digest from normal search/context;
- digest refresh re-checks source refs, policy, redaction and legal hold before regeneration;
- diagnostics show stale digest count without exposing digest text when policy forbids it.

### Digest Becomes Fake Primary Evidence

Expected behavior:

- digest has evidence grade `derived`;
- repeated digest refresh does not raise fact confidence;
- materializing a fact from a digest requires original source refs or reviewer confirmation;
- context renderer labels digest as compact derived context, not source truth.

### Consolidation Job Races With Fact Update

Expected behavior:

- job stores candidate aggregate versions and re-checks before apply;
- stale candidates are skipped or recomputed;
- checkpoint/audit records skipped counts;
- active context never waits for consolidation completion.

### Repeated Suggestion Spam

Expected behavior:

- dedupe suggestions by normalized candidate text, entity key, kind and source hash;
- rate-limit near-duplicate suggestions per profile/thread;
- merge supporting source refs into existing pending suggestion;
- diagnostics show suppressed duplicate count.

### Ambiguous Forget Request

Example:

```text
user says "forget that decision"
multiple recent decisions match
```

Expected behavior:

- do not broad-delete by guess;
- return candidate targets with ids/sources for confirmation;
- allow exact delete by fact id, document id, thread id or source ref;
- support scoped delete once target is resolved.

### Hard Delete and Backups

Expected behavior:

- hard delete removes raw source text, document chunks and vector points;
- Graphiti deletion is best-effort but canonical filter hides immediately;
- backup retention policy must be explicit;
- exported bundles must respect hard-deleted tombstones;
- audit may keep minimal metadata only if policy/legal mode allows it.

### Malicious or Broken Document Import

Expected behavior:

- reject or quarantine zip bombs, binary files disguised as text, unsupported mime and over-limit files;
- normalize encoding safely;
- cap extracted text size per document and per chunk;
- treat document text as untrusted prompt-injection surface;
- never execute embedded content or links during extraction.

### Document Parser Drift

Expected behavior:

- parser name/version is stored on document extraction metadata;
- extraction changes can be re-run in shadow against golden documents;
- source offsets are validated after parser upgrades;
- parser upgrade cannot silently rewrite active facts without policy/review.

### Confidential Data Embedded Accidentally

Problem:

```text
secret token is embedded before redaction catches it
```

Expected behavior:

- secret detector runs before embedding/classification;
- if secret is detected after embedding, chunk status becomes `stale_sensitive`;
- vector point is deleted and replaced only with redacted/local-safe representation if policy allows;
- audit records remediation without logging the secret.

### Partial Document Extraction Failure

Expected behavior:

- document can be `processed_with_errors`;
- successful chunks remain searchable if policy allows;
- failed pages/sections are recorded in diagnostics;
- retries target only failed extraction stages when possible.

### Embedding Model Migration

Expected behavior:

- embedding model and dimension are stored in chunk metadata;
- new model uses new Qdrant collection namespace or versioned payload;
- migration can dual-write temporarily;
- cutover requires shadow search comparison before old collection deletion.

### Rebuild While Writes Continue

Expected behavior:

- rebuild takes a canonical snapshot watermark;
- worker indexes records up to watermark;
- outbox replays writes after watermark;
- search can expose `index_generation` diagnostics during rebuild.
- new generation activates only after verification; old generation remains active during rebuild.

### Projection Mapping Lost or Corrupted

Expected behavior:

- canonical records remain readable and deletable through Postgres status;
- verification marks affected projections `failed` or `stale`;
- rebuild can recreate mappings from canonical ids and deterministic adapter payloads where possible;
- if external object cannot be identified safely, adapter performs scoped generation rebuild instead of fuzzy delete.

### Projection Generation Split Brain

Problem:

```text
some workers write Qdrant generation 3 while search reads generation 2 and Graphiti is on generation 4.
```

Expected behavior:

- active generation is stored per projection type/adapter/profile;
- workers read target generation from `ProjectionRebuildJob` or active projection config;
- search includes generation diagnostics and canonical filters all candidates;
- mismatched generation is degraded/diagnostic state, not silent success.

### Projection Activation Fails Halfway

Expected behavior:

- activation is explicit, audited and idempotent;
- generation switch is committed in Postgres before clients treat it active;
- failure keeps previous generation active;
- cleanup of old generation is separate retention/maintenance work, not part of activation transaction.

### Client Cache After Forget

Expected behavior:

- context bundles include ids, versions and generated_at;
- clients must not reuse cached context after forget/update events if cache invalidation is available;
- server-side context API always canonical-filters again;
- SDK can expose cache TTL and invalidation hooks later.

### Server Context Cache After Forget

Expected behavior:

- forget/update writes canonical tombstone/status and cache invalidation before prompt-impacting cache reuse;
- cached context bundle with matching deleted fact id is rejected or rebuilt;
- cached candidate ids can be reused only after canonical filter drops deleted/superseded ids;
- diagnostics show blocked stale cache hit by id/count, not raw text.

### Grant Change While Context Is Cached

Expected behavior:

- cache key includes principal or grant version;
- grant revoke makes older cache entries unusable for that principal/profile set;
- context/search response re-checks current `ProfileGrant` before returning text;
- shared team cache never crosses principal/profile grants unless explicitly safe and tested.

### Policy Disable While Context Is Cached

Expected behavior:

- policy version is part of user-visible cache keys;
- disabling memory bypasses or invalidates prompt-time context cache immediately;
- cached diagnostics can remain visible to admins if labeled stale and raw text is hidden;
- Client App Settings and `INTERVIEW_MEMORY_FORCE_DISABLED=true` still override platform cache.

### Embedding Cache Crosses Sensitivity Boundary

Expected behavior:

- embedding cache key includes sensitivity, redaction version, provider, model and purpose;
- later secret detection marks old embedding cache unusable and schedules derived deindex;
- token-count/hash caches cannot be used to reconstruct raw restricted text;
- cache diagnostics expose hash/version/counts only.

### Cache Stampede During Large Import

Expected behavior:

- repeated identical context queries use single-flight recompute per cache key;
- waiting requests respect interactive timeout and can fall back to uncached canonical context;
- large import invalidations are batched by profile/source without hiding forget/delete events;
- cache recompute cannot consume reserved interactive capacity for unrelated profiles.

### Client Misses Event Delivery

Expected behavior:

- event delivery is at-least-once, not exactly-once;
- client stores last acknowledged cursor and can resume from it;
- if cursor expires, client receives typed `memory.cursor_expired` and must run snapshot/refetch flow;
- cached context is bounded by TTL even without event delivery;
- delete/forget remains safe because server-side context always canonical-filters.

### Forged or Replayed Connector Webhook

Expected behavior:

- signature and timestamp are checked before payload parsing;
- event id, external sequence and payload hash are stored in replay window;
- duplicate delivery returns stable accepted/deduped response;
- failed signature attempts are audited as safe metadata and rate-limited;
- no connector webhook can write outside its installation grants.

### Connector Backfill Replays Old Facts

Expected behavior:

- backfill events use source external ids and external sequence/cursor;
- tombstones and current policy are checked before materializing old facts;
- old source updates can create historical records or suggestions, not overwrite current facts silently;
- backfill can be paused/resumed from checkpoint without duplicate active facts.

### Time and Clock Skew

Expected behavior:

- keep `occurred_at`, `ingested_at` and Graphiti `reference_time` separately;
- do not trust client clock blindly for ordering critical updates;
- allow source-provided time as evidence, not transaction truth;
- sync conflict resolution uses canonical commit cursor and operation metadata before wall-clock timestamps;
- diagnostics surface suspicious time skew.

### Cross-App Idempotency Collision

Expected behavior:

- idempotency namespace includes `source_app`, `source_type`, `source_external_id` and profile;
- content hash dedupe is advisory, not the only identity;
- two apps can import same document into different profiles intentionally.

### Profile Split or Merge

Expected behavior:

- profile merge creates remap jobs for Postgres records, Qdrant payloads and Graphiti group ids;
- profile split creates new profile and reindexes selected facts/chunks;
- operations are auditable and resumable;
- retrieval must not leak between old/new profiles during migration.

### Team Permission Changes

Expected behavior:

- authorization is checked in Postgres on every API read;
- SDK caches must expire when membership changes;
- context bundles should not be shared across users unless explicitly allowed;
- audit records who accessed sensitive profile memory.

### Service Token Leak

Expected behavior:

- service tokens are scoped to explicit space/profile/actions;
- stored token verifier is salted hash, not raw token;
- tokens can be revoked without deleting the principal history;
- diagnostics never print full tokens;
- leaked token cannot hard-delete/export unless explicitly granted.

### Residency Provider Region Unknown

Expected behavior:

- provider adapter reports region capability as unknown;
- `confidential`, `secret` and `restricted` data fail closed to local-only or reject;
- public/internal data follows policy but records a `ProcessingLocationDecision`;
- diagnostics show provider, purpose and safe reason code, not prompt/document text.

### Cross-Region Export or Backup Target

Expected behavior:

- export/backup dry-run reports region mismatch before artifact creation;
- approved cross-region transfer requires explicit request, expiry and admin/security audit;
- stale artifact download re-checks current residency policy;
- restore/import into stricter destination policy creates blockers instead of relaxing policy.

### Encryption Key Rotation Failure

Expected behavior:

- key rotation is resumable and records progress by key version and aggregate type;
- records keep decryptable old key version until re-encryption succeeds;
- failed rotation moves system to degraded/admin-visible state, not data loss;
- read/delete operations continue if required old key version is available;
- export/backup refuses to proceed if required key material is missing.

### Audit Chain Tampering

Expected behavior:

- append-only audit events include previous hash and current hash;
- verification detects deleted, reordered or modified audit events;
- high-value operations can be cross-checked against outbox/tombstone/export records;
- diagnostics report chain break by event id/sequence only, without raw memory content.

### Cross-Tenant Admin Mistake

Expected behavior:

- admin operations require explicit `space_id`;
- bulk operations require dry-run count and confirmation token;
- cross-space search/export is disabled by default;
- tests seed two spaces with same profile names and assert isolation.

### Unscoped Repository Query

Expected behavior:

- repository method refuses to execute without `ScopedRepositoryContext`;
- raw SQL helper rejects access to scoped tables without compiled scope predicate;
- diagnostics record safe violation count and method name, not SQL values or memory text;
- test fixtures seed same ids/names across spaces to catch accidental broad queries.

### Connection Pool Reuses Scope Settings

Expected behavior:

- unit of work binds scope at transaction start and clears it on release;
- optional Postgres RLS settings are reset on connection checkout/checkin;
- missing or mismatched transaction scope fails closed in remote/team mode;
- worker retry rebuilds scope instead of trusting previous connection/session state.

### Quota Exhaustion

Expected behavior:

- if embedding/classifier quota is exhausted, canonical ingestion can still store source if policy allows;
- derived processing remains pending with retry/backoff;
- API returns indexing/classification status;
- policy can reject new ingestion when quota is hard-limited.

### Quota Reservation Leak

Problem:

```text
worker reserves embedding tokens, crashes before provider call, and capacity stays blocked.
```

Expected behavior:

- reservations have TTL and cleanup job;
- retry with same idempotency key reuses or replaces expired reservation safely;
- expired reservation does not count against active capacity after grace period;
- diagnostics show expired reservation count by workload class.

### Provider Usage Exceeds Estimate

Expected behavior:

- admission uses conservative estimates for model/provider calls;
- actual usage is recorded after provider response;
- overage creates safe diagnostic event and can tighten future estimates;
- hard monthly/total limits can reject further work until reset/admin override.

### Noisy Connector Starves Profile

Expected behavior:

- fairness key includes connector/principal/profile/workload;
- connector-specific quota can throttle one integration without disabling whole profile;
- interactive context has reserved capacity;
- diagnostics show top resource consumers by safe ids, not raw text.

### Quota Rule Changes While Jobs Are Queued

Expected behavior:

- queued jobs re-check current quota/policy before running;
- old reservation can be released if new rules block work;
- stricter rule prevents new provider calls but does not corrupt already committed canonical records;
- admin can dry-run quota change impact before applying it.

### Outbox Duplicate Delivery

Problem:

```text
worker crashes after writing to Qdrant/Graphiti but before marking job done
```

Expected behavior:

- retry uses same idempotency key;
- adapter upsert overwrites or detects existing mapping;
- duplicate delivery cannot create duplicate active fact;
- diagnostics show retry count but user-visible memory remains deduped.

### API Response Lost After Commit

Problem:

```text
POST /v1/facts commits a fact, then server crashes before response reaches SDK.
```

Expected behavior:

- idempotency record remains `processing` or is recoverable by operation id;
- retry with same key/fingerprint returns existing operation/result;
- no second fact is created;
- response snapshot is reconstructed from canonical target if safe and schema-compatible.

### Idempotency Fingerprint Mismatch

Expected behavior:

- same idempotency key with different normalized body returns `memory.conflict`;
- conflict response includes safe request/operation ids, not request bodies;
- no side effect starts for the mismatched request;
- SDK surfaces this as non-retryable `MemoryConflictError`.

### Operation Cancel After Partial Commit

Expected behavior:

- cancel reports committed target ids and remaining queued work;
- committed canonical records are not silently rolled back;
- pending derived work is cancelled or allowed to drain according to operation type;
- audit records cancellation reason and actor.

### Operation Polling After Retention Window

Expected behavior:

- expired operation returns safe `not_found` or `expired` status according to API policy;
- audit and canonical records remain queryable through their normal APIs;
- SDK should not treat expired operation as failed mutation;
- diagnostics expose operation retention window.

### Outbox Ordering Race

Problem:

```text
graph.upsert_fact runs after graph.delete_fact for the same fact
```

Expected behavior:

- worker uses ordering key for same aggregate/profile;
- delete/deindex jobs check tombstone before any stale upsert proceeds;
- adapter upsert reloads canonical status and skips deleted/superseded records;
- tests simulate out-of-order delivery.

### Dead Letter Jobs

Expected behavior:

- jobs exceeding max attempts move to `dead`;
- diagnostics expose event type, aggregate id, last safe error and age;
- user/admin can retry after fixing config;
- dead graph/vector jobs do not block canonical reads/writes.

### LLM Provider Drift

Expected behavior:

- classifier model, prompt version and adapter version are stored with candidates;
- evaluations catch changed classification behavior;
- important reclassification runs in shadow before replacing current facts;
- policy can pin provider/model per profile.

### Structured Output Schema Drift

Problem:

```text
classifier prompt/model starts returning a different JSON shape or different enum values.
```

Expected behavior:

- output schema validation fails closed;
- invalid output creates no facts or suggestions;
- safe diagnostics include schema id, schema version and validation error class;
- prompt/schema changes run shadow eval before becoming active;
- rollback reactivates previous prompt/schema without mutating existing facts.

### Redaction Offset Loss

Problem:

```text
redacted text is embedded/classified, but citation offsets no longer point to the raw source.
```

Expected behavior:

- redaction artifact stores offset map;
- source refs use canonical raw source ranges;
- context snippets can show redacted preview while citations resolve to protected source under authorization;
- if offset map cannot be built, redacted text can be used only as low-confidence derived evidence or blocked by policy.

### AI Provider Budget Exhaustion

Expected behavior:

- quota is checked before provider calls;
- interactive context path does not wait for budget reset;
- async jobs move to delayed/retry or source_chunk_only mode according to policy;
- diagnostics show budget class and next retry time without raw text;
- provider budget exhaustion cannot block delete/forget/export of existing canonical data.

### Vector False Positives

Expected behavior:

- vector candidates are evidence candidates, not facts;
- context packer uses score thresholds, source refs and canonical status;
- low confidence snippets are labeled or omitted;
- reranker cannot resurrect deleted/superseded data.

### Context Monopolized By One Source

Expected behavior:

- context packer enforces per-document/profile caps;
- repeated near-duplicate chunks are collapsed;
- active facts and critical constraints keep reserved budget;
- diagnostics show source cap drops.

### Legal Export and Portability

Expected behavior:

- export active memories, source refs, policies and audit metadata by default;
- optional full export can include superseded facts and tombstones;
- hard-deleted content must not reappear in export;
- export/import preserves ids or records id remapping for sync later.

Portable bundle format:

```text
bundle_manifest.json
spaces.jsonl
profiles.jsonl
threads.jsonl
facts.jsonl
fact_versions.jsonl
source_refs.jsonl
documents.jsonl
chunks.jsonl
policies.jsonl
tombstones.jsonl
audit_redacted.jsonl
objects/
  raw_files_or_redacted_files
```

Bundle manifest:

```text
bundle_id
created_at
source_server_version
schema_version
key_metadata_version
export_mode: active_only | full_history | portability | legal
included_space_ids
redaction_mode
contains_raw_sources
max_sensitivity
checksum
```

Import rules:

- import is dry-run first by default;
- id collisions produce remap plan unless importing into same server lineage;
- hard-deleted/tombstoned ids cannot be resurrected unless explicit admin override allows history-only import;
- import preserves source refs or marks facts `evidence_missing`;
- import never bypasses current destination policy/sensitivity rules.

### Backup or Snapshot Leaks Hard-Deleted Data

Expected behavior:

- hard-delete creates tombstone and schedules live data deletion plus snapshot/export retention check;
- backup retention policy defines when old encrypted blobs/snapshots expire;
- derived index snapshots are not used as canonical restore if they contain deleted data;
- legal/full-history export can include only minimal deleted metadata if policy allows;
- restore runbook verifies deleted/superseded leakage after restoring from backup.

Event cursor contract:

```text
cursor is opaque
events are ordered by canonical commit position
events include aggregate type/id/version/status
tombstones are events
payloads are production-safe by default
clients store last acknowledged cursor
```

### Future Local-to-Cloud Sync Conflict

Expected behavior:

- v1 does not implement sync, but events must be sync-friendly;
- every mutable aggregate has stable id, version and updated_at;
- deletes/tombstones participate in sync before derived indexes;
- conflict resolution prefers explicit user updates over classifier-generated updates;
- unresolved conflicts become suggestions/review items, not silent overwrites.

Sync conflict policy:

```text
same id, same version:
  no-op

same id, different version:
  compare updated_at, principal, source trust and operation kind

delete vs update:
  delete/tombstone wins unless update is explicit admin restore

classifier update vs manual update:
  manual update wins

policy conflict:
  destination stricter policy wins

profile missing:
  import/sync creates disabled profile or fails dry-run, depending mode
```

Sync-readiness invariants:

- every mutable aggregate has stable id and version;
- every event has commit position and principal/source metadata;
- tombstones are retained long enough for sync peers;
- derived Graphiti/Qdrant ids are never sync source of truth;
- sync is opt-in and out of v1 runtime behavior, but schema must not block it.

### Sync Cursor Expired

Expected behavior:

- server returns typed `memory.conflict` or `memory.unsupported`, not an empty change set;
- peer must run export/import dry-run or full resync plan;
- tombstone window expiry is visible in diagnostics;
- no checkpoint is advanced until dry-run conflicts are resolved.

### Split-Brain Local and Remote Writes

Expected behavior:

- both sides preserve source refs, principal ids, peer ids and operation kinds;
- explicit user/admin update outranks classifier-generated update when safe;
- delete/tombstone outranks generated update;
- policy/legal hold conflicts block apply and create `SyncConflict`;
- conflict status is queryable without exposing raw private text.

### Sync Bundle Partially Applied

Expected behavior:

- apply is transactional per canonical batch where possible;
- resumable apply uses change set id and aggregate version idempotency;
- derived index jobs run only after canonical apply commits;
- failed apply does not advance peer checkpoint;
- diagnostics report applied count, conflict count and blocked count.

### Sync Peer Revoked During Apply

Expected behavior:

- worker re-checks peer status before every batch;
- revoked peer stops new apply/pull immediately;
- already committed canonical changes remain auditable and are not silently rolled back;
- pending derived index jobs still follow canonical state and policy.

### Remote Server Drift From Local Docker

Expected behavior:

- SDK reads `/v1/capabilities` and refuses unsupported operations cleanly;
- server exposes schema/API version and enabled adapters;
- migrations are backward-compatible across at least one client version;
- clients can fall back to local-only or disabled mode if remote policy is incompatible.

### Server Exposed Before Bootstrap

Problem:

```text
memo_stack_server starts in a fresh DB and accepts normal API requests before owner/token setup.
```

Expected behavior:

- normal read/write endpoints return `memory.unavailable` or bootstrap-required safe status;
- only health, capabilities, bootstrap status and protected local init are available;
- bootstrap token is required and expires quickly;
- successful bootstrap locks first-admin setup permanently until explicit recovery mode.

### Bootstrap Token Reused or Leaked

Expected behavior:

- token is shown once and stored only as hash;
- used, expired or mismatched fingerprint token is rejected;
- failed attempts are rate-limited and audited without logging the token;
- leaked bootstrap token cannot hard-delete/export because normal grants are created only after successful setup.

### API and Worker Config Drift

Problem:

```text
API process allows external AI=false, worker process has external AI=true and processes queued jobs differently.
```

Expected behavior:

- every process records RuntimeConfigSnapshot hash;
- worker claims only jobs compatible with its config snapshot;
- config mismatch appears in readiness and diagnostics;
- unsafe mismatch pauses affected workload classes instead of silently processing.

### Auth Mode Downgrade

Expected behavior:

- team/remote auth mode cannot downgrade to local token by env typo;
- downgrade requires maintenance command, explicit confirmation and audit;
- existing tokens/grants are not broadened by auth mode change;
- SDK sees degraded/misconfigured status instead of continuing with weaker assumptions.

### Dev Seed or Reset Against Real Data

Expected behavior:

- seed/reset requires `local_single_user`, known local lineage and explicit confirmation;
- seed uses synthetic fixtures only;
- reset never runs automatically during startup;
- team/remote mode exposes dry-run diagnostics, not destructive dev reset.

### Migration Backfill Reintroduces Deleted Data

Problem:

```text
backfill scans old rows and writes new projection metadata for facts already tombstoned or legally held.
```

Expected behavior:

- every backfill chunk re-checks canonical status, tombstone and legal hold;
- deleted/held/unauthorized rows are counted as skipped or blocked;
- derived index jobs are scheduled only for active eligible canonical records;
- tests seed stale/deleted rows before backfill and assert zero resurrection.

### Old Worker Processes New Job Payload

Problem:

```text
old worker binary claims an outbox job written by a newer schema/contract version.
```

Expected behavior:

- job payload includes schema/contract version;
- worker compares supported versions before claim;
- incompatible job remains pending or blocked with safe diagnostics;
- migration status reports old workers that must be drained or upgraded.

### Cleanup Runs Before Compatibility Window Ends

Expected behavior:

- cleanup phase is blocked while old SDK/Client App compatibility window is active;
- admin override requires ADR, backup/export evidence and explicit audit;
- capabilities expose pending compatibility-window expiry;
- rollback boundary is documented before cleanup starts.

### Partial Migration Leaves Mixed Read Paths

Expected behavior:

- deployment enters `read_only`, `maintenance` or `degraded` with safe capabilities;
- prompt-time context uses the last verified safe read path;
- dual-read mismatch blocks contract switch;
- migration run shows current phase, blockers and next safe command.

### Duplicate Scheduler Instances

Problem:

```text
two scheduler processes wake up and both enqueue retention scan or quota cleanup.
```

Expected behavior:

- scheduled task has stable singleton lease key;
- repeated tick for the same task window reuses idempotency key;
- only one logical operation/job is created;
- duplicate attempts are counted in diagnostics without noisy errors.

### Worker SIGTERM During Adapter Write

Expected behavior:

- worker enters draining and stops new claims;
- if external side effect may have happened, retry path reconciles through ProjectionMapping or adapter idempotency key;
- quota reservation is committed/released according to actual side effect status;
- operation remains pollable with safe waiting/running status.

### Stale Worker Lease Never Expires

Expected behavior:

- heartbeat timeout marks WorkerInstance stale;
- stale leases expire after grace period;
- reclaim requires handler idempotency capability;
- diagnostics show stale worker and blocked leases without raw payload.

### Scheduled Task Flood

Expected behavior:

- scheduler applies jitter and max concurrent task limits;
- task run uses admission control and workload class;
- repeated failures move task to degraded/failed diagnostics but do not create infinite job storms;
- admin can pause task without disabling normal API reads.

### Object Storage Orphans

Expected behavior:

- file delete and DB transaction cannot be assumed atomic;
- cleanup job finds storage objects without active DB references;
- hard delete records enough metadata to avoid resurrecting old blobs;
- diagnostics show orphan count without exposing raw paths publicly.

### Upload Completed But DB Commit Fails

Expected behavior:

- uploaded object remains `pending_upload` or `uploaded`, not active;
- cleanup expires unlinked upload sessions and temporary objects;
- retry can complete the same upload session idempotently if policy allows;
- no document/import artifact becomes visible until Postgres commit records verified metadata.

### Checksum or Mime Mismatch

Expected behavior:

- object is quarantined or deleted according to policy;
- document processing does not start;
- diagnostics show validation error class, not filename/object key/raw content;
- repeated completion with same bad object does not create new records.

### Artifact Download After Permission Revoked

Expected behavior:

- download use case re-checks current grants and sensitivity policy;
- previously issued short-lived URL is not treated as authorization;
- artifact can be revoked or marked stale after grant/hard-delete/policy change;
- audit records blocked download by safe ids.

### Hard Delete While Export Artifact Exists

Expected behavior:

- hard-delete dry-run reports affected artifacts;
- active export artifact is revoked, expired or labeled stale before physical blob deletion when policy requires;
- legal/full-history artifact can keep only allowed minimal metadata;
- hard-deleted raw content must not remain downloadable through old artifact ids.

### Object Store Delete Eventually Consistent

Expected behavior:

- `delete_pending` remains until delete verification succeeds or hold blocks deletion;
- cleanup retries verification with backoff;
- normal retrieval/search treats delete_pending object as unavailable;
- diagnostics report counts by status without exposing object key.

### Derived Index Permission Leak

Problem:

```text
Qdrant or Graphiti returns a candidate id from a profile the user cannot access.
```

Expected behavior:

- every retrieval result is authorization-filtered through Postgres;
- raw adapter results are never returned directly to clients;
- diagnostics for unauthorized drops are count-only by default;
- integration tests seed forbidden data and assert zero leakage.

### SDK Contract Versioning

Expected behavior:

- OpenAPI contract is generated and versioned;
- Python/TS clients should treat unknown enum values as unsupported, not crash the app;
- breaking API changes require new route version or explicit compatibility shim;
- memory policy modes are server-declared capabilities.

### OpenAPI Drift

Problem:

```text
server changes response schema, generated SDK still compiles but runtime clients break
```

Expected behavior:

- OpenAPI spec is generated from server routes in CI;
- contract diff is reviewed in PRs;
- generated SDK smoke tests call a real memo_stack_server test instance;
- unknown enum values are handled conservatively by clients;
- compatibility routes have separate contract tests because desktop expects legacy envelopes.

### Domain Object Leaks Into Public DTO

Problem:

```text
a FastAPI route returns a domain entity or ORM model directly because it is convenient
```

Expected behavior:

- public routes return only `memo_stack_contracts` DTOs or generated equivalents;
- mapper tests fail when required source refs, status, versions, sensitivity or operation ids are dropped;
- domain refactor does not change public response shape unless schema fixture changes in the same PR;
- code review treats direct domain/ORM/adapter serialization as a release blocker.

### Null vs Missing Field Drift

Problem:

```text
server starts returning null where old clients expected a missing optional field
```

Expected behavior:

- every public DTO documents absent, null and empty-list semantics;
- generated SDK fixtures include missing field, explicit null and unknown field cases;
- server accepts old request shape within compatibility window;
- contract change that changes nullability requires fixture and SDK compatibility evidence.

### Contract Fixture Is Updated Without Behavior Change

Problem:

```text
OpenAPI/fixtures are regenerated and committed, but route behavior was not intentionally changed
```

Expected behavior:

- generated contract diffs are reviewed separately from implementation noise;
- PR description explains every public contract diff;
- accidental fixture drift blocks merge;
- release notes mention any client-visible DTO change.

### Client Retry Without Idempotency Key

Problem:

```text
client times out after POST /v1/facts, retries, and creates duplicate memory
```

Expected behavior:

- SDK generates idempotency keys for mutating requests by default;
- server stores idempotency result for a bounded retention window;
- raw HTTP clients are documented to send `Idempotency-Key`;
- duplicate mutating request returns original result or safe conflict.

### Pagination Drift

Problem:

```text
client lists facts while facts are being updated/deleted
```

Expected behavior:

- cursor is opaque and tied to stable ordering;
- deleted/superseded data remains filtered even if it existed when cursor was created;
- clients can restart pagination safely;
- list responses include `has_more` and `next_cursor`.

### Event Cursor Expired

Expected behavior:

- server returns typed `memory.cursor_expired`;
- client can restart from snapshot/export flow;
- expired cursor does not fall back to "all data" automatically;
- diagnostics tell how far retention window goes.

### Import Resurrects Deleted Data

Expected behavior:

- destination tombstones are checked before import writes;
- dry-run reports would-resurrect records;
- default import blocks resurrection;
- admin override can import only as disabled/history when policy allows.

### SDK Enum Drift

Expected behavior:

- unknown mode/status/kind maps to `Unknown(value)` or equivalent;
- client can still show diagnostics and avoid unsafe action;
- generated SDK smoke tests include future/unknown enum fixture.

### Hidden External Calls From Adapters

Problem:

```text
Graphiti or classifier adapter defaults to an external LLM/embedder even though local/private mode is expected.
```

Expected behavior:

- all external LLM/embedding providers are configured through memo_stack_server config and `MemoryPolicy`;
- local Docker defaults to `MEMORY_ALLOW_EXTERNAL_AI=false`;
- boot fails or adapter is disabled if an external provider is selected without explicit policy/config;
- telemetry opt-out is set explicitly for Graphiti in private/local deployments.

### Missing Qdrant Payload Indexes

Problem:

```text
single Qdrant collection works at small scale but filtered search becomes slow at many profiles/documents.
```

Expected behavior:

- adapter startup checks required payload indexes;
- diagnostics report missing indexes before large imports;
- load tests include filtered search by profile/document/thread;
- strict/dev mode can reject filtered queries on unindexed fields.

### Graph Backend Capability Mismatch

Expected behavior:

- Graphiti adapter reports backend type and capabilities;
- tests cover the selected v1 backend, Neo4j;
- unsupported delete/search/index behavior degrades to canonical Postgres filtering, not silent trust in graph results;
- future FalkorDB/Kuzu/Neptune support is added by capability-specific adapter configuration, not branching throughout use cases.

### Disaster Recovery Mismatch

Problem:

```text
Postgres is restored to time T, but Qdrant/Graphiti indexes are restored to time T-1 or T+1.
```

Expected behavior:

- Postgres restore is canonical;
- derived indexes can be discarded and rebuilt from Postgres/outbox;
- Qdrant snapshots are used only as acceleration, not canonical truth;
- recovery runbook verifies no deleted/superseded memories leak after restore.

### Supply-Chain Vulnerability in Parser or Adapter

Expected behavior:

- parser/OCR/document adapters run with least privilege and no macro/script execution;
- dependency lockfile and SBOM are produced for release artifacts;
- known critical vulnerability blocks remote/team release unless explicitly waived by ADR;
- optional heavy parsers are isolated behind adapter boundaries and disabled by default;
- license/security scan covers Graphiti, Qdrant client, OCR/parser and provider SDK dependencies.

### Legacy Session Id Drift

Problem:

```text
document import writes to one legacy session_id
desktop reads context from another active session_id
```

Expected behavior:

- compatibility gateway treats legacy `session_id` as `MemoryThread.external_ref`;
- desktop companion session id remains stable until explicit reset/new-session action;
- import scripts must keep requiring `--use-companion-session`, `--session-id` or `--new-session`;
- diagnostics show both legacy session id and platform thread id.

### Mode Resolver Regression

Expected behavior:

- existing env/settings precedence remains covered by tests;
- `INTERVIEW_MEMORY_FORCE_DISABLED=true` always prevents backend memory calls;
- Settings `interview_memory_enabled=false` disables memory without app restart;
- `INTERVIEW_MEMORY_FORCE_LOCAL_ONLY=true` avoids backend calls and external providers;
- legacy booleans keep working until explicitly removed in a later migration.

### Double Local Memory Paths

Problem:

```text
old local_interview_memory Postgres and new memo_stack_server local Docker both ingest the same events.
```

Expected behavior:

- integration mode chooses one write target per run;
- diagnostics report selected memory target: legacy_backend, local_db, memo_stack_server or disabled;
- dual-write is allowed only in explicit shadow comparison mode with idempotency namespace;
- no hidden second local memory path can affect prompt context.

### Legacy Response Envelope Mismatch

Expected behavior:

- compatibility endpoints return the existing `ApiSuccess<T>` envelope expected by desktop;
- `/context` returns non-empty `text` only when context is safe to inject;
- empty or invalid response degrades to fallback;
- error bodies are bounded and safe because desktop stores a sanitized excerpt.

### Desktop Timeout and Retry Budget

Expected behavior:

- compatibility route must respond within current desktop budgets or return fallback-safe status;
- context path remains low latency, around current 2 second timeout budget;
- ingest remains best-effort and non-blocking;
- slow graph/vector work is never done synchronously in desktop prompt path.

### Assistant Ingest Policy Regression

Problem:

```text
current desktop skips AiResponse ingest, but new auto-memory starts storing assistant answers.
```

Expected behavior:

- compatibility gateway preserves skip/low-trust behavior by default;
- assistant answers can become memory only through explicit policy and source support;
- auto-memory tests include "assistant hallucinated requirement" as a negative case.

## Testing Strategy

### Unit Tests

Domain:

- fact lifecycle transitions;
- version conflict;
- supersede relation;
- tombstone creation;
- source ref requirements;
- profile isolation.
- memory policy mode matrix;
- suggestion lifecycle transitions;
- auto-promotion gates.
- ontology alias resolution;
- connector provenance validation;
- reviewer grant enforcement.
- document lifecycle transition matrix;
- import/export lifecycle transition matrix;
- outbox job lifecycle transition matrix;
- policy lifecycle and historical audit rules;
- contract version compatibility matrix parser.
- contract schema registry validation;
- public DTO unknown-field and unknown-enum behavior;
- domain-to-contract mapper preserves ids, status, source refs, versions, sensitivity and operation ids.
- bootstrap state transitions and token one-time behavior;
- runtime config snapshot fingerprint and precedence rules;
- deployment mode guard for seed/reset and local bootstrap.
- migration run phase transition rules;
- backfill job idempotency, cursor and watermark behavior;
- compatibility window expiry and cleanup blocking rules.
- worker instance lifecycle and heartbeat timeout behavior;
- worker lease acquire/renew/release/expire behavior;
- scheduled task singleton lease and idempotency behavior.
- storage object lifecycle and checksum verification behavior;
- upload session expiry, abort and idempotent completion behavior;
- artifact lifecycle, expiry, revoke and download-count behavior.
- entity resolution exact/alias/ambiguous cases;
- entity merge/split audit behavior;
- temporal current/as_of/history filtering;
- evidence confidence combination and downgrade rules;
- prompt-safe context item rendering contract.
- redaction artifact and offset map behavior;
- AI provider policy/purpose/model allowlist rules;
- structured output schema validation failure behavior;
- circuit breaker state transitions.
- token hash/revocation/rotation behavior;
- key version and re-encryption state machine;
- audit hash-chain verification.
- connector installation lifecycle transitions;
- event subscription lifecycle transitions;
- webhook signature and replay-window validation.
- sync peer lifecycle and checkpoint monotonicity;
- sync change set deterministic window selection;
- sync conflict resolution ordering rules.
- memory cluster lifecycle and split/merge metadata rules;
- digest lifecycle and source invalidation behavior;
- consolidation job lifecycle and false-merge guardrails.
- usage record append-only/idempotency behavior;
- quota rule precedence and workload admission decisions;
- quota reservation lifecycle and expiry behavior.
- client operation lifecycle and cancel semantics;
- idempotency record fingerprint/replay behavior;
- operation result snapshot retention and schema version behavior.
- projection state lifecycle and generation activation rules;
- projection mapping idempotency and adapter object safety;
- projection rebuild lifecycle, pause/resume and verification behavior.
- code scope matching and promotion rules;
- code reference status transitions for current/moved/stale/deleted;
- dirty worktree trust downgrade rules.
- retention rule action matrix;
- legal hold lifecycle and precedence;
- retention job idempotency/resume behavior.
- cache key dimension and freshness decision behavior;
- cache invalidation record idempotency and overlap matching;
- cache payload safety rules for ids-only, response-safe DTO and raw-text modes.
- backup policy validation and manifest hash behavior;
- restore run lifecycle, blocker classification and PITR tombstone replay behavior.
- fact currency state, conflict record and supersession decision behavior.
- read scope construction, visibility predicate composition and visibility proof redaction behavior.
- prompt path budget split, stage timeout and degradation decision behavior.

Application:

- remember fact use case;
- update fact use case;
- forget fact use case;
- ingest episode idempotency;
- ingest document chunking contract;
- create/complete upload session use cases;
- prepare artifact download authorization and expiry behavior;
- search canonical filtering;
- context packing budget.
- configure policy with optimistic version;
- classify episode into suggestion;
- classify episode into auto-promoted fact;
- reject assistant feedback loop without primary evidence;
- block promotion after source delete;
- branch/repo scope filtering.
- legacy mode mapping from `InterviewMemoryMode` to platform capabilities;
- legacy session id to `MemoryThread.external_ref` mapping.
- lifecycle guard use cases reject invalid state transitions;
- import dry-run produces deterministic conflict report;
- export bundle includes schema, ontology, policy and tombstone versions;
- compatibility capabilities report lists every supported contract version.
- public DTO fixtures match schema registry and generated OpenAPI;
- legacy envelope mapper wraps the same result DTO as native `/v1` route;
- null, missing field and empty list semantics stay compatible for supported clients.
- validate runtime config rejects unsafe auth/provider/deployment combinations;
- bootstrap local deployment creates owner/space/profile/policy/token once;
- config mismatch between API and worker pauses incompatible workload classes.
- plan migration reports expand/backfill/dual-read/cleanup phases without mutation;
- run data backfill skips tombstoned/held records and resumes after crash;
- contract switch is blocked when dual-read fixtures disagree.
- register worker rejects incompatible config/schema versions;
- claim worker batch respects draining state, workload priority and fairness;
- run scheduled task creates one logical operation for duplicate ticks.
- complete upload blocks checksum/mime mismatch before document creation;
- artifact download re-checks current grants and sensitivity policy;
- hard-delete schedules storage object delete and artifact revoke when required.
- resolve entity use case returns `ambiguous` instead of merging across profiles/scopes;
- remember fact records confidence explanation and temporal fields;
- repeated remember/update/forget with same idempotency key returns stable operation/result;
- idempotency fingerprint mismatch returns conflict with no side effect;
- operation cancellation reports committed targets safely.
- build context labels temporal status and excludes historical facts by default;
- auto_safe requires entity/evidence/temporal confidence gates.
- external processing requires allowed purpose/provider/model and budget;
- redaction artifacts are created before allowed external processing;
- invalid classifier JSON produces diagnostics and no memory mutation;
- provider outage degrades according to policy without blocking delete/forget.
- token scope checks block export/hard_delete without explicit grant;
- key rotation preserves read/delete and fails safe when key version is missing;
- audit verification detects modified/deleted/reordered high-value events.
- register connector creates scoped principal/token and audit;
- connector pause/revoke blocks new writes immediately;
- connector event ingest rejects forged/replayed events before parsing;
- event subscription delivery is at-least-once and cache invalidation safe.
- prepare sync change set returns deterministic counts for a cursor window;
- apply sync change set dry-run creates conflicts without mutating active facts;
- revoked sync peer cannot pull, push or advance checkpoints.
- consolidate memory dry-run reports duplicate clusters without mutating active facts;
- digest refresh marks old digest stale/superseded and preserves source refs;
- build context can use reviewed clusters without hiding contradictions.
- admit work reserves budget for expensive jobs and rejects/degrades according to policy;
- quota exhaustion stores source without AI when policy allows;
- quota reservation is committed/released/expired idempotently.
- rebuild projection dry-run reports counts and does not change active generation;
- verify projection health reports drift without raw text;
- stale projection state never bypasses canonical filtering.
- resolve code scope use case normalizes repo/branch/commit/PR;
- branch/PR memory does not become global without promotion;
- code reference resolver marks stale refs instead of silently changing evidence.
- apply retention policy dry-run reports target counts without mutation;
- legal hold blocks hard-delete but allows safe retrieval hiding;
- profile deletion runs through resumable retention/delete job.
- resolve cache freshness rejects expired, invalidated and dimension-mismatched entries;
- forget/update/policy/grant changes invalidate affected context/search/rerank cache entries;
- build context with cache hit still canonical-filters status, grants, policy and temporal visibility.
- plan backup records commit position, event cursor, key versions and object inventory hash;
- validate restore reports missing keys, missing objects, tombstone conflicts and hard-delete blockers without mutation;
- apply restore into a new space preserves source refs, provenance and destination policy.
- detect fact conflict creates reviewable conflict record without changing active facts silently;
- apply supersession updates old/new fact currency, temporal fields and audit together;
- resolve current fact set excludes disputed/high-risk stale facts from normal context.
- search/list/context/export use cases require `ReadScope` and return or record `VisibilityProof`;
- denied direct reads do not reveal hidden memory existence unless endpoint policy allows forbidden diagnostics;
- access diagnostics require admin/debug grant before exposing raw text.
- build context resolves prompt path budget and returns typed degradation decision when any stage times out;
- graph/vector/rerank timeout does not block canonical fallback or prompt-safe response;
- prompt-path provider calls are blocked by default unless an ADR-enabled policy explicitly allows them.

Adapters:

- Postgres repository contract;
- Graphiti adapter with fake/integration backend;
- Qdrant adapter with test collection;
- Qdrant required payload indexes validation;
- embedding stub;
- classifier stub.
- entity resolution adapter/fake contract;
- evidence scoring adapter/fake contract;
- semantic similarity adapter/fake contract for consolidation;
- redaction adapter/fake contract;
- prompt template/schema adapter contract;
- AI provider gateway fake with budget, timeout and schema errors;
- object storage fake with checksum, missing object, delete and quarantine behavior;
- backup storage fake with manifest hash, missing object, key-missing and snapshot-mismatch behavior;
- fact currency resolver fake for contradiction, supersession and current-set tests;
- visibility guard fake for cross-profile, deleted, sensitivity and denial-leakage tests;
- prompt path budget fake with graph/vector/rerank timeout and fallback scenarios;
- webhook security fake for signature/replay tests;
- projection admin fake for rebuild/verify/generation tests;
- code reference resolver fake for rename/line-drift/symbol-move tests;
- Graphiti entity candidate mapping does not overwrite canonical entity identity.

### Integration Tests

Docker stack:

```text
Postgres + Qdrant + Graphiti backend + memo_stack_server
```

Scenarios:

- create profile;
- remember fact;
- search fact;
- update fact and verify old hidden;
- delete fact and verify stale index filtered;
- ingest document and retrieve chunk;
- profile isolation;
- worker retry.
- policy update while classification job is pending;
- suggestion approve/reject creates correct audit and indexes only approved facts;
- auto_safe does not promote conflicts or low-trust sources.
- Graphiti adapter boots with telemetry disabled in local/private config;
- external AI provider is blocked when `MEMORY_ALLOW_EXTERNAL_AI=false`;
- missing Qdrant payload index appears in diagnostics.
- legacy `/api/v1/interview-memory/ingest` maps to `IngestEpisodeUseCase`;
- legacy `/api/v1/interview-memory/context` maps to `BuildContextUseCase`;
- legacy response envelope matches current desktop bridge expectations.
- common API envelope and typed error contract tests;
- ontology endpoint and unknown kind alias contract tests;
- connector write without provenance is rejected;
- connector cannot self-approve generated suggestion without explicit policy;
- idempotency key replay returns stable result;
- cursor pagination remains stable across concurrent updates;
- export/import dry-run blocks tombstone resurrection;
- event cursor returns ordered tombstone/update events.
- authorization denies cross-space and cross-profile reads;
- service token with ingest-only scope cannot read/export/forget;
- outbox duplicate delivery is idempotent;
- outbox delete/upsert ordering race never resurrects deleted memory;
- dead-letter job appears in diagnostics and canonical reads still work.
- document lifecycle transitions survive worker crash and retry;
- suggestion lifecycle audit records policy/classifier/source versions;
- import/export lifecycle supports dry-run, cancel, retry and artifact expiry;
- contract version matrix is reflected in `/v1/capabilities`;
- API, SDK and OpenAPI fixtures remain compatible across the supported window.
- `memo_stack_contracts` schema registry matches OpenAPI components and JSON schema artifacts;
- generated SDK handles unknown enum, unknown field, missing field and explicit null fixtures;
- native `/v1` route and Client App compatibility route map to equivalent safe result DTOs.
- fresh DB reports bootstrap_required and blocks normal API traffic until setup completes;
- second bootstrap attempt and reused setup token are rejected;
- dev seed/reset refuses team/remote deployment lineage.
- migration dry-run estimates affected rows/jobs/contracts without mutation;
- old worker binary cannot claim incompatible job payload;
- cleanup phase is blocked before compatibility window expiry.
- two scheduler instances do not enqueue duplicate singleton maintenance jobs;
- worker crash after adapter side effect reconciles through idempotency/projection mapping;
- graceful shutdown checkpoint/release path leaves operation status safe.
- upload session completion verifies checksum and creates trusted StorageObject once;
- missing object makes document/artifact degraded and never prompt-visible;
- artifact download after grant revoke is blocked.
- same-name entities in different profiles remain isolated after Graphiti indexing;
- `as_of` retrieval returns historical fact while normal context excludes it;
- repeated derived summaries do not raise confidence enough for auto-promotion;
- explicit correction supersedes old fact or creates review according to currency policy;
- conflicting import creates `FactConflictRecord`, not silent overwrite;
- normal context excludes unresolved critical disputed facts while history can show them with labels;
- context bundle renders memory as evidence with `is_instruction=false`.
- external provider call is blocked in local/private mode unless explicitly allowed;
- confidential text uses redacted artifact before external classification;
- provider structured-output drift creates no suggestions/facts;
- provider circuit breaker appears in diagnostics and async jobs retry safely.
- key rotation and backup restore preserve encrypted memory access;
- audit chain verification passes after export/delete/key operations;
- revoked service token cannot read/export/forget immediately;
- hard-deleted data does not reappear after backup restore and derived index rebuild.
- backup manifest verification blocks modified object refs or missing key versions;
- restore dry-run reports tombstone/hard-delete/legal-hold blockers before any mutation;
- point-in-time restore replays retained hard-delete/tombstone records before context/search is enabled.
- every read endpoint returns safe denial or a visibility proof;
- list cursor and direct get by id do not leak hidden ids;
- admin debug diagnostics require explicit grant and audit.
- context deadline is met when Graphiti, Qdrant or rerank stage times out;
- degraded context carries machine-readable degradation decision;
- maintenance/import/rebuild load does not starve prompt-path local Docker test.
- connector install/pause/resume/revoke behavior is reflected in diagnostics;
- signed connector webhook writes once under duplicate delivery;
- event subscription receives update/delete/policy events in cursor order;
- stale client context is invalidated after forget/update event.
- server-side context cache does not return forgotten, updated, superseded or grant-revoked memory;
- cache backend outage returns recomputed/degraded context without privacy or deletion regression;
- expired invalidation replay window causes cache to fail closed and recompute.
- sync exchange endpoints return `memory.unsupported` when capability is disabled;
- sync dry-run propagates tombstones before updates and never accepts derived index ids;
- sync checkpoint does not advance after partial or conflicted apply.
- consolidation job creates proposed duplicate cluster and does not merge facts automatically;
- digest becomes stale after source delete/update and is excluded from normal context;
- low-cohesion cluster is visible in diagnostics but not used for context packing.
- noisy connector is throttled without blocking other connectors or interactive context;
- queued job re-checks quota after quota-rule update;
- provider timeout does not leak quota reservation.
- same idempotency key replay returns the same operation/result after server restart;
- idempotency fingerprint mismatch is rejected before side effects;
- cancelled long-running operation reports committed target ids and safe status.
- projection mapping is created/updated/deleted idempotently for Graphiti and Qdrant writes;
- projection rebuild with concurrent writes activates only after verification;
- projection generation mismatch appears in diagnostics and canonical filtering still hides deleted data.
- code reference resolver marks moved/stale/deleted refs correctly;
- branch-scoped facts are excluded from unrelated branch context;
- PR merge event can promote selected facts to repo scope with audit.
- retention dry-run and execution respect legal holds;
- profile delete cleanup deindexes Graphiti/Qdrant and cleans object storage or reports orphans.
- cache purge removes only derived payloads/metadata and never canonical records.

### E2E Tests

Client App:

- import large document;
- ask context query;
- verify expected facts/chunks recalled;
- update obsolete fact;
- verify old answer not used;
- forget fact;
- verify deleted fact not recalled.
- switch profile policy from suggestions to auto_safe;
- verify new safe candidate auto-promotes and old pending suggestion remains pending;
- verify disabling memory stops context injection.
- run existing production-safe memory canary against compatibility gateway;
- run existing document recall E2E against compatibility gateway;
- verify native `/v1/context` and legacy `/api/v1/interview-memory/context` agree on safe context DTO fields;
- verify old SDK/client fixture can read response from current memo_stack_server without crashing on additive fields;
- verify fresh local Docker can bootstrap first owner/profile/token and then run context/remember calls;
- verify unbootstrapped server cannot ingest/search memory through normal endpoints;
- verify `INTERVIEW_MEMORY_FORCE_DISABLED=true` prevents backend calls;
- verify Settings `interview_memory_enabled=false` disables memory without restart;
- verify missing auth falls back instead of blocking chat.
- verify legacy routes expose compatible capabilities during migration;
- verify sync exchange capability is disabled by default in v1;
- verify imported profile bundle can be searched after restart and rebuild;
- verify disabling policy while a document import is running prevents prompt-time context injection.
- verify stale architecture decision is not injected after a newer superseding decision;
- verify same-name entity from another profile is not used in interview/coding context.
- verify SDK/MCP client refetches context after memory update/delete event.
- verify branch-local coding note is not used in main branch context.
- verify retention dry-run reports stale imported document without deleting it.
- verify repeated meeting/interview notes consolidate into a digest with source refs;
- verify deleting a source document removes dependent digest from context.
- verify huge import is accepted as background job and context still returns/falls back within budget.
- verify embedding quota exhaustion does not block forget/delete/context fallback.
- verify projection rebuild after restart does not resurrect deleted facts.
- verify retry after dropped response does not create duplicate fact/document.
- verify context cache hit before forget becomes a safe miss after forget.
- verify cached context built under old grant/policy is blocked after grant revoke or policy disable.
- verify secret redaction invalidates cached embedding/rerank/context paths.
- verify same memory query as reader/admin returns correct visibility without hidden-count leakage.
- verify direct request for forbidden memory id returns safe denial with no text.
- verify context response carries visibility proof diagnostics in debug-safe form.
- verify Graphiti/Qdrant timeout returns degraded context or fallback within desktop budget.
- verify provider/rerank outage does not block Client App context response.
- verify huge import keeps prompt-context p95 within configured local budget.

Coding agent team scenario:

- store architecture decision;
- store rejected approach;
- store current task;
- search from another client;
- verify source refs.
- store branch-specific decision;
- verify another branch does not receive it as global constraint.
- store same service/package name in two repos and verify entity scope keeps results separate.
- verify rejected approach remains available as negative constraint without becoming an instruction.
- simulate Codex and GitHub connector writing same decision and verify dedupe/provenance.
- simulate two similar but different repo decisions and verify consolidation does not false-merge them.
- simulate connector revocation and verify later writes are rejected.
- simulate one connector exhausting AI quota and verify another connector can still retrieve context.
- simulate file rename/symbol move and verify stale code citation is labeled.
- simulate abandoned PR and verify its implementation notes are downranked outside branch/PR scope.
- restore Postgres from backup and rebuild Qdrant/Graphiti from canonical records.
- verify projection generation activation is audited and previous generation remains usable on failure.
- verify repeated agent queries hit cache for latency but still respect update/delete/grant changes.
- simulate disaster recovery restore and verify prompt-impacting context stays disabled until validation passes.
- restore backup created before hard-delete and verify deleted source chunks are not prompt-visible.

### Evaluation Harness

Golden dataset format:

```text
dataset_id
space_fixture
profiles[]
threads[]
documents[]
facts[]
queries[]
expected:
  must_include_memory_ids[]
  must_include_source_refs[]
  must_not_include_memory_ids[]
  stale_fact_ids[]
  deleted_fact_ids[]
  disputed_fact_ids[]
  superseded_fact_ids[]
  current_fact_group_ids[]
  cache_invalidated_fact_ids[]
  forbidden_after_grant_change_ids[]
  hidden_memory_ids[]
  denied_read_ids[]
  required_terms[]
  forbidden_terms[]
```

Eval suites:

```text
document_recall:
  early/middle/late chunks from large docs

fact_lifecycle:
  update/supersede/delete/forget behavior

profile_isolation:
  same query across profiles/spaces

source_attribution:
  returned facts cite correct source refs

negative_constraints:
  rejected approaches and "do not use X" survive filler

auto_memory_precision:
  candidates that should remain suggestions

prompt_injection:
  malicious memory text cannot become instruction

context_budget:
  important facts survive low token budgets

entity_resolution:
  same name across profiles/repos/packages stays separate

temporal_validity:
  current/as_of/history queries return different expected facts

confidence_safety:
  derived evidence does not auto-promote without trusted support

code_scope:
  repo/branch/PR/commit scoped facts only appear in matching code context

code_reference_drift:
  file rename, line drift and symbol move degrade citations safely

retention_safety:
  dry-run, legal hold and profile delete behavior are deterministic

sync_readiness:
  cursor windows, tombstones and conflict records are deterministic

consolidation_quality:
  duplicate clusters, digests and false-merge cases preserve source truth

quota_fairness:
  large imports and noisy connectors do not starve interactive context

projection_correctness:
  rebuild, generation activation and stale projection filtering preserve canonical truth

operation_idempotency:
  retries, dropped responses and cancellation preserve one logical mutation
```

Scoring:

```text
recall_at_k
precision_at_k
source_ref_accuracy
stale_leakage_rate
deleted_leakage_rate
profile_leakage_rate
entity_merge_error_rate
code_scope_leakage_rate
code_reference_stale_unlabeled_rate
temporal_leakage_rate
confidence_gate_violation_rate
forbidden_term_leakage_rate
context_budget_survival_rate
retention_hold_violation_rate
retention_orphan_count
sync_conflict_silent_apply_rate
sync_checkpoint_regression_rate
consolidation_false_merge_rate
digest_stale_leakage_rate
digest_source_ref_coverage
duplicate_active_fact_rate
quota_admission_false_allow_rate
quota_reservation_leak_rate
interactive_context_starvation_rate
noisy_neighbor_impact_rate
residency_policy_violation_rate
external_processing_region_unknown_block_rate
supply_chain_blocking_finding_count
parser_sandbox_violation_count
security_waiver_expired_count
projection_drift_rate
projection_rebuild_failure_rate
projection_generation_mismatch_rate
idempotency_duplicate_side_effect_rate
operation_replay_mismatch_rate
operation_cancel_partial_confusion_rate
```

Rules:

- every retrieval/context change runs the small golden suite;
- broad eval suite runs before changing reranker, chunking, embedding model or context packer;
- eval artifacts are production-safe and must not store raw private docs by default;
- failed evals should print ids and labels, not full sensitive text.

### Fixture Governance

Fixture categories:

```text
unit:
  tiny inline synthetic records

contract:
  stable request/response JSON without private text

golden_eval:
  synthetic docs/facts/queries with expected ids

compatibility:
  legacy Client App envelope/session fixtures

load:
  generated large docs, not checked in if huge
```

Rules:

- no real interview transcripts, private code or user documents in committed fixtures;
- fixture ids should be stable and human-readable;
- golden expected outputs should refer to ids/source refs, not long raw passages;
- large generated fixtures should have deterministic seed and generator script;
- failing tests must print fixture ids and diff summaries, not raw sensitive text.

### Verification Commands

Minimum local checks for Client App compatibility phase:

```bash
pnpm test:run -- src/stores/appConfig.sync.test.ts src/windowing/stateSync/appConfigSync.scenario.test.ts
pnpm e2e:memory-canary -- --api-url http://127.0.0.1:7788
pnpm e2e:memory-document-recall -- --api-url http://127.0.0.1:7788
pnpm e2e:companion-context -- --verify-memory --memory-api-url http://127.0.0.1:7788
```

Minimum memo_stack checks:

```bash
pytest packages/memo_stack_core/tests packages/memo_stack_server/tests
pytest packages/memo_stack_core/tests/test_fact_currency.py packages/memo_stack_server/tests/test_current_fact_context.py
pytest packages/memo_stack_core/tests/test_backup_restore.py packages/memo_stack_server/tests/test_restore_validation.py
pytest packages/memo_stack_core/tests/test_visibility_guard.py packages/memo_stack_server/tests/test_read_visibility.py
pytest packages/memo_stack_core/tests/test_prompt_path_slo.py packages/memo_stack_server/tests/test_context_deadlines.py
pytest packages/memo_stack_core/tests/test_cache_freshness.py packages/memo_stack_server/tests/test_cache_invalidation.py
pytest packages/memo_stack_core/tests/test_data_residency.py packages/memo_stack_server/tests/test_processing_location.py
pytest packages/memo_stack_core/tests/test_repository_scope.py packages/memo_stack_server/tests/test_query_scope.py
pytest packages/memo_stack_core/tests/test_supply_chain.py packages/memo_stack_server/tests/test_parser_sandbox.py
python -m memo_stack_server openapi > /tmp/memory-openapi.json
python -m memo_stack_server diagnostics --check-supply-chain --check-parser-sandbox
python -m memo_stack_server diagnostics --check-indexes --check-capabilities
python -m memo_stack_server worker --once --queue maintenance
python -m memo_stack_server eval run --suite small-golden
```

Production/staging compatibility canary:

```bash
INTERVIEW_MEMORY_AUTH_TOKEN="<token>" pnpm e2e:memory-canary -- --api-url https://api.voicetext.site
```

Document import compatibility:

```bash
pnpm memory:import-document -- --file ./profile.txt --use-companion-session --api-url http://127.0.0.1:7788
```

Avoid as default verification:

- full desktop app smoke before core API contract tests pass;
- broad production canary before local compatibility gateway passes;
- tests that store raw transcript/code/prompt text in artifacts.

### CI Gates

Required gates before merge:

```text
format/lint
type checks
unit tests
import boundary tests
contract schema registry check
contract mapper fixture tests
bootstrap/config safety tests
migration/backfill safety tests
worker/scheduler orchestration tests
storage/artifact lifecycle tests
OpenAPI deterministic diff
contract version matrix check
migration upgrade test
lifecycle transition tests
entity/temporal/confidence semantic tests
redaction/provider governance tests
data residency and processing-location tests
repository/query scope tests
key/token/audit integrity tests
connector/event delivery tests
sync-readiness contract tests
consolidation/digest quality tests
usage/quota admission tests
projection/rebuild contract tests
operation/idempotency replay tests
code scope/reference tests
retention/legal hold tests
small golden eval
dependency lock check
SBOM generation check
license/security scan
parser sandbox policy tests
security waiver expiry test
synthetic fixture safety check
```

Adapter PR gates:

```text
Postgres adapter:
  migration up/down or forward-only migration verification
  repository contract tests
  encrypted field/key version tests
  audit chain verification tests

Qdrant adapter:
  payload index diagnostics
  stale/delete filtering test

Graphiti adapter:
  telemetry disabled check
  capability report
  profile isolation test
  entity candidate mapping test
  explicit provider registry configuration test

Client App compatibility:
  legacy envelope contract
  existing canary scripts
```

SDK/API contract gates:

```text
typed error fixture tests
unknown enum fixture tests
unknown field/nullability fixture tests
domain-to-contract mapper tests
idempotency replay test
cursor pagination drift test
capabilities compatibility test
contract version compatibility test
connector lifecycle contract test
event delivery/cache invalidation contract test
export/import dry-run test
SDK supported-window fixture test
context item schema fixture test
classifier structured-output schema fixture test
```

Bootstrap/config gates:

```text
fresh DB bootstrap-required test
one-time bootstrap token test
first owner/space/profile provisioning test
auth mode downgrade rejection test
API/worker config hash mismatch test
dev seed/reset deployment guard test
config status safe-output test
```

Migration/upgrade gates:

```text
migration dry-run fixture test
expand/backfill/dual-read/cleanup phase test
backfill crash/resume test
backfill tombstone/legal-hold skip test
old worker incompatible payload rejection test
compatibility window cleanup block test
post-migration OpenAPI/SDK fixture test
derived projection migration rebuild test
```

Worker/scheduler gates:

```text
worker registration and heartbeat test
worker lease reclaim after stale heartbeat test
graceful shutdown drain test
unsupported job version claim rejection test
duplicate scheduler singleton task test
scheduled task flood/backoff test
external side-effect reconciliation test
```

Storage/artifact gates:

```text
upload checksum and size verification test
mime/policy quarantine test
missing object degraded diagnostics test
artifact revoke/expiry access test
hard-delete object deletion verification test
object key redaction in diagnostics test
```

Release gates:

```text
version bump
changelog entry
OpenAPI artifact
SDK generation smoke
docker image build
SBOM/security scan when moving outside local-only dev
```

### Evaluation Metrics

Measure:

```text
recall@k
precision@k
source attribution accuracy
stale fact leakage rate
deleted fact leakage rate
disputed fact current-context leakage rate
current fact resolver accuracy
supersession correctness rate
visibility proof coverage rate
denied read existence leakage rate
query_scope_missing_proof_rate
unscoped_query_blocked_count
server cache stale/forbidden hit blocked count
profile leakage rate
entity merge error rate
code scope leakage rate
code reference stale unlabeled rate
temporal leakage rate
confidence gate violation rate
context budget efficiency
context budget survival rate
prompt_path_deadline_miss_count
prompt_path_degraded_response_rate
prompt_path_stage_timeout_count
prompt_path_fallback_success_rate
redaction_offset_accuracy
provider_schema_validation_failure_count
provider_circuit_breaker_open_count
key_rotation_failed_count
audit_chain_verification_failed_count
token_revocation_lag_ms
connector_replay_rejected_count
event_delivery_lag_ms
event_delivery_failure_count
client_cache_stale_hit_count
code_scope_filter_drop_count
code_reference_stale_count
retention_job_failed_count
retention_held_target_blocked_count
retention_orphan_count
sync_conflict_silent_apply_count
sync_checkpoint_regression_count
sync_capability_disabled_violation_count
consolidation_false_merge_count
consolidation_duplicate_cluster_count
digest_stale_leakage_count
digest_source_ref_coverage
duplicate_active_fact_rate
quota_admission_false_allow_count
quota_reservation_leak_count
interactive_context_starvation_count
noisy_neighbor_throttle_count
residency_policy_violation_count
processing_location_denied_count
external_processing_unknown_region_block_count
cross_region_transfer_review_count
projection_drift_count
projection_rebuild_failed_count
projection_generation_mismatch_count
idempotency_duplicate_side_effect_count
operation_replay_mismatch_count
operation_cancel_partial_confusion_count
contract_schema_drift_count
contract_mapper_missing_field_count
bootstrap_open_endpoint_count
config_drift_blocked_job_count
unsafe_dev_reset_blocked_count
migration_backfill_resume_failure_count
migration_dual_read_mismatch_count
old_worker_incompatible_claim_count
worker_lease_reclaim_count
worker_graceful_shutdown_failure_count
scheduled_task_duplicate_suppressed_count
storage_object_missing_count
storage_checksum_mismatch_count
artifact_revoked_download_blocked_count
indexing latency
suggestion precision
auto-promotion false positive rate
policy violation rate
missing payload index count
external call blocked count
external call redaction required count
legacy compatibility fallback count
legacy mode mapping violation count
authorization denial leakage count
outbox duplicate side-effect count
dead outbox job age
source ref accuracy
forbidden term leakage rate
context instruction leakage rate
secret embedding remediation count
```

Minimum gates for v1:

- deleted fact leakage: 0 in tests;
- disputed fact leakage into current constraints: 0 in tests;
- supersession correctness failures: 0 in curated update tests;
- cross-profile leakage: 0 in tests;
- source ref coverage for facts: 100%;
- policy violation rate: 0 in tests;
- authorization leakage: 0 in tests;
- visibility proof missing on guarded read paths: 0 in tests;
- denied read existence leakage: 0 in tests;
- query scope missing proof on guarded repository methods: 0 in tests;
- unscoped scoped-table repository queries allowed: 0 in tests;
- prompt path hard-deadline misses: 0 in compatibility/local Docker tests;
- prompt path unsafe degraded responses: 0 in tests;
- prompt path fallback success rate: tracked and should not regress;
- outbox duplicate side effects: 0 in tests;
- entity merge errors: 0 in curated same-name tests;
- temporal leakage: 0 in current-context curated evals;
- confidence gate violations: 0 in auto_safe curated safety set;
- context instruction leakage: 0 in prompt-injection evals;
- redaction offset errors: 0 in redaction/citation tests;
- provider schema drift mutations: 0 facts/suggestions created from invalid structured output;
- secret external-processing leaks: 0 in tests;
- key rotation data loss: 0 in tests;
- backup manifest integrity failures accepted: 0 in tests;
- restore prompt-visible before validation: 0 in tests;
- hard-deleted content resurrected after restore: 0 in tests;
- audit chain verification failures: 0 after normal operations;
- revoked token successful accesses: 0 in tests;
- forged/replayed connector events accepted: 0 in tests;
- event ordering violations: 0 in subscription tests;
- stale client cache hits after invalidation: 0 in tests;
- server cache stale/forbidden hits returned to user: 0 in tests;
- cache invalidation lag for forget/grant/policy safety paths: 0 unsafe responses in tests;
- residency policy violations: 0 in storage/provider/export/backup/sync tests;
- external processing with unknown region for restricted data: 0 allowed calls in tests;
- critical/high dependency findings without active waiver: 0 in remote/team release gates;
- parser sandbox network/macro/resource violations create active memory: 0 in tests;
- code scope leakage: 0 in curated branch/repo tests;
- stale code references without label: 0 in code-reference evals;
- legal hold violations: 0 in retention tests;
- retention hard-delete without dry-run: 0 in team/remote tests;
- retention orphan count: 0 after successful profile delete test;
- sync silent conflict applies: 0 in dry-run/apply tests;
- sync checkpoint regressions: 0 in checkpoint tests;
- sync capability disabled violations: 0 in v1 tests;
- consolidation false merges: 0 in curated same-name/same-topic tests;
- stale digest leakage: 0 in normal context tests;
- digest source ref coverage: 100% for active digests;
- duplicate active fact rate: tracked and should not regress after consolidation jobs;
- quota reservation leaks: 0 in worker crash tests;
- interactive context starvation: 0 in large-import/noisy-connector tests;
- quota false allows past hard limit: 0 in admission tests;
- projection drift after verified rebuild: 0 in projection tests;
- projection generation mismatch leaks: 0 in search/context tests;
- rebuild activation failure data loss: 0 in generation activation tests;
- duplicate side effects from idempotent replay: 0 in API/SDK tests;
- operation replay mismatches: 0 in response snapshot tests;
- partial cancel ambiguity: 0 in operation cancel tests;
- contract schema drift: 0 in API/SDK/fixture checks;
- mapper missing required public fields: 0 in mapper tests;
- normal endpoint access before bootstrap: 0 in bootstrap tests;
- unsafe config drift job processing: 0 in API/worker config tests;
- unsafe dev reset/seed against non-local lineage: 0 in tests;
- backfill duplicate or skipped-resume errors: 0 in migration tests;
- old worker incompatible job claims: 0 in migration tests;
- cleanup before compatibility window expiry: 0 in migration tests;
- duplicate singleton scheduled task side effects: 0 in scheduler tests;
- unrecoverable worker lease leaks after stale heartbeat: 0 in worker tests;
- graceful shutdown data loss: 0 in worker shutdown tests;
- trusted document created from invalid upload: 0 in storage tests;
- artifact downloads after revoke/expiry: 0 in artifact tests;
- raw object key leakage in diagnostics: 0 in storage tests;
- stale/deleted/forbidden leakage: 0 in curated evals;
- source ref accuracy: 100% on curated fact tests;
- auto-promotion false positive target: start with 0 on curated safety set;
- document recall target: project-specific benchmark, initially > 90% on curated set;
- precision target: track separately, do not optimize only recall.

## Observability

Logs:

- request id;
- principal id and auth mode;
- space/profile/thread ids;
- use case name;
- outbox job id;
- outbox idempotency key and ordering key when safe;
- adapter latency;
- candidate counts;
- canonical filter drops;
- packer drops.
- selected memory target: disabled, legacy_backend, local_db, memo_stack_server;
- resolved legacy mode and platform policy mode;
- legacy session id and platform thread id mapping.
- entity resolution status and ambiguity count;
- temporal filter mode and historical drop count;
- fact currency status, conflict count, supersession decision id and current resolver version without raw text.
- confidence gate decisions without raw text.
- processing-location decision id, purpose, region and safe denial code without raw text.
- provider/purpose/model id, prompt/schema version and circuit breaker state without raw prompts;
- admission decision, workload class, quota rule ids and reservation id without raw prompt/document text.
- redaction artifact ids and counts, not redacted secret values.
- connector id/source stream/sync state without raw payload;
- event subscription delivery status, cursor and lag.
- sync peer id, checkpoint cursor, change set id and conflict counts without raw memory text.
- consolidation job id, cluster count, digest count, stale digest count and false-merge guardrail score.
- projection state counts, active generation, rebuild job id, drift count and adapter capability version.
- operation id/type/status, idempotency record status and replay snapshot id without request body.
- contract schema id/version and mapper name for public responses without raw body.
- bootstrap state, deployment mode and config hash without raw env or token values.
- migration run id/phase/status, backfill cursor/counts and compatibility window ids without raw data.
- worker id/group/status, heartbeat age, lease counts and scheduled task status without raw payload.
- storage object id/purpose/status/checksum state and artifact status without raw object key.
- backup run id/status/manifest hash, restore run id/status/blocker counts and key/object availability without raw payload.
- read scope purpose, visibility proof id/hash, denied-read safe reason and drop counts without hidden record text.
- prompt path run id, client kind, stage timings, deadline, degradation mode and fallback reason without raw prompt or memory text.
- cache kind, cache hit/miss/freshness decision, invalidation cursor and blocked stale-hit count without raw payload.
- code scope match/drop reason and stale code-reference counts.
- retention job status, dry-run counts, held target counts and orphan cleanup counts.

Metrics:

```text
memory_api_requests_total
memory_api_latency_ms
memory_outbox_pending
memory_outbox_failed
memory_graph_index_latency_ms
memory_vector_index_latency_ms
memory_search_candidates_count
memory_search_filtered_count
memory_context_tokens
memory_missing_payload_indexes
memory_external_ai_blocked_total
memory_external_ai_redaction_required_total
memory_ai_provider_schema_validation_failed_total
memory_ai_provider_circuit_open_total
memory_redaction_artifacts_created_total
memory_redaction_offset_error_total
memory_key_rotation_failed_total
memory_backup_run_failed_total
memory_backup_manifest_verify_failed_total
memory_restore_validation_blocked_total
memory_restore_missing_key_version_total
memory_restore_missing_object_total
memory_restore_hard_delete_conflict_total
memory_audit_chain_verification_failed_total
memory_token_revocation_lag_ms
memory_visibility_proof_missing_total
memory_denied_read_existence_leakage_total
memory_visibility_filter_drop_total
memory_prompt_path_deadline_miss_total
memory_prompt_path_degraded_total
memory_prompt_path_stage_timeout_total
memory_prompt_path_fallback_success_total
memory_prompt_path_p95_latency_ms
memory_connector_replay_rejected_total
memory_event_delivery_lag_ms
memory_event_delivery_failed_total
memory_client_cache_stale_hit_total
memory_server_cache_hit_total
memory_server_cache_miss_total
memory_server_cache_stale_hit_blocked_total
memory_server_cache_forbidden_hit_blocked_total
memory_server_cache_invalidation_lag_ms
memory_server_cache_stampede_suppressed_total
memory_server_cache_payload_missing_total
memory_server_cache_orphan_payload_total
memory_sync_conflict_silent_apply_total
memory_sync_checkpoint_regression_total
memory_sync_capability_disabled_violation_total
memory_consolidation_false_merge_total
memory_consolidation_jobs_failed_total
memory_digest_stale_leakage_total
memory_digest_source_ref_coverage
memory_duplicate_active_fact_rate
memory_quota_reservation_active_total
memory_quota_reservation_expired_total
memory_quota_reservation_leak_total
memory_quota_admission_decision_total
memory_interactive_context_starvation_total
memory_noisy_neighbor_throttled_total
memory_projection_drift_total
memory_projection_rebuild_failed_total
memory_projection_generation_mismatch_total
memory_projection_stale_total
memory_idempotency_duplicate_side_effect_total
memory_operation_replay_mismatch_total
memory_operation_cancel_partial_confusion_total
memory_client_operation_active_total
memory_contract_schema_drift_total
memory_contract_mapper_missing_field_total
memory_bootstrap_open_endpoint_total
memory_config_drift_blocked_job_total
memory_unsafe_dev_reset_blocked_total
memory_migration_backfill_resume_failure_total
memory_migration_dual_read_mismatch_total
memory_old_worker_incompatible_claim_total
memory_worker_lease_reclaim_total
memory_worker_graceful_shutdown_failed_total
memory_scheduled_task_duplicate_suppressed_total
memory_storage_object_missing_total
memory_storage_checksum_mismatch_total
memory_artifact_revoked_download_blocked_total
memory_code_scope_filter_drop_total
memory_code_reference_stale_total
memory_retention_job_failed_total
memory_retention_held_target_blocked_total
memory_retention_orphan_total
memory_graph_capability_mismatch_total
memory_legacy_compat_requests_total
memory_legacy_compat_fallback_total
memory_selected_target
memory_authz_denied_total
memory_query_scope_missing_proof_total
memory_unscoped_query_blocked_total
memory_maintenance_scope_override_total
memory_rls_policy_violation_total
memory_dependency_blocking_finding_total
memory_parser_sandbox_violation_total
memory_release_attestation_blocked_total
memory_security_waiver_expired_total
memory_quota_rejected_total
memory_outbox_dead_age_seconds
memory_outbox_duplicate_suppressed_total
memory_eval_recall_at_k
memory_eval_source_ref_accuracy
memory_context_budget_survival_rate
memory_entity_ambiguous_total
memory_entity_merge_error_eval_rate
memory_temporal_filtered_total
memory_fact_conflict_open_total
memory_fact_supersession_applied_total
memory_fact_currency_disputed_leakage_total
memory_current_fact_resolver_mismatch_total
memory_confidence_gate_blocked_total
memory_context_instruction_leakage_eval_rate
memory_secret_embedding_remediation_total
memory_document_processing_errors_total
memory_ai_token_usage_total
```

Diagnostics endpoint:

```text
GET /v1/diagnostics/profile/{profile_id}
```

Production-safe by default:

- counts;
- statuses;
- ids;
- no raw text unless debug auth/scope enabled.

## Rollback and Kill Switches

Memo stack rollout must be reversible at each layer.

Desktop/user-facing rollback:

```text
Settings AppConfig.interview_memory_enabled=false
INTERVIEW_MEMORY_FORCE_DISABLED=true
INTERVIEW_MEMORY_MODE=disabled
INTERVIEW_MEMORY_ENABLED=false
INTERVIEW_MEMORY_ACTIVE_CONTEXT=false
```

Backend/provider rollback:

```text
MEMORY_ALLOW_EXTERNAL_AI=false
GRAPHITI_TELEMETRY_ENABLED=false
disable Graphiti adapter
disable Qdrant adapter
run Postgres-only canonical mode
```

Migration rollback:

```text
pause migration/backfill jobs
keep old compatible read path active
enter read_only or maintenance when schema safety is uncertain
rollback only before destructive cleanup or irreversible transformation
resume from migration cursor after fix
```

Integration rollback:

```text
point INTERVIEW_MEMORY_API_URL back to existing backend
disable compatibility gateway prompt impact
keep ingest shadow-only
fall back to minimal current-session context
```

Rules:

- rollback must not delete data automatically;
- disabling retrieval must not disable delete/status/admin diagnostics;
- Postgres-only mode must still allow remember/update/forget by id;
- migration rollback must respect compatibility window and audit boundaries;
- desktop prompt path must fail closed to fallback context, not block the interview/chat.

## Risk Register

| Risk | Severity | Likelihood | Mitigation |
|---|---:|---:|---|
| Cross-profile or cross-space leakage | 10 | 4 | canonical authz filter, profile grants, isolation tests |
| Endpoint forgets visibility guard | 10 | 4 | mandatory `ReadScope`/`VisibilityProof`, endpoint contract tests, repository predicate checks |
| Repository method forgets scope predicate | 10 | 4 | `RepositoryScope`, scoped repository context, query proof and unscoped SQL tests |
| Maintenance/bulk job mutates wrong space/profile | 10 | 3 | maintenance scope override, dry-run counts, scoped worker payloads and bulk mutation tests |
| Denied read reveals hidden memory existence | 9 | 4 | denied-read policy, safe errors, probe tests and rate-limit metrics |
| Deleted/superseded memory appears in context | 10 | 4 | Postgres status wins, stale index filtering, delete race tests |
| Contradicted fact remains active | 9 | 5 | conflict records, current fact resolver, disputed-current leakage tests |
| Weak source silently supersedes strong fact | 9 | 4 | source trust policy, supersession decision review gates and rollback tests |
| Context path misses live workflow deadline | 9 | 5 | prompt-path budget, stage timeouts, degraded response and fallback tests |
| Degraded context is over-trusted as complete | 8 | 4 | typed degradation decision, response metadata and SDK handling tests |
| Auto-memory stores hallucinated assistant output | 9 | 5 | assistant as derived evidence, suggestions default, false-positive eval |
| Secret/restricted data sent to external provider | 10 | 3 | sensitivity model, external AI policy gate, secret detector before embedding |
| Data leaves allowed residency boundary | 10 | 3 | residency policy, processing-location decisions, provider region checks and artifact transfer tests |
| Unknown provider region is treated as safe | 9 | 4 | fail-closed rules for sensitive data, provider capability diagnostics and local-only fallback |
| Provider prompt/schema drift mutates memory | 9 | 4 | versioned prompt/schema, strict validation, shadow eval, rollback |
| Redaction breaks citations or leaks secrets | 10 | 3 | redaction artifacts, offset maps, remediation tests |
| AI cost spike from auto-memory/import | 8 | 5 | provider quotas, circuit breakers, workload classes, diagnostics |
| Key loss makes encrypted memory unreadable | 10 | 2 | key versions, decrypt-only old keys, backup restore key checks |
| Backup restore resurrects hard-deleted memory | 10 | 3 | backup manifest, deletion ledger, PITR tombstone replay and restore leakage tests |
| Backup artifact becomes weaker hidden data store | 10 | 3 | artifact auth, sensitivity inheritance, key policy, retention and access audit |
| Backup/export/import bypasses residency | 10 | 3 | region dry-run blockers, cross-region transfer review and artifact download-time checks |
| Restore proceeds with missing blobs or keys | 9 | 4 | restore validation blockers, degraded restore mode and object/key inventory checks |
| Audit tampering hides destructive action | 9 | 3 | append-only audit, hash chain, chain verification |
| Supply-chain issue in parser/provider SDK | 8 | 4 | lockfiles, SBOM, vulnerability/license scan, adapter sandboxing |
| Parser sandbox escape or resource exhaustion | 9 | 3 | network-deny sandbox policy, CPU/memory/time limits, quarantine and parser-run tests |
| Security waiver never expires | 8 | 4 | scoped expiring waiver, release attestation and waiver-expiry CI gate |
| Forged/replayed connector event writes memory | 9 | 4 | webhook signatures, replay window, connector grants, idempotency |
| Client cache uses deleted/updated memory | 9 | 4 | event subscription, TTL, canonical filtering, invalidation tests |
| Server cache returns deleted or forbidden memory | 10 | 3 | cache freshness use case, canonical re-check, invalidation cursor and stale-hit blocked tests |
| Cache key misses grant or policy dimension | 9 | 4 | cache key dimension tests, grant/policy version in metadata, fail-closed freshness checks |
| Cache stampede starves context path | 7 | 4 | single-flight recompute, timeout fallback, reserved interactive capacity metrics |
| Local and remote memory diverge silently | 9 | 4 | sync feature gate, deterministic change sets, conflict records, checkpoint tests |
| Consolidation false-merges distinct facts | 9 | 4 | proposed clusters first, guardrail score, source/entity/scope checks, split tests |
| Digest hides contradictions or stale sources | 8 | 5 | digest lifecycle, source invalidation, derived evidence labels, stale digest tests |
| Quota reservation leak blocks useful work | 8 | 4 | reservation TTL, cleanup job, idempotent release/commit tests |
| Noisy connector or import starves interactive context | 9 | 4 | fairness keys, reserved interactive capacity, workload admission tests |
| Derived projection drift hides or resurrects memory | 10 | 3 | projection state/mapping, canonical filtering, rebuild verification tests |
| Rebuild generation activation loses data | 9 | 3 | source watermark, old generation fallback, explicit activation audit |
| API retry duplicates a committed mutation | 10 | 4 | idempotency record, operation ledger, response snapshot replay tests |
| Long-running operation status lies to SDK | 8 | 4 | client operation lifecycle, safe progress, cancel/partial commit tests |
| Public DTO schema drifts from domain/use cases | 9 | 5 | `memo_stack_contracts`, mapper tests, golden fixtures, OpenAPI diff |
| Server starts open before bootstrap | 10 | 3 | explicit bootstrap state, one-time setup token, normal endpoint lock tests |
| API and worker use incompatible config | 9 | 4 | runtime config snapshots, config hash diagnostics, worker claim compatibility checks |
| Dev seed/reset touches real data | 10 | 2 | deployment lineage guard, synthetic-only fixtures, explicit confirmation tests |
| Migration/backfill corrupts canonical data | 10 | 3 | phased migration model, dry-run, idempotent backfills, tombstone/legal-hold checks |
| Old worker processes new payload schema | 9 | 4 | payload version checks, worker compatibility gates, migration lock diagnostics |
| Cleanup removes old contract too early | 8 | 4 | compatibility windows, cleanup phase guard, SDK/Client App fixture gates |
| Duplicate scheduler runs maintenance twice | 8 | 4 | scheduled task singleton leases, idempotency keys, duplicate tick tests |
| Worker crash leaves stuck lease or quota | 8 | 5 | heartbeat expiry, lease reclaim, quota release/commit reconciliation tests |
| Graceful shutdown loses progress | 8 | 4 | worker draining lifecycle, checkpoint rules, shutdown integration tests |
| Raw blob leaks or remains after hard-delete | 10 | 3 | StorageObject lifecycle, hard-delete verification, object key redaction tests |
| Corrupted or hostile upload becomes trusted document | 9 | 4 | checksum/mime/quarantine gates, parser safety tests, upload completion tests |
| Export artifact outlives permissions or deletion | 9 | 4 | artifact revoke/expiry, download-time auth checks, hard-delete artifact tests |
| Connector backfill resurrects obsolete facts | 8 | 4 | sync checkpoints, tombstone checks, policy re-check before materialization |
| Branch-local coding memory leaks into mainline context | 9 | 4 | CodeScope filters, promotion rules, branch leakage eval |
| Code citation points to wrong code after refactor | 8 | 5 | CodeReference content hash, symbol resolver, stale labels |
| Retention deletes useful or held memory | 9 | 3 | dry-run, legal hold checks, high-importance review gate |
| Profile deletion leaves data or index orphans | 8 | 4 | retention/delete job, orphan diagnostics, derived deindex tests |
| Outbox duplicate delivery creates duplicate graph/vector data | 8 | 5 | idempotency keys, adapter mapping tables, duplicate delivery tests |
| Graphiti backend behavior differs from assumptions | 8 | 5 | spike gate, capabilities, canonical filtering, backend-specific tests |
| Qdrant filter performance degrades with scale | 7 | 5 | payload indexes, diagnostics, load tests |
| Client App prompt path regresses | 9 | 4 | compatibility gateway first, existing canaries, fallback-only failure |
| Large import starves interactive context | 8 | 4 | workload queues, priority, quotas, backpressure |
| Eval suite gives false confidence | 7 | 5 | negative cases, source-ref accuracy, stale/deleted leakage gates |
| Plan scope becomes unreviewable | 8 | 6 | PR roadmap, MVP cutline, forbidden changes per phase |

Risk review cadence:

- update this table after every phase;
- add a mitigation before accepting a new high-severity risk;
- do not ship prompt-impacting behavior with unresolved severity 9-10 risk.

## ADR and PR Discipline

ADR required for:

- changing source of truth;
- adding/removing a storage engine;
- changing memory policy modes;
- enabling external AI by default;
- changing compatibility route behavior;
- changing fact lifecycle semantics;
- changing fact currency, contradiction or supersession resolution semantics;
- changing SDK public contract.
- changing canonical public DTO ownership, schema registry or mapper rules;
- changing bootstrap, auth-mode, config precedence or deployment mode behavior;
- changing read-path visibility, denied-read policy or debug raw-text access behavior;
- changing repository scope, query-proof or maintenance override semantics;
- changing prompt-path SLO, fallback order, degradation modes or stage budget defaults;
- changing migration phase model, compatibility windows or data backfill semantics;
- changing worker lease, scheduler, shutdown or job claim semantics;
- changing storage object, upload session, artifact download or object-delete verification semantics;
- changing backup policy, backup manifest, restore validation or disaster recovery semantics;
- changing data residency, processing-location or cross-region transfer semantics;
- changing dependency/license/security gate, parser sandbox or release attestation semantics;
- enabling a new external AI provider/purpose;
- changing quota/admission defaults for expensive or prompt-path work;
- changing projection generation, rebuild activation or adapter mapping semantics;
- changing operation/idempotency replay semantics or operation retention window;
- changing classifier prompt/schema used for auto-promotion;
- adding connector source app with write capability;
- changing event delivery or cache invalidation contract;
- adding server-side context/search/rerank caching or changing cache freshness dimensions;
- enabling sync exchange apply mode or changing sync conflict resolution;
- enabling automatic fact merge/delete through consolidation;
- changing digest generation policy or treating digests as fact evidence;
- changing destructive retention defaults or legal hold behavior;

ADR template:

```text
Title
Status: proposed | accepted | superseded
Date
Context
Decision
Alternatives considered
Consequences
Rollback
Links to eval/test evidence
```

PR description must include:

```text
Memory mode impact:
Data ownership impact:
Adapters touched:
Auth/privacy impact:
Data residency impact:
Read visibility impact:
Repository/query scope impact:
Supply-chain/parser impact:
Prompt-path SLO impact:
Fact currency/conflict impact:
Outbox/retry impact:
OpenAPI/SDK impact:
Contract schema impact:
Bootstrap/config impact:
Migration/backfill impact:
Worker/scheduler impact:
Storage/artifact impact:
Backup/restore impact:
Cache/freshness impact:
Eval impact:
Rollback:
Verification commands:
```

Rules:

- behavior-changing PRs must include at least one regression test or explicit reason why not;
- prompt-impacting PRs require eval output;
- adapter PRs require capability diagnostics;
- public DTO changes require fixture diff, mapper tests and SDK compatibility evidence;
- bootstrap/config changes require first-boot, auth downgrade and config drift tests;
- migration/backfill changes require dry-run, crash/resume, old-worker and cleanup-window tests;
- worker/scheduler changes require heartbeat, singleton, lease reclaim and graceful shutdown tests;
- storage/artifact changes require checksum, quarantine, delete verification and artifact revoke tests;
- backup/restore changes require manifest, key availability, PITR and hard-delete resurrection tests;
- residency/provider-placement changes require storage, provider, backup/export/import and sync denial tests;
- cache/freshness changes require forget, update, grant revoke and policy change invalidation tests;
- read-path changes require visibility proof, denial leakage and cross-profile/deleted filtering tests;
- repository/query-scope changes require unscoped query, bulk mutation, worker scan and optional RLS tests;
- dependency/parser changes require SBOM, vulnerability/license scan, sandbox and waiver-expiry tests;
- prompt-path changes require deadline, degraded response, fallback and stage-timeout tests;
- fact currency changes require conflict, supersession, current-set and history/current context tests;
- generated files should be isolated in separate commits or PRs when possible.

## Implementation Phases

### MVP Cutline

V1 target is a reusable memo stack that can run locally and be integrated safely. V1 is not a full SaaS and not a full Zep competitor.

Must include in V1:

```text
memo_stack_core domain
memo_stack_server HTTP API
canonical Postgres fact lifecycle
fact currency and conflict resolution
profiles/threads/policies/principals
remember/update/forget/search basics
outbox with idempotency and leases
sync-ready ids, tombstones and event cursor semantics
Qdrant document/chunk retrieval
object storage lifecycle for large files and artifacts
Graphiti adapter behind port
context builder with source refs
Client App client compatibility gateway
small golden eval suite
local Docker
backup manifest and restore dry-run guardrails
prompt-path SLO and degradation guardrails
data residency and processing-location guardrails
```

May be postponed after V1:

```text
full Memory Studio UI
multi-region sync
bidirectional local-to-cloud sync exchange
billing/team SaaS admin
automatic profile classification
OCR/image document extraction
advanced graph visualization
multi-graph-backend production support beyond Neo4j
hard enterprise compliance workflows
```

Hard stop conditions:

- no Graphiti/Qdrant adapter until `memo_stack_core` import boundaries are enforced by tests;
- no public API expansion until `memo_stack_contracts` schema registry and mapper tests exist;
- no local Docker release until first bootstrap, config doctor and dev reset guards pass;
- no data migration/backfill rollout until dry-run, crash/resume and compatibility-window gates pass;
- no background worker rollout until worker lease, scheduler singleton and shutdown gates pass;
- no auto-update/supersede rollout until fact currency, conflict and current-set tests pass;
- no large document/import/export rollout until storage object, upload checksum, artifact revoke and delete verification gates pass;
- no backup/restore rollout until manifest verification, key availability, object inventory and hard-delete restore tests pass;
- no remote/team deployment until data residency, processing-location and artifact transfer denial tests pass;
- no remote/team deployment until repository scope, query proof, unscoped SQL and maintenance override tests pass;
- no remote/team deployment until dependency inventory, SBOM, license/security scan, parser sandbox and waiver-expiry tests pass;
- no new read endpoint rollout until it has `ReadScope`, `VisibilityPredicate`, `VisibilityProof` and denial-leakage tests;
- no prompt-impacting context rollout until deadline, stage-timeout, degraded response and fallback tests pass;
- no mutating API rollout until operation/idempotency replay tests pass;
- no server-side context/search cache rollout until cache freshness, forget, update, grant revoke and policy disable tests pass;
- no prompt-impacting Client App switch until compatibility canary and document recall pass against memo_stack_server;
- no auto_safe default until suggestion mode and false-positive evals pass;
- no automatic consolidation merge/delete until digest/cluster false-merge evals pass;
- no large imports/auto-memory/external AI until quota admission, storage artifact and reservation tests pass;
- no external AI default until sensitivity, policy and quota gates are implemented;
- no sync exchange apply mode until a sync ADR, dry-run tests and conflict-review flow exist;
- no remote/team deployment until authz/profile grants, repository scope, key/token/audit integrity, residency guardrails, supply-chain/parser gates and backup/rebuild runbook pass tests.

### PR Roadmap

Recommended PR sequence:

1. Core skeleton and contracts
   🎯 10   🛡️ 9   🧠 4
   Approx changes: `1000-1700` lines.

   Scope:

   - package layout;
   - `memo_stack_contracts` package and schema registry skeleton;
   - domain value objects/entities as dependency-light dataclasses/domain models;
   - public DTOs for health/capabilities/common envelope;
   - mapper conventions and first mapper tests;
   - bootstrap state and config snapshot skeleton;
   - config doctor CLI;
   - migration run and compatibility window skeleton;
   - worker instance, lease and scheduled task skeleton;
   - storage object, upload session and artifact skeleton;
   - fact currency, conflict and supersession skeleton;
   - backup policy, backup manifest and restore run skeleton;
   - deployment region, residency policy and processing-location decision skeleton;
   - read scope, visibility predicate and proof skeleton;
   - repository scope, query proof and maintenance override skeleton;
   - dependency inventory, parser sandbox policy and release attestation skeleton;
   - prompt path budget and degradation decision skeleton;
   - cache policy, entry metadata and invalidation skeleton;
   - ports only, no real adapters;
   - FastAPI health/capabilities skeleton;
   - OpenAPI generation;
   - import-boundary tests.

2. Canonical Postgres lifecycle
   🎯 9   🛡️ 9   🧠 6
   Approx changes: `1700-3000` lines.

   Scope:

   - migrations;
   - repositories;
   - unit of work;
   - remember/update/forget facts;
   - principals/profile grants;
   - audit and outbox tables;
   - client operation and idempotency tables;
   - token hash store, key versions and audit chain.
   - first real bootstrap command backed by Postgres;
   - config snapshot persistence and API/worker compatibility check;
   - migration run tables and first dry-run planner;
   - storage object/upload/artifact tables and repository tests;
   - fact currency/conflict/supersession tables and current resolver tests;
   - backup/restore tables and manifest validation tests;
   - region/residency tables and processing-location repository tests;
   - read visibility guard and access audit tests;
   - repository scope tables, query proof tests and unscoped SQL negative tests;
   - supply-chain inventory tables, parser run records and release attestation tests;
   - prompt path run/stage tables and SLO tests;
   - cache metadata/invalidation tables and freshness use-case tests;

2.5. Repository scope and query isolation hardening
   🎯 9   🛡️ 9   🧠 5
   Approx changes: `500-1000` lines.

   Scope:

   - `RepositoryScope`, `ScopedRepositoryContext`, `QueryScopeProof`, `MaintenanceScopeOverride`;
   - repository method signature cleanup for scoped tables;
   - central SQL/ORM scope predicate compiler;
   - query proof diagnostics;
   - unscoped SQL negative tests;
   - optional Postgres RLS smoke tests for remote/team mode.

3. Worker and outbox hardening
   🎯 9   🛡️ 9   🧠 6
   Approx changes: `1200-2200` lines.

   Scope:

   - worker registration and heartbeat;
   - worker leases and graceful shutdown;
   - scheduled task singleton leases;
   - idempotency keys;
   - operation status updates and result snapshots;
   - leases;
   - ordering keys;
   - dead-letter diagnostics;
   - retry/backoff policies;
   - projection state/mapping updates from workers;
   - key rotation/re-encryption jobs;
   - audit chain verification job.

3.5. Backup, restore and DR guardrails
   🎯 9   🛡️ 9   🧠 6
   Approx changes: `600-1200` lines.

   Scope:

   - `BackupPolicy`, `BackupRun`, `BackupManifest`, `RestoreRun`;
   - backup/restore admin API;
   - manifest hash and object inventory validation;
   - key-version availability checks;
   - restore dry-run blocker report;
   - hard-delete/tombstone restore safety tests.

3.6. Data residency and processing-location guardrails
   🎯 9   🛡️ 9   🧠 5
   Approx changes: `500-1000` lines.

   Scope:

   - `DeploymentRegion`, `DataResidencyPolicy`, `ProcessingLocationDecision`;
   - local synthetic region support;
   - provider region capability checks;
   - storage/provider/export/backup/import/sync denial tests;
   - admin diagnostics for safe location decisions.

3.65. Supply-chain and parser sandbox guardrails
   🎯 9   🛡️ 9   🧠 5
   Approx changes: `500-1000` lines.

   Scope:

   - `DependencyInventory`, `DependencyRiskFinding`, `LicensePolicy`;
   - `ParserSandboxPolicy`, `ParserExecutionRun`;
   - `ReleaseArtifactAttestation`;
   - SBOM/vulnerability/license scan integration;
   - parser sandbox/resource-limit tests;
   - waiver lifecycle and remote/team release gates.

3.75. Prompt-path SLO guardrails
   🎯 9   🛡️ 9   🧠 5
   Approx changes: `500-1000` lines.

   Scope:

   - `PromptPathBudget`, `ContextStageBudget`, `ContextDegradationDecision`;
   - fallback context plan;
   - prompt path run/stage diagnostics;
   - deadline propagation helpers;
   - slow graph/vector/rerank fake tests.

4. Projection state and rebuild operations
   🎯 9   🛡️ 9   🧠 7
   Approx changes: `800-1600` lines.

   Scope:

   - `ProjectionState`, `ProjectionMapping`, `ProjectionRebuildJob`;
   - projection diagnostics API;
   - rebuild/verify/pause/resume/activate generation;
   - adapter mapping idempotency;
   - rebuild watermark and generation tests.

5. Qdrant document RAG
   🎯 9   🛡️ 8   🧠 6
   Approx changes: `1100-2100` lines.

   Scope:

   - upload session completion flow;
   - storage object checksum/quarantine validation;
   - staged document pipeline;
   - chunking;
   - Qdrant adapter;
   - payload indexes diagnostics;
   - document recall eval.

6. Graphiti adapter spike then implementation
   🎯 8   🛡️ 8   🧠 8
   Approx changes: `1000-2200` lines.

   Scope:

   - adapter spike first;
   - capability contract;
   - episode/fact indexing;
   - search mapping;
   - stale result canonical filtering.

7. Context builder and eval harness
   🎯 9   🛡️ 9   🧠 7
   Approx changes: `1300-2200` lines.

   Scope:

   - merge/rerank/pack;
   - prompt-path stage budgets and degradation decisions;
   - code scope matching and labels;
   - stale code-reference labeling;
   - context quality gates;
   - server cache freshness checks for context/search;
   - small golden eval runner;
   - diagnostics.

8. Memory consolidation and digest quality
   🎯 8   🛡️ 9   🧠 7
   Approx changes: `800-1600` lines.

   Scope:

   - `MemoryCluster`, `MemoryDigest`, `ConsolidationJob`;
   - consolidation repository and API;
   - digest lifecycle and source invalidation;
   - proposed duplicate clusters;
   - false-merge evals and diagnostics.

9. Usage, quota and admission control
   🎯 9   🛡️ 9   🧠 6
   Approx changes: `700-1400` lines.

   Scope:

   - `UsageRecord`, `QuotaRule`, `QuotaReservation`, `AdmissionDecision`;
   - quota/admission APIs;
   - reserved interactive capacity;
   - noisy-neighbor fairness keys;
   - reservation cleanup and usage reconciliation.

10. Policy-gated auto memory
   🎯 8   🛡️ 9   🧠 7
   Approx changes: `900-1800` lines.

   Scope:

   - suggestion lifecycle;
   - classifier orchestration;
   - auto_safe only behind explicit policy;
   - false-positive evals.

11. Connector, MCP and event delivery contracts
   🎯 8   🛡️ 9   🧠 7
   Approx changes: `900-1700` lines.

   Scope:

   - connector lifecycle API;
   - webhook signature/replay protection;
   - connector sync state/backfill;
   - event subscriptions and cache invalidation;
   - MCP action classes and destructive confirmation gates.

12. Sync readiness guardrails
   🎯 8   🛡️ 9   🧠 6
   Approx changes: `500-1000` lines.

   Scope:

   - sync peer/checkpoint domain contracts;
   - capabilities flag disabled by default;
   - change set dry-run contracts;
   - conflict record storage;
   - no public apply mode without ADR.

13. Client App compatibility gateway
   🎯 9   🛡️ 9   🧠 7
   Approx changes: `900-1800` lines.

   Scope:

   - legacy routes;
   - session/thread mapping;
   - envelope compatibility;
   - existing canary scripts against memo_stack_server.

Each PR should have:

- one primary behavior change;
- focused tests;
- rollback path;
- production-safe diagnostics;
- no unrelated refactor;
- no generated client churn unless the PR is explicitly about contract generation.

### Phase 0 - Skeleton

🎯 10   🛡️ 9   🧠 4
Estimated changes: `800-1400` lines.

Deliver:

- package layout;
- domain entities;
- `MemoryPolicy` and `MemorySuggestion` domain contracts;
- `MemoryCluster`, `MemoryDigest` and `ConsolidationJob` contracts;
- `UsageRecord`, `QuotaRule`, `QuotaReservation` and `AdmissionDecision` contracts;
- `ProjectionState`, `ProjectionMapping` and `ProjectionRebuildJob` contracts;
- `ClientOperation`, `IdempotencyRecord` and `OperationResultSnapshot` contracts;
- `MemoryEntity` and temporal/evidence value objects;
- `FactCurrencyState`, `FactConflictRecord` and `SupersessionDecision` contracts;
- `Principal`, `SpaceMember`, `ProfileGrant` contracts;
- ports;
- OpenAPI generation config;
- FastAPI health;
- config;
- OpenAPI;
- basic tests.

Exit gate:

- import boundaries are clean;
- domain imports no adapter libs;
- SDK can call health;
- OpenAPI diff is deterministic in CI.

Forbidden in Phase 0:

- real Graphiti/Qdrant/Postgres adapter logic;
- Client App prompt path changes;
- classifier/LLM calls;
- background worker side effects beyond a no-op interface;
- migration of existing memory data.

### Phase 1 - Canonical Postgres Core

🎯 9   🛡️ 9   🧠 6
Estimated changes: `1600-2900` lines.

Deliver:

- migrations;
- repositories;
- UnitOfWork;
- remember/update/forget fact;
- canonical entity repository and alias repository;
- code repository/reference tables and value objects;
- temporal/evidence fields and query filters;
- fact currency, conflict and supersession tables;
- profile/thread;
- memory policy;
- memory suggestions;
- memory cluster/digest/consolidation tables as dormant contracts;
- usage/quota/reservation tables;
- projection state/mapping/rebuild tables;
- client operation/idempotency/result snapshot tables;
- backup policy/run/manifest and restore run validation tables;
- redaction artifacts;
- provider config, prompt template and AI call audit tables;
- schema migration run, data backfill job and compatibility window tables;
- principals, memberships and profile grants;
- audit;
- outbox table with idempotency/lease fields;
- quota rules;
- API envelope, typed errors and idempotency replay store.

Exit gate:

- fact lifecycle tests pass;
- entity resolution and temporal filtering tests pass;
- fact currency and conflict resolution tests pass;
- code scope/reference domain tests pass;
- policy/suggestion lifecycle tests pass;
- digest/consolidation lifecycle tests pass;
- usage/quota reservation lifecycle tests pass;
- migration dry-run and backfill resume tests pass;
- projection state/rebuild lifecycle tests pass;
- operation/idempotency lifecycle tests pass;
- backup manifest and restore dry-run lifecycle tests pass;
- redaction artifact and provider config tests pass;
- authorization contract tests pass;
- outbox idempotency and dead-letter tests pass;
- common API envelope/error/idempotency tests pass;
- deleted/superseded facts hidden by repository queries.

### Phase 1.25 - Fact Currency and Conflict Resolution

🎯 9   🛡️ 10   🧠 6
Estimated changes: `600-1200` lines.

Deliver:

- `FactCurrencyState`;
- `FactConflictRecord`;
- `SupersessionDecision`;
- `CurrentFactSet`;
- current fact resolver;
- conflict detection use cases;
- review/apply supersession workflow;
- current/history/disputed context tests.

Exit gate:

- explicit correction supersedes or creates review according to policy;
- weak derived evidence cannot overwrite strong primary evidence;
- unresolved critical conflict is excluded from normal context;
- history search can return superseded/disputed facts with labels.

### Phase 1.5 - Backup, Restore and DR Guardrails

🎯 9   🛡️ 9   🧠 6
Estimated changes: `600-1200` lines.

Deliver:

- backup policy model;
- backup run and manifest metadata;
- restore run and validation report;
- admin backup/restore endpoints;
- object inventory and manifest hash verification;
- key-version availability checks;
- PITR tombstone/hard-delete replay plan;
- restore dry-run before apply.

Exit gate:

- backup manifest records commit position, event cursor, key versions and object inventory hash;
- restore dry-run blocks missing keys, missing blobs and hard-delete conflicts;
- restore cannot make prompt-visible memory until validation passes;
- derived index snapshots are treated as acceleration only and can be rebuilt from Postgres.

### Phase 1.75 - Read Visibility Guard

🎯 9   🛡️ 10   🧠 6
Estimated changes: `500-1000` lines.

Deliver:

- `ReadScope` value object;
- `VisibilityPredicate` builder;
- `VisibilityProof` contract;
- denied-read policy;
- predicate-aware repository hydration methods;
- access diagnostics and safe read audit;
- endpoint tests for search/list/context/export/debug visibility.

Exit gate:

- every user-visible read path has proof or safe denial;
- list pagination and direct get by id do not leak hidden ids;
- cross-profile and deleted candidates from Graphiti/Qdrant/cache are dropped;
- export and diagnostics use same visibility predicate as normal reads unless explicit debug grant is audited.

### Phase 1.85 - Prompt-Path SLO Guardrails

🎯 9   🛡️ 9   🧠 5
Estimated changes: `500-1000` lines.

Deliver:

- `PromptPathBudget`;
- `ContextStageBudget`;
- `ContextDegradationDecision`;
- `FallbackContextPlan`;
- prompt path run/stage diagnostics;
- deadline propagation helpers;
- local Docker SLO tests with slow graph/vector/rerank fakes.

Exit gate:

- context API returns full, degraded or fallback-safe response before hard deadline;
- graph/vector/rerank timeouts do not block canonical fallback;
- degraded context is machine-readable and prompt-safe;
- Client App compatibility route keeps current desktop timeout behavior.

### Phase 2 - Qdrant RAG

🎯 9   🛡️ 8   🧠 6
Estimated changes: `1000-1800` lines.

Deliver:

- document ingestion;
- staged document processing pipeline;
- sensitivity classification for documents/chunks;
- chunking;
- Qdrant adapter;
- vector search;
- canonical filter;
- document retrieval tests.

Exit gate:

- ingest document -> search chunk works;
- delete document -> chunk not returned;
- Qdrant down does not break canonical write;
- secret/restricted document does not call external embedding/classification.

### Phase 3 - Graphiti Temporal Graph

🎯 8   🛡️ 8   🧠 8
Estimated changes: `1200-2400` lines.

Spike gate before implementation:

```text
create test profile
add episode with reference_time
add/update/delete canonical fact
search by entity/fact text
verify group/profile isolation
verify Graphiti entity match is only a candidate unless Postgres entity is resolved
verify telemetry disabled
verify stale Graphiti result is filtered by Postgres
record exact API calls and backend capability gaps
```

Deliver:

- Graphiti adapter;
- episode indexing;
- fact indexing;
- graph search;
- group/profile mapping;
- entity candidate mapping into canonical `MemoryEntity`;
- temporal `reference_time` mapping;
- sequential processing per group.

Exit gate:

- remember episode -> graph search returns candidate;
- update fact -> old hidden;
- delete fact -> stale graph result filtered.

### Phase 4 - Context Builder

🎯 9   🛡️ 9   🧠 7
Estimated changes: `1200-2100` lines.

Deliver:

- merge graph/vector candidates;
- rerank;
- prompt-path stage budgets and degradation decisions;
- context packer;
- temporal/current/history filter;
- context item trust labels;
- context quality gates;
- cache freshness checks and diagnostics;
- diagnostics;
- prompt-injection-safe formatting.

Exit gate:

- curated eval passes recall/precision thresholds;
- temporal leakage and context instruction leakage are 0 on curated suite;
- Graphiti/Qdrant/rerank timeout scenarios return degraded/fallback context within budget;
- context budget never overflows;
- source refs included;
- no single document/profile monopolizes context.
- forget/update/grant/policy cache invalidation blocks stale cached bundles.

### Phase 4.25 - Memory Consolidation and Digests

🎯 8   🛡️ 9   🧠 7
Estimated changes: `800-1600` lines.

Deliver:

- memory cluster repository and API;
- digest lifecycle and refresh jobs;
- consolidation job dry-run;
- duplicate cluster proposal flow;
- false-merge guardrails;
- context packer support for reviewed clusters and active digests.

Exit gate:

- duplicate facts create proposed clusters without mutating active facts;
- digest has source refs and is labeled as derived;
- stale digest is excluded after source update/delete;
- false-merge evals pass for same-name/same-topic but different entity/repo/profile cases;
- context packer uses digests without hiding contradictory active facts.

### Phase 4.35 - Usage, Quota and Admission Control

🎯 9   🛡️ 9   🧠 6
Estimated changes: `700-1400` lines.

Deliver:

- usage record and quota repositories;
- reservation lifecycle;
- admission decision use cases;
- workload fairness keys;
- reserved interactive context capacity;
- quota diagnostics and safe usage summaries.

Exit gate:

- background work cannot consume reserved interactive capacity;
- provider timeout does not leak quota reservation;
- quota hard limit prevents provider call;
- one connector/profile can be throttled without blocking unrelated reads/context;
- quota exhaustion can degrade to source_chunk_only when policy allows.

### Phase 4.5 - Policy-Gated Auto Memory

🎯 9   🛡️ 9   🧠 7
Estimated changes: `900-1800` lines.

Deliver:

- `MemoryPolicy` API;
- classifier orchestration;
- prompt template/output schema versioning;
- provider gateway policy/budget checks;
- suggestion queue API;
- approve/reject flows;
- `auto_safe` policy mode;
- safety gates for source trust, entity confidence, temporal confidence, secrets, conflicts and deleted sources;
- evaluation set for auto-promotion precision.
- review workflow queues and actions;
- connector self-review guardrails.

Exit gate:

- `suggestions` mode never injects pending suggestions into context;
- `auto_safe` passes curated false-positive safety set;
- repeated derived evidence does not auto-promote;
- invalid structured classifier output creates no memory mutation;
- provider circuit breaker and budget exhaustion are visible in diagnostics;
- policy change affects pending jobs safely;
- connector-created suggestion cannot be self-approved unless policy allows.

### Phase 5 - Client App Integration

🎯 9   🛡️ 9   🧠 7
Estimated changes: `900-1800` lines across memo_stack_server compatibility routes, tests and small Client App config wiring.

Deliver:

- legacy `/api/v1/interview-memory/*` compatibility routes in memo_stack_server;
- mapping from legacy `session_id` to platform `MemoryThread`;
- response envelope compatible with current desktop bridge;
- memo_stack_server URL config through existing `INTERVIEW_MEMORY_API_URL` path first;
- no desktop prompt-path rewrite until compatibility canary is green;
- document import path through existing `pnpm memory:import-document`;
- context retrieval path through existing `pnpm e2e:memory-canary` and document recall tests;
- diagnostics showing selected target, resolved mode, policy mode and fallback reason.

Exit gate:

- Client App does not import Graphiti/Qdrant;
- local Docker memory works;
- fallback works when memo_stack_server down.
- existing mode precedence tests pass;
- existing canary scripts pass against memo_stack_server URL;
- `INTERVIEW_MEMORY_FORCE_DISABLED=true` prevents backend calls;
- Settings switch still disables memory without restart;
- document import into companion session is recalled by desktop context;
- ingest-only service token cannot retrieve or delete memory;
- compatibility route contract tests pass against generated OpenAPI and legacy envelope expectations.

## Build vs Buy Decision

Final chosen option:

**Our Memo Stack Core + Graphiti + Qdrant directly**
🎯 9   🛡️ 9   🧠 7
Estimated changes: `15500-28500` lines.

Why:

- best Clean Architecture fit;
- canonical lifecycle is ours;
- no vendor lock-in;
- Graphiti handles temporal graph;
- Qdrant handles RAG/documents;
- Postgres handles truth/governance.

Rejected as core:

**Cognee-first**
🎯 6   🛡️ 5   🧠 5
Estimated changes: `2000-4000` lines.

Reason:

- powerful but too platform-like;
- global config/context;
- heavy dependency surface;
- adapter release drift risk;
- domain lifecycle would leak from Cognee into our model.

Accepted as optional later:

**Cognee adapter**
🎯 8   🛡️ 7   🧠 6
Estimated changes: `1500-3000` lines.

Use only for:

- document ingestion experiments;
- GraphRAG comparison;
- benchmark adapter.

## Critical Design Rules

1. No Graphiti/Qdrant types in `memo_stack_core`.
2. No direct Graphiti/Qdrant import in client apps.
3. Postgres canonical status always wins.
4. Every fact needs source refs.
5. Delete/forget must hide immediately.
6. Derived indexes are rebuildable.
7. Context bundle must be explainable through source refs.
8. Profiles are mandatory boundaries.
9. Memory text is untrusted content.
10. External AI/embedding calls are explicit policy decisions.
11. Memory mode is policy-configured per profile/source, not hardcoded in adapters.
12. Assistant answers are derived evidence, not primary evidence by default.
13. Pending async jobs re-check canonical state and current policy before promotion.
14. Branch/repo/environment scope is part of relevance for coding-agent memory.
15. `MemorySuggestion` is inactive until approved or auto-promoted by policy.
16. Legacy compatibility routes are adapters over core use cases, not a second memory system.
17. Existing Client App kill switches must remain stronger than platform policy.
18. A run must have one prompt-impacting memory target unless explicit shadow comparison mode is enabled.
19. Authorization is checked in canonical Postgres, never delegated to Graphiti/Qdrant.
20. Outbox handlers must be idempotent and safe under duplicate delivery.
21. Interactive context latency has priority over ingestion/indexing/AI maintenance jobs.
22. Sensitivity classification controls external processing, logging, export and embedding.
23. Generated summaries and assistant answers are never primary evidence.
24. Retrieval/context changes require golden eval coverage, not only unit tests.
25. Dependency lockfiles and CI gates are part of the architecture, not optional cleanup.
26. Fixtures must be synthetic/sanitized and stable by id.
27. ADR is required for storage, lifecycle, provider, policy or public API changes.
28. Public API errors are typed contracts, not log messages.
29. Mutating client calls require idempotency strategy.
30. Import/export/sync use canonical ids, versions and tombstones, never derived index ids.
31. Memory kinds, relation types and source types are governed ontology, not arbitrary strings.
32. Connector writes require provenance and scoped principal permissions.
33. Aggregate states change only through documented lifecycle transitions.
34. Public contract versions must be reported by capabilities and covered by fixtures.
35. Architecture-impacting PRs must update the decision traceability matrix or state why it is unchanged.
36. Canonical entity identity lives in Postgres; Graphiti entity matches are candidates only.
37. Current context uses temporal filters by default and labels any historical evidence.
38. Confidence is evidence-derived and cannot be inflated by repeated generated summaries alone.
39. Retrieved memory is rendered as untrusted evidence, never as an instruction.
40. All AI/model calls go through provider governance with purpose, policy, budget and audit.
41. Redaction artifacts preserve source refs and offset maps.
42. Structured model outputs are versioned contracts and fail closed on validation errors.
43. Provider outage or circuit breaker must degrade memory quality, not canonical lifecycle safety.
44. Bearer tokens are stored only as scoped salted hashes and are revocable.
45. Encrypted records carry key version and key rotation is resumable.
46. High-value audit events are append-only and tamper-evident.
47. Parser/provider dependencies require lockfile, SBOM and security/license gates before remote/team use.
48. Connector lifecycle controls write ability; provenance history survives pause/revoke.
49. Webhook connector events require signature, replay protection and source idempotency.
50. Event payloads are cache invalidation hints, not authority to bypass normal read APIs.
51. MCP destructive actions require explicit grants and confirmation.
52. CodeScope controls coding-agent relevance; branch/PR facts are not global by default.
53. CodeReference line ranges are hints; commit/content hash/symbol evidence is preferred.
54. Destructive retention requires dry-run and audit before apply.
55. Active legal hold blocks hard-delete, retention purge and sync purge until released.
56. Profile/thread deletion is a resumable cascade job, not direct table deletion.
57. Sync exchange is disabled by default and must be advertised through capabilities before use.
58. Sync uses canonical ids, versions, tombstones and commit cursors, never Graphiti/Qdrant ids.
59. Sync conflicts become `SyncConflict` records or suggestions, never silent active mutations.
60. Digests are derived context and never primary evidence.
61. Consolidation cannot merge/delete active facts without review or a later ADR-defined safe rule.
62. Cluster/digest context must preserve source refs and must not hide contradictions.
63. Expensive work requires admission control and quota reservation before execution.
64. Interactive context keeps reserved capacity that background jobs cannot consume.
65. Quota exhaustion must degrade safely and must not block delete/forget/status operations.
66. Every derived index write updates ProjectionState and ProjectionMapping.
67. Projection rebuild uses source watermark and explicit generation activation.
68. Failed projection rebuild cannot replace the active generation or change canonical truth.
69. Mutating API requests create or reuse idempotency records before side effects.
70. ClientOperation is the public progress contract; OutboxJob remains internal worker state.
71. Idempotent replay returns the stored result or operation status, never a second mutation.
72. Public DTOs live in `memo_stack_contracts`, not in domain entities, ORM models or adapter payloads.
73. Every public DTO change requires schema fixture diff, mapper tests and SDK compatibility evidence.
74. Unknown public enum values must degrade safely, never trigger unsafe default behavior.
75. Fresh deployments must expose only bootstrap-safe endpoints until first owner/space/profile setup is complete.
76. API and worker processes must declare compatible runtime config snapshots before processing jobs.
77. Dev seed/reset commands require local deployment lineage confirmation and synthetic-only fixtures.
78. Schema upgrades use expand/backfill/dual-read/contract-switch/cleanup phases, not one-shot destructive migrations.
79. Data backfills are chunked, idempotent, tombstone-aware and never write derived indexes directly.
80. Contract cleanup is blocked until compatibility window expiry and explicit rollback boundary acceptance.
81. Every background worker registers a WorkerInstance and owns work through expiring WorkerLease records.
82. Scheduled maintenance uses singleton task leases and idempotency keys, never hidden in-process timers.
83. Graceful shutdown must stop new claims, checkpoint/release current work and keep client operations pollable.
84. Raw object storage keys are never public ids and never appear in normal diagnostics.
85. Documents/imports/artifacts become trusted only after StorageObject checksum, mime, quota and policy verification.
86. Artifact download authorization is checked at request time, not delegated to URL lifetime.
87. Server-side cache is a derived performance layer and never bypasses canonical auth/status/policy filtering.
88. Forget/delete/grant revoke/policy disable/source redaction invalidate affected context/search/rerank cache before prompt-impacting reuse.
89. Cache keys for user-visible context include space, profile set, principal or grant version, policy version, ontology version, temporal mode and commit cursor.
90. Backup manifests are governed contracts with hashes, key versions, tombstone window and hard-delete ledger metadata.
91. Restore starts as dry-run and cannot enable prompt-visible memory until validation passes.
92. Derived index snapshots are restore accelerators only and never override canonical Postgres rows, tombstones or legal holds.
93. Every user-visible read path requires explicit `ReadScope`, `VisibilityPredicate` and `VisibilityProof`.
94. Denied reads must not reveal whether hidden memory exists unless endpoint policy and grants explicitly allow forbidden diagnostics.
95. Export, list, diagnostics, cache hydration and context reads use the same canonical visibility guard by default.
96. Prompt-impacting context requests must have explicit hard deadline, stage budgets and fallback behavior.
97. Slow Graphiti, Qdrant, cache, rerank or provider paths must degrade context quality instead of blocking the live workflow.
98. Degraded context must be machine-readable and must never bypass visibility, freshness or prompt-safe rendering rules.
99. Fact currentness is separate from fact lifecycle status and is resolved through auditable currency records.
100. Unresolved high-impact conflicts are review items, not current prompt constraints.
101. Supersession must be an explicit decision with source refs, temporal fields and rollback audit.
102. All memory writes pass write admission before becoming facts, suggestions or indexed chunks.
103. Assistant/agent generated output is derived evidence and cannot self-promote without primary source or explicit review.
104. Instruction-like source text is stored as untrusted evidence, never as future agent instruction.
105. Remote/team deployments require explicit data residency policy before accepting raw memory or artifacts.
106. External provider, managed index, backup, export, import and sync transfer actions require a `ProcessingLocationDecision`.
107. Scoped repository methods require `RepositoryScope` or `ScopedRepositoryContext`, never naked ids only.
108. Bulk/admin/worker maintenance mutations require dry-run evidence and audited `MaintenanceScopeOverride`.
109. Optional Postgres RLS is defense-in-depth, not a replacement for application-level scope contracts and tests.
110. Remote/team releases require dependency inventory, SBOM, license/security scan and release attestation.
111. Parser/OCR/archive execution uses sandbox policy with network denied, macro/script execution denied and resource limits.
112. Security waivers are scoped, expiring and audited; expired waivers block remote/team release gates again.

## Open Questions Before Implementation

1. Embeddings provider for v1.
   - Recommendation: OpenAI embeddings plus deterministic stub tests.
   - Alternative: local fastembed for privacy-first local mode.

2. Fact update model.
   - Recommendation: immutable versions plus active pointer/status.
   - Alternative: new fact row per update with `supersedes_fact_id`.

3. Profile model UX.
   - Recommendation: explicit profile names and API-level profile ids.
   - Alternative: automatic profile classification later.

4. Auto-memory thresholds.
   - Recommendation: conservative defaults, then tune with evals.
   - Alternative: user-configurable thresholds from day one.

5. Branch/repo scope schema.
   - Recommendation: keep optional typed metadata in v1 and promote to first-class fields after Client App/Codex integration proves access patterns.
   - Alternative: first-class repo/branch/commit columns immediately.

6. Legacy route deprecation timing.
   - Recommendation: keep `/api/v1/interview-memory/*` compatibility through v1 and remove only after SDK/new desktop client is proven.
   - Alternative: migrate desktop bridge directly after the first successful local canary.

7. Package/repository location.
   - Recommendation: start inside Client App `memo_stack/` until architecture is proven, then extract to standalone repo/package.
   - Alternative: create standalone repo immediately.

8. First generated SDK target.
   - Recommendation: Python SDK first, TypeScript/Rust generated clients after OpenAPI stabilizes.
   - Alternative: generate TS immediately for Client App bridge work.

9. Entity registry scope.
   - Recommendation: profile-scoped entities in v1, with optional space-level aliases later.
   - Alternative: shared space-level entity registry from day one, but this increases permission and merge risk.

10. Temporal query default.
    - Recommendation: current-only by default for `/v1/context`, explicit `as_of/history` for search/debug.
    - Alternative: retrieval can include historical facts by default with labels, but prompt quality risk is higher.

11. Confidence scoring implementation.
    - Recommendation: deterministic evidence scoring rules first, LLM only proposes candidates/explanations.
    - Alternative: model-scored confidence from day one, but this is harder to test and tune.

12. AI provider gateway scope.
    - Recommendation: implement provider governance as shared adapter infrastructure in v1, but expose only purpose-specific ports to use cases.
    - Alternative: expose a generic model-call API in `memo_stack_core`, but this increases coupling and misuse risk.

13. Redaction engine.
    - Recommendation: deterministic regex/entropy/known secret detectors first, with LLM-assisted sensitive-data detection only later and local-only by default.
    - Alternative: model-based redaction from day one, but privacy and repeatability risk is higher.

14. Key management for v1.
    - Recommendation: local/dev uses file/env-backed key provider, team/remote requires external secret manager/KMS adapter before launch.
    - Alternative: Postgres-only key storage, but this weakens backup and DB-leak isolation.

15. Residency policy strictness.
    - Recommendation: local v1 uses one synthetic `local` region, remote/team requires one explicit home region and fail-closed provider placement for sensitive data.
    - Alternative: postpone residency until SaaS, but this makes later local-to-cloud migration and team compliance retrofits risky.
    - Alternative: full multi-region routing from day one, but this is too much ops and conflict complexity before core memory quality is proven.

16. Audit integrity level.
    - Recommendation: per-space hash chain in v1, optional external append-only log later.
    - Alternative: external audit sink from day one, but it adds ops burden before product fit is proven.

17. Connector event delivery mode.
    - Recommendation: polling cursor first, webhook subscriptions optional after cursor contract is stable.
    - Alternative: webhook-first delivery, but this adds signature/retry/dead-letter ops before clients prove need.

18. MCP destructive actions.
    - Recommendation: destructive MCP tools disabled by default and enabled only with explicit grant plus confirmation token.
    - Alternative: rely on normal write grants, but agent mistake blast radius is too high.

19. Code scope strictness.
    - Recommendation: repo/branch/PR scope is strict by default, with explicit promotion to repo/global memory.
    - Alternative: fuzzy branch matching by default, but wrong-context coding advice risk is too high.

20. Code reference resolution.
    - Recommendation: commit/content-hash/symbol resolver best effort with stale labels when uncertain.
    - Alternative: line-number citations only, but this breaks quickly after normal refactors.

21. Sync exchange timing.
    - Recommendation: keep v1 sync-ready only, with disabled endpoints and deterministic dry-run contracts.
    - Alternative: implement local-to-cloud apply mode in v1, but this increases data-loss and support risk before core memory quality is proven.

22. Consolidation strictness.
    - Recommendation: proposed clusters and derived digests first; no automatic fact merge/delete in v1.
    - Alternative: aggressive auto-merge by similarity threshold, but false-merge blast radius is too high for team/coding-agent memory.

23. Quota strictness.
    - Recommendation: hard limits for external AI/provider calls, soft degrade for source storage and interactive context.
    - Alternative: global best-effort rate limit, but it is too weak for team/coding-agent workloads and hides noisy-neighbor bugs.

24. Projection generation activation.
    - Recommendation: rebuild into a new generation and activate only after verification.
    - Alternative: in-place rebuild, but it risks partial indexes and hard-to-debug stale/deleted leaks.

25. Public operation model.
    - Recommendation: public `ClientOperation` plus internal `OutboxJob`, with idempotency response snapshots.
    - Alternative: expose internal outbox jobs to SDKs, but this leaks worker internals and makes retries brittle.

26. Contract model implementation style.
    - Recommendation: separate `memo_stack_contracts` package with public DTOs/schema registry, while `memo_stack_core` keeps dependency-light domain entities and internal use-case DTOs.
    - Alternative: put all DTOs inside `memo_stack_core`, but this makes domain refactors and public contract evolution harder to separate.
    - Alternative: generate everything only from OpenAPI, but import/export/events/MCP contracts still need explicit non-HTTP schema ownership.

27. Bootstrap interface.
    - Recommendation: CLI-first bootstrap for local Docker, with optional protected `/v1/bootstrap/local-init` only while uninitialized.
    - Alternative: API-first bootstrap, but this increases exposure risk if the server is bound beyond localhost.
    - Alternative: seed fixed dev token from env, but this is easy to accidentally carry into team/remote mode.

28. Migration strategy.
    - Recommendation: expand/backfill/dual-read/contract-switch/cleanup for all data or public contract migrations.
    - Alternative: simple Alembic-only migrations, but this is unsafe once SDKs, workers and derived indexes exist.
    - Alternative: forward-only no-rollback migrations, but this increases support risk for local/team self-hosted deployments.

29. Worker and scheduler topology.
    - Recommendation: one worker binary can run many groups, but all claims go through WorkerInstance, WorkerLease and ScheduledTask contracts.
    - Alternative: separate microservices per queue from day one, but this adds ops overhead before platform behavior is proven.
    - Alternative: simple in-process asyncio tasks, but this is fragile under restart, scale-out and local-to-remote migration.

30. Object storage adapter for v1.
    - Recommendation: local filesystem/minio-compatible adapter behind `ObjectStoragePort`, with production path using S3-compatible storage later.
    - Alternative: Postgres bytea for local v1, but this weakens large-file, export and backup behavior.
    - Alternative: direct S3-only from day one, but it adds cloud dependency to local-first development.

31. Backup consistency strategy.
    - Recommendation: hybrid manifest with canonical Postgres export/backup metadata, object inventory and optional derived snapshots.
    - Alternative: logical export/import only, simpler but weaker for disaster recovery.
    - Alternative: physical snapshots for every backend, faster at scale but riskier for version drift and derived-index correctness.

32. Prompt-path deadline defaults.
    - Recommendation: Client App-compatible hard budget around current desktop timeout, with larger explicit SDK/agent budgets.
    - Alternative: profile-configurable deadlines from day one, but bad config can make live interviews hang.
    - Alternative: best-effort context without hard deadline, but this is too risky for prompt-impacting workflows.

33. Fact conflict resolution strictness.
    - Recommendation: conservative review-gated resolution with limited auto-supersede for explicit user corrections and stronger primary sources.
    - Alternative: aggressive auto-supersede for all newer facts, but this can replace correct memory with weak imports.
    - Alternative: never auto-supersede, but memory becomes noisy and requires too much manual maintenance.

## First Concrete PR

Recommended first PR:

```text
feat(memory): scaffold reusable memo stack core and server
```

Scope:

- `memo_stack_contracts` package;
- `memo_stack_core` package;
- domain entities;
- public DTO/schema registry skeleton;
- mapper conventions and first mapper tests;
- bootstrap/config/migration state skeletons;
- data residency and write admission skeletons;
- ports;
- DTOs;
- FastAPI skeleton;
- health endpoint;
- config;
- developer tooling config;
- first ADR;
- no Graphiti/Qdrant yet;
- unit tests for domain boundaries.

Why:

- locks clean architecture before adapter pressure starts;
- easy to review;
- prevents "just import graphiti here" shortcuts;
- gives stable API surface for next PRs.

Acceptance criteria:

- `memo_stack_core` imports only stdlib/domain-safe dependencies;
- `memo_stack_contracts` imports no FastAPI, SQLAlchemy, Graphiti, Qdrant or domain infrastructure;
- `memo_stack_server` owns FastAPI/composition root;
- public DTOs for health/capabilities/common envelope have fixtures;
- mapper tests prove domain/use-case result to response DTO conversion;
- bootstrap/config/migration state contracts have domain tests without real adapters;
- backup/restore skeleton has manifest and validation-report domain tests without real backup storage;
- write admission and processing-location skeletons have domain tests without real providers;
- every port has a fake or stub test implementation;
- `GET /v1/health` and `GET /v1/capabilities` work;
- OpenAPI generation is deterministic;
- first ADR records V1 cutline and adapter choices;
- no behavior change in existing Client App runtime.

Suggested verification:

```bash
pytest packages/memo_stack_core/tests packages/memo_stack_server/tests
pytest packages/memo_stack_contracts/tests
python -m memo_stack_server openapi > /tmp/memory-openapi.json
rg -n "graphiti|qdrant_client|sqlalchemy|fastapi" packages/memo_stack_core
rg -n "fastapi|sqlalchemy|graphiti|qdrant_client" packages/memo_stack_contracts
```

The import-boundary commands should return no forbidden imports from `memo_stack_core` or `memo_stack_contracts`.

## Done Definition for V1

V1 is done when:

- local Docker stack starts with one command;
- fresh local Docker reports bootstrap_required, then CLI bootstrap creates first owner, space, profile and scoped token;
- normal memory API traffic is blocked until bootstrap, migrations and runtime config validation complete;
- API and worker config snapshots are compatible before background jobs run;
- SDK can remember/search/update/forget facts;
- SDK can configure memory policy and review suggestions;
- SDK can ingest/search documents;
- SDK can poll/cancel public operations and safely replay idempotent mutations;
- write admission blocks prompt injection, assistant self-promotion and low-trust connector writes from becoming active memory;
- local and remote modes record processing-location decisions before external provider, managed index, backup, export, import or sync transfer actions;
- scoped repository methods reject unscoped access and query-scope proof diagnostics exist for guarded reads/writes;
- release attestation, dependency inventory and parser sandbox diagnostics exist before remote/team mode is considered safe;
- public DTOs live in `memo_stack_contracts` and are covered by schema registry, fixtures and mapper tests;
- domain entities, ORM rows and adapter payloads are never returned directly as public API/SDK DTOs;
- generated SDK compatibility fixtures cover unknown enum, unknown field, missing field and explicit null cases;
- Graphiti and Qdrant are both used through adapters;
- Graphiti runs with explicit provider config and telemetry disabled by default in private/local mode;
- Qdrant required payload indexes are created and checked by diagnostics;
- Postgres can rebuild derived indexes;
- projection state/mapping tracks Graphiti/Qdrant status by canonical aggregate version;
- projection rebuild uses watermark, generation activation and verification without replacing canonical truth;
- deleted/superseded memory never appears in normal search/context;
- server-side context/search/rerank caches are governed by cache freshness tests for forget, update, grant revoke, policy disable and source redaction;
- prompt-path context retrieval has deadline, stage budget, degradation and fallback tests for slow graph/vector/rerank/provider paths;
- Client App can connect through HTTP without Graphiti/Qdrant dependency;
- Client App legacy `/api/v1/interview-memory/*` compatibility routes pass existing canaries;
- existing `InterviewMemoryMode` precedence and kill switches remain compatible;
- companion session import/read path maps to platform thread/profile correctly;
- authorization and profile grants prevent cross-space/cross-profile leakage;
- implementation navigation map and decision traceability matrix are updated by every architecture-impacting PR;
- aggregate lifecycle state machines are enforced by domain tests;
- contract version compatibility matrix is reflected by capabilities, OpenAPI and SDK fixtures;
- schema/data migrations use phased upgrade flow with dry-run, idempotent backfill, compatibility windows and cleanup guards;
- worker/scheduler execution is covered by WorkerInstance, WorkerLease, ScheduledTask, heartbeat and graceful shutdown tests;
- storage objects, upload sessions and artifacts are governed by checksum, quarantine, revoke, expiry and delete-verification tests;
- backup manifests, restore dry-run and disaster recovery validation cover key availability, object inventory, PITR and hard-delete safety;
- canonical entity resolution prevents same-name cross-profile/repo merges;
- current/as_of/history temporal retrieval semantics are tested;
- fact currency resolver prevents stale, disputed or weakly superseded facts from appearing as current constraints;
- confidence gates block auto-promotion without trusted evidence;
- consolidation creates proposed clusters and active digests without treating digests as primary evidence;
- stale digests are invalidated by source/policy/redaction changes and excluded from normal context;
- false-merge evals protect similar but distinct facts across profiles, repos, entities and time windows;
- context bundle items are rendered as untrusted evidence with source/confidence/temporal labels;
- outbox duplicate delivery and stale ordering cannot create duplicate or resurrected memory;
- client operation/idempotency records prevent duplicate side effects after retries, timeouts and restarts;
- operation result snapshots replay safe responses inside the configured retention window;
- quota/admission/reservations protect interactive context from large imports, AI jobs and noisy connectors;
- quota reservation lifecycle is tested for commit, release, expiry, provider timeout and retry;
- sensitivity rules prevent secret/restricted external processing by default;
- AI provider calls are governed by purpose, provider/model allowlist, budget, redaction and audit;
- redaction artifacts preserve citation offset maps and secret remediation can deindex stale embeddings;
- structured classifier/model outputs are schema-validated and fail closed;
- bearer tokens are hashed/scoped/revocable and never logged raw;
- encrypted records keep key versions and key rotation/restore paths are tested;
- backup artifacts inherit sensitivity, retention, key policy and current authorization checks;
- audit chain verifies high-value admin/export/delete/policy/key events;
- release artifacts pass dependency lock, SBOM and security/license gates for remote/team use;
- connector lifecycle supports install, pause, resume, revoke, token rotation and sync-state diagnostics;
- connector webhook/event ingest verifies signatures, replay windows and source idempotency;
- event subscriptions or polling cursor invalidate client caches after update/delete/policy events;
- cache diagnostics expose safe freshness state, hit/miss counts and stale-hit blocks without raw memory text;
- MCP destructive actions are gated by explicit grants and confirmation;
- code scope filtering prevents branch/PR/local facts from leaking into unrelated coding context;
- code references handle file rename, line drift and symbol moves with stale/moved labels;
- staged document pipeline handles partial extraction and hostile files safely;
- small golden eval suite gates retrieval/context changes;
- MVP cutline, PR roadmap and risk register are kept current;
- every phase exit gate is met before starting prompt-impacting integration;
- CI gates cover lint, type checks, import boundaries, tests, OpenAPI diff and fixture safety;
- local Docker has healthchecks, seed/reset scripts and diagnostics;
- dev seed/reset commands are synthetic-only and guarded by local lineage confirmation;
- ADRs exist for accepted storage/provider/API decisions;
- API/SDK contract covers typed errors, pagination, idempotency and capabilities;
- export/import dry-run and event cursor contracts are tested;
- sync exchange is disabled by default, capability-gated and covered by checkpoint/conflict dry-run tests;
- consolidation/digest contracts are covered by lifecycle, source-ref and context-packing tests;
- ontology aliases and connector provenance contracts are tested;
- OpenAPI/SDK contract checks are part of CI;
- e2e tests verify large document recall, fact update and forget;
- tests verify manual, suggestions and auto_safe policy modes;
- diagnostics show source refs and indexing status;
- operational runbooks cover provider outage, restore, rebuild, migration failure and secret remediation;
- production-safe mode does not leak raw memory text.
