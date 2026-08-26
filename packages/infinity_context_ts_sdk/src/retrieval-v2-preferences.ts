import { InfinityContextError } from "./errors.js";
import type { RetrievalV2Candidate } from "./retrieval-v2-types.js";

export interface RequestedPreferenceEvidence {
  readonly sourceWeights: ReadonlyMap<string, number>;
  readonly sourceRequested: number;
  readonly actorRequested: number;
  readonly timeRequested: number;
}

export function requestedPreferenceEvidence(value: unknown): RequestedPreferenceEvidence {
  const input = object(value, "request.soft_preferences");
  const sourceWeights = new Map<string, number>();
  let sourceRequested = 0;
  for (const [index, value] of array(input.source_preferences, "request.soft_preferences.source_preferences").entries()) {
    const item = object(value, `request.soft_preferences.source_preferences.${index}`);
    const key = string(item.key, `request.soft_preferences.source_preferences.${index}.key`);
    const itemWeight = weight(item.weight_micros, `request.soft_preferences.source_preferences.${index}.weight_micros`);
    sourceWeights.set(key, itemWeight);
    sourceRequested += itemWeight;
  }
  let actorRequested = 0;
  for (const [index, value] of array(input.actor_preferences, "request.soft_preferences.actor_preferences").entries()) {
    const item = object(value, `request.soft_preferences.actor_preferences.${index}`);
    string(item.key, `request.soft_preferences.actor_preferences.${index}.key`);
    actorRequested += weight(item.weight_micros, `request.soft_preferences.actor_preferences.${index}.weight_micros`);
  }
  const timeRequested = input.time_weight_micros === null
    ? 0
    : weight(input.time_weight_micros, "request.soft_preferences.time_weight_micros");
  return { sourceWeights, sourceRequested, actorRequested, timeRequested };
}

export function validatePreferenceEvidence(
  candidate: RetrievalV2Candidate,
  requested: RequestedPreferenceEvidence,
): void {
  if (candidate.source_requested_weight_micros !== requested.sourceRequested ||
    candidate.actor_requested_weight_micros !== requested.actorRequested ||
    candidate.time_requested_weight_micros !== requested.timeRequested) fail("response requested preference evidence differs from the request");
  if (candidate.source_matched_weight_micros !== (requested.sourceWeights.get(candidate.source_key) ?? 0)) {
    fail("response matched source preference evidence does not reconstruct");
  }
  if (candidate.actor_matched_weight_micros > requested.actorRequested ||
    ![0, requested.timeRequested].includes(candidate.time_matched_weight_micros)) {
    fail("response matched actor/time preference evidence exceeds the request");
  }
}

function object(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${path} must be an object`);
  return value as Record<string, unknown>;
}

function array(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) fail(`${path} must be an array`);
  return value;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") fail(`${path} must be a string`);
  return value;
}

function weight(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 100_000 || value > 10_000_000) {
    fail(`${path} must be an integer within 100000..10000000`);
  }
  return value;
}

function fail(message: string): never {
  throw new InfinityContextError({
    statusCode: 0, code: "memory.context_retrieval_contract_invalid", message, retryable: false,
  });
}
