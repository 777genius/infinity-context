import { describe, expect, it } from "vitest";
import { HttpClient, InfinityContextError, redactSensitiveText } from "../src/index.js";

const EXTERNAL_CAUSE = { name: "Error", message: "External error cause redacted" };

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
    const deepBody = `${'{"next":'.repeat(20_000)}"leaf"${"}".repeat(20_000)}`;
    let sends = 0;
    const client = new HttpClient({
      transport: {
        send: async () => {
          sends += 1;
          return { status: 400, headers: new Headers(), body: deepBody };
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
