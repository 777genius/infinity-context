export function assertRetrievalRuntimeCanary({
  capability,
  response,
  expectedFingerprint,
  expectedProfile,
  expectedSdkRevision,
  expectedServiceRevision,
  expectedRequiredProviderLanes,
  expectedProviderLanes,
  expectedLocator,
}) {
  assertRetrievalCapabilityPins({
    capability, expectedFingerprint, expectedProfile, expectedSdkRevision,
    expectedServiceRevision, expectedRequiredProviderLanes, expectedProviderLanes,
  });
  if (response.status === "unavailable") {
    throw new Error("Retrieval canary is unavailable");
  }
  if (response.candidates.length === 0) {
    throw new Error("Retrieval canary returned an empty candidate set");
  }
  if (!response.candidates.some((candidate) => candidate.locator === expectedLocator)) {
    throw new Error("Retrieval canary did not return the seeded expected locator");
  }
  const required = new Set(capability.required_provider_lanes);
  const outcomes = new Map(
    response.provider_outcomes.map((outcome) => [outcome.provider_id, outcome]),
  );
  for (const providerId of required) {
    const lane = capability.provider_lanes.find(
      (candidate) => candidate.provider_id === providerId,
    );
    const outcome = outcomes.get(providerId);
    if (
      !lane?.healthy ||
      !lane.profile_qualified ||
      outcome?.status !== "available" ||
      outcome.reason_code !== null
    ) {
      throw new Error(`Retrieval required lane ${providerId} is not healthy and complete`);
    }
  }
}

export function assertRetrievalCapabilityPins({
  capability,
  expectedFingerprint,
  expectedProfile,
  expectedSdkRevision,
  expectedServiceRevision,
  expectedRequiredProviderLanes,
  expectedProviderLanes,
}) {
  if (
    capability.capability_fingerprint !== expectedFingerprint ||
    capability.profile_id !== expectedProfile ||
    capability.sdk_revision !== expectedSdkRevision ||
    capability.service_revision !== expectedServiceRevision ||
    !sameStrings(capability.required_provider_lanes, expectedRequiredProviderLanes) ||
    !sameStrings(capability.provider_lanes.map((lane) => lane.provider_id), expectedProviderLanes)
  ) {
    throw new Error("Live Retrieval capability differs from immutable canary pins");
  }
}

function sameStrings(actual, expected) {
  return Array.isArray(expected) && actual.length === expected.length &&
    actual.every((value, index) => value === expected[index]);
}
