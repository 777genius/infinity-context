"""Temporal contract mapping checks for the memory facts server feature."""

from datetime import UTC, datetime

import pytest
from infinity_context_contracts.features.memory_facts import (
    MemoryFactEpistemicContextDto,
    MemoryFactFreshnessDto,
    MemoryFactRetentionDto,
    MemoryFactSourceRefDto,
    MemoryFactTemporalDto,
    RememberFactRequestDto,
)
from infinity_context_core.features.memory_facts import public as memory_facts
from infinity_context_server.features.context_building.contracts import BuildContextHttpRequest
from infinity_context_server.features.memory_facts import public as server_public
from infinity_context_server.features.memory_facts.contracts import (
    MemoryFactTemporalHttpRequest,
)
from infinity_context_server.features.memory_facts.temporal_contracts import (
    ConfirmFactHttpRequest,
)


def test_memory_facts_mapper_preserves_independent_temporal_semantics() -> None:
    request = RememberFactRequestDto(
        text="The release branch uses PostgreSQL.",
        source_refs=(MemoryFactSourceRefDto(source_type="document", source_id="doc_1"),),
        space_id="space_1",
        memory_scope_id="scope_1",
        classification="restricted",
        temporal=MemoryFactTemporalDto(
            kind="state",
            observed_at="2026-08-05T10:00:00+00:00",
            valid_from="2026-08-01T00:00:00+00:00",
            basis="asserted",
            precision="day",
        ),
        retention=MemoryFactRetentionDto(
            ttl_policy="review",
            context_expires_at="2026-09-01T00:00:00+00:00",
            purge_after="2026-10-01T00:00:00+00:00",
        ),
        epistemic_context=MemoryFactEpistemicContextDto(
            mode="perspective",
            asserted_by="user-1",
            perspective_subject="team-1",
        ),
    )

    command = server_public.remember_fact_command_from_contract(request)

    assert command.quality is not None
    assert command.quality.classification == "restricted"
    assert command.temporal_extent is not None
    assert command.temporal_extent.kind is memory_facts.FactTemporalKind.STATE
    assert command.temporal_extent.valid_from == datetime(2026, 8, 1, tzinfo=UTC)
    assert command.freshness is None
    assert command.retention is not None
    assert command.retention.context_expires_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert command.epistemic_context is not None
    assert command.epistemic_context.perspective_subject == "team-1"


def test_memory_facts_mapper_rejects_unaudited_initial_confirmation() -> None:
    request = RememberFactRequestDto(
        text="The release branch uses PostgreSQL.",
        source_refs=(MemoryFactSourceRefDto(source_type="document", source_id="doc_1"),),
        space_id="space_1",
        memory_scope_id="scope_1",
        temporal=MemoryFactTemporalDto(
            kind="state",
            observed_at="2026-08-05T10:00:00+00:00",
            basis="asserted",
        ),
        freshness=MemoryFactFreshnessDto(
            last_confirmed_at="2026-08-05T10:00:00+00:00",
            confirmation_basis="manual_review",
        ),
    )

    with pytest.raises(ValueError, match="cannot set freshness"):
        server_public.remember_fact_command_from_contract(request)


def test_memory_fact_http_create_rejects_governance_only_temporal_basis() -> None:
    with pytest.raises(ValueError):
        MemoryFactTemporalHttpRequest.model_validate(
            {
                "kind": "state",
                "observed_at": "2026-08-05T10:00:00+00:00",
                "basis": "confirmed",
            }
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    (
        (
            MemoryFactTemporalHttpRequest,
            {"kind": "state", "observed_at": "2026-08-05T10:00:00"},
        ),
        (
            ConfirmFactHttpRequest,
            {
                "expected_version": 1,
                "confirmed_at": "2026-08-05T10:00:00",
                "confirmation_basis": "manual_review",
                "evidence_refs": [
                    {
                        "source_ref": {
                            "source_type": "document",
                            "source_id": "doc_1",
                        }
                    }
                ],
            },
        ),
        (
            BuildContextHttpRequest,
            {"query": "current architecture", "as_of": "2026-08-05T10:00:00"},
        ),
    ),
)
def test_temporal_http_contracts_reject_naive_datetimes(model, payload) -> None:
    with pytest.raises(ValueError, match="timezone"):
        model.model_validate(payload)
