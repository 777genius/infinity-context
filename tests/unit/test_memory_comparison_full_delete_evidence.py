from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import infinity_context_server.memory_comparison_full_delete_evidence as delete_evidence_module
import pytest
from infinity_context_server.memory_comparison_full_delete_evidence import (
    DeleteEvidenceVerificationError,
    DeleteScopeRequest,
    DeleteVerificationTrustPolicy,
    InfinityCleanupWitness,
    InfinityReadbackWitness,
    Mem0CleanupWitness,
    Mem0ReadbackWitness,
    SealedTerminalDeleteEvidence,
    TerminalDeleteEvidenceSession,
    TrustedDeleteVerificationCoordinator,
    consume_terminal_delete_evidence,
    create_terminal_delete_evidence_session,
    create_trusted_delete_verification_coordinator,
    seal_terminal_delete_evidence,
    terminal_delete_evidence_report,
)
from infinity_context_server.memory_comparison_full_delete_evidence_trust import (
    _create_delete_verification_trust_policy_issuer_for_composition_root,
    _issue_delete_verification_trust_policy_for_composition_root,
)

RUN = "run-delete-1"
PROFILE = "mem0-locomo-top200-v1"
INFINITY_BACKEND = "infinity-context"
MEM0_BACKEND = "mem0-managed"
SCOPE = "benchmark-user-42"
SOURCE = "locomo-corpus-2026"
INFINITY_ADAPTER = "fake-infinity-delete-adapter"
MEM0_ADAPTER = "fake-mem0-delete-adapter"
INFINITY_IMPLEMENTATION = "1" * 64
MEM0_IMPLEMENTATION = "2" * 64
EXTERNAL_ATTESTATION = "3" * 64
AUTHORITY_IMPLEMENTATION = "4" * 64


def _session(**overrides: str) -> TerminalDeleteEvidenceSession:
    values = {
        "run_id": RUN,
        "profile_id": PROFILE,
        "infinity_backend_id": INFINITY_BACKEND,
        "mem0_backend_id": MEM0_BACKEND,
        "scope_id": SCOPE,
        "source_id": SOURCE,
    }
    values.update(overrides)
    return create_terminal_delete_evidence_session(**values)


def _consume(
    evidence: SealedTerminalDeleteEvidence,
    session: TerminalDeleteEvidenceSession,
    policy: DeleteVerificationTrustPolicy,
    **overrides: str,
) -> None:
    values = {
        "consumer_id": "future-composite-1",
        "run_id": RUN,
        "profile_id": PROFILE,
        "infinity_backend_id": INFINITY_BACKEND,
        "mem0_backend_id": MEM0_BACKEND,
        "scope_id": SCOPE,
        "source_id": SOURCE,
    }
    values.update(overrides)
    consume_terminal_delete_evidence(evidence, session, policy=policy, **values)


class FakeInfinityDeletePort:
    def __init__(
        self,
        *,
        acknowledge: bool = True,
        wrong_field: tuple[str, object] | None = None,
        remaining: tuple[int, int] = (0, 0),
        second_deleted: tuple[int, int] = (0, 0),
        missing_readback: bool = False,
    ) -> None:
        self.acknowledge = acknowledge
        self.wrong_field = wrong_field
        self.remaining = remaining
        self.second_deleted = second_deleted
        self.missing_readback = missing_readback
        self.calls: list[tuple[str, DeleteScopeRequest]] = []

    def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
        self.calls.append(("cleanup", request))
        deleted = (3, 4) if request.attempt == 1 else self.second_deleted
        values: dict[str, object] = {
            "run_id": request.run_id,
            "profile_id": request.profile_id,
            "backend_id": request.backend_id,
            "scope_id": request.scope_id,
            "source_id": request.source_id,
            "attempt": request.attempt,
            "acknowledged": self.acknowledge,
            "canonical_deleted_count": deleted[0],
            "derived_deleted_count": deleted[1],
            "already_absent": sum(deleted) == 0,
        }
        if self.wrong_field is not None:
            values[self.wrong_field[0]] = self.wrong_field[1]
        return InfinityCleanupWitness(**values)

    def readback(self, request: DeleteScopeRequest) -> InfinityReadbackWitness:
        self.calls.append(("readback", request))
        if self.missing_readback:
            return None  # type: ignore[return-value]
        return InfinityReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            canonical_remaining_count=self.remaining[0],
            derived_remaining_count=self.remaining[1],
        )


class FakeMem0DeletePort:
    def __init__(
        self,
        *,
        acknowledge: bool = True,
        wrong_field: tuple[str, object] | None = None,
        remaining: int = 0,
        second_deleted: int = 0,
        missing_readback: bool = False,
    ) -> None:
        self.acknowledge = acknowledge
        self.wrong_field = wrong_field
        self.remaining = remaining
        self.second_deleted = second_deleted
        self.missing_readback = missing_readback
        self.calls: list[tuple[str, DeleteScopeRequest]] = []

    def cleanup(self, request: DeleteScopeRequest) -> Mem0CleanupWitness:
        self.calls.append(("cleanup", request))
        deleted = 5 if request.attempt == 1 else self.second_deleted
        values: dict[str, object] = {
            "run_id": request.run_id,
            "profile_id": request.profile_id,
            "backend_id": request.backend_id,
            "scope_id": request.scope_id,
            "source_id": request.source_id,
            "attempt": request.attempt,
            "acknowledged": self.acknowledge,
            "deleted_count": deleted,
            "already_absent": deleted == 0,
        }
        if self.wrong_field is not None:
            values[self.wrong_field[0]] = self.wrong_field[1]
        return Mem0CleanupWitness(**values)

    def readback(self, request: DeleteScopeRequest) -> Mem0ReadbackWitness:
        self.calls.append(("readback", request))
        if self.missing_readback:
            return None  # type: ignore[return-value]
        return Mem0ReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            remaining_count=self.remaining,
        )


@dataclass(frozen=True, slots=True)
class _TrustFixture:
    policy: DeleteVerificationTrustPolicy
    coordinator: TrustedDeleteVerificationCoordinator


def _trust(
    infinity: FakeInfinityDeletePort,
    mem0: FakeMem0DeletePort,
) -> _TrustFixture:
    issuer = _create_delete_verification_trust_policy_issuer_for_composition_root(
        authority_id="unit-test-composition-root",
        authority_implementation_sha256=AUTHORITY_IMPLEMENTATION,
    )
    policy = _issue_delete_verification_trust_policy_for_composition_root(
        issuer,
        infinity_port=infinity,
        mem0_port=mem0,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        infinity_adapter_id=INFINITY_ADAPTER,
        mem0_adapter_id=MEM0_ADAPTER,
        infinity_implementation_sha256=INFINITY_IMPLEMENTATION,
        mem0_implementation_sha256=MEM0_IMPLEMENTATION,
        external_attestation_commitment=EXTERNAL_ATTESTATION,
    )
    return _TrustFixture(
        policy,
        create_trusted_delete_verification_coordinator(policy=policy),
    )


def _seal(
    session: TerminalDeleteEvidenceSession | None = None,
    infinity: FakeInfinityDeletePort | None = None,
    mem0: FakeMem0DeletePort | None = None,
) -> tuple[
    TerminalDeleteEvidenceSession,
    SealedTerminalDeleteEvidence,
    FakeInfinityDeletePort,
    FakeMem0DeletePort,
    DeleteVerificationTrustPolicy,
]:
    active_session = session or _session()
    infinity_port = infinity or FakeInfinityDeletePort()
    mem0_port = mem0 or FakeMem0DeletePort()
    trust = _trust(infinity_port, mem0_port)
    evidence = seal_terminal_delete_evidence(
        active_session,
        policy=trust.policy,
        coordinator=trust.coordinator,
    )
    return active_session, evidence, infinity_port, mem0_port, trust.policy


def test_terminal_delete_seal_records_scoped_absence_and_idempotent_cleanup() -> None:
    session, evidence, infinity, mem0, policy = _seal()
    report = terminal_delete_evidence_report(evidence, policy=policy)

    assert json.loads(json.dumps(report)) == report
    assert report["run_id"] == RUN
    assert report["profile_id"] == PROFILE
    assert report["scope_id"] == SCOPE
    assert report["source_id"] == SOURCE
    assert report["evidence_role"] == "component_only"
    assert report["externally_authentic"] is False
    assert report["composite_policy_consume_required"] is True
    assert report["verification_policy"]["external_attestation_commitment"] == (
        EXTERNAL_ATTESTATION
    )
    assert report["infinity"] == {
        "backend_id": INFINITY_BACKEND,
        "adapter_provenance": {
            "adapter_id": INFINITY_ADAPTER,
            "implementation_sha256": INFINITY_IMPLEMENTATION,
            "policy_bound": True,
        },
        "first_cleanup": {
            "attempt": 1,
            "acknowledged": True,
            "canonical_deleted_count": 3,
            "derived_deleted_count": 4,
            "already_absent": False,
        },
        "first_readback": {
            "attempt": 1,
            "canonical_remaining_count": 0,
            "derived_remaining_count": 0,
        },
        "second_cleanup": {
            "attempt": 2,
            "acknowledged": True,
            "canonical_deleted_count": 0,
            "derived_deleted_count": 0,
            "already_absent": True,
        },
        "second_readback": {
            "attempt": 2,
            "canonical_remaining_count": 0,
            "derived_remaining_count": 0,
        },
        "idempotent_second_cleanup": True,
        "terminal_absence": True,
    }
    assert report["mem0"]["idempotent_second_cleanup"] is True
    assert [kind for kind, _ in infinity.calls] == [
        "cleanup",
        "readback",
        "cleanup",
        "readback",
    ]
    assert [kind for kind, _ in mem0.calls] == [
        "cleanup",
        "readback",
        "cleanup",
        "readback",
    ]
    _consume(evidence, session, policy)
    assert terminal_delete_evidence_report(evidence, policy=policy) == report


@pytest.mark.parametrize("backend", ("infinity", "mem0"))
def test_false_cleanup_ack_fails_closed_and_session_can_retry(backend: str) -> None:
    session = _session()
    infinity = FakeInfinityDeletePort(acknowledge=backend != "infinity")
    mem0 = FakeMem0DeletePort(acknowledge=backend != "mem0")
    trust = _trust(infinity, mem0)

    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            session,
            policy=trust.policy,
            coordinator=trust.coordinator,
        )

    retry_infinity = FakeInfinityDeletePort()
    retry_mem0 = FakeMem0DeletePort()
    retry_trust = _trust(retry_infinity, retry_mem0)
    evidence = seal_terminal_delete_evidence(
        session,
        policy=retry_trust.policy,
        coordinator=retry_trust.coordinator,
    )
    assert terminal_delete_evidence_report(evidence, policy=retry_trust.policy)["scope_id"] == SCOPE


@pytest.mark.parametrize(
    ("infinity", "mem0"),
    (
        (FakeInfinityDeletePort(missing_readback=True), FakeMem0DeletePort()),
        (FakeInfinityDeletePort(), FakeMem0DeletePort(missing_readback=True)),
        (FakeInfinityDeletePort(remaining=(1, 0)), FakeMem0DeletePort()),
        (FakeInfinityDeletePort(remaining=(0, 1)), FakeMem0DeletePort()),
        (FakeInfinityDeletePort(), FakeMem0DeletePort(remaining=1)),
    ),
)
def test_missing_or_nonempty_readback_fails_closed(
    infinity: FakeInfinityDeletePort,
    mem0: FakeMem0DeletePort,
) -> None:
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )


@pytest.mark.parametrize(
    ("infinity", "mem0"),
    (
        (FakeInfinityDeletePort(second_deleted=(1, 0)), FakeMem0DeletePort()),
        (FakeInfinityDeletePort(second_deleted=(0, 1)), FakeMem0DeletePort()),
        (FakeInfinityDeletePort(), FakeMem0DeletePort(second_deleted=1)),
    ),
)
def test_second_cleanup_must_observe_idempotent_noop(
    infinity: FakeInfinityDeletePort,
    mem0: FakeMem0DeletePort,
) -> None:
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "wrong-run"),
        ("profile_id", "wrong-profile"),
        ("backend_id", "wrong-backend"),
        ("scope_id", "wrong-scope"),
        ("source_id", "wrong-source"),
        ("attempt", 2),
    ),
)
@pytest.mark.parametrize("backend", ("infinity", "mem0"))
def test_every_cleanup_witness_identity_is_exactly_bound(
    field: str,
    value: object,
    backend: str,
) -> None:
    infinity = FakeInfinityDeletePort(wrong_field=(field, value) if backend == "infinity" else None)
    mem0 = FakeMem0DeletePort(wrong_field=(field, value) if backend == "mem0" else None)
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )


def test_seal_is_one_time_and_admission_is_exact_one_time() -> None:
    session, evidence, infinity, mem0, policy = _seal()

    competing_trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="not open"):
        seal_terminal_delete_evidence(
            session,
            policy=competing_trust.policy,
            coordinator=competing_trust.coordinator,
        )
    with pytest.raises(DeleteEvidenceVerificationError, match="binding mismatch"):
        _consume(evidence, session, policy, scope_id="wrong-scope")

    other_session = _session(run_id="run-delete-2")
    with pytest.raises(DeleteEvidenceVerificationError, match="binding mismatch"):
        _consume(evidence, other_session, policy)

    _consume(evidence, session, policy)
    with pytest.raises(DeleteEvidenceVerificationError, match="stale or replayed"):
        _consume(evidence, session, policy)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "wrong-run"),
        ("profile_id", "wrong-profile"),
        ("infinity_backend_id", "wrong-infinity"),
        ("mem0_backend_id", "wrong-mem0"),
        ("scope_id", "wrong-scope"),
        ("source_id", "wrong-source"),
    ),
)
def test_admission_revalidates_every_exact_binding(
    field: str,
    value: str,
) -> None:
    session, evidence, _, _, policy = _seal()
    with pytest.raises(DeleteEvidenceVerificationError, match="binding mismatch"):
        _consume(evidence, session, policy, **{field: value})

    _consume(evidence, session, policy)
    with pytest.raises(DeleteEvidenceVerificationError, match="stale or replayed"):
        _consume(evidence, session, policy)


def test_public_report_and_forged_capabilities_are_never_admission_input() -> None:
    session, evidence, _, _, policy = _seal()
    report = terminal_delete_evidence_report(evidence, policy=policy)
    report["externally_authentic"] = True
    report["composite_policy_consume_required"] = False
    revalidated = terminal_delete_evidence_report(evidence, policy=policy)
    assert revalidated["externally_authentic"] is False
    assert revalidated["composite_policy_consume_required"] is True
    assert revalidated["commitment"] == report["commitment"]

    with pytest.raises(DeleteEvidenceVerificationError, match="type is invalid"):
        _consume(report, session, policy)  # type: ignore[arg-type]

    forged = object.__new__(SealedTerminalDeleteEvidence)
    object.__setattr__(forged, "_SealedTerminalDeleteEvidence__commitment", report["commitment"])
    with pytest.raises(DeleteEvidenceVerificationError, match="unregistered"):
        terminal_delete_evidence_report(forged, policy=policy)

    with pytest.raises(DeleteEvidenceVerificationError, match="must be issued"):
        SealedTerminalDeleteEvidence(commitment="0" * 64, _token=None)
    with pytest.raises(DeleteEvidenceVerificationError, match="must be issued"):
        TerminalDeleteEvidenceSession(commitment="0" * 64, _token=None)

    with pytest.raises(DeleteEvidenceVerificationError, match="must be issued"):
        DeleteVerificationTrustPolicy(commitment="0" * 64, _token=None)

    with pytest.raises(DeleteEvidenceVerificationError, match="must be issued"):
        TrustedDeleteVerificationCoordinator(commitment="0" * 64, _token=None)


def test_mutated_session_and_seal_fail_revalidation() -> None:
    session, evidence, _, _, policy = _seal()
    original = evidence._SealedTerminalDeleteEvidence__commitment
    object.__setattr__(evidence, "_SealedTerminalDeleteEvidence__commitment", "0" * 64)
    with pytest.raises(DeleteEvidenceVerificationError, match="integrity"):
        terminal_delete_evidence_report(evidence, policy=policy)
    object.__setattr__(evidence, "_SealedTerminalDeleteEvidence__commitment", original)

    object.__setattr__(session, "_TerminalDeleteEvidenceSession__commitment", "0" * 64)
    with pytest.raises(DeleteEvidenceVerificationError, match="integrity"):
        terminal_delete_evidence_report(evidence, policy=policy)


def test_coordinator_capability_is_policy_bound_and_revalidated() -> None:
    session = _session()
    infinity = FakeInfinityDeletePort()
    mem0 = FakeMem0DeletePort()
    trust = _trust(infinity, mem0)
    coordinator = trust.coordinator
    evidence = seal_terminal_delete_evidence(
        session,
        policy=trust.policy,
        coordinator=coordinator,
    )
    original = coordinator._TrustedDeleteVerificationCoordinator__commitment

    object.__setattr__(
        coordinator,
        "_TrustedDeleteVerificationCoordinator__commitment",
        "0" * 64,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="coordinator integrity"):
        terminal_delete_evidence_report(evidence, policy=trust.policy)
    object.__setattr__(
        coordinator,
        "_TrustedDeleteVerificationCoordinator__commitment",
        original,
    )
    assert (
        terminal_delete_evidence_report(
            evidence,
            policy=trust.policy,
        )["coordinator_commitment"]
        == original
    )

    forged = object.__new__(TrustedDeleteVerificationCoordinator)
    object.__setattr__(
        forged,
        "_TrustedDeleteVerificationCoordinator__commitment",
        original,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="unissued"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=forged,
        )


def test_unregistered_protocol_port_cannot_issue_admission_evidence() -> None:
    session = _session()
    infinity = FakeInfinityDeletePort()
    mem0 = FakeMem0DeletePort()

    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="policy-bound coordinator"):
        seal_terminal_delete_evidence(
            session,
            policy=trust.policy,
            coordinator=infinity,  # type: ignore[arg-type]
        )
    assert infinity.calls == []
    assert mem0.calls == []


def test_public_api_has_no_raw_port_or_self_asserted_provenance_registration() -> None:
    infinity = FakeInfinityDeletePort()
    mem0 = FakeMem0DeletePort()

    assert not hasattr(
        delete_evidence_module,
        "register_trusted_delete_verification_coordinator",
    )
    with pytest.raises(TypeError):
        create_trusted_delete_verification_coordinator(  # type: ignore[call-arg]
            infinity_port=infinity,
            mem0_port=mem0,
            infinity_backend_id=INFINITY_BACKEND,
            mem0_backend_id=MEM0_BACKEND,
            infinity_adapter_id=INFINITY_ADAPTER,
            mem0_adapter_id=MEM0_ADAPTER,
            infinity_implementation_sha256=INFINITY_IMPLEMENTATION,
            mem0_implementation_sha256=MEM0_IMPLEMENTATION,
        )
    assert infinity.calls == []
    assert mem0.calls == []


def test_cross_policy_coordinator_report_and_consume_fail_closed() -> None:
    session = _session()
    infinity = FakeInfinityDeletePort()
    mem0 = FakeMem0DeletePort()
    trust = _trust(infinity, mem0)
    other_trust = _trust(infinity, mem0)

    with pytest.raises(DeleteEvidenceVerificationError, match="coordinator integrity"):
        seal_terminal_delete_evidence(
            session,
            policy=trust.policy,
            coordinator=other_trust.coordinator,
        )
    assert infinity.calls == []
    assert mem0.calls == []

    evidence = seal_terminal_delete_evidence(
        session,
        policy=trust.policy,
        coordinator=trust.coordinator,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="coordinator integrity"):
        terminal_delete_evidence_report(evidence, policy=other_trust.policy)
    with pytest.raises(DeleteEvidenceVerificationError, match="coordinator integrity"):
        _consume(evidence, session, other_trust.policy)

    _consume(evidence, session, trust.policy)


def test_mutated_or_forged_policy_cannot_report_or_consume() -> None:
    session, evidence, _, _, policy = _seal()
    original = policy._DeleteVerificationTrustPolicy__commitment
    object.__setattr__(
        policy,
        "_DeleteVerificationTrustPolicy__commitment",
        "0" * 64,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="policy integrity"):
        terminal_delete_evidence_report(evidence, policy=policy)
    object.__setattr__(
        policy,
        "_DeleteVerificationTrustPolicy__commitment",
        original,
    )

    forged = object.__new__(DeleteVerificationTrustPolicy)
    object.__setattr__(
        forged,
        "_DeleteVerificationTrustPolicy__commitment",
        original,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="unissued"):
        terminal_delete_evidence_report(evidence, policy=forged)
    _consume(evidence, session, policy)


@pytest.mark.parametrize(
    "attestation",
    ("", "3" * 63, "3" * 65, "G" * 64, True),
)
def test_composition_root_policy_requires_exact_external_attestation_commitment(
    attestation: object,
) -> None:
    issuer = _create_delete_verification_trust_policy_issuer_for_composition_root(
        authority_id="unit-test-composition-root",
        authority_implementation_sha256=AUTHORITY_IMPLEMENTATION,
    )
    with pytest.raises(DeleteEvidenceVerificationError, match="attestation commitment"):
        _issue_delete_verification_trust_policy_for_composition_root(
            issuer,
            infinity_port=FakeInfinityDeletePort(),
            mem0_port=FakeMem0DeletePort(),
            infinity_backend_id=INFINITY_BACKEND,
            mem0_backend_id=MEM0_BACKEND,
            infinity_adapter_id=INFINITY_ADAPTER,
            mem0_adapter_id=MEM0_ADAPTER,
            infinity_implementation_sha256=INFINITY_IMPLEMENTATION,
            mem0_implementation_sha256=MEM0_IMPLEMENTATION,
            external_attestation_commitment=attestation,  # type: ignore[arg-type]
        )


def test_request_mutation_rejects_custom_string_without_equality_dispatch() -> None:
    class HostileString(str):
        equality_called = False

        def __eq__(self, other: object) -> bool:
            del other
            type(self).equality_called = True
            raise AssertionError("custom equality must not run")

    class MutatingInfinity(FakeInfinityDeletePort):
        def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
            object.__setattr__(request, "scope_id", HostileString(SCOPE))
            return InfinityCleanupWitness(
                run_id=RUN,
                profile_id=PROFILE,
                backend_id=INFINITY_BACKEND,
                scope_id=SCOPE,
                source_id=SOURCE,
                attempt=request.attempt,
                acknowledged=True,
                canonical_deleted_count=0,
                derived_deleted_count=0,
                already_absent=True,
            )

    infinity = MutatingInfinity()
    mem0 = FakeMem0DeletePort()
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )
    assert HostileString.equality_called is False
    assert mem0.calls == []


def test_port_cannot_mutate_dispatched_request_and_rebind_scope() -> None:
    class MutatingInfinity(FakeInfinityDeletePort):
        def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
            object.__setattr__(request, "scope_id", "attacker-scope")
            return InfinityCleanupWitness(
                run_id=request.run_id,
                profile_id=request.profile_id,
                backend_id=request.backend_id,
                scope_id=request.scope_id,
                source_id=request.source_id,
                attempt=request.attempt,
                acknowledged=True,
                canonical_deleted_count=0,
                derived_deleted_count=0,
                already_absent=True,
            )

    infinity = MutatingInfinity()
    mem0 = FakeMem0DeletePort()
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )


def test_mutated_readback_witness_cannot_rebind_source() -> None:
    class RebindingMem0(FakeMem0DeletePort):
        def readback(self, request: DeleteScopeRequest) -> Mem0ReadbackWitness:
            witness = super().readback(request)
            object.__setattr__(witness, "source_id", "attacker-source")
            return witness

    infinity = FakeInfinityDeletePort()
    mem0 = RebindingMem0()
    trust = _trust(infinity, mem0)
    with pytest.raises(DeleteEvidenceVerificationError, match="verification failed"):
        seal_terminal_delete_evidence(
            _session(),
            policy=trust.policy,
            coordinator=trust.coordinator,
        )


def test_witness_mutation_after_seal_does_not_alias_internal_evidence() -> None:
    class RetainingMem0(FakeMem0DeletePort):
        retained: Mem0ReadbackWitness | None = None

        def readback(self, request: DeleteScopeRequest) -> Mem0ReadbackWitness:
            witness = super().readback(request)
            self.retained = witness
            return witness

    mem0 = RetainingMem0()
    _, evidence, _, _, policy = _seal(mem0=mem0)
    before = terminal_delete_evidence_report(evidence, policy=policy)
    assert mem0.retained is not None
    object.__setattr__(mem0.retained, "remaining_count", 99)
    assert terminal_delete_evidence_report(evidence, policy=policy) == before


def test_concurrent_seal_allows_only_one_backend_flow() -> None:
    session = _session()
    entered = threading.Event()
    release = threading.Event()

    class BlockingInfinity(FakeInfinityDeletePort):
        def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
            if request.attempt == 1:
                entered.set()
                assert release.wait(timeout=5)
            return super().cleanup(request)

    infinity = BlockingInfinity()
    mem0 = FakeMem0DeletePort()
    trust = _trust(infinity, mem0)
    competing_infinity = FakeInfinityDeletePort()
    competing_mem0 = FakeMem0DeletePort()
    competing_trust = _trust(competing_infinity, competing_mem0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            seal_terminal_delete_evidence,
            session,
            policy=trust.policy,
            coordinator=trust.coordinator,
        )
        assert entered.wait(timeout=5)
        second = pool.submit(
            seal_terminal_delete_evidence,
            session,
            policy=competing_trust.policy,
            coordinator=competing_trust.coordinator,
        )
        with pytest.raises(DeleteEvidenceVerificationError, match="not open"):
            second.result(timeout=5)
        release.set()
        evidence = first.result(timeout=5)
    assert terminal_delete_evidence_report(evidence, policy=trust.policy)["run_id"] == RUN
    assert len(infinity.calls) == 4
    assert len(mem0.calls) == 4


@pytest.mark.parametrize(
    "kwargs",
    (
        {"run_id": ""},
        {"profile_id": " leading"},
        {"infinity_backend_id": MEM0_BACKEND},
        {"scope_id": " "},
        {"source_id": True},
    ),
)
def test_session_binding_requires_exact_distinct_primitives(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(DeleteEvidenceVerificationError):
        _session(**kwargs)  # type: ignore[arg-type]
