import { describe, expect, it } from "vitest";
import {
  InfinityContextClient,
  ValueError,
  createMemoryIngestionLoopPlan,
  createMemoryPreferenceBriefPlan,
  createMemoryScopePlan,
  createMemorySourceEvidencePlan,
  createMemorySummaryLoopPlan,
} from "../src/index.js";

describe("InfinityContextClient", () => {
  it("plans durable workspace user topic and source memory scopes", () => {
    const scopePlan = createMemoryScopePlan({
      spaceSlug: "social-monitor:tenant_1:workspace_1",
      spaceName: "Tenant 1 workspace 1",
      users: [
        {
          externalRef: "user_1",
          displayName: "User 1",
          email: "user1@example.com",
          role: "owner",
        },
      ],
      topics: [
        {
          slug: "ai-agents",
          name: "AI agents memory",
        },
      ],
      sources: [
        {
          sourceType: "reddit",
          sourceId: "r/LocalLLaMA",
          name: "Reddit LocalLLaMA source memory",
          includeInReadScope: false,
        },
        {
          externalRef: "source:github:openai-agents",
        },
      ],
      threadExternalRef: "digest:daily",
    });

    expect(scopePlan.memoryScopes).toEqual([
      {
        kind: "workspace",
        externalRef: "workspace-global",
        name: "Workspace global memory",
      },
      { kind: "user", externalRef: "user:user_1", name: "User 1 memory" },
      {
        kind: "topic",
        externalRef: "topic:ai-agents",
        name: "AI agents memory",
      },
      {
        kind: "source",
        externalRef: "source:reddit:r/LocalLLaMA",
        name: "Reddit LocalLLaMA source memory",
      },
      {
        kind: "source",
        externalRef: "source:github:openai-agents",
        name: "source:github:openai-agents memory",
      },
    ]);
    expect(scopePlan.users).toEqual([
      {
        externalRef: "user:user_1",
        displayName: "User 1",
        email: "user1@example.com",
        role: "owner",
      },
    ]);
    expect(scopePlan.readScope).toEqual({
      spaceSlug: "social-monitor:tenant_1:workspace_1",
      memoryScopeExternalRefs: [
        "workspace-global",
        "user:user_1",
        "topic:ai-agents",
        "source:github:openai-agents",
      ],
      threadExternalRef: "digest:daily",
    });
    expect(scopePlan.topology).toMatchObject({
      spaceSlug: "social-monitor:tenant_1:workspace_1",
      spaceName: "Tenant 1 workspace 1",
      createMemberships: true,
      memoryScopes: scopePlan.memoryScopes,
      users: scopePlan.users,
    });
    expect(Object.isFrozen(scopePlan.memoryScopes)).toBe(true);
    expect(Object.isFrozen(scopePlan.readScope.memoryScopeExternalRefs)).toBe(
      true,
    );

    const loopPlan = createMemorySummaryLoopPlan(
      {
        topology: scopePlan.topology,
        brief: {
          query: "What matters in AI agents today?",
          ...scopePlan.readScope,
        },
      },
      {
        preset: "durable",
      },
    );

    expect(loopPlan.input.topology).toBe(scopePlan.topology);
    expect(loopPlan.input.brief).toMatchObject({
      query: "What matters in AI agents today?",
      spaceSlug: "social-monitor:tenant_1:workspace_1",
      memoryScopeExternalRefs: [
        "workspace-global",
        "user:user_1",
        "topic:ai-agents",
        "source:github:openai-agents",
      ],
      includeSearch: true,
      includeDigest: true,
    });
  });

  it("validates memory scope plan identifiers", () => {
    expect(() =>
      createMemoryScopePlan({
        spaceSlug: "",
      }),
    ).toThrow(ValueError);
    expect(() =>
      createMemoryScopePlan({
        spaceSlug: "workspace",
        sources: [{ sourceType: "github" }],
      }),
    ).toThrow("source scope requires sourceId or externalRef");
  });

  it("plans provider source evidence batches with stable memory defaults", () => {
    const plan = createMemorySourceEvidencePlan({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      threadExternalRef: "scan:2026-06-22",
      sourceAgent: "social-monitor",
      sourceType: "reddit",
      idempotencyKeyPrefix: "scan",
      headers: { "x-scan-id": "scan_1" },
      metadata: { scan: "daily" },
      sourceRefs: [{ source_type: "scan", source_id: "scan_1" }],
      concurrency: 2,
      continueOnError: true,
      document: { classification: "public" },
      linkSuggestions: { persist: true, limit: 5 },
      findings: [
        {
          sourceId: "reddit:t3_abc",
          title: "Reddit discussion on agent memory",
          text: "Operators want Reddit freshness and citations in summaries.",
          occurredAt: "2026-06-22T10:00:00.000Z",
          url: "https://reddit.com/r/LocalLLaMA/comments/abc",
          metadata: { subreddit: "LocalLLaMA" },
          headers: { "x-item-id": "reddit:t3_abc" },
          sourceRefs: [{ source_type: "reddit", source_id: "reddit:t3_abc" }],
        },
        {
          sourceType: "github",
          sourceId: "github:issue_1",
          title: "GitHub issue about memory SDK",
          memoryScopeExternalRef: "source:github:memory-sdk",
          idempotencyKey: "github:issue_1:custom",
          fact: {
            memoryScopeExternalRef: "topic:ai-agents",
            tags: ["github", "sdk"],
          },
        },
      ],
    });

    expect(plan.summary).toEqual({
      total: 2,
      sourceTypes: ["reddit", "github"],
      idempotencyKeys: ["scan:reddit:reddit:t3_abc", "github:issue_1:custom"],
    });
    expect(plan.sourceRefs).toEqual([
      { source_type: "reddit", source_id: "reddit:t3_abc" },
      { source_type: "scan", source_id: "scan_1" },
      { source_type: "github", source_id: "github:issue_1" },
    ]);
    expect(plan.batch).toMatchObject({
      headers: { "x-scan-id": "scan_1" },
      concurrency: 2,
      continueOnError: true,
      items: plan.items,
    });
    expect(plan.items[0]).toMatchObject({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "topic:ai-agents",
      threadExternalRef: "scan:2026-06-22",
      sourceAgent: "social-monitor",
      sourceType: "reddit",
      sourceId: "reddit:t3_abc",
      title: "Reddit discussion on agent memory",
      text: "Operators want Reddit freshness and citations in summaries.",
      occurredAt: "2026-06-22T10:00:00.000Z",
      idempotencyKey: "scan:reddit:reddit:t3_abc",
      headers: { "x-item-id": "reddit:t3_abc" },
      metadata: {
        scan: "daily",
        subreddit: "LocalLLaMA",
        url: "https://reddit.com/r/LocalLLaMA/comments/abc",
      },
      sourceRefs: [
        { source_type: "reddit", source_id: "reddit:t3_abc" },
        { source_type: "scan", source_id: "scan_1" },
      ],
      document: { classification: "public" },
      linkSuggestions: { persist: true, limit: 5 },
    });
    expect(plan.items[1]).toMatchObject({
      memoryScopeExternalRef: "source:github:memory-sdk",
      sourceType: "github",
      sourceId: "github:issue_1",
      text: "GitHub issue about memory SDK",
      idempotencyKey: "github:issue_1:custom",
      fact: {
        memoryScopeExternalRef: "topic:ai-agents",
        tags: ["github", "sdk"],
      },
    });
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.items)).toBe(true);
    expect(Object.isFrozen(plan.sourceRefs)).toBe(true);
  });

  it("validates provider source evidence plans before workflow execution", () => {
    expect(() =>
      createMemorySourceEvidencePlan({
        sourceAgent: "social-monitor",
        findings: [{ sourceId: "post_1", text: "Missing source type." }],
      }),
    ).toThrow("source evidence finding requires sourceType or plan sourceType");
    expect(() =>
      createMemorySourceEvidencePlan({
        sourceAgent: "social-monitor",
        sourceType: "reddit",
        findings: [{ sourceId: "post_1", text: "" }],
      }),
    ).toThrow("source evidence finding requires text or title");
  });

  it("plans a complete ingestion summary loop from provider findings", () => {
    const plan = createMemoryIngestionLoopPlan({
      spaceSlug: "social-monitor:tenant:workspace",
      spaceName: "Tenant workspace",
      sourceAgent: "social-monitor",
      query: "What matters most in AI agents today?",
      topic: "AI agents daily digest",
      threadExternalRef: "scan:2026-06-22",
      headers: { "x-trace-id": "scan:2026-06-22" },
      scope: {
        topics: [{ slug: "ai-agents", name: "AI agents" }],
        sources: [
          {
            sourceType: "reddit",
            sourceId: "r/LocalLLaMA",
            name: "Reddit LocalLLaMA",
          },
          {
            sourceType: "github",
            sourceId: "openai/openai-node",
            name: "GitHub openai-node",
          },
        ],
      },
      sourceEvidence: {
        sourceType: "reddit",
        concurrency: 2,
        continueOnError: true,
        document: { classification: "public" },
        linkSuggestions: { persist: true, limit: 5 },
      },
      brief: {
        tokenBudget: 1200,
        maxFacts: 8,
        memoryScopeExternalRefs: ["user:user_1"],
      },
      preset: "durable",
      findings: [
        {
          sourceId: "reddit:t3_abc",
          title: "Reddit thread about memory agents",
          text: "Operators want freshness, citations and source ranking.",
        },
        {
          sourceType: "github",
          sourceId: "github:issue_42",
          title: "GitHub issue about SDK ergonomics",
          text: "Developers want typed source evidence planning.",
          memoryScopeExternalRef: "source:github:openai/openai-node",
        },
      ],
    });

    expect(plan.scope.memoryScopes).toEqual([
      {
        kind: "workspace",
        externalRef: "workspace-global",
        name: "Workspace global memory",
      },
      { kind: "topic", externalRef: "topic:ai-agents", name: "AI agents" },
      {
        kind: "source",
        externalRef: "source:reddit:r/LocalLLaMA",
        name: "Reddit LocalLLaMA",
      },
      {
        kind: "source",
        externalRef: "source:github:openai/openai-node",
        name: "GitHub openai-node",
      },
    ]);
    expect(plan.readScope).toEqual({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRefs: [
        "workspace-global",
        "topic:ai-agents",
        "source:reddit:r/LocalLLaMA",
        "source:github:openai/openai-node",
        "user:user_1",
      ],
      threadExternalRef: "scan:2026-06-22",
    });
    expect(plan.sourceEvidence.batch).toMatchObject({
      headers: { "x-trace-id": "scan:2026-06-22" },
      concurrency: 2,
      continueOnError: true,
    });
    expect(plan.sourceEvidence.items[0]).toMatchObject({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "source:reddit:r/LocalLLaMA",
      threadExternalRef: "scan:2026-06-22",
      sourceAgent: "social-monitor",
      sourceType: "reddit",
      sourceId: "reddit:t3_abc",
      idempotencyKey: "scan:2026-06-22:reddit:reddit:t3_abc",
      document: { classification: "public" },
      linkSuggestions: { persist: true, limit: 5 },
    });
    expect(plan.sourceEvidence.items[1]).toMatchObject({
      memoryScopeExternalRef: "source:github:openai/openai-node",
      sourceType: "github",
      sourceId: "github:issue_42",
      idempotencyKey: "scan:2026-06-22:github:github:issue_42",
    });
    expect(plan.summaryLoop.input).toMatchObject({
      headers: { "x-trace-id": "scan:2026-06-22" },
      topology: plan.scope.topology,
      sourceEvidence: plan.sourceEvidence.batch,
      outboxDrain: { throwOnFailure: true },
      brief: {
        query: "What matters most in AI agents today?",
        topic: "AI agents daily digest",
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: [
          "workspace-global",
          "topic:ai-agents",
          "source:reddit:r/LocalLLaMA",
          "source:github:openai/openai-node",
          "user:user_1",
        ],
        threadExternalRef: "scan:2026-06-22",
        tokenBudget: 1200,
        maxFacts: 8,
        includeSearch: true,
        includeDigest: true,
      },
    });
    expect(plan.policy).toMatchObject({
      requireReadiness: true,
      requireSourceEvidence: true,
      requireOutboxDrain: true,
      requireQuality: true,
    });
    expect(plan.summary).toEqual({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeCount: 4,
      findingCount: 2,
      sourceTypes: ["reddit", "github"],
      readScopeExternalRefs: [
        "workspace-global",
        "topic:ai-agents",
        "source:reddit:r/LocalLLaMA",
        "source:github:openai/openai-node",
        "user:user_1",
      ],
    });
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.readScope.memoryScopeExternalRefs)).toBe(true);
  });

  it("validates ingestion loop plan identifiers", () => {
    expect(() =>
      createMemoryIngestionLoopPlan({
        spaceSlug: "",
        sourceAgent: "social-monitor",
        query: "Daily digest",
        findings: [],
      }),
    ).toThrow("createMemoryIngestionLoopPlan requires spaceSlug");
    expect(() =>
      createMemoryIngestionLoopPlan({
        spaceSlug: "workspace",
        sourceAgent: "",
        query: "Daily digest",
        findings: [],
      }),
    ).toThrow("createMemoryIngestionLoopPlan requires sourceAgent");
    expect(() =>
      createMemoryIngestionLoopPlan({
        spaceSlug: "workspace",
        sourceAgent: "social-monitor",
        query: "",
        findings: [],
      }),
    ).toThrow("createMemoryIngestionLoopPlan requires query");
  });

  it("plans preference seeded briefs for user personalized summaries", () => {
    const plan = createMemoryPreferenceBriefPlan({
      spaceSlug: "social-monitor:tenant:workspace",
      spaceName: "Tenant workspace",
      query: "Which style should today's AI agents digest use?",
      topic: "AI agents digest preferences",
      threadExternalRef: "digest:2026-06-22",
      headers: { "x-trace-id": "preference-plan" },
      scope: {
        users: [
          {
            externalRef: "user_1",
            displayName: "User 1",
            includeInReadScope: true,
          },
        ],
        topics: [
          {
            slug: "ai-agents:preferences",
            name: "AI agents preferences",
          },
        ],
      },
      idempotencyKeyPrefix: "pref:ai-agents",
      sourceType: "social-monitor",
      sourceIdPrefix: "feedback:user_1",
      brief: {
        tokenBudget: 900,
        maxFacts: 6,
        memoryScopeExternalRefs: ["workspace:editorial-policy"],
      },
      preferences: [
        {
          text: "User prefers concise summaries grouped by provider.",
          tags: ["summary", "style"],
        },
        {
          text: "User wants Reddit discussions separated from GitHub issues.",
          memoryScopeExternalRef: "topic:ai-agents:preferences",
          idempotencyKey: "pref:ai-agents:provider-split",
          sourceRefs: [{ source_type: "feedback", source_id: "feedback_1" }],
          headers: { "x-preference-id": "provider-split" },
          tags: ["summary", "provider_split"],
        },
      ],
    });

    expect(plan.scope.memoryScopes).toEqual([
      {
        kind: "workspace",
        externalRef: "workspace-global",
        name: "Workspace global memory",
      },
      { kind: "user", externalRef: "user:user_1", name: "User 1 memory" },
      {
        kind: "topic",
        externalRef: "topic:ai-agents:preferences",
        name: "AI agents preferences",
      },
    ]);
    expect(plan.facts[0]).toMatchObject({
      text: "User prefers concise summaries grouped by provider.",
      memoryScopeExternalRef: "user:user_1",
      idempotencyKey: "pref:ai-agents:preference:0",
      sourceRefs: [
        {
          source_type: "social-monitor",
          source_id: "feedback:user_1:preference:0",
        },
      ],
      kind: "user_preference",
      classification: "internal",
      category: "summary_preference",
      tags: ["summary", "style"],
      ttlPolicy: "durable",
    });
    expect(plan.facts[1]).toMatchObject({
      headers: { "x-preference-id": "provider-split" },
      memoryScopeExternalRef: "topic:ai-agents:preferences",
      idempotencyKey: "pref:ai-agents:provider-split",
      sourceRefs: [{ source_type: "feedback", source_id: "feedback_1" }],
    });
    expect(plan.readScope).toEqual({
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRefs: [
        "workspace-global",
        "user:user_1",
        "topic:ai-agents:preferences",
        "workspace:editorial-policy",
      ],
      threadExternalRef: "digest:2026-06-22",
    });
    expect(plan.input).toMatchObject({
      headers: { "x-trace-id": "preference-plan" },
      spaceSlug: "social-monitor:tenant:workspace",
      memoryScopeExternalRef: "user:user_1",
      threadExternalRef: "digest:2026-06-22",
      idempotencyKeyPrefix: "pref:ai-agents",
      sourceType: "social-monitor",
      sourceIdPrefix: "feedback:user_1",
      topology: plan.scope.topology,
      outboxDrain: { throwOnFailure: true },
      brief: {
        query: "Which style should today's AI agents digest use?",
        topic: "AI agents digest preferences",
        spaceSlug: "social-monitor:tenant:workspace",
        memoryScopeExternalRefs: [
          "workspace-global",
          "user:user_1",
          "topic:ai-agents:preferences",
          "workspace:editorial-policy",
        ],
        threadExternalRef: "digest:2026-06-22",
        tokenBudget: 900,
        maxFacts: 6,
      },
    });
    expect(plan.summary).toEqual({
      spaceSlug: "social-monitor:tenant:workspace",
      preferenceCount: 2,
      defaultMemoryScopeExternalRef: "user:user_1",
      readScopeExternalRefs: [
        "workspace-global",
        "user:user_1",
        "topic:ai-agents:preferences",
        "workspace:editorial-policy",
      ],
      idempotencyKeys: [
        "pref:ai-agents:preference:0",
        "pref:ai-agents:provider-split",
      ],
    });
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.facts)).toBe(true);
    expect(Object.isFrozen(plan.readScope.memoryScopeExternalRefs)).toBe(true);
  });

  it("validates preference seeded brief plans", () => {
    expect(() =>
      createMemoryPreferenceBriefPlan({
        spaceSlug: "",
        query: "Daily digest",
        preferences: [],
      }),
    ).toThrow("createMemoryPreferenceBriefPlan requires spaceSlug");
    expect(() =>
      createMemoryPreferenceBriefPlan({
        spaceSlug: "workspace",
        query: "",
        preferences: [],
      }),
    ).toThrow("createMemoryPreferenceBriefPlan requires query");
    expect(() =>
      createMemoryPreferenceBriefPlan({
        spaceSlug: "workspace",
        query: "Daily digest",
        preferences: [{ text: "" }],
      }),
    ).toThrow("memory preference requires text");
  });
});
