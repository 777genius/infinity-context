from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_core.application.context_hydration import (
    _with_application_evidence_contract,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_reported_obligation_attribution import (
    third_party_reported_obligation_spans,
)
from infinity_context_core.application.context_source_siblings import (
    is_direct_source_sibling_obligation_evidence,
    project_source_sibling_obligation_evidence,
    source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import (
    BuildContextQuery,
    ConsistencyMode,
    ContextBundle,
    ContextItem,
)
from infinity_context_core.application.use_cases import build_context as build_context_module
from infinity_context_core.application.use_cases.build_context import BuildContextUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SourceRef, SpaceId


@pytest.mark.parametrize(
    "text",
    (
        '"I must approve the dispatch manifest," the supervisor reported.',
        '"I must approve the dispatch manifest", the night shift supervisors report.',
        "“I must approve the dispatch manifest,” — reported the supervisor.",
        "'I must approve the dispatch manifest': the supervisor stated.",
        "‘I must approve the dispatch manifest’ – stated the supervisor.",
        'The supervisor reported: "I must approve the dispatch manifest."',
        "Reported the supervisor — “I must approve the dispatch manifest.”",
    ),
)
def test_public_obligation_policy_rejects_third_party_quoted_attribution(
    text: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert not is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize(
    "text",
    (
        (
            "The senior vice president of global warehouse and regional field operations "
            'reported: "I must approve the dispatch manifest."'
        ),
        (
            "Reported the senior vice president of global warehouse and regional field "
            "operations — “I must approve the dispatch manifest.”"
        ),
        (
            '"I must approve the dispatch manifest," the senior vice president of global '
            "warehouse and regional field operations reported."
        ),
        (
            "‘I must approve the dispatch manifest’ – stated the senior vice president of "
            "global warehouse and regional field operations."
        ),
        (
            "The senior vice president of US distribution and field operations stated: "
            "‘I must approve the dispatch manifest.’"
        ),
        'Alexandra Morgan stated: "I must approve the dispatch manifest."',
        '"I must approve the dispatch manifest," — reported Alexandra Morgan.',
        'She reported: "I must approve the dispatch manifest."',
        "“I must approve the dispatch manifest,” they reported.",
    ),
)
def test_public_obligation_policy_structurally_attributes_reporters_without_role_caps(
    text: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert not is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize(
    "text",
    (
        (
            '"I must approve the dispatch manifest." The senior vice president of global '
            "warehouse and regional field operations reported a loading delay."
        ),
        (
            "The senior vice president of global warehouse and regional field operations "
            'reported a loading delay. "I must approve the dispatch manifest."'
        ),
    ),
)
def test_public_obligation_policy_does_not_attribute_across_sentences(text: str) -> None:
    query = "Which dispatch manifest do I need to approve?"
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.applied


@pytest.mark.parametrize(
    "reported_clause",
    (
        'The supervisor reported: "I need to approve the loading checklist."',
        "The supervisor reported: I need to approve the loading checklist.",
    ),
)
def test_public_obligation_policy_keeps_reported_action_and_scope_in_one_span(
    reported_clause: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    text = f"I must approve the dispatch manifest. {reported_clause}"

    reported = third_party_reported_obligation_spans(text)
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert len(reported) == 1
    assert text[slice(*reported[0])].rstrip(".") == ("I need to approve the loading checklist")
    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.text == "I must approve the dispatch manifest"


@pytest.mark.parametrize(
    "text",
    (
        "I must approve the dispatch manifest before loading.",
        '"I must approve the dispatch manifest before loading."',
        "I reported that I must approve the dispatch manifest before loading.",
    ),
)
def test_public_obligation_policy_preserves_unattributed_first_person_statement(
    text: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.applied


@pytest.mark.parametrize(
    "text",
    (
        (
            "I must approve the dispatch manifest. "
            'The supervisor reported: "I must approve the dispatch manifest."'
        ),
        (
            'The supervisor reported: "I must approve the dispatch manifest." '
            "I must approve the dispatch manifest."
        ),
        (
            'The supervisor reported: "I must approve the dispatch manifest." '
            "The coordinator stated: “I must approve the dispatch manifest.” "
            "I must approve the dispatch manifest."
        ),
        (
            'The supervisor reported: "I must approve the dispatch manifest"; '
            "I must approve the dispatch manifest."
        ),
        (
            "The supervisor reported: “I must approve the dispatch manifest.”\n"
            "I must approve the dispatch manifest."
        ),
        ("I do not need to approve the loading checklist. I must approve the dispatch manifest."),
        (
            'The supervisor reported: "I must inspect the loading bay." '
            "I must approve the dispatch manifest."
        ),
        (
            "The supervisor reported: “I must inspect the loading bay.” "
            "I must approve the dispatch manifest."
        ),
    ),
)
def test_public_obligation_policy_keeps_aligned_direct_clause_despite_local_rejections(
    text: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"

    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.applied
    assert projection.text == "I must approve the dispatch manifest"
    assert len(projection.spans) == 1
    assert text[slice(*projection.spans[0])] == projection.text


@pytest.mark.parametrize(
    ("query", "reported"),
    (
        (
            "Which dispatch manifest must Morgan approve?",
            'The supervisor reported: "Morgan must approve the dispatch manifest."',
        ),
        (
            "Which dispatch manifest must Alexandra Morgan approve?",
            "The supervisor reported that Alexandra Morgan must approve the dispatch manifest.",
        ),
        (
            "Which dispatch manifest must she approve?",
            'The supervisor reported: "she must approve the dispatch manifest."',
        ),
        (
            "Which dispatch manifest must the night shift supervisor approve?",
            (
                "The coordinator reported that the night shift supervisor must approve "
                "the dispatch manifest."
            ),
        ),
    ),
)
def test_public_obligation_policy_rejects_reported_subject_grammar_cases(
    query: str,
    reported: str,
) -> None:
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=reported),
        text=reported,
    )

    assert third_party_reported_obligation_spans(reported)
    assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=reported)
    assert projection.rank == 3
    assert not projection.applied


@pytest.mark.parametrize(
    ("query", "direct"),
    (
        (
            "Which dispatch manifest must Morgan approve?",
            "Morgan must approve the dispatch manifest",
        ),
        (
            "Which dispatch manifest must Alexandra Morgan approve?",
            "Alexandra Morgan must approve the dispatch manifest",
        ),
        (
            "Which dispatch manifest must she approve?",
            "she must approve the dispatch manifest",
        ),
        (
            "Which dispatch manifest must the night shift supervisor approve?",
            "the night shift supervisor must approve the dispatch manifest",
        ),
    ),
)
def test_subject_grammar_keeps_candidate_local_direct_evidence_eligible(
    query: str,
    direct: str,
) -> None:
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=direct),
        text=direct,
    )

    assert third_party_reported_obligation_spans(direct) == ()
    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=direct)
    assert projection.rank == 0
    assert projection.text == direct


@pytest.mark.parametrize("boundary", ("; ", "\n"))
@pytest.mark.parametrize("reported_first", (False, True))
def test_named_report_attribution_keeps_unrelated_direct_clause_eligible(
    boundary: str,
    reported_first: bool,
) -> None:
    query = "Which dispatch manifest must Morgan approve?"
    direct = "Morgan must approve the dispatch manifest"
    reported = (
        'The coordinator reported: "Alexandra Morgan must inspect the loading bay"'
    )
    clauses = (reported, direct) if reported_first else (direct, reported)
    text = boundary.join(clauses)

    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert third_party_reported_obligation_spans(text)
    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.text == direct
    assert projection.spans and text[slice(*projection.spans[0])] == direct


@pytest.mark.parametrize(
    "text",
    (
        'The supervisor reported: "I must approve the dispatch manifest."',
        'The supervisor reported "I must approve the dispatch manifest."',
        '- "I must approve the dispatch manifest," the supervisor reported calmly.',
        '1) "I must approve the dispatch manifest" the supervisor reported clearly.',
        "* “I must approve the dispatch manifest,” Alexandra stated explicitly.",
        "+ ‘I must approve the dispatch manifest’ the supervisor reported urgently.",
        '• "I must approve the dispatch manifest," the supervisor reported briefly.',
        "2. “I must approve the dispatch manifest,” the supervisor reported quietly.",
    ),
)
def test_public_obligation_policy_never_upgrades_reported_only_forms(text: str) -> None:
    query = "Which dispatch manifest do I need to approve?"

    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert third_party_reported_obligation_spans(text)
    assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 3
    assert not projection.applied


@pytest.mark.parametrize(
    "modifier",
    ("supply", "family", "assembly", "friendly", "costly", "monthly"),
)
def test_public_obligation_policy_does_not_invent_reporter_from_false_modifier(
    modifier: str,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    text = f'"I must approve the dispatch manifest," the supervisor reported {modifier}.'

    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert third_party_reported_obligation_spans(text) == ()
    assert projection.rank == 0
    assert projection.applied


def test_application_path_does_not_prioritize_inverted_long_role_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    text = (
        '"I must approve the dispatch manifest," the senior vice president of global '
        "warehouse and regional field operations reported."
    )
    bundle = _execute_final_bundle(
        monkeypatch,
        query=query,
        final_ranked_items=(
            _item(
                "third-party-report",
                text,
                score=0.98,
                evidence_tier=1,
                answer_evidence=True,
            ),
            _item(
                "current-user-obligation",
                "I must approve the dispatch manifest before loading.",
                score=0.97,
                evidence_tier=1,
                answer_evidence=True,
            ),
        ),
    )

    assert [item.item_id for item in bundle.items] == [
        "current-user-obligation",
        "third-party-report",
    ]
    current, reported = bundle.items
    assert current.score == 0.99
    assert reported.score == 0.98
    assert reported.diagnostics is not None
    assert "application_evidence_contract_tier" not in reported.diagnostics["score_signals"]
    assert "application_evidence_priority" not in reported.diagnostics["score_signals"]


def test_application_path_preserves_cross_sentence_unattributed_obligation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "Which dispatch manifest do I need to approve?"
    direct_text = (
        '"I must approve the dispatch manifest." The senior vice president of global '
        "warehouse and regional field operations reported a loading delay."
    )
    bundle = _execute_final_bundle(
        monkeypatch,
        query=query,
        final_ranked_items=(
            _item(
                "generic-advice",
                "Review the dispatch checklist before loading.",
                score=0.98,
            ),
            _item(
                "cross-sentence-direct-obligation",
                direct_text,
                score=0.97,
                evidence_tier=1,
                answer_evidence=True,
            ),
        ),
    )

    assert [item.item_id for item in bundle.items] == [
        "cross-sentence-direct-obligation",
        "generic-advice",
    ]
    direct = bundle.items[0]
    assert direct.score == 0.99
    assert direct.diagnostics is not None
    assert direct.diagnostics["score_signals"]["application_evidence_contract_tier"] == 1


def test_final_bundle_renders_distinct_obligations_before_advice_and_unrelated_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_ranked_items = (
        _item(
            "generic-advice",
            "General planning advice: review the checklist and communicate early.",
            score=0.99,
        ),
        _item(
            "same-action-decoy",
            "A different department delivered visitor badges for a past conference.",
            score=0.985,
        ),
        _item(
            "confirm-window",
            "I need to verify the rehearsal window with the venue.",
            score=0.88,
            evidence_tier=1,
            answer_evidence=True,
            penalty=0.11,
        ),
        _item(
            "bring-records",
            "I need to deliver the signed readiness records before rehearsal.",
            score=0.87,
            evidence_tier=1,
            answer_evidence=True,
            penalty=0.11,
        ),
        _item(
            "deliver-cards",
            "I need to deliver replacement access cards before rehearsal.",
            score=0.86,
            evidence_tier=1,
            answer_evidence=True,
            penalty=0.11,
        ),
    )

    bundle = _execute_final_bundle(
        monkeypatch,
        query="Which readiness items do I need to verify or deliver before rehearsal?",
        final_ranked_items=final_ranked_items,
        rerank_omitted_item_ids=frozenset({"deliver-cards"}),
    )

    item_ids = [item.item_id for item in bundle.items]
    assert set(item_ids[:3]) == {"bring-records", "deliver-cards", "confirm-window"}
    assert item_ids[3:] == ["generic-advice", "same-action-decoy"]
    obligation_positions = [
        item_ids.index("confirm-window"),
        item_ids.index("bring-records"),
        item_ids.index("deliver-cards"),
    ]
    assert max(obligation_positions) < item_ids.index("generic-advice")
    assert max(obligation_positions) < item_ids.index("same-action-decoy")
    _assert_rendered_in_item_order(bundle)
    assert bundle.diagnostics["items_used"] == 5
    prioritized = bundle.items[:3]
    assert all(item.score == 0.99 for item in prioritized)
    assert all(
        item.diagnostics is not None
        and item.diagnostics["score_signals"]["application_evidence_priority"] == 1
        for item in prioritized
    )


def test_final_bundle_keeps_duration_evidence_bounded_and_preserves_currentness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_query = "daily bicycle commute office duration how long"
    evidence_reason = "decomposition_activity_duration"
    duration_text = "D8:2 My bicycle commute takes 35 minutes each way."
    advice_text = "D8:3 You should allow 35 minutes for the bicycle commute each way."
    unrelated_duration_text = "D8:4 The equipment repair took 35 minutes from start to finish."
    assert source_sibling_answer_evidence(
        expansion_query=evidence_query,
        expansion_reason=evidence_reason,
        text=duration_text,
    )
    assert not source_sibling_answer_evidence(
        expansion_query=evidence_query,
        expansion_reason=evidence_reason,
        text=advice_text,
    )
    assert not source_sibling_answer_evidence(
        expansion_query=evidence_query,
        expansion_reason=evidence_reason,
        text=unrelated_duration_text,
    )

    final_ranked_items = (
        _item(
            "ordinary-advice",
            advice_text,
            score=0.99,
        ),
        _item(
            "irrelevant-same-action",
            "Another rider completed a bicycle commute for an unrelated route.",
            score=0.98,
            answer_evidence=True,
        ),
        _item(
            "direct-duration",
            duration_text,
            score=0.81,
            answer_evidence=True,
            expansion_reason=evidence_reason,
            penalty=0.08,
        ),
        _item(
            "unrelated-duration",
            unrelated_duration_text,
            score=0.975,
        ),
        _item(
            "current-procedure",
            "The final procedure now uses the blue verification form.",
            score=0.995,
            finality_boost=0.046,
        ),
        _item(
            "earlier-procedure",
            "The earlier procedure used the orange verification form.",
            score=0.91,
            evidence_tier=2,
            currentness_penalty=0.065,
            reasons=("current_conflict_earlier_assertion",),
        ),
    )

    bundle = _execute_final_bundle(
        monkeypatch,
        query="How long is the bicycle commute, and what is the current procedure?",
        final_ranked_items=final_ranked_items,
    )

    item_ids = [item.item_id for item in bundle.items]
    assert item_ids == [
        "current-procedure",
        "direct-duration",
        "ordinary-advice",
        "irrelevant-same-action",
        "unrelated-duration",
        "earlier-procedure",
    ]
    assert item_ids.index("direct-duration") < 3
    assert item_ids.index("direct-duration") < item_ids.index("irrelevant-same-action")
    assert item_ids.index("direct-duration") < item_ids.index("unrelated-duration")
    assert item_ids.index("current-procedure") < item_ids.index("earlier-procedure")
    assert "ordinary-advice" in item_ids
    current = next(item for item in bundle.items if item.item_id == "current-procedure")
    assert current.score == 0.995
    stale = next(item for item in bundle.items if item.item_id == "earlier-procedure")
    assert stale.score == 0.91
    assert stale.diagnostics is not None
    assert stale.diagnostics["score_signals"]["current_conflict_earlier_assertion_penalty"] == 0.065
    _assert_rendered_in_item_order(bundle)


def _execute_final_bundle(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: str,
    final_ranked_items: tuple[ContextItem, ...],
    rerank_omitted_item_ids: frozenset[str] = frozenset(),
) -> ContextBundle:
    use_case = BuildContextUseCase(
        uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
        ids=_Ids(),  # type: ignore[arg-type]
        vector_index=object(),  # type: ignore[arg-type]
        graph_index=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
    )
    use_case._canonical_collector = _CanonicalCollector()  # type: ignore[assignment]
    use_case._hydrator = _Hydrator()  # type: ignore[assignment]
    use_case._artifact_evidence_collector = _ArtifactCollector(  # type: ignore[assignment]
        final_ranked_items
    )
    use_case._context_link_expander = _LinkExpander()  # type: ignore[assignment]

    async def empty_selection(**_kwargs: object) -> tuple[tuple[object, ...], dict[str, object]]:
        return (), {}

    async def temporal_passthrough(
        *, items: tuple[object, ...], **_kwargs: object
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        return items, {}

    async def aggregation_seed_passthrough(
        *, canonical_chunks: tuple[object, ...], **_kwargs: object
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        return canonical_chunks, {}

    async def empty_items(**_kwargs: object) -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(build_context_module, "_keyword_neighbor_chunk_items", empty_selection)
    monkeypatch.setattr(
        build_context_module,
        "_keyword_source_sibling_chunk_items",
        empty_selection,
    )
    monkeypatch.setattr(build_context_module, "_stale_review_items", empty_selection)
    monkeypatch.setattr(build_context_module, "_pending_conflict_items", empty_items)
    monkeypatch.setattr(
        build_context_module,
        "_aggregation_admission_seed_chunks",
        aggregation_seed_passthrough,
    )
    monkeypatch.setattr(
        build_context_module,
        "_apply_temporal_relation_signals",
        temporal_passthrough,
    )
    monkeypatch.setattr(
        build_context_module,
        "apply_deterministic_rerank_adjustments",
        lambda *_args, **_kwargs: tuple(
            _with_application_evidence_contract(item, query_text=query)
            for item in final_ranked_items
            if item.item_id not in rerank_omitted_item_ids
        ),
    )

    return asyncio.run(
        use_case.execute(
            BuildContextQuery(
                space_id=SpaceId("space-generic"),
                memory_scope_ids=(MemoryScopeId("scope-generic"),),
                query=query,
                consistency_mode=ConsistencyMode.CANONICAL_ONLY,
                token_budget=1600,
            )
        )
    )


class _CanonicalCollector:
    async def collect(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            facts=(),
            anchors=(),
            keyword_chunks=(),
            keyword_query_count=1,
            keyword_query_reasons=("original_query",),
            anchor_lookup_keys_considered=0,
            anchors_loaded_by_lookup=0,
        )


class _Hydrator:
    async def revalidate_visible_items(
        self, items: tuple[object, ...], **_kwargs: object
    ) -> tuple[object, ...]:
        return items


class _ArtifactCollector:
    def __init__(self, items: tuple[ContextItem, ...]) -> None:
        self._items = items

    async def collect(self, **_kwargs: object) -> tuple[object, ...]:
        return self._items


class _LinkExpander:
    async def collect(self, *, items: tuple[object, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(items=(), diagnostics={})


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_evidence_priority_test"


def _item(
    item_id: str,
    text: str,
    *,
    score: float,
    evidence_tier: int | None = None,
    answer_evidence: bool = False,
    expansion_reason: str = "",
    penalty: float = 0.0,
    finality_boost: float = 0.0,
    currentness_penalty: float = 0.0,
    reasons: tuple[str, ...] = (),
) -> ContextItem:
    score_signals: dict[str, object] = {
        "deterministic_rerank_boost": 0.0,
        "deterministic_rerank_penalty": penalty,
        "deterministic_rerank_net_adjustment": -penalty,
    }
    if evidence_tier is not None:
        score_signals["application_evidence_contract_tier"] = evidence_tier
    if answer_evidence:
        score_signals["source_sibling_answer_evidence"] = 1
    if expansion_reason:
        score_signals["query_expansion_reason"] = expansion_reason
    if finality_boost:
        score_signals["current_conflict_finality_boost"] = finality_boost
    if currentness_penalty:
        score_signals["current_conflict_earlier_assertion_penalty"] = currentness_penalty
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id=f"generic-source-{item_id}:turn",
                chunk_id=f"generic-chunk-{item_id}",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "memory_scope_id": "scope-generic",
            "score_signals": score_signals,
            "provenance": {
                "deterministic_rerank_applied": True,
                "deterministic_rerank_reasons": list(reasons),
            },
        },
    )


def _assert_rendered_in_item_order(bundle: ContextBundle) -> None:
    positions = [bundle.rendered_text.index(item.text) for item in bundle.items]
    assert positions == sorted(positions)
