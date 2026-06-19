from infinity_context_server.eval_case_runner import (
    _MAX_DIAGNOSTIC_MISMATCH_FAILURES,
    _case_failures,
    _required_case_metrics,
    _required_diagnostic_mismatches,
    _required_diagnostics_ok,
    _required_mapping_group_mismatches,
)
from infinity_context_server.eval_types import EvalCase


def test_required_diagnostic_failures_are_bounded_and_redacted() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    required = tuple(
        (f"diag_{index}", f"expected {raw_secret}")
        for index in range(_MAX_DIAGNOSTIC_MISMATCH_FAILURES + 4)
    )
    diagnostics = {
        f"diag_{index}": f"actual Bearer {raw_secret}"
        for index in range(_MAX_DIAGNOSTIC_MISMATCH_FAILURES + 4)
    }

    mismatches = _required_diagnostic_mismatches(diagnostics, required=required)
    failures = _case_failures(
        case=EvalCase(
            case_id="hybrid_document_beats_single_source",
            category="hybrid_retrieval",
            space_id="space_eval",
            memory_scope_ids=("scope_eval",),
            query="hybrid retrieval",
            required_diagnostics=required,
        ),
        recall_ok=True,
        precision_ok=True,
        evidence_guard=True,
        diagnostic_mismatches=mismatches,
        token_overflow=False,
        item_ids=("chunk_hybrid",),
    )

    rendered = repr(failures)
    assert len(mismatches) == _MAX_DIAGNOSTIC_MISMATCH_FAILURES
    assert mismatches[0]["key"] == "diag_0"
    assert mismatches[0]["operator"] == "eq"
    assert raw_secret not in rendered
    assert "[redacted]" in rendered
    assert failures == (
        {
            "case_id": "hybrid_document_beats_single_source",
            "category": "hybrid_retrieval",
            "reason": "required_diagnostics_missing",
            "item_ids": ["chunk_hybrid"],
            "diagnostic_mismatches": list(mismatches),
        },
    )


def test_required_diagnostics_support_operator_requirements() -> None:
    diagnostics = {
        "hybrid_items_used": 2,
        "retrieval_sources_used": ["vector_chunks", "keyword_chunks"],
        "context_assembly_version": "context-v2-hybrid-explainable",
    }

    assert _required_diagnostics_ok(
        diagnostics,
        required=(
            ("hybrid_items_used", "gte", 1),
            ("retrieval_sources_used", "contains", "keyword_chunks"),
            ("context_assembly_version", "eq", "context-v2-hybrid-explainable"),
        ),
    )

    mismatches = _required_diagnostic_mismatches(
        diagnostics,
        required=(
            ("hybrid_items_used", "gte", 3),
            ("retrieval_sources_used", "contains", "graph_facts"),
            ("context_assembly_version", "unknown_operator", "context-v2"),
        ),
    )

    assert mismatches == (
        {
            "key": "hybrid_items_used",
            "operator": "gte",
            "expected": 3,
            "actual": 2,
        },
        {
            "key": "retrieval_sources_used",
            "operator": "contains",
            "expected": "graph_facts",
            "actual": "['vector_chunks', 'keyword_chunks']",
        },
        {
            "key": "context_assembly_version",
            "operator": "unknown_operator",
            "expected": "context-v2",
            "actual": "context-v2-hybrid-explainable",
        },
    )


def test_required_mapping_groups_match_source_refs_and_nested_citations() -> None:
    source_refs = (
        {
            "source_type": "asset_extraction",
            "source_id": "quality-mm-extract",
            "page_number": 2,
            "time_start_ms": 1200,
            "time_end_ms": 5400,
            "bbox": [12.0, 32.0, 300.0, 88.0],
            "quote_preview": "Project Atlas invoice appears in OCR.",
        },
    )
    citations = (
        {
            "source_type": "asset_extraction",
            "source_id": "quality-mm-extract",
            "page_number": 2,
            "time_range_ms": {"start": 1200, "end": 5400},
            "bbox": [12.0, 32.0, 300.0, 88.0],
            "label": "[1] asset_extraction quality-mm-extract p.2 1200-5400ms bbox",
        },
    )

    assert (
        _required_mapping_group_mismatches(
            source_refs,
            required=(
                (
                    ("source_type", "eq", "asset_extraction"),
                    ("source_id", "eq", "quality-mm-extract"),
                    ("page_number", "eq", 2),
                    ("bbox", "eq", [12.0, 32.0, 300.0, 88.0]),
                    ("quote_preview", "contains", "Project Atlas invoice"),
                ),
            ),
        )
        == ()
    )
    assert (
        _required_mapping_group_mismatches(
            citations,
            required=(
                (
                    ("source_type", "eq", "asset_extraction"),
                    ("time_range_ms.start", "eq", 1200),
                    ("time_range_ms.end", "eq", 5400),
                    ("label", "contains", "bbox"),
                ),
            ),
        )
        == ()
    )

    mismatches = _required_mapping_group_mismatches(
        citations,
        required=((("source_id", "eq", "wrong-mm-extract"),),),
    )

    assert mismatches == (
        {
            "group_index": 0,
            "candidate_count": 1,
            "required": [
                {
                    "key": "source_id",
                    "operator": "eq",
                    "expected": "wrong-mm-extract",
                }
            ],
        },
    )


def test_case_failures_include_source_ref_and_citation_requirements() -> None:
    case = EvalCase(
        case_id="multimodal_source_refs_recall_with_citations",
        category="documents",
        space_id="space_eval",
        memory_scope_ids=("scope_eval",),
        query="Project Atlas screenshot OCR",
    )

    failures = _case_failures(
        case=case,
        recall_ok=True,
        precision_ok=True,
        evidence_guard=True,
        diagnostic_mismatches=(),
        source_ref_mismatches=({"group_index": 0, "candidate_count": 0, "required": []},),
        citation_mismatches=({"group_index": 0, "candidate_count": 0, "required": []},),
        token_overflow=False,
        item_ids=("chunk_mm",),
    )

    assert failures == (
        {
            "case_id": "multimodal_source_refs_recall_with_citations",
            "category": "documents",
            "reason": "required_source_refs_missing",
            "item_ids": ["chunk_mm"],
            "source_ref_mismatches": [
                {"group_index": 0, "candidate_count": 0, "required": []}
            ],
        },
        {
            "case_id": "multimodal_source_refs_recall_with_citations",
            "category": "documents",
            "reason": "required_citations_missing",
            "item_ids": ["chunk_mm"],
            "citation_mismatches": [
                {"group_index": 0, "candidate_count": 0, "required": []}
            ],
        },
    )


def test_required_case_metrics_report_missing_required_cases() -> None:
    metrics = _required_case_metrics(
        case_ids=("specific_target_beats_similar_project", "unrelated_capture_has_no_candidates"),
        required_case_ids=(
            "specific_target_beats_similar_project",
            "event_call_beats_recent_chat",
            "unrelated_capture_has_no_candidates",
        ),
    )

    assert metrics == {
        "required_case_count": 3,
        "required_cases_present": 2,
        "missing_required_case_count": 1,
        "missing_required_cases": ["event_call_beats_recent_chat"],
        "required_case_coverage_rate": 0.6667,
    }
