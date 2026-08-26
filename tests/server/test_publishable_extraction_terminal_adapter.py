"""Provider-free tests for the extraction-suite scheduler terminal adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableExtractionRunTerminal,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_extraction_terminal_adapter as extraction_adapter,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBackendAuthority,
    SchedulerBridgeBootAuthority,
    SchedulerDeadlineTokenAuthority,
    SchedulerRunAuthority,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    verify_authenticated_extraction_terminal,
)

_STORE_SECRETS = (b"locomo-extraction-adapter-secret!!", b"longmem-extraction-adapter-secret!")


def _sha(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def scheduler_authority() -> tuple[
    SchedulerSuiteAuthority,
    tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
]:
    profiles = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
    case_groups = tuple(
        tuple(
            SchedulerCaseAuthority(
                case_id=f"{profile.benchmark.value}-case-{index}",
                case_alias=f"{profile.benchmark.value}-{index}",
            )
            for index in range(profile.case_count)
        )
        for profile in profiles
    )
    backends = (
        SchedulerBackendAuthority("infinity-context", _sha("infinity-target")),
        SchedulerBackendAuthority("mem0", _sha("mem0-target")),
    )

    def binding(index: int) -> SchedulerRunBinding:
        profile = profiles[index]
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1_000,
            dispatch_deadline_unix_ms=2_000,
            answer_max_output_tokens=8,
            judge_max_output_tokens=8,
            run_token_ceiling=profile.case_count * 2 * (8 + 8),
        )
        return SchedulerRunBinding(
            run_id=f"{profile.benchmark.value}-extraction-adapter-run",
            profile=profile,
            binding_commitment_sha256=_sha(f"binding:{index}"),
            dataset_sha256=_sha(f"dataset:{index}"),
            case_manifest_sha256=case_manifest_sha256(case_groups[index]),
            backends=backends,
            limits=limits,
        )

    suite = SchedulerSuiteAuthority(
        suite_id="publishable-extraction-adapter-suite",
        publication_bundle_sha256=_sha("publication-bundle"),
        methodology_sha256=_sha("methodology"),
        source_commit_sha256=_sha("source-commit"),
        bridge_boot=SchedulerBridgeBootAuthority(
            bridge_id="publishable-extraction-adapter-bridge",
            implementation_sha256=_sha("bridge-implementation"),
            runtime_authority_sha256=_sha("runtime-authority"),
            boot_nonce_sha256=_sha("boot-nonce"),
            receipt_verifier_policy_sha256=_sha("receipt-verifier-policy"),
        ),
        ordered_runs=(binding(0), binding(1)),
    )
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=cases)
        for run, cases in zip(runs, case_groups, strict=True)
    )
    specs = tuple(
        SchedulerRunStoreSpec(
            run=run,
            manifest=manifest,
            database_path=Path(f"unused-{index}.sqlite3"),
            private_directory=Path(f"unused-private-{index}"),
            authentication_secret=_STORE_SECRETS[index],
        )
        for index, (run, manifest) in enumerate(zip(runs, manifests, strict=True))
    )
    return suite, specs


def _terminal(
    suite: SchedulerSuiteAuthority,
    spec: SchedulerRunStoreSpec,
    index: int,
    *,
    overrides: dict[str, object] | None = None,
) -> PublishableExtractionRunTerminal:
    run = spec.run
    profile_id, receipt_count = PUBLISHABLE_EXTRACTION_BENCHMARKS[index]
    values: dict[str, object] = {
        "profile_id": profile_id,
        "run_id_sha256": _sha(run.binding.run_id),
        "binding_commitment_sha256": run.binding.binding_commitment_sha256,
        "methodology_commitment_sha256": suite.methodology_sha256,
        "admission_commitment_sha256": _sha(f"admission:{index}"),
        "ingestion_root_sha256": _sha(f"ingestion:{index}"),
        "a1_terminal_commitment_sha256": _sha(f"a1-terminal:{index}"),
        "a1_manifest_context_sha256": _sha(f"a1-context:{index}"),
        "runtime_binding_commitment_sha256": _sha(f"phase-c-runtime:{index}"),
        "scheduler_bridge_runtime_authority_sha256": (suite.bridge_boot.runtime_authority_sha256),
        "expected_receipt_count": receipt_count,
        "dataset_sha256": run.binding.dataset_sha256,
    }
    values.update(overrides or {})
    context = ManagedFullRunExtractionContext(
        profile_id=str(values["profile_id"]),
        run_id_sha256=str(values["run_id_sha256"]),
        binding_commitment_sha256=str(values["binding_commitment_sha256"]),
        methodology_commitment_sha256=str(values["methodology_commitment_sha256"]),
        admission_commitment_sha256=str(values["admission_commitment_sha256"]),
        ingestion_root_sha256=str(values["ingestion_root_sha256"]),
        a1_terminal_commitment_sha256=str(values["a1_terminal_commitment_sha256"]),
        a1_manifest_context_sha256=str(values["a1_manifest_context_sha256"]),
        runtime_binding_commitment_sha256=str(values["runtime_binding_commitment_sha256"]),
        expected_receipt_count=int(values["expected_receipt_count"]),
    )
    page_count = (
        context.expected_receipt_count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1
    ) // FULL_RUN_EXTRACTION_PAGE_SIZE
    ledger_body = {
        "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
        "context_commitment_sha256": context.commitment_sha256,
        "receipt_count": context.expected_receipt_count,
        "page_count": page_count,
        "receipt_pages_root_sha256": _sha(f"receipt-pages:{index}"),
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    ledger = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=context.expected_receipt_count,
        page_count=page_count,
        receipt_pages_root_sha256=str(ledger_body["receipt_pages_root_sha256"]),
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
        terminal_commitment_sha256=canonical_sha256(ledger_body),
    )
    return PublishableExtractionRunTerminal(
        profile_id=context.profile_id,
        run_id_sha256=context.run_id_sha256,
        binding_commitment_sha256=context.binding_commitment_sha256,
        methodology_commitment_sha256=context.methodology_commitment_sha256,
        admission_commitment_sha256=context.admission_commitment_sha256,
        ingestion_root_sha256=context.ingestion_root_sha256,
        a1_terminal_commitment_sha256=context.a1_terminal_commitment_sha256,
        a1_manifest_context_sha256=context.a1_manifest_context_sha256,
        runtime_binding_commitment_sha256=context.runtime_binding_commitment_sha256,
        scheduler_bridge_runtime_authority_sha256=(
            str(values["scheduler_bridge_runtime_authority_sha256"])
        ),
        preparation_receipt_sha256=_sha(f"preparation:{index}"),
        dataset_sha256=str(values["dataset_sha256"]),
        a2_terminal_commitment_sha256=_sha(f"a2-terminal:{index}"),
        expected_receipt_count=context.expected_receipt_count,
        journal_manifest_commitment_sha256=_sha(f"journal-manifest:{index}"),
        journal_state_commitment_sha256=_sha(f"journal-state:{index}"),
        journal_head_event_sha256=_sha(f"journal-head:{index}"),
        ledger_terminal=ledger,
    )


def _readback(
    suite: SchedulerSuiteAuthority,
    specs: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
    *,
    locomo_overrides: dict[str, object] | None = None,
    longmemeval_overrides: dict[str, object] | None = None,
) -> PublishableExtractionSuiteReadback:
    return PublishableExtractionSuiteReadback(
        locomo_terminal=_terminal(suite, specs[0], 0, overrides=locomo_overrides),
        longmemeval_terminal=_terminal(
            suite,
            specs[1],
            1,
            overrides=longmemeval_overrides,
        ),
    )


def test_converts_exact_readback_and_authenticates_with_each_store_secret(
    scheduler_authority,
) -> None:
    suite, specs = scheduler_authority
    readback = _readback(suite, specs)
    adapter = extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
        suite=suite,
        run_stores=specs,
        readback=readback,
    )

    assert adapter.read_policy_sha256 == (
        extraction_adapter.PUBLISHABLE_EXTRACTION_SUITE_TERMINAL_READ_POLICY_SHA256
    )
    assert adapter.read_policy_sha256 == (
        "8ade5efffac4fdceb535a0f2a75c9edb9c42be9357937e62629ba5fa2fcedc38"
    )
    for index, spec in enumerate(specs):
        authenticated = adapter.read_terminal(run=spec.run)
        source = (readback.locomo_terminal, readback.longmemeval_terminal)[index]
        projected = authenticated.evidence.terminal
        assert authenticated.run_authority_sha256 == spec.run.commitment_sha256
        assert projected is not source.ledger_terminal
        assert projected.receipt_count == source.ledger_terminal.receipt_count
        assert projected.page_count == source.ledger_terminal.page_count
        assert (
            projected.receipt_pages_root_sha256 == source.ledger_terminal.receipt_pages_root_sha256
        )
        assert projected.total_tokens == source.ledger_terminal.total_tokens
        assert authenticated.evidence.context.profile_id == source.profile_id
        assert authenticated.evidence.context.run_id_sha256 == source.run_id_sha256
        assert authenticated.evidence.context.binding_commitment_sha256 == (
            source.binding_commitment_sha256
        )
        assert source.runtime_binding_commitment_sha256 != (
            suite.bridge_boot.runtime_authority_sha256
        )
        assert authenticated.evidence.context.runtime_binding_commitment_sha256 == (
            suite.bridge_boot.runtime_authority_sha256
        )
        assert projected.context_commitment_sha256 == (
            authenticated.evidence.context.commitment_sha256
        )
        assert verify_authenticated_extraction_terminal(
            authenticated,
            authentication_secret=spec.authentication_secret,
        )
        assert not verify_authenticated_extraction_terminal(
            authenticated,
            authentication_secret=specs[1 - index].authentication_secret,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id_sha256": _sha("foreign-run")},
        {"binding_commitment_sha256": _sha("foreign-binding")},
        {"dataset_sha256": _sha("foreign-dataset")},
        {"methodology_commitment_sha256": _sha("foreign-methodology")},
    ],
)
def test_rejects_valid_source_terminal_cross_wired_to_scheduler_authority(
    scheduler_authority,
    overrides: dict[str, object],
) -> None:
    suite, specs = scheduler_authority
    readback = _readback(suite, specs, locomo_overrides=overrides)

    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_extraction_terminal_adapter_terminal_divergent",
    ):
        extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=specs,
            readback=readback,
        )


def test_rejects_shared_scheduler_bridge_runtime_cross_wire(scheduler_authority) -> None:
    suite, specs = scheduler_authority
    overrides = {
        "scheduler_bridge_runtime_authority_sha256": _sha("foreign-scheduler-bridge-runtime")
    }
    readback = _readback(
        suite,
        specs,
        locomo_overrides=overrides,
        longmemeval_overrides=overrides,
    )

    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_extraction_terminal_adapter_terminal_divergent",
    ):
        extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=specs,
            readback=readback,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("profile_id", "mem0-longmemeval-top50-v1"),
        ("expected_receipt_count", 5_881),
    ],
)
def test_revalidates_profile_and_count_on_received_readback(
    scheduler_authority,
    field_name: str,
    value: object,
) -> None:
    suite, specs = scheduler_authority
    readback = _readback(suite, specs)
    terminal = readback.locomo_terminal
    object.__setattr__(terminal, field_name, value)
    object.__setattr__(terminal, "terminal_commitment_sha256", canonical_sha256(terminal.body()))
    object.__setattr__(
        readback,
        "suite_readback_commitment_sha256",
        canonical_sha256(readback.body()),
    )

    with pytest.raises(SchedulerRunnerError):
        extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=specs,
            readback=readback,
        )


def test_rejects_terminal_context_cross_wire_and_unknown_run(scheduler_authority) -> None:
    suite, specs = scheduler_authority
    readback = _readback(suite, specs)
    terminal = readback.locomo_terminal
    ledger = terminal.ledger_terminal
    object.__setattr__(ledger, "context_commitment_sha256", _sha("wrong-context"))
    object.__setattr__(
        ledger,
        "terminal_commitment_sha256",
        canonical_sha256(ledger.body()),
    )
    object.__setattr__(terminal, "terminal_commitment_sha256", canonical_sha256(terminal.body()))
    object.__setattr__(
        readback,
        "suite_readback_commitment_sha256",
        canonical_sha256(readback.body()),
    )
    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_extraction_terminal_adapter_terminal_divergent",
    ):
        extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=specs,
            readback=readback,
        )

    clean = _readback(suite, specs)
    adapter = extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
        suite=suite,
        run_stores=specs,
        readback=clean,
    )
    unknown = SchedulerRunAuthority(
        suite_authority_sha256=_sha("foreign-suite"),
        suite_id="foreign-suite",
        run_index=0,
        binding=specs[0].run.binding,
        bridge_boot_authority_sha256=_sha("foreign-bridge-boot"),
    )
    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_extraction_terminal_adapter_run_unknown",
    ):
        adapter.read_terminal(run=unknown)


def test_rejects_swapped_run_store_slots(scheduler_authority) -> None:
    suite, specs = scheduler_authority
    readback = _readback(suite, specs)

    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_extraction_terminal_adapter_suite_invalid",
    ):
        extraction_adapter.PublishableExtractionSuiteTerminalAdapter(
            suite=suite,
            run_stores=(specs[1], specs[0]),
            readback=readback,
        )
