"""Fail-closed response contract for provider-free document seeding."""

from __future__ import annotations

from infinity_context_server.public_benchmark_http import response_data
from infinity_context_server.public_benchmark_models import BenchmarkHttpResponsePort


def document_seed_response_accepted(response: BenchmarkHttpResponsePort) -> bool:
    """Accept a created document or an explicit canonical-content deduplication."""

    if response.status_code not in {200, 201}:
        return False
    data = response_data(response)
    if not _nonempty_text(data.get("id")):
        return False
    if response.status_code == 201:
        return True
    return data.get("indexing_status") == "already_indexed_or_pending"


def require_document_seed(response: BenchmarkHttpResponsePort, failure: Exception) -> None:
    """Raise the caller's bounded failure when the response is not authoritative."""

    if not document_seed_response_accepted(response):
        raise failure


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
