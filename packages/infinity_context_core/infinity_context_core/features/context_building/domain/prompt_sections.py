"""Prompt evidence section planning for packed context items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from infinity_context_core.features.context_building.domain.context import ContextItem

CRITICAL_SECTION_ID: Final = "critical_evidence"
PRIMARY_SECTION_ID: Final = "primary_evidence"
SUPPORTING_SECTION_ID: Final = "supporting_evidence"
LOW_TRUST_SECTION_ID: Final = "low_trust_evidence"


@dataclass(frozen=True, slots=True)
class PromptEvidenceSection:
    """A prompt section containing quoted evidence items."""

    section_id: str
    title: str
    items: tuple[ContextItem, ...]
    priority: int
    estimated_tokens: int

    def __post_init__(self) -> None:
        if not self.section_id.strip():
            raise ValueError("Prompt evidence section requires an id")
        if not self.title.strip():
            raise ValueError("Prompt evidence section requires a title")
        if self.estimated_tokens < 0:
            raise ValueError("Prompt evidence section tokens cannot be negative")


@dataclass(frozen=True, slots=True)
class PromptSectionPlan:
    """Deterministic section plan for rendering packed prompt evidence."""

    sections: tuple[PromptEvidenceSection, ...]
    total_estimated_tokens: int = 0

    @property
    def items(self) -> tuple[ContextItem, ...]:
        """Return all planned items in section order."""

        return tuple(item for section in self.sections for item in section.items)


@dataclass(frozen=True, slots=True)
class PromptSectionPolicy:
    """Classify context items into stable prompt evidence sections."""

    primary_priority_threshold: int = 5
    critical_tags: tuple[str, ...] = ("critical", "current", "pinned", "selected")
    critical_roles: tuple[str, ...] = (
        "critical_evidence",
        "current_request_evidence",
        "selected_evidence",
    )
    primary_roles: tuple[str, ...] = ("answer_evidence", "primary_evidence")
    low_trust_tags: tuple[str, ...] = ("assistant_derived", "derived", "low_trust")
    low_trust_kinds: tuple[str, ...] = (
        "assistant_answer",
        "derived_summary",
        "summary",
    )
    low_trust_roles: tuple[str, ...] = ("low_trust_evidence",)

    def __post_init__(self) -> None:
        if self.primary_priority_threshold < 0:
            raise ValueError("Primary priority threshold cannot be negative")


@dataclass(frozen=True, slots=True)
class PromptSectionPlanner:
    """Group packed context items without treating memory as instructions."""

    policy: PromptSectionPolicy = PromptSectionPolicy()

    def plan(self, items: tuple[ContextItem, ...]) -> PromptSectionPlan:
        grouped: dict[str, list[ContextItem]] = {
            CRITICAL_SECTION_ID: [],
            PRIMARY_SECTION_ID: [],
            SUPPORTING_SECTION_ID: [],
            LOW_TRUST_SECTION_ID: [],
        }

        for item in items:
            grouped[self._section_id(item)].append(item)

        sections: list[PromptEvidenceSection] = []
        for section_id, title, priority in _SECTION_ORDER:
            section_items = tuple(grouped[section_id])
            if not section_items:
                continue
            sections.append(
                PromptEvidenceSection(
                    section_id=section_id,
                    title=title,
                    items=section_items,
                    priority=priority,
                    estimated_tokens=sum(item.token_cost for item in section_items),
                )
            )

        return PromptSectionPlan(
            sections=tuple(sections),
            total_estimated_tokens=sum(section.estimated_tokens for section in sections),
        )

    def _section_id(self, item: ContextItem) -> str:
        role = item.role.casefold()
        kind = item.kind.casefold()
        tags = {tag.casefold() for tag in item.tags}

        if role in self.policy.low_trust_roles:
            return LOW_TRUST_SECTION_ID
        if kind in self.policy.low_trust_kinds or tags.intersection(
            self.policy.low_trust_tags
        ):
            return LOW_TRUST_SECTION_ID
        if role in self.policy.critical_roles or tags.intersection(
            self.policy.critical_tags
        ):
            return CRITICAL_SECTION_ID
        if role in self.policy.primary_roles:
            return PRIMARY_SECTION_ID
        if item.priority >= self.policy.primary_priority_threshold:
            return PRIMARY_SECTION_ID
        return SUPPORTING_SECTION_ID


_SECTION_ORDER: Final[tuple[tuple[str, str, int], ...]] = (
    (CRITICAL_SECTION_ID, "Critical evidence", 100),
    (PRIMARY_SECTION_ID, "Primary evidence", 80),
    (SUPPORTING_SECTION_ID, "Supporting evidence", 50),
    (LOW_TRUST_SECTION_ID, "Low-trust evidence", 10),
)


__all__ = (
    "CRITICAL_SECTION_ID",
    "LOW_TRUST_SECTION_ID",
    "PRIMARY_SECTION_ID",
    "PromptEvidenceSection",
    "PromptSectionPlan",
    "PromptSectionPlanner",
    "PromptSectionPolicy",
    "SUPPORTING_SECTION_ID",
)
