"""Evidence rendering policy for prompt-safe context bundles."""

from __future__ import annotations

from dataclasses import dataclass, field

from infinity_context_core.features.context_building.domain.context import (
    ContextItem,
    ContextSourceRef,
)
from infinity_context_core.features.context_building.domain.prompt_sections import (
    PromptSectionPlan,
    PromptSectionPlanner,
)


@dataclass(frozen=True, slots=True)
class EvidenceRenderPolicy:
    """Controls how selected context items are rendered as evidence."""

    heading: str = "Memory evidence (untrusted)"
    include_sources: bool = True
    include_section_titles: bool = True
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
    section_planner: PromptSectionPlanner = field(default_factory=PromptSectionPlanner)

    def render(self, items: tuple[ContextItem, ...]) -> str:
        return self.render_plan(self.section_planner.plan(items))

    def render_plan(self, plan: PromptSectionPlan) -> str:
        if not plan.sections:
            return ""

        lines = [self.policy.heading]
        index = 1
        for section in plan.sections:
            if self.policy.include_section_titles:
                lines.append(f"[{section.section_id}] {section.title}")
            for item in section.items:
                sources = _format_sources(item)
                text = _normalize_text(item.text)
                if self.policy.max_item_chars is not None:
                    text = _truncate(text, self.policy.max_item_chars)

                labels = [
                    f"item={_safe_label(item.item_id)}",
                    f"kind={_safe_label(item.kind)}",
                    f"role={_safe_label(item.role)}",
                    f"priority={item.priority}",
                ]
                if self.policy.include_sources:
                    labels.append(f"sources={sources}")
                labels.extend(_format_evidence_labels(item))

                lines.append(f"{index}. {'; '.join(labels)}")
                lines.append(f'   quote: "{_quote_text(text)}"')
                index += 1

        return "\n".join(lines)


def _format_sources(item: ContextItem) -> str:
    source_refs: list[ContextSourceRef] = []
    for evidence in item.evidence:
        source_refs.extend(evidence.source_refs)

    labels = []
    for ref in source_refs:
        source = f"{_safe_identity_part(ref.source_type)}:{_safe_identity_part(ref.source_id)}"
        if ref.chunk_id is not None:
            source = f"{source}#{_safe_identity_part(ref.chunk_id)}"
        elif ref.fact_id is not None:
            source = f"{source}#{_safe_identity_part(ref.fact_id)}"
        labels.append(source)
    return ",".join(labels)


def _format_evidence_labels(item: ContextItem) -> list[str]:
    values: dict[str, list[str]] = {}
    for evidence in item.evidence:
        _append_label(values, "trust", evidence.trust_level)
        _append_label(values, "confidence", evidence.confidence)
        _append_label(values, "lifecycle", evidence.lifecycle_label)
        _append_label(values, "temporal", evidence.temporal_label)
        _append_label(values, "temporal_assurance", evidence.temporal_assurance)
        for reason in evidence.temporal_reason_codes:
            _append_label(values, "temporal_reason", reason)
        _append_label(values, "temporal_kind", evidence.temporal_kind)
        _append_label(
            values,
            "version",
            str(evidence.canonical_version) if evidence.canonical_version is not None else None,
        )
        for name in ("observed_at", "valid_from", "valid_to", "last_confirmed_at"):
            timestamp = getattr(evidence, name)
            _append_label(values, name, timestamp.isoformat() if timestamp is not None else None)
        for provider in evidence.retrieval_sources:
            _append_label(values, "retrieved_via", provider)
    return [
        f"{name}={','.join(_safe_label(item) for item in items)}" for name, items in values.items()
    ]


def _append_label(values: dict[str, list[str]], name: str, value: str | None) -> None:
    if value is None or value in values.setdefault(name, []):
        return
    values[name].append(value)


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _quote_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _safe_label(value: str, *, max_chars: int = 160) -> str:
    normalized = _normalize_text(value)
    sanitized = "".join(
        character if character.isalnum() or character in "._:/@+-" else "_"
        for character in normalized
    )
    return _truncate(sanitized, max_chars)


def _safe_identity_part(value: str) -> str:
    return _safe_label(value, max_chars=120)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return f"{text[: max_chars - 3]}..."


__all__ = ("ContextEvidenceRenderer", "EvidenceRenderPolicy")
