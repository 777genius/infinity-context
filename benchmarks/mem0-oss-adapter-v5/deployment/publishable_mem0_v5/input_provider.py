"""Production dependency factory for publishable input preparation."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    compose_managed_mem0_v5_extraction_capabilities,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
)
from infinity_context_server.memory_comparison_managed_v5_live_cli_config_loader import (
    load_managed_v5_live_cli_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    validate_managed_v5_live_public_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_public_composition import (
    compose_managed_v5_live_public_inputs,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_prepared_authority import (
    StrictV4PreparedRunAuthority,
    open_strict_v4_prepared_run_authority,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as extraction_run,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as extraction_suite,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunProviderInputs,
)
from infinity_context_server.publishable_input_preparation import (
    OpenedPublishableInputPreparationSession,
    PublishableExtractionTerminalFileStore,
    PublishableInputPreparationError,
    PublishableInputPreparationProviderInputs,
    PublishableStrictV4RecoveryCapabilities,
)

from .input_provider_config import (
    PublishableInputPreparationProviderConfig,
    PublishableInputPreparationProviderSecrets,
    PublishableInputPreparationRunConfig,
    PublishableInputPreparationRunSecrets,
    parse_publishable_input_preparation_inputs,
)
from .run_provider import (
    OfficialCaseProjection,
    PublishableProductionOpenMode,
    build_publishable_suite_from_prepared_receipts,
)
from .run_provider_config import (
    OfficialDatasetConfig,
    RunProviderConfig,
    RunProviderSecrets,
    parse_run_provider_inputs,
)
from .run_provider_preflight import (
    PublishableRunRuntimeValidation,
    preflight_run_provider,
    verify_publishable_run_runtime_authority,
)

PUBLISHABLE_MEM0_INFINITY_INPUT_PROVIDER_NAME = "mem0-infinity-production-v1"
PublishableFullExtractionRunConfiguration = extraction_run.PublishableFullExtractionRunConfiguration
PublishableFullExtractionSuiteConfiguration = (
    extraction_suite.PublishableFullExtractionSuiteConfiguration
)

_PROCESS_LOCK = "publishable-input-preparation.lock"
_EXTRACTION_STATE_DIRECTORIES = ("locomo-extraction", "longmemeval-extraction")


@final
class Mem0InfinityPublishableInputPreparationDependencyFactory:
    """Open exact authenticated producer dependencies without provider dispatch."""

    __slots__ = ()

    async def open_session(
        self, *, inputs: PublishableInputPreparationProviderInputs
    ) -> OpenedPublishableInputPreparationSession:
        provider_config, provider_secrets = parse_publishable_input_preparation_inputs(inputs)
        run_inputs = PublishableRunProviderInputs(
            state_root=inputs.state_root,
            adapter_config_json=inputs.run_adapter_config_json,
            adapter_secrets_json=inputs.run_adapter_secrets_json,
        )
        run_config, run_secrets = parse_run_provider_inputs(run_inputs)
        _validate_provider_cross_wiring(
            inputs=inputs,
            provider_config=provider_config,
            provider_secrets=provider_secrets,
            run_config=run_config,
            run_secrets=run_secrets,
        )
        opened: list[StrictV4PreparedRunAuthority] = []
        infinity: InfinityContextHttpComparisonBackend | None = None
        try:
            strict_runs = []
            for source, run in zip(
                (run_config.locomo_dataset, run_config.longmemeval_dataset),
                (provider_config.locomo, provider_config.longmemeval),
                strict=True,
            ):
                authority = await _open_strict_run(source=source, config=run)
                opened.append(authority)
                strict_runs.append(authority)
            strict_pair = (strict_runs[0], strict_runs[1])
            official = OfficialCaseProjection.load(run_config)
            _validate_official_case_bridge(
                strict_pair=strict_pair,
                official=official,
                run_config=run_config,
            )
            readiness = preflight_run_provider(
                config=run_config,
                secrets=run_secrets,
                mode=PublishableProductionOpenMode(provider_config.fleet_mode),
            )
            suite = build_publishable_suite_from_prepared_receipts(
                config=run_config,
                projection=official,
                receipts=(strict_pair[0].receipt, strict_pair[1].receipt),
                readiness=readiness,
            )
            _validate_backend_target_bridge(strict_pair=strict_pair, suite=suite)
            extraction = PublishableFullExtractionSuiteConfiguration(
                locomo=_compose_extraction_run(
                    strict=strict_pair[0],
                    provider_config=provider_config.locomo,
                    provider_secrets=provider_secrets.locomo,
                    run_config=run_config,
                    run_secrets=run_secrets,
                    run_id=run_config.suite.locomo_run_id,
                    state_directory=inputs.state_root / _EXTRACTION_STATE_DIRECTORIES[0],
                    scheduler_runtime_sha256=suite.bridge_boot.runtime_authority_sha256,
                    request_timeout_seconds=provider_config.request_timeout_seconds,
                ),
                longmemeval=_compose_extraction_run(
                    strict=strict_pair[1],
                    provider_config=provider_config.longmemeval,
                    provider_secrets=provider_secrets.longmemeval,
                    run_config=run_config,
                    run_secrets=run_secrets,
                    run_id=run_config.suite.longmemeval_run_id,
                    state_directory=inputs.state_root / _EXTRACTION_STATE_DIRECTORIES[1],
                    scheduler_runtime_sha256=suite.bridge_boot.runtime_authority_sha256,
                    request_timeout_seconds=provider_config.request_timeout_seconds,
                ),
            )
            terminal_store = PublishableExtractionTerminalFileStore(
                paths=run_config.extraction_terminal_paths,
                authentication_keys=run_secrets.extraction_authentication_keys,
            )
            infinity = InfinityContextHttpComparisonBackend(
                base_url=run_config.suite.infinity_base_url,
                auth_token=provider_secrets.infinity_auth_token,
                timeout_seconds=provider_config.request_timeout_seconds,
                retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
                mirror_memories_as_documents=False,
            )
            return OpenedPublishableInputPreparationSession(
                suite=suite,
                official_case_projection=official,
                strict_v4_recovery=tuple(
                    PublishableStrictV4RecoveryCapabilities(
                        receipt_store=item.receipt_store,
                        registration_port=item.registration_port,
                    )
                    for item in strict_pair
                ),
                extraction_configuration=extraction,
                extraction_terminal_store=terminal_store,
                process_lock_path=inputs.state_root / _PROCESS_LOCK,
                retrieval_database_path=run_config.retrieval_database_path,
                retrieval_authentication_key=run_secrets.retrieval_authentication_key,
                expected_retrieval_authority_root_sha256=(
                    run_config.retrieval_authority_root_sha256
                ),
                infinity_backend=infinity,
                close_callbacks=(infinity.close, strict_pair[1].close, strict_pair[0].close),
            )
        except BaseException:
            if infinity is not None:
                with suppress(BaseException):
                    infinity.close()
            for authority in reversed(opened):
                with suppress(BaseException):
                    authority.close()
            raise


async def _open_strict_run(
    *,
    source: OfficialDatasetConfig,
    config: PublishableInputPreparationRunConfig,
) -> StrictV4PreparedRunAuthority:
    return await open_strict_v4_prepared_run_authority(
        request_path=config.strict_request_path,
        dataset_path=source.path,
        receipt_path=config.strict_receipt_path,
        keyring_path=config.strict_keyring_path,
        receipt_key_path=config.strict_receipt_key_path,
        registration_postgres_dsn_path=config.strict_registration_postgres_dsn_path,
    )


def _compose_extraction_run(
    *,
    strict: StrictV4PreparedRunAuthority,
    provider_config: PublishableInputPreparationRunConfig,
    provider_secrets: PublishableInputPreparationRunSecrets,
    run_config: RunProviderConfig,
    run_secrets: RunProviderSecrets,
    run_id: str,
    state_directory: Path,
    scheduler_runtime_sha256: str,
    request_timeout_seconds: float,
) -> PublishableFullExtractionRunConfiguration:
    live_config, contract_path, contract_sha256 = load_managed_v5_live_cli_config(
        provider_config.managed_v5_live_config_path
    )
    runtime_authority = validate_managed_v5_live_public_config(live_config)
    profile = resolve_full_comparison_profile(strict.receipt.profile_id)
    if profile is None:
        _fail("publishable_input_provider_profile_invalid")
    public = compose_managed_v5_live_public_inputs(
        projection=strict.projection,
        profile=profile,
        deadline=datetime.fromtimestamp(
            run_config.suite.dispatch_deadline_unix_ms / 1000,
            UTC,
        ),
        current_date=strict.manifest.current_date,
        extraction_contract_binding=ManagedMem0V5ExtractionContractBinding(
            contract_path,
            contract_sha256,
        ),
        operator_extraction_token_ceiling=(provider_config.operator_extraction_token_ceiling),
        operator_total_token_ceiling=provider_config.operator_total_token_ceiling,
        runtime_authority=runtime_authority,
        config=live_config,
        timeout_seconds=request_timeout_seconds,
    )
    runtime = verify_publishable_run_runtime_authority(
        config=run_config,
        secrets=run_secrets,
        run_id=run_id,
    )
    _validate_live_runtime_bridge(
        strict=strict,
        public=public,
        runtime=runtime,
        runtime_authority=runtime_authority,
        run_config=run_config,
        run_id=run_id,
    )
    live_inputs = public.inputs
    capabilities = compose_managed_mem0_v5_extraction_capabilities(
        cases=live_inputs.cases,
        current_date=live_inputs.current_date,
        request=live_inputs.request,
        origin=live_inputs.mem0_origin,
        timeout_seconds=live_inputs.timeout_seconds,
        state_paths=live_inputs.state_paths,
        credential_paths=live_inputs.credential_paths,
        runtime_receipt_boundary=live_inputs.runtime_receipt_boundary,
        trusted_runtime_binding=live_inputs.trusted_runtime_binding,
        receipt_authority=live_inputs.receipt_authority,
        transport=live_inputs.mem0_transport,
    )
    if capabilities.admission != public.admission:
        _fail("publishable_input_provider_admission_cross_wire")
    return PublishableFullExtractionRunConfiguration(
        preparation_receipt=strict.receipt,
        preparation_authenticator=strict.authenticator,
        preparation_key_authority=strict.key_identity_authority,
        manifest_authority=public.manifest_authority,
        admission=capabilities.admission,
        runtime_receipt_authority=live_inputs.receipt_authority,
        runtime_receipt_verifier=capabilities.runtime_receipt_verifier,
        http_lane=capabilities.http_lane,
        expected_runtime=runtime.expected_authority,
        runtime_attestation=runtime.validation,
        runtime_target_identity_sha256=runtime.target_identity_sha256,
        scheduler_bridge_runtime_authority_sha256=scheduler_runtime_sha256,
        state_directory=state_directory,
        journal_hmac_key=provider_secrets.journal_hmac_key,
        operation_receipt_hmac_key=provider_secrets.operation_receipt_hmac_key,
        ledger_hmac_key=provider_secrets.ledger_hmac_key,
    )


def _validate_official_case_bridge(
    *,
    strict_pair: tuple[StrictV4PreparedRunAuthority, StrictV4PreparedRunAuthority],
    official: OfficialCaseProjection,
    run_config: RunProviderConfig,
) -> None:
    expected = (
        (LOCOMO_PROFILE, run_config.suite.locomo_run_id, run_config.locomo_dataset.sha256),
        (
            LONGMEMEVAL_PROFILE,
            run_config.suite.longmemeval_run_id,
            run_config.longmemeval_dataset.sha256,
        ),
    )
    for index, (strict, values) in enumerate(zip(strict_pair, expected, strict=True)):
        profile, run_id, dataset_sha256 = values
        bindings = strict.projection.bindings
        aliases = tuple(item.case_id for item in strict.projection.cases)
        official_aliases = tuple(item.case_alias for item in official.identities[index])
        if (
            strict.receipt.profile_id != profile.profile_id
            or bindings.profile_id != profile.profile_id
            or len(strict.projection.cases) != profile.case_count
            or strict.manifest.case_count != profile.case_count
            or strict.receipt.dataset_sha256 != dataset_sha256
            or bindings.dataset_sha256 != dataset_sha256
            or bindings.run_id != run_id
            or strict.receipt.run_id_sha256 != hashlib.sha256(run_id.encode()).hexdigest()
            or aliases != official_aliases
        ):
            _fail("publishable_input_provider_official_case_cross_wire")


def _validate_backend_target_bridge(*, strict_pair, suite) -> None:
    expected = tuple(
        (item.backend_role, item.target_identity_sha256)
        for item in suite.ordered_backend_identities
    )
    for strict in strict_pair:
        observed = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in strict.projection.bindings.backend_targets
        )
        if observed != expected:
            _fail("publishable_input_provider_backend_cross_wire")


def _validate_live_runtime_bridge(
    *,
    strict: StrictV4PreparedRunAuthority,
    public: object,
    runtime: PublishableRunRuntimeValidation,
    runtime_authority: object,
    run_config: RunProviderConfig,
    run_id: str,
) -> None:
    expected = runtime.expected_authority
    authority = run_config.runtime_authority
    try:
        if (
            public.manifest_authority != strict.manifest
            or public.admission.commitment_sha256 != strict.receipt.admission_commitment_sha256
            or public.inputs.request.run_id != run_id
            or public.inputs.mem0_origin != run_config.suite.mem0_base_url
            or runtime_authority.runtime_source_sha256 != authority.runtime_source_sha256
            or runtime_authority.route_binding_sha256 != authority.runtime_route_binding_sha256
            or runtime_authority.extraction_system_prompt_sha256
            != authority.extraction_system_prompt_sha256
            or runtime_authority.extraction_response_format_sha256
            != authority.extraction_response_format_sha256
            or runtime_authority.extraction_response_schema_sha256
            != authority.extraction_response_schema_sha256
            or expected.runtime_source_sha256 != runtime_authority.runtime_source_sha256
            or expected.runtime_route_binding_sha256 != runtime_authority.route_binding_sha256
            or expected.subscription_runtime_binding_commitment_sha256
            != authority.subscription_runtime_binding_commitment_sha256
            or expected.expected_account_binding_hmac_sha256
            != runtime_authority.account_binding_hmac_sha256
            or expected.expected_base_instructions_sha256
            != runtime_authority.base_instructions_sha256
            or expected.extraction_system_prompt_sha256
            != runtime_authority.extraction_system_prompt_sha256
            or expected.extraction_response_format_sha256
            != runtime_authority.extraction_response_format_sha256
            or expected.extraction_response_schema_sha256
            != runtime_authority.extraction_response_schema_sha256
            or expected.requested_output_tokens != runtime_authority.requested_output_tokens
        ):
            _fail("publishable_input_provider_runtime_cross_wire")
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_provider_runtime_cross_wire")


def _validate_provider_cross_wiring(
    *,
    inputs: PublishableInputPreparationProviderInputs,
    provider_config: PublishableInputPreparationProviderConfig,
    provider_secrets: PublishableInputPreparationProviderSecrets,
    run_config: RunProviderConfig,
    run_secrets: RunProviderSecrets,
) -> None:
    provider_paths = (*provider_config.locomo.paths, *provider_config.longmemeval.paths)
    distinct_paths = tuple(dict.fromkeys(provider_paths))
    provider_owned_paths = {
        *provider_paths,
        *(
            candidate
            for receipt in (
                provider_config.locomo.strict_receipt_path,
                provider_config.longmemeval.strict_receipt_path,
            )
            for candidate in _sqlite_footprint(receipt)
        ),
    }
    extraction_state_paths = tuple(
        path
        for directory in (
            inputs.state_root / _EXTRACTION_STATE_DIRECTORIES[0],
            inputs.state_root / _EXTRACTION_STATE_DIRECTORIES[1],
        )
        for path in extraction_run.publishable_full_extraction_state_paths(directory)
    )
    state_sqlite_paths = (
        run_config.official_case_authority_path,
        *run_config.scheduler_database_paths,
        run_config.suite_seal_database_path,
        run_config.retrieval_database_path,
        *extraction_state_paths,
    )
    reserved = {
        run_config.locomo_dataset.path,
        run_config.longmemeval_dataset.path,
        *run_config.extraction_terminal_paths,
        run_config.publication_receipt_path,
        inputs.state_root / _PROCESS_LOCK,
        *(inputs.state_root / item for item in _EXTRACTION_STATE_DIRECTORIES),
        *(candidate for path in state_sqlite_paths for candidate in _sqlite_footprint(path)),
    }
    if provider_owned_paths & reserved:
        _fail("publishable_input_provider_path_cross_wire")
    try:
        canonical = tuple(path.resolve(strict=True) for path in distinct_paths)
        metadata = tuple(path.lstat() for path in distinct_paths)
    except OSError:
        _fail("publishable_input_provider_path_invalid")
    try:
        reserved_identities = {
            (item.st_dev, item.st_ino)
            for path in reserved
            if os.path.lexists(path)
            for item in (path.lstat(),)
        }
    except OSError:
        _fail("publishable_input_provider_path_invalid")
    if (
        any(path != resolved for path, resolved in zip(distinct_paths, canonical, strict=True))
        or any(stat.S_ISLNK(item.st_mode) for item in metadata)
        or len({(item.st_dev, item.st_ino) for item in metadata}) != len(metadata)
        or reserved_identities & {(item.st_dev, item.st_ino) for item in metadata}
    ):
        _fail("publishable_input_provider_path_cross_wire")
    new_secrets = (
        *provider_secrets.locomo.keys,
        *provider_secrets.longmemeval.keys,
        provider_secrets.infinity_auth_token.encode("utf-8"),
    )
    old_secrets = (
        *run_secrets.extraction_authentication_keys,
        run_secrets.retrieval_authentication_key,
        run_secrets.bridge_journal_authentication_key,
        run_secrets.output_cipher_key,
        run_secrets.runtime_attestation_root_secret,
        *(item.attestation_secret for item in run_secrets.bridges),
        *(item.launcher_receipt_key for item in run_secrets.bridges),
        *(item.authorization_bearer.encode("utf-8") for item in run_secrets.bridges),
    )
    if len(set((*new_secrets, *old_secrets))) != len(new_secrets) + len(old_secrets):
        _fail("publishable_input_provider_secret_reuse")
    try:
        root = inputs.state_root.lstat()
        if root.st_uid != os.geteuid() or stat.S_IMODE(root.st_mode) != 0o700:
            raise OSError
    except OSError:
        _fail("publishable_input_provider_state_invalid")


def _sqlite_footprint(path: Path) -> tuple[Path, Path, Path, Path]:
    return tuple(Path(f"{path}{suffix}") for suffix in ("", "-journal", "-shm", "-wal"))


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "PUBLISHABLE_MEM0_INFINITY_INPUT_PROVIDER_NAME",
    "Mem0InfinityPublishableInputPreparationDependencyFactory",
    "parse_publishable_input_preparation_inputs",
)
