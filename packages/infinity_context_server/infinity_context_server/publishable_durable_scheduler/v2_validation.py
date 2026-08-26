"""Shared exact validation helpers for scheduler-v2 reference modules."""

from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    SchedulerV2Error,
    SlotBinding,
)


def require_live(binding: SlotBinding, now_unix_ms: int, database_now_unix_ms: int) -> None:
    if (
        type(now_unix_ms) is not int
        or type(database_now_unix_ms) is not int
        or now_unix_ms >= binding.absolute_deadline_unix_ms
        or database_now_unix_ms >= binding.absolute_deadline_unix_ms
    ):
        raise SchedulerV2Error("absolute_deadline_exhausted")


def require_sha(value: object, code: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise SchedulerV2Error(code)


__all__ = ("require_live", "require_sha")
