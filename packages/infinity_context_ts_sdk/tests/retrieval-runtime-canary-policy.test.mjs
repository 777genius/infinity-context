import { describe, expect, it } from "vitest";

import { assertRetrievalRuntimeCanary } from "../scripts/retrieval-runtime-canary-policy.mjs";

const capability = {
  capability_fingerprint: "f".repeat(64),
  profile_id: "profile-a",
  sdk_revision: "a".repeat(40),
  service_revision: "b".repeat(40),
  required_provider_lanes: ["postgres"],
  provider_lanes: [
    { provider_id: "graph", required: false, healthy: false, profile_qualified: false },
    { provider_id: "postgres", required: true, healthy: true, profile_qualified: true },
  ],
};
const response = {
  status: "available",
  candidates: [{ locator: "seeded-locator" }],
  provider_outcomes: [
    { provider_id: "graph", status: "unavailable", reason_code: "provider_unavailable" },
    { provider_id: "postgres", status: "available", reason_code: null },
  ],
};
const expected = {
  expectedFingerprint: capability.capability_fingerprint,
  expectedProfile: capability.profile_id,
  expectedSdkRevision: capability.sdk_revision,
  expectedServiceRevision: capability.service_revision,
  expectedLocator: "seeded-locator",
};

describe("Retrieval runtime canary policy", () => {
  it("accepts deterministic optional degradation without blocking a healthy required lane", () => {
    expect(() =>
      assertRetrievalRuntimeCanary({ capability, response, ...expected }),
    ).not.toThrow();
  });

  it.each([
    ["unavailable", { ...response, status: "unavailable" }],
    ["empty", { ...response, candidates: [] }],
    ["wrong locator", { ...response, candidates: [{ locator: "wrong" }] }],
    [
      "degraded required lane",
      {
        ...response,
        provider_outcomes: [
          response.provider_outcomes[0],
          { provider_id: "postgres", status: "unavailable", reason_code: "provider_unavailable" },
        ],
      },
    ],
  ])("rejects %s", (_name, candidate) => {
    expect(() =>
      assertRetrievalRuntimeCanary({ capability, response: candidate, ...expected }),
    ).toThrow();
  });

  it("rejects fingerprint, profile and revision drift", () => {
    for (const key of [
      "expectedFingerprint",
      "expectedProfile",
      "expectedSdkRevision",
      "expectedServiceRevision",
    ]) {
      expect(() =>
        assertRetrievalRuntimeCanary({ capability, response, ...expected, [key]: "wrong" }),
      ).toThrow(/immutable canary pins/);
    }
  });
});
