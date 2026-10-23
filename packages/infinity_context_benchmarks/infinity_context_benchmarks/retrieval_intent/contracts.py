"""Benchmark-owned contracts policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalEntityIntent:
    """Person or named-entity surfaces extracted from a question."""

    canonical: str
    surfaces: tuple[str, ...]
    speaker_surfaces: tuple[str, ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "canonical": self.canonical,
            "surfaces": list(self.surfaces),
            "speaker_surfaces": list(self.speaker_surfaces),
        }


@dataclass(frozen=True)
class RetrievalTimeIntent:
    """Temporal constraints extracted from a question."""

    is_temporal: bool
    terms: tuple[str, ...]
    surface_terms: tuple[str, ...]
    kind: str

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "is_temporal": self.is_temporal,
            "terms": list(self.terms),
            "surface_terms": list(self.surface_terms),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class RetrievalRelationIntent:
    """Typed relation facet inferred from question-only relation terms."""

    category: str
    terms: tuple[str, ...]
    variant_terms: tuple[str, ...]
    evidence_need: str
    reason_codes: tuple[str, ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "category": self.category,
            "terms": list(self.terms),
            "variant_terms": list(self.variant_terms),
            "evidence_need": self.evidence_need,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class RetrievalIntent:
    """Question-only retrieval intent used by query planning and rerank."""

    question: str
    lexical_terms: tuple[str, ...]
    entities: tuple[RetrievalEntityIntent, ...]
    relation_terms: tuple[str, ...]
    relation_variant_terms: tuple[str, ...]
    time_intent: RetrievalTimeIntent
    visual_terms: tuple[str, ...]
    multi_hop_markers: tuple[str, ...]
    evidence_need: tuple[str, ...]
    risk_flags: tuple[str, ...]
    bundle_evidence_roles: tuple[str, ...] = ()
    relation_intents: tuple[RetrievalRelationIntent, ...] = ()
    answer_unit_shapes: tuple[str, ...] = ()

    @property
    def entity_names(self) -> tuple[str, ...]:
        return tuple(entity.canonical for entity in self.entities)

    @property
    def entity_surfaces(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(surface for entity in self.entities for surface in entity.surfaces)
        )

    @property
    def speaker_surfaces(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                surface for entity in self.entities for surface in entity.speaker_surfaces
            )
        )

    def to_query_profile(self) -> dict[str, object]:
        return {
            "lexical_terms": self.lexical_terms,
            "entities": self.entity_names,
            "entity_surfaces": self.entity_surfaces,
            "speaker_surfaces": self.speaker_surfaces,
            "relation_terms": self.relation_terms,
            "relation_variant_terms": self.relation_variant_terms,
            "relation_categories": tuple(intent.category for intent in self.relation_intents),
            "relation_category_terms": {
                intent.category: tuple(dict.fromkeys((*intent.terms, *intent.variant_terms)))
                for intent in self.relation_intents
            },
            "is_temporal_query": self.time_intent.is_temporal,
            "time_intent_kind": self.time_intent.kind,
            "temporal_terms": self.time_intent.terms,
            "temporal_surface_terms": self.time_intent.surface_terms,
            "visual_terms": self.visual_terms,
            "multi_hop_markers": self.multi_hop_markers,
            "evidence_need": self.evidence_need,
            "bundle_evidence_roles": self.bundle_evidence_roles,
            "answer_unit_shapes": self.answer_unit_shapes,
            "risk_flags": self.risk_flags,
        }

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": "retrieval_intent.v1",
            "entity_count": len(self.entities),
            "entities": [entity.to_diagnostics() for entity in self.entities],
            "relations": {
                "terms": list(self.relation_terms),
                "variant_terms": list(self.relation_variant_terms),
                "intents": [intent.to_diagnostics() for intent in self.relation_intents],
            },
            "time_intent": self.time_intent.to_diagnostics(),
            "visual_terms": list(self.visual_terms),
            "multi_hop_markers": list(self.multi_hop_markers),
            "evidence_need": list(self.evidence_need),
            "bundle_evidence_roles": list(self.bundle_evidence_roles),
            "answer_unit_shapes": list(self.answer_unit_shapes),
            "risk_flags": list(self.risk_flags),
            "uses_ground_truth": False,
        }
