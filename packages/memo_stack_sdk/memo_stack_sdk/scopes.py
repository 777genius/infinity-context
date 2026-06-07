"""Scope value objects for the Memo Stack SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memo_stack_sdk._payloads import (
    context_scope_payload as _context_scope_payload,
)
from memo_stack_sdk._payloads import (
    single_scope_body as _single_scope_body,
)
from memo_stack_sdk._payloads import (
    validate_read_scope_payload as _validate_read_scope_payload,
)
from memo_stack_sdk._payloads import (
    validate_single_scope_payload as _validate_single_scope_payload,
)


@dataclass(frozen=True)
class MemoryScope:
    space_id: str | None = None
    profile_id: str | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    profile_external_ref: str | None = None
    thread_external_ref: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = _single_scope_body(
            space_id=self.space_id,
            profile_id=self.profile_id,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            profile_external_ref=self.profile_external_ref,
            thread_external_ref=self.thread_external_ref,
        )
        _validate_single_scope_payload(payload)
        return payload


@dataclass(frozen=True)
class ReadScope:
    space_id: str | None = None
    profile_ids: tuple[str, ...] | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    profile_external_ref: str | None = None
    profile_external_refs: tuple[str, ...] | None = None
    thread_external_ref: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = _context_scope_payload(
            space_id=self.space_id,
            profile_ids=list(self.profile_ids) if self.profile_ids is not None else None,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            profile_external_ref=self.profile_external_ref,
            profile_external_refs=(
                list(self.profile_external_refs)
                if self.profile_external_refs is not None
                else None
            ),
            thread_external_ref=self.thread_external_ref,
        )
        _validate_read_scope_payload(payload)
        return payload


__all__ = ["MemoryScope", "ReadScope"]
