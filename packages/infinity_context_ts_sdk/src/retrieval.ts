import { copyInfinityContextError, type InfinityContextError } from "./errors.js";
import { assertExactDocumentReconciliationCapabilityV1 } from "./document-reconciliation.js";
import { retrievalContributionScorePicos, retrievalPreferenceScores } from "./retrieval-numeric.js";
import { requestedPreferenceEvidence, validatePreferenceEvidence } from "./retrieval-preferences.js";
import { decodeRetrievalJson } from "./retrieval-json.js";
import {
  compareUtf8, normalizePythonWhitespace, unicodeScalarLength as codePointLength,
} from "./retrieval-canonical.js";
import {
  array, boundedInteger, capabilityFail, enumArray, exactObject, fail, finite, freeze, integer,
  literal, lowerHex, noOverlap, nonNegativeSafeInteger, nullableOpaque, oneOf, opaque, opaqueArray,
  positiveFinite, sortedUnique, string, timestamp, timestampValue, unique, weight, weightMicros,
} from "./retrieval-validation.js";
import type { JsonObject, JsonValue } from "./types.js";
import {
  CONTEXT_RETRIEVAL_CONTRACT,
  CONTEXT_RETRIEVAL_RANKING_POLICY,
  type RetrievalCapability,
  type RequiredRetrievalCapability,
  type RetrievalAppliedBounds,
  type RetrievalBoundsInput,
  type RetrievalCandidate,
  type RetrievalCapabilityBounds,
  type RetrievalCapabilityProviderLane,
  type RetrievalContribution,
  type RetrievalDegradationReasonCode,
  type RetrievalHardFiltersInput,
  type RetrievalHardFilterSignal,
  type RetrievalNeighbor,
  type RetrievalProviderOutcome,
  type RetrievalProviderReasonCode,
  type RetrievalProviderStatus,
  type RetrievalQueryInput,
  type RetrievalRankingParameters,
  type RetrievalRawScoreKind,
  type RetrievalScopeInput,
  type RetrievalSoftPreferencesInput,
  type RetrievalSoftPreferenceSignal,
  type RetrievalTimeIntervalInput,
  type RetrievalRelativeTimeIntervalInput,
  type RetrievalSourceGenerationInput,
  type RetrievalWeightedKeyInput,
  type RetrieveContextInput,
  type RetrieveContextResponse,
} from "./retrieval-types.js";

const RESPONSE_KEYS = [
  "contract_version", "ranking_policy", "status", "capability_fingerprint", "profile_id",
  "coverage", "applied_bounds", "candidates", "provider_outcomes", "degradation_reason_codes",
] as const;
const LOCATOR_KEYS = [
  "locator", "source_key", "document_key", "chunk_key", "canonical_identity",
  "canonical_version", "lifecycle_status", "relation", "distance",
] as const;
const CANDIDATE_KEYS = [
  ...LOCATOR_KEYS, "provider_rank", "fused_score", "base_score_picos",
  "source_requested_weight_micros", "source_matched_weight_micros",
  "actor_requested_weight_micros", "actor_matched_weight_micros",
  "time_requested_weight_micros", "time_matched_weight_micros",
  "preference_score_micros", "preference_boost_micros", "rerank_score_picos",
  "matched_query_ids", "contributions", "neighbors",
] as const;
const CONTRIBUTION_KEYS = [
  "provider_id", "query_id", "provider_rank", "provider_weight_micros", "query_weight_micros",
  "contribution_score_picos", "provider_weight", "query_weight", "contribution",
  "raw_score_kind", "raw_score_value",
] as const;
const APPLIED_BOUND_KEYS = [
  "candidate_limit", "result_limit", "neighbor_radius", "response_byte_limit", "deadline_ms",
  "returned_seeds", "returned_neighbors",
] as const;
const CAPABILITY_BOUND_KEYS = [
  "query_variants", "query_characters", "provider_lanes", "provider_rank", "candidate_limit",
  "source_generations", "result_limit", "neighbor_radius", "response_byte_limit", "deadline_ms", "weight_micros",
] as const;
const HARD_SIGNALS = [
  "actor_keys", "category", "document_keys", "excluded_source_keys", "kinds", "relative_time_interval",
  "source_generations", "tags_all", "tags_any", "tags_none", "time_interval",
] as const satisfies readonly RetrievalHardFilterSignal[];
const SOFT_SIGNALS = ["actor_preferences", "relative_time_interval", "source_preferences", "time_interval"] as const satisfies readonly RetrievalSoftPreferenceSignal[];
const DEGRADATION_CODES = [
  "capability_profile_mismatch", "neighbor_capability_unavailable", "optional_provider_failed",
  "optional_provider_unavailable", "optional_provider_unqualified", "response_byte_limit_exceeded",
] as const satisfies readonly RetrievalDegradationReasonCode[];
const RAW_SCORE_KINDS = ["similarity", "distance", "relevance", "bm25"] as const satisfies readonly RetrievalRawScoreKind[];
const CAPABILITY_INTEGER_PATHS = ["bounds.*.*", "provider_lanes.*.weight_micros", "ranking_parameters.*"] as const;
const CAPABILITIES_RESPONSE_INTEGER_PATHS = [
  "context.retrieval.bounds.*.*", "context.retrieval.provider_lanes.*.weight_micros",
  "context.retrieval.ranking_parameters.*",
] as const;
const RESPONSE_INTEGER_PATHS = [
  "applied_bounds.candidate_limit", "applied_bounds.result_limit", "applied_bounds.neighbor_radius",
  "applied_bounds.response_byte_limit", "applied_bounds.deadline_ms", "applied_bounds.returned_seeds",
  "applied_bounds.returned_neighbors", "candidates.*.canonical_version", "candidates.*.distance",
  "candidates.*.provider_rank", "candidates.*.contributions.*.provider_rank",
  "candidates.*.base_score_picos", "candidates.*.source_requested_weight_micros",
  "candidates.*.source_matched_weight_micros", "candidates.*.actor_requested_weight_micros",
  "candidates.*.actor_matched_weight_micros", "candidates.*.time_requested_weight_micros",
  "candidates.*.time_matched_weight_micros", "candidates.*.preference_score_micros",
  "candidates.*.preference_boost_micros", "candidates.*.rerank_score_picos",
  "candidates.*.contributions.*.provider_weight_micros",
  "candidates.*.contributions.*.query_weight_micros",
  "candidates.*.contributions.*.contribution_score_picos",
  "candidates.*.neighbors.*.canonical_version", "candidates.*.neighbors.*.distance",
] as const;
const RANKING_PARAMETERS = Object.freeze({
  rank_constant: 60,
  weight_scale_micros: 1_000_000,
  score_scale_picos: 1_000_000_000_000,
  preference_scale_micros: 1_000_000,
  max_preference_boost_micros: 250_000,
  contribution_rounding: "round_half_even",
  preference_rounding: "floor",
  canonical_signal_match_policy: "canonical_exact_key_interval_overlap.v1",
} as const satisfies RetrievalRankingParameters);

export function retrievalRequestPayload(input: RetrieveContextInput): JsonObject {
  const root = exactObject(input, [
    "contractVersion", "capabilityFingerprint", "profileId", "scope", "queries", "filters",
    "softPreferences", "bounds",
  ], "input");
  literal(root.contractVersion, CONTEXT_RETRIEVAL_CONTRACT, "input.contractVersion");
  const scope = exactObject(root.scope, ["spaceId", "memoryScopeId", "threadId"], "input.scope", true);
  const queries = array(root.queries, "input.queries");
  if (queries.length < 1 || queries.length > 6) fail("input.queries must contain 1..6 variants");
  const queryIds = new Set<string>();
  const queryPayloads = queries.map((value, index) => {
    const query = exactObject(value, ["queryId", "query", "weightMicros"], `input.queries.${index}`, true);
    const queryId = opaque(query.queryId, `input.queries.${index}.queryId`, 64);
    if (queryIds.has(queryId)) fail("input.queries queryId values must be unique");
    queryIds.add(queryId);
    const normalizedQuery = string(query.query, `input.queries.${index}.query`);
    if (normalizedQuery !== normalizePythonWhitespace(normalizedQuery) || codePointLength(normalizedQuery) > 512) {
      fail(`input.queries.${index}.query must be normalized and contain 1..512 characters`);
    }
    return freeze({
      query_id: queryId,
      query: normalizedQuery,
      weight_micros: query.weightMicros === undefined
        ? 1_000_000
        : weightMicros(query.weightMicros, `input.queries.${index}.weightMicros`),
    });
  });
  if (queryPayloads.some((item, index) => index > 0 &&
    compareUtf8(queryPayloads[index - 1]!.query_id, item.query_id) >= 0)) {
    fail("input.queries queryId values must be UTF-8 sorted and unique");
  }
  const payload = {
    contract_version: CONTEXT_RETRIEVAL_CONTRACT,
    capability_fingerprint: lowerHex(root.capabilityFingerprint, 64, "input.capabilityFingerprint"),
    profile_id: opaque(root.profileId, "input.profileId"),
    scope: freeze({
      space_id: opaque(scope.spaceId, "input.scope.spaceId"),
      memory_scope_id: opaque(scope.memoryScopeId, "input.scope.memoryScopeId"),
      thread_id: scope.threadId === undefined || scope.threadId === null
        ? null
        : opaque(scope.threadId, "input.scope.threadId"),
    }),
    queries: freeze(queryPayloads),
    filters: encodeFilters(root.filters),
    soft_preferences: encodeSoftPreferences(root.softPreferences),
    bounds: encodeBounds(root.bounds),
  };
  return freeze(payload) as unknown as JsonObject;
}

export function decodeRetrieveContextResponse(
  payload: unknown,
  request: RetrieveContextInput,
  capability: RetrievalCapability,
  receivedResponseBytes: number,
): RetrieveContextResponse {
  const requestPayload = retrievalRequestPayload(request);
  return decodeRetrieveContextResponseForPayload(payload, requestPayload, capability, receivedResponseBytes);
}

export function decodeRetrieveContextResponseForPayload(
  payload: unknown,
  requestPayload: JsonObject,
  capability: RetrievalCapability,
  receivedResponseBytes: number,
): RetrieveContextResponse {
  const attested = decodeCapability(capability, "retrieval capability");
  const root = exactObject(payload, RESPONSE_KEYS, "response");
  literal(root.contract_version, CONTEXT_RETRIEVAL_CONTRACT, "response.contract_version");
  literal(root.ranking_policy, CONTEXT_RETRIEVAL_RANKING_POLICY, "response.ranking_policy");
  literal(root.coverage, "top_k_only", "response.coverage");
  const fingerprint = lowerHex(root.capability_fingerprint, 64, "response.capability_fingerprint");
  const profileId = opaque(root.profile_id, "response.profile_id");
  if (fingerprint !== requestPayload.capability_fingerprint || profileId !== requestPayload.profile_id) {
    fail("response capability fingerprint/profile does not match the request");
  }
  if (fingerprint !== attested.capability_fingerprint || profileId !== attested.profile_id) {
    fail("response capability fingerprint/profile does not match the attestation");
  }
  const status = oneOf(root.status, ["available", "unavailable", "unqualified"], "response.status");
  const applied = decodeAppliedBounds(root.applied_bounds, requestPayload.bounds);
  const candidates = array(root.candidates, "response.candidates").map(decodeCandidate);
  const outcomes = array(root.provider_outcomes, "response.provider_outcomes").map(decodeProviderOutcome);
  const reasons = enumArray(root.degradation_reason_codes, DEGRADATION_CODES, "response.degradation_reason_codes", 6);

  if (candidates.length !== applied.returned_seeds || candidates.length > applied.result_limit) {
    fail("response candidate count does not match applied bounds");
  }
  if ((status === "available") !== (candidates.length > 0)) {
    fail("response status and candidate availability differ");
  }
  for (let index = 1; index < candidates.length; index += 1) {
    const previous = candidates[index - 1]!;
    const current = candidates[index]!;
    if (previous.rerank_score_picos < current.rerank_score_picos ||
      (previous.rerank_score_picos === current.rerank_score_picos && previous.base_score_picos < current.base_score_picos) ||
      (previous.rerank_score_picos === current.rerank_score_picos && previous.base_score_picos === current.base_score_picos &&
        compareUnicode(previous.canonical_identity, current.canonical_identity) >= 0)) {
      fail("response candidates are not ordered by (-rerank_score_picos, -base_score_picos, canonical_identity)");
    }
  }
  sortedUnique(outcomes.map((item) => item.provider_id), "response.provider_outcomes");
  if (outcomes.length > 4) fail("response provider outcomes exceed 4 lanes");
  sortedUnique(reasons, "response.degradation_reason_codes");

  const all = candidates.flatMap((candidate) => [candidate, ...candidate.neighbors]);
  unique(all.map((item) => item.locator), "response locators");
  unique(all.map((item) => item.canonical_identity), "response canonical identities");
  const neighborCount = candidates.reduce((total, candidate) => total + candidate.neighbors.length, 0);
  if (neighborCount !== applied.returned_neighbors) fail("response neighbor count does not match applied bounds");
  const queryWeights = requestQueryWeights(requestPayload.queries);
  const totalQueryWeight = [...queryWeights.values()].reduce((total, value) => total + value, 0);
  const requestedPreferences = requestedPreferenceEvidence(requestPayload.soft_preferences);
  const lanes = new Map(attested.provider_lanes.map((lane) => [lane.provider_id, lane]));
  const outcomeByProvider = new Map(outcomes.map((outcome) => [outcome.provider_id, outcome]));
  const preProviderReason = reasons.length === 1 &&
    (reasons[0] === "capability_profile_mismatch" || reasons[0] === "neighbor_capability_unavailable");
  if (preProviderReason && (status !== "unavailable" || candidates.length > 0 || outcomes.length > 0)) {
    fail("response pre-provider degradation must be an empty unavailable response");
  }
  if (reasons[0] === "neighbor_capability_unavailable" &&
    (attested.supports_neighbors || applied.neighbor_radius === 0)) {
    fail("response neighbor-capability degradation is inconsistent with the attestation and request");
  }
  if (!preProviderReason &&
    !sameStrings(outcomes.map((outcome) => outcome.provider_id), attested.provider_lanes.map((lane) => lane.provider_id))) {
    fail("response provider outcomes must exactly cover the attested provider lanes");
  }
  const failedRequired = attested.required_provider_lanes.filter((providerId) => {
    const outcome = outcomeByProvider.get(providerId);
    return outcome?.status !== "available" || outcome.reason_code !== null;
  });
  if (failedRequired.length > 0 && candidates.length > 0) {
    fail("response cannot accept partial candidates when a required provider lane is unavailable");
  }
  if (failedRequired.length > 0 && status !== "unavailable") {
    fail("response with a failed required provider lane must be unavailable");
  }
  const expectedProviderReasons = preProviderReason
    ? []
    : providerDegradationReasons(attested.provider_lanes, outcomeByProvider);
  const nonProviderReasons = reasons.filter((reason) => !reason.startsWith("optional_provider_"));
  if (!sameStrings(reasons.filter((reason) => reason.startsWith("optional_provider_")), expectedProviderReasons)) {
    fail("response optional-provider degradation reasons differ from provider outcomes");
  }
  if (!preProviderReason && nonProviderReasons.some((reason) => reason !== "response_byte_limit_exceeded")) {
    fail("response degradation reason is inconsistent with the attested request and capability");
  }
  if (reasons.includes("response_byte_limit_exceeded") &&
    (status !== "unavailable" || candidates.length > 0 || failedRequired.length > 0)) {
    fail("response-byte degradation requires an empty unavailable response");
  }
  const qualifiedOutcomes = outcomes.filter((outcome) =>
    outcome.status === "available" && outcome.reason_code === null);
  const hasUnqualifiedOutcome = outcomes.some((outcome) => outcome.status === "unqualified");
  if (failedRequired.length === 0 && !reasons.includes("response_byte_limit_exceeded") && candidates.length === 0) {
    if (status === "unavailable" && (qualifiedOutcomes.length > 0 || hasUnqualifiedOutcome)) {
      fail("response unavailable status is inconsistent with provider outcomes");
    }
    if (status === "unqualified" && !hasUnqualifiedOutcome && qualifiedOutcomes.length === 0) {
      fail("response unqualified status is inconsistent with provider outcomes");
    }
  }
  for (const candidate of candidates) {
    validateNeighbors(candidate, applied.neighbor_radius);
    validatePreferenceEvidence(candidate, requestedPreferences);
    for (const contribution of candidate.contributions) {
      const queryWeight = queryWeights.get(contribution.query_id);
      const lane = lanes.get(contribution.provider_id);
      const outcome = outcomeByProvider.get(contribution.provider_id);
      if (queryWeight === undefined || lane === undefined || !lane.healthy || !lane.profile_qualified ||
        outcome?.status !== "available" || outcome.reason_code !== null) {
        fail("response contribution provenance is not qualified by the request, capability, and provider outcomes");
      }
      if (contribution.query_weight_micros !== queryWeight || contribution.provider_weight_micros !== lane.weight_micros) {
        fail("response contribution weights differ from request/capability evidence");
      }
      const reconstructed = retrievalContributionScorePicos(
        lane.weight_micros, queryWeight, totalQueryWeight, contribution.provider_rank,
      );
      if (contribution.contribution_score_picos !== reconstructed) {
        fail("response contribution does not reconstruct under weighted_rrf_canonical_preferences.v1");
      }
    }
  }
  const byteLength = boundedInteger(receivedResponseBytes, 0, Number.MAX_SAFE_INTEGER, "received response byte length");
  if (byteLength > applied.response_byte_limit) fail("response exceeds the requested response-byte limit");

  return freeze({
    contract_version: CONTEXT_RETRIEVAL_CONTRACT,
    ranking_policy: CONTEXT_RETRIEVAL_RANKING_POLICY,
    status,
    capability_fingerprint: fingerprint,
    profile_id: profileId,
    coverage: "top_k_only",
    applied_bounds: applied,
    candidates: freeze(candidates),
    provider_outcomes: freeze(outcomes),
    degradation_reason_codes: freeze(reasons),
  });
}

export function decodeRetrieveContextResponseBytes(
  body: Uint8Array | string,
  requestPayload: JsonObject,
  capability: RetrievalCapability,
): RetrieveContextResponse {
  const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
  const requestBounds = exactObject(requestPayload.bounds, [
    "candidate_limit", "result_limit", "neighbor_radius", "response_byte_limit", "deadline_ms",
  ], "request.bounds");
  const maximum = boundedInteger(requestBounds.response_byte_limit, 16384, 1048576, "request.bounds.response_byte_limit");
  if (bytes.byteLength > maximum) fail("response exceeds the requested response-byte limit");
  const payload = decodeRetrievalJson(bytes, RESPONSE_INTEGER_PATHS);
  return decodeRetrieveContextResponseForPayload(payload, requestPayload, capability, bytes.byteLength);
}

/** Synchronous structural/pin validation only; no cryptographic verification. */ export function assertRetrievalCapability(
  capabilities: unknown,
  required: RequiredRetrievalCapability,
): RetrievalCapability {
  try {
    const root = exactObject(capabilities, undefined, "capabilities");
    const context = exactObject(root.context, undefined, "capabilities.context");
    const actual = decodeCapability(context.retrieval, "capabilities.context.retrieval");
    const expected = exactObject(required, [
      "capabilityFingerprint", "profileId", "requiredProviderLanes",
    ], "required retrieval capability");
    const fingerprint = lowerHex(expected.capabilityFingerprint, 64, "required retrieval capability.capabilityFingerprint");
    const profileId = opaque(expected.profileId, "required retrieval capability.profileId");
    const lanes = opaqueArray(expected.requiredProviderLanes, "required retrieval capability.requiredProviderLanes");
    sortedUnique(lanes, "required retrieval capability.requiredProviderLanes");
    if (actual.capability_fingerprint !== fingerprint || actual.profile_id !== profileId ||
      !sameStrings(actual.required_provider_lanes, lanes)) {
      capabilityFail("context.retrieval attestation differs from the pinned fingerprint/profile/required lanes");
    }
    return actual;
  } catch (error) {
    const safe = copyInfinityContextError(error);
    if (safe?.code === "memory.context_retrieval_capability_mismatch") {
      throw safe;
    }
    capabilityFail("context.retrieval attestation is malformed");
  }
}

/** Synchronous structural decoding only; no cryptographic verification. */ export function decodeRetrievalCapability(value: unknown): RetrievalCapability {
  try {
    return decodeCapability(value, "retrieval capability");
  } catch (error) {
    const safe = copyInfinityContextError(error);
    if (safe?.code === "memory.context_retrieval_capability_mismatch") throw safe;
    capabilityFail("retrieval capability is malformed");
  }
}

export function decodeRetrievalCapabilityBytes(body: Uint8Array | string): RetrievalCapability {
  return decodeRetrievalCapability(decodeRetrievalJson(body, CAPABILITY_INTEGER_PATHS));
}

export function decodeContextRetrievalCapabilitiesResponseBytes(body: Uint8Array | string): JsonObject {
  const value = decodeRetrievalJson(body, CAPABILITIES_RESPONSE_INTEGER_PATHS);
  const root = exactObject(value, undefined, "capabilities");
  if (root.context !== undefined) {
    const context = exactObject(root.context, undefined, "capabilities.context");
    if (context.retrieval !== undefined) decodeCapability(context.retrieval, "capabilities.context.retrieval");
  }
  if (root.documents !== undefined) {
    const documents = exactObject(root.documents, undefined, "capabilities.documents");
    if (documents.exact_reconciliation !== undefined) {
      assertExactDocumentReconciliationCapabilityV1(documents.exact_reconciliation);
    }
  }
  return root as unknown as JsonObject;
}

export function validateRetrievalPreflight(
  request: RetrieveContextInput,
  capability: RetrievalCapability,
  required: RequiredRetrievalCapability,
): void {
  try {
    validateContextRetrievalPreflight(request, capability, required);
  } catch (error) {
    const safe = copyInfinityContextError(error);
    if (safe?.code === "memory.context_retrieval_capability_mismatch") throw safe;
    capabilityFail("retrieval preflight evidence is malformed");
  }
}

function validateContextRetrievalPreflight(
  requestValue: RetrieveContextInput,
  capability: RetrievalCapability,
  required: RequiredRetrievalCapability,
): void {
  const request = exactObject(requestValue, undefined, "retrieval request");
  const attested = decodeCapability(capability, "retrieval capability");
  const pins = exactObject(required, [
    "capabilityFingerprint", "profileId", "requiredProviderLanes",
  ], "required retrieval capability");
  const pinnedFingerprint = lowerHex(pins.capabilityFingerprint, 64, "required retrieval capability.capabilityFingerprint");
  const pinnedProfile = opaque(pins.profileId, "required retrieval capability.profileId");
  const pinnedLanes = opaqueArray(pins.requiredProviderLanes, "required retrieval capability.requiredProviderLanes");
  sortedUnique(pinnedLanes, "required retrieval capability.requiredProviderLanes");
  if (request.contractVersion !== attested.contract_version ||
    attested.ranking_policy !== CONTEXT_RETRIEVAL_RANKING_POLICY ||
    request.capabilityFingerprint !== attested.capability_fingerprint ||
    request.profileId !== attested.profile_id ||
    request.capabilityFingerprint !== pinnedFingerprint || request.profileId !== pinnedProfile ||
    !sameStrings(attested.required_provider_lanes, pinnedLanes)) {
    capabilityFail("retrieval request, capability attestation, and client pins do not match");
  }
}

function encodeFilters(value: unknown): JsonValue {
  const input = exactObject(value, [
    "sourceGenerations", "excludedSourceKeys", "documentKeys", "kinds", "category",
    "tagsAny", "tagsAll", "tagsNone", "actorKeys", "timeInterval", "relativeTimeInterval",
  ], "input.filters");
  const sourceGenerations = encodeSourceGenerations(input.sourceGenerations);
  const sourceKeys = sourceGenerations.map((pair) => pair.source_key);
  const excluded = opaqueArray(input.excludedSourceKeys, "input.filters.excludedSourceKeys");
  noOverlap(sourceKeys, excluded, "input.filters source inclusion and exclusion");
  const tagsAll = opaqueArray(input.tagsAll, "input.filters.tagsAll");
  const tagsNone = opaqueArray(input.tagsNone, "input.filters.tagsNone");
  noOverlap(tagsAll, tagsNone, "input.filters required and excluded tags");
  const timeInterval = encodeInterval(input.timeInterval, "input.filters.timeInterval");
  const relativeTimeInterval = encodeRelativeInterval(input.relativeTimeInterval, "input.filters.relativeTimeInterval");
  if (timeInterval !== null && relativeTimeInterval !== null) fail("input.filters may select at most one time coordinate");
  return freeze({
    source_generations: sourceGenerations,
    excluded_source_keys: excluded,
    document_keys: opaqueArray(input.documentKeys, "input.filters.documentKeys"),
    kinds: opaqueArray(input.kinds, "input.filters.kinds"),
    category: nullableOpaque(input.category, "input.filters.category"),
    tags_any: opaqueArray(input.tagsAny, "input.filters.tagsAny"),
    tags_all: tagsAll,
    tags_none: tagsNone,
    actor_keys: opaqueArray(input.actorKeys, "input.filters.actorKeys"),
    time_interval: timeInterval,
    relative_time_interval: relativeTimeInterval,
  });
}

function encodeSoftPreferences(value: unknown): JsonValue {
  const input = exactObject(value, ["sourcePreferences", "actorPreferences", "timeInterval", "relativeTimeInterval", "timeWeightMicros"], "input.softPreferences");
  const interval = encodeInterval(input.timeInterval, "input.softPreferences.timeInterval");
  const relativeInterval = encodeRelativeInterval(input.relativeTimeInterval, "input.softPreferences.relativeTimeInterval");
  const timeWeightMicros = input.timeWeightMicros === null
    ? null
    : weightMicros(input.timeWeightMicros, "input.softPreferences.timeWeightMicros");
  const coordinateCount = Number(interval !== null) + Number(relativeInterval !== null);
  if ((coordinateCount === 0) !== (timeWeightMicros === null) || coordinateCount > 1) {
    fail("input.softPreferences requires timeWeightMicros with exactly one time coordinate");
  }
  return freeze({
    source_preferences: encodeWeightedKeys(input.sourcePreferences, "input.softPreferences.sourcePreferences"),
    actor_preferences: encodeWeightedKeys(input.actorPreferences, "input.softPreferences.actorPreferences"),
    time_interval: interval,
    relative_time_interval: relativeInterval,
    time_weight_micros: timeWeightMicros,
  });
}

function encodeWeightedKeys(value: unknown, path: string): readonly JsonValue[] {
  const keys = array(value, path).map((item, index) => {
    const input = exactObject(item, ["key", "weightMicros"], `${path}.${index}`);
    return freeze({
      key: opaque(input.key, `${path}.${index}.key`),
      weight_micros: weightMicros(input.weightMicros, `${path}.${index}.weightMicros`),
    });
  });
  if (keys.length > 100) fail(`${path} exceeds 100 entries`);
  unique(keys.map((item) => (item as { key: string }).key), path);
  sortedUnique(keys.map((item) => (item as { key: string }).key), path);
  return freeze(keys);
}

function encodeSourceGenerations(value: unknown): readonly { readonly source_key: string; readonly projection_generation: string }[] {
  const pairs = array(value, "input.filters.sourceGenerations").map((item, index) => {
    const path = `input.filters.sourceGenerations.${index}`;
    const input = exactObject(item, ["sourceKey", "projectionGeneration"], path);
    return freeze({
      source_key: opaque(input.sourceKey, `${path}.sourceKey`),
      projection_generation: opaque(input.projectionGeneration, `${path}.projectionGeneration`),
    });
  });
  if (pairs.length < 1 || pairs.length > 100) fail("input.filters.sourceGenerations must contain 1..100 entries");
  unique(pairs.map((pair) => pair.source_key), "input.filters.sourceGenerations source keys");
  if (pairs.some((pair, index) => index > 0 &&
    (compareUtf8(pairs[index - 1]!.source_key, pair.source_key) ||
      compareUtf8(pairs[index - 1]!.projection_generation, pair.projection_generation)) >= 0)) {
    fail("input.filters.sourceGenerations must be sorted by UTF-8 pair order");
  }
  return freeze(pairs);
}

function encodeInterval(value: unknown, path: string): JsonValue {
  if (value === null) return null;
  const input = exactObject(value, ["startAt", "endAt"], path);
  const start = timestamp(input.startAt, `${path}.startAt`);
  const end = timestamp(input.endAt, `${path}.endAt`);
  if (timestampValue(start) > timestampValue(end)) fail(`${path}.startAt cannot follow endAt`);
  return freeze({ start_at: start, end_at: end });
}

function encodeRelativeInterval(value: unknown, path: string): JsonValue {
  if (value === null) return null;
  const input = exactObject(value, ["startMs", "endMs"], path);
  const start = boundedInteger(input.startMs, 0, Number.MAX_SAFE_INTEGER, `${path}.startMs`);
  const end = boundedInteger(input.endMs, 0, Number.MAX_SAFE_INTEGER, `${path}.endMs`);
  if (start > end) fail(`${path}.startMs cannot follow endMs`);
  return freeze({ start_ms: start, end_ms: end });
}

function encodeBounds(value: unknown): JsonValue {
  const input = exactObject(value, ["candidateLimit", "resultLimit", "neighborRadius", "responseByteLimit", "deadlineMs"], "input.bounds");
  const candidateLimit = boundedInteger(input.candidateLimit, 1, 1000, "input.bounds.candidateLimit");
  const resultLimit = boundedInteger(input.resultLimit, 1, 50, "input.bounds.resultLimit");
  if (resultLimit > candidateLimit) fail("input.bounds.resultLimit cannot exceed candidateLimit");
  return freeze({
    candidate_limit: candidateLimit,
    result_limit: resultLimit,
    neighbor_radius: boundedInteger(input.neighborRadius, 0, 2, "input.bounds.neighborRadius"),
    response_byte_limit: boundedInteger(input.responseByteLimit, 16384, 1048576, "input.bounds.responseByteLimit"),
    deadline_ms: boundedInteger(input.deadlineMs, 1, 2000, "input.bounds.deadlineMs"),
  });
}

function decodeAppliedBounds(value: unknown, requested: JsonValue | undefined): RetrievalAppliedBounds {
  const input = exactObject(value, APPLIED_BOUND_KEYS, "response.applied_bounds");
  const request = exactObject(requested, ["candidate_limit", "result_limit", "neighbor_radius", "response_byte_limit", "deadline_ms"], "request.bounds");
  for (const key of ["candidate_limit", "result_limit", "neighbor_radius", "response_byte_limit", "deadline_ms"] as const) {
    integer(input[key], `response.applied_bounds.${key}`);
    if (input[key] !== request[key]) fail(`response.applied_bounds.${key} differs from the request`);
  }
  const returnedSeeds = boundedInteger(input.returned_seeds, 0, input.result_limit as number, "response.applied_bounds.returned_seeds");
  const maxNeighbors = returnedSeeds * (input.neighbor_radius as number) * 2;
  const returnedNeighbors = boundedInteger(input.returned_neighbors, 0, maxNeighbors, "response.applied_bounds.returned_neighbors");
  return freeze({
    candidate_limit: input.candidate_limit as number,
    result_limit: input.result_limit as number,
    neighbor_radius: input.neighbor_radius as number,
    response_byte_limit: input.response_byte_limit as number,
    deadline_ms: input.deadline_ms as number,
    returned_seeds: returnedSeeds,
    returned_neighbors: returnedNeighbors,
  });
}

function decodeCandidate(value: unknown, index: number): RetrievalCandidate {
  const path = `response.candidates.${index}`;
  const input = exactObject(value, CANDIDATE_KEYS, path);
  literal(input.lifecycle_status, "active", `${path}.lifecycle_status`);
  literal(input.relation, "direct", `${path}.relation`);
  literal(input.distance, 0, `${path}.distance`);
  const contributions = array(input.contributions, `${path}.contributions`).map((item, contributionIndex) =>
    decodeContribution(item, `${path}.contributions.${contributionIndex}`));
  if (contributions.length === 0) fail(`${path}.contributions requires provenance`);
  const matched = opaqueArray(input.matched_query_ids, `${path}.matched_query_ids`, 64);
  if (matched.length === 0) fail(`${path}.matched_query_ids requires provenance`);
  sortedUnique(matched, `${path}.matched_query_ids`);
  unique(contributions.map((item) => JSON.stringify([item.provider_id, item.query_id])), `${path}.contributions provider/query keys`);
  if (contributions.some((item, index) => index > 0 && compareContributions(contributions[index - 1]!, item) >= 0)) {
    fail(`${path}.contributions must be sorted by (provider_id, query_id)`);
  }
  const contributedQueries = [...new Set(contributions.map((item) => item.query_id))].sort(compareUnicode);
  if (JSON.stringify(matched) !== JSON.stringify(contributedQueries)) fail(`${path}.matched_query_ids differ from contributions`);
  const providerRank = boundedInteger(input.provider_rank, 1, 1000, `${path}.provider_rank`);
  if (providerRank !== Math.min(...contributions.map((item) => item.provider_rank))) fail(`${path}.provider_rank differs from contribution minimum`);
  const fusedScore = positiveFinite(input.fused_score, `${path}.fused_score`);
  const baseScorePicos = boundedInteger(input.base_score_picos, 1, Number.MAX_SAFE_INTEGER, `${path}.base_score_picos`);
  const contributionTotal = contributions.reduce(
    (total, item) => total + BigInt(item.contribution_score_picos), 0n,
  );
  if (contributionTotal > BigInt(Number.MAX_SAFE_INTEGER) || baseScorePicos !== Number(contributionTotal)) {
    fail(`${path}.base_score_picos does not reconstruct from contributions`);
  }
  if (fusedScore !== baseScorePicos / 1_000_000_000_000) {
    fail(`${path}.fused_score does not mirror base_score_picos`);
  }
  const sourceRequested = nonNegativeSafeInteger(input.source_requested_weight_micros, `${path}.source_requested_weight_micros`);
  const sourceMatched = nonNegativeSafeInteger(input.source_matched_weight_micros, `${path}.source_matched_weight_micros`);
  const actorRequested = nonNegativeSafeInteger(input.actor_requested_weight_micros, `${path}.actor_requested_weight_micros`);
  const actorMatched = nonNegativeSafeInteger(input.actor_matched_weight_micros, `${path}.actor_matched_weight_micros`);
  const timeRequested = nonNegativeSafeInteger(input.time_requested_weight_micros, `${path}.time_requested_weight_micros`);
  const timeMatched = nonNegativeSafeInteger(input.time_matched_weight_micros, `${path}.time_matched_weight_micros`);
  if (sourceMatched > sourceRequested || actorMatched > actorRequested || timeMatched > timeRequested) {
    fail(`${path} preference dimension evidence is out of bounds`);
  }
  let scores: ReturnType<typeof retrievalPreferenceScores>;
  try {
    scores = retrievalPreferenceScores(
      baseScorePicos,
      sourceRequested + actorRequested + timeRequested,
      sourceMatched + actorMatched + timeMatched,
    );
  } catch {
    fail(`${path} preference evidence is out of bounds`);
  }
  const preferenceScore = boundedInteger(input.preference_score_micros, 0, 1_000_000, `${path}.preference_score_micros`);
  const preferenceBoost = boundedInteger(input.preference_boost_micros, 0, 250_000, `${path}.preference_boost_micros`);
  const rerankScore = boundedInteger(input.rerank_score_picos, 1, Number.MAX_SAFE_INTEGER, `${path}.rerank_score_picos`);
  if (preferenceScore !== scores.preferenceScoreMicros || preferenceBoost !== scores.preferenceBoostMicros ||
    rerankScore !== scores.rerankScorePicos) {
    fail(`${path} preference and rerank scores do not reconstruct from integer evidence`);
  }
  const sourceKey = opaque(input.source_key, `${path}.source_key`);
  const documentKey = opaque(input.document_key, `${path}.document_key`);
  const neighbors = array(input.neighbors, `${path}.neighbors`).map((item, neighborIndex) =>
    decodeNeighbor(item, `${path}.neighbors.${neighborIndex}`, sourceKey));
  return freeze({
    locator: opaque(input.locator, `${path}.locator`), source_key: sourceKey,
    document_key: documentKey, chunk_key: opaque(input.chunk_key, `${path}.chunk_key`),
    canonical_identity: opaque(input.canonical_identity, `${path}.canonical_identity`),
    canonical_version: boundedInteger(input.canonical_version, 1, Number.MAX_SAFE_INTEGER, `${path}.canonical_version`),
    lifecycle_status: "active", relation: "direct", distance: 0, provider_rank: providerRank,
    fused_score: fusedScore, base_score_picos: baseScorePicos,
    source_requested_weight_micros: sourceRequested, source_matched_weight_micros: sourceMatched,
    actor_requested_weight_micros: actorRequested, actor_matched_weight_micros: actorMatched,
    time_requested_weight_micros: timeRequested, time_matched_weight_micros: timeMatched,
    preference_score_micros: preferenceScore, preference_boost_micros: preferenceBoost,
    rerank_score_picos: rerankScore,
    matched_query_ids: matched, contributions: freeze(contributions), neighbors: freeze(neighbors),
  });
}

function decodeContribution(value: unknown, path: string): RetrievalContribution {
  const input = exactObject(value, CONTRIBUTION_KEYS, path);
  const rawKind = input.raw_score_kind === null ? null : oneOf(input.raw_score_kind, RAW_SCORE_KINDS, `${path}.raw_score_kind`);
  const rawValue = input.raw_score_value === null ? null : finite(input.raw_score_value, `${path}.raw_score_value`);
  if ((rawKind === null) !== (rawValue === null)) fail(`${path} raw score kind and value are both required`);
  const providerWeightMicros = weightMicros(input.provider_weight_micros, `${path}.provider_weight_micros`);
  const queryWeightMicros = weightMicros(input.query_weight_micros, `${path}.query_weight_micros`);
  const contributionScorePicos = boundedInteger(input.contribution_score_picos, 1, Number.MAX_SAFE_INTEGER, `${path}.contribution_score_picos`);
  const providerWeight = weight(input.provider_weight, `${path}.provider_weight`);
  const queryWeight = weight(input.query_weight, `${path}.query_weight`);
  const contribution = positiveFinite(input.contribution, `${path}.contribution`);
  if (providerWeight !== providerWeightMicros / 1_000_000 || queryWeight !== queryWeightMicros / 1_000_000 ||
    contribution !== contributionScorePicos / 1_000_000_000_000) {
    fail(`${path} informational float mirrors differ from authoritative integers`);
  }
  return freeze({
    provider_id: opaque(input.provider_id, `${path}.provider_id`), query_id: opaque(input.query_id, `${path}.query_id`, 64),
    provider_rank: boundedInteger(input.provider_rank, 1, 1000, `${path}.provider_rank`),
    provider_weight_micros: providerWeightMicros, query_weight_micros: queryWeightMicros,
    contribution_score_picos: contributionScorePicos,
    provider_weight: providerWeight, query_weight: queryWeight, contribution,
    raw_score_kind: rawKind, raw_score_value: rawValue,
  });
}

function decodeNeighbor(value: unknown, path: string, sourceKey: string): RetrievalNeighbor {
  const input = exactObject(value, LOCATOR_KEYS, path);
  literal(input.lifecycle_status, "active", `${path}.lifecycle_status`);
  literal(input.relation, "neighbor", `${path}.relation`);
  const distance = oneOf(input.distance, [-2, -1, 1, 2] as const, `${path}.distance`);
  const source = opaque(input.source_key, `${path}.source_key`);
  const document = opaque(input.document_key, `${path}.document_key`);
  if (source !== sourceKey) fail(`${path} crosses source`);
  return freeze({
    locator: opaque(input.locator, `${path}.locator`), source_key: source, document_key: document,
    chunk_key: opaque(input.chunk_key, `${path}.chunk_key`), canonical_identity: opaque(input.canonical_identity, `${path}.canonical_identity`),
    canonical_version: boundedInteger(input.canonical_version, 1, Number.MAX_SAFE_INTEGER, `${path}.canonical_version`),
    lifecycle_status: "active", relation: "neighbor", distance,
  });
}

function decodeProviderOutcome(value: unknown, index: number): RetrievalProviderOutcome {
  const path = `response.provider_outcomes.${index}`;
  const input = exactObject(value, ["provider_id", "status", "reason_code"], path);
  const status = oneOf(input.status, ["available", "unavailable", "unqualified"], `${path}.status`);
  const reason = input.reason_code === null ? null : oneOf(input.reason_code,
    ["provider_error", "provider_unavailable", "provider_unqualified", "provider_truncated"] as const,
    `${path}.reason_code`);
  const valid = status === "available" ? reason === null || reason === "provider_truncated"
    : status === "unavailable" ? reason === "provider_error" || reason === "provider_unavailable"
      : reason === "provider_unqualified";
  if (!valid) fail(`${path}.reason_code is invalid for status ${status}`);
  return freeze({ provider_id: opaque(input.provider_id, `${path}.provider_id`), status, reason_code: reason });
}

function providerDegradationReasons(
  lanes: readonly RetrievalCapabilityProviderLane[],
  outcomes: ReadonlyMap<string, RetrievalProviderOutcome>,
): readonly RetrievalDegradationReasonCode[] {
  const reasons = new Set<RetrievalDegradationReasonCode>();
  for (const lane of lanes) {
    const outcome = outcomes.get(lane.provider_id)!;
    if (lane.required || (outcome.status === "available" && outcome.reason_code === null)) continue;
    if (outcome.reason_code === "provider_error") reasons.add("optional_provider_failed");
    else if (outcome.status === "unqualified") reasons.add("optional_provider_unqualified");
    else reasons.add("optional_provider_unavailable");
  }
  return freeze([...reasons].sort(compareUnicode));
}

function decodeCapability(value: unknown, path: string): RetrievalCapability {
  const input = exactObject(value, [
    "endpoint", "contract_version", "ranking_policy", "ranking_parameters", "capability_fingerprint", "profile_id",
    "service_revision", "sdk_revision", "attribute_schema", "index_profile_digest", "coverage",
    "supports_neighbors", "bounds", "hard_filter_signals", "soft_preference_signals",
    "required_provider_lanes", "provider_lanes",
  ], path);
  literal(input.endpoint, "/v1/context/retrieve", `${path}.endpoint`);
  literal(input.contract_version, CONTEXT_RETRIEVAL_CONTRACT, `${path}.contract_version`);
  literal(input.ranking_policy, CONTEXT_RETRIEVAL_RANKING_POLICY, `${path}.ranking_policy`);
  const rankingParameters = decodeRankingParameters(input.ranking_parameters, `${path}.ranking_parameters`);
  literal(input.coverage, "top_k_only", `${path}.coverage`);
  literal(input.attribute_schema, "document-retrieval-projection.v1", `${path}.attribute_schema`);
  if (typeof input.supports_neighbors !== "boolean") capabilityFail(`${path}.supports_neighbors must be boolean`);
  const bounds = decodeCapabilityBounds(input.bounds, `${path}.bounds`);
  const hard = enumArray(input.hard_filter_signals, HARD_SIGNALS, `${path}.hard_filter_signals`, HARD_SIGNALS.length);
  const soft = enumArray(input.soft_preference_signals, SOFT_SIGNALS, `${path}.soft_preference_signals`, SOFT_SIGNALS.length);
  sortedUnique(hard, `${path}.hard_filter_signals`);
  sortedUnique(soft, `${path}.soft_preference_signals`);
  if (!sameStrings(hard, HARD_SIGNALS) || !sameStrings(soft, SOFT_SIGNALS)) {
    capabilityFail(`${path} does not attest every required hard and soft signal`);
  }
  const requiredLanes = opaqueArray(input.required_provider_lanes, `${path}.required_provider_lanes`);
  sortedUnique(requiredLanes, `${path}.required_provider_lanes`);
  const lanes = array(input.provider_lanes, `${path}.provider_lanes`).map((item, index) =>
    decodeCapabilityLane(item, `${path}.provider_lanes.${index}`));
  if (lanes.length < 1 || lanes.length > 4) capabilityFail(`${path}.provider_lanes must contain 1..4 lanes`);
  sortedUnique(lanes.map((lane) => lane.provider_id), `${path}.provider_lanes`);
  const attestedRequired = lanes.filter((lane) => lane.required).map((lane) => lane.provider_id);
  if (!sameStrings(requiredLanes, attestedRequired)) {
    capabilityFail(`${path}.required_provider_lanes differ from required lane descriptors`);
  }
  if (lanes.some((lane) => lane.required && (!lane.healthy || !lane.profile_qualified))) {
    capabilityFail(`${path} has an unhealthy or profile-unqualified required lane`);
  }
  return freeze({
    endpoint: "/v1/context/retrieve",
    contract_version: CONTEXT_RETRIEVAL_CONTRACT, ranking_policy: CONTEXT_RETRIEVAL_RANKING_POLICY,
    ranking_parameters: rankingParameters,
    capability_fingerprint: lowerHex(input.capability_fingerprint, 64, `${path}.capability_fingerprint`),
    profile_id: opaque(input.profile_id, `${path}.profile_id`),
    service_revision: lowerHex(input.service_revision, 40, `${path}.service_revision`),
    sdk_revision: lowerHex(input.sdk_revision, 40, `${path}.sdk_revision`),
    attribute_schema: "document-retrieval-projection.v1",
    index_profile_digest: lowerHex(input.index_profile_digest, 64, `${path}.index_profile_digest`),
    coverage: "top_k_only",
    supports_neighbors: input.supports_neighbors as boolean, bounds, hard_filter_signals: hard,
    soft_preference_signals: soft, required_provider_lanes: requiredLanes, provider_lanes: freeze(lanes),
  });
}

function decodeRankingParameters(value: unknown, path: string): RetrievalRankingParameters {
  const keys = Object.keys(RANKING_PARAMETERS) as (keyof RetrievalRankingParameters)[];
  const input = exactObject(value, keys, path);
  for (const key of keys) {
    if (input[key] !== RANKING_PARAMETERS[key]) capabilityFail(`${path}.${key} does not match Retrieval`);
  }
  return RANKING_PARAMETERS;
}

function decodeCapabilityLane(value: unknown, path: string): RetrievalCapabilityProviderLane {
  const input = exactObject(value, [
    "provider_id", "required", "healthy", "weight_micros", "profile_qualified",
  ], path);
  for (const key of ["required", "healthy", "profile_qualified"] as const) {
    if (typeof input[key] !== "boolean") capabilityFail(`${path}.${key} must be boolean`);
  }
  return freeze({
    provider_id: opaque(input.provider_id, `${path}.provider_id`),
    required: input.required as boolean,
    healthy: input.healthy as boolean,
    weight_micros: boundedInteger(input.weight_micros, 100000, 10000000, `${path}.weight_micros`),
    profile_qualified: input.profile_qualified as boolean,
  });
}

function decodeCapabilityBounds(value: unknown, path: string): RetrievalCapabilityBounds {
  const input = exactObject(value, CAPABILITY_BOUND_KEYS, path);
  const specs = {
    query_variants: [1, 6], query_characters: [1, 512], provider_lanes: [1, 4], provider_rank: [1, 1000],
    source_generations: [1, 100], candidate_limit: [1, 1000], result_limit: [1, 50], neighbor_radius: [0, 2],
    response_byte_limit: [16384, 1048576], deadline_ms: [1, 2000], weight_micros: [100000, 10000000],
  } as const;
  const output: Record<string, readonly [number, number]> = {};
  for (const key of CAPABILITY_BOUND_KEYS) {
    const pair = array(input[key], `${path}.${key}`);
    if (pair.length !== 2 || pair[0] !== specs[key][0] || pair[1] !== specs[key][1]) {
      capabilityFail(`${path}.${key} does not attest the Retrieval mechanical bound`);
    }
    output[key] = freeze([specs[key][0], specs[key][1]]);
  }
  return freeze(output) as unknown as RetrievalCapabilityBounds;
}

function compareContributions(left: RetrievalContribution, right: RetrievalContribution): number {
  return compareUnicode(left.provider_id, right.provider_id) || compareUnicode(left.query_id, right.query_id);
}

function compareUnicode(left: string, right: string): number {
  return compareUtf8(left, right);
}

function requestQueryWeights(value: JsonValue | undefined): ReadonlyMap<string, number> {
  const weights = new Map<string, number>();
  for (const [index, item] of array(value, "request.queries").entries()) {
    const input = exactObject(item, ["query_id", "query", "weight_micros"], `request.queries.${index}`);
    const queryId = opaque(input.query_id, `request.queries.${index}.query_id`, 64);
    weights.set(queryId, weightMicros(input.weight_micros, `request.queries.${index}.weight_micros`));
  }
  return weights;
}

function validateNeighbors(candidate: RetrievalCandidate, radius: number): void {
  const distances = candidate.neighbors.map((neighbor) => neighbor.distance);
  if (distances.length > radius * 2 || distances.some((distance) => Math.abs(distance) > radius)) {
    fail("response neighbors exceed the applied neighbor radius");
  }
  unique(distances.map(String), "response neighbor distances");
  const canonical = [-2, -1, 1, 2].filter((distance) => Math.abs(distance) <= radius);
  const positions = distances.map((distance) => canonical.indexOf(distance));
  if (positions.some((position, index) => index > 0 && positions[index - 1]! >= position)) {
    fail("response neighbors are not in canonical distance order");
  }
  if ((distances.includes(-2) && !distances.includes(-1)) || (distances.includes(2) && !distances.includes(1))) {
    fail("response neighbors cross a canonical sequence gap");
  }
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}
