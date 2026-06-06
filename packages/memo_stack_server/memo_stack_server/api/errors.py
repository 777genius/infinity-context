"""HTTP error mapping."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryError,
    MemoryForbiddenError,
    MemoryInfrastructureError,
    MemoryIngressLimitError,
    MemoryInvariantError,
    MemoryNotFoundError,
    MemoryPolicyBlockedError,
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
                "message": str(exc),
                "retryable": exc.retryable,
            }
        },
    )


async def request_validation_error_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
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
