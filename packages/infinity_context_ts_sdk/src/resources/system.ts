import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import type { InfinityContextCapabilities, InfinityContextHealth } from "../types.js";
import { decodeContextRetrievalCapabilitiesResponseBytes } from "../retrieval-v2.js";

export class SystemClient {
  constructor(private readonly http: RequestExecutor) {}

  health(input: RequestControls = {}): Promise<InfinityContextHealth> {
    return this.http.request<InfinityContextHealth>({
      method: "GET",
      path: "/v1/health",
      ...requestControls(input),
    });
  }

  async capabilities(input: RequestControls = {}): Promise<InfinityContextCapabilities> {
    const response = await this.http.request<Uint8Array | string>({
      method: "GET",
      path: "/v1/capabilities",
      ...requestControls(input),
      responseType: "bytes",
    });
    return decodeContextRetrievalCapabilitiesResponseBytes(response) as InfinityContextCapabilities;
  }
}
