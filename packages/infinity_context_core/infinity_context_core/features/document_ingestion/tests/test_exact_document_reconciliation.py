from __future__ import annotations

import asyncio

import pytest

from infinity_context_core.features.document_ingestion.application.reconciliation import (
    ReconcileExactDocumentHandler,
    ReconcileExactDocumentQuery,
)
from infinity_context_core.features.document_ingestion.domain.reconciliation import (
    ExactDocumentIdentity,
    ExactDocumentObservation,
    reconcile_exact_document,
)
from infinity_context_core.features.document_ingestion.domain.source_document import (
    DocumentIngestionScope,
    SourceDocumentOrigin,
)


def _identity(**changes: str) -> ExactDocumentIdentity:
    values = {
        "scope": DocumentIngestionScope("space", "scope", "thread"),
        "origin": SourceDocumentOrigin("consumer-document", "opaque-42"),
        "projection_generation": "projection-7",
        "profile_generation": "profile-3",
    }
    values.update(changes)
    return ExactDocumentIdentity(**values)  # type: ignore[arg-type]


def _observation(**changes: object) -> ExactDocumentObservation:
    values = {
        "document_id": "doc-1",
        "canonical_status": "active",
        "projection_generation": "projection-7",
        "profile_generation": "profile-3",
        "visibility": "accepted",
        "idempotency_key_matches": True,
    }
    values.update(changes)
    return ExactDocumentObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("visibility", "state"),
    [("accepted", "present"), ("processing", "processing"), ("indexed", "indexed")],
)
def test_reconciliation_distinguishes_acceptance_processing_and_queryable_visibility(
    visibility: str, state: str
) -> None:
    result = reconcile_exact_document(_identity(), (_observation(visibility=visibility),))
    assert result.state == state
    assert result.visibility == visibility
    assert result.document_id == "doc-1"
    assert result.idempotency_key_matches is True


def test_absence_deleted_and_superseded_are_never_queryable() -> None:
    assert reconcile_exact_document(_identity(), ()).state == "deleted_or_proven_absent"
    for status in ("deleted", "superseded"):
        result = reconcile_exact_document(
            _identity(), (_observation(canonical_status=status, visibility="indexed"),)
        )
        assert result.state == "deleted_or_proven_absent"


def test_duplicates_and_wrong_exact_bindings_fail_closed() -> None:
    identity = _identity()
    assert reconcile_exact_document(identity, (_observation(), _observation())).state == "conflict"
    assert (
        reconcile_exact_document(identity, (_observation(projection_generation="wrong"),)).state
        == "conflict"
    )
    assert (
        reconcile_exact_document(identity, (_observation(profile_generation="wrong"),)).state
        == "unavailable"
    )
    assert (
        reconcile_exact_document(identity, (_observation(binding_conflict=True),)).state
        == "conflict"
    )


def test_application_handler_is_read_only_and_performs_one_bounded_observation() -> None:
    class ObservationPort:
        calls = 0

        async def observe_exact_document(self, identity, *, idempotency_key=None):
            self.calls += 1
            assert identity == _identity()
            assert idempotency_key == "mutation-1"
            return (_observation(visibility="processing"),)

    port = ObservationPort()
    result = asyncio.run(
        ReconcileExactDocumentHandler(port).execute(
            ReconcileExactDocumentQuery(_identity(), "mutation-1")
        )
    )
    assert result.state == "processing"
    assert port.calls == 1
