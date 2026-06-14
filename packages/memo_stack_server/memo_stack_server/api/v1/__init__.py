"""Version 1 API routes."""

from fastapi import APIRouter

from memo_stack_server.api.v1.anchors import router as anchors_router
from memo_stack_server.api.v1.assets import router as assets_router
from memo_stack_server.api.v1.capabilities import router as capabilities_router
from memo_stack_server.api.v1.captures import router as captures_router
from memo_stack_server.api.v1.context import router as context_router
from memo_stack_server.api.v1.context_links import router as context_links_router
from memo_stack_server.api.v1.diagnostics import router as diagnostics_router
from memo_stack_server.api.v1.digest import router as digest_router
from memo_stack_server.api.v1.documents import router as documents_router
from memo_stack_server.api.v1.episodes import router as episodes_router
from memo_stack_server.api.v1.export import router as export_router
from memo_stack_server.api.v1.facts import router as facts_router
from memo_stack_server.api.v1.health import router as health_router
from memo_stack_server.api.v1.insights import router as insights_router
from memo_stack_server.api.v1.memory_browser import router as memory_browser_router
from memo_stack_server.api.v1.operations import router as operations_router
from memo_stack_server.api.v1.spaces_memory_scopes import router as spaces_memory_scopes_router
from memo_stack_server.api.v1.suggestions import router as suggestions_router
from memo_stack_server.api.v1.thread_memory import router as thread_memory_router
from memo_stack_server.api.v1.usage import router as usage_router
from memo_stack_server.api.v1.users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(health_router)
router.include_router(capabilities_router)
router.include_router(spaces_memory_scopes_router)
router.include_router(users_router)
router.include_router(facts_router)
router.include_router(assets_router)
router.include_router(anchors_router)
router.include_router(documents_router)
router.include_router(episodes_router)
router.include_router(captures_router)
router.include_router(context_links_router)
router.include_router(context_router)
router.include_router(digest_router)
router.include_router(insights_router)
router.include_router(memory_browser_router)
router.include_router(operations_router)
router.include_router(thread_memory_router)
router.include_router(suggestions_router)
router.include_router(usage_router)
router.include_router(diagnostics_router)
router.include_router(export_router)
