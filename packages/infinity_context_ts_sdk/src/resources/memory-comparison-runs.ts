import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import { requireAllowedKeys, requireJsonObject, requireSha256, requireString } from "../canonical-validation.js";
import { ValueError } from "../payload.js";
import type { ApiEnvelope, JsonObject } from "../types.js";

interface IdempotentRequest extends RequestControls {
  readonly idempotencyKey: string;
}

export interface RegisterMemoryComparisonRunInput extends IdempotentRequest {
  readonly schemaVersion: "memory-comparison-run-registration.v2";
  readonly runIdSha256: string;
  readonly bindingCommitmentSha256: string;
  readonly infinityTargetIdentitySha256: string;
  readonly spaceSlug: string;
  readonly cleanupPlan: JsonObject;
  readonly cleanupPlanSha256: string;
}

export interface CleanupTargetAuthorityInput extends RequestControls {
  readonly schemaVersion: "memory-comparison-cleanup-target-authority-request.v1";
  readonly infinityTargetIdentitySha256: string;
}

export interface SealProjectionManifestInput extends RequestControls {
  readonly schemaVersion: "memory-comparison-projection-manifest-seal.v1";
  readonly projectionManifestSha256: string;
  readonly projectionManifest: JsonObject;
}

export interface CleanupMemoryComparisonRunInput extends IdempotentRequest {
  readonly schemaVersion: "memory-comparison-run-cleanup.v2";
  readonly bindingCommitmentSha256: string;
  readonly infinityTargetIdentitySha256: string;
  readonly spaceId: string;
  readonly spaceSlug: string;
  readonly cleanupPlanSha256: string;
}

export interface FinalizeMemoryComparisonCleanupInput extends IdempotentRequest {
  readonly schemaVersion: "memory-comparison-run-cleanup-finalize.v2";
  readonly receiptSha256: string;
  readonly cleanupPlanSha256: string;
}

export interface FinalizeMemoryComparisonAbortInput extends IdempotentRequest {
  readonly schemaVersion: "memory-comparison-run-abort-finalize.v2";
  readonly bindingCommitmentSha256: string;
  readonly infinityTargetIdentitySha256: string;
  readonly spaceId: string;
  readonly spaceSlug: string;
  readonly receiptSha256: string;
  readonly cleanupPlanSha256: string;
}

export interface MemoryComparisonRunData extends JsonObject {
  readonly schema_version: string;
  readonly authority: "infinity_canonical";
  readonly run_id_sha256: string;
  readonly state: string;
}

export class MemoryComparisonRunsClient {
  constructor(private readonly http: RequestExecutor) {}

  async register(input: RegisterMemoryComparisonRunInput): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    exact(input, ["schemaVersion", "runIdSha256", "bindingCommitmentSha256", "infinityTargetIdentitySha256", "spaceSlug", "cleanupPlan", "cleanupPlanSha256", "idempotencyKey"], "registerMemoryComparisonRun");
    requireSchema(input.schemaVersion, "memory-comparison-run-registration.v2");
    requireSha256(input.runIdSha256, "runIdSha256");
    requireSha256(input.bindingCommitmentSha256, "bindingCommitmentSha256");
    requireSha256(input.infinityTargetIdentitySha256, "infinityTargetIdentitySha256");
    requireSpaceSlug(input.spaceSlug);
    requireJsonObject(input.cleanupPlan, "cleanupPlan");
    requireSha256(input.cleanupPlanSha256, "cleanupPlanSha256");
    requireIdempotency(input.idempotencyKey);
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "POST", path: "/v1/internal/memory-comparison/runs", ...requestControls(input),
      idempotencyKey: input.idempotencyKey, json: {
        schema_version: input.schemaVersion, run_id_sha256: input.runIdSha256,
        binding_commitment_sha256: input.bindingCommitmentSha256,
        infinity_target_identity_sha256: input.infinityTargetIdentitySha256,
        space_slug: input.spaceSlug, cleanup_plan: input.cleanupPlan,
        cleanup_plan_sha256: input.cleanupPlanSha256,
      },
    });
  }

  async prepareCleanupTargetAuthority(input: CleanupTargetAuthorityInput): Promise<ApiEnvelope<JsonObject>> {
    exact(input, ["schemaVersion", "infinityTargetIdentitySha256"], "cleanupTargetAuthority");
    requireSchema(input.schemaVersion, "memory-comparison-cleanup-target-authority-request.v1");
    requireSha256(input.infinityTargetIdentitySha256, "infinityTargetIdentitySha256");
    return this.http.request<ApiEnvelope<JsonObject>>({
      method: "POST", path: "/v1/internal/memory-comparison/runs/cleanup-target-authority",
      ...requestControls(input), json: {
        schema_version: input.schemaVersion,
        infinity_target_identity_sha256: input.infinityTargetIdentitySha256,
      },
    });
  }

  async sealProjectionManifest(runIdSha256: string, input: SealProjectionManifestInput): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    requireRunId(runIdSha256);
    exact(input, ["schemaVersion", "projectionManifestSha256", "projectionManifest"], "sealProjectionManifest");
    requireSchema(input.schemaVersion, "memory-comparison-projection-manifest-seal.v1");
    requireSha256(input.projectionManifestSha256, "projectionManifestSha256");
    requireJsonObject(input.projectionManifest, "projectionManifest");
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "PUT", path: `/v1/internal/memory-comparison/runs/${runIdSha256}/projection-manifest`,
      ...requestControls(input), json: {
        schema_version: input.schemaVersion,
        projection_manifest_sha256: input.projectionManifestSha256,
        projection_manifest: input.projectionManifest,
      },
    });
  }

  async getCleanup(runIdSha256: string, input: RequestControls = {}): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    requireRunId(runIdSha256);
    requireAllowedKeys(input, CONTROLS, "getMemoryComparisonCleanup");
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "GET",
      path: `/v1/internal/memory-comparison/runs/${runIdSha256}/cleanup`,
      ...requestControls(input),
    });
  }

  async cleanup(runIdSha256: string, input: CleanupMemoryComparisonRunInput): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    requireRunId(runIdSha256);
    exact(input, ["schemaVersion", "bindingCommitmentSha256", "infinityTargetIdentitySha256", "spaceId", "spaceSlug", "cleanupPlanSha256", "idempotencyKey"], "cleanupMemoryComparisonRun");
    requireSchema(input.schemaVersion, "memory-comparison-run-cleanup.v2");
    validateRunBinding(input);
    requireIdempotency(input.idempotencyKey);
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "DELETE", path: `/v1/internal/memory-comparison/runs/${runIdSha256}`,
      ...requestControls(input), idempotencyKey: input.idempotencyKey, json: {
        schema_version: input.schemaVersion, binding_commitment_sha256: input.bindingCommitmentSha256,
        infinity_target_identity_sha256: input.infinityTargetIdentitySha256, space_id: input.spaceId,
        space_slug: input.spaceSlug, cleanup_plan_sha256: input.cleanupPlanSha256,
      },
    });
  }

  async finalizeCleanup(runIdSha256: string, input: FinalizeMemoryComparisonCleanupInput): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    requireRunId(runIdSha256);
    exact(input, ["schemaVersion", "receiptSha256", "cleanupPlanSha256", "idempotencyKey"], "finalizeMemoryComparisonCleanup");
    requireSchema(input.schemaVersion, "memory-comparison-run-cleanup-finalize.v2");
    requireSha256(input.receiptSha256, "receiptSha256");
    requireSha256(input.cleanupPlanSha256, "cleanupPlanSha256");
    requireIdempotency(input.idempotencyKey);
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "POST", path: `/v1/internal/memory-comparison/runs/${runIdSha256}/cleanup/finalize`,
      ...requestControls(input), idempotencyKey: input.idempotencyKey, json: {
        schema_version: input.schemaVersion, receipt_sha256: input.receiptSha256,
        cleanup_plan_sha256: input.cleanupPlanSha256,
      },
    });
  }

  async finalizeAbort(runIdSha256: string, input: FinalizeMemoryComparisonAbortInput): Promise<ApiEnvelope<MemoryComparisonRunData>> {
    requireRunId(runIdSha256);
    exact(input, ["schemaVersion", "bindingCommitmentSha256", "infinityTargetIdentitySha256", "spaceId", "spaceSlug", "receiptSha256", "cleanupPlanSha256", "idempotencyKey"], "finalizeMemoryComparisonAbort");
    requireSchema(input.schemaVersion, "memory-comparison-run-abort-finalize.v2");
    validateRunBinding(input);
    requireSha256(input.receiptSha256, "receiptSha256");
    requireIdempotency(input.idempotencyKey);
    return this.http.request<ApiEnvelope<MemoryComparisonRunData>>({
      method: "POST", path: `/v1/internal/memory-comparison/runs/${runIdSha256}/cleanup/abort/finalize`,
      ...requestControls(input), idempotencyKey: input.idempotencyKey, json: {
        schema_version: input.schemaVersion, binding_commitment_sha256: input.bindingCommitmentSha256,
        infinity_target_identity_sha256: input.infinityTargetIdentitySha256, space_id: input.spaceId,
        space_slug: input.spaceSlug, receipt_sha256: input.receiptSha256,
        cleanup_plan_sha256: input.cleanupPlanSha256,
      },
    });
  }
}

const CONTROLS = ["headers", "signal", "timeoutMs"] as const;
function exact(input: object, fields: readonly string[], label: string): void { requireAllowedKeys(input, [...fields, ...CONTROLS], label); }
function requireSchema(actual: string, expected: string): void {
  if (actual !== expected) throw new ValueError(`schemaVersion must be ${expected}`);
}
function requireRunId(value: string): void { requireSha256(value, "runIdSha256"); }
function requireIdempotency(value: string): void { requireString(value, "idempotencyKey", 8, 240); }
function requireSpaceSlug(value: string): void {
  requireString(value, "spaceSlug", 19, 98);
  if (!/^memory-comparison-[a-z0-9-]{1,80}$/u.test(value)) {
    throw new ValueError("spaceSlug must use the canonical memory-comparison prefix");
  }
}
function validateRunBinding(input: { readonly bindingCommitmentSha256: string; readonly infinityTargetIdentitySha256: string; readonly spaceId: string; readonly spaceSlug: string; readonly cleanupPlanSha256: string }): void {
  requireSha256(input.bindingCommitmentSha256, "bindingCommitmentSha256");
  requireSha256(input.infinityTargetIdentitySha256, "infinityTargetIdentitySha256");
  requireString(input.spaceId, "spaceId", 1, 80);
  requireSpaceSlug(input.spaceSlug);
  requireSha256(input.cleanupPlanSha256, "cleanupPlanSha256");
}
