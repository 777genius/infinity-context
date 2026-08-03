from __future__ import annotations

import copy
import json
import pickle
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_server import (
    memory_comparison_full_canonical_evidence as _canonical,
)
from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as _trust,
)
from infinity_context_server.memory_comparison_full_canonical_evidence import (
    INFINITY_CANONICAL_BACKEND_ID,
    CanonicalEvidenceError,
    CanonicalEvidenceRequest,
    CanonicalEvidenceSession,
    CanonicalLifecycleReceipt,
    CanonicalReadbackReceipt,
    VerifiedCanonicalEvidence,
    consume_canonical_evidence,
    issue_canonical_evidence_session,
)
from infinity_context_server.memory_comparison_full_canonical_evidence import (
    public_canonical_evidence_report as _public_component,
)
from infinity_context_server.memory_comparison_full_canonical_evidence import (
    seal_canonical_evidence as _seal_component,
)

_RUN = "run-17"
_PROFILE = "profile-3"
_SCOPE = "scope-a"
_CASE = "case-9"
_SOURCE = "source://conversation/9"
_RECORD = "record-22"


def _identity() -> dict[str, object]:
    return {
        "run_id": _RUN,
        "profile_id": _PROFILE,
        "backend_id": INFINITY_CANONICAL_BACKEND_ID,
        "scope_id": _SCOPE,
        "case_id": _CASE,
        "source_ref": _SOURCE,
    }


class _CanonicalSandbox:
    def __init__(
        self,
        *,
        lifecycle_changes: dict[str, object] | None = None,
        readback_changes: dict[str, object] | None = None,
        mutate_request: tuple[str, object] | None = None,
    ) -> None:
        self.lifecycle_changes = lifecycle_changes or {}
        self.readback_changes = readback_changes or {}
        self.mutate_request = mutate_request
        self.lifecycle_calls = 0
        self.readback_calls = 0
        self.seen_record_id: str | None = None

    def observe_lifecycle(
        self,
        request: CanonicalEvidenceRequest,
    ) -> CanonicalLifecycleReceipt:
        self.lifecycle_calls += 1
        values = {
            **_identity(),
            "canonical_record_id": _RECORD,
            "status": "active",
            "generation": 7,
            "watermark": 41,
            "derived_only": False,
            **self.lifecycle_changes,
        }
        receipt = CanonicalLifecycleReceipt(**values)  # type: ignore[arg-type]
        if self.mutate_request is not None:
            object.__setattr__(request, *self.mutate_request)
        return receipt

    def read_canonical(
        self,
        request: CanonicalEvidenceRequest,
        *,
        canonical_record_id: str,
    ) -> CanonicalReadbackReceipt:
        del request
        self.readback_calls += 1
        self.seen_record_id = canonical_record_id
        values = {
            **_identity(),
            "canonical_record_id": _RECORD,
            "status": "active",
            "generation": 7,
            "watermark": 41,
            "found": True,
            "derived_only": False,
            **self.readback_changes,
        }
        return CanonicalReadbackReceipt(**values)  # type: ignore[arg-type]


_SESSION_POLICIES: dict[CanonicalEvidenceSession, _trust.CanonicalSourceEvidenceTrustPolicy] = {}
_PROOF_POLICIES: dict[VerifiedCanonicalEvidence, _trust.CanonicalSourceEvidenceTrustPolicy] = {}


def _policy(port: _CanonicalSandbox) -> _trust.CanonicalSourceEvidenceTrustPolicy:
    return _trust._composition_issue_canonical_source_evidence_trust_policy(
        policy_id="policy-canonical",
        canonical_backend_id=INFINITY_CANONICAL_BACKEND_ID,
        infinity_source_backend_id="infinity-context",
        mem0_source_backend_id="mem0",
        canonical_adapter_id="sandbox-canonical-adapter",
        infinity_source_adapter_id="sandbox-source-adapter",
        mem0_source_adapter_id="sandbox-mem0-adapter",
        canonical_implementation_sha256="1" * 64,
        infinity_source_implementation_sha256="2" * 64,
        mem0_source_implementation_sha256="3" * 64,
        runtime_attestation_commitment="4" * 64,
        canonical_lifecycle_port=port,
        canonical_readback_port=port,
        infinity_retrieved_port=object(),
        infinity_ingested_port=object(),
        mem0_request_port=object(),
        mem0_readback_port=object(),
    )


def _session(
    sandbox: _CanonicalSandbox | None = None,
) -> tuple[CanonicalEvidenceSession, _CanonicalSandbox]:
    port = sandbox or _CanonicalSandbox()
    policy = _policy(port)
    session = issue_canonical_evidence_session(
        **_identity(),  # type: ignore[arg-type]
        minimum_generation=7,
        minimum_watermark=40,
        lifecycle_port=port,
        readback_port=port,
        trust_policy=policy,
    )
    _SESSION_POLICIES[session] = policy
    return session, port


def _seal(session: CanonicalEvidenceSession) -> VerifiedCanonicalEvidence:
    policy = _SESSION_POLICIES[session]
    proof = _seal_component(session, trust_policy=policy)
    _PROOF_POLICIES[proof] = policy
    return proof


def _public(proof: VerifiedCanonicalEvidence) -> dict[str, object]:
    policy = _PROOF_POLICIES.get(proof)
    if policy is None:
        policy = object.__new__(_trust.CanonicalSourceEvidenceTrustPolicy)
    return _public_component(proof, trust_policy=policy)


def _consume(proof: VerifiedCanonicalEvidence, **changes: object) -> dict[str, object]:
    values = _identity()
    values.update(changes)
    return consume_canonical_evidence(
        proof,
        trust_policy=_PROOF_POLICIES[proof],
        **values,  # type: ignore[arg-type]
    )


def test_canonical_lifecycle_and_readback_are_sealed_and_consumed_once() -> None:
    session, sandbox = _session()
    proof = _seal(session)

    report = _public(proof)
    assert report["backend_id"] == INFINITY_CANONICAL_BACKEND_ID
    assert report["source_ref"] == _SOURCE
    assert report["lifecycle"] == {
        "canonical_record_id": _RECORD,
        "generation": 7,
        "status": "active",
        "watermark": 41,
    }
    assert report["readback"] == {
        "canonical_record_id": _RECORD,
        "found": True,
        "generation": 7,
        "status": "active",
        "watermark": 41,
    }
    assert report["admission_from_public_json"] is False
    assert sandbox.lifecycle_calls == sandbox.readback_calls == 1
    assert sandbox.seen_record_id == _RECORD
    assert _consume(proof) == report

    with pytest.raises(CanonicalEvidenceError, match="already consumed"):
        _consume(proof)
    with pytest.raises(CanonicalEvidenceError, match="not live"):
        _seal(session)


def test_public_json_is_telemetry_and_mutation_cannot_admit() -> None:
    proof = _seal(_session()[0])
    report = _public(proof)
    report["run_id"] = "other"
    report["readback"] = {"found": False}

    with pytest.raises(CanonicalEvidenceError, match="type must be exact"):
        consume_canonical_evidence(  # type: ignore[arg-type]
            report,
            trust_policy=_PROOF_POLICIES[proof],
            **_identity(),  # type: ignore[arg-type]
        )
    assert _consume(proof)["run_id"] == _RUN
    json.dumps(report)


@pytest.mark.parametrize(
    ("lifecycle_changes", "readback_changes", "message"),
    (
        ({"status": "deleted"}, {}, "deleted"),
        ({"status": "superseded"}, {}, "superseded"),
        ({"derived_only": True}, {}, "derived-only"),
        ({"generation": 6}, {}, "generation is stale"),
        ({"watermark": 39}, {}, "watermark is stale"),
        ({"source_ref": "source://other"}, {}, "identity does not match"),
        ({}, {"found": False}, "did not find"),
        ({}, {"status": "deleted"}, "deleted"),
        ({}, {"status": "superseded"}, "superseded"),
        ({}, {"derived_only": True}, "derived-only"),
        ({}, {"canonical_record_id": "record-other"}, "does not match lifecycle"),
        ({}, {"generation": 6}, "generation is stale"),
        ({}, {"watermark": 39}, "watermark is stale"),
    ),
)
def test_invalid_canonical_state_is_rejected(
    lifecycle_changes: dict[str, object],
    readback_changes: dict[str, object],
    message: str,
) -> None:
    sandbox = _CanonicalSandbox(
        lifecycle_changes=lifecycle_changes,
        readback_changes=readback_changes,
    )
    session, _ = _session(sandbox)

    with pytest.raises(CanonicalEvidenceError, match=message):
        _seal(session)
    with pytest.raises(CanonicalEvidenceError, match="not live"):
        _seal(session)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "other-run"),
        ("profile_id", "other-profile"),
        ("backend_id", "other-backend"),
        ("scope_id", "other-scope"),
        ("case_id", "other-case"),
        ("source_ref", "source://other"),
    ),
)
def test_consume_requires_every_exact_identity_field(field: str, value: str) -> None:
    proof = _seal(_session()[0])

    with pytest.raises(CanonicalEvidenceError, match="identity does not match"):
        _consume(proof, **{field: value})

    assert _consume(proof)["case_id"] == _CASE


class _HostileText(str):
    def __eq__(self, other: object) -> bool:
        del other
        return True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "changed"),
        ("minimum_generation", 999),
        ("source_ref", _HostileText(_SOURCE)),
    ),
)
def test_port_side_request_mutation_is_detected(field: str, value: object) -> None:
    sandbox = _CanonicalSandbox(mutate_request=(field, value))
    session, _ = _session(sandbox)

    with pytest.raises(CanonicalEvidenceError, match="integrity"):
        _seal(session)
    assert sandbox.readback_calls == 0


def test_only_one_concurrent_seal_can_observe_ports() -> None:
    session, sandbox = _session()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(
            pool.map(
                lambda _: _seal_outcome(session),
                range(16),
            )
        )

    assert outcomes.count("sealed") == 1
    assert outcomes.count("rejected") == 15
    assert sandbox.lifecycle_calls == sandbox.readback_calls == 1


def _seal_outcome(session: CanonicalEvidenceSession) -> str:
    try:
        _seal(session)
    except CanonicalEvidenceError:
        return "rejected"
    return "sealed"


def test_capabilities_are_final_nonserializable_and_unforgeable() -> None:
    with pytest.raises(CanonicalEvidenceError, match="must be issued"):
        CanonicalEvidenceRequest(  # type: ignore[call-arg]
            **_identity(),
            minimum_generation=1,
            minimum_watermark=1,
            _token=object(),
        )
    with pytest.raises(CanonicalEvidenceError, match="must be issued"):
        CanonicalEvidenceSession(_token=object())
    with pytest.raises(CanonicalEvidenceError, match="must be sealed"):
        VerifiedCanonicalEvidence(_token=object())
    with pytest.raises(TypeError):

        class _RequestChild(CanonicalEvidenceRequest):
            pass

    session, _ = _session()
    proof = _seal(session)
    for value in (session, proof):
        with pytest.raises(TypeError):
            pickle.dumps(value)
        with pytest.raises(TypeError):
            copy.copy(value)
        with pytest.raises(TypeError):
            copy.deepcopy(value)

    forged = object.__new__(VerifiedCanonicalEvidence)
    with pytest.raises(CanonicalEvidenceError, match="integrity"):
        _public(forged)


def test_wrong_policy_is_rejected_at_seal_report_and_consume() -> None:
    session, _ = _session()
    right_policy = _SESSION_POLICIES[session]
    wrong_policy = _policy(_CanonicalSandbox())

    with pytest.raises(CanonicalEvidenceError, match="policy"):
        _seal_component(session, trust_policy=wrong_policy)

    proof = _seal(session)
    with pytest.raises(CanonicalEvidenceError, match="integrity"):
        _public_component(proof, trust_policy=wrong_policy)
    with pytest.raises(CanonicalEvidenceError, match="integrity"):
        consume_canonical_evidence(
            proof,
            trust_policy=wrong_policy,
            **_identity(),  # type: ignore[arg-type]
        )

    report = _public_component(proof, trust_policy=right_policy)
    assert report["trust_policy"]["policy_bound"] is True  # type: ignore[index]
    assert report["component_only"] is True
    assert report["externally_authentic"] is False
    assert report["composite_policy_consume_required"] is True
    assert _consume(proof)["run_id"] == _RUN


def test_policy_lane_replay_and_wrong_bound_ports_are_rejected() -> None:
    session, port = _session()
    policy = _SESSION_POLICIES[session]

    with pytest.raises(CanonicalEvidenceError, match="trust policy"):
        issue_canonical_evidence_session(
            **_identity(),  # type: ignore[arg-type]
            minimum_generation=7,
            minimum_watermark=40,
            lifecycle_port=port,
            readback_port=port,
            trust_policy=policy,
        )

    other_port = _CanonicalSandbox()
    other_policy = _policy(port)
    with pytest.raises(CanonicalEvidenceError, match="trust policy"):
        issue_canonical_evidence_session(
            **_identity(),  # type: ignore[arg-type]
            minimum_generation=7,
            minimum_watermark=40,
            lifecycle_port=other_port,
            readback_port=other_port,
            trust_policy=other_policy,
        )
    assert port.lifecycle_calls == other_port.lifecycle_calls == 0


def test_nested_policy_projection_mutation_cannot_poison_sealed_state() -> None:
    proof = _seal(_session()[0])
    first = _public(proof)
    policy = first["trust_policy"]
    for section in ("backend_ids", "adapter_ids", "implementation_sha256"):
        policy[section]["canonical"] = "poisoned"  # type: ignore[index]

    second = _public(proof)
    sealed_policy = second["trust_policy"]
    assert sealed_policy["backend_ids"]["canonical"] == INFINITY_CANONICAL_BACKEND_ID  # type: ignore[index]
    assert sealed_policy["adapter_ids"]["canonical"] == "sandbox-canonical-adapter"  # type: ignore[index]
    assert sealed_policy["implementation_sha256"]["canonical"] == "1" * 64  # type: ignore[index]
    assert _consume(proof)["trust_policy"] == sealed_policy


class _HostileList(list[object]):
    pass


class _HostileDict(dict[str, object]):
    pass


def test_recursive_freeze_and_thaw_copy_lists_and_tuples() -> None:
    frozen = _canonical._deep_freeze_report(
        {
            "nested": {
                "list": [{"value": "safe"}],
                "tuple": ("safe", {"value": "safe"}),
            }
        }
    )
    first = _canonical._thaw(frozen)
    first["nested"]["list"][0]["value"] = "poisoned"  # type: ignore[index]
    first["nested"]["tuple"][1]["value"] = "poisoned"  # type: ignore[index]

    second = _canonical._thaw(frozen)
    assert second == {
        "nested": {
            "list": [{"value": "safe"}],
            "tuple": ["safe", {"value": "safe"}],
        }
    }


@pytest.mark.parametrize(
    "payload",
    (
        {"value": _HostileText("safe")},
        {"value": _HostileList(["safe"])},
        _HostileDict({"value": "safe"}),
        {"value": object()},
    ),
)
def test_recursive_freeze_rejects_hostile_or_non_json_exact_types(
    payload: object,
) -> None:
    with pytest.raises(CanonicalEvidenceError, match="exact type"):
        _canonical._deep_freeze_report(payload)
