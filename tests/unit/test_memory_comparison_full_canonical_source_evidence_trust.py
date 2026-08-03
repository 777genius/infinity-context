from __future__ import annotations

import copy
import pickle

import pytest
from infinity_context_server import (
    memory_comparison_full_canonical_evidence as canonical_evidence,
)
from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as trust,
)
from infinity_context_server import (
    memory_comparison_full_source_evidence as source_evidence,
)
from infinity_context_server.memory_comparison_full_canonical_evidence import (
    INFINITY_CANONICAL_BACKEND_ID,
    CanonicalEvidenceError,
    issue_canonical_evidence_session,
)


class EqualPort:
    calls = 0

    def __eq__(self, other: object) -> bool:
        del other
        return True

    def observe_lifecycle(self, request: object) -> object:
        del request
        self.calls += 1
        return object()

    def read_canonical(self, request: object, *, canonical_record_id: str) -> object:
        del request, canonical_record_id
        self.calls += 1
        return object()


class EqualText(str):
    def __eq__(self, other: object) -> bool:
        del other
        return True


def ports() -> tuple[object, ...]:
    return tuple(EqualPort() for _ in range(6))


def issue_policy(
    bound_ports: tuple[object, ...],
    **changes: object,
) -> trust.CanonicalSourceEvidenceTrustPolicy:
    values = {
        "policy_id": "policy-17",
        "canonical_backend_id": INFINITY_CANONICAL_BACKEND_ID,
        "infinity_source_backend_id": "infinity-context",
        "mem0_source_backend_id": "mem0",
        "canonical_adapter_id": "canonical-adapter-v4",
        "infinity_source_adapter_id": "source-adapter-v7",
        "mem0_source_adapter_id": "mem0-adapter-v3",
        "canonical_implementation_sha256": "1" * 64,
        "infinity_source_implementation_sha256": "2" * 64,
        "mem0_source_implementation_sha256": "3" * 64,
        "runtime_attestation_commitment": "4" * 64,
        "canonical_lifecycle_port": bound_ports[0],
        "canonical_readback_port": bound_ports[1],
        "infinity_retrieved_port": bound_ports[2],
        "infinity_ingested_port": bound_ports[3],
        "mem0_request_port": bound_ports[4],
        "mem0_readback_port": bound_ports[5],
    }
    values.update(changes)
    return trust._composition_issue_canonical_source_evidence_trust_policy(
        **values  # type: ignore[arg-type]
    )


def test_policy_has_no_public_self_issuer_and_cannot_be_forged() -> None:
    assert "_composition_issue_canonical_source_evidence_trust_policy" not in trust.__all__
    assert all("register" not in name and "issue" not in name for name in trust.__all__)
    assert "issue_canonical_evidence_session" not in canonical_evidence.__all__
    assert "issue_source_evidence_session" not in source_evidence.__all__

    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="composition-root"):
        trust.CanonicalSourceEvidenceTrustPolicy(_token=object())

    forged = object.__new__(trust.CanonicalSourceEvidenceTrustPolicy)
    port = EqualPort()
    with pytest.raises(CanonicalEvidenceError, match="trust policy"):
        issue_canonical_evidence_session(
            run_id="run",
            profile_id="profile",
            backend_id=INFINITY_CANONICAL_BACKEND_ID,
            scope_id="scope",
            case_id="case",
            source_ref="source://one",
            minimum_generation=1,
            minimum_watermark=1,
            lifecycle_port=port,
            readback_port=port,
            trust_policy=forged,
        )
    assert port.calls == 0


def test_raw_ports_and_self_asserted_hashes_cannot_issue_evidence() -> None:
    port = EqualPort()
    with pytest.raises(TypeError, match="trust_policy"):
        issue_canonical_evidence_session(  # type: ignore[call-arg]
            run_id="run",
            profile_id="profile",
            backend_id=INFINITY_CANONICAL_BACKEND_ID,
            scope_id="scope",
            case_id="case",
            source_ref="source://one",
            minimum_generation=1,
            minimum_watermark=1,
            lifecycle_port=port,
            readback_port=port,
        )
    with pytest.raises(TypeError, match="implementation_sha256"):
        issue_canonical_evidence_session(  # type: ignore[call-arg]
            run_id="run",
            profile_id="profile",
            backend_id=INFINITY_CANONICAL_BACKEND_ID,
            scope_id="scope",
            case_id="case",
            source_ref="source://one",
            minimum_generation=1,
            minimum_watermark=1,
            lifecycle_port=port,
            readback_port=port,
            trust_policy=object(),
            canonical_implementation_sha256="1" * 64,
        )
    assert port.calls == 0


def test_snapshot_binds_provenance_and_is_component_only() -> None:
    bound_ports = ports()
    policy = issue_policy(bound_ports)
    lease = trust._reserve_canonical_source_evidence_trust(
        policy,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
        backend_ids=(INFINITY_CANONICAL_BACKEND_ID,),
    )
    trust._begin_canonical_source_evidence_trust(
        policy,
        lease,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
    )
    report = trust._seal_canonical_source_evidence_trust(
        policy,
        lease,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
    )

    assert report["policy_id"] == "policy-17"
    assert report["adapter_ids"] == {
        "canonical": "canonical-adapter-v4",
        "infinity_source": "source-adapter-v7",
        "mem0_source": "mem0-adapter-v3",
    }
    assert report["implementation_sha256"] == {
        "canonical": "1" * 64,
        "infinity_source": "2" * 64,
        "mem0_source": "3" * 64,
    }
    assert report["runtime_attestation_commitment"] == "4" * 64
    assert report["policy_bound"] is True
    assert report["externally_authentic"] is False
    assert report["component_only"] is True
    assert report["composite_policy_consume_required"] is True

    assert (
        trust._consume_canonical_source_evidence_trust_component(
            policy,
            lease,
            lane=trust.CANONICAL_POLICY_LANE,
            port_bindings=bound_ports[:2],
        )
        == report
    )
    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="already consumed"):
        trust._consume_canonical_source_evidence_trust_component(
            policy,
            lease,
            lane=trust.CANONICAL_POLICY_LANE,
            port_bindings=bound_ports[:2],
        )


def test_policy_rejects_replay_wrong_ports_and_cross_policy_lease() -> None:
    bound_ports = ports()
    policy = issue_policy(bound_ports)
    lease = trust._reserve_canonical_source_evidence_trust(
        policy,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
        backend_ids=(INFINITY_CANONICAL_BACKEND_ID,),
    )

    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="already reserved"):
        trust._reserve_canonical_source_evidence_trust(
            policy,
            lane=trust.CANONICAL_POLICY_LANE,
            port_bindings=bound_ports[:2],
            backend_ids=(INFINITY_CANONICAL_BACKEND_ID,),
        )

    another_policy = issue_policy(ports(), policy_id="policy-18")
    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="identity"):
        trust._begin_canonical_source_evidence_trust(
            another_policy,
            lease,
            lane=trust.CANONICAL_POLICY_LANE,
            port_bindings=bound_ports[:2],
        )

    source_policy = issue_policy(ports(), policy_id="policy-19")
    wrong_but_equal = tuple(EqualPort() for _ in range(4))
    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="differ"):
        trust._reserve_canonical_source_evidence_trust(
            source_policy,
            lane=trust.SOURCE_POLICY_LANE,
            port_bindings=wrong_but_equal,
            backend_ids=("infinity-context", "mem0"),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("policy_id", EqualText("policy-17")),
        ("canonical_adapter_id", EqualText("canonical-adapter-v4")),
        ("canonical_implementation_sha256", EqualText("1" * 64)),
        ("runtime_attestation_commitment", EqualText("4" * 64)),
    ),
)
def test_custom_equality_cannot_enter_policy_snapshot(field: str, value: object) -> None:
    with pytest.raises(trust.CanonicalSourceEvidenceTrustError, match="exact|string|sha256"):
        issue_policy(ports(), **{field: value})


def test_policy_mutation_is_rejected_without_changing_live_lease() -> None:
    bound_ports = ports()
    policy = issue_policy(bound_ports)
    lease = trust._reserve_canonical_source_evidence_trust(
        policy,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
        backend_ids=(INFINITY_CANONICAL_BACKEND_ID,),
    )

    with pytest.raises(AttributeError):
        object.__setattr__(policy, "policy_id", "mutated")
    with pytest.raises(AttributeError):
        object.__setattr__(policy, "commitment", "0" * 64)

    trust._begin_canonical_source_evidence_trust(
        policy,
        lease,
        lane=trust.CANONICAL_POLICY_LANE,
        port_bindings=bound_ports[:2],
    )


def test_policy_is_final_and_nonserializable() -> None:
    policy = issue_policy(ports())
    with pytest.raises(TypeError):

        class Child(trust.CanonicalSourceEvidenceTrustPolicy):
            pass

    with pytest.raises(TypeError):
        pickle.dumps(policy)
    with pytest.raises(TypeError):
        copy.copy(policy)
    with pytest.raises(TypeError):
        copy.deepcopy(policy)
