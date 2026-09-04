import { requestControls, type RequestControls, type RequestExecutor } from "../client.js";
import {
  optionalString,
  requireAllowedKeys,
  requireArray,
  requireEnum,
  requireSha256,
  requireString,
} from "../canonical-validation.js";
import { ValueError, withoutUndefined } from "../payload.js";
import type { ApiEnvelope, JsonObject } from "../types.js";

export type CodeRepositoryProvider = "local" | "github" | "gitlab" | "bitbucket" | "manual";
export type RepositoryEvidenceKind = "normalized_remote" | "git_common_dir" | "local_registry" | "path_fallback";
export type CodeScopeLevel = "global" | "repository" | "branch" | "pull_request" | "commit" | "package" | "file" | "symbol";

export interface RepositoryEvidenceInput extends JsonObject {
  readonly kind: RepositoryEvidenceKind;
  readonly digest: string;
}

export interface InitialCodeScopeInput {
  readonly scopeLevel: CodeScopeLevel;
  readonly branch?: string;
  readonly commitSha?: string;
}

export interface ResolveCodeRepositoryInput extends RequestControls {
  readonly spaceId: string;
  readonly evidence: readonly RepositoryEvidenceInput[];
  readonly provider?: CodeRepositoryProvider;
  readonly explicitRepositoryId?: string;
  readonly allowCreate?: boolean;
  readonly safeLabel?: string;
  readonly defaultBranch?: string;
  readonly monorepoRoot?: string;
  readonly initialCodeScope?: InitialCodeScopeInput;
}

export interface RegisterCodeScopeInput extends RequestControls {
  readonly spaceId: string;
  readonly scopeLevel: CodeScopeLevel;
  readonly branch?: string;
  readonly commitSha?: string;
}

export interface ResolvedCodeRepository extends JsonObject {
  readonly repository_id: string;
  readonly space_id: string;
  readonly provider: CodeRepositoryProvider;
  readonly status: string;
  readonly version: number;
  readonly evidence: readonly RepositoryEvidenceInput[];
}

export interface CodeScopeAuthorization extends JsonObject {
  readonly authorization_id: string;
  readonly repository_id: string;
  readonly space_id: string;
  readonly code_scope_id: string;
  readonly scope_level: CodeScopeLevel;
  readonly status: string;
  readonly version: number;
  readonly created: boolean;
}

export class CodeRepositoriesClient {
  constructor(private readonly http: RequestExecutor) {}

  async resolve(input: ResolveCodeRepositoryInput): Promise<ApiEnvelope<ResolvedCodeRepository>> {
    validateResolve(input);
    return this.http.request<ApiEnvelope<ResolvedCodeRepository>>({
      method: "POST",
      path: "/v1/code-repositories/resolve",
      ...requestControls(input),
      json: withoutUndefined({
        space_id: input.spaceId,
        evidence: input.evidence,
        provider: input.provider ?? "local",
        explicit_repository_id: input.explicitRepositoryId,
        allow_create: input.allowCreate ?? false,
        safe_label: input.safeLabel,
        default_branch: input.defaultBranch,
        monorepo_root: input.monorepoRoot,
        initial_code_scope: input.initialCodeScope === undefined ? undefined : withoutUndefined({
          scope_level: input.initialCodeScope.scopeLevel,
          branch: input.initialCodeScope.branch,
          commit_sha: input.initialCodeScope.commitSha,
        }),
      }) as JsonObject,
    });
  }

  async registerScope(repositoryId: string, input: RegisterCodeScopeInput): Promise<ApiEnvelope<CodeScopeAuthorization>> {
    requireString(repositoryId, "repositoryId", 1, 80);
    validateScope(input, "registerCodeScope");
    return this.http.request<ApiEnvelope<CodeScopeAuthorization>>({
      method: "POST",
      path: `/v1/code-repositories/${repositoryId}/scopes`,
      ...requestControls(input),
      json: withoutUndefined({
        space_id: input.spaceId,
        scope_level: input.scopeLevel,
        branch: input.branch,
        commit_sha: input.commitSha,
      }),
    });
  }
}

const PROVIDERS = ["local", "github", "gitlab", "bitbucket", "manual"] as const;
const EVIDENCE_KINDS = ["normalized_remote", "git_common_dir", "local_registry", "path_fallback"] as const;
const SCOPE_LEVELS = ["global", "repository", "branch", "pull_request", "commit", "package", "file", "symbol"] as const;
const CONTROLS = ["headers", "signal", "timeoutMs"] as const;

function validateResolve(input: ResolveCodeRepositoryInput): void {
  requireAllowedKeys(input, ["spaceId", "evidence", "provider", "explicitRepositoryId", "allowCreate", "safeLabel", "defaultBranch", "monorepoRoot", "initialCodeScope", ...CONTROLS], "resolveCodeRepository");
  requireString(input.spaceId, "spaceId", 1, 80);
  requireArray(input.evidence, "evidence", 1, 8);
  for (const evidence of input.evidence) {
    requireAllowedKeys(evidence, ["kind", "digest"], "repository evidence");
    requireEnum(evidence.kind, EVIDENCE_KINDS, "evidence.kind");
    requireSha256(evidence.digest, "evidence.digest");
  }
  if (input.provider !== undefined) requireEnum(input.provider, PROVIDERS, "provider");
  optionalString(input.explicitRepositoryId, "explicitRepositoryId", 1, 80);
  optionalString(input.safeLabel, "safeLabel", 1, 160);
  optionalString(input.defaultBranch, "defaultBranch", 1, 240);
  optionalString(input.monorepoRoot, "monorepoRoot", 1, 500);
  if (input.allowCreate !== undefined && typeof input.allowCreate !== "boolean") throw new ValueError("allowCreate must be boolean");
  if (input.initialCodeScope !== undefined) validateScope(input.initialCodeScope, "initialCodeScope");
}

function validateScope(input: InitialCodeScopeInput | RegisterCodeScopeInput, label: string): void {
  const register = "spaceId" in input;
  requireAllowedKeys(input, register ? ["spaceId", "scopeLevel", "branch", "commitSha", ...CONTROLS] : ["scopeLevel", "branch", "commitSha"], label);
  if (register) requireString(input.spaceId, "spaceId", 1, 80);
  requireEnum(input.scopeLevel, SCOPE_LEVELS, "scopeLevel");
  optionalString(input.branch, "branch", 1, 240);
  if (input.commitSha !== undefined && !/^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$/u.test(input.commitSha)) {
    throw new ValueError("commitSha must be a 40 or 64 character hexadecimal digest");
  }
}
