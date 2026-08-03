from infinity_context_core.application.context_diagnostics import _BUNDLE_COUNTER_KEYS
from infinity_context_sdk.context import context_bundle_from_response
from infinity_context_sdk.context_bundle_diagnostics import ContextBundleDiagnostics


def test_sdk_bundle_diagnostics_preserves_legacy_positional_field_order() -> None:
    legacy_sentinels = tuple(object() for _ in range(220))

    diagnostics = ContextBundleDiagnostics(*legacy_sentinels)

    assert diagnostics.context_assembly_version is legacy_sentinels[0]
    assert diagnostics.raw is legacy_sentinels[16]
    assert diagnostics.vector_status is legacy_sentinels[17]
    assert diagnostics.retrieval_trace is legacy_sentinels[219]
    assert diagnostics.ranked_evidence_candidate_count == 0


def test_sdk_bundle_counters_clamp_negative_payload_values() -> None:
    counters = {key: -(index + 1) for index, key in enumerate(_BUNDLE_COUNTER_KEYS)}

    bundle = context_bundle_from_response(
        {
            "data": {
                "bundle_id": "ctx_negative_counter_contract",
                "rendered_text": "",
                "diagnostics": {
                    "context_assembly_version": "context-v2-hybrid-explainable",
                    "consistency_mode": "best_effort",
                    **counters,
                },
                "items": [],
            }
        }
    )

    for key in _BUNDLE_COUNTER_KEYS:
        assert getattr(bundle.diagnostics, key) == 0
