import type { MaybePromise } from "./types.js";

/** Dynamic token providers receive the complete SDK operation signal. */
export type AuthTokenProvider =
  | string
  | null
  | undefined
  | ((signal?: AbortSignal) => MaybePromise<string | null | undefined>)
  | { getToken: (signal?: AbortSignal) => MaybePromise<string | null | undefined> };

export async function resolveAuthToken(
  provider: AuthTokenProvider,
  signal?: AbortSignal,
): Promise<string | undefined> {
  const raw =
    typeof provider === "function"
      ? await provider(signal)
      : typeof provider === "object" && provider !== null && "getToken" in provider
        ? await provider.getToken(signal)
        : provider;

  const token = typeof raw === "string" ? raw.trim() : "";
  return token.length > 0 ? token : undefined;
}
