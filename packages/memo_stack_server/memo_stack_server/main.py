"""FastAPI app entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from memo_stack_adapters.postgres import create_schema
from memo_stack_core.domain.errors import MemoryError

from memo_stack_server.api.errors import (
    internal_error_handler,
    memory_error_handler,
    request_validation_error_handler,
)
from memo_stack_server.api.v1 import router as v1_router
from memo_stack_server.api.v1.health import router as root_health_router
from memo_stack_server.composition import build_container
from memo_stack_server.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if container.settings.auto_create_schema:
            await create_schema(container.engine)
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(title="Memo Stack", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_exception_handler(MemoryError, memory_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
    app.include_router(root_health_router)
    app.include_router(v1_router)
    if container.settings.legacy_client_enabled:
        from memo_stack_server.api.legacy_client import router as legacy_client_router

        app.include_router(legacy_client_router)
    return app


app = create_app()


def main() -> None:
    settings = Settings()
    settings.validate_for_startup()
    uvicorn.run(
        "memo_stack_server.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
