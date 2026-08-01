from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_managed_run import ManagedRunError
from managed_run_test_support import (
    MANAGED_ATTESTATION as _MANAGED_ATTESTATION,
)
from managed_run_test_support import (
    Abort as _Abort,
)
from managed_run_test_support import (
    assert_not_published as _assert_not_published,
)
from managed_run_test_support import (
    delete_events as _deletes,
)
from managed_run_test_support import (
    make_plan as _plan,
)
from managed_run_test_support import (
    make_rig as _rig,
)
from managed_run_test_support import (
    run_managed as _run,
)


@pytest.mark.parametrize(
    "stage",
    ("retrieve", "answer", "judge", "execution.seal", "canonical_source.seal"),
)
def test_every_post_ingest_baseexception_runs_both_delete_passes(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    rig = _rig()
    if stage == "canonical_source.seal":
        rig.policy.fail_at = stage
    elif stage in {"judge", "execution.seal"}:
        rig.judge.fail_at = stage
    else:
        rig.execution.fail_at = stage

    with pytest.raises(_Abort, match=stage) as raised:
        _run(rig, monkeypatch)

    assert _deletes(rig.events) == [
        "delete:infinity-context:1",
        "delete:mem0:1",
        "delete:infinity-context:2",
        "delete:mem0:2",
    ]
    assert "delete.seal" in rig.events
    assert rig.policy.terminal_managed_attestation is _MANAGED_ATTESTATION
    assert rig.policy.terminal_managed_commitment == "8" * 64
    assert not getattr(raised.value, "__notes__", ())
    _assert_not_published(rig.events)


def test_pre_attestation_failure_runs_deletes_without_false_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.attest.fail = True

    with pytest.raises(RuntimeError, match="attest failed") as raised:
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert rig.policy.terminal_managed_attestation is None
    assert rig.policy.terminal_managed_commitment is None
    assert not getattr(raised.value, "__notes__", ())
    _assert_not_published(rig.events)


def test_manifest_mismatch_blocks_publish_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.manifest_override = "9" * 64

    with pytest.raises(ManagedRunError, match="case manifest"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "canonical_source.seal" in rig.events
    assert "components.issue" not in rig.events


def test_cleanup_failure_attempts_all_deletes_and_blocks_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.fail_at = "delete:mem0:1"

    with pytest.raises(RuntimeError, match="delete:mem0:1"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_reused_lane_receipts_fail_before_execution_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.execution.reuse_receipts = True

    with pytest.raises(ManagedRunError, match="receipt identity"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_reused_delete_receipt_attempts_all_cleanup_and_blocks_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.reuse_delete_receipts = True

    with pytest.raises(ManagedRunError, match="globally distinct"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    _assert_not_published(rig.events)


def test_judge_binding_mismatch_burns_authority_before_reset_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    rig = _rig()
    rig.judge.bind_mismatch = True

    with pytest.raises(ManagedRunError, match="judge case material"):
        _run(rig, monkeypatch, plan=admission)

    assert rig.events == ["judge.bind"]
    retry = _rig()
    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(retry, monkeypatch, plan=admission)
    assert retry.events == []


def test_judge_bind_time_mutation_fails_before_reset_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.mutate_during_bind = True

    with pytest.raises(ManagedRunError, match="changed during execution"):
        _run(rig, monkeypatch)

    assert rig.events == ["judge.bind"]


def test_nested_private_metadata_mutation_fails_after_lanes_before_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.mutate_nested_metadata = True

    with pytest.raises(ManagedRunError, match="changed during execution"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_answer_query_mutation_fails_before_execution_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.execution.mutate_query = True

    with pytest.raises(ManagedRunError, match="answer case material changed"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_execution_seal_revalidates_private_case_commitments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.material_override = (("opaque-case", "0" * 64),)

    with pytest.raises(ManagedRunError, match="admitted case material"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "canonical_source.seal" in rig.events
    assert "components.issue" not in rig.events


def test_verified_plan_commitment_tampering_fails_before_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    object.__setattr__(admission, "_VerifiedManagedRunPlan__commitment", "0" * 64)
    rig = _rig()

    with pytest.raises(ManagedRunError, match="integrity failed"):
        _run(rig, monkeypatch, plan=admission)

    assert rig.events == []


def test_policy_attestation_commitment_mismatch_cleans_up_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.expected_managed_commitment_sha256 = "9" * 64

    with pytest.raises(ManagedRunError, match="commitment mismatch"):
        _run(rig, monkeypatch)

    assert rig.events.count("canonical_source.seal") == 1
    assert len(_deletes(rig.events)) == 4
    assert rig.events.index("canonical_source.seal") < rig.events.index("delete:infinity-context:1")
    _assert_not_published(rig.events)


def test_none_managed_attestation_commitment_cleans_up_before_ingest_or_policy_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()

    with pytest.raises(ManagedRunError, match="managed attestation must be SHA-256") as raised:
        _run(rig, monkeypatch, attestation_commitment=None)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert getattr(raised.value, "__notes__", ()) == [
        "terminal cleanup also failed: ManagedRunError"
    ]
    assert not any(item.startswith("ingest:") for item in rig.events)
    assert "canonical_source.seal" not in rig.events
    _assert_not_published(rig.events)


def test_none_managed_attestation_cleans_up_before_ingest_or_policy_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    with pytest.raises(ManagedRunError, match="managed attestation is missing") as raised:
        _run(rig, monkeypatch, managed_attestation=None)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert not getattr(raised.value, "__notes__", ())
    assert not any(item.startswith("ingest:") for item in rig.events)
    assert "canonical_source.seal" not in rig.events
    _assert_not_published(rig.events)
