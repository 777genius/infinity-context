"""Health API."""

from typing import Annotated

from fastapi import APIRouter, Depends

from memo_stack_server.api.dependencies import get_container
from memo_stack_server.composition import Container

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(container: Annotated[Container, Depends(get_container)]) -> dict[str, str]:
    return {
        "status": "ok",
        "service": container.settings.service_name,
        "deploy_profile": container.settings.deploy_profile.value,
    }
