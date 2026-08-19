import assert from "node:assert/strict";

import { endpointSet, evaluateApiParity } from "./api-parity-policy.mjs";

const allowedMissing = new Map([
  ["GET /v1/healthz", "Liveness alias is intentionally not exposed."],
]);
const reviewedServerOnlyEndpoints = new Map([
  ["POST /v1/internal/report", { owner: "diagnostics", reason: "Internal-only API." }],
]);
const serverEndpoints = endpointSet([
  "GET /v1/healthz",
  "GET /v1/items",
  "POST /v1/internal/report",
]);
const sdkEndpoints = endpointSet(["GET /v1/items"]);

assert.equal(evaluate({ serverEndpoints, sdkEndpoints }).ok, true);

const unknownSdk = evaluate({
  serverEndpoints,
  sdkEndpoints: endpointSet([...sdkEndpoints, "GET /v1/ghost"]),
});
assert.equal(unknownSdk.ok, false);
assert.deepEqual(unknownSdk.unknownSdkEndpoints, ["GET /v1/ghost"]);

const missingSdk = evaluate({
  serverEndpoints,
  sdkEndpoints: endpointSet([]),
});
assert.equal(missingSdk.ok, false);
assert.deepEqual(missingSdk.missing, ["GET /v1/items"]);

const staleException = evaluate({
  serverEndpoints,
  sdkEndpoints: endpointSet([...sdkEndpoints, "GET /v1/healthz"]),
});
assert.equal(staleException.ok, false);
assert.equal(staleException.staleAllowedExceptions[0]?.[0], "GET /v1/healthz");

const staleReviewedGap = evaluate({
  serverEndpoints,
  sdkEndpoints: endpointSet([...sdkEndpoints, "POST /v1/internal/report"]),
});
assert.equal(staleReviewedGap.ok, false);
assert.equal(staleReviewedGap.staleReviewedGaps[0]?.[0], "POST /v1/internal/report");

console.log("API parity policy fixtures ok: unknown, missing, stale exception and stale review fail closed.");

function evaluate({ serverEndpoints: server, sdkEndpoints: sdk }) {
  return evaluateApiParity({
    allowedMissing,
    reviewedServerOnlyEndpoints,
    sdkEndpoints: sdk,
    serverEndpoints: server,
  });
}
