import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import { InfinityContextError } from "../errors.js";
import { scopeQuery, ValueError, withoutUndefined, type SingleScopeInput } from "../payload.js";
import type {
  ApiEnvelope,
  AssetExtractionDetails,
  AssetExtractionJobRecord,
  AssetRecord,
  JsonObject,
} from "../types.js";

export type AssetExtractionListInput = RequestControls & {
  readonly status?: string | null;
  readonly limit?: number;
};

export type AssetExtractionTerminalStatus = "succeeded" | "failed" | "canceled" | "unsupported" | "stale" | (string & {});

export interface WaitAssetExtractionInput extends RequestControls {
  readonly pollIntervalMs?: number;
  readonly maxAttempts?: number;
  readonly terminalStatuses?: readonly AssetExtractionTerminalStatus[];
  readonly failureStatuses?: readonly AssetExtractionTerminalStatus[];
  readonly throwOnFailure?: boolean;
  readonly sleep?: (ms: number) => Promise<void>;
}

export class AssetsClient {
  constructor(private readonly http: RequestExecutor) {}

  uploadAsset(input: SingleScopeInput & RequestControls & {
    readonly filename: string;
    readonly content: BodyInit;
    readonly contentType?: string;
    readonly classification?: string;
    readonly extract?: boolean;
    readonly parserProfile?: string;
  }): Promise<ApiEnvelope<AssetRecord>> {
    return this.http.request<ApiEnvelope<AssetRecord>>({
      method: "POST",
      path: "/v1/assets",
      ...requestControls(input),
      params: withoutUndefined({
        ...scopeQuery(input),
        filename: input.filename,
        content_type: input.contentType,
        classification: input.classification ?? "unknown",
        extract: input.extract ?? false,
        parser_profile: input.parserProfile,
      }),
      bytes: input.content,
      contentType: input.contentType,
    });
  }

  listAssets(input: SingleScopeInput & RequestControls & {
    readonly status?: string | null;
    readonly limit?: number;
  }): Promise<ApiEnvelope<AssetRecord[]>> {
    return this.http.request<ApiEnvelope<AssetRecord[]>>({
      method: "GET",
      path: "/v1/assets",
      ...requestControls(input),
      params: withoutUndefined({
        ...scopeQuery(input),
        status: input.status === undefined ? "stored" : input.status,
        limit: input.limit ?? 50,
      }),
    });
  }

  getAsset(assetId: string, input: RequestControls = {}): Promise<ApiEnvelope<AssetRecord>> {
    return this.http.request<ApiEnvelope<AssetRecord>>({
      method: "GET",
      path: `/v1/assets/${assetId}`,
      ...requestControls(input),
    });
  }

  deleteAsset(assetId: string, input: RequestControls = {}): Promise<ApiEnvelope<AssetRecord>> {
    return this.http.request<ApiEnvelope<AssetRecord>>({
      method: "DELETE",
      path: `/v1/assets/${assetId}`,
      ...requestControls(input),
    });
  }

  downloadAsset(assetId: string, input: RequestControls = {}): Promise<Uint8Array> {
    return this.http.request<Uint8Array>({
      method: "GET",
      path: `/v1/assets/${assetId}/download`,
      ...requestControls(input),
      responseType: "bytes",
    });
  }

  requestAssetExtraction(
    assetId: string,
    input: { readonly parserProfile?: string } & RequestControls = {},
  ): Promise<ApiEnvelope<AssetExtractionJobRecord>> {
    return this.http.request<ApiEnvelope<AssetExtractionJobRecord>>({
      method: "POST",
      path: `/v1/assets/${assetId}/extractions`,
      ...requestControls(input),
      params: withoutUndefined({ parser_profile: input.parserProfile }),
    });
  }

  listAssetExtractions(
    assetId: string,
    input: AssetExtractionListInput = {},
  ): Promise<ApiEnvelope<AssetExtractionJobRecord[]>> {
    return this.http.request<ApiEnvelope<AssetExtractionJobRecord[]>>({
      method: "GET",
      path: `/v1/assets/${assetId}/extractions`,
      ...requestControls(input),
      params: extractionListQuery(input),
    });
  }

  listScopeAssetExtractions(
    input: SingleScopeInput & AssetExtractionListInput,
  ): Promise<ApiEnvelope<AssetExtractionJobRecord[]>> {
    return this.http.request<ApiEnvelope<AssetExtractionJobRecord[]>>({
      method: "GET",
      path: "/v1/asset-extractions",
      ...requestControls(input),
      params: withoutUndefined({
        ...scopeQuery(input),
        status: input.status,
        limit: input.limit ?? 50,
      }),
    });
  }

  getAssetExtraction(jobId: string, input: RequestControls = {}): Promise<ApiEnvelope<AssetExtractionDetails>> {
    return this.http.request<ApiEnvelope<AssetExtractionDetails>>({
      method: "GET",
      path: `/v1/asset-extractions/${jobId}`,
      ...requestControls(input),
    });
  }

  async waitForAssetExtraction(
    jobId: string,
    input: WaitAssetExtractionInput = {},
  ): Promise<ApiEnvelope<AssetExtractionDetails>> {
    const maxAttempts = normalizedMaxAttempts(input.maxAttempts);
    const pollIntervalMs = normalizedPollInterval(input.pollIntervalMs);
    const terminalStatuses = new Set(input.terminalStatuses ?? DEFAULT_EXTRACTION_TERMINAL_STATUSES);
    const failureStatuses = new Set(input.failureStatuses ?? DEFAULT_EXTRACTION_FAILURE_STATUSES);
    let last: ApiEnvelope<AssetExtractionDetails> | undefined;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      throwIfAborted(input.signal);
      last = await this.getAssetExtraction(jobId, input);
      if (terminalStatuses.has(last.data.status)) {
        if (input.throwOnFailure === true && failureStatuses.has(last.data.status)) {
          throw assetExtractionFailed(jobId, last.data);
        }
        return last;
      }
      if (attempt + 1 < maxAttempts) {
        await waitForNextPoll(input, pollIntervalMs);
      }
    }

    throw assetExtractionTimeout(jobId, maxAttempts, last?.data);
  }

  retryAssetExtraction(jobId: string, input: RequestControls = {}): Promise<ApiEnvelope<AssetExtractionJobRecord>> {
    return this.http.request<ApiEnvelope<AssetExtractionJobRecord>>({
      method: "POST",
      path: `/v1/asset-extractions/${jobId}/retry`,
      ...requestControls(input),
    });
  }

  cancelAssetExtraction(jobId: string, input: RequestControls = {}): Promise<ApiEnvelope<AssetExtractionJobRecord>> {
    return this.http.request<ApiEnvelope<AssetExtractionJobRecord>>({
      method: "POST",
      path: `/v1/asset-extractions/${jobId}/cancel`,
      ...requestControls(input),
    });
  }

  downloadExtractionArtifact(artifactId: string, input: RequestControls = {}): Promise<Uint8Array> {
    return this.http.request<Uint8Array>({
      method: "GET",
      path: `/v1/extraction-artifacts/${artifactId}/download`,
      ...requestControls(input),
      responseType: "bytes",
    });
  }
}

const extractionListQuery = (input: AssetExtractionListInput): JsonObject =>
  withoutUndefined({
    status: input.status,
    limit: input.limit ?? 50,
  }) as JsonObject;

const DEFAULT_EXTRACTION_TERMINAL_STATUSES = ["succeeded", "failed", "canceled", "unsupported", "stale"] as const;
const DEFAULT_EXTRACTION_FAILURE_STATUSES = ["failed", "canceled", "unsupported", "stale"] as const;

function normalizedMaxAttempts(value: number | undefined): number {
  const attempts = value ?? 30;
  if (!Number.isInteger(attempts) || attempts < 1) {
    throw new ValueError("waitForAssetExtraction maxAttempts must be an integer greater than 0");
  }
  return attempts;
}

function normalizedPollInterval(value: number | undefined): number {
  const pollIntervalMs = value ?? 1_000;
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 0) {
    throw new ValueError("waitForAssetExtraction pollIntervalMs must be a non-negative number");
  }
  return pollIntervalMs;
}

async function waitForNextPoll(input: WaitAssetExtractionInput, pollIntervalMs: number): Promise<void> {
  throwIfAborted(input.signal);
  if (pollIntervalMs === 0) {
    return;
  }
  if (input.sleep !== undefined) {
    await input.sleep(pollIntervalMs);
    throwIfAborted(input.signal);
    return;
  }
  await sleepWithSignal(pollIntervalMs, input.signal);
}

function sleepWithSignal(ms: number, signal: AbortSignal | undefined): Promise<void> {
  if (signal?.aborted === true) {
    return Promise.reject(abortError(signal.reason));
  }

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      resolve();
    }, ms);
    timeout.unref?.();

    const onAbort = () => {
      cleanup();
      reject(abortError(signal?.reason));
    };
    const cleanup = () => {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", onAbort);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted === true) {
    throw abortError(signal.reason);
  }
}

function abortError(reason: unknown): Error {
  return reason instanceof Error ? reason : new DOMException("Operation aborted", "AbortError");
}

function assetExtractionTimeout(
  jobId: string,
  maxAttempts: number,
  last: AssetExtractionDetails | undefined,
): InfinityContextError {
  return new InfinityContextError({
    statusCode: 0,
    code: "memory.asset_extraction_timeout",
    message: `Asset extraction ${jobId} did not reach a terminal status after ${maxAttempts} attempt(s)`,
    retryable: true,
    details: withoutUndefined({
      job_id: jobId,
      max_attempts: maxAttempts,
      last_status: last?.status,
      last_attempt_count: last?.attempt_count,
    }),
  });
}

function assetExtractionFailed(jobId: string, job: AssetExtractionDetails): InfinityContextError {
  return new InfinityContextError({
    statusCode: 0,
    code: job.safe_error_code ?? "memory.asset_extraction_failed",
    message: job.safe_error_message ?? `Asset extraction ${jobId} finished with status ${job.status}`,
    retryable: false,
    details: withoutUndefined({
      job_id: jobId,
      status: job.status,
      attempt_count: job.attempt_count,
      safe_error_code: job.safe_error_code,
    }),
  });
}
