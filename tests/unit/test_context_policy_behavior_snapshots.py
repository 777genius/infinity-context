"""Pinned pre-refactor outputs for domain scoring and rendered evidence packing."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from infinity_context_core.application.context_domain_rerank_apply import (
    apply_domain_rerank_signals,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_query_expansion import build_query_expansion_plan
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "context_policy_refactor"
_SCENARIOS = {
    "inventory": (
        "What pottery did Maya make?",
        "pottery_type_bridge",
        (
            "D1:1 Maya: I made a clay bowl and a small cup at pottery class.",
            "D1:2 Nora: I made plates for my kitchen.",
            "D1:3 Maya: The pottery project planning meeting was postponed.",
        ),
    ),
    "aggregation": (
        "Which books has Maya read?",
        "book_reading_list_bridge",
        (
            'D2:1 Maya: I read "Station Eleven" and "A Wrinkle in Time".',
            'D2:2 Maya: I just finished reading "The Left Hand of Darkness".',
            "D2:3 Nora: The library has a book reading list for everyone.",
        ),
    ),
    "state": (
        "What is Maya's current goal?",
        "adoption_current_goal_bridge",
        (
            "D3:1 Maya: My current goal is to adopt a child and start a family.",
            "D3:2 Maya: I used to want to move abroad, but that is no longer my plan.",
            "D3:3 Nora: The adoption agency published a software project roadmap.",
        ),
    ),
    "relationship": (
        "Is Maya married?",
        "relationship_status_bridge",
        (
            "D4:1 Maya: My husband and I have been married for five years.",
            "D4:2 Nora: Are you married? How long have you been married?",
            "D4:3 Maya: My project partner finished the launch checklist.",
        ),
    ),
    "place": (
        "Which country did Maya visit?",
        "travel_country_inventory_bridge",
        (
            "D5:1 Maya: I visited France and Italy last summer.",
            "D5:2 Maya: My friend lives in Canada and plans to visit next year.",
            "D5:3 Nora: We discussed the travel database project.",
        ),
    ),
    "temporal": (
        "When did Maya get her dog Luna?",
        "pet_acquisition_temporal_bridge",
        (
            "D6:1 Maya: I adopted my dog Luna in March 2024.",
            "D6:2 Maya: Luna loves playing in the park with other dogs.",
            "D6:3 Nora: I adopted a cat in June 2023.",
        ),
    ),
    "support": (
        "Who gives Maya emotional support?",
        "support_network_bridge",
        (
            "D7:1 Maya: My mother and coach are my rocks and always comfort me.",
            "D7:2 Maya: I wrote technical support documentation for the SDK.",
            "D7:3 Nora: My friends give me strength and encouragement.",
        ),
    ),
}


def _scenario_output(name: str) -> dict[str, object]:
    query, reason, texts = _SCENARIOS[name]
    items = tuple(
        ContextItem(
            item_id=f"{name}_{index}",
            item_type="chunk",
            text=text,
            score=0.9,
            source_refs=(
                SourceRef(
                    source_type="locomo_turn",
                    source_id=f"locomo:synthetic:session_{index}:D{index}:1:turn",
                    chunk_id=f"{name}_{index}",
                    quote_preview=text,
                ),
            ),
            diagnostics={
                "memory_scope_id": "synthetic_scope",
                "retrieval_sources": ["keyword_source_sibling_chunks"],
                "score_signals": {
                    "query_expansion_reason": reason,
                    "source_sibling_answer_evidence": 1,
                },
            },
        )
        for index, text in enumerate(texts, 1)
    )
    adjustments = [
        asdict(
            apply_domain_rerank_signals(
                query=query,
                query_reason=reason,
                item=item,
                relevance=score_query_relevance(query=query, text=item.text),
                has_multi_evidence_aggregation_candidate=name == "aggregation",
            )
        )
        for item in items
    ]
    ranked = apply_deterministic_rerank_adjustments(
        items,
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    packed = {
        budget_name: asdict(
            ContextPacker().pack(
                bundle_id=f"synthetic_{name}_{budget_name}",
                items=ranked,
                token_budget=token_budget,
                max_rendered_chars=char_budget,
                query=query,
            )
        )
        for budget_name, token_budget, char_budget in (
            ("normal", 1200, 4000),
            ("tight", 160, 650),
        )
    }
    # JSON normalization is only for output comparison; typed inputs above never round-trip JSON.
    return json.loads(json.dumps({"adjustments": adjustments, "packed": packed}))


@pytest.mark.parametrize("scenario", tuple(_SCENARIOS))
def test_scoring_and_rendered_evidence_match_pinned_base(scenario: str) -> None:
    expected = json.loads((_FIXTURES / f"{scenario}.json").read_text(encoding="utf-8"))
    assert _scenario_output(scenario) == expected
