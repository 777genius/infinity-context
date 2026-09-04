import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

import * as sdk from "../src/index.js";
import { runRetrievalRuntimeCanaryCli } from "../scripts/retrieval-runtime-canary.mjs";

describe("Retrieval runtime canary endpoint exactness", () => {
  it.each([201, 202])("rejects runtime Retrieval HTTP %s before decoding", async (status) => {
    const fixture = await runtimeFixtures();
    const requests = [];
    const fakeSdk = sdkWithResponses([
      sdkResponse({ context: { retrieval: fixture.capability } }),
      sdkResponse({}, status),
    ], requests);

    const result = await runRetrievalRuntimeCanaryCli({
      env: runtimeEnv(fixture.capability),
      sdk: fakeSdk,
      stdout: captureOutput(),
      requestFixture: fixture.request,
      localAttestationVerifier: async () => {},
    });

    expect(result.exitCode).toBe(1);
    expect(result.error).toMatchObject({
      code: "memory.unexpected_response_status",
      statusCode: status,
      retryable: false,
    });
    expect(requests).toEqual(["GET /v1/capabilities", "POST /v1/context/retrieve"]);
  });

  it("requires JSON media on the runtime capability GET", async () => {
    const fixture = await runtimeFixtures();
    const requests = [];
    const fakeSdk = sdkWithResponses([{
      status: 200,
      headers: new Headers({ "content-type": "text/plain" }),
      body: JSON.stringify({ context: { retrieval: fixture.capability } }),
    }], requests);

    const result = await runRetrievalRuntimeCanaryCli({
      env: runtimeEnv(fixture.capability),
      sdk: fakeSdk,
      stdout: captureOutput(),
      requestFixture: fixture.request,
      localAttestationVerifier: async () => {},
    });

    expect(result.exitCode).toBe(1);
    expect(result.error).toMatchObject({
      code: "memory.invalid_response_content_type",
      statusCode: 200,
      retryable: false,
    });
    expect(requests).toEqual(["GET /v1/capabilities"]);
  });
});

async function runtimeFixtures() {
  const [capabilityFixture, requestFixture] = await Promise.all([
    readFile(new URL("../fixtures/context_retrieval_v2/capability.json", import.meta.url), "utf8"),
    readFile(new URL("../fixtures/context_retrieval_v2/request.json", import.meta.url), "utf8"),
  ]);
  return { capability: JSON.parse(capabilityFixture), request: JSON.parse(requestFixture) };
}

function runtimeEnv(capability) {
  return {
    INFINITY_CONTEXT_URL: "http://memory.test",
    RETRIEVAL_CANARY_SPACE_ID: "space-canary",
    RETRIEVAL_CANARY_MEMORY_SCOPE_ID: "scope-canary",
    RETRIEVAL_CAPABILITY_FINGERPRINT: capability.capability_fingerprint,
    RETRIEVAL_PROFILE_ID: capability.profile_id,
    RETRIEVAL_SDK_REVISION: capability.sdk_revision,
    RETRIEVAL_SERVICE_REVISION: capability.service_revision,
    RETRIEVAL_REQUIRED_PROVIDER_LANES: capability.required_provider_lanes.join(","),
    RETRIEVAL_PROVIDER_LANES: capability.provider_lanes.map((lane) => lane.provider_id).join(","),
    RETRIEVAL_CANARY_EXPECTED_LOCATOR: "seeded-locator",
  };
}

function captureOutput() {
  return {
    text: "",
    write(value) {
      this.text += value;
      return true;
    },
  };
}

function sdkResponse(value, status = 200) {
  return {
    status,
    headers: new Headers({ "content-type": "application/json" }),
    body: JSON.stringify(value),
  };
}

function sdkWithResponses(responses, requests) {
  return {
    ...sdk,
    HttpClient: class {
      constructor(options) {
        this.client = new sdk.HttpClient({
          ...options,
          retryPolicy: { maxAttempts: 1 },
          transport: {
            send: async (request) => {
              requests.push(`${request.method} ${request.url.pathname}`);
              const response = responses.shift();
              if (response === undefined) throw new Error("unexpected SDK request");
              return response;
            },
          },
        });
      }

      request(options) {
        return this.client.request(options);
      }
    },
  };
}
