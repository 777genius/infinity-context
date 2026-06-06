"""HTTP auth dependency and Core Lite scope guard."""

from typing import Annotated, Any

from fastapi import Depends, Header, Request
from memo_stack_core.domain.errors import MemoryForbiddenError, MemoryUnauthorizedError

from memo_stack_server.api.dependencies import get_container
from memo_stack_server.auth_scope import (
    PathResourceRefs,
    profile_matches,
    requested_profile_refs,
    requested_space_refs,
    space_matches,
)
from memo_stack_server.auth_tokens import (
    MEMORY_PERMISSION_ADMIN,
    MEMORY_PERMISSION_DELETE,
    MEMORY_PERMISSION_DIAGNOSTICS,
    MEMORY_PERMISSION_READ,
    MEMORY_PERMISSION_WRITE,
    ActiveServiceToken,
    get_active_db_token,
)
from memo_stack_server.composition import Container


async def require_service_token(
    container: Annotated[Container, Depends(get_container)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = container.settings.service_token
    if not expected:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise MemoryUnauthorizedError("Missing or invalid service token")
    token = authorization.removeprefix(prefix).strip()
    if token == expected:
        return
    db_token = await get_active_db_token(container, token)
    if db_token is None:
        raise MemoryUnauthorizedError("Missing or invalid service token")
    _ensure_permission(request, db_token)
    await _ensure_scoped_token_can_access_request(container, request, db_token)
    await _ensure_profile_scoped_token_can_access_request(container, request, db_token)


def _ensure_permission(request: Request, token: ActiveServiceToken) -> None:
    required = _required_permission(request)
    if required is None:
        return
    if required not in token.permissions and MEMORY_PERMISSION_ADMIN not in token.permissions:
        raise MemoryForbiddenError("Service token lacks required permission")


def _required_permission(request: Request) -> str | None:
    path = request.url.path
    method = request.method.upper()

    if path == "/v1/capabilities":
        return MEMORY_PERMISSION_READ

    if path.startswith("/v1/diagnostics"):
        return MEMORY_PERMISSION_DIAGNOSTICS

    if path in {"/v1/context", "/v1/search"}:
        return MEMORY_PERMISSION_READ

    if path.startswith("/api/v1/interview-memory"):
        return _legacy_required_permission(path, method)

    if path == "/v1/episodes":
        return MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/captures"):
        if method == "DELETE":
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ if method == "GET" else MEMORY_PERMISSION_WRITE

    if path.startswith("/v1/thread-memory"):
        if method == "DELETE" or path.endswith("/delete"):
            return MEMORY_PERMISSION_DELETE
        return MEMORY_PERMISSION_READ

    if path.startswith("/v1/facts"):
        return _fact_required_permission(method)

    if path.startswith("/v1/documents"):
        return _document_required_permission(method)

    if path.startswith("/v1/suggestions"):
        return _suggestion_required_permission(method)

    if path == "/v1/spaces":
        return MEMORY_PERMISSION_WRITE if method == "POST" else MEMORY_PERMISSION_READ

    if path == "/v1/profiles":
        return MEMORY_PERMISSION_WRITE if method == "POST" else MEMORY_PERMISSION_READ

    return MEMORY_PERMISSION_READ


def _legacy_required_permission(path: str, method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if path.endswith("/context") or path.endswith("/status"):
        return MEMORY_PERMISSION_READ
    return MEMORY_PERMISSION_WRITE


def _fact_required_permission(method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if method in {"POST", "PATCH", "PUT"}:
        return MEMORY_PERMISSION_WRITE
    return MEMORY_PERMISSION_READ


def _document_required_permission(method: str) -> str:
    if method == "DELETE":
        return MEMORY_PERMISSION_DELETE
    if method in {"POST", "PATCH", "PUT"}:
        return MEMORY_PERMISSION_WRITE
    return MEMORY_PERMISSION_READ


def _suggestion_required_permission(method: str) -> str:
    if method == "GET":
        return MEMORY_PERMISSION_READ
    return MEMORY_PERMISSION_WRITE


async def _ensure_scoped_token_can_access_request(
    container: Container,
    request: Request,
    token: ActiveServiceToken,
) -> None:
    if token.space_id is None:
        return
    if _is_safe_unscoped_endpoint(request):
        return

    requested_spaces = await _requested_space_refs(container, request)
    if not requested_spaces:
        raise MemoryForbiddenError("Scoped service token cannot access unscoped endpoint")

    for requested_space in requested_spaces:
        if not await space_matches(container, token.space_id, requested_space):
            raise MemoryForbiddenError("Scoped service token cannot access requested space")


async def _ensure_profile_scoped_token_can_access_request(
    container: Container,
    request: Request,
    token: ActiveServiceToken,
) -> None:
    if token.profile_ids is None:
        return
    if _is_safe_unscoped_endpoint(request):
        return

    requested_profiles = await _requested_profile_refs(container, request)
    if not requested_profiles:
        raise MemoryForbiddenError("Profile-scoped service token cannot access unscoped endpoint")

    for requested_profile in requested_profiles:
        matched = False
        for token_profile in token.profile_ids:
            if await profile_matches(
                container,
                token_profile,
                requested_profile,
                space_scope=token.space_id,
            ):
                matched = True
                break
        if not matched:
            raise MemoryForbiddenError(
                "Profile-scoped service token cannot access requested profile"
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
                or request.url.path in {"/v1/context", "/v1/search", "/v1/episodes"}
                or request.url.path.startswith("/v1/facts")
                or request.url.path.startswith("/v1/captures")
                or request.url.path.startswith("/v1/documents")
                or request.url.path.startswith("/v1/suggestions")
                or request.url.path.startswith("/v1/thread-memory")
            )
            else None
        ),
        path_refs=PathResourceRefs(
            fact_id=_path_param(path_params, "fact_id"),
            document_id=_path_param(path_params, "document_id"),
            suggestion_id=_path_param(path_params, "suggestion_id"),
            profile_id=_path_param(path_params, "profile_id"),
        ),
        include_default_legacy_space=request.url.path.startswith("/api/v1/interview-memory"),
    )


async def _requested_profile_refs(container: Container, request: Request) -> set[str]:
    query_profile = request.query_params.get("profile_id")
    query_profile_external_ref = request.query_params.get("profile_external_ref")

    body = await _json_body(request)
    body_profile = body.get("profile_id")
    body_profile_ids = body.get("profile_ids")
    body_profile_external_ref = body.get("profile_external_ref") or body.get("external_ref")
    body_profile_external_refs = body.get("profile_external_refs")

    path_params = request.path_params
    return await requested_profile_refs(
        container,
        query_profile=query_profile,
        query_profile_external_ref=query_profile_external_ref,
        body_profile=body_profile if isinstance(body_profile, str) and body_profile else None,
        body_profile_ids=(
            tuple(profile_id for profile_id in body_profile_ids if isinstance(profile_id, str))
            if isinstance(body_profile_ids, list)
            else ()
        ),
        body_profile_external_ref=(
            body_profile_external_ref
            if (
                request.url.path == "/v1/profiles"
                or request.url.path in {"/v1/context", "/v1/search", "/v1/episodes"}
                or request.url.path.startswith("/v1/facts")
                or request.url.path.startswith("/v1/captures")
                or request.url.path.startswith("/v1/documents")
                or request.url.path.startswith("/v1/suggestions")
                or request.url.path.startswith("/v1/thread-memory")
            )
            and isinstance(body_profile_external_ref, str)
            and body_profile_external_ref
            else None
        ),
        body_profile_external_refs=(
            tuple(ref for ref in body_profile_external_refs if isinstance(ref, str))
            if isinstance(body_profile_external_refs, list)
            else ()
        ),
        path_refs=PathResourceRefs(
            fact_id=_path_param(path_params, "fact_id"),
            document_id=_path_param(path_params, "document_id"),
            suggestion_id=_path_param(path_params, "suggestion_id"),
            profile_id=_path_param(path_params, "profile_id"),
        ),
        include_default_legacy_profile=request.url.path.startswith("/api/v1/interview-memory"),
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
