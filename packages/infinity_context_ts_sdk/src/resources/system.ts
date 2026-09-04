import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import type { InfinityContextCapabilities, InfinityContextHealth } from "../types.js";
import { decodeContextRetrievalCapabilitiesResponseBytes } from "../retrieval.js";

/** Capabilities are metadata, so 256 KiB is a conservative hard response ceiling. */
export const CAPABILITIES_MAX_RESPONSE_BYTES = 256 * 1024;

export class SystemClient {
  constructor(private readonly http: RequestExecutor) {}

  health(input: RequestControls = {}): Promise<InfinityContextHealth> {
    return this.http.request<InfinityContextHealth>({
      method: "GET",
      path: "/v1/health",
      expectedStatuses: [200],
      ...requestControls(input),
    });
  }

  async capabilities(input: RequestControls = {}): Promise<InfinityContextCapabilities> {
    const response = await this.http.request<Uint8Array | string>({
      method: "GET",
      path: "/v1/capabilities",
      expectedStatuses: [200],
      ...requestControls(input),
      responseType: "bytes",
      requireJsonResponse: true,
      maxResponseBytes: CAPABILITIES_MAX_RESPONSE_BYTES,
    });
    return decodeContextRetrievalCapabilitiesResponseBytes(response) as InfinityContextCapabilities;
  }
}
