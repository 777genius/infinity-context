import { expect } from "vitest";
import type { HttpRequest, HttpResponse, HttpTransport } from "../src/index.js";

export class RecordingTransport implements HttpTransport {
  readonly requests: HttpRequest[] = [];
  readonly bodies: unknown[] = [];
  #responses: HttpResponse[];

  constructor(responses: HttpResponse[]) {
    this.#responses = [...responses];
  }

  async send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    if (request.body?.kind === "json") {
      this.bodies.push(request.body.value);
    }
    return this.#responses.shift() ?? jsonResponse({ data: { ok: true } });
  }
}

export class HangingTransport implements HttpTransport {
  readonly requests: HttpRequest[] = [];

  send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    return new Promise((_, reject) => {
      request.signal?.addEventListener("abort", () => {
        const reason = request.signal?.reason;
        reject(reason instanceof Error ? reason : new DOMException("Request aborted", "AbortError"));
      }, { once: true });
    });
  }
}

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): HttpResponse {
  return {
    status,
    headers: new Headers(headers),
    body: JSON.stringify(body),
  };
}

export async function waitForRecordedRequests(
  source: { readonly requests: readonly HttpRequest[] },
  count: number,
): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (source.requests.length >= count) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error(`Expected ${count} recorded request(s), got ${source.requests.length}`);
}

export function expectCompletedSignalsDetached(
  signals: readonly (AbortSignal | undefined)[],
  controller: AbortController,
  reason: string,
): void {
  expect(signals.every((signal) => signal !== undefined && !signal.aborted)).toBe(true);
  controller.abort(reason);
  expect(signals.every((signal) => signal !== undefined && !signal.aborted)).toBe(true);
}

export function spaceRecord(id: string, slug: string) {
  return {
    id,
    slug,
    name: "SDK proof",
    status: "active",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function scopeRecord(id: string, externalRef: string) {
  return {
    id,
    space_id: "space_1",
    external_ref: externalRef,
    name: externalRef,
    status: "active",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function userRecord(id: string, externalRef: string) {
  return {
    id,
    external_ref: externalRef,
    display_name: "SDK user",
    email: null,
    status: "active",
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function membershipRecord(id: string, spaceId: string, userId: string, role = "member") {
  return {
    id,
    space_id: spaceId,
    user_id: userId,
    role,
    status: "active",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function outboxItem(id: number, status: string) {
  return {
    id,
    event_type: "fact.upsert",
    aggregate_type: "memory_fact",
    aggregate_id: `fact_${id}`,
    aggregate_version: 1,
    workload_class: "projection",
    fairness_key: "space_1",
    status,
    attempt_count: status === "retry_pending" ? 1 : 0,
    last_safe_error: null,
    last_safe_diagnostic_code: null,
    next_attempt_at: "2026-06-06T00:00:00.000Z",
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function factRecord(id: string) {
  return {
    id,
    text: `${id} text`,
    kind: "note",
    status: "active",
    version: 1,
  };
}

export function documentRecord(id: string) {
  return {
    id,
    title: `${id} title`,
    status: "active",
  };
}

export function documentChunkRecord(id: string, sequence: number) {
  return {
    id,
    document_id: "doc_1",
    sequence,
    text: `${id} text`,
    token_estimate: 3,
    metadata: {},
  };
}

export function memorySuggestionRecord(id: string) {
  return {
    id,
    status: "pending",
    candidate_text: `${id} candidate`,
  };
}

export function anchorRecord(id: string, label: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    kind: "project",
    normalized_key: label.toLowerCase().replaceAll(" ", "-"),
    label,
    aliases: [],
    description: null,
    status: "active",
    confidence: "medium",
    evidence_refs: [],
    observed_at: "2026-06-06T00:00:00.000Z",
    valid_from: null,
    valid_to: null,
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function memoryBrowserData() {
  return {
    generated_at: "2026-06-22T10:00:00.000Z",
    memory_scope: {
      id: "scope_1",
      space_id: "space_1",
      external_ref: "topic:ai-agents",
      name: "AI agents",
      status: "active",
      created_at: "2026-06-22T10:00:00.000Z",
      updated_at: "2026-06-22T10:00:00.000Z",
    },
    facts: [factRecord("fact_1")],
    episodes: [],
    documents: [],
    chunks: [],
    extraction_jobs: [],
    threads: [],
    captures: [],
    assets: [],
    anchors: [],
    context_links: [],
    context_link_suggestions: [],
    stats: { facts: 1 },
    visual_summary: {},
    quick_actions: [],
    diagnostics: {},
  };
}

export function operationsConsoleData() {
  return {
    generated_at: "2026-06-22T10:00:00.000Z",
    scope: { space_id: "space_1", memory_scope_id: "scope_1" },
    extraction_status_counts: {},
    link_suggestion_status_counts: {},
    extraction_jobs: [],
    context_link_suggestions: [],
    diagnostics: { queue_lag: 0 },
  };
}

export function contextResponse(runId: string, diagnostics: Record<string, unknown>) {
  return {
    data: {
      bundle_id: "bundle_1",
      rendered_text: `${runId}: Qdrant and Graphiti memory evidence.`,
      items: [
        {
          item_id: "item_1",
          item_type: "fact",
          text: `${runId}: Qdrant owns vector recall.`,
          score: 0.9,
          source_refs: [{ source_type: "sdk-full-memory-proof", source_id: "fact" }],
        },
      ],
      top_evidence: [],
      answer_support: {
        status: "supported",
        items_returned: 1,
        coverage: {},
        policy: {},
        warnings: [],
      },
      diagnostics: {
        vector_status: "ok",
        graph_status: "ok",
        rag_status: "ok",
        ...diagnostics,
      },
    },
  };
}

export function searchResponse(diagnostics: Record<string, unknown>) {
  return {
    data: {
      items: [
        {
          item_id: "item_1",
          item_type: "fact",
          text: "Qdrant owns vector recall.",
          score: 0.9,
          source_refs: [{ source_type: "sdk-full-memory-proof", source_id: "fact" }],
        },
      ],
      top_evidence: [],
      diagnostics: {
        vector_status: "ok",
        graph_status: "ok",
        ...diagnostics,
      },
    },
  };
}

export function digestResponse(runId: string) {
  return {
    data: {
      digest_id: "digest_1",
      topic: "SDK proof",
      rendered_markdown: `${runId}: concise digest`,
      sections: [],
      source_refs: [],
      token_estimate: 10,
      diagnostics: { evidence_only: true },
    },
  };
}

export function contextLinkRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    source_type: "capture",
    source_id: "capture_1",
    target_type: "fact",
    target_id: "fact_1",
    relation_type: "supports",
    confidence: "medium",
    reason: "reviewed",
    status: "active",
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
  };
}

export function contextLinkSuggestionRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    source_type: "capture",
    source_id: "capture_1",
    target_type: "fact",
    target_id: "fact_1",
    relation_type: "supports",
    confidence: "medium",
    reason: "semantic match",
    score: 0.91,
    status: "pending",
    review_actionable: true,
    available_review_actions: ["approve", "reject"],
    review_state_reason: "pending_user_review",
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
    reviewed_at: null,
    review_reason: null,
    review_audit: { events: [], event_count: 0, truncated: false },
  };
}

export function captureRecord(id: string) {
  return {
    id,
    space_id: "space_1",
    memory_scope_id: "scope_1",
    thread_id: "thread_1",
    source_agent: "social-monitor",
    source_kind: "hook",
    event_type: "summary.feedback.recorded",
    actor_role: "user",
    text_preview: "User says Reddit source freshness matters.",
    payload_hash: "hash_1",
    status: "active",
    consolidation_status: "pending",
    trust_level: "high",
    source_authority: "user_statement",
    sensitivity: "medium",
    data_classification: "internal",
    evidence_refs: [{ source_type: "summary", source_id: "summary_1" }],
    metadata: {},
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:00:00.000Z",
    occurred_at: "2026-06-06T00:00:00.000Z",
    received_at: "2026-06-06T00:00:01.000Z",
    trace_id: "trace_1",
    versions: {
      schema: "capture.v1",
      parser: "parser.v1",
      redaction: "redaction.v1",
      admission: "admission.v1",
      normalization: "normalization.v1",
      policy: "policy.v1",
      extractor: "extractor.v1",
      resolver: "resolver.v1",
    },
    last_error_code: null,
  };
}

export function assetExtractionJobRecord(id: string) {
  return {
    id,
    asset_id: "asset_1",
    space_id: "space_1",
    memory_scope_id: "scope_1",
    thread_id: "thread_1",
    parser_profile: "markdown-strict",
    parser_config_hash: "parser_hash_1",
    source_sha256_hex: "sha_1",
    status: "running",
    attempt_count: 1,
    safe_error_code: null,
    safe_error_message: null,
    parser_name: "markdown",
    parser_version: "1.0.0",
    model_version: null,
    result_document_ids: ["document_1"],
    metadata: {},
    progress: { phase: "parsing", percent: 60 },
    execution: { available_actions: ["cancel"] },
    usage: { input_bytes: 1024 },
    created_at: "2026-06-06T00:00:00.000Z",
    updated_at: "2026-06-06T00:01:00.000Z",
    started_at: "2026-06-06T00:00:05.000Z",
    finished_at: null,
  };
}

export function extractionArtifactRecord(id: string) {
  return {
    id,
    job_id: "job_1",
    asset_id: "asset_1",
    artifact_type: "markdown",
    storage_backend: "local",
    download_path: `/v1/extraction-artifacts/${id}/download`,
    sha256_hex: "artifact_sha_1",
    byte_size: 256,
    metadata: {},
    created_at: "2026-06-06T00:02:00.000Z",
  };
}
