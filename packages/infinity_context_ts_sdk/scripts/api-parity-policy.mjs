export function evaluateApiParity({
  serverEndpoints,
  sdkEndpoints,
  allowedMissing,
  reviewedServerOnlyEndpoints,
}) {
  const requiredServerEndpoints = [...serverEndpoints].filter(
    (endpoint) => !allowedMissing.has(endpoint) && !reviewedServerOnlyEndpoints.has(endpoint),
  );
  const missing = requiredServerEndpoints
    .filter((endpoint) => !sdkEndpoints.has(endpoint))
    .sort();
  const unknownSdkEndpoints = [...sdkEndpoints]
    .filter((endpoint) => !serverEndpoints.has(endpoint))
    .sort();
  const staleAllowedExceptions = [...allowedMissing].filter(
    ([endpoint]) => !serverEndpoints.has(endpoint) || sdkEndpoints.has(endpoint),
  );
  const staleReviewedGaps = [...reviewedServerOnlyEndpoints].filter(
    ([endpoint]) => !serverEndpoints.has(endpoint) || sdkEndpoints.has(endpoint),
  );
  const activeAllowedExceptions = [...allowedMissing].filter(
    ([endpoint]) => serverEndpoints.has(endpoint) && !sdkEndpoints.has(endpoint),
  );

  return {
    activeAllowedExceptions,
    missing,
    ok:
      missing.length === 0 &&
      unknownSdkEndpoints.length === 0 &&
      staleAllowedExceptions.length === 0 &&
      staleReviewedGaps.length === 0,
    requiredServerEndpoints,
    staleAllowedExceptions,
    staleReviewedGaps,
    unknownSdkEndpoints,
  };
}

export function endpointSet(values) {
  return new Set(values);
}
