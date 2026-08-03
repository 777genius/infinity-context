from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as _trust,
)
from infinity_context_server.memory_comparison_full_source_evidence import (
    INFINITY_SOURCE_BACKEND_ID,
    MEM0_SOURCE_BACKEND_ID,
    InfinityIngestedSourceReceipt,
    InfinityRetrievedSourceReceipt,
    Mem0SourceReadbackReceipt,
    Mem0SourceRequestReceipt,
    SourceEvidenceError,
    SourceEvidenceRequest,
    VerifiedSourceEvidence,
    consume_source_evidence,
    issue_source_evidence_session,
)
from infinity_context_server.memory_comparison_full_source_evidence import (
    public_source_evidence_report as _public_component,
)
from infinity_context_server.memory_comparison_full_source_evidence import (
    seal_source_evidence as _seal_component,
)

RUN, PROFILE, SCOPE, CASE = "run-21", "profile-8", "scope-b", "case-4"
SOURCE, REVISION, DIGEST = "source://conversation/4", 12, "a" * 64
INGESTION, REQUEST = "ingestion-19", "request-55"


def binding() -> dict[str, object]:
    return {
        "run_id": RUN,
        "profile_id": PROFILE,
        "scope_id": SCOPE,
        "case_id": CASE,
        "source_ref": SOURCE,
        "source_revision": REVISION,
        "source_sha256": DIGEST,
        "infinity_backend_id": INFINITY_SOURCE_BACKEND_ID,
        "mem0_backend_id": MEM0_SOURCE_BACKEND_ID,
    }


def identity(backend_id: str) -> dict[str, object]:
    values = binding()
    values.pop("infinity_backend_id")
    values.pop("mem0_backend_id")
    values["backend_id"] = backend_id
    return values


class Sandbox:
    def __init__(
        self,
        *,
        retrieved: dict[str, object] | None = None,
        ingested: dict[str, object] | None = None,
        request: dict[str, object] | None = None,
        readback: dict[str, object] | None = None,
        mutate: tuple[str, str, object] | None = None,
    ) -> None:
        self.changes = {
            "retrieved": retrieved or {},
            "ingested": ingested or {},
            "request": request or {},
            "readback": readback or {},
        }
        self.mutate = mutate
        self.calls = {name: 0 for name in self.changes}
        self.seen_ingestion: str | None = None
        self.seen_request: str | None = None

    def retrieve_source(
        self,
        request: SourceEvidenceRequest,
    ) -> InfinityRetrievedSourceReceipt:
        self.calls["retrieved"] += 1
        receipt = InfinityRetrievedSourceReceipt(
            **{
                **identity(INFINITY_SOURCE_BACKEND_ID),
                "retrieved_item_id": "retrieved-31",
                "ingestion_id": INGESTION,
                "derived_only": False,
                **self.changes["retrieved"],
            }
        )  # type: ignore[arg-type]
        self._mutate(request, "retrieved")
        return receipt

    def read_ingested_source(
        self,
        request: SourceEvidenceRequest,
        *,
        ingestion_id: str,
    ) -> InfinityIngestedSourceReceipt:
        self.calls["ingested"] += 1
        self.seen_ingestion = ingestion_id
        receipt = InfinityIngestedSourceReceipt(
            **{
                **identity(INFINITY_SOURCE_BACKEND_ID),
                "ingestion_id": INGESTION,
                "present": True,
                "deleted": False,
                **self.changes["ingested"],
            }
        )  # type: ignore[arg-type]
        self._mutate(request, "ingested")
        return receipt

    def observe_source_request(
        self,
        request: SourceEvidenceRequest,
    ) -> Mem0SourceRequestReceipt:
        self.calls["request"] += 1
        receipt = Mem0SourceRequestReceipt(
            **{
                **identity(MEM0_SOURCE_BACKEND_ID),
                "request_id": REQUEST,
                "accepted": True,
                **self.changes["request"],
            }
        )  # type: ignore[arg-type]
        self._mutate(request, "request")
        return receipt

    def read_source_result(
        self,
        request: SourceEvidenceRequest,
        *,
        request_id: str,
    ) -> Mem0SourceReadbackReceipt:
        self.calls["readback"] += 1
        self.seen_request = request_id
        receipt = Mem0SourceReadbackReceipt(
            **{
                **identity(MEM0_SOURCE_BACKEND_ID),
                "request_id": REQUEST,
                "memory_item_id": "memory-73",
                "found": True,
                **self.changes["readback"],
            }
        )  # type: ignore[arg-type]
        self._mutate(request, "readback")
        return receipt

    def _mutate(self, request: SourceEvidenceRequest, stage: str) -> None:
        if self.mutate is not None and self.mutate[0] == stage:
            object.__setattr__(request, self.mutate[1], self.mutate[2])


_SESSION_POLICIES: dict[object, _trust.CanonicalSourceEvidenceTrustPolicy] = {}
_PROOF_POLICIES: dict[VerifiedSourceEvidence, _trust.CanonicalSourceEvidenceTrustPolicy] = {}


def policy(port: Sandbox) -> _trust.CanonicalSourceEvidenceTrustPolicy:
    return _trust._composition_issue_canonical_source_evidence_trust_policy(
        policy_id="policy-source",
        canonical_backend_id="infinity-context",
        infinity_source_backend_id=INFINITY_SOURCE_BACKEND_ID,
        mem0_source_backend_id=MEM0_SOURCE_BACKEND_ID,
        canonical_adapter_id="sandbox-canonical-adapter",
        infinity_source_adapter_id="sandbox-source-adapter",
        mem0_source_adapter_id="sandbox-mem0-adapter",
        canonical_implementation_sha256="1" * 64,
        infinity_source_implementation_sha256="2" * 64,
        mem0_source_implementation_sha256="3" * 64,
        runtime_attestation_commitment="4" * 64,
        canonical_lifecycle_port=object(),
        canonical_readback_port=object(),
        infinity_retrieved_port=port,
        infinity_ingested_port=port,
        mem0_request_port=port,
        mem0_readback_port=port,
    )


def session(port: Sandbox | None = None) -> tuple[object, Sandbox]:
    sandbox = port or Sandbox()
    trust_policy = policy(sandbox)
    capability = issue_source_evidence_session(
        **binding(),
        retrieved_port=sandbox,
        ingested_port=sandbox,
        mem0_request_port=sandbox,
        mem0_readback_port=sandbox,
        trust_policy=trust_policy,
    )  # type: ignore[arg-type]
    _SESSION_POLICIES[capability] = trust_policy
    return capability, sandbox


def seal(capability: object) -> VerifiedSourceEvidence:
    trust_policy = _SESSION_POLICIES[capability]
    proof = _seal_component(
        capability,  # type: ignore[arg-type]
        trust_policy=trust_policy,
    )
    _PROOF_POLICIES[proof] = trust_policy
    return proof


def public(proof: VerifiedSourceEvidence) -> dict[str, object]:
    trust_policy = _PROOF_POLICIES.get(proof)
    if trust_policy is None:
        trust_policy = object.__new__(_trust.CanonicalSourceEvidenceTrustPolicy)
    return _public_component(proof, trust_policy=trust_policy)


def consume(proof: VerifiedSourceEvidence, **changes: object) -> dict[str, object]:
    values = binding()
    values.update(changes)
    return consume_source_evidence(
        proof,
        trust_policy=_PROOF_POLICIES[proof],
        **values,  # type: ignore[arg-type]
    )


def test_valid_lineage_and_mem0_witness_are_one_shot() -> None:
    capability, sandbox = session()
    proof = seal(capability)  # type: ignore[arg-type]
    report = public(proof)
    infinity = report["infinity_source_binding"]
    mem0 = report["mem0_source_witness"]

    assert infinity["retrieved"]["ingestion_id"] == INGESTION  # type: ignore[index]
    assert infinity["ingested"]["source_ref"] == SOURCE  # type: ignore[index]
    assert mem0["request"] == {"request_id": REQUEST, "accepted": True}  # type: ignore[index]
    assert mem0["readback"]["memory_item_id"] == "memory-73"  # type: ignore[index]
    assert "canonical" not in json.dumps(mem0).casefold()
    assert sandbox.seen_ingestion == INGESTION
    assert sandbox.seen_request == REQUEST
    assert all(count == 1 for count in sandbox.calls.values())
    assert consume(proof) == report
    with pytest.raises(SourceEvidenceError, match="already consumed"):
        consume(proof)
    with pytest.raises(SourceEvidenceError, match="not live"):
        seal(capability)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"retrieved": {"derived_only": True}}, "derived-only"),
        ({"retrieved": {"source_ref": "source://other"}}, "does not match"),
        ({"retrieved": {"source_revision": 11}}, "does not match"),
        ({"retrieved": {"source_sha256": "b" * 64}}, "does not match"),
        ({"ingested": {"present": False}}, "missing or deleted"),
        ({"ingested": {"deleted": True}}, "missing or deleted"),
        ({"ingested": {"ingestion_id": "other"}}, "does not bind"),
        ({"request": {"accepted": False}}, "not accepted"),
        ({"request": {"source_ref": "source://other"}}, "does not match"),
        ({"readback": {"found": False}}, "did not find"),
        ({"readback": {"request_id": "other"}}, "does not bind"),
        ({"readback": {"source_sha256": "b" * 64}}, "does not match"),
    ),
)
def test_invalid_lineage_is_rejected(
    changes: dict[str, dict[str, object]],
    message: str,
) -> None:
    capability, _ = session(Sandbox(**changes))
    with pytest.raises(SourceEvidenceError, match=message):
        seal(capability)  # type: ignore[arg-type]
    with pytest.raises(SourceEvidenceError, match="not live"):
        seal(capability)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "other"),
        ("profile_id", "other"),
        ("scope_id", "other"),
        ("case_id", "other"),
        ("source_ref", "source://other"),
        ("source_revision", 99),
        ("source_sha256", "b" * 64),
        ("infinity_backend_id", "other"),
        ("mem0_backend_id", "other"),
    ),
)
def test_consumption_requires_all_bindings(field: str, value: object) -> None:
    proof = seal(session()[0])  # type: ignore[arg-type]
    with pytest.raises(SourceEvidenceError):
        consume(proof, **{field: value})
    assert consume(proof)["run_id"] == RUN


class HostileText(str):
    def __eq__(self, other: object) -> bool:
        del other
        return True


@pytest.mark.parametrize(
    ("mutation", "later"),
    (
        (("retrieved", "run_id", "changed"), "ingested"),
        (("ingested", "source_revision", 99), "request"),
        (("request", "source_ref", HostileText(SOURCE)), "readback"),
        (("readback", "source_sha256", "b" * 64), None),
    ),
)
def test_request_mutation_is_detected(
    mutation: tuple[str, str, object],
    later: str | None,
) -> None:
    sandbox = Sandbox(mutate=mutation)
    capability, _ = session(sandbox)
    with pytest.raises(SourceEvidenceError, match="integrity"):
        seal(capability)  # type: ignore[arg-type]
    if later is not None:
        assert sandbox.calls[later] == 0


def test_public_json_never_admits() -> None:
    proof = seal(session()[0])  # type: ignore[arg-type]
    report = public(proof)
    report["run_id"] = "other"
    with pytest.raises(SourceEvidenceError, match="type must be exact"):
        consume_source_evidence(report, trust_policy=_PROOF_POLICIES[proof], **binding())  # type: ignore[arg-type]
    assert consume(proof)["run_id"] == RUN


def test_concurrent_seal_observes_ports_once() -> None:
    capability, sandbox = session()

    def outcome() -> str:
        try:
            seal(capability)  # type: ignore[arg-type]
        except SourceEvidenceError:
            return "rejected"
        return "sealed"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: outcome(), range(16)))
    assert outcomes.count("sealed") == 1
    assert outcomes.count("rejected") == 15
    assert all(count == 1 for count in sandbox.calls.values())


def test_request_and_proof_cannot_be_forged() -> None:
    with pytest.raises(SourceEvidenceError, match="must be issued"):
        SourceEvidenceRequest(**identity(INFINITY_SOURCE_BACKEND_ID), _token=object())  # type: ignore[arg-type]
    with pytest.raises(SourceEvidenceError, match="must be sealed"):
        VerifiedSourceEvidence(_token=object())
    forged = object.__new__(VerifiedSourceEvidence)
    with pytest.raises(SourceEvidenceError, match="integrity"):
        public(forged)


def test_source_requires_same_policy_at_seal_report_and_consume() -> None:
    capability, _ = session()
    right_policy = _SESSION_POLICIES[capability]
    wrong_policy = policy(Sandbox())

    with pytest.raises(SourceEvidenceError, match="policy"):
        _seal_component(capability, trust_policy=wrong_policy)  # type: ignore[arg-type]

    proof = seal(capability)
    with pytest.raises(SourceEvidenceError, match="integrity"):
        _public_component(proof, trust_policy=wrong_policy)
    with pytest.raises(SourceEvidenceError, match="integrity"):
        consume_source_evidence(
            proof,
            trust_policy=wrong_policy,
            **binding(),  # type: ignore[arg-type]
        )

    report = _public_component(proof, trust_policy=right_policy)
    assert report["trust_policy"]["policy_bound"] is True  # type: ignore[index]
    assert report["component_only"] is True
    assert report["externally_authentic"] is False
    assert report["composite_policy_consume_required"] is True
    assert consume(proof)["run_id"] == RUN


def test_source_policy_lane_replay_and_wrong_ports_are_rejected() -> None:
    capability, sandbox = session()
    trust_policy = _SESSION_POLICIES[capability]

    with pytest.raises(SourceEvidenceError, match="trust policy"):
        issue_source_evidence_session(
            **binding(),
            retrieved_port=sandbox,
            ingested_port=sandbox,
            mem0_request_port=sandbox,
            mem0_readback_port=sandbox,
            trust_policy=trust_policy,
        )  # type: ignore[arg-type]

    other = Sandbox()
    other_policy = policy(sandbox)
    with pytest.raises(SourceEvidenceError, match="trust policy"):
        issue_source_evidence_session(
            **binding(),
            retrieved_port=other,
            ingested_port=other,
            mem0_request_port=other,
            mem0_readback_port=other,
            trust_policy=other_policy,
        )  # type: ignore[arg-type]
    assert all(count == 0 for count in sandbox.calls.values())
    assert all(count == 0 for count in other.calls.values())
