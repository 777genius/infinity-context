"""Exact integer scoring boundary tests for Retrieval V2."""

import pytest

from infinity_context_core.features.context_building.application.locator_retrieval_v2 import (
    _rrf_contribution_score_picos,
)
from infinity_context_core.features.context_building.domain.locator_retrieval_v2_filters import (
    LocatorPreferenceEvidenceV2,
)
from infinity_context_core.features.context_building.public import (
    LocatorProviderLaneCapabilityV2,
    LocatorProviderRegistrationV2,
    LocatorRetrievalCapabilityV2,
)
from infinity_context_core.features.context_building.tests.test_locator_retrieval_v2 import (
    FINGERPRINT,
    _Provider,
)


@pytest.mark.parametrize("value", [0.1000001, 1 / 3, 9.9999999, True, 99_999, 10_000_001])
def test_provider_weights_require_exact_bounded_integer_micros(value: object) -> None:
    with pytest.raises(ValueError, match="weight_micros"):
        LocatorProviderRegistrationV2(
            "dense",
            _Provider(),
            weight_micros=value,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="weight_micros"):
        LocatorProviderLaneCapabilityV2(
            "dense",
            True,
            True,
            value,
            True,  # type: ignore[arg-type]
        )
    bounds_type = LocatorRetrievalCapabilityV2(FINGERPRINT, "profile").bounds.__class__
    with pytest.raises(ValueError, match="weight_micros|bounds"):
        bounds_type(weight_micros=(100_000, value))  # type: ignore[arg-type]


def test_integer_rrf_exact_halves_use_round_half_even() -> None:
    assert _rrf_contribution_score_picos(100_001, 100_000, 100_000, 68) == 781_257_812
    assert _rrf_contribution_score_picos(100_005, 100_000, 100_000, 324) == 260_429_688


def test_preference_evidence_rejects_cross_dimension_weight_swap() -> None:
    with pytest.raises(ValueError, match="dimension evidence"):
        LocatorPreferenceEvidenceV2(
            score_micros=500_000,
            boost_micros=125_000,
            source_requested_weight_micros=0,
            source_matched_weight_micros=1_000_000,
            actor_requested_weight_micros=2_000_000,
            actor_matched_weight_micros=0,
        )
