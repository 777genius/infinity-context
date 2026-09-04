import type { RequestControls } from "../client.js";
import { ValueError } from "../payload.js";
import type { SpacesClient } from "../resources/spaces.js";
import type { UsersClient } from "../resources/users.js";
import type { JsonObject, MemoryScopeRecord, Space, SpaceMembership, UserRecord } from "../types.js";
import {
  optional,
  requiredWorkflowText,
  safeWorkflowError,
  workflowConflict,
  workflowControls,
} from "./workflow-helpers.js";

export interface MemoryTopologyResources {
  readonly spaces: SpacesClient;
  readonly users: UsersClient;
}

export interface EnsureMemoryScopeInput {
  readonly externalRef: string;
  readonly name: string;
}

export interface EnsureMemoryUserInput {
  readonly externalRef: string;
  readonly displayName: string;
  readonly email?: string;
  readonly metadata?: JsonObject;
  readonly role?: string;
}

export interface EnsureMemoryTopologyInput extends RequestControls {
  readonly spaceSlug: string;
  readonly spaceName: string;
  readonly memoryScopes?: readonly EnsureMemoryScopeInput[];
  readonly users?: readonly EnsureMemoryUserInput[];
  readonly createMemberships?: boolean;
  readonly listLimit?: number;
}

export interface EnsureMemoryTopologyCreated {
  readonly space: boolean;
  readonly memoryScopes: readonly string[];
  readonly users: readonly string[];
  readonly memberships: readonly string[];
}

export interface EnsureMemoryTopologyDiagnostics {
  readonly listLimit: number;
  readonly warnings: readonly string[];
}

export interface EnsureMemoryTopologyResult {
  readonly space: Space;
  readonly memoryScopes: readonly MemoryScopeRecord[];
  readonly users: readonly UserRecord[];
  readonly memberships: readonly SpaceMembership[];
  readonly created: EnsureMemoryTopologyCreated;
  readonly diagnostics: EnsureMemoryTopologyDiagnostics;
}

interface EnsureWorkflowResult<TRecord> {
  readonly record: TRecord;
  readonly created: boolean;
}

export async function ensureMemoryTopology(
  resources: MemoryTopologyResources,
  input: EnsureMemoryTopologyInput,
): Promise<EnsureMemoryTopologyResult> {
  const controls = workflowControls(input);
  const listLimit = input.listLimit ?? 500;
  const warnings: string[] = [];
  const createdScopes: string[] = [];
  const createdUsers: string[] = [];
  const createdMemberships: string[] = [];

  const spaceResult = await ensureWorkflowSpace(resources, {
    ...controls,
    slug: requiredWorkflowText(input.spaceSlug, "ensureMemoryTopology requires spaceSlug"),
    name: requiredWorkflowText(input.spaceName, "ensureMemoryTopology requires spaceName"),
    listLimit,
  });

  const memoryScopes: MemoryScopeRecord[] = [];
  for (const scope of input.memoryScopes ?? []) {
    const result = await ensureWorkflowMemoryScope(resources, {
      ...controls,
      spaceId: spaceResult.record.id,
      externalRef: requiredWorkflowText(scope.externalRef, "ensureMemoryTopology scope requires externalRef"),
      name: requiredWorkflowText(scope.name, "ensureMemoryTopology scope requires name"),
      listLimit,
    });
    memoryScopes.push(result.record);
    if (result.created) {
      createdScopes.push(result.record.external_ref);
    }
  }

  const users: UserRecord[] = [];
  const memberships: SpaceMembership[] = [];
  if (input.users !== undefined && input.users.length > 0) {
    const existingUsers = await resources.users.listUsers({
      ...controls,
      limit: listLimit,
    });
    const userRecordsByExternalRef = new Map<string, UserRecord>();

    for (const user of input.users) {
      const result = await ensureWorkflowUser(resources, {
        ...controls,
        externalRef: requiredWorkflowText(user.externalRef, "ensureMemoryTopology user requires externalRef"),
        displayName: requiredWorkflowText(user.displayName, "ensureMemoryTopology user requires displayName"),
        ...optional("email", user.email),
        ...optional("metadata", user.metadata),
        listLimit,
        existingUsers: existingUsers.data,
      });
      users.push(result.record);
      userRecordsByExternalRef.set(result.record.external_ref, result.record);
      if (result.created) {
        createdUsers.push(result.record.external_ref);
      }
    }

    if (input.createMemberships ?? true) {
      const existingMemberships = await resources.users.listSpaceMemberships(spaceResult.record.id, {
        ...controls,
        limit: listLimit,
      });
      for (const user of input.users) {
        const userRecord = userRecordsByExternalRef.get(user.externalRef);
        if (userRecord === undefined) {
          continue;
        }
        const result = await ensureWorkflowMembership(resources, {
          ...controls,
          spaceId: spaceResult.record.id,
          userId: userRecord.id,
          role: user.role ?? "member",
          listLimit,
          existingMemberships: existingMemberships.data,
        });
        memberships.push(result.record);
        if (result.created) {
          createdMemberships.push(userRecord.external_ref);
        } else if (result.record.role !== (user.role ?? "member")) {
          warnings.push(`membership for ${userRecord.external_ref} exists with role ${result.record.role}`);
        }
      }
    }
  }

  return {
    space: spaceResult.record,
    memoryScopes,
    users,
    memberships,
    created: {
      space: spaceResult.created,
      memoryScopes: createdScopes,
      users: createdUsers,
      memberships: createdMemberships,
    },
    diagnostics: {
      listLimit,
      warnings,
    },
  };
}

async function ensureWorkflowSpace(
  resources: MemoryTopologyResources,
  input: { readonly slug: string; readonly name: string; readonly listLimit: number } & RequestControls,
): Promise<EnsureWorkflowResult<Space>> {
  const existing = await resources.spaces.listSpaces({ ...workflowControls(input), limit: input.listLimit });
  const found = existing.data.find((space) => space.slug === input.slug);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.spaces.createSpace({
      ...workflowControls(input),
      slug: input.slug,
      name: input.name,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw safeWorkflowError(error);
    }
    const afterConflict = await resources.spaces.listSpaces({ ...workflowControls(input), limit: input.listLimit });
    const created = afterConflict.data.find((space) => space.slug === input.slug);
    if (created === undefined) {
      throw safeWorkflowError(error);
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowMemoryScope(
  resources: MemoryTopologyResources,
  input: {
    readonly spaceId: string;
    readonly externalRef: string;
    readonly name: string;
    readonly listLimit: number;
  } & RequestControls,
): Promise<EnsureWorkflowResult<MemoryScopeRecord>> {
  const existing = await resources.spaces.listMemoryScopes({
    ...workflowControls(input),
    spaceId: input.spaceId,
    limit: input.listLimit,
  });
  const found = existing.data.find((scope) => scope.external_ref === input.externalRef);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.spaces.createMemoryScope({
      ...workflowControls(input),
      spaceId: input.spaceId,
      externalRef: input.externalRef,
      name: input.name,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw safeWorkflowError(error);
    }
    const afterConflict = await resources.spaces.listMemoryScopes({
      ...workflowControls(input),
      spaceId: input.spaceId,
      limit: input.listLimit,
    });
    const created = afterConflict.data.find((scope) => scope.external_ref === input.externalRef);
    if (created === undefined) {
      throw safeWorkflowError(error);
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowUser(
  resources: MemoryTopologyResources,
  input: {
    readonly externalRef: string;
    readonly displayName: string;
    readonly email?: string;
    readonly metadata?: JsonObject;
    readonly listLimit: number;
    readonly existingUsers: readonly UserRecord[];
  } & RequestControls,
): Promise<EnsureWorkflowResult<UserRecord>> {
  const found = input.existingUsers.find((user) => user.external_ref === input.externalRef);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.users.createUser({
      ...workflowControls(input),
      externalRef: input.externalRef,
      displayName: input.displayName,
      ...optional("email", input.email),
      ...optional("metadata", input.metadata),
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw safeWorkflowError(error);
    }
    const afterConflict = await resources.users.listUsers({ ...workflowControls(input), limit: input.listLimit });
    const created = afterConflict.data.find((user) => user.external_ref === input.externalRef);
    if (created === undefined) {
      throw safeWorkflowError(error);
    }
    return { record: created, created: false };
  }
}

async function ensureWorkflowMembership(
  resources: MemoryTopologyResources,
  input: {
    readonly spaceId: string;
    readonly userId: string;
    readonly role: string;
    readonly listLimit: number;
    readonly existingMemberships: readonly SpaceMembership[];
  } & RequestControls,
): Promise<EnsureWorkflowResult<SpaceMembership>> {
  const found = input.existingMemberships.find((membership) => membership.user_id === input.userId);
  if (found !== undefined) {
    return { record: found, created: false };
  }

  try {
    const created = await resources.users.createSpaceMembership(input.spaceId, {
      ...workflowControls(input),
      userId: input.userId,
      role: input.role,
    });
    return { record: created.data, created: true };
  } catch (error) {
    if (!workflowConflict(error)) {
      throw safeWorkflowError(error);
    }
    const afterConflict = await resources.users.listSpaceMemberships(input.spaceId, {
      ...workflowControls(input),
      limit: input.listLimit,
    });
    const created = afterConflict.data.find((membership) => membership.user_id === input.userId);
    if (created === undefined) {
      throw safeWorkflowError(error);
    }
    return { record: created, created: false };
  }
}
