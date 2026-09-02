import { describe, expect, it } from "vitest";
import { HttpClient, InfinityContextError } from "../src/index.js";

describe("hostile public Error handling", () => {
  it.each(["abort", "throw"] as const)(
    "never invokes hostile inherited Error surfaces for a raw %s",
    async (mode) => {
      let getterCalls = 0;
      class HostileError extends Error {}
      Object.defineProperties(HostileError.prototype, {
        name: { get: () => { getterCalls += 1; throw new Error("HOSTILE_NAME_SENTINEL"); } },
        message: { get: () => { getterCalls += 1; return "api_key=HOSTILE_MESSAGE_SENTINEL"; } },
        credential: { value: "HOSTILE_INHERITED_SENTINEL" },
        toString: { value: () => { throw new Error("HOSTILE_TOSTRING_SENTINEL"); } },
      });
      const hostile = Object.create(HostileError.prototype) as Error;
      Object.defineProperty(hostile, "cause", {
        value: new Error("authorization=Bearer HOSTILE_NESTED_SENTINEL"),
      });
      const controller = new AbortController();
      if (mode === "abort") controller.abort(hostile);
      const client = new HttpClient({
        transport: { send: async () => { throw hostile; } },
        retryPolicy: { maxAttempts: 1 },
      });

      let caught: unknown;
      try {
        await client.request({ method: "GET", path: "/hostile", signal: controller.signal });
      } catch (error) {
        caught = error;
      }

      expect(caught).toBeInstanceOf(InfinityContextError);
      expect(caught).toMatchObject({
        code: mode === "abort" ? "memory.request_aborted" : "memory.network_error",
        retryable: mode !== "abort",
      });
      expect(getterCalls).toBe(0);
      expect((caught as Error).cause).not.toBe(hostile);
      const exposed = publicErrorText(caught);
      for (const sentinel of [
        "HOSTILE_NAME_SENTINEL",
        "HOSTILE_MESSAGE_SENTINEL",
        "HOSTILE_INHERITED_SENTINEL",
        "HOSTILE_TOSTRING_SENTINEL",
        "HOSTILE_NESTED_SENTINEL",
      ]) expect(exposed).not.toContain(sentinel);
      expect(getterCalls).toBe(0);
    },
  );

  it("sanitizes throwing own Error accessors without invoking them", () => {
    let getterCalls = 0;
    const hostile = new Error("safe constructor value");
    Object.defineProperties(hostile, {
      name: { get: () => { getterCalls += 1; throw new Error("OWN_NAME_SENTINEL"); } },
      message: { get: () => { getterCalls += 1; throw new Error("OWN_MESSAGE_SENTINEL"); } },
      toString: { value: () => { throw new Error("OWN_TOSTRING_SENTINEL"); } },
    });

    const error = new InfinityContextError({
      statusCode: 0,
      code: "memory.network_error",
      message: "safe public message",
      retryable: true,
      cause: hostile,
    });

    expect(getterCalls).toBe(0);
    expect(error.cause).not.toBe(hostile);
    expect(publicErrorText(error)).not.toMatch(/OWN_(?:NAME|MESSAGE|TOSTRING)_SENTINEL/);
    expect(getterCalls).toBe(0);
  });

  it("does not coerce hostile non-Error throw values", async () => {
    let coercions = 0;
    const hostile = {
      credential: "RAW_THROW_SENTINEL",
      get name() { throw new Error("RAW_NAME_SENTINEL"); },
      toString() { coercions += 1; throw new Error("RAW_TOSTRING_SENTINEL"); },
    };
    const client = new HttpClient({
      transport: { send: async () => { throw hostile; } },
      retryPolicy: { maxAttempts: 1 },
    });

    await expect(client.request({ method: "GET", path: "/hostile-value" })).rejects.toMatchObject({
      code: "memory.network_error",
      message: "Infinity Context request failed",
      cause: undefined,
    });
    expect(coercions).toBe(0);
  });

  it.each([
    new Error("benign native error"),
    new TypeError("benign native type error"),
    new DOMException("benign native abort", "AbortError"),
  ])("retains benign native error identity for %#", (cause) => {
    const error = new InfinityContextError({
      statusCode: 0,
      code: "memory.network_error",
      message: "safe public message",
      retryable: true,
      cause,
    });
    expect(error.cause).toBe(cause);
  });
});

function publicErrorText(value: unknown, seen = new WeakSet<object>()): string {
  if (value === null || (typeof value !== "object" && typeof value !== "function")) return String(value);
  if (typeof value === "function") return "[function]";
  if (seen.has(value)) return "[cycle]";
  seen.add(value);
  const surfaces: string[] = [];
  let surface: object | null = value;
  while (surface !== null) {
    for (const key of Object.getOwnPropertyNames(surface)) {
      if (key === "constructor") continue;
      const descriptor = Object.getOwnPropertyDescriptor(surface, key);
      surfaces.push(descriptor !== undefined && "value" in descriptor
        ? `${key}:${publicErrorText(descriptor.value, seen)}`
        : `${key}:[accessor]`);
    }
    surface = Object.getPrototypeOf(surface) as object | null;
  }
  return surfaces.join("\n");
}
