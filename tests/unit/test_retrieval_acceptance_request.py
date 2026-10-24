"""Catch invalid real-store fixture requests even when services are unavailable."""

from __future__ import annotations

import pytest
from infinity_context_server.features.context_building.public import ContextRequest
from pydantic import ValidationError

from tests.context_retrieval_test_support import retrieval_context_payload


def test_real_store_retrieval_payload_matches_public_context_request():
    request = ContextRequest.model_validate(retrieval_context_payload())
    assert request.max_chunks == request.max_evidence_items == 1
    assert request.max_facts == 0
    assert request.token_budget == 512


def test_public_context_request_still_rejects_deployment_only_char_budget():
    with pytest.raises(ValidationError, match="max_rendered_chars"):
        ContextRequest.model_validate({**retrieval_context_payload(), "max_rendered_chars": 1024})
