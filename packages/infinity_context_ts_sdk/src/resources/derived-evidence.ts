import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import { requireAllowedKeys, requireArray, requireSha256, requireString } from "../canonical-validation.js";
import { withoutUndefined } from "../payload.js";
import type { ApiEnvelope, JsonObject } from "../types.js";

export interface DerivedEvidenceScopeInput extends RequestControls {
  readonly spaceId: string;
  readonly memoryScopeId: string;
  readonly threadId?: string;
}

export interface ObserveDerivedPresenceInput extends DerivedEvidenceScopeInput {
  readonly expectedChunkIds?: readonly string[];
  readonly expectedFactIds?: readonly string[];
}

export interface DeleteQdrantEvidenceInput extends DerivedEvidenceScopeInput {
  readonly expectedChunkIds: readonly string[];
  readonly targetCommitmentSha256: string;
  readonly manifestBindingSha256: string;
}

export interface GraphitiIdentityManifestInput {
  readonly episodeIds?: readonly string[];
  readonly entityIds?: readonly string[];
  readonly mentionsEdgeIds?: readonly string[];
  readonly relatesToEdgeIds?: readonly string[];
}

export interface DeleteGraphitiEvidenceInput extends DerivedEvidenceScopeInput {
  readonly expectedFactIds: readonly string[];
  readonly identityManifest: GraphitiIdentityManifestInput;
  readonly targetCommitmentSha256: string;
  readonly manifestBindingSha256: string;
}

export interface DerivedPresenceData extends JsonObject {
  readonly scope: JsonObject;
  readonly outbox: JsonObject;
  readonly lanes: JsonObject;
}

export interface DerivedDeleteData extends JsonObject {
  readonly lane: "qdrant" | "graphiti";
  readonly target_commitment_sha256: string;
  readonly manifest_binding_sha256: string;
  readonly verified_absent: boolean;
  readonly passes: readonly JsonObject[];
}

export class DerivedEvidenceClient {
  constructor(private readonly http: RequestExecutor) {}

  async observePresence(input: ObserveDerivedPresenceInput): Promise<ApiEnvelope<DerivedPresenceData>> {
    validateScope(input, ["expectedChunkIds", "expectedFactIds"], "observeDerivedPresence");
    const chunks = input.expectedChunkIds ?? [];
    const facts = input.expectedFactIds ?? [];
    if (chunks.length === 0 && facts.length === 0) requireArray(chunks, "expected identities", 1, MAX_EXPECTED_IDENTITIES);
    validateIds(chunks, "expectedChunkIds", 0, MAX_EXPECTED_IDENTITIES);
    validateIds(facts, "expectedFactIds", 0, MAX_EXPECTED_IDENTITIES);
    return this.http.request<ApiEnvelope<DerivedPresenceData>>({
      method: "POST",
      path: "/v1/diagnostics/derived-evidence/presence",
      ...requestControls(input),
      json: withoutUndefined({
        space_id: input.spaceId,
        memory_scope_id: input.memoryScopeId,
        thread_id: input.threadId,
        expected_chunk_ids: chunks,
        expected_fact_ids: facts,
      }),
    });
  }

  async deleteQdrant(input: DeleteQdrantEvidenceInput): Promise<ApiEnvelope<DerivedDeleteData>> {
    validateScope(input, ["expectedChunkIds", "targetCommitmentSha256", "manifestBindingSha256"], "deleteQdrantEvidence");
    validateIds(input.expectedChunkIds, "expectedChunkIds", 1, MAX_EXPECTED_IDENTITIES);
    validateCommitments(input);
    return this.http.request<ApiEnvelope<DerivedDeleteData>>({
      method: "POST",
      path: "/v1/diagnostics/derived-evidence/qdrant/delete",
      ...requestControls(input),
      json: withoutUndefined({
        space_id: input.spaceId,
        memory_scope_id: input.memoryScopeId,
        thread_id: input.threadId,
        expected_chunk_ids: input.expectedChunkIds,
        target_commitment_sha256: input.targetCommitmentSha256,
        manifest_binding_sha256: input.manifestBindingSha256,
      }),
    });
  }

  async deleteGraphiti(input: DeleteGraphitiEvidenceInput): Promise<ApiEnvelope<DerivedDeleteData>> {
    validateScope(input, ["expectedFactIds", "identityManifest", "targetCommitmentSha256", "manifestBindingSha256"], "deleteGraphitiEvidence");
    validateIds(input.expectedFactIds, "expectedFactIds", 1, MAX_EXPECTED_IDENTITIES);
    requireAllowedKeys(input.identityManifest, ["episodeIds", "entityIds", "mentionsEdgeIds", "relatesToEdgeIds"], "identityManifest");
    for (const [key, ids] of Object.entries(input.identityManifest)) validateIds(ids ?? [], `identityManifest.${key}`, 0, MAX_GRAPH_PHYSICAL_IDENTITIES);
    validateCommitments(input);
    return this.http.request<ApiEnvelope<DerivedDeleteData>>({
      method: "POST",
      path: "/v1/diagnostics/derived-evidence/graphiti/delete",
      ...requestControls(input),
      json: withoutUndefined({
        space_id: input.spaceId,
        memory_scope_id: input.memoryScopeId,
        thread_id: input.threadId,
        expected_fact_ids: input.expectedFactIds,
        identity_manifest: {
          episode_ids: input.identityManifest.episodeIds ?? [],
          entity_ids: input.identityManifest.entityIds ?? [],
          mentions_edge_ids: input.identityManifest.mentionsEdgeIds ?? [],
          relates_to_edge_ids: input.identityManifest.relatesToEdgeIds ?? [],
        },
        target_commitment_sha256: input.targetCommitmentSha256,
        manifest_binding_sha256: input.manifestBindingSha256,
      }) as JsonObject,
    });
  }
}

const MAX_EXPECTED_IDENTITIES = 5_000;
const MAX_GRAPH_PHYSICAL_IDENTITIES = 20_000;
const CONTROLS = ["headers", "signal", "timeoutMs"] as const;

function validateScope(input: DerivedEvidenceScopeInput, fields: readonly string[], label: string): void {
  requireAllowedKeys(input, ["spaceId", "memoryScopeId", "threadId", ...fields, ...CONTROLS], label);
  requireString(input.spaceId, "spaceId", 1, 80);
  requireString(input.memoryScopeId, "memoryScopeId", 1, 80);
  if (input.threadId !== undefined) requireString(input.threadId, "threadId", 1, 80);
}

function validateIds(ids: readonly string[], label: string, minimum: number, maximum: number): void {
  requireArray(ids, label, minimum, maximum);
  for (const id of ids) requireString(id, `${label} item`);
}

function validateCommitments(input: { readonly targetCommitmentSha256: string; readonly manifestBindingSha256: string }): void {
  requireSha256(input.targetCommitmentSha256, "targetCommitmentSha256");
  requireSha256(input.manifestBindingSha256, "manifestBindingSha256");
}
