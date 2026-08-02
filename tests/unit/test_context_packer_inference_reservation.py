import pytest
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_family,
)
from infinity_context_core.application.context_packer_inference_reservation import (
    inference_reservation_for_char_pressure,
)
from infinity_context_core.application.context_packer_selection import (
    _rendered_char_count,
    _select_item,
    _SelectionState,
    replace_selected_item,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.features.context_building.public import (
    InferenceEvidenceCandidate,
    InferenceEvidenceReservationRequest,
    InferenceReservationPressure,
    inference_query_predicate,
    reserve_inference_evidence,
)


def test_char_pressure_preserves_exact_positive_projection() -> None:
    selected, generic = _pressure_selected_items()
    target = _resize_for_projected_chars(
        selected,
        _item(
            "target",
            score=0.935,
            text=(
                "John earned a salary and saved enough income to cover bills and "
                "expenses when he was younger."
            ),
        ),
        projected_chars=19_375,
    )

    assert _rendered_char_count(selected) == 17_977
    assert _rendered_char_count((*selected, target)) == 19_375

    result = ContextPacker().pack(
        bundle_id="ctx-inference-pressure",
        items=(*selected, target),
        query="What might John's financial status be?",
        token_budget=10_000,
        max_rendered_chars=18_000,
    )

    selected_ids = {item.item_id for item in result.bundle.items}
    assert "target" in selected_ids
    assert generic.item_id not in selected_ids
    assert result.bundle.diagnostics["dropped_by_char_cap"] >= 1
    assert result.bundle.diagnostics["inference_reservations_selected"] == 1
    assert result.bundle.diagnostics["inference_generic_displacements"] == 1


def test_replacement_preserves_coverage_only_answer_support_family_state() -> None:
    support = _item(
        "generic",
        score=0.99,
        text="John finished his homework before checking the time.",
    )
    coverage_only = _item(
        "career",
        score=0.98,
        text="D4:13 Caroline plans a career helping people with mental health.",
        reason="career_intent_bridge",
    )
    replacement = _item(
        "target",
        score=0.935,
        text="John's family struggled financially when he was younger.",
    )
    state = _selection_state()
    _select_item(
        state,
        item=support,
        item_tokens=estimate_tokens(support.text) + 16,
    )
    _select_item(
        state,
        item=coverage_only,
        item_tokens=estimate_tokens(coverage_only.text) + 16,
        mark_answer_support_family=False,
    )
    decomposition_family = _answer_support_diversity_family(support)
    career_family = _answer_support_diversity_family(coverage_only)
    before = _selection_state_snapshot(state)

    assert decomposition_family == "query_reason:decomposition-inference-support"
    assert career_family.startswith("query_reason_career_slot:career-intent-bridge:")
    assert before["answer_support_family_ids"] == frozenset({decomposition_family})
    assert career_family not in before["answer_support_family_ids"]
    assert replace_selected_item(
        state,
        displaced=support,
        replacement=replacement,
        budget=10_000,
        char_budget=18_000,
    )

    after = _selection_state_snapshot(state)
    assert after["answer_support_family_ids"] == frozenset({decomposition_family})
    assert career_family not in after["answer_support_family_ids"]
    assert after["selected_item_ids"] == (coverage_only.item_id, replacement.item_id)
    assert after["selected_keys"] == frozenset(
        {
            (coverage_only.item_type, coverage_only.item_id),
            (replacement.item_type, replacement.item_id),
        }
    )
    assert after["used_tokens"] == sum(
        estimate_tokens(item.text) + 16 for item in (coverage_only, replacement)
    )
    assert after["rendered_chars"] == _rendered_char_count((coverage_only, replacement))
    assert after["chunks_by_source"] == {
        "scope-synthetic:synthetic:source-career": 1,
        "scope-synthetic:synthetic:source-target": 1,
    }
    assert after["source_capped_items"] == {
        "scope-synthetic:synthetic:source-career": 1,
        "scope-synthetic:synthetic:source-target": 1,
    }
    assert after["art_style_items"] == before["art_style_items"]
    assert after["source_refs"] == (
        coverage_only.source_refs,
        replacement.source_refs,
    )
    assert after["diagnostics"] == (
        coverage_only.diagnostics,
        replacement.diagnostics,
    )


@pytest.mark.parametrize(
    "query",
    (
        "Could John's financial status be poor?",
        "Would John's financial status be poor?",
        "Could you tell me what might John's financial status be?",
        "Would you please say what might John's financial status be?",
        "Hello, what might John's financial status be?",
        "Hi! What might John's financial status be?",
        'What might "John\'s" financial status be?',
        "What might 'John' financial status be?",
        "What might someone's financial status be?",
        "what might john's financial status be?",
        "What broad terms might John's financial status intersect?",
        "What might John's purchase cost be?",
    ),
)
def test_query_predicate_closes_polite_quote_generic_and_broad_bypasses(
    query: str,
) -> None:
    assert inference_query_predicate(query) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John has abundant homework time.",
        "John bought it for an expensive price.",
        "John has an abundance of time for homework and said money once.",
    ),
)
def test_policy_rejects_unrelated_or_purchase_evidence(target_text: str) -> None:
    request = _policy_request(target_text=target_text)
    assert reserve_inference_evidence(request) is None


def test_policy_reserves_household_resource_contrast_from_financial_lane() -> None:
    request = _policy_request(
        target_text=(
            "John mentioned his kids having a lot while others lack resources, "
            "indicating a material disparity."
        ),
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    reservation = reserve_inference_evidence(request)

    assert reservation is not None
    assert reservation.candidate_id == "target"
    assert reservation.displaced_candidate_id == "generic"


def test_adapter_swaps_compatible_inference_lanes_across_real_source_groups() -> None:
    displaced = _item(
        "generic-source-group",
        score=0.99,
        text="A generic inference support note about homework and time.",
        source_id="D4:2",
        extra={"keyword_aggregation_source_group": "conversation:D4"},
    )
    reserved = _item(
        "financial-source-group",
        score=0.935,
        text=(
            "John mentioned his kids having a lot while others lack resources, "
            "indicating a material disparity."
        ),
        reason="decomposition_financial_resources_inference",
        source_id="D5:5",
        extra={"keyword_aggregation_source_group": "conversation:D5"},
    )

    assert _answer_support_diversity_family(reserved) != _answer_support_diversity_family(
        displaced
    )
    reservation = inference_reservation_for_char_pressure(
        query="What might John's financial status be?",
        rejected=reserved,
        selected=(displaced,),
        protected_keys=frozenset(),
    )

    assert reservation is not None
    assert reservation.reserved is reserved
    assert reservation.displaced is displaced
    assert (
        inference_reservation_for_char_pressure(
            query="What might John's financial status be?",
            rejected=reserved,
            selected=(displaced,),
            protected_keys=frozenset({(displaced.item_type, displaced.item_id)}),
        )
        is None
    )


@pytest.mark.parametrize(
    "target_text",
    (
        "John explained his family has surplus assets while other households lack "
        "basic resources.",
        "John said his dependents have plenty of possessions whereas other families "
        "cannot afford material needs.",
    ),
)
def test_policy_reserves_paraphrased_local_material_contrasts(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is not None


@pytest.mark.parametrize(
    "target_text",
    (
        "John earns a salary that covers bills.",
        "John's savings cover household expenses.",
        "John has financial security and assets.",
    ),
)
def test_policy_reserves_subject_bound_direct_financial_evidence(
    target_text: str,
) -> None:
    assert reserve_inference_evidence(_policy_request(target_text=target_text)) is not None


def test_policy_rejects_reversed_household_resource_contrast() -> None:
    request = _policy_request(
        target_text=(
            "John said his children don't have enough while other families have plenty "
            "and need nothing."
        ),
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John said Maria told him her kids have a lot while others lack resources.",
        "John is happy; Maria has money.",
        "John's kids have a lot. Other families lack resources.",
        "John mentioned his kids having a lot of homework. Other families lack resources.",
        "John bought a gift; other families lack resources.",
        "John gives charity help to other families.",
        "John said his kids have a lot while other families need help.",
        "John mentioned his kids not having a lot while others lack resources.",
        "John mentioned his kids having a lot while Maria said others lack resources.",
        "John said his kids have plenty of homework while others lack resources.",
        "John said his kids have a lot while others do not lack resources.",
        "John said his kids have a lot while others don't lack resources.",
        "John said his kids have a lot while others deny they lack resources.",
        "John said his kids have a lot while others claim they lack resources.",
        "John said his kids have a lot while others say they lack resources.",
    ),
)
def test_policy_rejects_cross_speaker_cross_clause_and_nonmaterial_contrasts(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John said his children have so much homework while others lack time.",
        "John said his kids have so much fun while others don't.",
        "John said his children get plenty of attention while other kids get less.",
        "John said his family has plenty of chores while others have nothing scheduled.",
        "John said other children need help.",
        "John said his children have plenty.",
    ),
)
def test_policy_rejects_unrelated_or_incomplete_household_contrasts(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John said Maria has substantial savings.",
        "John's friend has plenty of money saved.",
        "Maria has a financial budget, while John mentioned the money.",
    ),
)
def test_policy_rejects_financial_evidence_not_bound_to_subject(
    target_text: str,
) -> None:
    assert reserve_inference_evidence(_policy_request(target_text=target_text)) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John said his children never have enough while other families lack resources.",
        "John said his children aren't having enough while other families lack resources.",
        "John's wealthy friend has enough resources to cover bills.",
        "John's wealth manager has income and savings.",
    ),
)
def test_policy_rejects_negated_or_third_party_financial_false_positives(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John's brother has savings.",
        "John's sister has assets.",
        "John's lawyer has savings.",
        "John's company has assets.",
        "John has a friend with savings.",
        "John believes Maria has savings.",
        "John thinks Maria has income.",
        "John knows Maria has savings.",
        "John is convinced Maria has savings.",
        "John was told Maria has savings.",
    ),
)
def test_policy_rejects_nonassertive_subject_financial_mentions(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John was poor at chess.",
        "John is rich in ideas.",
        "John is wealthy in experience.",
        "John is wealthy with experience.",
        "John is wealthy in ideas.",
        "Spiritually, John is wealthy.",
        "In experience, John is wealthy.",
        "Creatively, John is bankrupt.",
        "John is wealthy. In experience, not money.",
    ),
)
def test_policy_rejects_ambiguous_or_metaphorical_financial_states(
    target_text: str,
) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is None


@pytest.mark.parametrize(
    "target_text",
    (
        "John earns a salary.",
        "John has financial security and assets.",
        "John saved enough income.",
        "John is in debt.",
        "John was in debt.",
        "John is financially secure.",
        "John is financially struggling.",
        "John's savings cover household expenses.",
    ),
)
def test_policy_reserves_immediate_subject_financial_grammar(target_text: str) -> None:
    request = _policy_request(
        target_text=target_text,
        target_overrides={
            "query_reason": "decomposition_financial_resources_inference"
        },
    )

    assert reserve_inference_evidence(request) is not None


@pytest.mark.parametrize("conflict_key", ("conflicting_fact_id", "conflict_fact_id"))
def test_conflict_ids_prevent_reservation(conflict_key: str) -> None:
    selected, generic = _pressure_selected_items()
    target = _resize_for_projected_chars(
        selected,
        _item(
            "target",
            score=0.935,
            text="John has money saved and appears financially secure.",
            extra={conflict_key: "fact-conflict"},
        ),
        projected_chars=19_375,
    )
    result = ContextPacker().pack(
        bundle_id=f"ctx-{conflict_key}",
        items=(*selected, target),
        query="What might John's financial status be?",
        token_budget=10_000,
        max_rendered_chars=18_000,
    )
    selected_ids = {item.item_id for item in result.bundle.items}
    assert generic.item_id in selected_ids
    assert "target" not in selected_ids
    assert result.bundle.diagnostics["inference_reservations_selected"] == 0


@pytest.mark.parametrize("unsafe_field", ("instruction", "conflict_ids", "review_only"))
def test_policy_rejects_instruction_and_unresolved_provenance(unsafe_field: str) -> None:
    overrides: dict[str, object] = {unsafe_field: True}
    if unsafe_field == "conflict_ids":
        overrides[unsafe_field] = frozenset({"fact-1"})
    assert reserve_inference_evidence(_policy_request(target_overrides=overrides)) is None


def test_policy_never_displaces_a_coverage_protected_candidate() -> None:
    request = _policy_request()
    protected = InferenceEvidenceReservationRequest(
        query=request.query,
        pressure=request.pressure,
        rejected=request.rejected,
        selected=request.selected,
        protected_candidate_ids=frozenset({"generic"}),
    )

    assert reserve_inference_evidence(protected) is None


def test_token_pressure_never_activates_inference_reservation() -> None:
    result = ContextPacker().pack(
        bundle_id="ctx-token-pressure",
        items=(
            _item("generic", score=0.99, text="Generic inference support homework."),
            _item(
                "target",
                score=0.935,
                text="John has substantial savings. " + "word " * 300,
            ),
        ),
        query="What might John's financial status be?",
        token_budget=64,
        max_rendered_chars=18_000,
    )
    assert result.bundle.diagnostics["dropped_by_budget"] >= 1
    assert result.bundle.diagnostics["inference_reservation_attempted"] is False
    assert result.bundle.diagnostics["inference_reservations_selected"] == 0


def test_source_pressure_never_activates_inference_reservation() -> None:
    selected = tuple(
        _item(
            f"generic-{index}",
            score=0.99 - index * 0.001,
            text=f"Generic inference note {index} about homework.",
            source_id="shared-source",
            reason="decomposition_inference_support" if index == 0 else "original_query",
        )
        for index in range(4)
    )
    target = _item(
        "target",
        score=0.935,
        text="John has substantial savings and appears financially secure.",
        source_id="shared-source",
    )
    result = ContextPacker().pack(
        bundle_id="ctx-source-pressure",
        items=(*selected, target),
        query="What might John's financial status be?",
        token_budget=10_000,
        max_rendered_chars=18_000,
    )
    assert result.bundle.diagnostics["dropped_by_source_cap"] >= 1
    assert result.bundle.diagnostics["inference_reservation_attempted"] is False
    assert result.bundle.diagnostics["inference_reservations_selected"] == 0


def _policy_request(
    *,
    target_text: str = "John has money saved and appears financially secure.",
    target_overrides: dict[str, object] | None = None,
) -> InferenceEvidenceReservationRequest:
    return InferenceEvidenceReservationRequest(
        query="What might John's financial status be?",
        pressure=InferenceReservationPressure.CHARACTER_CAP,
        rejected=_policy_candidate(
            "target", target_text, rank=27, score=0.935, **(target_overrides or {})
        ),
        selected=(
            _policy_candidate(
                "generic",
                "A generic inference support note about homework and time.",
                rank=1,
                score=0.99,
            ),
        ),
    )


def _policy_candidate(
    candidate_id: str,
    text: str,
    *,
    rank: int,
    score: float,
    instruction: bool = False,
    conflict_ids: frozenset[str] = frozenset(),
    review_only: bool = False,
    query_reason: str = "decomposition_inference_support",
) -> InferenceEvidenceCandidate:
    return InferenceEvidenceCandidate(
        candidate_id=candidate_id,
        text=text,
        query_reason=query_reason,
        rank=rank,
        score=score,
        source_backed=True,
        instruction=instruction,
        conflict_ids=conflict_ids,
        review_only=review_only,
    )


def _item(
    item_id: str,
    *,
    score: float,
    text: str,
    extra: dict[str, object] | None = None,
    reason: str = "decomposition_inference_support",
    source_id: str | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(source_type="synthetic", source_id=source_id or f"source-{item_id}"),
        ),
        diagnostics={
            "memory_scope_id": "scope-synthetic",
            "score_signals": {"query_expansion_reason": reason},
            **(extra or {}),
        },
    )


def _pressure_selected_items() -> tuple[tuple[ContextItem, ...], ContextItem]:
    generic = _item(
        "generic",
        score=0.99,
        text="John finished his homework before checking the time. " + "x" * 1400,
    )
    fillers = tuple(
        _item(
            f"filler-{index:02d}",
            score=0.989 - index * 0.001,
            text=f"Independent source-backed planning note {index}. " + "z" * 400,
            reason="original_query",
        )
        for index in range(26)
    )
    selected = (generic, *fillers)
    difference = 17_977 - _rendered_char_count(selected)
    assert 0 <= difference < 4_000
    padding, remainder = divmod(difference, 3)
    resized_tail = tuple(
        _item(
            item.item_id,
            score=item.score,
            text=f"{item.text}{_word_padding(padding + (index < remainder))}",
            reason="original_query",
        )
        for index, item in enumerate(fillers[-3:])
    )
    return (generic, *fillers[:-3], *resized_tail), generic


def _resize_for_projected_chars(
    selected: tuple[ContextItem, ...],
    second: ContextItem,
    *,
    projected_chars: int,
) -> ContextItem:
    difference = projected_chars - _rendered_char_count((*selected, second))
    assert difference >= 0
    return _item(
        second.item_id,
        score=second.score,
        text=f"{second.text}{_word_padding(difference)}",
        extra=dict(second.diagnostics or {}),
    )


def _word_padding(length: int) -> str:
    if length <= 0:
        return ""
    return ("x " * ((length + 1) // 2))[: length - 1] + "x"


def _selection_state() -> _SelectionState:
    return _SelectionState(
        selected=[],
        selected_keys=set(),
        selected_answer_support_families=set(),
        selected_chunks_by_source={},
        selected_source_capped_items_by_source={},
        selected_art_style_items_by_source_group={},
    )


def _selection_state_snapshot(state: _SelectionState) -> dict[str, object]:
    return {
        "selected_item_ids": tuple(item.item_id for item in state.selected),
        "selected_keys": frozenset(state.selected_keys),
        "answer_support_family_ids": frozenset(state.selected_answer_support_families),
        "chunks_by_source": dict(state.selected_chunks_by_source),
        "source_capped_items": dict(state.selected_source_capped_items_by_source),
        "art_style_items": dict(state.selected_art_style_items_by_source_group),
        "used_tokens": state.used_tokens,
        "rendered_chars": _rendered_char_count(tuple(state.selected)),
        "source_refs": tuple(item.source_refs for item in state.selected),
        "diagnostics": tuple(item.diagnostics for item in state.selected),
    }
