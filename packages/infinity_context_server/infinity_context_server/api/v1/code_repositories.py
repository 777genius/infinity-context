"""Strict-admin enrollment boundary for canonical code repositories."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from infinity_context_core.features.code_identity.public import (
    CodeRepositoryProvider,
    CodeScopeDescriptor,
    CodeScopeLevel,
    RegisterCodeScopeAuthorizationCommand,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
    ResolveCodeRepositoryCommand,
)
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_strict_admin_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.composition import Container

router = APIRouter(
    prefix="/code-repositories",
    tags=["code-repositories"],
    dependencies=[Depends(require_strict_admin_service_token)],
)


class RepositoryEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RepositoryEvidenceKind
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegisterCodeScopeAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    scope_level: CodeScopeLevel
    branch: str | None = Field(default=None, min_length=1, max_length=240)
    commit_sha: str | None = Field(default=None, pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class InitialCodeScopeAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_level: CodeScopeLevel
    branch: str | None = Field(default=None, min_length=1, max_length=240)
    commit_sha: str | None = Field(default=None, pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class ResolveCodeRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    evidence: list[RepositoryEvidenceRequest] = Field(min_length=1, max_length=8)
    provider: CodeRepositoryProvider = CodeRepositoryProvider.LOCAL
    explicit_repository_id: str | None = Field(default=None, min_length=1, max_length=80)
    allow_create: bool = False
    safe_label: str | None = Field(default=None, min_length=1, max_length=160)
    default_branch: str | None = Field(default=None, min_length=1, max_length=240)
    monorepo_root: str | None = Field(default=None, min_length=1, max_length=500)
    initial_code_scope: InitialCodeScopeAuthorizationRequest | None = None


@router.post("/resolve")
async def resolve_code_repository(
    request: ResolveCodeRepositoryRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    evidence = tuple(
        RepositoryIdentityEvidence(kind=item.kind, digest=item.digest) for item in request.evidence
    )
    try:
        result = await container.code_repository_enrollment.execute(
            ResolveCodeRepositoryCommand(
                space_id=request.space_id,
                evidence=evidence,
                provider=request.provider,
                explicit_repository_id=request.explicit_repository_id,
                allow_create=request.allow_create,
                safe_label=request.safe_label,
                default_branch=request.default_branch,
                monorepo_root=request.monorepo_root,
            ),
            initial_scope=(
                CodeScopeDescriptor(
                    scope_level=request.initial_code_scope.scope_level,
                    branch=request.initial_code_scope.branch,
                    commit_sha=request.initial_code_scope.commit_sha,
                )
                if request.initial_code_scope is not None
                else None
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    repository = result.repository
    return {
        "data": {
            "repository_id": repository.repository_id,
            "space_id": repository.space_id,
            "provider": repository.provider.value,
            "safe_label": repository.safe_label,
            "default_branch": repository.default_branch,
            "monorepo_root": repository.monorepo_root,
            "status": repository.status.value,
            "version": repository.version,
            "resolution_method": result.resolution_method,
            "binding_id": result.binding_id,
            "binding_version": result.binding_version,
            "binding_grant": result.binding_grant,
            "evidence": [
                {"kind": item.kind.value, "digest": item.digest} for item in repository.evidence
            ],
            "initial_code_scope": (
                {
                    "authorization_id": result.scope_authorization.authorization_id,
                    "code_scope_id": result.scope_authorization.code_scope_id,
                    "scope_level": result.scope_authorization.scope_level.value,
                    "status": result.scope_authorization.status.value,
                }
                if result.scope_authorization is not None
                else None
            ),
        }
    }


@router.post("/{repository_id}/scopes")
async def register_code_scope_authorization(
    repository_id: str,
    request: RegisterCodeScopeAuthorizationRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    try:
        scope = CodeScopeDescriptor(
            scope_level=request.scope_level,
            branch=request.branch,
            commit_sha=request.commit_sha,
        ).resolve(repository_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        result = await container.code_scope_authorization.execute(
            RegisterCodeScopeAuthorizationCommand(
                space_id=request.space_id,
                scope=scope,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    authorization = result.authorization
    return {
        "data": {
            "authorization_id": authorization.authorization_id,
            "repository_id": authorization.repository_id,
            "space_id": authorization.space_id,
            "code_scope_id": authorization.code_scope_id,
            "scope_level": authorization.scope_level.value,
            "evidence_digest": authorization.evidence_digest,
            "status": authorization.status.value,
            "version": authorization.version,
            "created": result.created,
        }
    }


__all__ = ("router",)
