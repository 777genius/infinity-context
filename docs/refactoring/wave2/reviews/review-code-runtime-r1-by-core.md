# Runtime R1 code review — core owner

Reviewed arch-runtime HEAD `a1c41da2` against immutable evidence `422fd508` / compressed `ff31862e` and source move `4517a35c`. Inspected canonical capsule ownership/dependencies, explicit legacy imports, consumer import migration, complete contract tests/global inventory, architecture guard and wheel probe. Independently ran only bounded intent contract + capsule ownership tests: **7 passed**, including all1,630 full cases.

Decision: **production source supported; one verification blocker before merge**.

## R1-C1 — installed server consumer promised by the plan is not exercised

`scripts/smoke_benchmark_package_wheels.py:30–60` replays the lower-level canonical intent API for every installation and checks old aliases/pickles for server/bundle. It never calls installed `infinity_context_server.memory_comparison_rerank.query_retrieval_intent`. The approved revised plan explicitly distinguishes standalone lower-level replay from server/bundle actual consumer output. Source-tree contract tests do call that consumer, but cannot prove the wheel's migrated import boundary and behavior.

Add a bounded server/bundle loop invoking the actual installed `query_retrieval_intent` with frozen question/category inputs (the existing contract test's SimpleNamespace is sufficient), and compare full asdict intent, diagnostics and query profile to frozen outputs. Keep standalone replay server-free. Existing target-only origin assertions must cover the newly loaded server/core modules. Then let root execute the one scheduled wheel proof; no second install harness or provider calls required.

## Verified source findings

All ten canonical modules have focused responsibilities and stdlib/own-capsule imports. The public ten-name API is narrow, old defined/helper/imported attributes are explicit, and alias/new pickle identity is exercised. The actual consumer change is imports only; typed DTO fields/method behavior and inference precedence remain in their original policy bodies. Exact facet order and all31 facets are covered, with complete output checks rather than counts alone. The executable inventory includes nested comprehension/property globals and evaluated hints; no hidden assignment forwarding or product imports were introduced. New modules remain below1,000LOC.

No source behavior defect found. Approval after R1-C1 is incorporated and root supplies installed-wheel/shared gate evidence.

## Fix verification —89e2a7ad

Inspected the corrective wheel-probe diff. Server/bundle now import the installed real consumer, replay all frozen question/category inputs and compare complete intent/diagnostics/profile before final namespace-origin assertions. Standalone remains server-free. **R1-C1 resolved; source and verification implementation approved, no unresolved review blocker.** Root still executes the scheduled isolated wheel and shared acceptance gates; no redundant build was run for this follow-up.
