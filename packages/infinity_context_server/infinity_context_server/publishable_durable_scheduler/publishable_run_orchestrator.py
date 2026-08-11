"""Outer resumable composition and exact publication-attestation lifecycle."""

from __future__ import annotations

import hmac
import os
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.features.subscription_runtime_bridge.process_files import (
    read_private_json,
    write_private_json_once,
    write_private_json_replace,
)
from infinity_context_server.memory_comparison_publishable_go_readiness import (
    PublishableExecutionAuthority,
    PublishableExecutionPolicyError,
    require_active_publishable_execution_authority,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
    verify_publishable_run_attestation,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunDependencyFactoryPort,
    PublishableRunError,
    PublishableRunProviderInputs,
    PublishableRunRuntimeCapabilities,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_official_cases import (
    PreparedPublishableOfficialCases,
    prepare_publishable_official_cases,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    SchedulerStepDisposition,
    SchedulerSuiteSeal,
)

PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT = 64 * 1024

PublishableProductionComposition = (
    publishable_production_composition.PublishableProductionComposition
)
PublishableProductionOpenMode = publishable_production_composition.PublishableProductionOpenMode
PublishableProductionCompositionOpener = Callable[..., PublishableProductionComposition]
_IMMUTABLE_TERMINAL_DISPOSITIONS = frozenset(
    {
        SchedulerStepDisposition.DEADLINE_EXHAUSTED.value,
        SchedulerStepDisposition.FAILED_KNOWN.value,
        SchedulerStepDisposition.FROZEN_OUTCOME_UNKNOWN.value,
        SchedulerStepDisposition.SEALED.value,
    }
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunOrchestrator:
    """Join injected adapters to the reviewed production scheduler composition."""

    dependency_factory: PublishableRunDependencyFactoryPort = field(repr=False)
    composition_opener: PublishableProductionCompositionOpener = field(
        default=(publishable_production_composition.open_publishable_production_composition),
        repr=False,
    )

    def __post_init__(self) -> None:
        if not callable(getattr(self.dependency_factory, "open_session", None)) or not callable(
            self.composition_opener
        ):
            _fail("publishable_run_orchestrator_invalid")

    def run(
        self,
        *,
        config: PublishableRunConfig,
        secrets: PublishableRunSecrets,
    ) -> PublishableRunAttestation:
        if type(config) is not PublishableRunConfig or type(secrets) is not PublishableRunSecrets:
            _fail("publishable_run_orchestrator_inputs_invalid")
        _require_cross_layer_secret_distinctness(secrets)
        execution_authority = _issue_publishable_execution_authority()
        mode = _open_mode(config)
        prior_receipt = _authenticate_existing_receipt(config=config, secrets=secrets)
        session = self.dependency_factory.open_session(
            inputs=PublishableRunProviderInputs(
                state_root=_provider_state_root(config),
                adapter_config_json=config.adapter_config_json,
                adapter_secrets_json=secrets.adapter_secrets_json,
            ),
            mode=mode,
        )
        prepared: PreparedPublishableOfficialCases | None = None
        try:
            if not callable(getattr(session, "open_runtime", None)) or not callable(
                getattr(session, "close", None)
            ):
                _fail("publishable_run_session_invalid")
            suite = session.suite
            projection = session.official_case_projection
            prepared = prepare_publishable_official_cases(
                suite=suite,
                projection=projection,
                config=config,
                secrets=secrets,
            )
            runtime = session.open_runtime(
                case_authority_root_sha256=prepared.terminal.authority_root_sha256,
            )
            if type(runtime) is not PublishableRunRuntimeCapabilities:
                _fail("publishable_run_runtime_capabilities_invalid")
            receipt = self._execute(
                mode=mode,
                config=config,
                secrets=secrets,
                prepared=prepared,
                suite=suite,
                runtime=runtime,
                prior_receipt=prior_receipt,
                execution_authority=execution_authority,
            )
        finally:
            try:
                if prepared is not None:
                    prepared.close()
            finally:
                close_session = getattr(session, "close", None)
                if callable(close_session):
                    close_session()
        return _persist_exact_receipt(receipt, config=config, secrets=secrets)

    def _execute(
        self,
        *,
        mode: PublishableProductionOpenMode,
        config: PublishableRunConfig,
        secrets: PublishableRunSecrets,
        prepared: PreparedPublishableOfficialCases,
        suite: SchedulerSuiteAuthority,
        runtime: PublishableRunRuntimeCapabilities,
        prior_receipt: PublishableRunAttestation | None,
        execution_authority: PublishableExecutionAuthority,
    ) -> PublishableRunAttestation:
        composition = self._open(
            mode=mode,
            prepared=prepared,
            suite=suite,
            runtime=runtime,
            execution_authority=execution_authority,
        )
        initial_committed = composition.runner.committed_call_count()
        initial_statistics = runtime.bridge_journal.statistics()
        checkpoint = _authority_checkpoint(
            config=config,
            secrets=secrets,
            prepared=prepared,
            suite=suite,
            runtime=runtime,
            composition=composition,
            committed_call_count=initial_committed,
            statistics=initial_statistics,
        )
        if prior_receipt is None:
            if (
                initial_committed != 0
                or initial_statistics.intent_count != 0
                or initial_statistics.result_count != 0
                or initial_statistics.physical_receipt_count != 0
                or initial_statistics.event_count != 0
            ):
                _fail("publishable_run_authority_checkpoint_missing")
            _persist_exact_receipt(checkpoint, config=config, secrets=secrets)
        else:
            _require_authority_binding(prior=prior_receipt, observed=checkpoint)
        disposition = _drive(
            composition,
            max_dispatches=config.max_dispatches_per_batch,
        )
        seal: SchedulerSuiteSeal | None = None
        if disposition in {
            SchedulerStepDisposition.EVALUATION_COMPLETE,
            SchedulerStepDisposition.SEALED,
        }:
            seal = composition.runner.seal()
            disposition = SchedulerStepDisposition.SEALED
        final_committed = composition.runner.committed_call_count()
        statistics = runtime.bridge_journal.statistics()
        provider_dispatches = statistics.intent_count - initial_statistics.intent_count
        accounting_complete = (
            provider_dispatches >= 0
            and final_committed == initial_committed + provider_dispatches
            and statistics.intent_count
            == statistics.result_count
            == statistics.physical_receipt_count
            == final_committed
        )
        if seal is not None:
            self._require_exact_reopen(
                composition=composition,
                prepared=prepared,
                suite=suite,
                runtime=runtime,
                seal=seal,
                statistics=statistics,
                execution_authority=execution_authority,
            )
        return PublishableRunAttestation.create(
            suite_authority_sha256=suite.commitment_sha256,
            ordered_run_authority_sha256=tuple(item.commitment_sha256 for item in prepared.runs),
            official_case_authority_root_sha256=(prepared.terminal.authority_root_sha256),
            retrieval_authority_root_sha256=(runtime.retrieval_authority.authority_root_sha256),
            extraction_suite_readback_sha256=(
                runtime.extraction_suite.suite_readback_commitment_sha256
            ),
            production_composition_authority_sha256=composition.authority_sha256,
            suite_seal_sha256=None if seal is None else seal.commitment_sha256,
            terminal_disposition=disposition.value,
            case_count=prepared.terminal.case_count,
            evaluation_call_count=final_committed,
            extraction_operation_count=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
            provider_intent_count=statistics.intent_count,
            provider_result_count=statistics.result_count,
            provider_call_count=statistics.intent_count,
            provider_accounting_complete=accounting_complete,
            charged_tokens=None if seal is None else seal.charged_tokens,
            call_ledger=None if seal is None else seal.call_ledger,
            paired_outcome=None if seal is None else seal.paired_outcome,
            authentication_key_id=config.publication_key_id,
            authentication_secret=secrets.publication_receipt_authentication_key,
        )

    def _open(
        self,
        *,
        mode: PublishableProductionOpenMode,
        prepared: PreparedPublishableOfficialCases,
        suite: SchedulerSuiteAuthority,
        runtime: PublishableRunRuntimeCapabilities,
        execution_authority: PublishableExecutionAuthority,
    ) -> PublishableProductionComposition:
        _require_publishable_execution_authority(
            execution_authority,
            suite=suite,
        )
        return self.composition_opener(
            mode=mode,
            suite=suite,
            run_stores=prepared.run_stores,
            extraction_suite=runtime.extraction_suite,
            official_case_authority=prepared.reader,
            retrieval_capture_authority=runtime.retrieval_authority,
            output_cipher=runtime.output_cipher,
            bridge_keys=runtime.bridge_keys,
            bridge_fleet_readiness=runtime.bridge_fleet_readiness,
            bridge_transport=runtime.bridge_transport,
            bridge_journal=runtime.bridge_journal,
            clock=runtime.clock,
            lease_id_factory=runtime.lease_id_factory,
            suite_seal_store=prepared.seal_store,
            lease_duration_ms=runtime.lease_duration_ms,
        )

    def _require_exact_reopen(
        self,
        *,
        composition: PublishableProductionComposition,
        prepared: PreparedPublishableOfficialCases,
        suite: SchedulerSuiteAuthority,
        runtime: PublishableRunRuntimeCapabilities,
        seal: SchedulerSuiteSeal,
        statistics: object,
        execution_authority: PublishableExecutionAuthority,
    ) -> None:
        reopened = self._open(
            mode=PublishableProductionOpenMode.RESUME,
            prepared=prepared,
            suite=suite,
            runtime=runtime,
            execution_authority=execution_authority,
        )
        step = reopened.runner.run_bounded(max_dispatches=1)
        if (
            step.disposition is not SchedulerStepDisposition.SEALED
            or step.provider_dispatches != 0
            or reopened.runner.seal() != seal
            or reopened.runner.committed_call_count() != PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
            or reopened.authority_sha256 != composition.authority_sha256
            or runtime.bridge_journal.statistics() != statistics
            or seal.case_count != PUBLISHABLE_SUITE_CASE_COUNT
            or seal.evaluation_call_count != PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
            or seal.extraction_operation_count != PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT
        ):
            _fail("publishable_run_exact_reopen_failed")


def _issue_publishable_execution_authority() -> PublishableExecutionAuthority:
    """Reject the active candidate before filesystem or provider capabilities."""

    try:
        return require_active_publishable_execution_authority(
            publishable_production_composition.publishable_production_execution_orchestration_authority()
        )
    except PublishableExecutionPolicyError:
        _fail("publishable_run_execution_profile_blocked")
    except Exception:
        _fail("publishable_run_execution_profile_blocked")


def _require_publishable_execution_authority(
    authority: PublishableExecutionAuthority,
    *,
    suite: SchedulerSuiteAuthority,
) -> None:
    """Rebind the admission before every production composition open."""

    try:
        publishable_production_composition.require_publishable_production_execution_authority(
            authority,
            suite=suite,
        )
    except Exception:
        _fail("publishable_run_execution_authority_invalid")


def _drive(
    composition: PublishableProductionComposition,
    *,
    max_dispatches: int,
) -> SchedulerStepDisposition:
    while True:
        step = composition.runner.run_bounded(max_dispatches=max_dispatches)
        if step.disposition is SchedulerStepDisposition.COMMITTED:
            continue
        return step.disposition


def _require_cross_layer_secret_distinctness(secrets: PublishableRunSecrets) -> None:
    """Reject adapter plaintext or hex material equal to any outer authority key."""

    outer_keys = (
        secrets.official_case_authentication_key,
        *secrets.scheduler_authentication_keys,
        secrets.suite_seal_authentication_key,
        secrets.publication_receipt_authentication_key,
    )
    stack: list[object] = [secrets.adapter_secrets()]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            stack.extend(current.values())
        elif type(current) is list:
            stack.extend(current)
        elif type(current) is str and any(
            _adapter_string_matches_key(current, key) for key in outer_keys
        ):
            _fail("publishable_run_cross_layer_secret_reuse")


def _adapter_string_matches_key(value: str, key: bytes) -> bool:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("publishable_run_adapter_secrets_invalid")
    if len(encoded) == len(key) and hmac.compare_digest(encoded, key):
        return True
    return (
        len(value) == len(key) * 2
        and value.isascii()
        and all(character in "0123456789abcdefABCDEF" for character in value)
        and hmac.compare_digest(value.casefold(), key.hex())
    )


def _authority_checkpoint(
    *,
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
    prepared: PreparedPublishableOfficialCases,
    suite: SchedulerSuiteAuthority,
    runtime: PublishableRunRuntimeCapabilities,
    composition: PublishableProductionComposition,
    committed_call_count: int,
    statistics: object,
) -> PublishableRunAttestation:
    """Authenticate every immutable runtime authority before the first dispatch."""

    return PublishableRunAttestation.create(
        suite_authority_sha256=suite.commitment_sha256,
        ordered_run_authority_sha256=tuple(item.commitment_sha256 for item in prepared.runs),
        official_case_authority_root_sha256=prepared.terminal.authority_root_sha256,
        retrieval_authority_root_sha256=runtime.retrieval_authority.authority_root_sha256,
        extraction_suite_readback_sha256=(
            runtime.extraction_suite.suite_readback_commitment_sha256
        ),
        production_composition_authority_sha256=composition.authority_sha256,
        suite_seal_sha256=None,
        terminal_disposition="prepared",
        case_count=prepared.terminal.case_count,
        evaluation_call_count=committed_call_count,
        extraction_operation_count=PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
        provider_intent_count=statistics.intent_count,
        provider_result_count=statistics.result_count,
        provider_call_count=statistics.intent_count,
        provider_accounting_complete=(
            statistics.intent_count
            == statistics.result_count
            == statistics.physical_receipt_count
            == committed_call_count
        ),
        charged_tokens=None,
        authentication_key_id=config.publication_key_id,
        authentication_secret=secrets.publication_receipt_authentication_key,
    )


def _require_authority_binding(
    *,
    prior: PublishableRunAttestation,
    observed: PublishableRunAttestation,
) -> None:
    prior_binding = (
        prior.suite_authority_sha256,
        prior.ordered_run_authority_sha256,
        prior.official_case_authority_root_sha256,
        prior.retrieval_authority_root_sha256,
        prior.extraction_suite_readback_sha256,
        prior.production_composition_authority_sha256,
        prior.case_count,
        prior.extraction_operation_count,
        prior.authentication_key_id,
    )
    observed_binding = (
        observed.suite_authority_sha256,
        observed.ordered_run_authority_sha256,
        observed.official_case_authority_root_sha256,
        observed.retrieval_authority_root_sha256,
        observed.extraction_suite_readback_sha256,
        observed.production_composition_authority_sha256,
        observed.case_count,
        observed.extraction_operation_count,
        observed.authentication_key_id,
    )
    if prior_binding != observed_binding:
        _fail("publishable_run_authority_binding_divergent")


def _provider_state_root(config: PublishableRunConfig) -> Path:
    parent = config.publication_receipt_path.parent
    root = parent / ".provider"
    try:
        parent_value = parent.lstat()
        if (
            stat.S_ISLNK(parent_value.st_mode)
            or not stat.S_ISDIR(parent_value.st_mode)
            or parent_value.st_uid != os.geteuid()
            or stat.S_IMODE(parent_value.st_mode) != 0o700
        ):
            _fail("publishable_run_provider_state_parent_invalid")
        with suppress(FileExistsError):
            root.mkdir(mode=0o700)
        value = root.lstat()
        if (
            root.resolve(strict=True) != root
            or stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            _fail("publishable_run_provider_state_invalid")
    except PublishableRunError:
        raise
    except OSError:
        _fail("publishable_run_provider_state_invalid")
    return root


def _open_mode(config: PublishableRunConfig) -> PublishableProductionOpenMode:
    state_paths = (*config.scheduler_database_paths, config.suite_seal_database_path)
    existing = tuple(path.exists() for path in state_paths)
    if not any(existing):
        if config.publication_receipt_path.exists():
            _fail("publishable_run_state_generation_partial")
        return PublishableProductionOpenMode.CREATE
    if all(existing):
        return PublishableProductionOpenMode.RESUME
    _fail("publishable_run_state_generation_partial")


def _authenticate_existing_receipt(
    *,
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
) -> PublishableRunAttestation | None:
    path = config.publication_receipt_path
    if not path.exists():
        return None
    try:
        payload = read_private_json(path, maximum_bytes=PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT)
        receipt = PublishableRunAttestation.from_payload(payload)
    except Exception:
        _fail("publishable_run_receipt_authentication_invalid")
    if not verify_publishable_run_attestation(
        receipt,
        authentication_secret=secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=config.publication_key_id,
    ):
        _fail("publishable_run_receipt_authentication_invalid")
    return receipt


def _persist_exact_receipt(
    receipt: PublishableRunAttestation,
    *,
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
) -> PublishableRunAttestation:
    path = config.publication_receipt_path
    payload = receipt.payload()
    if path.exists():
        prior_payload = read_private_json(path, maximum_bytes=PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT)
        prior = PublishableRunAttestation.from_payload(prior_payload)
        if not verify_publishable_run_attestation(
            prior,
            authentication_secret=secrets.publication_receipt_authentication_key,
            expected_authentication_key_id=config.publication_key_id,
        ):
            _fail("publishable_run_receipt_authentication_invalid")
        if prior.terminal_disposition in _IMMUTABLE_TERMINAL_DISPOSITIONS:
            if prior != receipt or prior_payload != payload:
                _fail("publishable_run_terminal_receipt_divergent")
            return prior
        write_private_json_replace(
            path,
            payload,
            maximum_bytes=PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT,
        )
    else:
        write_private_json_once(
            path,
            payload,
            maximum_bytes=PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT,
        )
    readback_payload = read_private_json(path, maximum_bytes=PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT)
    readback = PublishableRunAttestation.from_payload(readback_payload)
    if (
        readback != receipt
        or readback_payload != payload
        or not verify_publishable_run_attestation(
            readback,
            authentication_secret=secrets.publication_receipt_authentication_key,
            expected_authentication_key_id=config.publication_key_id,
        )
    ):
        _fail("publishable_run_receipt_readback_invalid")
    return readback


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "PUBLISHABLE_RUN_RECEIPT_BYTES_LIMIT",
    "PublishableProductionCompositionOpener",
    "PublishableRunOrchestrator",
)
