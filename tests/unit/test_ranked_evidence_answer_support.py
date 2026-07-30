from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
from infinity_context_server import ranked_evidence_answer_support as support_policy
from infinity_context_server.ranked_evidence_answer_support import (
    RankedEvidenceAnswerSupportObservation,
    ranked_evidence_answer_support_metrics,
    ranked_evidence_answer_support_metrics_contract_valid,
)

_QUESTION = "What activities has Riley done?"
_EXPECTED = ("Museum visits, acrylic art; overnight trips and pool practice.",)
_QUANTITY_QUESTION = "How many items of clothing do I need to pick up or return from a store?"
_SLOT_ALIASES = {
    "museum": "activity_museum",
    "art": "activity_painting",
    "painting": "activity_painting",
    "trips": "outdoor_camping",
    "camping": "outdoor_camping",
    "practice": "activity_swimming",
    "swimming": "activity_swimming",
    "cycling": "activity_cycling",
}
_REAL_QUERY_SUPPORTED = support_policy._activity_policy.activity_inventory_query_supported
_REAL_SLOT_KEY = support_policy._activity_policy.activity_inventory_slot_key
_REAL_EVIDENCE_SLOTS = support_policy._activity_policy.activity_inventory_evidence_slots


@pytest.fixture(autouse=True)
def _activity_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    def query_supported(query: str) -> bool:
        return query == _QUESTION

    def slot_key(label: str) -> str:
        words = frozenset(label.casefold().strip(".").split())
        return next((slot for marker, slot in _SLOT_ALIASES.items() if marker in words), "")

    def evidence_slots(*, query: str, text: str) -> tuple[str, ...]:
        assert query == _QUESTION
        if text.startswith("Caroline:"):
            return ()
        words = frozenset(text.casefold().strip(".").split())
        return tuple(
            dict.fromkeys(slot for marker, slot in _SLOT_ALIASES.items() if marker in words)
        )

    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_query_supported",
        query_supported,
        raising=False,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_slot_key",
        slot_key,
        raising=False,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_evidence_slots",
        evidence_slots,
        raising=False,
    )


def _observation(
    fingerprint: str,
    text: str,
    *,
    cutoff: int = 4,
    source_refs: tuple[str, ...] = ("episode:1",),
) -> RankedEvidenceAnswerSupportObservation:
    return RankedEvidenceAnswerSupportObservation(
        cutoff=cutoff,
        fingerprint=fingerprint,
        text=text,
        source_refs=source_refs,
    )


def _full_observations(
    *,
    cutoff: int = 4,
) -> tuple[RankedEvidenceAnswerSupportObservation, ...]:
    return (
        _observation("fp-museum", "Riley: I toured a museum.", cutoff=cutoff),
        _observation("fp-paint", "Riley: I made a painting.", cutoff=cutoff),
        _observation("fp-camp", "Riley: I went camping.", cutoff=cutoff),
        _observation("fp-swim", "Riley: I started swimming.", cutoff=cutoff),
    )


def _metrics(
    observations: object = None,
    *,
    question: object = _QUESTION,
    expected_terms: object = _EXPECTED,
    expected_refs: object = (),
) -> dict[str, object]:
    return ranked_evidence_answer_support_metrics(
        _full_observations() if observations is None else observations,
        question=question,
        expected_terms=expected_terms,
        expected_refs=expected_refs,
    )


def _quantity_metrics(
    observations: tuple[RankedEvidenceAnswerSupportObservation, ...],
    *,
    expected_terms: object = ("3",),
    expected_refs: object = ("D2:1",),
) -> dict[str, object]:
    return _metrics(
        observations,
        question=_QUANTITY_QUESTION,
        expected_terms=expected_terms,
        expected_refs=expected_refs,
    )


def test_alternative_evidence_wording_supports_all_four_answer_units() -> None:
    metrics = _metrics()

    assert metrics == {
        "schema_version": "ranked-evidence-answer-support-metrics.v1",
        "applicable": True,
        "fallback_reason": None,
        "expected_unit_count": 4,
        "cutoffs": [
            {
                "cutoff": 4,
                "supported_unit_count": 4,
                "recall": 1.0,
                "complete": True,
            }
        ],
        "matches": True,
    }
    assert ranked_evidence_answer_support_metrics_contract_valid(
        metrics,
        expected_cutoffs=(4,),
    )


def test_oxford_comma_answer_is_parsed_as_four_units() -> None:
    metrics = _metrics(
        expected_terms=("Museum visits, acrylic art, overnight trips, and pool practice.",)
    )

    assert metrics["applicable"] is True
    assert metrics["expected_unit_count"] == 4
    assert metrics["matches"] is True


def test_five_distinct_supported_units_do_not_overflow() -> None:
    observations = (
        *_full_observations(cutoff=5),
        _observation(
            "fp-cycle",
            "Riley: I started cycling.",
            cutoff=5,
        ),
    )

    metrics = _metrics(
        observations,
        expected_terms=(
            "Museum visits, acrylic art, overnight trips, pool practice, and cycling.",
        ),
    )

    assert metrics["applicable"] is True
    assert metrics["expected_unit_count"] == 5
    assert metrics["cutoffs"][0]["supported_unit_count"] == 5
    assert metrics["matches"] is True


def test_real_core_helpers_support_qa16_activity_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_query_supported",
        _REAL_QUERY_SUPPORTED,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_slot_key",
        _REAL_SLOT_KEY,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_evidence_slots",
        _REAL_EVIDENCE_SLOTS,
    )
    observations = (
        _observation("real-pottery", "D1:1 Riley: I started taking a pottery class."),
        _observation("real-camping", "D1:2 Riley: I went camping."),
        _observation("real-painting", "D1:3 Riley: I started painting."),
        _observation("real-swimming", "D1:4 Riley: I started swimming."),
    )

    metrics = _metrics(
        observations,
        expected_terms=("pottery, camping, painting, and swimming",),
    )

    assert metrics["applicable"] is True
    assert metrics["expected_unit_count"] == 4
    assert metrics["cutoffs"][0]["supported_unit_count"] == 4
    assert metrics["matches"] is True


def test_real_core_helpers_do_not_credit_relational_companion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_query_supported",
        _REAL_QUERY_SUPPORTED,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_slot_key",
        _REAL_SLOT_KEY,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_evidence_slots",
        _REAL_EVIDENCE_SLOTS,
    )
    observations = (
        _observation(
            "real-companion",
            "D1:1 Jordan: I went camping.",
            cutoff=2,
        ),
        _observation(
            "real-owner",
            "D1:2 Riley: I started swimming.",
            cutoff=2,
        ),
    )

    metrics = _metrics(
        observations,
        question="What activities did Riley do with Jordan?",
        expected_terms=("camping and swimming",),
    )

    assert metrics["applicable"] is True
    assert metrics["cutoffs"][0]["supported_unit_count"] == 1
    assert metrics["matches"] is False


def test_real_core_helpers_do_not_credit_image_query_or_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_query_supported",
        _REAL_QUERY_SUPPORTED,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_slot_key",
        _REAL_SLOT_KEY,
    )
    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_evidence_slots",
        _REAL_EVIDENCE_SLOTS,
    )
    observations = (
        _observation(
            "real-owner",
            "D1:1 Riley: I started swimming.",
            cutoff=2,
        ),
        _observation(
            "real-image-exploit",
            (
                "D1:2 Riley: My kids waved while Jordan tried climbing. "
                "[Sharing image - query: climbing wall. A gym photo]"
            ),
            cutoff=2,
        ),
    )

    metrics = _metrics(
        observations,
        expected_terms=("swimming and climbing",),
    )

    assert metrics["applicable"] is True
    assert metrics["cutoffs"][0]["supported_unit_count"] == 1
    assert metrics["matches"] is False


def test_missing_one_of_four_units_reports_three_quarters_without_leaking_it() -> None:
    metrics = _metrics(_full_observations()[:3])

    assert metrics["applicable"] is True
    assert metrics["matches"] is False
    assert metrics["cutoffs"] == [
        {
            "cutoff": 4,
            "supported_unit_count": 3,
            "recall": 0.75,
            "complete": False,
        }
    ]


def test_wrong_speaker_gets_no_slot_from_core_helper() -> None:
    observations = (
        *_full_observations()[:3],
        _observation("fp-wrong-owner", "Caroline: I started swimming."),
    )

    metrics = _metrics(observations)

    assert metrics["cutoffs"][0]["supported_unit_count"] == 3
    assert metrics["matches"] is False


def test_matching_observation_without_normalized_source_refs_cannot_support() -> None:
    observations = (
        *_full_observations()[:3],
        _observation(
            "fp-no-source",
            "Riley: I started swimming.",
            source_refs=(" ", ""),
        ),
    )

    metrics = _metrics(observations)

    assert observations[-1].source_refs == ()
    assert metrics["cutoffs"][0]["supported_unit_count"] == 3
    assert metrics["matches"] is False


@pytest.mark.parametrize(
    ("expected_terms", "reason"),
    [
        (
            ("Museum visits, acrylic art, overnight trips, pool practice, and astrophysics",),
            "ambiguous_expected_unit_slots",
        ),
        (
            (
                "unit01, unit02, unit03, unit04, unit05, unit06, unit07, unit08, "
                "unit09, unit10, unit11, unit12, unit13, unit14, unit15, unit16, "
                "and unit17",
            ),
            "expected_unit_overflow",
        ),
        (
            ("Museum visits and another museum visit",),
            "ambiguous_expected_unit_slots",
        ),
    ],
)
def test_unsupported_or_ambiguous_answer_falls_back_to_exact_refs(
    expected_terms: tuple[str, ...],
    reason: str,
) -> None:
    metrics = _metrics(expected_terms=expected_terms)

    assert metrics == {
        "schema_version": "ranked-evidence-answer-support-metrics.v1",
        "applicable": False,
        "fallback_reason": reason,
        "expected_unit_count": 0,
        "cutoffs": [],
        "matches": False,
    }
    assert ranked_evidence_answer_support_metrics_contract_valid(metrics)


def test_metrics_never_expose_raw_gold_answers_or_generic_unit_slots() -> None:
    unique_gold = (
        "Museum visits, acrylic art; overnight trips and pool practice.",
        "Museum visits",
        "acrylic art",
        "overnight trips",
        "pool practice",
    )

    payload = json.dumps(_metrics(), sort_keys=True)

    assert all(value not in payload for value in unique_gold)
    assert all(slot not in payload for slot in _SLOT_ALIASES.values())
    assert frozenset(_metrics()) == {
        "schema_version",
        "applicable",
        "fallback_reason",
        "expected_unit_count",
        "cutoffs",
        "matches",
    }


def test_cutoffs_and_supported_counts_must_be_monotonic() -> None:
    first = _full_observations(cutoff=4)
    second = tuple(
        _observation(
            observation.fingerprint,
            observation.text,
            cutoff=8,
            source_refs=observation.source_refs,
        )
        for observation in first[:3]
    )

    metrics = _metrics((*first, *second))

    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "non_monotonic_support"
    assert metrics["matches"] is False


def test_observation_is_frozen_and_copies_normalized_refs() -> None:
    refs = [" episode:1 ", "episode:1", ""]
    observation = RankedEvidenceAnswerSupportObservation(
        cutoff=4,
        fingerprint="fp",
        text="Riley: I painted.",
        source_refs=refs,
    )
    refs.append("episode:2")

    assert observation.source_refs == ("episode:1",)
    with pytest.raises(FrozenInstanceError):
        observation.cutoff = 8


def test_unsupported_query_does_not_parse_post_response_expected_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_read(_: str) -> str:
        raise AssertionError("gold slot mapping must remain unread")

    monkeypatch.setattr(
        support_policy._activity_policy,
        "activity_inventory_slot_key",
        must_not_read,
    )

    metrics = _metrics(question="What color does Riley prefer?")

    assert metrics["fallback_reason"] == "unsupported_query"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda metrics: metrics.update({"raw_answer": "secret"}),
        lambda metrics: metrics["cutoffs"][0].update({"unit": "secret"}),
        lambda metrics: metrics["cutoffs"][0].update({"recall": 0.5}),
        lambda metrics: metrics.update({"matches": False}),
        lambda metrics: metrics["cutoffs"].append(
            {
                "cutoff": 3,
                "supported_unit_count": 4,
                "recall": 1.0,
                "complete": True,
            }
        ),
        lambda metrics: metrics["cutoffs"].append(
            {
                "cutoff": 8,
                "supported_unit_count": 3,
                "recall": 0.75,
                "complete": False,
            }
        ),
    ],
)
def test_contract_rejects_malformed_or_non_monotonic_payloads(mutator: object) -> None:
    metrics = deepcopy(_metrics())
    mutator(metrics)

    assert not ranked_evidence_answer_support_metrics_contract_valid(metrics)


@pytest.mark.parametrize(
    "expected_cutoffs",
    [
        (4, 4),
        (8,),
        (True,),
        (),
    ],
)
def test_contract_requires_the_exact_configured_cutoff_sequence(
    expected_cutoffs: tuple[object, ...],
) -> None:
    assert not ranked_evidence_answer_support_metrics_contract_valid(
        _metrics(),
        expected_cutoffs=expected_cutoffs,
    )


@pytest.mark.parametrize(
    "delimiter",
    (" | ", " / ", " & ", "\n"),
)
def test_unsupported_answer_delimiters_fail_closed(delimiter: str) -> None:
    metrics = _metrics(expected_terms=(f"Museum visits{delimiter}acrylic art",))

    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "ambiguous_expected_unit_slots"


def test_observation_cutoff_is_bounded_to_gate_contract() -> None:
    metrics = _metrics(
        tuple(
            _observation(
                observation.fingerprint,
                observation.text,
                cutoff=201,
                source_refs=observation.source_refs,
            )
            for observation in _full_observations()
        )
    )

    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "invalid_observations"
    malformed = deepcopy(_metrics())
    malformed["cutoffs"][0]["cutoff"] = 201
    assert not ranked_evidence_answer_support_metrics_contract_valid(
        malformed,
        expected_cutoffs=(201,),
    )


def test_locomo_quantity_counts_three_distinct_members_in_official_session() -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "locomo-colors",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("source_session_turn_refs:session_2:D2:4",),
            ),
            _observation(
                "locomo-boots",
                "user: I still need to pick up my boots from Nordstrom Rack.",
                source_refs=("source_session_turn_refs:session_2:D2:8",),
            ),
        ),
    )

    assert metrics["applicable"] is True
    assert metrics["expected_unit_count"] == 3
    assert metrics["cutoffs"] == [
        {
            "cutoff": 4,
            "supported_unit_count": 3,
            "recall": 1.0,
            "complete": True,
        }
    ]
    assert metrics["matches"] is True


def test_longmemeval_embedded_same_session_counts_three_and_rejects_decoy() -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "longmem-official",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("longmemeval:quantity-case:session-0012",),
            ),
            _observation(
                "longmem-official-boots",
                "user: I still need to pick up my boots from Nordstrom Rack.",
                source_refs=("longmemeval:quantity-case:session-0012",),
            ),
            _observation(
                "longmem-decoy",
                "user: I still need to return my coat to Zara.",
                source_refs=("longmemeval:quantity-case:session-0020",),
            ),
        ),
        expected_refs=("session-0012",),
    )

    assert metrics["expected_unit_count"] == 3
    assert metrics["cutoffs"][0]["supported_unit_count"] == 3
    assert metrics["matches"] is True


def test_quantity_unions_distinct_members_across_multiple_official_sessions() -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "union-first",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("source_session_turn_refs:session_2:D2:4",),
            ),
            _observation(
                "union-second",
                "user: I still need to pick up my boots from Nordstrom Rack.",
                source_refs=("source_session_turn_refs:session_4:D4:8",),
            ),
        ),
        expected_refs=("D2:1", "session_4"),
    )

    assert metrics["cutoffs"][0]["supported_unit_count"] == 3
    assert metrics["matches"] is True


def test_quantity_incomplete_support_fails_match_without_leaking_values() -> None:
    gold = "three"
    official_session = "session-0031"
    metrics = _quantity_metrics(
        (
            _observation(
                "incomplete",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=(f"longmemeval:private-case:{official_session}",),
            ),
        ),
        expected_terms=(gold,),
        expected_refs=(official_session,),
    )

    assert metrics["cutoffs"][0] == {
        "cutoff": 4,
        "supported_unit_count": 2,
        "recall": 2 / 3,
        "complete": False,
    }
    assert metrics["matches"] is False
    payload = json.dumps(metrics, sort_keys=True)
    assert gold not in payload
    assert official_session not in payload
    assert "red" not in payload
    assert "blue" not in payload
    assert "member_" not in payload


@pytest.mark.parametrize(
    "expected_terms",
    [
        ("3 items",),
        ("about three",),
        ("03",),
        ("seventeen",),
        ("3", "three"),
    ],
)
def test_quantity_gold_parser_accepts_only_exact_bounded_count(
    expected_terms: tuple[str, ...],
) -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "strict-gold",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("source_session_turn_refs:session_2:D2:4",),
            ),
        ),
        expected_terms=expected_terms,
    )

    assert metrics["applicable"] is False
    assert metrics["matches"] is False


def test_quantity_does_not_derive_retrieval_terms_from_gold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_expand(**_: object) -> tuple[str, ...]:
        raise AssertionError("post-response gold must not seed retrieval terms")

    monkeypatch.setattr(
        support_policy._quantity_policy,
        "quantity_evidence_retrieval_terms",
        must_not_expand,
    )
    metrics = _quantity_metrics(
        (
            _observation(
                "no-gold-retrieval",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("source_session_turn_refs:session_2:D2:4",),
            ),
        ),
    )

    assert metrics["applicable"] is True


def test_quantity_fails_closed_for_ambiguous_session_source_ref() -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "ambiguous-session",
                "user: I still need to return my red and blue shirts to the store.",
                source_refs=("longmemeval:quantity-case:session-0012:session-0020",),
            ),
        ),
        expected_refs=("session-0012",),
    )

    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "quantity_policy_error"


def test_quantity_fails_closed_for_official_and_unscoped_source_refs() -> None:
    metrics = _quantity_metrics(
        (
            _observation(
                "official-plus-unscoped-decoy",
                (
                    "user: I still need to return my red and blue shirts to the store. "
                    "I also need to pick up my boots from Nordstrom Rack."
                ),
                source_refs=(
                    "longmemeval:quantity-case:session-0012",
                    "unscoped-decoy-source",
                ),
            ),
        ),
        expected_refs=("session-0012",),
    )

    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "quantity_policy_error"
    assert metrics["matches"] is False
