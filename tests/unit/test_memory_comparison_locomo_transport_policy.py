from __future__ import annotations

import hashlib
import json

import pytest
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_user_id,
)
from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION,
    LocomoOfficialTurnsTransportRequest,
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
    locomo_timestamp_evidence_payload_is_exact,
    locomo_timestamp_transport_contract,
    public_locomo_timestamp_transport_evidence,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

_RUN_ID = "run-transport-1"


def _messages() -> list[dict[str, object]]:
    return [{"role": "user", "content": "official LoCoMo turn D1:1"}]


def _metadata(corpus_key: str = "corpus-a") -> dict[str, object]:
    source_id = f"locomo:{corpus_key}:session_1:D1:1:turn"
    return {
        "benchmark": "locomo",
        "case_id": f"{corpus_key}:qa:1",
        "corpus_key": corpus_key,
        "source_external_id": source_id,
        "source_id": source_id,
        "session_key": "session_1",
        "session_date": "1:56 pm on 8 May, 2023",
        "dia_id": "D1:1",
        "role": "user",
        "speaker": "Caroline",
        "locomo_evidence_ref": "D1:1",
    }


def _source_id(corpus_key: str = "corpus-a") -> str:
    return str(_metadata(corpus_key)["source_id"])


def _request(
    *,
    run_id: str = _RUN_ID,
    corpus_key: str = "corpus-a",
    timestamp: int = 1_683_554_160,
) -> LocomoOfficialTurnsTransportRequest:
    metadata = _metadata(corpus_key)
    return LocomoOfficialTurnsTransportRequest.create(
        messages=_messages(),
        user_id=mem0_benchmark_user_id(run_id),
        run_id=run_id,
        metadata=metadata,
        timestamp=timestamp,
        idempotency_key=str(metadata["source_id"]),
    )


def _expected(
    *,
    run_id: str = _RUN_ID,
    corpus_key: str = "corpus-a",
    timestamp: int = 1_683_554_160,
    metadata: dict[str, object] | None = None,
    messages: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
) -> ExpectedOfficialLocomoTurn:
    metadata = _metadata(corpus_key) if metadata is None else metadata
    messages = _messages() if messages is None else messages
    message = messages[0]
    return ExpectedOfficialLocomoTurn.create(
        run_id=run_id,
        corpus_key=str(metadata["corpus_key"]),
        source_external_id=str(metadata["source_external_id"]),
        source_id=str(metadata["source_id"]),
        session_key=str(metadata["session_key"]),
        speaker=str(metadata["speaker"]),
        session_date=str(metadata["session_date"]),
        trigger_case_id=str(metadata["case_id"]),
        dia_id=str(metadata["dia_id"]),
        role=str(message["role"]),
        content=str(message["content"]),
        timestamp=timestamp,
    )


def _evaluation(corpus_key: str = "corpus-a") -> dict[str, object]:
    return {
        "benchmark": "locomo",
        "backend": "mem0",
        "ingestion": {
            "metadata": {
                "corpus_key": corpus_key,
                # Deliberately forged self-report: the contract must ignore it.
                "timestamps_sent": False,
                "ingestion_payload_count": 999,
                "timestamp_payload_count": 0,
            }
        },
    }


def _evidence(
    key: RunScopedLocomoTransportEvidenceKey,
    corpus_key: str = "corpus-a",
    *,
    timestamp: int = 1_683_554_160,
) -> LocomoTimestampTransportEvidence:
    return key.issue(
        _request(
            corpus_key=corpus_key,
            timestamp=timestamp,
        ),
        expected_turn=_expected(corpus_key=corpus_key, timestamp=timestamp),
    )


def test_exact_sealed_transport_evidence_authorizes_locomo_timestamp_contract() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence_a = _evidence(key)
    evidence_b = _evidence(
        key,
        "corpus-b",
        timestamp=1_683_554_160,
    )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(), _evaluation(), _evaluation("corpus-b")),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(evidence_a, evidence_b),
    )
    assert contract["matches"] is True
    assert contract["issues"] == []
    assert contract["observed_evaluation_count"] == 3
    assert contract["observed_corpus_count"] == 2
    assert contract["evidence_count"] == 2
    assert contract["ingestion_payload_count"] == 2
    assert contract["timestamp_payload_count"] == 2
    assert contract["timestamp_attested_evaluation_count"] == 3
    assert all(locomo_timestamp_evidence_payload_is_exact(item) for item in contract["evidence"])
    assert "timestamps_sent" not in repr(contract)


def test_public_evidence_is_exact_safe_serializable_projection() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence = _evidence(key)
    payload = public_locomo_timestamp_transport_evidence(
        evidence,
        verifier=key,
        expected_run_id=_RUN_ID,
        expected_corpus_key="corpus-a",
    )
    assert set(payload) == {
        "schema_version",
        "run_id_sha256",
        "corpus_key_sha256",
        "source_id_sha256",
        "turn_identity_sha256",
        "expected_turn_digest_sha256",
        "trigger_case_id_sha256",
        "ingest_mode",
        "ingestion_payload_count",
        "timestamp_payload_count",
        "request_projection_schema_version",
        "request_digest_sha256",
        "commitment_sha256",
    }
    assert locomo_timestamp_evidence_payload_is_exact(payload) is True
    payload["extra"] = "forged"
    assert locomo_timestamp_evidence_payload_is_exact(payload) is False


def test_managed_public_trigger_binds_opaque_alias_after_raw_turn_validation() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    opaque_alias = "locomo-case-" + "a" * 64
    evidence = key.issue(
        _request(),
        expected_turn=_expected(),
        public_trigger_case_id=opaque_alias,
    )
    payload = public_locomo_timestamp_transport_evidence(
        evidence,
        verifier=key,
        expected_run_id=_RUN_ID,
        expected_corpus_key="corpus-a",
    )

    assert payload["trigger_case_id_sha256"] == hashlib.sha256(opaque_alias.encode()).hexdigest()
    assert payload["trigger_case_id_sha256"] != hashlib.sha256(b"corpus-a:qa:1").hexdigest()
    with pytest.raises(ValueError, match="public trigger case_id"):
        key.issue(
            _request(),
            expected_turn=_expected(),
            public_trigger_case_id=" bad ",
        )

    class MappingSubclass(dict):
        pass

    assert locomo_timestamp_evidence_payload_is_exact(MappingSubclass(payload)) is False


@pytest.mark.parametrize("declared", (None, False, 1, "true"))
def test_locomo_requires_declared_sent_exact_true(declared: object) -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    kwargs = {
        "benchmark": "locomo",
        "evaluations": (_evaluation(),),
        "declared_sent": declared,
        "run_id": _RUN_ID,
        "verifier": key,
        "timestamp_evidence": (_evidence(key),),
    }
    if declared in (1, "true"):
        with pytest.raises(BenchmarkValidationError):
            locomo_timestamp_transport_contract(**kwargs)  # type: ignore[arg-type]
    else:
        contract = locomo_timestamp_transport_contract(**kwargs)  # type: ignore[arg-type]
        assert contract["matches"] is False
        assert contract["issues"] == [{"code": "declared_sent_not_exact_true", "count": 1}]


@pytest.mark.parametrize(
    "evidence_factory",
    (
        lambda key: (),
        lambda key: (_evidence(key), _evidence(key)),
        lambda key: (_evidence(key, "unexpected"),),
    ),
)
def test_missing_duplicate_and_unexpected_corpus_evidence_fail_closed(
    evidence_factory,
) -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(),),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=evidence_factory(key),
    )
    assert contract["matches"] is False
    assert contract["issues"]


def test_request_digest_counts_run_and_corpus_are_hmac_bound() -> None:
    mutations = (
        ("_run_id", "other-run"),
        ("_corpus_key", "other-corpus"),
        ("_source_id", "other-source"),
        ("_turn_identity_sha256", "0" * 64),
        ("_expected_turn_digest_sha256", "0" * 64),
        ("_trigger_case_id_sha256", "0" * 64),
        ("_ingest_mode", "rich-documents"),
        ("_ingestion_payload_count", 4),
        ("_timestamp_payload_count", 2),
        ("_request_digest_sha256", "0" * 64),
        ("_commitment_sha256", "0" * 64),
        ("_proof", b"0" * 32),
    )
    for name, value in mutations:
        key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
        evidence = _evidence(key)
        object.__setattr__(evidence, name, value)
        contract = locomo_timestamp_transport_contract(
            benchmark="locomo",
            evaluations=(_evaluation(),),
            declared_sent=True,
            run_id=_RUN_ID,
            verifier=key,
            timestamp_evidence=(evidence,),
        )
        assert contract["matches"] is False, name


def test_wrong_run_key_and_timestamp_count_mismatch_fail_closed() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    wrong_key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence = _evidence(key)
    object.__setattr__(evidence, "_timestamp_payload_count", 0)
    for verifier in (key, wrong_key):
        contract = locomo_timestamp_transport_contract(
            benchmark="locomo",
            evaluations=(_evaluation(),),
            declared_sent=True,
            run_id=_RUN_ID,
            verifier=verifier,
            timestamp_evidence=(evidence,),
        )
        assert contract["matches"] is False


def test_missing_corpus_key_mapping_subclasses_and_forged_get_fail() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    missing = _evaluation()
    del missing["ingestion"]["metadata"]["corpus_key"]
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(missing,),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(_evidence(key),),
    )
    assert contract["matches"] is False

    class Forged(dict):
        def get(self, key, default=None):
            raise AssertionError("forged get must not be called")

    with pytest.raises(BenchmarkValidationError, match="exact dict"):
        locomo_timestamp_transport_contract(
            benchmark="locomo",
            evaluations=(Forged(_evaluation()),),
            declared_sent=True,
            run_id=_RUN_ID,
            verifier=key,
            timestamp_evidence=(_evidence(key),),
        )
    nested = _evaluation()
    nested["ingestion"] = Forged(nested["ingestion"])
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(nested,),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(_evidence(key),),
    )
    assert contract["matches"] is False


def test_sealed_classes_reject_direct_construction_and_subclasses() -> None:
    with pytest.raises(TypeError, match="generate"):
        RunScopedLocomoTransportEvidenceKey(
            run_id=_RUN_ID,
            secret=b"x" * 32,
            _construction_seal=object(),
        )
    with pytest.raises(TypeError, match="issue"):
        LocomoTimestampTransportEvidence(
            run_id=_RUN_ID,
            corpus_key="corpus-a",
            source_id=_source_id(),
            turn_identity_sha256="0" * 64,
            expected_turn_digest_sha256="0" * 64,
            trigger_case_id_sha256="0" * 64,
            ingest_mode="official-turns",
            ingestion_payload_count=1,
            timestamp_payload_count=1,
            request_digest_sha256="0" * 64,
            commitment_sha256="0" * 64,
            proof=b"0" * 32,
            _construction_seal=object(),
        )
    with pytest.raises(TypeError, match="create"):
        LocomoOfficialTurnsTransportRequest(
            canonical_bytes=b"{}",
            _construction_seal=object(),
        )
    with pytest.raises(TypeError, match="sealed"):

        class ForgedEvidence(LocomoTimestampTransportEvidence):
            pass


def test_key_integrity_snapshot_rejects_run_rescope_before_issue_and_verify() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence = _evidence(key)
    object.__setattr__(key, "_run_id", "silently-rescoped-run")
    with pytest.raises(ValueError, match="key is invalid"):
        key.issue(
            _request(run_id="silently-rescoped-run"),
            expected_turn=_expected(run_id="silently-rescoped-run"),
        )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(),),
        declared_sent=True,
        run_id="silently-rescoped-run",
        verifier=key,
        timestamp_evidence=(evidence,),
    )
    assert contract["matches"] is False
    assert {item["code"] for item in contract["issues"]} >= {
        "live_verifier_invalid",
        "invalid_corpus_evidence",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (("_secret", b"x" * 32), ("_seal", object())),
)
def test_key_integrity_snapshot_rejects_all_other_key_state_mutations(
    field: str,
    value: object,
) -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    request = _request()
    object.__setattr__(key, field, value)
    with pytest.raises(ValueError, match="key is invalid"):
        key.issue(request, expected_turn=_expected())


def test_issuer_accepts_only_exact_producer_observed_add_request_projection() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    request = _request()
    evidence = key.issue(request, expected_turn=_expected())
    projection = public_locomo_timestamp_transport_evidence(
        evidence,
        verifier=key,
        expected_run_id=_RUN_ID,
        expected_corpus_key="corpus-a",
    )
    canonical_projection = json.dumps(
        {
            "messages": _messages(),
            "user_id": mem0_benchmark_user_id(_RUN_ID),
            "run_id": _RUN_ID,
            "metadata": _metadata(),
            "idempotency_key": _source_id(),
            "timestamp": 1_683_554_160,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION.endswith(".v1")
    assert projection["request_digest_sha256"] == hashlib.sha256(canonical_projection).hexdigest()
    assert projection["ingestion_payload_count"] == 1
    assert projection["timestamp_payload_count"] == 1


def test_arbitrary_payload_and_caller_claimed_counts_are_not_an_issuer_api() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    with pytest.raises(TypeError):
        key.issue(  # type: ignore[call-arg]
            corpus_key="corpus-a",
            ingestion_payload_count=1,
            timestamp_payload_count=1,
            request_payload=b'{"messages":[]}',
        )
    with pytest.raises(ValueError, match="invalid or mutated"):
        key.issue(  # type: ignore[arg-type]
            b'{"messages":[],"timestamp":1}', expected_turn=_expected()
        )


@pytest.mark.parametrize("invalid_timestamp", (None, True, 1.0, "1", -1))
def test_add_request_rejects_missing_or_non_exact_timestamp(
    invalid_timestamp: object,
) -> None:
    kwargs = {
        "messages": _messages(),
        "user_id": mem0_benchmark_user_id(_RUN_ID),
        "idempotency_key": _source_id(),
        "run_id": _RUN_ID,
        "metadata": _metadata(),
    }
    if invalid_timestamp is None:
        with pytest.raises(TypeError):
            LocomoOfficialTurnsTransportRequest.create(**kwargs)  # type: ignore[call-arg]
    else:
        with pytest.raises(ValueError, match="timestamp"):
            LocomoOfficialTurnsTransportRequest.create(
                **kwargs,
                timestamp=invalid_timestamp,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize(
    "messages",
    (
        (),
        ({"role": "user"},),
        ({"role": "user", "content": "turn", "extra": True},),
        ({"role": "tool", "content": "turn"},),
        ({"role": "user", "content": ""},),
        (
            {"role": "user", "content": "turn one"},
            {"role": "assistant", "content": "turn two"},
        ),
    ),
)
def test_add_request_rejects_missing_extra_and_malformed_message_fields(messages) -> None:
    with pytest.raises(ValueError):
        LocomoOfficialTurnsTransportRequest.create(
            messages=messages,
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=_metadata(),
            timestamp=1_683_554_160,
            idempotency_key=_source_id(),
        )


def test_mutated_or_duplicate_field_request_bytes_cannot_be_signed() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    request = _request()
    object.__setattr__(
        request,
        "_canonical_bytes",
        b'{"messages":[],"timestamp":1,"timestamp":2}',
    )
    with pytest.raises(ValueError, match="invalid or mutated"):
        key.issue(request, expected_turn=_expected())


@pytest.mark.parametrize(
    "mutation",
    (
        lambda metadata: metadata.pop("corpus_key"),
        lambda metadata: metadata.__setitem__("extra", True),
        lambda metadata: metadata.__setitem__("benchmark", "longmemeval"),
        lambda metadata: metadata.__setitem__("role", "assistant"),
        lambda metadata: metadata.__setitem__("locomo_evidence_ref", "D9:9"),
    ),
)
def test_add_request_rejects_inexact_locomo_turn_metadata(mutation) -> None:
    metadata = _metadata()
    mutation(metadata)
    with pytest.raises(ValueError):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_554_160,
            idempotency_key=str(metadata.get("source_id", _source_id())),
        )


def test_add_request_rejects_mapping_subclasses_and_unknown_top_level_fields() -> None:
    class MappingSubclass(dict):
        pass

    with pytest.raises(ValueError, match="exact dict records"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=(MappingSubclass(_messages()[0]),),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=_metadata(),
            timestamp=1_683_554_160,
            idempotency_key=_source_id(),
        )
    with pytest.raises(ValueError, match="metadata must be an exact dict"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=MappingSubclass(_metadata()),
            timestamp=1_683_554_160,
            idempotency_key=_source_id(),
        )
    with pytest.raises(TypeError):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=_metadata(),
            timestamp=1_683_554_160,
            idempotency_key=_source_id(),
            extra=True,  # type: ignore[call-arg]
        )


def test_distinct_official_turn_requests_for_one_corpus_are_not_duplicates() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    first = key.issue(_request(), expected_turn=_expected())
    second_metadata = _metadata()
    second_metadata.update(
        {
            "source_external_id": "locomo:corpus-a:session_1:D1:2:turn",
            "source_id": "locomo:corpus-a:session_1:D1:2:turn",
            "dia_id": "D1:2",
            "role": "assistant",
            "speaker": "Melanie",
            "locomo_evidence_ref": "D1:2",
        }
    )
    second_messages = ({"role": "assistant", "content": "official LoCoMo turn D1:2"},)
    second = key.issue(
        LocomoOfficialTurnsTransportRequest.create(
            messages=second_messages,
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=second_metadata,
            timestamp=1_683_554_160,
            idempotency_key=str(second_metadata["source_id"]),
        ),
        expected_turn=_expected(
            metadata=second_metadata,
            messages=second_messages,
            timestamp=1_683_554_160,
        ),
    )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(),),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(first, second),
    )
    assert contract["matches"] is True
    assert contract["evidence_count"] == 2
    assert contract["ingestion_payload_count"] == 2
    assert contract["timestamp_payload_count"] == 2


def test_same_logical_turn_with_changed_body_and_time_is_rejected_as_rewrite() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    first = key.issue(_request(), expected_turn=_expected())
    metadata = _metadata()
    metadata.update({"case_id": "corpus-a:qa:2", "session_date": "1:56 pm on 9 May, 2023"})
    rewritten_messages = ({"role": "user", "content": "rewritten official turn"},)
    rewritten = key.issue(
        LocomoOfficialTurnsTransportRequest.create(
            messages=rewritten_messages,
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_640_560,
            idempotency_key=str(metadata["source_id"]),
        ),
        expected_turn=_expected(
            metadata=metadata,
            messages=rewritten_messages,
            timestamp=1_683_640_560,
        ),
    )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(),),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(first, rewritten),
    )
    assert contract["matches"] is False
    assert contract["evidence_count"] == 1
    assert contract["issues"] == [{"code": "duplicate_logical_turn_evidence", "count": 1}]


def test_same_session_and_dia_alias_with_new_source_id_is_still_duplicate() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    first = key.issue(_request(), expected_turn=_expected())
    alias_metadata = _metadata()
    alias_source = "locomo:other-sample:session_1:D1:1:turn"
    alias_metadata.update(
        {
            "source_external_id": alias_source,
            "source_id": alias_source,
            "case_id": "other-sample:qa:1",
        }
    )
    alias = key.issue(
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=alias_metadata,
            timestamp=1_683_554_160,
            idempotency_key=alias_source,
        ),
        expected_turn=_expected(
            metadata=alias_metadata,
            timestamp=1_683_554_160,
        ),
    )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=(_evaluation(),),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(first, alias),
    )
    assert contract["matches"] is False
    assert contract["issues"] == [{"code": "duplicate_logical_turn_evidence", "count": 1}]


@pytest.mark.parametrize(
    ("mutation", "messages"),
    (
        (
            lambda metadata: metadata.__setitem__("source_id", "unrelated-source"),
            _messages(),
        ),
        (
            lambda metadata: metadata.__setitem__("session_key", "session_9"),
            _messages(),
        ),
        (
            lambda metadata: metadata.__setitem__("role", "system"),
            ({"role": "system", "content": "system turn"},),
        ),
    ),
)
def test_add_request_rejects_source_alias_and_official_role_conflicts(
    mutation,
    messages,
) -> None:
    metadata = _metadata()
    mutation(metadata)
    with pytest.raises(ValueError):
        LocomoOfficialTurnsTransportRequest.create(
            messages=messages,
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_554_160,
            idempotency_key=str(metadata["source_id"]),
        )


def test_add_request_rejects_unrelated_user_whitespace_content_and_epoch_zero() -> None:
    metadata = _metadata()
    common = {
        "run_id": _RUN_ID,
        "metadata": metadata,
        "idempotency_key": str(metadata["source_id"]),
    }
    with pytest.raises(ValueError, match="canonical benchmark run user"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id="unrelated-user",
            timestamp=1_683_554_160,
            **common,
        )
    with pytest.raises(ValueError, match="nonblank"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=({"role": "user", "content": "   \n\t"},),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            timestamp=1_683_554_160,
            **common,
        )
    with pytest.raises(ValueError, match="session_date"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            timestamp=0,
            **common,
        )


def test_add_request_requires_exact_idempotency_and_matching_source_timestamp() -> None:
    metadata = _metadata()
    with pytest.raises(ValueError, match="Idempotency-Key"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_554_160,
            idempotency_key="wrong-idempotency-key",
        )
    with pytest.raises(TypeError):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_554_160,
        )
    metadata_with_timestamp = {**metadata, "source_timestamp": 1_683_554_161}
    with pytest.raises(ValueError, match="source_timestamp"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata_with_timestamp,
            timestamp=1_683_554_160,
            idempotency_key=str(metadata["source_id"]),
        )


def test_add_request_accepts_and_binds_canonical_source_sha256() -> None:
    metadata = {**_metadata(), "source_sha256": "a" * 64}
    request = LocomoOfficialTurnsTransportRequest.create(
        messages=_messages(),
        user_id=mem0_benchmark_user_id(_RUN_ID),
        run_id=_RUN_ID,
        metadata=metadata,
        timestamp=1_683_554_160,
        idempotency_key=str(metadata["source_id"]),
    )
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    evidence = key.issue(request, expected_turn=_expected(metadata=metadata))
    assert type(evidence) is LocomoTimestampTransportEvidence


@pytest.mark.parametrize("invalid", ("A" * 64, "a" * 63, 1, None))
def test_add_request_rejects_invalid_canonical_source_sha256(invalid: object) -> None:
    metadata = {**_metadata(), "source_sha256": invalid}
    with pytest.raises(ValueError, match="source_sha256"):
        LocomoOfficialTurnsTransportRequest.create(
            messages=_messages(),
            user_id=mem0_benchmark_user_id(_RUN_ID),
            run_id=_RUN_ID,
            metadata=metadata,
            timestamp=1_683_554_160,
            idempotency_key=str(metadata["source_id"]),
        )


def test_hashed_benchmark_user_id_is_accepted_by_transport() -> None:
    run_id = "Run X/Y"
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=run_id)
    evidence = key.issue(_request(run_id=run_id), expected_turn=_expected(run_id=run_id))
    assert key.verify(
        evidence,
        expected_run_id=run_id,
        expected_corpus_key="corpus-a",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("session_key", "Session_1"),
        ("session_key", "session_01"),
        ("session_key", "session_1\u200b"),
        ("dia_id", "d1:1"),
        ("dia_id", "D01:1"),
        ("dia_id", "D1:01"),
        ("source_external_id", "Locomo:corpus-a:session_1:D1:1:turn"),
        ("source_external_id", "locomo:caf\u00e9:session_1:D1:1:turn"),
        ("source_external_id", "locomo:cafe\u0301:session_1:D1:1:turn"),
        ("source_external_id", "locomo:corpus a:session_1:D1:1:turn"),
        ("source_external_id", "locomo:corpus\u200b:session_1:D1:1:turn"),
        ("source_external_id", "locomo:corpus\n:session_1:D1:1:turn"),
        ("source_id", "locomo:corpus a:session_1:D1:1:turn"),
    ),
)
def test_expected_turn_rejects_case_unicode_whitespace_and_control_aliases(
    field: str,
    value: str,
) -> None:
    metadata = _metadata()
    metadata[field] = value
    if field == "source_external_id":
        metadata["source_id"] = value
    with pytest.raises(ValueError, match=field):
        _expected(metadata=metadata)


def test_run_and_source_identifier_boundaries_match_adapter_contracts() -> None:
    run_id = "r" * 160
    assert len(mem0_benchmark_user_id(run_id)) <= 160
    RunScopedLocomoTransportEvidenceKey.generate(run_id=run_id)
    with pytest.raises(ValueError, match="SafeIdentifier"):
        mem0_benchmark_user_id("r" * 161)
    with pytest.raises(ValueError, match="run_id"):
        RunScopedLocomoTransportEvidenceKey.generate(run_id="r" * 161)

    suffix = ":session_1:D1:1:turn"
    source_external_id = "locomo:" + "a" * (160 - len("locomo:") - len(suffix)) + suffix
    metadata = _metadata()
    metadata.update({"source_external_id": source_external_id, "source_id": source_external_id})
    metadata["case_id"] = source_external_id.split(":", 2)[1] + ":qa:1"
    _expected(metadata=metadata)
    metadata["source_external_id"] = "locomo:" + "a" * (161 - len("locomo:") - len(suffix)) + suffix
    metadata["source_id"] = metadata["source_external_id"]
    with pytest.raises(ValueError, match="source_id"):
        _expected(metadata=metadata)


@pytest.mark.parametrize(
    "field",
    (
        "run_id",
        "corpus_key",
        "source_external_id",
        "source_id",
        "session_key",
        "dia_id",
        "role",
        "content",
        "timestamp",
    ),
)
def test_issuer_rejects_every_expected_loader_projection_mismatch(field: str) -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    metadata = _metadata()
    messages = _messages()
    run_id = _RUN_ID
    timestamp = 1_683_554_160
    if field == "run_id":
        run_id = "other-run"
    elif field == "corpus_key":
        metadata["corpus_key"] = "other-corpus"
    elif field in {"source_external_id", "source_id"}:
        alias = "locomo:other-sample:session_1:D1:1:turn"
        metadata.update(
            {"source_external_id": alias, "source_id": alias, "case_id": "other-sample:qa:1"}
        )
    elif field == "session_key":
        metadata.update(
            {
                "session_key": "session_2",
                "source_external_id": "locomo:corpus-a:session_2:D1:1:turn",
                "source_id": "locomo:corpus-a:session_2:D1:1:turn",
            }
        )
    elif field == "dia_id":
        metadata.update(
            {
                "dia_id": "D1:2",
                "source_external_id": "locomo:corpus-a:session_1:D1:2:turn",
                "source_id": "locomo:corpus-a:session_1:D1:2:turn",
            }
        )
    elif field == "role":
        messages = [{"role": "assistant", "content": messages[0]["content"]}]
    elif field == "content":
        messages = [{"role": "user", "content": "different content"}]
    else:
        metadata["session_date"] = "1:56 pm on 9 May, 2023"
        timestamp = 1_683_640_560
    expected = _expected(
        run_id=run_id,
        metadata=metadata,
        messages=messages,
        timestamp=timestamp,
    )
    with pytest.raises(ValueError, match="differs from expected"):
        key.issue(_request(), expected_turn=expected)


def test_actual_loader_shape_without_source_timestamp_is_accepted() -> None:
    metadata = _metadata()
    assert "source_timestamp" not in metadata
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    request = LocomoOfficialTurnsTransportRequest.create(
        messages=_messages(),
        user_id=mem0_benchmark_user_id(_RUN_ID),
        run_id=_RUN_ID,
        metadata=metadata,
        timestamp=1_683_554_160,
        idempotency_key=str(metadata["source_id"]),
    )
    evidence = key.issue(request, expected_turn=_expected(metadata=metadata))
    assert key.verify(
        evidence,
        expected_run_id=_RUN_ID,
        expected_corpus_key="corpus-a",
    )


def test_expected_turn_is_sealed_and_serialized_mapping_is_not_admission() -> None:
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    expected = _expected()
    with pytest.raises(ValueError, match="expected official"):
        key.issue(_request(), expected_turn={})  # type: ignore[arg-type]
    object.__setattr__(expected, "_canonical_bytes", b"{}")
    with pytest.raises(ValueError, match="invalid or mutated"):
        key.issue(_request(), expected_turn=expected)
    with pytest.raises(TypeError, match="ExpectedOfficialLocomoTurn.create"):
        ExpectedOfficialLocomoTurn(canonical_bytes=b"{}", _construction_seal=object())
    with pytest.raises(TypeError, match="sealed"):

        class ForgedExpected(ExpectedOfficialLocomoTurn):
            pass


def test_longmemeval_is_not_required_only_for_exact_empty_transport_state() -> None:
    exact = locomo_timestamp_transport_contract(
        benchmark="longmemeval",
        evaluations=({"benchmark": "longmemeval", "backend": "mem0"},),
        declared_sent=None,
    )
    assert exact["required"] is False
    assert exact["matches"] is True
    key = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)
    inexact = locomo_timestamp_transport_contract(
        benchmark="longmemeval",
        evaluations=({"benchmark": "longmemeval", "backend": "mem0"},),
        declared_sent=True,
        run_id=_RUN_ID,
        verifier=key,
        timestamp_evidence=(_evidence(key),),
    )
    assert inexact["matches"] is False
    assert inexact["issues"] == ["longmemeval_transport_state_not_exact"]
