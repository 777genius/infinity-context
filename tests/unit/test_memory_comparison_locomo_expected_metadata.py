from __future__ import annotations

import hashlib

import pytest
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_corpus_user_id,
)
from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoOfficialTurnsTransportRequest,
    RunScopedLocomoTransportEvidenceKey,
    public_locomo_timestamp_transport_evidence,
)

_RUN_ID = "run-transport-1"
_TIMESTAMP = 1_683_554_160


def _metadata() -> dict[str, object]:
    source_id = "locomo:corpus-a:session_1:D1:1:turn"
    return {
        "benchmark": "locomo",
        "case_id": "corpus-a:qa:1",
        "corpus_key": "corpus-a",
        "source_external_id": source_id,
        "source_id": source_id,
        "session_key": "session_1",
        "session_date": "1:56 pm on 8 May, 2023",
        "dia_id": "D1:1",
        "role": "user",
        "speaker": "Caroline",
        "locomo_evidence_ref": "D1:1",
    }


def _request(
    metadata: dict[str, object], *, timestamp: int = _TIMESTAMP
) -> LocomoOfficialTurnsTransportRequest:
    return LocomoOfficialTurnsTransportRequest.create(
        messages=({"role": "user", "content": "official LoCoMo turn D1:1"},),
        user_id=mem0_benchmark_corpus_user_id(_RUN_ID, str(metadata["corpus_key"])),
        run_id=_RUN_ID,
        metadata=metadata,
        timestamp=timestamp,
        idempotency_key=str(metadata["source_id"]),
    )


def _expected() -> ExpectedOfficialLocomoTurn:
    metadata = _metadata()
    return ExpectedOfficialLocomoTurn.create(
        run_id=_RUN_ID,
        corpus_key="corpus-a",
        source_external_id=str(metadata["source_external_id"]),
        source_id=str(metadata["source_id"]),
        session_key="session_1",
        dia_id="D1:1",
        speaker="Caroline",
        session_date="1:56 pm on 8 May, 2023",
        trigger_case_id="corpus-a:qa:1",
        role="user",
        content="official LoCoMo turn D1:1",
        timestamp=_TIMESTAMP,
    )


@pytest.mark.parametrize("mutation", ("mallory", "future_date", "other_trigger_qa"))
def test_issuer_rejects_observed_expected_metadata_mutations(mutation: str) -> None:
    metadata = _metadata()
    timestamp = _TIMESTAMP
    if mutation == "mallory":
        metadata["speaker"] = "Mallory"
    elif mutation == "future_date":
        metadata["session_date"] = "1:56 pm on 8 May, 2099"
        timestamp = 4_081_931_760
    else:
        metadata["case_id"] = "corpus-a:qa:2"
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    with pytest.raises(ValueError, match="differs from expected"):
        key.issue(_request(metadata, timestamp=timestamp), expected_turn=_expected())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("speaker", "Mall\u00f3ry"),
        ("speaker", "M" * 81),
        ("session_date", "1:56 PM on 8 May, 2023"),
        ("session_date", "1:56 pm on 8 May, 2023\u200b"),
    ),
)
def test_request_rejects_noncanonical_loader_metadata(field: str, value: str) -> None:
    metadata = _metadata()
    metadata[field] = value
    with pytest.raises(ValueError, match=field):
        _request(metadata)


def test_receipt_binds_trigger_case_without_exposing_raw_routing_metadata() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence = key.issue(_request(_metadata()), expected_turn=_expected())
    receipt = public_locomo_timestamp_transport_evidence(
        evidence,
        verifier=key,
        expected_run_id=_RUN_ID,
        expected_corpus_key="corpus-a",
    )
    assert receipt["trigger_case_id_sha256"] == hashlib.sha256(b"corpus-a:qa:1").hexdigest()
    assert "corpus-a:qa:1" not in repr(receipt)
