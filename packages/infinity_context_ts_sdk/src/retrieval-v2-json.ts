import { InfinityContextError } from "./errors.js";
import { assertUnicodeScalarString } from "./retrieval-v2-canonical.js";

/** Strict UTF-8 JSON seam with duplicate detection after JSON string decoding. */
export function decodeContextRetrievalV2Json(
  body: Uint8Array | string,
  integerPaths: readonly string[] = [],
): unknown {
  let text: string;
  try {
    // Preserve a leading BOM so the JSON parser rejects it exactly as the
    // authoritative Python UTF-8 decoder does. TextDecoder strips it unless
    // ignoreBOM is enabled, which would make the SDK accept noncanonical bytes.
    text = typeof body === "string"
      ? body
      : new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(body);
    const parser = new JsonShapeParser(text, integerPaths);
    parser.parse();
    return JSON.parse(text) as unknown;
  } catch (error) {
    if (error instanceof InfinityContextError) throw error;
    strictJsonInvalid("payload must be strict UTF-8 JSON");
  }
}

class JsonShapeParser {
  #index = 0;
  readonly #integerPaths: readonly string[];

  constructor(private readonly text: string, integerPaths: readonly string[]) {
    this.#integerPaths = integerPaths;
  }

  parse(): void {
    this.#value([]);
    this.#space();
    if (this.#index !== this.text.length) throw new SyntaxError("trailing JSON data");
  }

  #value(path: readonly (string | number)[]): void {
    this.#space();
    const character = this.text[this.#index];
    if (character === "{") this.#object(path);
    else if (character === "[") this.#array(path);
    else if (character === "\"") this.#string();
    else this.#primitive(path);
  }

  #object(path: readonly (string | number)[]): void {
    this.#index += 1;
    const keys = new Set<string>();
    this.#space();
    if (this.text[this.#index] === "}") { this.#index += 1; return; }
    while (true) {
      this.#space();
      if (this.text[this.#index] !== "\"") throw new SyntaxError("object key required");
      const key = this.#string();
      if (keys.has(key)) strictJsonInvalid(`payload contains duplicate key after decoding: ${key}`);
      keys.add(key);
      this.#space();
      if (this.text[this.#index] !== ":") throw new SyntaxError("colon required");
      this.#index += 1;
      this.#value([...path, key]);
      this.#space();
      const delimiter = this.text[this.#index++];
      if (delimiter === "}") return;
      if (delimiter !== ",") throw new SyntaxError("object delimiter required");
    }
  }

  #array(path: readonly (string | number)[]): void {
    this.#index += 1;
    this.#space();
    if (this.text[this.#index] === "]") { this.#index += 1; return; }
    let index = 0;
    while (true) {
      this.#value([...path, index]);
      index += 1;
      this.#space();
      const delimiter = this.text[this.#index++];
      if (delimiter === "]") return;
      if (delimiter !== ",") throw new SyntaxError("array delimiter required");
    }
  }

  #string(): string {
    const start = this.#index;
    this.#index += 1;
    while (this.#index < this.text.length) {
      const character = this.text[this.#index++];
      if (character === "\"") {
        const value = JSON.parse(this.text.slice(start, this.#index)) as string;
        assertUnicodeScalarString(value, "JSON string");
        return value;
      }
      if (character === "\\") this.#index += 1;
      else if (character !== undefined && character.charCodeAt(0) < 0x20) throw new SyntaxError("control in string");
    }
    throw new SyntaxError("unterminated string");
  }

  #primitive(path: readonly (string | number)[]): void {
    const remainder = this.text.slice(this.#index);
    const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/u.exec(remainder);
    if (match === null) throw new SyntaxError("JSON value required");
    if (this.#isIntegerPath(path) && !/^-?(?:0|[1-9]\d*)$/u.test(match[0])) {
      strictJsonInvalid(`${formatPath(path)} must use integer JSON syntax`);
    }
    this.#index += match[0].length;
  }

  #isIntegerPath(path: readonly (string | number)[]): boolean {
    const rendered = path.map(String);
    return this.#integerPaths.some((pattern) => {
      const parts = pattern.split(".");
      return parts.length === rendered.length && parts.every((part, index) =>
        part === "*" || part === rendered[index]);
    });
  }

  #space(): void {
    while (this.#index < this.text.length && /[\u0009\u000a\u000d\u0020]/u.test(this.text[this.#index]!)) this.#index += 1;
  }
}

function formatPath(path: readonly (string | number)[]): string {
  return path.length === 0 ? "payload" : path.join(".");
}

function strictJsonInvalid(message: string): never {
  throw new InfinityContextError({
    statusCode: 0, code: "memory.context_retrieval_contract_invalid", message, retryable: false,
  });
}
