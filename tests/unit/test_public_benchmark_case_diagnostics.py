from __future__ import annotations

from dataclasses import dataclass

from infinity_context_server.public_benchmark_case_diagnostics import (
    case_evidence_ref_previews,
    case_evidence_refs,
    response_evidence_text,
)


@dataclass(frozen=True)
class _Case:
    metadata: dict[str, object]


def test_response_evidence_text_includes_public_api_citation_fields() -> None:
    evidence = response_evidence_text(
        {
            "items": [
                {
                    "text": "snippet without the exact dialogue marker",
                    "citations": [
                        {
                            "source_type": "locomo_turn",
                            "source_id": "locomo:conv-8:session_2:D2:6:turn",
                            "chunk_id": "chunk-D2-6",
                            "quote_preview": "D2:6 Priya chose Osaka for the conference",
                        }
                    ],
                }
            ],
        }
    )

    assert "D2:6" in evidence
    assert "Osaka for the conference" in evidence


def test_response_evidence_text_includes_string_source_refs() -> None:
    evidence = response_evidence_text(
        {
            "items": [
                {
                    "text": "snippet without the exact dialogue marker",
                    "source_refs": ["D3:9"],
                }
            ],
        }
    )

    assert "D3:9" in evidence


def test_case_evidence_refs_accepts_evidence_terms_alias() -> None:
    refs = case_evidence_refs(_Case(metadata={"evidence_terms": ["D1:2", "D2:4"]}))

    assert refs == ("D1:2", "D2:4")


def test_case_evidence_refs_flattens_nested_locomo_evidence() -> None:
    case = _Case(
        metadata={
            "evidence": ["D1:1", ["D1:4", "D1:missing"], {"ignored": "D1:5"}],
            "evidence_previews": {
                "D1:1": "Caroline wants to pursue counseling.",
                "D1:4": "Mental health work feels like the right path.",
            },
        }
    )

    refs = case_evidence_refs(case)

    assert refs == ("D1:1", "D1:4", "D1:missing")
    assert case_evidence_ref_previews(case, refs=refs) == (
        "D1:1: Caroline wants to pursue counseling.",
        "D1:4: Mental health work feels like the right path.",
    )
