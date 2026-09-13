"""Exact integer scoring boundary tests for Retrieval."""

import asyncio

import pytest

from infinity_context_core.features.context_building.application.locator_retrieval import (
    _rrf_contribution_score_picos,
)
from infinity_context_core.features.context_building.domain.locator_retrieval_filters import (
    LocatorPreferenceEvidence,
)
from infinity_context_core.features.context_building.public import (
    LocatorProviderLaneCapability,
    LocatorProviderRegistration,
    LocatorRetrievalCapability,
)
from infinity_context_core.features.context_building.tests.test_locator_retrieval import (
    FINGERPRINT,
    _canonical,
    _hit,
    _Hydrator,
    _Provider,
    _request,
    _retrieve,
)


@pytest.mark.parametrize("value", [0.1000001, 1 / 3, 9.9999999, True, 99_999, 10_000_001])
def test_provider_weights_require_exact_bounded_integer_micros(value: object) -> None:
    with pytest.raises(ValueError, match="weight_micros"):
        LocatorProviderRegistration(
            "dense",
            _Provider(),
            weight_micros=value,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="weight_micros"):
        LocatorProviderLaneCapability(
            "dense",
            True,
            True,
            value,
            True,  # type: ignore[arg-type]
        )
    bounds_type = LocatorRetrievalCapability(FINGERPRINT, "profile").bounds.__class__
    with pytest.raises(ValueError, match="weight_micros|bounds"):
        bounds_type(weight_micros=(100_000, value))  # type: ignore[arg-type]


def test_integer_rrf_exact_halves_use_round_half_even() -> None:
    assert _rrf_contribution_score_picos(100_001, 100_000, 100_000, 68) == 781_257_812
    assert _rrf_contribution_score_picos(100_005, 100_000, 100_000, 324) == 260_429_688


def test_empty_lexical_lane_preserves_dense_only_results_and_strong_hits_fuse() -> None:
    dense = _Provider((_hit("dense-only", rank=1), _hit("shared", rank=2)))
    canonical = _Hydrator((_canonical("dense-only"), _canonical("shared")))
    registrations = (
        LocatorProviderRegistration("dense", dense),
        LocatorProviderRegistration("lexical", _Provider(())),
    )

    dense_only = asyncio.run(_retrieve(registrations, canonical).execute(_request()))
    assert tuple(item.canonical_identity for item in dense_only.candidates) == (
        "dense-only",
        "shared",
    )
    assert all(
        tuple(value.provider_id for value in item.contributions) == ("dense",)
        for item in dense_only.candidates
    )

    fused = asyncio.run(
        _retrieve(
            (
                registrations[0],
                LocatorProviderRegistration(
                    "lexical", _Provider((_hit("shared", provider="lexical"),))
                ),
            ),
            canonical,
        ).execute(_request())
    )
    assert fused.candidates[0].canonical_identity == "shared"
    assert tuple(value.provider_id for value in fused.candidates[0].contributions) == (
        "dense",
        "lexical",
    )


def test_preference_evidence_rejects_cross_dimension_weight_swap() -> None:
    with pytest.raises(ValueError, match="dimension evidence"):
        LocatorPreferenceEvidence(
            score_micros=500_000,
            boost_micros=125_000,
            source_requested_weight_micros=0,
            source_matched_weight_micros=1_000_000,
            actor_requested_weight_micros=2_000_000,
            actor_matched_weight_micros=0,
        )
