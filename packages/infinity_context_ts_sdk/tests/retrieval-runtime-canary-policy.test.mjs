import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import * as sdk from "../src/index.js";
import {
  runRetrievalRuntimeCanaryCli,
} from "../scripts/retrieval-runtime-canary.mjs";
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
const servers = [];

afterEach(async () => {
  await Promise.all(servers.splice(0).map(async (server) => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }));
});

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

  it("executes through a package-bin symlink and reports a controlled failure", async () => {
    const root = await mkdtemp(join(tmpdir(), "retrieval-canary-bin-"));
    const bin = join(root, "node_modules", ".bin", "infinity-context-retrieval-runtime-canary");
    const cli = fileURLToPath(new URL("../scripts/retrieval-runtime-canary.mjs", import.meta.url));
    try {
      await mkdir(dirname(bin), { recursive: true });
      await symlink(cli, bin);

      const result = spawnSync(process.execPath, [bin], {
        encoding: "utf8",
        env: {},
        timeout: 2_000,
      });

      expect(result.error).toBeUndefined();
      expect(result.signal).toBeNull();
      expect(result.status).toBe(1);
      expect(result.stderr).toBe("");
      expect(JSON.parse(result.stdout)).toMatchObject({
        schema_version: "infinity-context-retrieval-runtime-canary.v1",
        ok: false,
        error: {
          name: "Error",
          message: "RETRIEVAL_CANARY_SPACE_ID is required",
        },
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it.each(["capability", "retrieval"])(
    "records a typed SDK byte-budget failure for an oversized %s response",
    async (oversizedEndpoint) => {
      const fixture = await runtimeFixtures();
      const requests = [];
      const service = await startService(async (request, reply) => {
        requests.push({ method: request.method, url: request.url, body: await requestBody(request) });
        if (request.url === "/v1/capabilities" && oversizedEndpoint !== "capability") {
          return json(reply, { context: { retrieval: fixture.capability } });
        }
        const byteLimit = oversizedEndpoint === "capability"
          ? 1_048_576
          : fixture.request.bounds.response_byte_limit;
        reply.writeHead(200, { "content-type": "application/json" });
        reply.end("x".repeat(byteLimit + 1));
      });

      const output = captureOutput();
      const processState = {};
      const result = await runRetrievalRuntimeCanaryCli({
        env: runtimeEnv(service.url, fixture.capability),
        sdk,
        stdout: output,
        requestFixture: fixture.request,
        exitCodeTarget: processState,
      });

      expect(result.exitCode).toBe(1);
      expect(processState.exitCode).toBe(1);
      expect(result.error).toBeInstanceOf(sdk.InfinityContextError);
      expect(result.error).toMatchObject({
        code: "memory.response_byte_limit_exceeded",
        statusCode: 200,
        retryable: false,
      });
      expect(JSON.parse(output.text)).toMatchObject({
        ok: false,
        error: {
          name: "InfinityContextError",
          code: "memory.response_byte_limit_exceeded",
          status_code: 200,
          retryable: false,
        },
      });
      expect(requests.map(({ method, url }) => `${method} ${url}`)).toEqual(
        oversizedEndpoint === "capability"
          ? ["GET /v1/capabilities"]
          : ["GET /v1/capabilities", "POST /v1/context/retrieve"],
      );
      if (oversizedEndpoint === "retrieval") {
        expect(JSON.parse(requests[1].body).queries).toEqual([
          { query_id: "runtime-canary", query: "runtime readiness", weight_micros: 1000000 },
        ]);
      }
    },
  );

  it("bounds a stalled retrieval body and records the typed SDK timeout", async () => {
    const fixture = await runtimeFixtures();
    const boundedRequest = {
      ...fixture.request,
      bounds: { ...fixture.request.bounds, deadline_ms: 40 },
    };
    let retrievalRequest;
    const service = await startService(async (request, reply) => {
      if (request.url === "/v1/capabilities") {
        return json(reply, { context: { retrieval: fixture.capability } });
      }
      retrievalRequest = JSON.parse(await requestBody(request));
      reply.writeHead(200, { "content-type": "application/json" });
      reply.write('{"status":"available","candidates":[');
    });

    const output = captureOutput();
    const processState = {};
    const startedAt = Date.now();
    const result = await runRetrievalRuntimeCanaryCli({
      env: runtimeEnv(service.url, fixture.capability),
      sdk,
      stdout: output,
      requestFixture: boundedRequest,
      exitCodeTarget: processState,
    });

    expect(Date.now() - startedAt).toBeLessThan(1_000);
    expect(result.exitCode).toBe(1);
    expect(processState.exitCode).toBe(1);
    expect(result.error).toBeInstanceOf(sdk.InfinityContextError);
    expect(result.error).toMatchObject({ code: "memory.request_timeout", retryable: true });
    expect(JSON.parse(output.text)).toMatchObject({
      ok: false,
      error: {
        name: "InfinityContextError",
        code: "memory.request_timeout",
        retryable: true,
      },
    });
    expect(retrievalRequest.queries[0]).toMatchObject({ query_id: "runtime-canary" });
    expect(retrievalRequest.bounds.deadline_ms).toBe(40);
  });
});

async function runtimeFixtures() {
  const [capabilityFixture, requestFixture] = await Promise.all([
    readFile(new URL("../fixtures/context_retrieval_v2/capability.json", import.meta.url), "utf8"),
    readFile(new URL("../fixtures/context_retrieval_v2/request.json", import.meta.url), "utf8"),
  ]);
  return { capability: JSON.parse(capabilityFixture), request: JSON.parse(requestFixture) };
}

function runtimeEnv(url, capabilityFixture) {
  return {
    INFINITY_CONTEXT_URL: url,
    RETRIEVAL_CANARY_SPACE_ID: "space-canary",
    RETRIEVAL_CANARY_MEMORY_SCOPE_ID: "scope-canary",
    RETRIEVAL_CAPABILITY_FINGERPRINT: capabilityFixture.capability_fingerprint,
    RETRIEVAL_PROFILE_ID: capabilityFixture.profile_id,
    RETRIEVAL_SDK_REVISION: capabilityFixture.sdk_revision,
    RETRIEVAL_SERVICE_REVISION: capabilityFixture.service_revision,
    RETRIEVAL_CANARY_EXPECTED_LOCATOR: "seeded-locator",
  };
}

async function startService(handler) {
  const server = createServer((request, response) => {
    Promise.resolve(handler(request, response)).catch((error) => {
      response.destroy(error);
    });
  });
  servers.push(server);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return { url: `http://127.0.0.1:${address.port}` };
}

async function requestBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

function json(response, value) {
  response.writeHead(200, { "content-type": "application/json" });
  response.end(JSON.stringify(value));
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
