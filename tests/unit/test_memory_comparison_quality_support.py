from __future__ import annotations

from infinity_context_server.memory_comparison_quality_support import (
    bundle_weak_support_reasons,
)


def test_bundle_weak_support_reasons_reports_primary_low_answerability() -> None:
    bundle = {
        "items": [
            {
                "role": "primary",
                "source_refs": ["D1:1"],
                "answerability_score": 0.42,
                "source_locality_score": 0.8,
            },
            {
                "role": "supporting",
                "source_refs": ["D1:2"],
                "answerability_score": 0.8,
                "source_locality_score": 0.8,
            },
        ]
    }

    assert bundle_weak_support_reasons(bundle) == (
        "weak_selected_support",
        "low_answerability_support",
    )


def test_bundle_weak_support_reasons_reports_primary_weak_source_locality() -> None:
    bundle = {
        "items": [
            {
                "role": "primary",
                "source_refs": ["D9:1"],
                "answerability_score": 0.82,
                "source_locality_score": 0.3,
            },
            {
                "role": "location_support",
                "source_refs": ["D1:2"],
                "answerability_score": 0.8,
                "source_locality_score": 0.8,
            },
        ]
    }

    assert bundle_weak_support_reasons(bundle) == (
        "weak_selected_support",
        "weak_source_locality_support",
    )
