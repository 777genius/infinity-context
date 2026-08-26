export function assertRetrievalV2RuntimeCanary({
  capability,
  response,
  expectedFingerprint,
  expectedProfile,
  expectedSdkRevision,
  expectedServiceRevision,
  expectedLocator,
}) {
  if (
    capability.capability_fingerprint !== expectedFingerprint ||
    capability.profile_id !== expectedProfile ||
    capability.sdk_revision !== expectedSdkRevision ||
    capability.service_revision !== expectedServiceRevision
  ) {
    throw new Error("Live Retrieval V2 capability differs from immutable canary pins");
  }
  if (response.status === "unavailable") {
    throw new Error("Retrieval V2 canary is unavailable");
  }
  if (response.candidates.length === 0) {
    throw new Error("Retrieval V2 canary returned an empty candidate set");
  }
  if (!response.candidates.some((candidate) => candidate.locator === expectedLocator)) {
    throw new Error("Retrieval V2 canary did not return the seeded expected locator");
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
      throw new Error(`Retrieval V2 required lane ${providerId} is not healthy and complete`);
    }
  }
}
