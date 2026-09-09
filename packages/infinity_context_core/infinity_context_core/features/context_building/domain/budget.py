"""Budget policy for selecting context evidence under a prompt limit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.context import (
    ContextDroppedItem,
    ContextItem,
)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Independent token and optional rendered Unicode character limits.

    Token estimates and reserves retain their existing meaning. A character cap
    measures the complete evidence rendering with Python's ``len(str)``; zero
    allows an empty bundle and ``None`` preserves uncapped feature callers.
    """

    max_prompt_tokens: int
    reserved_response_tokens: int = 0
    reserved_system_tokens: int = 0
    max_rendered_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_rendered_chars is not None and self.max_rendered_chars < 0:
            raise ValueError("Rendered character budget cannot be negative")
        if self.max_prompt_tokens < 1:
            raise ValueError("Context budget must allow at least one prompt token")
        if self.reserved_response_tokens < 0:
            raise ValueError("Response token reserve cannot be negative")
        if self.reserved_system_tokens < 0:
            raise ValueError("System token reserve cannot be negative")
        if self.available_evidence_tokens < 0:
            raise ValueError("Token reserves exceed the prompt budget")

    @property
    def available_evidence_tokens(self) -> int:
        """Tokens available for rendered memory evidence."""

        return (
            self.max_prompt_tokens
            - self.reserved_response_tokens
            - self.reserved_system_tokens
        )


@dataclass(frozen=True, slots=True)
class ContextPackingPlan:
    """Deterministic result of applying the budget policy to candidates."""

    selected_items: tuple[ContextItem, ...]
    dropped_items: tuple[ContextDroppedItem, ...]
    token_budget: ContextBudget
    total_estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ContextBudgetPolicy:
    """Select higher-priority context items without splitting evidence records."""

    def plan(
        self,
        items: tuple[ContextItem, ...],
        budget: ContextBudget,
        *,
        render: Callable[[tuple[ContextItem, ...]], str] | None = None,
    ) -> ContextPackingPlan:
        if budget.max_rendered_chars is not None and render is None:
            from .rendering import ContextEvidenceRenderer

            render = ContextEvidenceRenderer().render
        remaining = budget.available_evidence_tokens
        selected: list[ContextItem] = []
        dropped: list[ContextDroppedItem] = []
        used = 0

        ranked_items = sorted(
            enumerate(items),
            key=lambda item: (-item[1].priority, -item[1].score, item[0]),
        )
        for _, item in ranked_items:
            token_cost = item.token_cost
            if token_cost <= remaining:
                # Measure the actual proposed rendering, including section headings,
                # escaped quotes, citations and numbering. Keep evidence records whole.
                if (
                    budget.max_rendered_chars is not None
                    and render is not None
                    and len(render((*selected, item))) > budget.max_rendered_chars
                ):
                    dropped.append(
                        ContextDroppedItem(
                            item_id=item.item_id,
                            reason="rendered_character_budget_exceeded",
                            estimated_tokens=token_cost,
                        )
                    )
                    continue
                selected.append(item)
                remaining -= token_cost
                used += token_cost
                continue

            reason = "item_exceeds_budget"
            if token_cost <= budget.available_evidence_tokens:
                reason = "budget_exhausted"
            dropped.append(
                ContextDroppedItem(
                    item_id=item.item_id,
                    reason=reason,
                    estimated_tokens=token_cost,
                )
            )

        return ContextPackingPlan(
            selected_items=tuple(selected),
            dropped_items=tuple(dropped),
            token_budget=budget,
            total_estimated_tokens=used,
        )


__all__ = ("ContextBudget", "ContextBudgetPolicy", "ContextPackingPlan")
