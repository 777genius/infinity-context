"""FastAPI app entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from infinity_context_adapters.postgres import create_schema
from infinity_context_core.domain.errors import MemoryError

from infinity_context_server.api.errors import (
    internal_error_handler,
    memory_error_handler,
    request_validation_error_handler,
)
from infinity_context_server.api.v1 import router as v1_router
from infinity_context_server.api.v1.context_retrieval import (
    router as context_retrieval_router,
)
from infinity_context_server.api.v1.health import router as root_health_router
from infinity_context_server.composition import build_container
from infinity_context_server.config import Settings
from infinity_context_server.processes import ProjectionOutboxProcess
from infinity_context_server.web_ui import mount_web_ui

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            if container.settings.auto_create_schema:
                await create_schema(container.engine)
            await container.start_retrieval_runtime()
            try:
                await ProjectionOutboxProcess(container).reconcile_vector_tombstones(limit=100)
            except Exception:
                logger.warning("projection tombstone reconciliation deferred at startup")
            yield
        finally:
            await container.aclose()

    app = FastAPI(title="Infinity Context", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_exception_handler(MemoryError, memory_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
    app.include_router(root_health_router)
    app.include_router(v1_router)
    if container.locator_retrieval is not None:
        app.include_router(context_retrieval_router, prefix="/v1")
    if container.settings.legacy_client_enabled:
        from infinity_context_server.api.legacy_client import router as legacy_client_router

        app.include_router(legacy_client_router)
    mount_web_ui(app, enabled=container.settings.ui_enabled)
    return app


app = create_app()


def main() -> None:
    settings = Settings()
    settings.validate_for_startup()
    uvicorn.run(
        "infinity_context_server.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
