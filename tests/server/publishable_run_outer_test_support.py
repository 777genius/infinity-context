"""Provider-free support for the installed publishable-run composition root."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeJournal,
    BridgeJournalStatistics,
    HmacJournalIntegrity,
)
from infinity_context_server.memory_comparison_paired_superiority_policy import (
    PAIRED_SUPERIORITY_POLICY_SHA256,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    PAIRED_AUTHORITY_MAPPING_SHA256,
    PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
    PairedOutcomeSealBinding,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_CONFIG_SCHEMA,
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableProjectedOfficialCase,
    PublishableRunConfig,
    PublishableRunRuntimeCapabilities,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    SUITE_SEAL_READBACK_POLICY_SHA256,
    SchedulerRunStoreSpec,
    SchedulerStepDisposition,
    SchedulerSuiteSeal,
)
from scheduler_subscription_bridge_composition_test_support import (
    bridge_fleet_readiness,
    official_suite_and_manifests,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
    synthetic_extraction_suite_readback,
)
from subscription_runtime_bridge_test_support import FakeSecrets

PRIVATE_CASE_SENTINEL = "private-official-case-material-2040"
PRIVATE_ADAPTER_SENTINEL = "private-adapter-credential-must-not-publish"
PUBLICATION_AUTHENTICATION_SECRET = bytes([5]) * 32

_CONFIG_KEY_FIELDS = (
    "official_case_authentication_key_hex",
    "locomo_scheduler_authentication_key_hex",
    "longmemeval_scheduler_authentication_key_hex",
    "suite_seal_authentication_key_hex",
    "publication_receipt_authentication_key_hex",
)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PrivateRunFiles:
    root: Path
    config_path: Path
    secrets_path: Path
    config: PublishableRunConfig
    secrets: PublishableRunSecrets

    @property
    def argv(self) -> list[str]:
        return [
            "--private-root",
            str(self.root),
            "--config",
            str(self.config_path),
            "--secrets",
            str(self.secrets_path),
            "--allow-live",
        ]

    def private_needles(self) -> tuple[str, ...]:
        paths = (
            self.root,
            self.config_path,
            self.secrets_path,
            self.config.official_case_authority_path,
            *self.config.scheduler_database_paths,
            self.config.suite_seal_database_path,
            self.config.publication_receipt_path,
        )
        keys = (
            self.secrets.official_case_authentication_key,
            *self.secrets.scheduler_authentication_keys,
            self.secrets.suite_seal_authentication_key,
            self.secrets.publication_receipt_authentication_key,
        )
        return (
            *(str(path) for path in paths),
            *(path.name for path in paths),
            *(key.hex() for key in keys),
            PRIVATE_ADAPTER_SENTINEL,
            PRIVATE_CASE_SENTINEL,
            "locomo-case-0",
            "longmemeval-case-499",
        )


def private_run_files(tmp_path: Path) -> PrivateRunFiles:
    root = tmp_path / "publishable-run-private"
    state = root / "state"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    config_payload = {
        "adapter": {"public_endpoint": "https://provider-free.invalid"},
        "dependency_provider": "tests.provider-free",
        "max_dispatches_per_batch": 17,
        "publication_key_id": "publication-key-2040",
        "schema_version": PUBLISHABLE_RUN_CONFIG_SCHEMA,
        "state": {
            "longmemeval_scheduler_database_path": str(state / "longmemeval.sqlite3"),
            "locomo_scheduler_database_path": str(state / "locomo.sqlite3"),
            "official_case_authority_path": str(state / "official-cases.sqlite3"),
            "publication_receipt_path": str(state / "publication-receipt.json"),
            "suite_seal_database_path": str(state / "suite-seal.sqlite3"),
        },
    }
    secrets_payload = {
        "adapter": {"credential": PRIVATE_ADAPTER_SENTINEL},
        "keys": {
            field_name: (bytes([index]) * 32).hex()
            for index, field_name in enumerate(_CONFIG_KEY_FIELDS, start=1)
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    config_path = _private_json(root / "config.json", config_payload)
    secrets_path = _private_json(root / "secrets.json", secrets_payload)
    config, secrets = load_publishable_run_files(
        private_root=root,
        config_path=config_path,
        secrets_path=secrets_path,
    )
    return PrivateRunFiles(root, config_path, secrets_path, config, secrets)


class SyntheticOfficialCaseProjection:
    """Generate exact identities lazily and optionally fail one page once."""

    def __init__(self, *, crash_on_page_call: int | None = None) -> None:
        self.crash_on_page_call = crash_on_page_call
        self.page_calls: list[tuple[str, int, int]] = []
        self.emitted_case_count = 0

    def read_page(self, *, run, start_case_index: int, limit: int):
        benchmark = run.binding.profile.benchmark.value
        self.page_calls.append((benchmark, start_case_index, limit))
        if self.crash_on_page_call == len(self.page_calls):
            self.crash_on_page_call = None
            raise RuntimeError("synthetic_projection_crash")
        stop = min(start_case_index + limit, run.binding.profile.case_count)
        page = tuple(self._case(benchmark, index) for index in range(start_case_index, stop))
        self.emitted_case_count += len(page)
        return page

    @staticmethod
    def _case(benchmark: str, index: int) -> PublishableProjectedOfficialCase:
        case_id = f"{benchmark}-case-{index}"
        return PublishableProjectedOfficialCase(
            case_index=index,
            case_id=case_id,
            case_alias=f"{benchmark}-{index}",
            case=PublicBenchmarkCase(
                benchmark=benchmark,
                case_id=case_id,
                question=f"{PRIVATE_CASE_SENTINEL}:{benchmark}:{index}",
                expected_terms=("synthetic",),
                metadata={"_evaluator_ground_truth": "synthetic"},
            ),
        )


@dataclass(frozen=True, slots=True)
class FakeRunScenario:
    disposition: SchedulerStepDisposition
    committed_call_count: int
    provider_count: int

    @classmethod
    def publishable(cls) -> FakeRunScenario:
        return cls(
            SchedulerStepDisposition.EVALUATION_COMPLETE,
            PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
            PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        )


@dataclass(slots=True)
class FakeRunState:
    scenario: FakeRunScenario
    crash_after_committed_count: int | None = None
    committed_call_count: int = 0
    provider_count: int = 0
    sealed: bool = False
    crashed: bool = False
    composition_modes: list[PublishableProductionOpenMode] = field(default_factory=list)
    dispatch_accounting: list[int] = field(default_factory=list)

    def statistics(self) -> BridgeJournalStatistics:
        return BridgeJournalStatistics(
            intent_count=self.provider_count,
            result_count=self.provider_count,
            event_count=self.provider_count * 2,
        )


class ProviderFreeDependencyFactory:
    """Real 2,040-case projection plus aggregate-only fake scheduler execution."""

    def __init__(
        self,
        *,
        projection: SyntheticOfficialCaseProjection | None = None,
        scenario: FakeRunScenario | None = None,
        crash_after_committed_count: int | None = None,
    ) -> None:
        self.readiness = bridge_fleet_readiness()
        self.suite, self.runs, self.manifests, _ = official_suite_and_manifests(self.readiness)
        self.projection = projection or SyntheticOfficialCaseProjection()
        self.state = FakeRunState(
            scenario or FakeRunScenario.publishable(),
            crash_after_committed_count=crash_after_committed_count,
        )
        self.retrieval_authority_root_sha256 = sha("provider-free-retrieval-authority")
        self.session_modes: list[PublishableProductionOpenMode] = []
        self.provider_inputs: list[object] = []
        self.case_authority_roots: list[str] = []
        self._runtime_sequence = 0

    def open_session(self, *, inputs, mode):
        self.session_modes.append(mode)
        self.provider_inputs.append(inputs)
        return _ProviderFreeSession(self, inputs=inputs)

    def open_composition(self, **arguments):
        mode = arguments["mode"]
        self.state.composition_modes.append(mode)
        for spec in arguments["run_stores"]:
            _state_marker(spec.database_path)
        _state_marker(arguments["suite_seal_store"].database_path)
        return SimpleNamespace(
            authority_sha256=sha("provider-free-production-composition"),
            runner=_AggregateRunner(self, arguments["suite"]),
        )

    def patched_statistics(self) -> BridgeJournalStatistics:
        return self.state.statistics()


class _ProviderFreeSession:
    def __init__(self, factory: ProviderFreeDependencyFactory, *, inputs) -> None:
        self._factory = factory
        self._inputs = inputs
        self._journal: BridgeJournal | None = None
        self.suite = factory.suite
        self.official_case_projection = factory.projection

    def open_runtime(self, *, case_authority_root_sha256: str):
        factory = self._factory
        factory.case_authority_roots.append(case_authority_root_sha256)
        specs = tuple(
            SchedulerRunStoreSpec(
                run=run,
                manifest=manifest,
                database_path=(self._inputs.state_root / f"extraction-{index}.sqlite3"),
                private_directory=self._inputs.state_root,
                authentication_secret=key,
            )
            for index, (run, manifest, key) in enumerate(
                zip(
                    factory.runs,
                    factory.manifests,
                    (
                        b"provider-free-extraction-authentication-key-0",
                        b"provider-free-extraction-authentication-key-1",
                    ),
                    strict=True,
                )
            )
        )
        runtime_root = self._inputs.state_root / "fake-runtime"
        runtime_root.mkdir(mode=0o700, exist_ok=True)
        runtime_root.chmod(0o700)
        factory._runtime_sequence += 1
        self._journal = BridgeJournal.create(
            runtime_root / f"journal-{factory._runtime_sequence}.sqlite3",
            integrity=HmacJournalIntegrity(b"provider-free-journal-key-material-v1"),
        )
        bridge_keys = FakeSecrets(factory.readiness.pool)
        return PublishableRunRuntimeCapabilities(
            extraction_suite=synthetic_extraction_suite_readback(factory.suite, specs),
            retrieval_authority=_ForbiddenRetrievalAuthority(
                factory.retrieval_authority_root_sha256
            ),
            output_cipher=_ForbiddenOutputCipher(),
            bridge_keys=bridge_keys,
            bridge_fleet_readiness=factory.readiness,
            bridge_transport=_ForbiddenTransport(),
            bridge_journal=self._journal,
            clock=lambda: 2_000,
            lease_id_factory=lambda: "provider-free-lease",
        )

    def close(self) -> None:
        if self._journal is not None:
            self._journal.close()


class _AggregateRunner:
    def __init__(self, factory: ProviderFreeDependencyFactory, suite) -> None:
        self._factory = factory
        self._seal = _suite_seal(suite, factory.runs)

    def committed_call_count(self) -> int:
        return self._factory.state.committed_call_count

    def run_bounded(self, *, max_dispatches: int):
        if max_dispatches < 1:
            raise AssertionError("fake_runner_dispatch_bound_invalid")
        state = self._factory.state
        if state.sealed:
            state.dispatch_accounting.append(0)
            return SimpleNamespace(
                disposition=SchedulerStepDisposition.SEALED,
                provider_dispatches=0,
            )
        before = state.provider_count
        partial = state.crash_after_committed_count
        if partial is not None and not state.crashed:
            if not 0 < partial < state.scenario.committed_call_count:
                raise AssertionError("fake_runner_crash_prefix_invalid")
            state.committed_call_count = partial
            state.provider_count = partial
            state.crashed = True
            state.dispatch_accounting.append(partial - before)
            raise RuntimeError("synthetic_scheduler_crash_after_durable_prefix")
        state.committed_call_count = state.scenario.committed_call_count
        state.provider_count = state.scenario.provider_count
        state.dispatch_accounting.append(state.provider_count - before)
        return SimpleNamespace(
            disposition=state.scenario.disposition,
            provider_dispatches=state.provider_count - before,
        )

    def seal(self) -> SchedulerSuiteSeal:
        self._factory.state.sealed = True
        return self._seal


class _ForbiddenRetrievalAuthority:
    def __init__(self, authority_root_sha256: str) -> None:
        self.authority_root_sha256 = authority_root_sha256

    def read_exact(self, *, key):
        raise AssertionError(f"provider-free retrieval unexpectedly read {type(key).__name__}")


class _ForbiddenOutputCipher:
    def seal(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        raise AssertionError("provider-free output cipher unexpectedly used")


class _ForbiddenTransport:
    def post_once(self, **_arguments):
        raise AssertionError("provider-free transport unexpectedly used")


def _suite_seal(suite, runs) -> SchedulerSuiteSeal:
    return SchedulerSuiteSeal(
        suite_authority_sha256=suite.commitment_sha256,
        runtime_provenance_sha256=suite.runtime_provenance_sha256,
        ordered_run_authority_sha256=tuple(run.commitment_sha256 for run in runs),
        ordered_evaluation_receipt_root_sha256=(sha("evaluation-0"), sha("evaluation-1")),
        ordered_extraction_terminal_sha256=(sha("extraction-0"), sha("extraction-1")),
        ordered_authenticated_extraction_terminal_sha256=(
            sha("authenticated-extraction-0"),
            sha("authenticated-extraction-1"),
        ),
        renderer_policy_sha256=sha("renderer-policy"),
        private_answer_policy_sha256=sha("private-answer-policy"),
        receipt_verifier_policy_sha256=suite.bridge_boot.receipt_verifier_policy_sha256,
        outcome_readback_policy_sha256=sha("outcome-readback-policy"),
        extraction_terminal_read_policy_sha256=sha("extraction-read-policy"),
        seal_readback_policy_sha256=SUITE_SEAL_READBACK_POLICY_SHA256,
        case_count=PUBLISHABLE_SUITE_CASE_COUNT,
        evaluation_call_count=PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        extraction_operation_count=PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
        charged_tokens=PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        paired_outcome=_passing_paired_outcome(),
    )


def _passing_paired_outcome() -> PairedOutcomeSealBinding:
    return PairedOutcomeSealBinding(
        terminal_sha256=sha("paired-terminal"),
        ordered_paired_outcomes_root_sha256=sha("paired-outcomes-root"),
        pair_count=PUBLISHABLE_SUITE_CASE_COUNT,
        judge_normalization_policy_sha256=PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
        authority_mapping_sha256=PAIRED_AUTHORITY_MAPPING_SHA256,
        paired_superiority_policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        policy_evidence_sha256=sha("paired-policy-evidence"),
        policy_publication_bundle_sha256=sha("paired-policy-publication-bundle"),
        paired_superiority_metrics_sha256=sha("paired-superiority-metrics"),
        paired_superiority_decision_sha256=sha("paired-superiority-decision"),
        paired_superiority_criterion_met=True,
    )


def _private_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _state_marker(path: Path) -> None:
    if not path.exists():
        path.touch(mode=0o600)
    path.chmod(0o600)


__all__ = (
    "FakeRunScenario",
    "PRIVATE_ADAPTER_SENTINEL",
    "PRIVATE_CASE_SENTINEL",
    "PUBLICATION_AUTHENTICATION_SECRET",
    "PrivateRunFiles",
    "ProviderFreeDependencyFactory",
    "SyntheticOfficialCaseProjection",
    "private_run_files",
)
