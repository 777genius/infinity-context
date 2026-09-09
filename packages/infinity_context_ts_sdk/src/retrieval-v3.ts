/** Explicit thread selector wire seam. V2 parsers are deliberately unchanged. */
import type { JsonObject } from "./types.js";
import type { RetrievalCapability, RetrieveContextInput, RetrieveContextResponse } from "./retrieval-types.js";
import {
  decodeRetrievalCapability, decodeRetrieveContextResponseForPayload,
  retrievalRequestPayload, RESPONSE_INTEGER_PATHS,
} from "./retrieval.js";
import { decodeRetrievalJson } from "./retrieval-json.js";
import { exactObject, literal, nullableOpaque, opaque, fail, freeze } from "./retrieval-validation.js";

export const CONTEXT_RETRIEVAL_V3_CONTRACT = "context-retrieval.v3" as const;
export const RETRIEVAL_V3_ENDPOINT = "/v1/context/retrieve-v3" as const;
export type RetrievalThreadSelector = { readonly mode: "exact"; readonly id: string | null }
  | { readonly mode: "any" };
export interface RetrieveContextV3Input extends Omit<RetrieveContextInput, "contractVersion" | "scope"> {
  readonly contractVersion: typeof CONTEXT_RETRIEVAL_V3_CONTRACT;
  readonly scope: {
    readonly spaceId: string;
    readonly memoryScopeId: string;
    readonly thread: RetrievalThreadSelector;
  };
}
export interface RetrievalV3Capability extends Omit<RetrievalCapability, "contract_version" | "endpoint"> {
  readonly contract_version: typeof CONTEXT_RETRIEVAL_V3_CONTRACT;
  readonly endpoint: typeof RETRIEVAL_V3_ENDPOINT;
}
export interface RetrieveContextV3Response extends Omit<RetrieveContextResponse, "contract_version"> {
  readonly contract_version: typeof CONTEXT_RETRIEVAL_V3_CONTRACT;
}

export function retrievalV3RequestPayload(input: RetrieveContextV3Input): JsonObject {
  literal(input.contractVersion, CONTEXT_RETRIEVAL_V3_CONTRACT, "input.contractVersion");
  const scope = exactObject(input.scope, ["spaceId", "memoryScopeId", "thread"], "input.scope");
  const thread = exactObject(scope.thread, undefined, "input.scope.thread");
  if (thread.mode !== "any" && thread.mode !== "exact") fail("thread.mode is unsupported");
  exactObject(thread, thread.mode === "any" ? ["mode"] : ["mode", "id"], "thread");
  const id = thread.mode === "exact" ? nullableOpaque(thread.id, "thread.id") : null;
  const spaceId = opaque(scope.spaceId, "scope.spaceId");
  const memoryScopeId = opaque(scope.memoryScopeId, "scope.memoryScopeId");
  const common = retrievalRequestPayload({
    ...input, contractVersion: "context-retrieval.v2", scope: { spaceId, memoryScopeId, threadId: id },
  });
  const selector: JsonObject = thread.mode === "any" ? { mode: "any" } : { mode: "exact", id };
  return freeze({ ...common, contract_version: CONTEXT_RETRIEVAL_V3_CONTRACT,
    scope: { spaceId, memoryScopeId, thread: selector },
  });
}

/** Structural validation; execution separately verifies the canonical SHA-256. */
export function decodeRetrievalV3Capability(value: unknown): RetrievalV3Capability {
  const root = exactObject(value, undefined, "capability");
  literal(root.contract_version, CONTEXT_RETRIEVAL_V3_CONTRACT, "capability.contract_version");
  literal(root.endpoint, RETRIEVAL_V3_ENDPOINT, "capability.endpoint");
  const common = decodeRetrievalCapability({ ...root,
    contract_version: "context-retrieval.v2", endpoint: "/v1/context/retrieve" });
  return freeze({ ...common, contract_version: CONTEXT_RETRIEVAL_V3_CONTRACT, endpoint: RETRIEVAL_V3_ENDPOINT });
}

export function commonV3Capability(value: RetrievalV3Capability): RetrievalCapability {
  return decodeRetrievalCapability({ ...value, contract_version: "context-retrieval.v2", endpoint: "/v1/context/retrieve" });
}

export function decodeRetrieveContextV3ResponseBytes(
  body: Uint8Array | string, request: JsonObject, capability: RetrievalV3Capability,
): RetrieveContextV3Response {
  const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
  const root = exactObject(decodeRetrievalJson(bytes, RESPONSE_INTEGER_PATHS), undefined, "response");
  literal(root.contract_version, CONTEXT_RETRIEVAL_V3_CONTRACT, "response.contract_version");
  const common = decodeRetrieveContextResponseForPayload(
    { ...root, contract_version: "context-retrieval.v2" },
    { ...request, contract_version: "context-retrieval.v2" }, commonV3Capability(capability), bytes.byteLength,
  );
  return freeze({ ...common, contract_version: CONTEXT_RETRIEVAL_V3_CONTRACT });
}
