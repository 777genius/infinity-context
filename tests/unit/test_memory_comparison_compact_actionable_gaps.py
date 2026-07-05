from __future__ import annotations

from infinity_context_server import memory_comparison_benchmark as benchmark


def _ranked_gap(index: int) -> dict[str, object]:
    return {
        "rank": index,
        "impact_count": 10 - index,
        "impact_rate": 0.123456789,
        "severity": "blocking",
        "category": "query_plan",
        "gap": f"gap-{index}",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "sample_case_ids": [
            f"case-{index}-1",
            f"case-{index}-2",
            f"case-{index}-3",
            f"case-{index}-4",
        ],
        "action": "Verbose remediation text stays out of compact summaries.",
        "samples": [{"case_id": f"case-{index}-1", "text": "fixture detail"}],
        "evidence": {"sample": "diagnostic detail"},
    }


def test_compact_actionable_gaps_bounds_and_excludes_verbose_fields() -> None:
    compact = benchmark._compact_actionable_gaps(
        [_ranked_gap(index) for index in range(1, 8)]
    )

    assert len(compact) == 5
    assert compact[0] == {
        "rank": 1,
        "impact_count": 9,
        "impact_rate": 0.123457,
        "severity": "blocking",
        "category": "query_plan",
        "gap": "gap-1",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "sample_case_ids": ["case-1-1", "case-1-2", "case-1-3"],
    }
    assert compact[-1]["gap"] == "gap-5"
    assert all("action" not in gap for gap in compact)
    assert all("samples" not in gap for gap in compact)
    assert all("evidence" not in gap for gap in compact)


def test_compact_fast_gate_summary_surfaces_bounded_actionable_gaps(
    monkeypatch,
) -> None:
    ranked_gaps = [_ranked_gap(index) for index in range(1, 7)]

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "evaluation_count": 1,
            "expected_case_count": 1,
            "actionable_gap_summary": {
                "top_gap": ranked_gaps[0],
                "ranked_gaps": ranked_gaps,
                "blocking_gap_count": 6,
                "diagnostic_gap_count": 0,
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))

    assert summary["top_gap"] == ranked_gaps[0]
    assert len(summary["top_actionable_gaps"]) == 5
    assert summary["top_actionable_gaps"][0] == {
        "rank": 1,
        "impact_count": 9,
        "impact_rate": 0.123457,
        "severity": "blocking",
        "category": "query_plan",
        "gap": "gap-1",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "sample_case_ids": ["case-1-1", "case-1-2", "case-1-3"],
    }
    assert all("action" not in gap for gap in summary["top_actionable_gaps"])
    assert all("samples" not in gap for gap in summary["top_actionable_gaps"])
    assert all("evidence" not in gap for gap in summary["top_actionable_gaps"])
