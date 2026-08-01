from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from infinity_context_server import memory_comparison_managed_run as managed
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedAnswerCase,
    ManagedRunError,
    create_managed_comparison_run_bindings,
    public_managed_run,
    run_managed_comparison,
    run_managed_comparison_with_bindings,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError
from managed_run_test_support import (
    CASE_IDS as _CASE_IDS,
)
from managed_run_test_support import (
    MANAGED_ATTESTATION as _MANAGED_ATTESTATION,
)
from managed_run_test_support import (
    Rig as _Rig,
)
from managed_run_test_support import (
    delete_events as _deletes,
)
from managed_run_test_support import (
    make_legacy_plan as _legacy_plan,
)
from managed_run_test_support import (
    make_plan as _plan,
)
from managed_run_test_support import (
    make_rig as _rig,
)
from managed_run_test_support import (
    patch_attestation as _patch_attestation,
)
from managed_run_test_support import (
    run_managed as _run,
)


def test_exact_lifecycle_orders_terminal_delete_before_nine_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    created_bindings: list[object] = []
    factory = managed.create_full_comparison_run_bindings

    def capture_bindings(**kwargs: Any) -> object:
        created = factory(**kwargs)
        created_bindings.append(created)
        return created

    monkeypatch.setattr(managed, "create_full_comparison_run_bindings", capture_bindings)
    outcome = _run(rig, monkeypatch)
    report = public_managed_run(outcome)

    assert rig.events.count("reset") == 1
    assert rig.events.count("attest") == 1
    assert rig.events.count("ingest:infinity-context") == 2
    assert rig.events.count("ingest:mem0") == 2
    assert sum(item.startswith("retrieve:") for item in rig.events) == 4
    assert sum(item.startswith("answer:") for item in rig.events) == 4
    assert sum(item.startswith("judge:") for item in rig.events) == 4
    assert _deletes(rig.events) == [
        "delete:infinity-context:1",
        "delete:mem0:1",
        "delete:infinity-context:2",
        "delete:mem0:2",
    ]
    assert rig.events.index("delete.seal") < rig.events.index("components.issue")
    assert rig.events.index("components.issue") < rig.events.index("verdict.public")
    assert report["managed_run"]["component_count"] == 9
    assert rig.policy.sealed_managed_attestation is _MANAGED_ATTESTATION
    assert rig.policy.sealed_managed_commitment == "8" * 64
    assert rig.events.count("canonical_source.seal") == 1
    assert rig.events.index("canonical_source.seal") < rig.events.index("delete:infinity-context:1")
    first_retrieve = next(event for event in rig.events if event.startswith("retrieve:"))
    assert rig.events.index("canonical_source.seal") < rig.events.index(first_retrieve)
    assert rig.judge.sealed_manifest is not None
    assert tuple(item.case_id for item in rig.judge.sealed_manifest) == rig.judge.bound_aliases
    assert all(raw_id not in repr(rig.judge.sealed_manifest) for raw_id in _CASE_IDS)
    assert len({item.corpus_id for item in rig.judge.sealed_manifest}) == 2
    assert rig.judge.sealed_manifest_sha256 == execution_case_manifest_sha256(
        rig.judge.sealed_manifest
    )
    assert rig.policy.sealed_case_manifest_sha256 == rig.judge.sealed_manifest_sha256
    assert rig.judge.sealed_executions is not None
    first_alias, second_alias = rig.judge.bound_aliases
    assert tuple((item.case_id, item.backend_role) for item in rig.judge.sealed_executions) == (
        (first_alias, "infinity-context"),
        (first_alias, "mem0"),
        (second_alias, "infinity-context"),
        (second_alias, "mem0"),
    )
    assert rig.judge.sealed_case_material is not None
    assert all(type(item) is ManagedAnswerCase for item in rig.execution.queries)
    assert not hasattr(rig.execution, "bound_cases")
    rendered_report = json.dumps(report, sort_keys=True)
    for private in (*_CASE_IDS, "question 1", "answer 1", "D1:1"):
        assert private not in rendered_report
    assert len(created_bindings) == 1
    assert rig.assembler.bindings is created_bindings[0]


def test_precreated_bindings_are_reused_without_runner_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    bindings = create_managed_comparison_run_bindings(admission)
    rig = _rig()
    _patch_attestation(monkeypatch, commitment="8" * 64, attestation=_MANAGED_ATTESTATION)
    monkeypatch.setattr(
        managed,
        "create_full_comparison_run_bindings",
        lambda **_: pytest.fail("runner must reuse composition bindings"),
    )

    outcome = run_managed_comparison_with_bindings(
        admission,
        bindings=bindings,
        reset_port=rig.reset,
        attestation_port=rig.attest,
        ingest_port=rig.ingest,
        clock=rig.clock,
        execution_port=rig.execution,
        judge_port=rig.judge,
        policy_port=rig.policy,
        assembler=rig.assembler,
    )

    assert public_managed_run(outcome)["managed_run"]["component_count"] == 9
    assert rig.assembler.bindings is bindings


def test_canary_runs_full_lifecycle_but_is_never_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    report = public_managed_run(_run(rig, monkeypatch, scope="canary"))

    assert len(_deletes(rig.events)) == 4
    assert report["publishable"] is False
    assert report["eligible"] is False


@pytest.mark.parametrize(
    ("attribute", "role"),
    (
        ("reset", "reset"),
        ("attest", "attestation"),
        ("ingest", "ingest"),
        ("clock", "clock"),
        ("execution", "execution"),
        ("judge", "judge"),
        ("policy", "policy"),
        ("assembler", "assembler"),
    ),
)
def test_preflight_missing_provenance_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    role: str,
) -> None:
    rig = _rig()
    delattr(getattr(rig, attribute), "implementation_sha256")

    with pytest.raises(ManagedRunError, match=f"{role} port provenance"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_preflight_invalid_provenance_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.ingest.adapter_id = ""

    with pytest.raises(ManagedRunError, match="ingest adapter_id"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_preflight_missing_operation_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.clock.now = None  # type: ignore[method-assign,assignment]

    with pytest.raises(ManagedRunError, match="clock port operation"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_plan_scope_is_normalized_and_invalid_scope_fails_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = public_managed_run(_run(_rig(), monkeypatch, plan=_plan(scope=" CANARY ")))

    assert report["scope"] == "canary"
    with pytest.raises(BenchmarkValidationError, match="unsupported full comparison scope"):
        _plan(scope="preview")


def test_direct_legacy_plan_never_authorizes_managed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    with pytest.raises(ManagedRunError, match="requires a verified managed run plan"):
        _run(rig, monkeypatch, plan=_legacy_plan())
    assert rig.events == []


def test_failed_port_preflight_does_not_consume_verified_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    rig = _rig()
    rig.ingest.adapter_id = ""

    with pytest.raises(ManagedRunError, match="ingest adapter_id"):
        _run(rig, monkeypatch, plan=admission)
    assert rig.events == []

    rig.ingest.adapter_id = "ingest"
    public_managed_run(_run(rig, monkeypatch, plan=admission))
    assert rig.events.count("reset") == 1


def test_verified_plan_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _plan()
    public_managed_run(_run(_rig(), monkeypatch, plan=admission))
    retry_rig = _rig()

    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(retry_rig, monkeypatch, plan=admission)

    assert retry_rig.events == []


def test_concurrent_verified_plan_consume_binds_private_cases_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    _patch_attestation(
        monkeypatch,
        commitment="8" * 64,
        attestation=_MANAGED_ATTESTATION,
    )
    rigs = (_rig(), _rig())

    def invoke(rig: _Rig) -> object:
        return run_managed_comparison(
            admission,
            reset_port=rig.reset,
            attestation_port=rig.attest,
            ingest_port=rig.ingest,
            clock=rig.clock,
            execution_port=rig.execution,
            judge_port=rig.judge,
            policy_port=rig.policy,
            assembler=rig.assembler,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(invoke, rig) for rig in rigs)
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]

    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], ManagedRunError)
    assert sum(rig.events.count("judge.bind") for rig in rigs) == 1
    assert sum(rig.events.count("reset") for rig in rigs) == 1
