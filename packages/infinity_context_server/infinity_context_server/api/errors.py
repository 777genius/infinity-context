"""HTTP error mapping."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from infinity_context_contracts.features.context_building import (
    ContextRetrievalV2ErrorDto,
    ContextRetrievalV2ErrorEnvelopeDto,
)
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryError,
    MemoryForbiddenError,
    MemoryInfrastructureError,
    MemoryIngressLimitError,
    MemoryInvariantError,
    MemoryNotFoundError,
    MemoryPolicyBlockedError,
    MemoryQuotaExceededError,
    MemoryUnauthorizedError,
    MemoryValidationError,
)

STATUS_BY_ERROR_TYPE = {
    MemoryValidationError: 400,
    MemoryConflictError: 409,
    MemoryNotFoundError: 404,
    MemoryForbiddenError: 403,
    MemoryUnauthorizedError: 401,
    MemoryPolicyBlockedError: 422,
    MemoryQuotaExceededError: 402,
    MemoryIngressLimitError: 429,
    MemoryInvariantError: 500,
    MemoryInfrastructureError: 503,
}

SAFE_PUBLIC_ERROR_BY_TYPE = {
    MemoryInvariantError: {
        "code": "memory.internal",
        "message": "Internal error",
        "retryable": True,
    },
    MemoryInfrastructureError: {
        "code": "memory.provider_unavailable",
        "message": "Provider unavailable",
        "retryable": True,
    },
}


async def memory_error_handler(_request: Request, exc: MemoryError) -> JSONResponse:
    request_path = _request.url.path if _request is not None else ""
    if request_path == "/v1/context/retrieve":
        if isinstance(exc, MemoryUnauthorizedError):
            return _retrieval_error("memory.unauthorized", "Authentication required")
        if isinstance(exc, MemoryForbiddenError):
            return _retrieval_error("memory.forbidden", "Retrieval V2 scope is forbidden")
    status_code = STATUS_BY_ERROR_TYPE.get(type(exc), 500)
    safe_error = SAFE_PUBLIC_ERROR_BY_TYPE.get(type(exc))
    if safe_error is not None:
        return JSONResponse(
            status_code=status_code,
            content={"error": safe_error},
        )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": redact_sensitive_text(str(exc)),
                "retryable": exc.retryable,
            }
        },
    )


async def request_validation_error_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    request_path = _request.url.path if _request is not None else ""
    if request_path == "/v1/context/retrieve":
        return _retrieval_error(
            "memory.context_retrieval_contract_invalid",
            "Retrieval V2 request does not match the canonical contract",
        )
    if request_path == "/v1/documents" and any(
        "retrieval_projection" in error.get("loc", ()) for error in _exc.errors()
    ):
        return _retrieval_error(
            "memory.document_projection_invalid",
            "Document retrieval projection is invalid",
        )
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "memory.validation",
                "message": "Request validation failed",
                "retryable": False,
            }
        },
    )


async def internal_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "memory.internal",
                "message": "Internal error",
                "retryable": True,
            }
        },
    )


def _retrieval_error(code: str, message: str) -> JSONResponse:
    envelope = ContextRetrievalV2ErrorEnvelopeDto(ContextRetrievalV2ErrorDto(code, message, False))
    return JSONResponse(
        status_code=envelope.http_status,
        content=envelope.to_dict(),
    )
