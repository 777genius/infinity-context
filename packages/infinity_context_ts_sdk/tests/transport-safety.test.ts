import { createServer } from "node:http";
import { describe, expect, it } from "vitest";
import { FetchTransport, HttpClient, InfinityContextClient } from "../src/index.js";
import { RecordingTransport, jsonResponse } from "./fixtures.js";

describe("HTTP transport safety", () => {
  it.each([301, 302, 303, 307, 308])(
    "rejects HTTP %s without following or replaying a POST",
    async (status) => {
      const calls: Array<{ readonly url: string; readonly init?: RequestInit }> = [];
      const fetchLike = (async (input: string | URL | Request, init?: RequestInit) => {
        calls.push({ url: String(input), ...(init === undefined ? {} : { init }) });
        return new Response("redirect body", {
          status,
          headers: { location: "https://hostile.example/steal" },
        });
      }) as typeof fetch;
      const client = new HttpClient({
        baseUrl: "https://memory.test",
        token: "credential-sentinel",
        transport: new FetchTransport(fetchLike),
        retryPolicy: { maxAttempts: 1 },
      });

      await expect(client.request({
        method: "POST", path: "/v1/facts", json: { text: "submit once" }, expectedStatuses: [201],
      })).rejects.toMatchObject({ code: "memory.redirect_rejected", statusCode: status, retryable: false });
      expect(calls).toHaveLength(1);
      expect(calls[0]?.url).toBe("https://memory.test/v1/facts");
      expect(calls[0]?.init?.redirect).toBe("manual");
      expect(new Headers(calls[0]?.init?.headers).get("authorization")).toBe("Bearer credential-sentinel");
      expect(JSON.stringify(calls)).not.toContain("hostile.example");
    },
  );

  it.each(["opaque", "opaqueredirect"] as const)(
    "rejects a deterministic %s redirect response before body handling",
    async (type) => {
      let bodyAccessed = false;
      const response = {
        type,
        status: 0,
        get headers() { throw new Error("opaque headers must not be inspected"); },
        get body() { bodyAccessed = true; throw new Error("opaque body must not be inspected"); },
      } as unknown as Response;
      const calls: RequestInit[] = [];
      const transport = new FetchTransport((async (_input, init) => {
        calls.push(init ?? {});
        return response;
      }) as typeof fetch);

      await expect(transport.send({
        method: "POST", url: new URL("https://memory.test/write"), headers: new Headers(),
        body: { kind: "json", value: { once: true } },
      })).rejects.toMatchObject({ code: "memory.redirect_rejected", statusCode: 0, retryable: false });
      expect(calls).toHaveLength(1);
      expect(calls[0]?.redirect).toBe("manual");
      expect(bodyAccessed).toBe(false);
    },
  );

  it("rejects a real loopback Fetch redirect without following or replaying the POST", async () => {
    let sourceCalls = 0;
    let targetCalls = 0;
    const server = createServer((request, response) => {
      if (request.url === "/redirect") {
        sourceCalls += 1;
        response.writeHead(307, { location: "/target" });
      } else {
        targetCalls += 1;
        response.writeHead(200, { "content-type": "application/json" });
      }
      response.end("{}");
    });
    try {
      await new Promise<void>((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
      });
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "EACCES" || code === "EPERM") {
        console.warn(`Skipping real loopback redirect proof: listen denied with ${code}`);
        return;
      }
      throw error;
    }
    try {
      const address = server.address();
      if (address === null || typeof address === "string") throw new Error("loopback server address unavailable");
      const client = new HttpClient({
        baseUrl: `http://127.0.0.1:${address.port}`,
        token: "credential-sentinel",
        retryPolicy: { maxAttempts: 2 },
      });

      const outcome = await client.request({
        method: "POST", path: "/redirect", json: { submit: "once" }, expectedStatuses: [200],
      }).catch((error: unknown) => error);
      expect(outcome).toMatchObject({
        code: "memory.redirect_rejected", statusCode: 307, retryable: false,
      });
      expect(sourceCalls).toBe(1);
      expect(targetCalls).toBe(0);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("requires an operation's exact declared success status before decoding", async () => {
    const client = new HttpClient({
      transport: new FetchTransport((async () => new Response(new Uint8Array([0xff]), {
        status: 200,
        headers: { "content-type": "text/html" },
      })) as typeof fetch),
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(client.request({
      method: "POST", path: "/create", expectedStatuses: [201],
    })).rejects.toMatchObject({ code: "memory.unexpected_response_status", statusCode: 200 });
  });

  it.each([
    ["missing", undefined],
    ["HTML", "text/html"],
    ["wrong charset", "application/json; charset=iso-8859-1"],
    ["duplicate charset", "application/json; charset=utf-8; charset=utf-8"],
    ["ambiguous values", "application/json, text/html"],
    ["unknown parameter", "application/json; profile=unsafe"],
  ] as const)("rejects %s content type before successful JSON decoding", async (_name, contentType) => {
    const headers = new Headers();
    if (contentType !== undefined) headers.set("content-type", contentType);
    const client = new HttpClient({
      transport: { send: async () => ({ status: 200, headers, body: "{\"ok\":true}" }) },
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(client.request({ method: "GET", path: "/json" })).rejects.toMatchObject({
      code: "memory.invalid_response_content_type", statusCode: 200, retryable: false,
    });
  });

  it.each(["application/json", "Application/JSON; Charset=UTF-8"])(
    "accepts exact JSON media contract %s",
    async (contentType) => {
      const client = new HttpClient({
        transport: { send: async () => ({
          status: 200, headers: new Headers({ "content-type": contentType }), body: "{\"ok\":true}",
        }) },
        retryPolicy: { maxAttempts: 1 },
      });
      await expect(client.request({ method: "GET", path: "/json" })).resolves.toEqual({ ok: true });
    },
  );

  it("requires JSON media for the raw-byte capabilities decoder", async () => {
    const client = new InfinityContextClient({
      transport: new RecordingTransport([{
        status: 200,
        headers: new Headers({ "content-type": "text/html" }),
        body: new TextEncoder().encode("{\"enabled_adapters\":[]}"),
      }]),
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(client.system.capabilities()).rejects.toMatchObject({
      code: "memory.invalid_response_content_type", statusCode: 200,
    });
  });

  it("does not parse or expose an HTML or missing-media-type error body", async () => {
    for (const headers of [
      new Headers({ "content-type": "text/html" }),
      new Headers({ "content-type": "application/json; charset=iso-8859-1" }),
      new Headers({ "content-type": "application/json; charset=utf-8; charset=utf-8" }),
      new Headers(),
    ]) {
      const secret = "credential=must-not-escape";
      const client = new HttpClient({
        transport: { send: async () => ({ status: 400, headers, body: `<html>${secret}</html>` }) },
        retryPolicy: { maxAttempts: 1 },
      });
      try {
        await client.request({ method: "GET", path: "/error" });
        throw new Error("expected failure");
      } catch (error) {
        expect(error).toMatchObject({
          code: "memory.invalid_response_content_type",
          message: "Infinity Context error response must use application/json with optional UTF-8 charset",
          retryable: false,
        });
        expect(JSON.stringify(error)).not.toContain(secret);
      }
    }
  });

  it("bounds capability, error, and ordinary JSON success bodies before parsing", async () => {
    const capabilityClient = new InfinityContextClient({
      transport: new RecordingTransport([jsonResponse({ padding: "x".repeat(256 * 1024) })]),
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(capabilityClient.system.capabilities()).rejects.toMatchObject({
      code: "memory.response_byte_limit_exceeded", statusCode: 200,
    });

    const errorClient = new HttpClient({
      transport: new RecordingTransport([jsonResponse({
        error: { code: "memory.hidden", message: "must not parse" }, padding: "x".repeat(16_384),
      }, 400)]),
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(errorClient.request({ method: "GET", path: "/error" })).rejects.toMatchObject({
      code: "memory.response_byte_limit_exceeded", statusCode: 400,
    });

    const successClient = new HttpClient({
      transport: new RecordingTransport([jsonResponse({ ok: true })]),
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(successClient.request({
      method: "GET", path: "/success", maxResponseBytes: 5,
    })).rejects.toMatchObject({ code: "memory.response_byte_limit_exceeded", statusCode: 200 });
  });
});
