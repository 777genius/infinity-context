from infinity_context_core.application.context_keyword_admission import admit_keyword_chunk
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_relevance import score_query_relevance


def test_admission_reasons_preserve_order_and_short_circuit():
    query = "What did Alice decide for project Atlas rollout?"
    texts = (
        "Alice decided project Beacon rollout uses a staged launch.",
        "Bob decided project Atlas rollout uses a staged launch.",
        "The weather is pleasant today.",
        "Alice decided project Atlas rollout uses a staged launch.",
    )
    calls = []
    reasons = []
    for text in texts:

        def best(text=text):
            calls.append(text)
            return query, "original_query", score_query_relevance(query=query, text=text)

        reasons.append(
            admit_keyword_chunk(
                query=query,
                text=text,
                anchor_intent=build_query_anchor_intent(query),
                best_query=best,
            ).reason
        )
    assert reasons == ["project_identity", "anchor_conflict", "insufficient_relevance", "admitted"]
    assert calls == list(texts[1:])


def test_admission_counters_survive_repeated_padded_bundle_projection():
    from infinity_context_core.application.context_diagnostics import (
        normalize_context_bundle_diagnostics,
    )

    counters = {
        "keyword_chunks_dropped_by_project_identity": 1,
        "keyword_chunks_dropped_by_anchor_conflict": 1,
        "keyword_chunks_dropped_by_insufficient_relevance": 1,
        "keyword_chunks_dropped_by_relevance": 3,
    }
    padded = {**{f"noise_{i}": i for i in range(128)}, **counters}
    projected = normalize_context_bundle_diagnostics(padded, items=())
    projected = normalize_context_bundle_diagnostics(projected, items=())
    assert all(projected[key] == value for key, value in counters.items())
