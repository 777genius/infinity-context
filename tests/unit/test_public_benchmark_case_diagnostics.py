from __future__ import annotations

from infinity_context_server.public_benchmark_case_diagnostics import (
    response_evidence_text,
)


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
