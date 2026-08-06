"""Authorization boundary for a reviewer applying memory changes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SuggestionReviewScope:
    """Immutable scope granted to one review operation."""

    space_id: str
    memory_scope_ids: tuple[str, ...]
    repository_id: str | None = None
    code_scope_id: str | None = None

    def __post_init__(self) -> None:
        if not self.space_id.strip():
            raise ValueError("Review space_id cannot be blank")
        if not self.memory_scope_ids or any(
            not scope_id.strip() for scope_id in self.memory_scope_ids
        ):
            raise ValueError("Review memory_scope_ids cannot be empty or blank")
        if self.code_scope_id is not None and self.repository_id is None:
            raise ValueError("Review code_scope_id requires repository_id")

    def allows(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        repository_id: str | None,
        code_scope_id: str | None,
    ) -> bool:
        if space_id != self.space_id or memory_scope_id not in self.memory_scope_ids:
            return False
        if self.repository_id is None:
            return repository_id is None and code_scope_id is None
        if repository_id != self.repository_id:
            return False
        return code_scope_id == self.code_scope_id


__all__ = ("SuggestionReviewScope",)
