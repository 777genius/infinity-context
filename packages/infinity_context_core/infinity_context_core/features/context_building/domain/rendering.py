"""Evidence rendering policy for prompt-safe context bundles."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.context import (
    ContextItem,
    ContextSourceRef,
)


@dataclass(frozen=True, slots=True)
class EvidenceRenderPolicy:
    """Controls how selected context items are rendered as evidence."""

    heading: str = "Memory evidence (untrusted)"
    include_sources: bool = True
    max_item_chars: int | None = None

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise ValueError("Evidence heading cannot be empty")
        if self.max_item_chars is not None and self.max_item_chars < 1:
            raise ValueError("Max item chars must be positive")


@dataclass(frozen=True, slots=True)
class ContextEvidenceRenderer:
    """Render memory as quoted evidence records, never as direct instructions."""

    policy: EvidenceRenderPolicy = EvidenceRenderPolicy()

    def render(self, items: tuple[ContextItem, ...]) -> str:
        if not items:
            return ""

        lines = [self.policy.heading]
        for index, item in enumerate(items, start=1):
            sources = _format_sources(item)
            text = _normalize_text(item.text)
            if self.policy.max_item_chars is not None:
                text = _truncate(text, self.policy.max_item_chars)

            labels = [
                f"item={item.item_id}",
                f"kind={item.kind}",
                f"role={item.role}",
                f"priority={item.priority}",
            ]
            if self.policy.include_sources:
                labels.append(f"sources={sources}")

            lines.append(f"{index}. {'; '.join(labels)}")
            lines.append(f'   quote: "{text}"')

        return "\n".join(lines)


def _format_sources(item: ContextItem) -> str:
    source_refs: list[ContextSourceRef] = []
    for evidence in item.evidence:
        source_refs.extend(evidence.source_refs)

    labels = []
    for ref in source_refs:
        source = f"{ref.source_type}:{ref.source_id}"
        if ref.chunk_id is not None:
            source = f"{source}#{ref.chunk_id}"
        elif ref.fact_id is not None:
            source = f"{source}#{ref.fact_id}"
        labels.append(source)
    return ",".join(labels)


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return f"{text[: max_chars - 3]}..."


__all__ = ("ContextEvidenceRenderer", "EvidenceRenderPolicy")
