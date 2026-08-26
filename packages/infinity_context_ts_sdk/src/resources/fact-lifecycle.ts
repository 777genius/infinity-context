import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import {
  optionalString,
  requireAllowedKeys,
  requireArray,
  requireAwareDateTime,
  requireInteger,
  requireString,
} from "../canonical-validation.js";
import { ValueError, withoutUndefined, type SingleScopeInput } from "../payload.js";
import type { ApiEnvelope, FactRecord, JsonObject, SourceRef } from "../types.js";

export interface TemporalEvidenceRefInput {
  readonly sourceRef: SourceRef;
  readonly evidenceId?: string;
}

export interface FactLifecycleInput extends SingleScopeInput, RequestControls {
  readonly evidenceRefs: readonly TemporalEvidenceRefInput[];
  readonly actorId?: string;
  readonly idempotencyKey: string;
}

export interface ConfirmFactInput extends FactLifecycleInput {
  readonly expectedVersion: number;
  readonly confirmedAt: string;
  readonly confirmationBasis: string;
}

export interface EndFactValidityInput extends FactLifecycleInput {
  readonly expectedVersion: number;
  readonly effectiveAt: string;
  readonly reasonCode: string;
}

export interface SupersedeFactInput extends FactLifecycleInput {
  readonly successorFactId: string;
  readonly expectedSuccessorVersion: number;
  readonly expectedPredecessorVersion: number;
  readonly effectiveAt: string;
  readonly reasonCode: string;
}

export interface DisputeFactInput extends FactLifecycleInput {
  readonly challengerFactId: string;
  readonly expectedChallengerVersion: number;
  readonly expectedChallengedVersion: number;
  readonly reasonCode: string;
}

export interface ReinstateSupersessionInput extends FactLifecycleInput {
  readonly supersessionDecisionId: string;
  readonly expectedRejectedSuccessorVersion: number;
  readonly expectedOriginalPredecessorVersion: number;
  readonly reasonCode: string;
}

export interface TemporalDecisionRecord extends JsonObject {
  readonly id: string;
  readonly type: string;
  readonly source_fact_id: string;
  readonly source_fact_version: number;
  readonly target_fact_id: string | null;
  readonly target_fact_version: number | null;
  readonly effective_at: string;
  readonly applied_at: string;
  readonly reason_code: string;
  readonly outbox_message_ids: readonly string[];
}

export interface SingleFactLifecycleResult extends JsonObject {
  readonly fact: FactRecord;
  readonly decision: TemporalDecisionRecord;
  readonly replayed: boolean;
}

export interface SupersedeFactResult extends JsonObject {
  readonly successor: FactRecord;
  readonly predecessor: FactRecord;
  readonly decision: TemporalDecisionRecord;
  readonly relation: JsonObject;
  readonly replayed: boolean;
}

export interface DisputeFactResult extends JsonObject {
  readonly challenger: FactRecord;
  readonly challenged: FactRecord;
  readonly decision: TemporalDecisionRecord;
  readonly replayed: boolean;
}

export interface ReinstateSupersessionResult extends JsonObject {
  readonly reinstated_fact: FactRecord;
  readonly rejected_successor: FactRecord;
  readonly decision: TemporalDecisionRecord;
  readonly relation: JsonObject;
  readonly replayed: boolean;
}

export class FactLifecycleClient {
  constructor(private readonly http: RequestExecutor) {}

  async confirm(factId: string, input: ConfirmFactInput): Promise<ApiEnvelope<SingleFactLifecycleResult>> {
    validateBase(factId, input, ["expectedVersion", "confirmedAt", "confirmationBasis"], "confirmFact");
    requireInteger(input.expectedVersion, "expectedVersion", 1);
    requireAwareDateTime(input.confirmedAt, "confirmedAt");
    requireString(input.confirmationBasis, "confirmationBasis", 1, 120);
    return this.http.request<ApiEnvelope<SingleFactLifecycleResult>>({
      method: "POST", path: `/v1/facts/${factId}/confirm`, ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        ...basePayload(input), expected_version: input.expectedVersion,
        confirmed_at: input.confirmedAt, confirmation_basis: input.confirmationBasis,
      },
    });
  }

  async endValidity(factId: string, input: EndFactValidityInput): Promise<ApiEnvelope<SingleFactLifecycleResult>> {
    validateBase(factId, input, ["expectedVersion", "effectiveAt", "reasonCode"], "endFactValidity");
    requireInteger(input.expectedVersion, "expectedVersion", 1);
    requireAwareDateTime(input.effectiveAt, "effectiveAt");
    requireString(input.reasonCode, "reasonCode", 1, 120);
    return this.http.request<ApiEnvelope<SingleFactLifecycleResult>>({
      method: "POST", path: `/v1/facts/${factId}/end-validity`, ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        ...basePayload(input), expected_version: input.expectedVersion,
        effective_at: input.effectiveAt, reason_code: input.reasonCode,
      },
    });
  }

  async supersede(factId: string, input: SupersedeFactInput): Promise<ApiEnvelope<SupersedeFactResult>> {
    validateBase(factId, input, ["successorFactId", "expectedSuccessorVersion", "expectedPredecessorVersion", "effectiveAt", "reasonCode"], "supersedeFact");
    requireString(input.successorFactId, "successorFactId", 1, 80);
    requireInteger(input.expectedSuccessorVersion, "expectedSuccessorVersion", 1);
    requireInteger(input.expectedPredecessorVersion, "expectedPredecessorVersion", 1);
    requireAwareDateTime(input.effectiveAt, "effectiveAt");
    requireString(input.reasonCode, "reasonCode", 1, 120);
    return this.http.request<ApiEnvelope<SupersedeFactResult>>({
      method: "POST", path: `/v1/facts/${factId}/supersede`, ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        ...basePayload(input), successor_fact_id: input.successorFactId,
        expected_successor_version: input.expectedSuccessorVersion,
        expected_predecessor_version: input.expectedPredecessorVersion,
        effective_at: input.effectiveAt, reason_code: input.reasonCode,
      },
    });
  }

  async dispute(factId: string, input: DisputeFactInput): Promise<ApiEnvelope<DisputeFactResult>> {
    validateBase(factId, input, ["challengerFactId", "expectedChallengerVersion", "expectedChallengedVersion", "reasonCode"], "disputeFact");
    requireString(input.challengerFactId, "challengerFactId", 1, 80);
    requireInteger(input.expectedChallengerVersion, "expectedChallengerVersion", 1);
    requireInteger(input.expectedChallengedVersion, "expectedChallengedVersion", 1);
    requireString(input.reasonCode, "reasonCode", 1, 120);
    return this.http.request<ApiEnvelope<DisputeFactResult>>({
      method: "POST", path: `/v1/facts/${factId}/dispute`, ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        ...basePayload(input), challenger_fact_id: input.challengerFactId,
        expected_challenger_version: input.expectedChallengerVersion,
        expected_challenged_version: input.expectedChallengedVersion,
        reason_code: input.reasonCode,
      },
    });
  }

  async reinstateSupersession(input: ReinstateSupersessionInput): Promise<ApiEnvelope<ReinstateSupersessionResult>> {
    validateBase(undefined, input, ["supersessionDecisionId", "expectedRejectedSuccessorVersion", "expectedOriginalPredecessorVersion", "reasonCode"], "reinstateSupersession");
    requireString(input.supersessionDecisionId, "supersessionDecisionId", 1, 80);
    requireInteger(input.expectedRejectedSuccessorVersion, "expectedRejectedSuccessorVersion", 1);
    requireInteger(input.expectedOriginalPredecessorVersion, "expectedOriginalPredecessorVersion", 1);
    requireString(input.reasonCode, "reasonCode", 1, 120);
    return this.http.request<ApiEnvelope<ReinstateSupersessionResult>>({
      method: "POST", path: "/v1/facts/reinstate-supersession", ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        ...basePayload(input), supersession_decision_id: input.supersessionDecisionId,
        expected_rejected_successor_version: input.expectedRejectedSuccessorVersion,
        expected_original_predecessor_version: input.expectedOriginalPredecessorVersion,
        reason_code: input.reasonCode,
      },
    });
  }
}

const BASE_KEYS = ["spaceId", "memoryScopeId", "threadId", "spaceSlug", "memoryScopeExternalRef", "threadExternalRef", "evidenceRefs", "actorId", "idempotencyKey", "headers", "signal", "timeoutMs"] as const;
const SOURCE_REF_KEYS = ["source_type", "source_id", "chunk_id", "char_start", "char_end", "quote_preview", "page_number", "time_start_ms", "time_end_ms", "bbox"] as const;

function validateBase(factId: string | undefined, input: FactLifecycleInput, extraKeys: readonly string[], label: string): void {
  if (factId !== undefined) requireString(factId, "factId", 1, 80);
  requireAllowedKeys(input, [...BASE_KEYS, ...extraKeys], label);
  optionalString(input.spaceId, "spaceId", 1, 80);
  optionalString(input.memoryScopeId, "memoryScopeId", 1, 80);
  optionalString(input.threadId, "threadId", 0, 80);
  optionalString(input.spaceSlug, "spaceSlug", 1, 160);
  optionalString(input.memoryScopeExternalRef, "memoryScopeExternalRef", 1, 200);
  optionalString(input.threadExternalRef, "threadExternalRef", 1, 200);
  optionalString(input.actorId, "actorId", 1, 160);
  requireString(input.idempotencyKey, "idempotencyKey", 1);
  requireArray(input.evidenceRefs, "evidenceRefs", 1, 20);
  for (const evidence of input.evidenceRefs) {
    requireAllowedKeys(evidence, ["sourceRef", "evidenceId"], "evidenceRef");
    requireAllowedKeys(evidence.sourceRef, SOURCE_REF_KEYS, "sourceRef");
    requireString(evidence.sourceRef.source_type, "sourceRef.source_type", 1, 80);
    requireString(evidence.sourceRef.source_id, "sourceRef.source_id", 1, 240);
    optionalString(evidence.sourceRef.chunk_id, "sourceRef.chunk_id", 1, 160);
    optionalString(evidence.sourceRef.quote_preview, "sourceRef.quote_preview", 0, 1_000);
    for (const field of ["char_start", "char_end", "time_start_ms", "time_end_ms"] as const) {
      const value = evidence.sourceRef[field];
      if (value !== undefined) requireInteger(value, `sourceRef.${field}`, 0);
    }
    if (evidence.sourceRef.page_number !== undefined) requireInteger(evidence.sourceRef.page_number, "sourceRef.page_number", 1);
    if (evidence.sourceRef.bbox !== undefined) {
      requireArray(evidence.sourceRef.bbox as readonly unknown[], "sourceRef.bbox", 4, 4);
      if (!(evidence.sourceRef.bbox as readonly unknown[]).every((value) => typeof value === "number" && Number.isFinite(value))) {
        throw new ValueError("sourceRef.bbox items must be finite numbers");
      }
    }
    optionalString(evidence.evidenceId, "evidenceId", 1, 160);
  }
}

function basePayload(input: FactLifecycleInput): JsonObject {
  return withoutUndefined({
    space_id: input.spaceId, memory_scope_id: input.memoryScopeId, thread_id: input.threadId,
    space_slug: input.spaceSlug, memory_scope_external_ref: input.memoryScopeExternalRef,
    thread_external_ref: input.threadExternalRef,
    evidence_refs: input.evidenceRefs.map((item) => withoutUndefined({ source_ref: item.sourceRef, evidence_id: item.evidenceId })),
    actor_id: input.actorId,
  });
}
