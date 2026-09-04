import { describe, expect, it, vi } from "vitest";
import {
  HttpClient,
  InfinityContextError,
  MAX_ERROR_RESPONSE_BYTES,
  redactSensitiveText,
} from "../src/index.js";
import type { JsonValue } from "../src/types.js";

const EXTERNAL_CAUSE = { name: "Error", message: "External error cause redacted" };
const DETAIL_BYTE_LIMIT = 16_384;

async function parsedHttpError(body: string): Promise<InfinityContextError> {
  const client = new HttpClient({
    transport: { send: async () => ({
      status: 400, headers: new Headers({ "content-type": "application/json" }), body,
    }) },
    retryPolicy: { maxAttempts: 1 },
  });
  try {
    await client.request({ method: "GET", path: "/server-error" });
  } catch (error) {
    expect(error).toBeInstanceOf(InfinityContextError);
    return error as InfinityContextError;
  }
  throw new Error("Expected the HTTP request to fail");
}

function jsonByteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

describe("bounded immutable public Error snapshots", () => {
  it.each(["abort", "throw"] as const)("does not inspect a hostile Proxy on raw %s", async (mode) => {
    const traps = { get: 0, getPrototypeOf: 0, ownKeys: 0, descriptor: 0 };
    const hostile = new Proxy({}, {
      get: () => { traps.get += 1; throw new Error("GET_TRAP"); },
      getPrototypeOf: () => { traps.getPrototypeOf += 1; throw new Error("PROTOTYPE_TRAP"); },
      ownKeys: () => { traps.ownKeys += 1; throw new Error("OWN_KEYS_TRAP"); },
      getOwnPropertyDescriptor: () => { traps.descriptor += 1; throw new Error("DESCRIPTOR_TRAP"); },
    });
    const controller = new AbortController();
    if (mode === "abort") controller.abort(hostile);
    const client = new HttpClient({
      transport: { send: async () => { throw hostile; } },
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(client.request({ method: "GET", path: "/hostile", signal: controller.signal })).rejects.toMatchObject({
      code: mode === "abort" ? "memory.request_aborted" : "memory.network_error",
      message: mode === "abort" ? "Infinity Context request aborted" : "Infinity Context request failed",
      cause: EXTERNAL_CAUSE,
    });
    expect(traps).toEqual({ get: 0, getPrototypeOf: 0, ownKeys: 0, descriptor: 0 });
  });

  it("does not invoke inherited, own, or lazy-stack accessors", () => {
    let calls = 0;
    const prototype = Object.create(null) as object;
    Object.defineProperties(prototype, {
      name: { get: () => { calls += 1; throw new Error("INHERITED_NAME"); } },
      message: { get: () => { calls += 1; throw new Error("INHERITED_MESSAGE"); } },
      toString: { value: () => { calls += 1; throw new Error("TO_STRING"); } },
    });
    const hostile = Object.create(prototype) as Error;
    Object.defineProperties(hostile, {
      cause: { get: () => { calls += 1; throw new Error("OWN_CAUSE"); } },
      stack: { get: () => { calls += 1; throw new Error("LAZY_STACK"); } },
    });

    const error = new InfinityContextError({
      statusCode: 0,
      code: "memory.network_error",
      message: "safe public message",
      retryable: true,
      cause: hostile,
    });

    expect(calls).toBe(0);
    expect(error.cause).toEqual(EXTERNAL_CAUSE);
    expect(Object.isFrozen(error.cause)).toBe(true);
    expect(calls).toBe(0);
  });

  it("does not recognize a forged InfinityContextError prototype", async () => {
    const forged = Object.create(InfinityContextError.prototype) as InfinityContextError;
    Object.defineProperties(forged, {
      code: { get: () => { throw new Error("FORGED_CODE_GETTER"); } },
      message: { get: () => { throw new Error("FORGED_MESSAGE_GETTER"); } },
    });
    const client = new HttpClient({
      transport: { send: async () => { throw forged; } },
      retryPolicy: { maxAttempts: 1 },
    });
    await expect(client.request({ method: "GET", path: "/forged" })).rejects.toMatchObject({
      code: "memory.network_error",
      message: "Infinity Context request failed",
      cause: EXTERNAL_CAUSE,
    });
  });

  it("fails closed on Proxy, cyclic, and 20k-level public details without traversal", () => {
    let traps = 0;
    const proxy = new Proxy({}, {
      get: () => { traps += 1; throw new Error("GET"); },
      getPrototypeOf: () => { traps += 1; throw new Error("PROTOTYPE"); },
      ownKeys: () => { traps += 1; throw new Error("KEYS"); },
      getOwnPropertyDescriptor: () => { traps += 1; throw new Error("DESCRIPTOR"); },
    });
    const root: Record<string, unknown> = { proxy };
    let cursor = root;
    for (let depth = 0; depth < 20_000; depth += 1) {
      const next: Record<string, unknown> = {};
      cursor.next = next;
      cursor = next;
    }
    cursor.cycle = root;
    const started = performance.now();
    const error = new InfinityContextError({
      statusCode: 400,
      code: "memory.bad_request",
      message: "bad request",
      retryable: false,
      details: root as never,
      cause: proxy,
    });

    expect(performance.now() - started).toBeLessThan(1_000);
    expect(error.details).toBe("[Untrusted details omitted]");
    expect(error.cause).toEqual(EXTERNAL_CAUSE);
    expect(traps).toBe(0);
  });

  it("bounds a 4MB adversarial text field and redacts whole sensitive fields", () => {
    const input = `prefix api_key=tail-${"x".repeat(4 * 1024 * 1024)}`;
    const started = performance.now();
    const output = redactSensitiveText(input);
    expect(output).toBe("[REDACTED]");
    expect(performance.now() - started).toBeLessThan(1_000);

    const benign = "x".repeat(4 * 1024 * 1024);
    expect(redactSensitiveText(benign).length).toBeLessThanOrEqual(16_384);
  });

  it.each([
    "tokenizer is enabled",
    "the secretary replied",
    "passwordless login is enabled",
  ])("preserves benign component boundary: %s", (value) => {
    expect(redactSensitiveText(value)).toBe(value);
    expect(redactSensitiveText(redactSensitiveText(value))).toBe(value);
  });

  it.each([
    "Authorization: (Bearer SECRET_TAIL)",
    "authorization=\\\"Basic SECRET_TAIL==\\\"",
    "escaped {\\\"api_key\\\":\\\"SECRET_TAIL\\\"}",
    "prefix clientSecret=SECRET_TAIL!",
    "refresh-token: SECRET_TAIL",
  ])("redacts the entire escaped or wrapped sensitive field: %s", (value) => {
    expect(redactSensitiveText(value)).toBe("[REDACTED]");
    expect(redactSensitiveText(redactSensitiveText(value))).toBe("[REDACTED]");
  });

  it("snapshots native and branded causes without retaining mutable public state", async () => {
    const native = new Error("native original");
    const first = new InfinityContextError({
      statusCode: 409,
      code: "memory.conflict",
      message: "safe original",
      retryable: false,
      cause: native,
    });
    native.message = "api_key=NATIVE_MUTATION";
    expect(first.cause).toEqual(EXTERNAL_CAUSE);
    expect(Object.isFrozen(first)).toBe(true);
    expect(Reflect.set(first as unknown as Record<string, unknown>, "message", "api_key=PUBLIC_MUTATION")).toBe(false);

    const client = new HttpClient({
      transport: { send: async () => { throw first; } },
      retryPolicy: { maxAttempts: 1 },
    });
    let copied: unknown;
    try { await client.request({ method: "GET", path: "/branded" }); } catch (error) { copied = error; }
    expect(copied).toBeInstanceOf(InfinityContextError);
    expect(copied).not.toBe(first);
    expect(copied).toMatchObject({ code: "memory.conflict", message: "safe original", retryable: false });
    expect(JSON.stringify(copied)).not.toMatch(/NATIVE_MUTATION|PUBLIC_MUTATION/);
  });

  it("bounds trusted network details iteratively with one network attempt", async () => {
    const deepBody = `${'{"next":'.repeat(1_000)}"leaf"${"}".repeat(1_000)}`;
    let sends = 0;
    const client = new HttpClient({
      transport: {
        send: async () => {
          sends += 1;
          return {
            status: 400, headers: new Headers({ "content-type": "application/json" }), body: deepBody,
          };
        },
      },
      retryPolicy: { maxAttempts: 1 },
    });
    const started = performance.now();
    let caught: unknown;
    try { await client.request({ method: "GET", path: "/deep" }); } catch (error) { caught = error; }
    expect(performance.now() - started).toBeLessThan(2_000);
    expect(sends).toBe(1);
    expect(caught).toBeInstanceOf(InfinityContextError);
    let value = (caught as InfinityContextError).details as Record<string, unknown>;
    let depth = 0;
    while (typeof value === "object" && value !== null && "next" in value) {
      expect(Object.isFrozen(value)).toBe(true);
      value = value.next as Record<string, unknown>;
      depth += 1;
    }
    expect(depth).toBeLessThanOrEqual(17);
    expect(value).toBe("[Truncated]");
  });

  it("replaces a large bounded sensitive server property name before public exposure", async () => {
    const sentinel = "SECRET_KEY_SENTINEL_MUST_NOT_ESCAPE";
    const sensitiveKey = `${"x".repeat(8_000)}_api_key_${sentinel}`;
    const error = await parsedHttpError(JSON.stringify({
      error: { code: "memory.bad_request", message: "safe failure" },
      [sensitiveKey]: "also hidden",
    }));
    const exposed = JSON.stringify(error.details);

    expect(exposed).toContain("[REDACTED_KEY]");
    expect(exposed).not.toContain(sentinel);
    expect(exposed).not.toContain("also hidden");
    expect(jsonByteLength(error.details)).toBeLessThanOrEqual(DETAIL_BYTE_LIMIT);
  });

  it("stops deterministically on hundreds of bounded parsed server properties", async () => {
    const payload: Record<string, unknown> = {
      error: { code: "memory.bad_request", message: "safe failure" },
    };
    for (let index = 0; index < 750; index += 1) payload[`field_${index}`] = index;
    const error = await parsedHttpError(JSON.stringify(payload));
    const details = error.details as Record<string, unknown>;

    // The root container also consumes one of the 256 graph nodes.
    expect(Object.keys(details).length).toBeLessThanOrEqual(255);
    expect(details.field_0).toBe(0);
    expect(details.field_749).toBeUndefined();
    expect(jsonByteLength(details)).toBeLessThanOrEqual(DETAIL_BYTE_LIMIT);
  });

  it.each(["string", "bytes"] as const)(
    "does not parse an oversized error body supplied by a custom %s transport",
    async (bodyType) => {
      const hiddenCode = "memory.hidden_after_hard_cap";
      const raw = JSON.stringify({
        error: { code: hiddenCode, message: "must not escape", retryable: true },
        padding: "x".repeat(MAX_ERROR_RESPONSE_BYTES),
      });
      const body = bodyType === "bytes" ? new TextEncoder().encode(raw) : raw;
      let sends = 0;
      const parse = vi.spyOn(JSON, "parse");
      const client = new HttpClient({
        transport: {
          send: async () => {
            sends += 1;
            return {
              status: 418,
              headers: new Headers({ "x-request-id": "request-hard-cap" }),
              body,
            };
          },
        },
        retryPolicy: { maxAttempts: 2 },
      });

      let caught: unknown;
      try {
        await client.request({ method: "GET", path: "/oversized-error" });
      } catch (error) {
        caught = error;
      }
      expect(parse).not.toHaveBeenCalled();
      parse.mockRestore();

      expect(caught).toBeInstanceOf(InfinityContextError);
      expect(caught).toMatchObject({
        code: "memory.response_byte_limit_exceeded",
        message: "Infinity Context response exceeds the caller byte limit",
        statusCode: 418,
        requestId: "request-hard-cap",
        retryable: false,
      });
      const error = caught as InfinityContextError;
      expect(error.details).toBeUndefined();
      expect(error.retryAfterMs).toBeUndefined();
      expect(error.cause).toBeUndefined();
      expect(`${error.code}\n${error.message}\n${JSON.stringify(error.details)}`).not.toMatch(
        /memory\.hidden_after_hard_cap|must not escape/,
      );
      expect(sends).toBe(1);
      expect(raw).toContain(hiddenCode);
    },
  );

  it("caps multibyte server keys by UTF-8 bytes and disambiguates truncated keys", async () => {
    const shared = "😀".repeat(100);
    const error = await parsedHttpError(JSON.stringify({
      error: { code: "memory.bad_request", message: "safe failure" },
      [`${shared}first`]: "one",
      [`${shared}second`]: "two",
    }));
    const details = error.details as Record<string, unknown>;
    const keys = Object.keys(details).filter((key) => key !== "error");

    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(2);
    expect(keys.every((key) => new TextEncoder().encode(key).byteLength <= 256)).toBe(true);
    expect(Object.values(details).filter((value) => value === "one" || value === "two")).toHaveLength(2);
  });

  it("keeps colliding sanitized sensitive keys unique without exposing their names", async () => {
    const sentinel = "SECRET_SENTINEL";
    const error = await parsedHttpError(JSON.stringify({
      error: { code: "memory.bad_request", message: "safe failure" },
      [`api_key_${sentinel}`]: "first hidden value",
      [`Bearer_${sentinel}`]: "second hidden value",
      authorization: "third hidden value",
    }));
    const details = error.details as Record<string, unknown>;
    const exposed = JSON.stringify(details);

    expect(details["[REDACTED_KEY]"]).toBe("[REDACTED]");
    expect(details["[REDACTED_KEY]_2"]).toBe("[REDACTED]");
    expect(details["[REDACTED_KEY]_3"]).toBe("[REDACTED]");
    expect(exposed).not.toMatch(/SECRET_SENTINEL|api_key|Bearer|authorization|hidden value/);
  });

  it("preserves normal useful parsed server details", async () => {
    const error = await parsedHttpError(JSON.stringify({
      error: { code: "memory.conflict", message: "Version conflict", retryable: false },
      current_version: 7,
      resource_id: "fact_123",
      conflicts: ["title", "summary"],
    }));

    expect(error).toMatchObject({ code: "memory.conflict", message: "Version conflict", retryable: false });
    expect(error.details).toMatchObject({
      current_version: 7,
      resource_id: "fact_123",
      conflicts: ["title", "summary"],
    });
  });

  it("includes escaped keys and values in the aggregate public detail byte bound", async () => {
    const payload: Record<string, unknown> = {
      error: { code: "memory.bad_request", message: "safe failure" },
    };
    for (let index = 0; index < 256; index += 1) {
      payload[`${'"\\\n'.repeat(80)}_${index}`] = '"\\\n'.repeat(2_000);
    }
    const error = await parsedHttpError(JSON.stringify(payload));

    expect(jsonByteLength(error.details)).toBeLessThanOrEqual(DETAIL_BYTE_LIMIT);
  });

  it("bounds property reads for an instrumented trusted parsed object", async () => {
    const target: Record<string, JsonValue> = {
      error: { code: "memory.bad_request", message: "safe failure" },
    };
    for (let index = 0; index < 5_000; index += 1) target[`field_${index}`] = index;
    const traps = { ownKeys: 0, descriptors: 0, gets: 0 };
    const instrumented = new Proxy(target, {
      ownKeys: (value) => { traps.ownKeys += 1; return Reflect.ownKeys(value); },
      getOwnPropertyDescriptor: (value, key) => {
        traps.descriptors += 1;
        return Reflect.getOwnPropertyDescriptor(value, key);
      },
      get: (value, key, receiver) => { traps.gets += 1; return Reflect.get(value, key, receiver); },
    });
    const parse = vi.spyOn(JSON, "parse").mockReturnValue(instrumented);
    try {
      await parsedHttpError("instrumented trusted payload");
    } finally {
      parse.mockRestore();
    }

    expect(traps.ownKeys).toBe(1);
    expect(traps.gets).toBeLessThanOrEqual(258);
    expect(traps.descriptors).toBeLessThanOrEqual(513);
  });

  it("bounds branded cause depth and reconstructs every branded cause", () => {
    let error = new InfinityContextError({
      statusCode: 0, code: "memory.root", message: "root failure", retryable: false,
    });
    for (let depth = 0; depth < 12; depth += 1) {
      const previous = error;
      error = new InfinityContextError({
        statusCode: 0, code: `memory.level_${depth}`, message: `level ${depth}`, retryable: false, cause: previous,
      });
      expect(error.cause).not.toBe(previous);
    }
    let cause: unknown = error.cause;
    let depth = 0;
    while (cause instanceof InfinityContextError) {
      depth += 1;
      cause = cause.cause;
    }
    expect(depth).toBeLessThanOrEqual(4);
    expect(cause).toEqual(EXTERNAL_CAUSE);
  });
});
