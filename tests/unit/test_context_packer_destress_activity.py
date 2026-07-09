from infinity_context_core.application.context_packer import (
    _answer_support_diversity_candidates,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _destress_item(item_id: str, text: str, source_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.99,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "score_signals": {
                "query_expansion_reason": "destress_activity_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 4,
            },
        },
    )


def test_destress_activity_exact_answer_support_prefers_first_direct_mention() -> None:
    early = _destress_item(
        "early_escape",
        "D1:6 Jon: Dancing has been my passion and escape.",
        "locomo:conv-fixture:session_1:D1:6:turn",
    )
    later = _destress_item(
        "later_stress_fix",
        "D11:6 Gina: Dance is my stress fix too and my worries vanish.",
        "locomo:conv-fixture:session_11:D11:6:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [later, early],
        query="How do Jon and Gina both like to destress?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="How do Jon and Gina both like to destress?",
    )

    assert candidates[ordered[0]].item_id == "early_escape"
