"""Small internal helpers shared by resumable runner policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import SchedulerRunAuthority
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)


@final
@dataclass(frozen=True, slots=True)
class RunnerEntry:
    run: SchedulerRunAuthority
    manifest: BuiltSchedulerManifest
    store: SQLiteDurableSchedulerStore
    authentication_secret: bytes


def manifest_call(manifest: BuiltSchedulerManifest, ordinal: int) -> SchedulerLogicalCall:
    try:
        shard = manifest.shards[ordinal // 256]
        return shard.calls[ordinal - shard.start_ordinal]
    except (IndexError, TypeError):
        _fail("scheduler_runner_manifest_call_missing")


def failure_code(error: BaseException) -> str:
    if isinstance(error, SchedulerRunnerError):
        return error.code
    return "scheduler_runner_dispatch_boundary_failed"


def port_digest(port: object, name: str) -> str:
    try:
        value = getattr(port, name)
    except Exception:
        _fail("scheduler_runner_composition_binding_invalid")
    if not is_sha256(value):
        _fail("scheduler_runner_composition_binding_invalid")
    return value


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = ("RunnerEntry", "failure_code", "manifest_call", "port_digest")
