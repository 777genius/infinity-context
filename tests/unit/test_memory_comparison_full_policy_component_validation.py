from __future__ import annotations

import copy
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from infinity_context_server import (
    memory_comparison_full_policy_component_validation as policy_validation,
)
from infinity_context_server.memory_comparison_full_policy_component_validation import (
    FullPolicyComponentValidationError,
    FullPolicyEvidencePair,
    FullPolicyManifestItem,
    FullPolicyRunManifest,
    VerifiedFullPolicyComponentValidation,
    consume_full_policy_component_validation,
    create_full_policy_component_validation_session,
    full_policy_component_validation_session_status,
    full_policy_run_manifest_commitment,
    public_full_policy_component_validation,
    seal_full_policy_component_validation,
)
from memory_comparison_full_policy_component_fixtures import (
    ATTESTATION,
    build_policy_aggregate_fixture,
)


def _session(fixture=None):
    active = fixture or build_policy_aggregate_fixture()
    return create_full_policy_component_validation_session(
        manifest=active.manifest,
        evidence_pairs=active.pairs,
        terminal_delete=active.terminal_delete,
        consumer_id="full-composite-consumer-1",
    )


def _consume(validation, fixture):
    return consume_full_policy_component_validation(
        validation,
        binding_commitment_sha256=full_policy_run_manifest_commitment(fixture.manifest),
        managed_attestation_commitment_sha256=ATTESTATION,
    )


def test_exact_manifest_coverage_seals_only_after_terminal_delete() -> None:
    fixture = build_policy_aggregate_fixture()
    session = _session(fixture)

    assert full_policy_component_validation_session_status(session) == "open"
    validation = seal_full_policy_component_validation(session)
    assert type(validation) is VerifiedFullPolicyComponentValidation
    assert full_policy_component_validation_session_status(session) == "sealed"

    report = public_full_policy_component_validation(validation)
    assert _consume(validation, fixture) == report
    assert json.loads(json.dumps(report)) == report
    assert report["status"] == "verified"
    assert report["run_id"] == fixture.manifest.run_id
    assert report["manifest_commitment_sha256"] == full_policy_run_manifest_commitment(
        fixture.manifest
    )
    assert report["manifest_item_count"] == 2
    assert report["coverage"] == {"canonical": 2, "source": 2, "delete": 1}
    assert len(report["item_policy_commitments"]) == 2
    assert len(set(report["item_policy_commitments"])) == 2
    assert report["managed_attestation_commitment_sha256"] == ATTESTATION
    assert report["delete_consumed_last"] is True
    assert report["all_components_consumed"] is True
    assert report["admission_from_public_json"] is False


def test_consumed_policy_validation_remains_publicly_revalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    validation = seal_full_policy_component_validation(_session(fixture))
    original = policy_validation._preflight_from_validation
    revalidations = 0

    def tracked_revalidation(state):
        nonlocal revalidations
        revalidations += 1
        return original(state)

    monkeypatch.setattr(
        policy_validation,
        "_preflight_from_validation",
        tracked_revalidation,
    )

    consumed = _consume(validation, fixture)

    assert public_full_policy_component_validation(validation) == consumed
    assert revalidations == 2
    with pytest.raises(FullPolicyComponentValidationError, match="already consumed"):
        _consume(validation, fixture)
    assert public_full_policy_component_validation(validation) == consumed
    assert revalidations == 3


@pytest.mark.parametrize(
    ("binding_commitment", "managed_attestation", "message"),
    (
        pytest.param("b" * 64, ATTESTATION, "binding commitment", id="binding"),
        pytest.param(None, "b" * 64, "managed attestation", id="attestation"),
    ),
)
def test_consume_commitment_mismatch_leaves_policy_validation_live(
    binding_commitment: str | None,
    managed_attestation: str,
    message: str,
) -> None:
    fixture = build_policy_aggregate_fixture()
    validation = seal_full_policy_component_validation(_session(fixture))
    expected_binding = full_policy_run_manifest_commitment(fixture.manifest)

    with pytest.raises(FullPolicyComponentValidationError, match=message):
        consume_full_policy_component_validation(
            validation,
            binding_commitment_sha256=(
                expected_binding if binding_commitment is None else binding_commitment
            ),
            managed_attestation_commitment_sha256=managed_attestation,
        )

    assert _consume(validation, fixture)["status"] == "verified"


def test_consume_revalidation_failure_leaves_policy_validation_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    validation = seal_full_policy_component_validation(_session(fixture))
    original = policy_validation.public_full_policy_component_validation

    def fail_revalidation(_validation):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        policy_validation,
        "public_full_policy_component_validation",
        fail_revalidation,
    )
    with pytest.raises(KeyboardInterrupt):
        _consume(validation, fixture)

    monkeypatch.setattr(
        policy_validation,
        "public_full_policy_component_validation",
        original,
    )
    assert _consume(validation, fixture)["status"] == "verified"


def test_concurrent_policy_consumers_have_exactly_one_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    validation = seal_full_policy_component_validation(_session(fixture))
    original = policy_validation.public_full_policy_component_validation
    revalidating = Event()
    release = Event()

    def blocked_revalidation(active_validation):
        revalidating.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test release timed out")
        return original(active_validation)

    monkeypatch.setattr(
        policy_validation,
        "public_full_policy_component_validation",
        blocked_revalidation,
    )

    def outcome() -> str:
        try:
            _consume(validation, fixture)
        except FullPolicyComponentValidationError as exc:
            return str(exc)
        return "consumed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(outcome)
        try:
            assert revalidating.wait(timeout=5)
            loser = pool.submit(outcome)
            assert loser.result(timeout=1) == ("policy validation consumption already active")
        finally:
            release.set()
        assert winner.result(timeout=5) == "consumed"

    with pytest.raises(FullPolicyComponentValidationError, match="already consumed"):
        _consume(validation, fixture)
    assert public_full_policy_component_validation(validation)["status"] == "verified"


def test_manifest_rejects_missing_extra_duplicate_and_reordered_coverage() -> None:
    fixture = build_policy_aggregate_fixture()

    with pytest.raises(FullPolicyComponentValidationError, match="count differs"):
        create_full_policy_component_validation_session(
            manifest=fixture.manifest,
            evidence_pairs=fixture.pairs[:1],
            terminal_delete=fixture.terminal_delete,
            consumer_id="consumer",
        )
    with pytest.raises(FullPolicyComponentValidationError, match="count differs"):
        create_full_policy_component_validation_session(
            manifest=fixture.manifest,
            evidence_pairs=(*fixture.pairs, fixture.pairs[0]),
            terminal_delete=fixture.terminal_delete,
            consumer_id="consumer",
        )

    first = fixture.manifest.items[0]
    with pytest.raises(FullPolicyComponentValidationError, match="duplicated"):
        FullPolicyRunManifest(
            run_id=fixture.manifest.run_id,
            profile_id=fixture.manifest.profile_id,
            infinity_backend_id=fixture.manifest.infinity_backend_id,
            mem0_backend_id=fixture.manifest.mem0_backend_id,
            scope_id=fixture.manifest.scope_id,
            delete_source_id=fixture.manifest.delete_source_id,
            managed_attestation_commitment_sha256=ATTESTATION,
            items=(first, first),
        )

    reordered = create_full_policy_component_validation_session(
        manifest=fixture.manifest,
        evidence_pairs=tuple(reversed(fixture.pairs)),
        terminal_delete=fixture.terminal_delete,
        consumer_id="consumer",
    )
    with pytest.raises(FullPolicyComponentValidationError, match="preflight failed"):
        seal_full_policy_component_validation(reordered)
    assert full_policy_component_validation_session_status(reordered) == "preflight_failed"


@pytest.mark.parametrize(
    "fixture",
    (
        pytest.param(
            build_policy_aggregate_fixture(item_attestation="b" * 64),
            id="canonical-source-managed-attestation",
        ),
        pytest.param(
            build_policy_aggregate_fixture(delete_attestation="b" * 64),
            id="delete-managed-attestation",
        ),
    ),
)
def test_every_policy_requires_the_same_managed_attestation_before_consumption(
    fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        policy_validation,
        "consume_canonical_evidence",
        lambda *args, **kwargs: calls.append("canonical"),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_source_evidence",
        lambda *args, **kwargs: calls.append("source"),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_terminal_delete_evidence",
        lambda *args, **kwargs: calls.append("delete"),
    )
    session = _session(fixture)

    with pytest.raises(FullPolicyComponentValidationError, match="preflight failed"):
        seal_full_policy_component_validation(session)

    assert calls == []
    assert full_policy_component_validation_session_status(session) == "preflight_failed"
    with pytest.raises(FullPolicyComponentValidationError, match="terminal"):
        seal_full_policy_component_validation(session)


def test_one_exact_policy_must_own_both_proofs_in_each_pair() -> None:
    fixture = build_policy_aggregate_fixture()
    first, second = fixture.pairs
    crossed = FullPolicyEvidencePair(first.canonical, second.source, first.trust_policy)
    session = create_full_policy_component_validation_session(
        manifest=fixture.manifest,
        evidence_pairs=(crossed, second),
        terminal_delete=fixture.terminal_delete,
        consumer_id="consumer",
    )

    with pytest.raises(FullPolicyComponentValidationError, match="preflight failed"):
        seal_full_policy_component_validation(session)
    assert full_policy_component_validation_session_status(session) == "preflight_failed"


@pytest.mark.parametrize("failure_position", range(5))
def test_each_consume_position_is_fail_closed_and_retry_is_rejected(
    failure_position: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    session = _session(fixture)
    original = {
        "canonical": policy_validation.consume_canonical_evidence,
        "source": policy_validation.consume_source_evidence,
        "delete": policy_validation.consume_terminal_delete_evidence,
    }
    trace: list[str] = []

    def invoke(kind: str, *args, **kwargs):
        position = len(trace)
        trace.append(kind)
        if position == failure_position:
            raise RuntimeError("injected consume failure")
        return original[kind](*args, **kwargs)

    monkeypatch.setattr(
        policy_validation,
        "consume_canonical_evidence",
        lambda *args, **kwargs: invoke("canonical", *args, **kwargs),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_source_evidence",
        lambda *args, **kwargs: invoke("source", *args, **kwargs),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_terminal_delete_evidence",
        lambda *args, **kwargs: invoke("delete", *args, **kwargs),
    )

    with pytest.raises(FullPolicyComponentValidationError, match="consumption failed"):
        seal_full_policy_component_validation(session)

    assert trace == ["canonical", "source", "canonical", "source", "delete"][: failure_position + 1]
    assert (
        full_policy_component_validation_session_status(session) == "partial_component_consumption"
    )
    with pytest.raises(FullPolicyComponentValidationError, match="terminal"):
        seal_full_policy_component_validation(session)


def test_concurrent_loser_fails_fast_while_primary_is_blocked_in_real_consume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    session = _session(fixture)
    original = policy_validation.consume_canonical_evidence
    lower_consumed = Event()
    release = Event()

    def consume_then_block(*args, **kwargs):
        original(*args, **kwargs)
        lower_consumed.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test release timed out")

    monkeypatch.setattr(
        policy_validation,
        "consume_canonical_evidence",
        consume_then_block,
    )

    def loser_outcome() -> str:
        try:
            seal_full_policy_component_validation(session)
        except FullPolicyComponentValidationError as exc:
            return str(exc)
        return "unexpected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        primary = pool.submit(seal_full_policy_component_validation, session)
        try:
            assert lower_consumed.wait(timeout=5)
            loser = pool.submit(loser_outcome)
            assert loser.result(timeout=1) == "aggregate consumption already active"
        finally:
            release.set()
        assert type(primary.result(timeout=5)) is VerifiedFullPolicyComponentValidation

    assert full_policy_component_validation_session_status(session) == "sealed"


def test_keyboard_interrupt_after_real_consume_aborts_and_fresh_retry_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    session = _session(fixture)
    original = policy_validation.consume_canonical_evidence
    lower_consumed = Event()
    release = Event()

    def consume_then_interrupt(*args, **kwargs):
        original(*args, **kwargs)
        lower_consumed.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test release timed out")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        policy_validation,
        "consume_canonical_evidence",
        consume_then_interrupt,
    )

    def primary_outcome() -> str:
        try:
            seal_full_policy_component_validation(session)
        except KeyboardInterrupt:
            return "interrupted"
        return "unexpected"

    with ThreadPoolExecutor(max_workers=1) as pool:
        primary = pool.submit(primary_outcome)
        try:
            assert lower_consumed.wait(timeout=5)
        finally:
            release.set()
        assert primary.result(timeout=5) == "interrupted"

    state = policy_validation._session_state(session)
    assert state.phase == "partial_component_consumption"
    assert state.started_count == 1
    assert state.completed_count == 0
    assert state.active_owner is None
    assert state.validation is None
    assert not any(
        validation_state.session is session
        for validation_state in policy_validation._VALIDATIONS.values()
    )
    with pytest.raises(
        FullPolicyComponentValidationError,
        match="terminal or active: partial_component_consumption",
    ):
        seal_full_policy_component_validation(session)


def test_token_failure_after_all_real_consumes_aborts_without_mint_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    session = _session(fixture)
    originals = {
        "canonical": policy_validation.consume_canonical_evidence,
        "source": policy_validation.consume_source_evidence,
        "delete": policy_validation.consume_terminal_delete_evidence,
    }
    trace: list[str] = []

    def invoke(kind: str, *args, **kwargs):
        result = originals[kind](*args, **kwargs)
        trace.append(kind)
        return result

    monkeypatch.setattr(
        policy_validation,
        "consume_canonical_evidence",
        lambda *args, **kwargs: invoke("canonical", *args, **kwargs),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_source_evidence",
        lambda *args, **kwargs: invoke("source", *args, **kwargs),
    )
    monkeypatch.setattr(
        policy_validation,
        "consume_terminal_delete_evidence",
        lambda *args, **kwargs: invoke("delete", *args, **kwargs),
    )

    def interrupt_token_mint(size: int) -> bytes:
        assert size == 32
        raise KeyboardInterrupt

    monkeypatch.setattr(policy_validation.secrets, "token_bytes", interrupt_token_mint)

    with pytest.raises(KeyboardInterrupt):
        seal_full_policy_component_validation(session)

    assert trace == ["canonical", "source", "canonical", "source", "delete"]
    state = policy_validation._session_state(session)
    assert state.phase == "partial_component_consumption"
    assert state.started_count == 5
    assert state.completed_count == 5
    assert state.active_position is None
    assert state.active_owner is None
    assert state.validation is None
    assert not any(
        validation_state.session is session
        for validation_state in policy_validation._VALIDATIONS.values()
    )
    with pytest.raises(FullPolicyComponentValidationError, match="terminal"):
        seal_full_policy_component_validation(session)
    assert trace == ["canonical", "source", "canonical", "source", "delete"]


def test_successful_consume_order_is_manifest_pairs_then_delete_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_policy_aggregate_fixture()
    originals = (
        policy_validation.consume_canonical_evidence,
        policy_validation.consume_source_evidence,
        policy_validation.consume_terminal_delete_evidence,
    )
    trace: list[str] = []

    def canonical(*args, **kwargs):
        trace.append(f"canonical:{kwargs['case_id']}")
        return originals[0](*args, **kwargs)

    def source(*args, **kwargs):
        trace.append(f"source:{kwargs['case_id']}")
        return originals[1](*args, **kwargs)

    def delete(*args, **kwargs):
        trace.append("delete")
        return originals[2](*args, **kwargs)

    monkeypatch.setattr(policy_validation, "consume_canonical_evidence", canonical)
    monkeypatch.setattr(policy_validation, "consume_source_evidence", source)
    monkeypatch.setattr(policy_validation, "consume_terminal_delete_evidence", delete)

    validation = seal_full_policy_component_validation(_session(fixture))

    assert trace == [
        "canonical:case-1",
        "source:case-1",
        "canonical:case-2",
        "source:case-2",
        "delete",
    ]
    assert public_full_policy_component_validation(validation)["delete_consumed_last"] is True


def test_concurrent_callers_issue_exactly_one_validation() -> None:
    session = _session()

    def outcome() -> str:
        try:
            seal_full_policy_component_validation(session)
        except FullPolicyComponentValidationError:
            return "rejected"
        return "sealed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: outcome(), range(2)))

    assert sorted(outcomes) == ["rejected", "sealed"]
    assert full_policy_component_validation_session_status(session) == "sealed"


def test_public_json_copy_pickle_and_forged_objects_never_admit() -> None:
    fixture = build_policy_aggregate_fixture()
    validation = seal_full_policy_component_validation(_session(fixture))
    report = public_full_policy_component_validation(validation)
    report["status"] = "forged"
    report["coverage"] = {"canonical": 999, "source": 999, "delete": 999}

    with pytest.raises(FullPolicyComponentValidationError, match="type must be exact"):
        public_full_policy_component_validation(report)  # type: ignore[arg-type]
    assert public_full_policy_component_validation(validation)["status"] == "verified"

    with pytest.raises(TypeError):
        copy.copy(validation)
    with pytest.raises(TypeError):
        copy.deepcopy(validation)
    with pytest.raises(TypeError):
        pickle.dumps(validation)
    with pytest.raises(FullPolicyComponentValidationError, match="unregistered"):
        public_full_policy_component_validation(
            object.__new__(VerifiedFullPolicyComponentValidation)
        )


def test_manifest_snapshots_primitives_and_rejects_nonexact_items() -> None:
    fixture = build_policy_aggregate_fixture(item_count=1)
    session = _session(fixture)
    original_commitment = full_policy_run_manifest_commitment(fixture.manifest)
    object.__setattr__(fixture.manifest, "run_id", "mutated-run")

    validation = seal_full_policy_component_validation(session)
    report = public_full_policy_component_validation(validation)
    assert report["run_id"] == "run-policy-1"
    assert report["manifest_commitment_sha256"] == original_commitment

    with pytest.raises(FullPolicyComponentValidationError, match="manifest item type"):
        replace(fixture.manifest, items=(object(),))  # type: ignore[arg-type]
    with pytest.raises(FullPolicyComponentValidationError, match="positive exact integer"):
        FullPolicyManifestItem("case", "source://case", True, "1" * 64)
