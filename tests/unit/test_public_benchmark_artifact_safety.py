from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server.public_benchmark import (
    CASE_SELECTION_FIRST,
    run_public_memory_benchmark,
)


def test_public_benchmark_result_redacts_requested_case_diagnostics(
    tmp_path: Path,
) -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    dataset = tmp_path / "dataset.json"
    report = tmp_path / "report.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "benchmark": "longmemeval",
                    "case_id": "info-1",
                    "question": "Where is marker 1?",
                    "expected_terms": ["MARKER_1"],
                    "documents": ["MARKER_1 is in the notes."],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=1,
        case_selection_strategy=CASE_SELECTION_FIRST,
        case_ids=(f"missing-case {bearer_payload}",),
        report_out=report,
    )
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    rendered = json.dumps({"result": result, "report": report_payload}, sort_keys=True)

    assert "Bearer" not in rendered
    assert result["requested_case_ids"] == ["missing-case [redacted]"]
    assert result["case_selection"]["requested_case_ids"] == ["missing-case [redacted]"]
    assert result["case_selection"]["missing_case_ids"] == ["missing-case [redacted]"]
    assert result["failures"][0]["case_id"] == "missing-case [redacted]"
