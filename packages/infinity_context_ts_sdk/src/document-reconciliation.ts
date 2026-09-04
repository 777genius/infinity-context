import { ValueError } from "./payload.js";
import { decodeRetrievalJson } from "./retrieval-json.js";
import type { JsonObject } from "./types.js";

export const EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1 = "document-reconciliation.v1" as const;
export const EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES = 65_536;

export type ExactDocumentReconciliationState =
  | "present"
  | "processing"
  | "indexed"
  | "deleted_or_proven_absent"
  | "conflict"
  | "unavailable";
export type ExactDocumentVisibilityEvidence =
  | "accepted"
  | "processing"
  | "indexed"
  | "not_queryable"
  | "unavailable";

export interface ExactDocumentReconciliationCapabilityV1 extends JsonObject {
  readonly contract_version: typeof EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1;
  readonly endpoint: "/v1/documents/reconcile-exact";
  readonly max_deadline_ms: number;
  readonly max_response_bytes: number;
  readonly read_only: true;
}

export interface ExactDocumentReconciliationResultV1 {
  readonly contract_version: typeof EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1;
  readonly state: ExactDocumentReconciliationState;
  readonly scope: {
    readonly space_id: string;
    readonly memory_scope_id: string;
    readonly thread_id: string | null;
  };
  readonly source_type: string;
  readonly source_external_id: string;
  readonly document_id: string | null;
  readonly canonical_status: string | null;
  readonly projection_generation: string | null;
  readonly profile_generation: string | null;
  readonly visibility: ExactDocumentVisibilityEvidence;
  readonly idempotency_key_matches: boolean | null;
}

export function assertExactDocumentReconciliationCapabilityV1(
  value: unknown,
): asserts value is ExactDocumentReconciliationCapabilityV1 {
  const item = exactObject(value, CAPABILITY_KEYS, "exact reconciliation capability");
  if (item.contract_version !== EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1) fail("capability version mismatch");
  if (item.endpoint !== "/v1/documents/reconcile-exact") fail("capability endpoint mismatch");
  integer(item.max_deadline_ms, 50, 10_000, "capability max_deadline_ms");
  if (item.max_response_bytes !== EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES) fail("capability response byte limit mismatch");
  if (item.read_only !== true) fail("capability must attest a read-only operation");
}

export function decodeExactDocumentReconciliationResponseV1(
  body: Uint8Array | string,
  expected: {
    readonly spaceId: string;
    readonly memoryScopeId: string;
    readonly threadId?: string | null;
    readonly sourceType: string;
    readonly sourceExternalId: string;
    readonly projectionGeneration?: string;
    readonly profileGeneration?: string;
  },
): ExactDocumentReconciliationResultV1 {
  const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
  if (bytes.byteLength > EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES) fail("response exceeds byte limit");
  let parsed: unknown;
  try {
    parsed = decodeRetrievalJson(bytes);
  } catch {
    fail("response is malformed JSON");
  }
  const root = exactObject(parsed, RESPONSE_KEYS, "response");
  const data = exactObject(root.data, RESULT_KEYS, "response.data");
  if (data.contract_version !== EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1) fail("response version mismatch");
  const state = member(data.state, STATES, "response state");
  const visibility = member(data.visibility, VISIBILITY, "response visibility");
  const scope = exactObject(data.scope, SCOPE_KEYS, "response scope");
  const spaceId = text(scope.space_id, 80, "response scope.space_id");
  const memoryScopeId = text(scope.memory_scope_id, 80, "response scope.memory_scope_id");
  const threadId = nullableText(scope.thread_id, 80, "response scope.thread_id");
  const sourceType = text(data.source_type, 80, "response source_type");
  const sourceExternalId = text(data.source_external_id, 240, "response source_external_id");
  if (spaceId !== expected.spaceId || memoryScopeId !== expected.memoryScopeId ||
      threadId !== (expected.threadId ?? null) || sourceType !== expected.sourceType ||
      sourceExternalId !== expected.sourceExternalId) fail("response exact identity mismatch");
  const projectionGeneration = nullableText(data.projection_generation, 256, "response projection_generation");
  const profileGeneration = nullableText(data.profile_generation, 160, "response profile_generation");
  if (expected.projectionGeneration !== undefined && state !== "conflict" &&
      projectionGeneration !== expected.projectionGeneration) fail("response weakened projection filter");
  if (expected.profileGeneration !== undefined && !["unavailable", "conflict"].includes(state) &&
      profileGeneration !== expected.profileGeneration) fail("response weakened profile filter");
  if (state === "indexed" && visibility !== "indexed") fail("indexed state lacks indexed evidence");
  if (["deleted_or_proven_absent", "conflict", "unavailable"].includes(state) && visibility === "indexed") {
    fail("non-queryable state claimed indexed visibility");
  }
  const match = data.idempotency_key_matches;
  if (match !== null && typeof match !== "boolean") fail("response idempotency match is invalid");
  return {
    contract_version: EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
    state,
    scope: { space_id: spaceId, memory_scope_id: memoryScopeId, thread_id: threadId },
    source_type: sourceType,
    source_external_id: sourceExternalId,
    document_id: nullableText(data.document_id, 80, "response document_id"),
    canonical_status: nullableText(data.canonical_status, 40, "response canonical_status"),
    projection_generation: projectionGeneration,
    profile_generation: profileGeneration,
    visibility,
    idempotency_key_matches: match,
  };
}

const STATES = new Set<ExactDocumentReconciliationState>(["present", "processing", "indexed", "deleted_or_proven_absent", "conflict", "unavailable"]);
const VISIBILITY = new Set<ExactDocumentVisibilityEvidence>(["accepted", "processing", "indexed", "not_queryable", "unavailable"]);
const CAPABILITY_KEYS = [
  "contract_version", "endpoint", "max_deadline_ms", "max_response_bytes", "read_only",
] as const;
const RESPONSE_KEYS = ["data"] as const;
const RESULT_KEYS = [
  "contract_version", "state", "scope", "source_type", "source_external_id", "document_id",
  "canonical_status", "projection_generation", "profile_generation", "visibility",
  "idempotency_key_matches",
] as const;
const SCOPE_KEYS = ["space_id", "memory_scope_id", "thread_id"] as const;

function object(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object`);
  return value as Record<string, unknown>;
}
function exactObject(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  const item = object(value, label);
  const actual = Object.keys(item);
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) {
    fail(`${label} keys are invalid`);
  }
  return item;
}
function text(value: unknown, maxBytes: number, label: string): string {
  if (typeof value !== "string" || value.length === 0 || new TextEncoder().encode(value).byteLength > maxBytes || /[\u0000-\u001f\u007f-\u009f]/u.test(value)) fail(`${label} is invalid`);
  return value;
}
function nullableText(value: unknown, maxBytes: number, label: string): string | null {
  return value === null ? null : text(value, maxBytes, label);
}
function integer(value: unknown, min: number, max: number, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) fail(`${label} is invalid`);
  return value as number;
}
function member<T extends string>(value: unknown, values: Set<T>, label: string): T {
  if (typeof value !== "string" || !values.has(value as T)) fail(`${label} is invalid`);
  return value as T;
}
function fail(message: string): never { throw new ValueError(message); }

export const exactDocumentReconciliationValidation = { text, integer };
