export const CONTEXT_RETRIEVAL_CONTRACT = "context-retrieval.v2" as const;
export const CONTEXT_RETRIEVAL_RANKING_POLICY = "weighted_rrf_canonical_preferences.v1" as const;

export interface RetrievalScopeInput {
  readonly spaceId: string;
  readonly memoryScopeId: string;
  readonly threadId?: string | null;
}

export interface RetrievalQueryInput {
  readonly queryId: string;
  readonly query: string;
  readonly weightMicros?: number;
}

export interface RetrievalTimeIntervalInput {
  readonly startAt: string;
  readonly endAt: string;
}

export interface RetrievalRelativeTimeIntervalInput {
  readonly startMs: number;
  readonly endMs: number;
}

export interface RetrievalSourceGenerationInput {
  readonly sourceKey: string;
  readonly projectionGeneration: string;
}

export interface RetrievalWeightedKeyInput {
  readonly key: string;
  readonly weightMicros: number;
}

export interface RetrievalHardFiltersInput {
  readonly sourceGenerations: readonly RetrievalSourceGenerationInput[];
  readonly excludedSourceKeys: readonly string[];
  readonly documentKeys: readonly string[];
  readonly kinds: readonly string[];
  readonly category: string | null;
  readonly tagsAny: readonly string[];
  readonly tagsAll: readonly string[];
  readonly tagsNone: readonly string[];
  readonly actorKeys: readonly string[];
  readonly timeInterval: RetrievalTimeIntervalInput | null;
  readonly relativeTimeInterval: RetrievalRelativeTimeIntervalInput | null;
}

export interface RetrievalSoftPreferencesInput {
  readonly sourcePreferences: readonly RetrievalWeightedKeyInput[];
  readonly actorPreferences: readonly RetrievalWeightedKeyInput[];
  readonly timeInterval: RetrievalTimeIntervalInput | null;
  readonly relativeTimeInterval: RetrievalRelativeTimeIntervalInput | null;
  readonly timeWeightMicros: number | null;
}

export interface RetrievalBoundsInput {
  readonly candidateLimit: number;
  readonly resultLimit: number;
  readonly neighborRadius: number;
  readonly responseByteLimit: number;
  readonly deadlineMs: number;
}

export interface RetrieveContextInput {
  readonly contractVersion: typeof CONTEXT_RETRIEVAL_CONTRACT;
  readonly capabilityFingerprint: string;
  readonly profileId: string;
  readonly scope: RetrievalScopeInput;
  readonly queries: readonly RetrievalQueryInput[];
  readonly filters: RetrievalHardFiltersInput;
  readonly softPreferences: RetrievalSoftPreferencesInput;
  readonly bounds: RetrievalBoundsInput;
}

export type RetrievalRawScoreKind = "similarity" | "distance" | "relevance" | "bm25";

export interface RetrievalContribution {
  readonly provider_id: string;
  readonly query_id: string;
  readonly provider_rank: number;
  readonly provider_weight_micros: number;
  readonly query_weight_micros: number;
  readonly contribution_score_picos: number;
  readonly provider_weight: number;
  readonly query_weight: number;
  readonly contribution: number;
  readonly raw_score_kind: RetrievalRawScoreKind | null;
  readonly raw_score_value: number | null;
}

export interface RetrievalNeighbor {
  readonly locator: string;
  readonly source_key: string;
  readonly document_key: string;
  readonly chunk_key: string;
  readonly canonical_identity: string;
  /** Positive safe integer; wider JSON integers cannot be represented losslessly by this SDK. */
  readonly canonical_version: number;
  readonly lifecycle_status: "active";
  readonly relation: "neighbor";
  readonly distance: -2 | -1 | 1 | 2;
}

export interface RetrievalCandidate {
  readonly locator: string;
  readonly source_key: string;
  readonly document_key: string;
  readonly chunk_key: string;
  readonly canonical_identity: string;
  /** Positive safe integer; wider JSON integers cannot be represented losslessly by this SDK. */
  readonly canonical_version: number;
  readonly lifecycle_status: "active";
  readonly relation: "direct";
  readonly distance: 0;
  readonly provider_rank: number;
  readonly fused_score: number;
  readonly base_score_picos: number;
  readonly source_requested_weight_micros: number;
  readonly source_matched_weight_micros: number;
  readonly actor_requested_weight_micros: number;
  readonly actor_matched_weight_micros: number;
  readonly time_requested_weight_micros: number;
  readonly time_matched_weight_micros: number;
  readonly preference_score_micros: number;
  readonly preference_boost_micros: number;
  readonly rerank_score_picos: number;
  readonly matched_query_ids: readonly string[];
  readonly contributions: readonly RetrievalContribution[];
  readonly neighbors: readonly RetrievalNeighbor[];
}

export type RetrievalProviderStatus = "available" | "unavailable" | "unqualified";
export type RetrievalProviderReasonCode =
  | "provider_error"
  | "provider_unavailable"
  | "provider_unqualified"
  | "provider_truncated";

export interface RetrievalProviderOutcome {
  readonly provider_id: string;
  readonly status: RetrievalProviderStatus;
  readonly reason_code: RetrievalProviderReasonCode | null;
}

export interface RetrievalAppliedBounds {
  readonly candidate_limit: number;
  readonly result_limit: number;
  readonly neighbor_radius: number;
  readonly response_byte_limit: number;
  readonly deadline_ms: number;
  readonly returned_seeds: number;
  readonly returned_neighbors: number;
}

export type RetrievalDegradationReasonCode =
  | "capability_profile_mismatch"
  | "neighbor_capability_unavailable"
  | "optional_provider_failed"
  | "optional_provider_unavailable"
  | "optional_provider_unqualified"
  | "response_byte_limit_exceeded";

export interface RetrieveContextResponse {
  readonly contract_version: typeof CONTEXT_RETRIEVAL_CONTRACT;
  readonly ranking_policy: typeof CONTEXT_RETRIEVAL_RANKING_POLICY;
  readonly status: RetrievalProviderStatus;
  readonly capability_fingerprint: string;
  readonly profile_id: string;
  readonly coverage: "top_k_only";
  readonly applied_bounds: RetrievalAppliedBounds;
  readonly candidates: readonly RetrievalCandidate[];
  readonly provider_outcomes: readonly RetrievalProviderOutcome[];
  readonly degradation_reason_codes: readonly RetrievalDegradationReasonCode[];
}

export type RetrievalHardFilterSignal =
  | "source_generations"
  | "excluded_source_keys"
  | "document_keys"
  | "kinds"
  | "category"
  | "tags_any"
  | "tags_all"
  | "tags_none"
  | "actor_keys"
  | "time_interval"
  | "relative_time_interval";

export type RetrievalSoftPreferenceSignal =
  | "source_preferences"
  | "actor_preferences"
  | "time_interval"
  | "relative_time_interval";

export interface RetrievalCapabilityBounds {
  readonly query_variants: readonly [1, 6];
  readonly query_characters: readonly [1, 512];
  readonly provider_lanes: readonly [1, 4];
  readonly provider_rank: readonly [1, 1000];
  readonly source_generations: readonly [1, 100];
  readonly candidate_limit: readonly [1, 1000];
  readonly result_limit: readonly [1, 50];
  readonly neighbor_radius: readonly [0, 2];
  readonly response_byte_limit: readonly [16384, 1048576];
  readonly deadline_ms: readonly [1, 2000];
  readonly weight_micros: readonly [100000, 10000000];
}

export interface RetrievalCapability {
  readonly endpoint: "/v1/context/retrieve";
  readonly contract_version: typeof CONTEXT_RETRIEVAL_CONTRACT;
  readonly ranking_policy: typeof CONTEXT_RETRIEVAL_RANKING_POLICY;
  readonly ranking_parameters: RetrievalRankingParameters;
  readonly capability_fingerprint: string;
  readonly profile_id: string;
  readonly service_revision: string;
  readonly sdk_revision: string;
  readonly attribute_schema: "document-retrieval-projection.v1";
  readonly index_profile_digest: string;
  readonly coverage: "top_k_only";
  readonly supports_neighbors: boolean;
  readonly bounds: RetrievalCapabilityBounds;
  readonly hard_filter_signals: readonly RetrievalHardFilterSignal[];
  readonly soft_preference_signals: readonly RetrievalSoftPreferenceSignal[];
  readonly required_provider_lanes: readonly string[];
  readonly provider_lanes: readonly RetrievalCapabilityProviderLane[];
}

export interface RetrievalRankingParameters {
  readonly rank_constant: 60;
  readonly weight_scale_micros: 1000000;
  readonly score_scale_picos: 1000000000000;
  readonly preference_scale_micros: 1000000;
  readonly max_preference_boost_micros: 250000;
  readonly contribution_rounding: "round_half_even";
  readonly preference_rounding: "floor";
  readonly canonical_signal_match_policy: "canonical_exact_key_interval_overlap.v1";
}

export interface RetrievalCapabilityProviderLane {
  readonly provider_id: string;
  readonly required: boolean;
  readonly healthy: boolean;
  readonly weight_micros: number;
  readonly profile_qualified: boolean;
}

export interface RequiredRetrievalCapability {
  readonly capabilityFingerprint: string;
  readonly profileId: string;
  readonly requiredProviderLanes: readonly string[];
}
