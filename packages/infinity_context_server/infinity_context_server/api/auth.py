"""HTTP auth dependency and Core Lite scope guard."""

import hmac
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from infinity_context_core.domain.errors import MemoryForbiddenError, MemoryUnauthorizedError
from infinity_context_core.features.agent_authorization.public import (
    AgentAccessPolicy,
    AgentScopeResolutionEvidence,
    AgentScopeResolutionMethod,
    AuthorizedAgentContext,
    WorkspaceScopeClaim,
    decode_workspace_scope_claim,
)
from infinity_context_core.processes.workspace_scope_claim_verification import (
    VerifyWorkspaceScopeClaimCommand,
)

from infinity_context_server.api.dependencies import get_container
from infinity_context_server.auth_scope import (
    PathResourceRefs,
    memory_scope_matches,
    requested_memory_scope_refs,
    requested_space_refs,
    space_matches,
)
from infinity_context_server.auth_tokens import (
    MEMORY_PERMISSION_ADMIN,
    MEMORY_PERMISSION_CAPTURE,
    MEMORY_PERMISSION_DELETE,
    MEMORY_PERMISSION_DIAGNOSTICS,
    MEMORY_PERMISSION_FACT_WRITE,
    MEMORY_PERMISSION_GOVERN,
    MEMORY_PERMISSION_READ,
    MEMORY_PERMISSION_WRITE,
    ActiveServiceToken,
    get_active_db_token,
)
from infinity_context_server.composition import Container

WORKSPACE_SCOPE_CLAIM_HEADER = "X-Infinity-Workspace-Claim"
WORKSPACE_SCOPE_GRANT_HEADER = "X-Infinity-Workspace-Grant"
WORKSPACE_SCOPE_CLAIM_MAX_AGE_SECONDS = 300
WORKSPACE_SCOPE_CLAIM_FUTURE_SKEW_SECONDS = 60


async def require_service_token(
    container: Annotated[Container, Depends(get_container)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = container.settings.service_token
    if not expected:
        request.state.authenticated_actor_id = "local-server"
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise MemoryUnauthorizedError("Missing or invalid service token")
    token = authorization.removeprefix(prefix).strip()
    if token == expected:
        request.state.authenticated_actor_id = "root-service-token"
        return
    db_token = await get_active_db_token(container, token)
    if db_token is None:
        raise MemoryUnauthorizedError("Missing or invalid service token")
    if not db_token.binding_active:
        raise MemoryForbiddenError("Service token scope is no longer active")
    request.state.authenticated_actor_id = db_token.token_id
    _ensure_permission(request, db_token)
    await _ensure_scoped_token_can_access_request(container, request, db_token)
    await _ensure_memory_scope_scoped_token_can_access_request(container, request, db_token)
    _ensure_repository_token_endpoint_isolated(request, db_token)
    workspace_claim = await _verified_workspace_scope_claim(
        container=container,
        request=request,
        token=db_token,
    )
    authorized_context = _authorized_agent_context_from_token(
        db_token,
        workspace_claim=workspace_claim,
    )
    if authorized_context is not None:
        request.state.authorized_agent_context = authorized_context


async def require_strict_admin_service_token(
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Require an unscoped root or database-backed admin token, even when unset."""

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise MemoryUnauthorizedError("Missing or invalid service token")
    token = authorization.removeprefix(prefix).strip()
    if not token:
        raise MemoryUnauthorizedError("Missing or invalid service token")

    expected = container.settings.service_token
    if expected and hmac.compare_digest(token, expected):
        return
    db_token = await get_active_db_token(container, token)
    if db_token is None:
        raise MemoryUnauthorizedError("Missing or invalid service token")
    if not db_token.binding_active:
        raise MemoryForbiddenError("Service token scope is no longer active")
    if MEMORY_PERMISSION_ADMIN not in db_token.permissions:
        raise MemoryForbiddenError("Service token lacks required permission")
    if db_token.space_id is not None or db_token.memory_scope_ids is not None:
        raise MemoryForbiddenError("Scoped service token cannot access unscoped endpoint")


def _ensure_permission(request: Request, token: ActiveServiceToken) -> None:
    required = _required_permission(request)
    if required is None:
        return
    if not _token_has_permission(token, required):
        raise MemoryForbiddenError("Service token lacks required permission")


def _token_has_permission(token: ActiveServiceToken, required: str) -> bool:
    if required in token.permissions or MEMORY_PERMISSION_ADMIN in token.permissions:
        return True
    legacy_write_permissions = {
        MEMORY_PERMISSION_CAPTURE,
        MEMORY_PERMISSION_FACT_WRITE,
        MEMORY_PERMISSION_GOVERN,
    }
    return (
        token.repository_id is None
        and required in legacy_write_permissions
        and MEMORY_PERMISSION_WRITE in token.permissions
    )


def get_authorized_agent_context(request: Request) -> AuthorizedAgentContext | None:
    """Return the immutable context established by service-token authentication."""

    value = getattr(request.state, "authorized_agent_context", None)
    return value if isinstance(value, AuthorizedAgentContext) else None


def get_authenticated_actor_id(request: Request) -> str | None:
    value = getattr(request.state, "authenticated_actor_id", None)
    return value if isinstance(value, str) and value.strip() else None


def _authorized_agent_context_from_token(
    token: ActiveServiceToken,
    *,
    workspace_claim: WorkspaceScopeClaim | None = None,
) -> AuthorizedAgentContext | None:
    if token.space_id is None or token.memory_scope_ids is None:
        return None
    return AuthorizedAgentContext(
        actor_id=token.token_id,
        space_id=token.space_id,
        memory_scope_ids=tuple(sorted(token.memory_scope_ids)),
        repository_id=token.repository_id,
        code_scope_id=(
            workspace_claim.code_scope_id if workspace_claim is not None else token.code_scope_id
        ),
        permissions=token.permissions,
        access_policy=(
            AgentAccessPolicy.LOCKED_PROJECT
            if token.repository_id is not None
            else AgentAccessPolicy.SCOPED
        ),
        resolution=(
            AgentScopeResolutionEvidence(
                method=workspace_claim.resolution_method,
                binding_id=workspace_claim.binding_id,
                binding_version=workspace_claim.binding_version,
                drift_status=workspace_claim.drift_status,
            )
            if workspace_claim is not None
            else AgentScopeResolutionEvidence(
                method=AgentScopeResolutionMethod.SERVER_TOKEN,
                binding_id=token.token_id,
            )
        ),
    )


async def _verified_workspace_scope_claim(
    *,
    container: Container,
    request: Request,
    token: ActiveServiceToken,
) -> WorkspaceScopeClaim | None:
    value = request.headers.get(WORKSPACE_SCOPE_CLAIM_HEADER)
    if value is None:
        if (
            token.repository_id is not None
            and token.code_scope_id is None
            and not _is_safe_unscoped_endpoint(request)
        ):
            raise MemoryForbiddenError(
                "Dynamic repository token requires a trusted workspace scope claim"
            )
        return None
    if token.repository_id is None:
        raise MemoryForbiddenError("Workspace claim requires a repository-scoped token")
    try:
        scheme, encoded, supplied_signature = value.split(".", 2)
        if scheme != "v1" or len(supplied_signature) != 64:
            raise ValueError("Invalid workspace claim envelope")
        claim = decode_workspace_scope_claim(encoded)
    except (UnicodeError, ValueError) as exc:
        raise MemoryForbiddenError("Invalid workspace scope claim") from exc
    binding_grant = request.headers.get(WORKSPACE_SCOPE_GRANT_HEADER)
    if binding_grant is None or not binding_grant.startswith("wg_") or len(binding_grant) > 160:
        raise MemoryForbiddenError("Workspace scope claim requires a binding grant")
    return await container.workspace_scope_claim_verification.execute(
        VerifyWorkspaceScopeClaimCommand(
            claim=claim,
            signed_value=f"{scheme}.{encoded}",
            supplied_signature=supplied_signature,
            binding_grant=binding_grant,
            token_space_id=token.space_id or "",
            token_repository_id=token.repository_id,
            token_code_scope_id=token.code_scope_id,
            now_epoch_seconds=int(container.clock.now().timestamp()),
        )
    )


def _ensure_repository_token_endpoint_isolated(
    request: Request,
    token: ActiveServiceToken,
) -> None:
    """Fail closed until each endpoint consumes AuthorizedAgentContext itself."""

    if token.repository_id is None:
        return
    method = request.method.upper()
    path = request.url.path
    fact_resource = path.removeprefix("/v1/facts/")
    is_single_fact_resource = (
        path.startswith("/v1/facts/") and bool(fact_resource) and "/" not in fact_resource
    )
    is_safe_fact_read = method == "GET" and (
        path == "/v1/facts"
        or is_single_fact_resource
        or (
            path.startswith("/v1/facts/")
            and path.endswith(("/versions", "/related", "/relations"))
            and fact_resource.count("/") == 1
        )
    )
    allowed = (
        (method == "GET" and path == "/v1/capabilities")
        or (method == "POST" and path in {"/v1/context", "/v1/search"})
        or (method == "POST" and path == "/v1/context/benchmark-search")
        or (method == "POST" and path == "/v1/captures")
        or (method == "POST" and path == "/v1/facts")
        or is_safe_fact_read
        or (method in {"PATCH", "DELETE"} and is_single_fact_resource)
        or (
            method == "POST"
            and path.startswith("/v1/facts/")
            and path.endswith(("/confirm", "/end-validity", "/supersede", "/dispute"))
        )
        or (method == "POST" and path == "/v1/facts/reinstate-supersession")
    )
    if not allowed:
        raise MemoryForbiddenError(
            "Repository-scoped token cannot access an endpoint without repository isolation"
        )


def _required_permission(request: Request) -> str | None:
    path = request.url.path
    method = request.method.upper()

    if path == "/v1/capabilities":
        return MEMORY_PERMISSION_READ

    if path.startswith("/v1/internal/memory-comparison/runs"):
        return MEMORY_PERMISSION_ADMIN

    if path in {
        "/v1/diagnostics/derived-evidence/qdrant/delete",
        "/v1/diagnostics/derived-evidence/graphiti/delete",
    }:
        return MEMORY_PERMISSION_ADMIN

    if path.startswith("/v1/diagnostics"):
        return MEMORY_PERMISSION_DIAGNOSTICS

    if path.startswith("/v1/export"):
        return MEMORY_PERMISSION_ADMIN

    if path in {"/v1/context", "/v1/search"}:
        return MEMORY_PERMISSION_READ

    if path.startswith("/api/v1/interview-memory"):
        return _legacy_required_permission(path, method)

    if path == "/v1/episodes":
        return MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/captures"):
        if method == "DELETE":
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_CAPTURE

    if (
        path.startswith("/v1/assets")
        or path.startswith("/v1/asset-extractions")
        or path.startswith("/v1/extraction-artifacts")
    ):
        if method == "DELETE":
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/context-links"):
        if method == "DELETE":
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/context-link-suggestions"):
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_WRITE

    if path == "/v1/link-suggestions":
        return MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/anchors"):
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/thread-memory"):
        if method == "DELETE" or path.endswith("/delete"):
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ

    if path.startswith("/v1/facts"):
        return _fact_required_permission(path, method)

    if path.startswith("/v1/documents"):
        return _document_required_permission(method)

    if path.startswith("/v1/suggestions"):
        return _suggestion_required_permission(path, method)

    if path == "/v1/spaces":
        return MEMORY_PERMISSION_WRITE if method == "POST" else MEMORY_PERMISSION_READ

    if path.startswith("/v1/users"):
        return MEMORY_PERMISSION_WRITE if method == "POST" else MEMORY_PERMISSION_READ

    if path.startswith("/v1/spaces/") and "/memberships" in path:
        return MEMORY_PERMISSION_WRITE if method == "POST" else MEMORY_PERMISSION_READ

    if path.startswith("/v1/memory-scopes"):
        return _memory_scope_required_permission(method)

    return MEMORY_PERMISSION_READ


def _legacy_required_permission(path: str, method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if path.endswith("/context") or path.endswith("/status"):
        return MEMORY_PERMISSION_READ
    return MEMORY_PERMISSION_WRITE


def _fact_required_permission(path: str, method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if method == "POST" and (
        path == "/v1/facts/reinstate-supersession"
        or path.endswith(("/confirm", "/end-validity", "/supersede", "/dispute"))
    ):
        return MEMORY_PERMISSION_GOVERN
    if method in {"POST", "PATCH", "PUT"}:
        return MEMORY_PERMISSION_FACT_WRITE
    return MEMORY_PERMISSION_READ


def _document_required_permission(method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if method in {"POST", "PATCH", "PUT"}:
        return MEMORY_PERMISSION_WRITE
    return MEMORY_PERMISSION_READ


def _suggestion_required_permission(path: str, method: str) -> str:
    if method == "GET":
        return MEMORY_PERMISSION_READ
    if path in {"/v1/suggestions", "/v1/suggestions/batch"}:
        return MEMORY_PERMISSION_CAPTURE
    return MEMORY_PERMISSION_GOVERN


def _memory_scope_required_permission(method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if method in {"POST", "PATCH", "PUT"}:
        return MEMORY_PERMISSION_WRITE
    return MEMORY_PERMISSION_READ


async def _ensure_scoped_token_can_access_request(
    container: Container,
    request: Request,
    token: ActiveServiceToken,
) -> None:
    if token.space_id is None:
        return
    if request.url.path.startswith("/v1/internal/memory-comparison/runs"):
        raise MemoryForbiddenError("Scoped service token cannot access unscoped endpoint")
    if _is_safe_unscoped_endpoint(request):
        return

    requested_spaces = await _requested_space_refs(container, request)
    if not requested_spaces:
        raise MemoryForbiddenError("Scoped service token cannot access unscoped endpoint")

    for requested_space in requested_spaces:
        if not await space_matches(container, token.space_id, requested_space):
            raise MemoryForbiddenError("Scoped service token cannot access requested space")


async def _ensure_memory_scope_scoped_token_can_access_request(
    container: Container,
    request: Request,
    token: ActiveServiceToken,
) -> None:
    if token.memory_scope_ids is None:
        return
    if request.url.path.startswith("/v1/internal/memory-comparison/runs"):
        raise MemoryForbiddenError(
            "MemoryScope-scoped service token cannot access unscoped endpoint"
        )
    if _is_safe_unscoped_endpoint(request):
        return

    requested_memory_scopes = await _requested_memory_scope_refs(container, request)
    if not requested_memory_scopes:
        raise MemoryForbiddenError(
            "MemoryScope-scoped service token cannot access unscoped endpoint"
        )

    for requested_memory_scope in requested_memory_scopes:
        matched = False
        for token_memory_scope in token.memory_scope_ids:
            if await memory_scope_matches(
                container,
                token_memory_scope,
                requested_memory_scope,
                space_scope=token.space_id,
            ):
                matched = True
                break
        if not matched:
            raise MemoryForbiddenError(
                "MemoryScope-scoped service token cannot access requested memory_scope"
            )


def _is_safe_unscoped_endpoint(request: Request) -> bool:
    return request.method.upper() == "GET" and request.url.path == "/v1/capabilities"


async def _requested_space_refs(container: Container, request: Request) -> set[str]:
    query_space = request.query_params.get("space_id")
    query_space_slug = request.query_params.get("space_slug")

    body = await _json_body(request)
    body_space = body.get("space_id")
    body_slug = body.get("space_slug") or body.get("slug")

    path_params = request.path_params
    return await requested_space_refs(
        container,
        query_space=query_space,
        query_space_slug=query_space_slug,
        body_space=body_space if isinstance(body_space, str) and body_space else None,
        body_space_slug=(
            body_slug
            if isinstance(body_slug, str)
            and body_slug
            and (
                request.url.path == "/v1/spaces"
                or (
                    request.url.path.startswith("/v1/spaces/")
                    and "/memberships" in request.url.path
                )
                or request.url.path in {"/v1/context", "/v1/search", "/v1/episodes"}
                or request.url.path.startswith("/v1/facts")
                or request.url.path.startswith("/v1/assets")
                or request.url.path.startswith("/v1/asset-extractions")
                or request.url.path.startswith("/v1/extraction-artifacts")
                or request.url.path.startswith("/v1/captures")
                or request.url.path.startswith("/v1/context-links")
                or request.url.path.startswith("/v1/context-link-suggestions")
                or request.url.path.startswith("/v1/documents")
                or request.url.path.startswith("/v1/anchors")
                or request.url.path == "/v1/link-suggestions"
                or request.url.path.startswith("/v1/suggestions")
                or request.url.path.startswith("/v1/thread-memory")
                or request.url.path.startswith("/v1/export")
            )
            else None
        ),
        path_refs=PathResourceRefs(
            space_id=_path_param(path_params, "space_id"),
            anchor_id=(
                _path_param(path_params, "anchor_id")
                or _path_param(path_params, "source_anchor_id")
            ),
            fact_id=_path_param(path_params, "fact_id"),
            document_id=_path_param(path_params, "document_id"),
            suggestion_id=_path_param(path_params, "suggestion_id"),
            asset_id=_path_param(path_params, "asset_id"),
            asset_extraction_job_id=_path_param(path_params, "job_id"),
            extraction_artifact_id=_path_param(path_params, "artifact_id"),
            context_link_id=_path_param(path_params, "context_link_id"),
            context_link_suggestion_id=_path_param(
                path_params,
                "context_link_suggestion_id",
            ),
            memory_scope_id=_path_param(path_params, "memory_scope_id"),
        ),
        include_default_legacy_space=request.url.path.startswith("/api/v1/interview-memory"),
    )


async def _requested_memory_scope_refs(container: Container, request: Request) -> set[str]:
    query_memory_scope = request.query_params.get("memory_scope_id")
    query_memory_scope_external_ref = request.query_params.get("memory_scope_external_ref")

    body = await _json_body(request)
    body_memory_scope = body.get("memory_scope_id")
    body_memory_scope_ids = body.get("memory_scope_ids")
    body_memory_scope_external_ref = body.get("memory_scope_external_ref") or body.get(
        "external_ref"
    )
    body_memory_scope_external_refs = body.get("memory_scope_external_refs")

    path_params = request.path_params
    return await requested_memory_scope_refs(
        container,
        query_memory_scope=query_memory_scope,
        query_memory_scope_external_ref=query_memory_scope_external_ref,
        body_memory_scope=body_memory_scope
        if isinstance(body_memory_scope, str) and body_memory_scope
        else None,
        body_memory_scope_ids=(
            tuple(
                memory_scope_id
                for memory_scope_id in body_memory_scope_ids
                if isinstance(memory_scope_id, str)
            )
            if isinstance(body_memory_scope_ids, list)
            else ()
        ),
        body_memory_scope_external_ref=(
            body_memory_scope_external_ref
            if (
                request.url.path == "/v1/memory-scopes"
                or (
                    request.url.path.startswith("/v1/spaces/")
                    and "/memberships" in request.url.path
                )
                or request.url.path in {"/v1/context", "/v1/search", "/v1/episodes"}
                or request.url.path.startswith("/v1/facts")
                or request.url.path.startswith("/v1/assets")
                or request.url.path.startswith("/v1/asset-extractions")
                or request.url.path.startswith("/v1/extraction-artifacts")
                or request.url.path.startswith("/v1/captures")
                or request.url.path.startswith("/v1/context-links")
                or request.url.path.startswith("/v1/context-link-suggestions")
                or request.url.path.startswith("/v1/documents")
                or request.url.path.startswith("/v1/anchors")
                or request.url.path == "/v1/link-suggestions"
                or request.url.path.startswith("/v1/suggestions")
                or request.url.path.startswith("/v1/thread-memory")
                or request.url.path.startswith("/v1/export")
            )
            and isinstance(body_memory_scope_external_ref, str)
            and body_memory_scope_external_ref
            else None
        ),
        body_memory_scope_external_refs=(
            tuple(ref for ref in body_memory_scope_external_refs if isinstance(ref, str))
            if isinstance(body_memory_scope_external_refs, list)
            else ()
        ),
        path_refs=PathResourceRefs(
            space_id=_path_param(path_params, "space_id"),
            anchor_id=(
                _path_param(path_params, "anchor_id")
                or _path_param(path_params, "source_anchor_id")
            ),
            fact_id=_path_param(path_params, "fact_id"),
            document_id=_path_param(path_params, "document_id"),
            suggestion_id=_path_param(path_params, "suggestion_id"),
            asset_id=_path_param(path_params, "asset_id"),
            asset_extraction_job_id=_path_param(path_params, "job_id"),
            extraction_artifact_id=_path_param(path_params, "artifact_id"),
            context_link_id=_path_param(path_params, "context_link_id"),
            context_link_suggestion_id=_path_param(
                path_params,
                "context_link_suggestion_id",
            ),
            memory_scope_id=_path_param(path_params, "memory_scope_id"),
        ),
        include_default_legacy_memory_scope=request.url.path.startswith("/api/v1/interview-memory"),
    )


async def _json_body(request: Request) -> dict[str, Any]:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return {}
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _path_param(path_params: dict[str, Any], key: str) -> str | None:
    value = path_params.get(key)
    return value if isinstance(value, str) and value else None
