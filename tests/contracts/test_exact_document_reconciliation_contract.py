from infinity_context_contracts.features.document_ingestion import (
    EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
    ExactDocumentReconciliationResultDto,
    ReconcileExactDocumentRequestDto,
)


def test_exact_reconciliation_contract_is_versioned_and_plain_json() -> None:
    request = ReconcileExactDocumentRequestDto(
        space_id="space-1",
        memory_scope_id="scope-1",
        thread_id="thread-1",
        source_type="opaque-kind",
        source_external_id="opaque-id",
        projection_generation="projection-2",
        profile_generation="profile-4",
        idempotency_key="mutation-9",
    )
    assert request.to_dict() == {
        "contract_version": EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
        "space_id": "space-1",
        "memory_scope_id": "scope-1",
        "thread_id": "thread-1",
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "projection_generation": "projection-2",
        "profile_generation": "profile-4",
        "idempotency_key": "mutation-9",
        "deadline_ms": 5000,
    }
    response = ExactDocumentReconciliationResultDto(
        contract_version=EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
        state="indexed",
        source_type=request.source_type,
        source_external_id=request.source_external_id,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        document_id="doc-1",
        canonical_status="active",
        projection_generation=request.projection_generation,
        profile_generation=request.profile_generation,
        visibility="indexed",
        idempotency_key_matches=True,
    )
    assert response.to_dict()["data"]["visibility"] == "indexed"


def test_exact_reconciliation_contract_rejects_unbounded_or_wrong_versions() -> None:
    common = dict(
        space_id="space",
        memory_scope_id="scope",
        source_type="kind",
        source_external_id="id",
    )
    for deadline in (0, 10_001):
        try:
            ReconcileExactDocumentRequestDto(**common, deadline_ms=deadline)
        except ValueError:
            pass
        else:
            raise AssertionError("unbounded deadline accepted")
    try:
        ReconcileExactDocumentRequestDto(**common, contract_version="v0")
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported contract accepted")
