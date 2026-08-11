"""Installed outer lifecycle for the authenticated one-case activation canary."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_publishable_canary_methodology import (
    PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
)

from .publishable_canary_activation_evidence import (
    CanaryActivationEvidenceBindings,
    PublishableCanaryActivationEvidence,
    build_complete_canary_activation_evidence,
    build_prepared_canary_activation_evidence,
    read_publishable_canary_activation_evidence,
    write_publishable_canary_activation_evidence,
)
from .publishable_canary_authority import (
    PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
    validate_publishable_canary_static_authority,
)
from .publishable_canary_composition import (
    PublishableCanaryComposition,
    PublishableCanaryMeasurement,
    open_publishable_canary_composition,
)
from .publishable_production_composition import (
    PublishableProductionOpenMode,
)
from .publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunDependencyFactoryPort,
    PublishableRunError,
    PublishableRunProviderInputs,
    PublishableRunRuntimeCapabilities,
    PublishableRunSecrets,
)
from .publishable_run_official_cases import (
    PreparedPublishableOfficialCases,
    prepare_publishable_official_cases,
)
from .publishable_run_orchestrator import (
    _require_cross_layer_secret_distinctness,
)

PUBLISHABLE_CANARY_STATE_DIRECTORY = "one-case-canary-v1"
PUBLISHABLE_CANARY_EVIDENCE_FILE = "activation-evidence.json"
_KEY_DERIVATION_DOMAIN = b"infinity-context/publishable-one-case-canary/key/v1\0"

PublishableCanaryCompositionOpener = Callable[..., PublishableCanaryComposition]


@final
@dataclass(frozen=True, slots=True, repr=False)
class _CanaryLayout:
    root: Path = field(repr=False)
    provider_root: Path = field(repr=False)
    config: PublishableRunConfig = field(repr=False)
    secrets: PublishableRunSecrets = field(repr=False)
    mode: PublishableProductionOpenMode


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableCanaryOrchestrator:
    """Bind production dependencies to a fixed, non-publishable four-call scope."""

    dependency_factory: PublishableRunDependencyFactoryPort = field(repr=False)
    composition_opener: PublishableCanaryCompositionOpener = field(
        default=open_publishable_canary_composition,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not callable(getattr(self.dependency_factory, "open_session", None)) or not callable(
            self.composition_opener
        ):
            _fail("publishable_canary_orchestrator_invalid")

    def run(
        self,
        *,
        config: PublishableRunConfig,
        secrets: PublishableRunSecrets,
    ) -> PublishableCanaryActivationEvidence:
        if type(config) is not PublishableRunConfig or type(secrets) is not PublishableRunSecrets:
            _fail("publishable_canary_orchestrator_inputs_invalid")
        validate_publishable_canary_static_authority()
        _require_cross_layer_secret_distinctness(secrets)
        if not config.official_case_authority_path.exists():
            _fail("publishable_canary_official_case_authority_missing")
        layout = _open_layout(config, secrets)
        _require_cross_layer_secret_distinctness(layout.secrets)
        prior = _read_prior(layout)
        session = self.dependency_factory.open_session(
            inputs=PublishableRunProviderInputs(
                state_root=layout.provider_root,
                adapter_config_json=layout.config.adapter_config_json,
                adapter_secrets_json=layout.secrets.adapter_secrets_json,
            ),
            mode=layout.mode,
        )
        prepared: PreparedPublishableOfficialCases | None = None
        try:
            if not callable(getattr(session, "open_runtime", None)) or not callable(
                getattr(session, "close", None)
            ):
                _fail("publishable_canary_session_invalid")
            suite = session.suite
            prepared = prepare_publishable_official_cases(
                suite=suite,
                projection=session.official_case_projection,
                config=layout.config,
                secrets=layout.secrets,
            )
            runtime = session.open_runtime(
                case_authority_root_sha256=prepared.terminal.authority_root_sha256,
            )
            if type(runtime) is not PublishableRunRuntimeCapabilities:
                _fail("publishable_canary_runtime_capabilities_invalid")
            composition = self._open_composition(
                mode=layout.mode,
                prepared=prepared,
                runtime=runtime,
                suite=suite,
            )
            bindings = _activation_bindings(
                prepared=prepared,
                runtime=runtime,
                composition=composition,
            )
            checkpoint = build_prepared_canary_activation_evidence(
                bindings=bindings,
                ordered_logical_call_ids=composition.ordered_logical_call_ids,
                authentication_key_id=layout.config.publication_key_id,
                authentication_secret=layout.secrets.publication_receipt_authentication_key,
            )
            measurement = composition.measure()
            if prior is None:
                if measurement != PublishableCanaryMeasurement(0, 0, 0, (), None):
                    _fail("publishable_canary_authority_checkpoint_missing")
                write_publishable_canary_activation_evidence(
                    layout.config.publication_receipt_path,
                    checkpoint,
                    authentication_secret=(layout.secrets.publication_receipt_authentication_key),
                    expected_authentication_key_id=layout.config.publication_key_id,
                )
            else:
                _require_prior_binding(prior, checkpoint)
                _require_prior_measurement(prior, measurement)
            while not measurement.complete:
                measurement = composition.advance_one()
            evidence = _complete_evidence(
                layout=layout,
                bindings=bindings,
                composition=composition,
                measurement=measurement,
            )
            return write_publishable_canary_activation_evidence(
                layout.config.publication_receipt_path,
                evidence,
                authentication_secret=layout.secrets.publication_receipt_authentication_key,
                expected_authentication_key_id=layout.config.publication_key_id,
            )
        finally:
            try:
                if prepared is not None:
                    prepared.close()
            finally:
                close = getattr(session, "close", None)
                if callable(close):
                    close()

    def _open_composition(self, *, mode, prepared, runtime, suite):
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


def _activation_bindings(
    *,
    prepared: PreparedPublishableOfficialCases,
    runtime: PublishableRunRuntimeCapabilities,
    composition: PublishableCanaryComposition,
) -> CanaryActivationEvidenceBindings:
    authority = composition.authority
    return CanaryActivationEvidenceBindings(
        canary_authority_sha256=authority.commitment_sha256,
        canary_profile_sha256=PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256,
        canary_methodology_sha256=PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
        target_publishable_profile_sha256=(PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
        target_publishable_methodology_sha256=(
            PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        ),
        suite_authority_sha256=authority.suite_authority_sha256,
        run_authority_sha256=authority.run_authority_sha256,
        selected_case_authority_sha256=authority.selected_case_authority_sha256,
        official_case_authority_root_sha256=(prepared.terminal.authority_root_sha256),
        retrieval_authority_root_sha256=runtime.retrieval_authority.authority_root_sha256,
        input_authority_sha256=prepared.terminal.terminal_commitment_sha256,
        extraction_suite_readback_sha256=(
            runtime.extraction_suite.suite_readback_commitment_sha256
        ),
        selected_extraction_authority_sha256=(composition.selected_extraction_terminal_sha256),
        runtime_provenance_sha256=composition.runtime_provenance.commitment_sha256,
        fleet_authority_sha256=(composition.runtime_provenance.bridge_fleet_readiness_sha256),
        canary_composition_authority_sha256=composition.authority_sha256,
        paired_path_authority_sha256=composition.paired_path_authority_sha256,
    )


def _complete_evidence(
    *,
    layout: _CanaryLayout,
    bindings: CanaryActivationEvidenceBindings,
    composition: PublishableCanaryComposition,
    measurement: PublishableCanaryMeasurement,
) -> PublishableCanaryActivationEvidence:
    receipts = measurement.ordered_receipt_sha256
    paired = measurement.paired_path_evidence_sha256
    if len(receipts) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT or paired is None:
        _fail("publishable_canary_complete_measurement_invalid")
    return build_complete_canary_activation_evidence(
        bindings=bindings,
        ordered_logical_call_ids=composition.ordered_logical_call_ids,
        ordered_provider_receipt_sha256=(
            receipts[0],
            receipts[1],
            receipts[2],
            receipts[3],
        ),
        paired_outcome_evidence_sha256=paired,
        measured_provider_intent_count=measurement.provider_intent_count,
        measured_provider_result_count=measurement.provider_result_count,
        measured_provider_call_count=measurement.provider_intent_count,
        authentication_key_id=layout.config.publication_key_id,
        authentication_secret=layout.secrets.publication_receipt_authentication_key,
    )


def _require_prior_binding(
    prior: PublishableCanaryActivationEvidence,
    checkpoint: PublishableCanaryActivationEvidence,
) -> None:
    if (
        prior.bindings != checkpoint.bindings
        or prior.ordered_logical_call_ids != checkpoint.ordered_logical_call_ids
        or prior.call_scope_sha256 != checkpoint.call_scope_sha256
        or prior.expected_provider_call_count != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
        or prior.authentication_key_id != checkpoint.authentication_key_id
    ):
        _fail("publishable_canary_authority_binding_divergent")


def _require_prior_measurement(
    prior: PublishableCanaryActivationEvidence,
    measurement: PublishableCanaryMeasurement,
) -> None:
    if prior.provider_accounting_complete and (
        not measurement.complete
        or prior.measured_provider_intent_count != measurement.provider_intent_count
        or prior.measured_provider_result_count != measurement.provider_result_count
        or prior.measured_provider_call_count != measurement.provider_intent_count
        or prior.ordered_provider_receipt_sha256 != measurement.ordered_receipt_sha256
        or prior.paired_outcome_evidence_sha256 != measurement.paired_path_evidence_sha256
    ):
        _fail("publishable_canary_terminal_state_divergent")


def _read_prior(layout: _CanaryLayout) -> PublishableCanaryActivationEvidence | None:
    path = layout.config.publication_receipt_path
    if not path.exists():
        return None
    try:
        return read_publishable_canary_activation_evidence(
            path,
            authentication_secret=layout.secrets.publication_receipt_authentication_key,
            expected_authentication_key_id=layout.config.publication_key_id,
        )
    except Exception:
        _fail("publishable_canary_activation_evidence_invalid")


def _open_layout(config: PublishableRunConfig, secrets: PublishableRunSecrets) -> _CanaryLayout:
    root = config.publication_receipt_path.parent / PUBLISHABLE_CANARY_STATE_DIRECTORY
    _require_isolated_canary_root(root, config)
    paths = _layout_paths(root)
    derived_secrets = _canary_secrets(secrets)
    derived_config = PublishableRunConfig(
        dependency_provider=config.dependency_provider,
        official_case_authority_path=config.official_case_authority_path,
        scheduler_database_paths=(paths["locomo"], paths["longmemeval"]),
        suite_seal_database_path=paths["seal"],
        publication_receipt_path=paths["evidence"],
        publication_key_id=_canary_key_id(config.publication_key_id),
        max_dispatches_per_batch=PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
        adapter_config_json=config.adapter_config_json,
    )
    if not root.exists():
        _require_private_directory(config.publication_receipt_path.parent)
        try:
            root.mkdir(mode=0o700)
            paths["locomo"].parent.mkdir(mode=0o700)
            paths["longmemeval"].parent.mkdir(mode=0o700)
            paths["provider"].mkdir(mode=0o700)
        except OSError:
            _fail("publishable_canary_state_initialization_failed")
        mode = PublishableProductionOpenMode.CREATE
    else:
        for directory in (
            root,
            paths["locomo"].parent,
            paths["longmemeval"].parent,
            paths["provider"],
        ):
            _require_private_directory(directory)
        state = (paths["locomo"], paths["longmemeval"], paths["seal"])
        existing = tuple(path.exists() for path in state)
        if all(existing) and paths["evidence"].exists():
            mode = PublishableProductionOpenMode.RESUME
        else:
            _fail("publishable_canary_state_generation_partial")
    return _CanaryLayout(
        root=root,
        provider_root=paths["provider"],
        config=derived_config,
        secrets=derived_secrets,
        mode=mode,
    )


def _require_isolated_canary_root(root: Path, config: PublishableRunConfig) -> None:
    full_state_paths = (
        config.official_case_authority_path,
        *config.scheduler_database_paths,
        config.suite_seal_database_path,
        config.publication_receipt_path,
    )
    try:
        resolved_root = root.resolve(strict=False)
        resolved_full_state_paths = tuple(path.resolve(strict=False) for path in full_state_paths)
    except (OSError, RuntimeError):
        _fail("publishable_canary_state_path_invalid")
    if any(
        resolved_root == path
        or resolved_root.is_relative_to(path)
        or path.is_relative_to(resolved_root)
        for path in resolved_full_state_paths
    ):
        _fail("publishable_canary_state_path_overlap")


def _layout_paths(root: Path) -> dict[str, Path]:
    return {
        "locomo": root / "locomo" / "scheduler.sqlite3",
        "longmemeval": root / "longmemeval" / "scheduler.sqlite3",
        "seal": root / "suite-seal.sqlite3",
        "evidence": root / PUBLISHABLE_CANARY_EVIDENCE_FILE,
        "provider": root / "provider",
    }


def _canary_secrets(source: PublishableRunSecrets) -> PublishableRunSecrets:
    return PublishableRunSecrets(
        official_case_authentication_key=source.official_case_authentication_key,
        scheduler_authentication_keys=(
            _derive_key(source.scheduler_authentication_keys[0], b"scheduler/locomo"),
            _derive_key(source.scheduler_authentication_keys[1], b"scheduler/longmemeval"),
        ),
        suite_seal_authentication_key=_derive_key(
            source.suite_seal_authentication_key,
            b"suite-seal",
        ),
        publication_receipt_authentication_key=_derive_key(
            source.publication_receipt_authentication_key,
            b"activation-evidence",
        ),
        adapter_secrets_json=source.adapter_secrets_json,
    )


def _derive_key(source: bytes, label: bytes) -> bytes:
    if type(source) is not bytes or len(source) < 32 or type(label) is not bytes or not label:
        _fail("publishable_canary_key_derivation_invalid")
    return hmac.new(source, _KEY_DERIVATION_DOMAIN + label, hashlib.sha256).digest()


def _canary_key_id(source: str) -> str:
    return "canary-" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _require_private_directory(path: Path) -> None:
    try:
        value = path.lstat()
        valid = (
            path.resolve(strict=True) == path
            and stat.S_ISDIR(value.st_mode)
            and not stat.S_ISLNK(value.st_mode)
            and value.st_uid == os.geteuid()
            and stat.S_IMODE(value.st_mode) == 0o700
        )
    except OSError:
        valid = False
    if not valid:
        _fail("publishable_canary_state_directory_invalid")


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "PUBLISHABLE_CANARY_EVIDENCE_FILE",
    "PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT",
    "PUBLISHABLE_CANARY_STATE_DIRECTORY",
    "PublishableCanaryCompositionOpener",
    "PublishableCanaryOrchestrator",
)
