export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | readonly JsonValue[];
export interface JsonObject {
  readonly [key: string]: JsonValue | undefined;
}

export type MaybePromise<T> = T | Promise<T>;

export type QueryParams = Record<string, unknown>;

export interface ApiEnvelope<T = JsonValue> {
  readonly data: T;
}

export interface SourceRef extends JsonObject {
  readonly source_type: string;
  readonly source_id: string;
}

export type Classification = "public" | "internal" | "confidential" | "restricted" | "unknown";

export interface Space {
  readonly id: string;
  readonly slug: string;
  readonly name: string;
  readonly status: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface MemoryScopeRecord {
  readonly id: string;
  readonly space_id: string;
  readonly external_ref: string;
  readonly name: string;
  readonly status: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface UserRecord {
  readonly id: string;
  readonly external_ref: string;
  readonly display_name: string;
  readonly email?: string | null;
  readonly status: string;
  readonly metadata: JsonObject;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface SpaceMembership {
  readonly id: string;
  readonly space_id: string;
  readonly user_id: string;
  readonly role: string;
  readonly status: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface FactRecord extends JsonObject {
  readonly id: string;
  readonly text: string;
  readonly kind: string;
  readonly status: string;
  readonly version: number;
}

export interface DocumentRecord extends JsonObject {
  readonly id: string;
  readonly title: string;
  readonly status: string;
}

export interface AssetRecord extends JsonObject {
  readonly id: string;
  readonly filename: string;
  readonly status: string;
}

export interface AssetExtractionJobRecord extends JsonObject {
  readonly id: string;
  readonly asset_id: string;
  readonly space_id: string;
  readonly memory_scope_id: string;
  readonly thread_id?: string | null;
  readonly parser_profile: string;
  readonly parser_config_hash: string;
  readonly source_sha256_hex: string;
  readonly status: string;
  readonly attempt_count: number;
  readonly safe_error_code?: string | null;
  readonly safe_error_message?: string | null;
  readonly parser_name?: string | null;
  readonly parser_version?: string | null;
  readonly model_version?: string | null;
  readonly result_document_ids: readonly string[];
  readonly metadata: JsonObject;
  readonly progress: JsonObject;
  readonly execution: JsonObject;
  readonly usage: JsonObject;
  readonly created_at: string;
  readonly updated_at: string;
  readonly started_at?: string | null;
  readonly finished_at?: string | null;
}

export interface ExtractionArtifactRecord extends JsonObject {
  readonly id: string;
  readonly job_id: string;
  readonly asset_id: string;
  readonly artifact_type: string;
  readonly storage_backend: string;
  readonly download_path: string;
  readonly sha256_hex: string;
  readonly byte_size: number;
  readonly metadata: JsonObject;
  readonly created_at: string;
}

export interface AssetExtractionDetails extends AssetExtractionJobRecord {
  readonly artifacts: readonly ExtractionArtifactRecord[];
}

export interface ThreadMemoryStatusData extends JsonObject {
  readonly chunks: number;
  readonly facts: number;
  readonly jobs: number;
  readonly pending_jobs: number;
}

export interface DeleteThreadMemoryData extends JsonObject {
  readonly deleted_chunks: number;
  readonly deleted_facts: number;
  readonly deleted_jobs: number;
}

export interface UsagePlanData extends JsonObject {
  readonly tier: string;
  readonly display_name: string;
  readonly media_analysis_seconds_per_month: number;
}

export interface UsageResourceData extends JsonObject {
  readonly resource: string;
  readonly limit: number;
  readonly used: number;
  readonly remaining: number;
  readonly window_start: string;
  readonly window_end: string;
}

export interface UsageSummaryData extends JsonObject {
  readonly space_id: string;
  readonly plan: UsagePlanData;
  readonly resources: readonly UsageResourceData[];
}

export interface SuggestionRecord extends JsonObject {
  readonly id: string;
  readonly status: string;
  readonly candidate_text: string;
}

export interface ContextLinkRecord extends JsonObject {
  readonly id: string;
  readonly space_id: string;
  readonly memory_scope_id: string;
  readonly source_type: string;
  readonly source_id: string;
  readonly target_type: string;
  readonly target_id: string;
  readonly relation_type: string;
  readonly confidence: string;
  readonly reason: string;
  readonly status: string;
  readonly metadata: JsonObject;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ContextLinkSuggestionRecord extends JsonObject {
  readonly id: string;
  readonly space_id: string;
  readonly memory_scope_id: string;
  readonly source_type: string;
  readonly source_id: string;
  readonly target_type: string;
  readonly target_id: string;
  readonly relation_type: string;
  readonly confidence: string;
  readonly reason: string;
  readonly score: number;
  readonly status: string;
  readonly review_actionable: boolean;
  readonly available_review_actions: readonly string[];
  readonly review_state_reason: string;
  readonly metadata: JsonObject;
  readonly created_at: string;
  readonly updated_at: string;
  readonly reviewed_at?: string | null;
  readonly review_reason?: string | null;
  readonly review_audit?: JsonObject;
}

export interface CaptureRecord extends JsonObject {
  readonly id: string;
  readonly space_id: string;
  readonly memory_scope_id: string;
  readonly thread_id?: string | null;
  readonly source_agent: string;
  readonly source_kind: string;
  readonly event_type: string;
  readonly actor_role: string;
  readonly text_preview: string;
  readonly payload_hash: string;
  readonly status: string;
  readonly consolidation_status: string;
  readonly trust_level: string;
  readonly source_authority: string;
  readonly sensitivity: string;
  readonly data_classification: string;
  readonly evidence_refs: readonly SourceRef[];
  readonly metadata: JsonObject;
  readonly created_at: string;
  readonly updated_at: string;
  readonly occurred_at: string;
  readonly received_at: string;
  readonly trace_id?: string | null;
  readonly versions: JsonObject;
  readonly last_error_code?: string | null;
}

export interface AnchorRecord extends JsonObject {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly status: string;
}

export interface InfinityContextHealth {
  readonly status: string;
  readonly service: string;
  readonly deploy_profile: string;
}

export interface InfinityContextCapabilities extends JsonObject {
  readonly api_version?: string;
  readonly server_version?: string;
  readonly service_name?: string;
  readonly service_revision?: string | null;
  readonly embedding_profile_id?: string | null;
  readonly embedding_profile_digest_sha256?: `sha256:${string}` | null;
  readonly deploy_profile?: string;
  readonly enabled_adapters?: string[];
  readonly supports_qdrant?: boolean;
  readonly supports_graphiti?: boolean;
  readonly context?: JsonObject & {
    readonly retrieval?: JsonObject & import("./retrieval-v2-types.js").ContextRetrievalCapabilityV2;
  };
}
