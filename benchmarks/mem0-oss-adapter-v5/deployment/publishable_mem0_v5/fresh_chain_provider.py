"""Production provider composition for the fixed fresh-chain 1+4 canary."""

from __future__ import annotations

import hashlib
import hmac
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    SubscriptionRuntimeBridgeAdapter,
)
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
)
from infinity_context_server.memory_comparison_http import InfinityContextHttpComparisonBackend
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    compose_managed_mem0_v5_extraction_capabilities,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_MAX_TOKENS,
    PinnedMem0V5ExtractionRequestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
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
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_CASE_ID,
    PUBLISHABLE_CANARY_CASE_INDEX,
    PUBLISHABLE_CANARY_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    PublishableRunProviderInputs,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP,
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
)
from infinity_context_server.publishable_fresh_chain_canary.infinity_retrieval import (
    open_sealed_fresh_chain_infinity_retrieval,
    prepare_sealed_fresh_chain_infinity_retrieval,
)
from infinity_context_server.publishable_fresh_chain_canary.layout import (
    fresh_chain_source_commitment,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    canonical_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_lifecycle import (
    OperatorLocalHmacFreshChainLifecycleJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.mem0_one_shot import (
    FreshChainMem0OneShotAdapter,
    FreshChainMem0RetrievalCleanup,
    OperatorLocalHmacMem0OneShotJournal,
)
from infinity_context_server.publishable_fresh_chain_canary.request_renderer import (
    FreshChainOfficialRequestRenderer,
)
from infinity_context_server.publishable_fresh_chain_canary.runtime import (
    FreshChainCanaryRuntimeSession,
)
from infinity_context_server.publishable_fresh_chain_canary.source_pack import (
    FreshChainWholeCorpusProjection,
    project_fresh_chain_whole_corpus,
)

from .bridge_dispatch import HttpxRelayBridgeTransport
from .fresh_chain_provider_config import (
    FreshChainProviderConfig,
    FreshChainProviderSecrets,
    parse_fresh_chain_provider_inputs,
)
from .run_provider import (
    PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
    OfficialCaseProjection,
    PublishableProductionOpenMode,
    _BridgeSecrets,
    _open_journal,
    _SingleOutputKeyResolver,
)
from .run_provider_preflight import preflight_run_provider

_BRIDGE_JOURNAL_FILE = "subscription-bridge-journal.sqlite3"
_LIFECYCLE_JOURNAL_FILE = "mem0-retrieval-cleanup.json"
_ONE_SHOT_JOURNAL_FILE = "mem0-one-shot.json"


def open_fresh_chain_session(
    *,
    inputs: PublishableRunProviderInputs,
    state_root: Path,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source_commitment_sha256: str,
    resume: bool,
) -> FreshChainCanaryRuntimeSession:
    """Open genuine provider seams without issuing an extraction/evaluation call."""

    _require_boundary(
        inputs=inputs,
        state_root=state_root,
        namespace_id=namespace_id,
        namespace_commitment_sha256=namespace_commitment_sha256,
        source_commitment_sha256=source_commitment_sha256,
        resume=resume,
    )
    config, secrets = parse_fresh_chain_provider_inputs(inputs)
    _require_source_binding(inputs, source_commitment_sha256)
    _require_token_policy(config)
    mode = PublishableProductionOpenMode.RESUME if resume else PublishableProductionOpenMode.CREATE
    infinity = None
    bridge_journal = None
    try:
        case = _official_case(config)
        source = project_fresh_chain_whole_corpus(case, current_date=config.current_date)
        readiness = preflight_run_provider(config=config.run, secrets=secrets.run, mode=mode)
        _prepare_infinity_if_missing(config=config, secrets=secrets, case=case)
        extraction = _compose_extraction(
            config=config,
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source=source,
        )
        infinity = open_sealed_fresh_chain_infinity_retrieval(
            database_path=config.infinity_retrieval_database_path,
            authentication_key=secrets.run.retrieval_authentication_key,
            retrieval_authority_root_sha256=None,
            case=case,
            case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
            expected_run_id=config.run.suite.locomo_run_id,
        )
        bridge_journal = _open_journal(
            state_root / _BRIDGE_JOURNAL_FILE,
            mode=mode,
            authentication_key=secrets.run.bridge_journal_authentication_key,
        )
        bridge = _bridge(config, secrets, readiness, bridge_journal)
        one_shot = _one_shot(
            state_root=state_root,
            secrets=secrets,
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source=source,
            extraction=extraction,
        )
        lifecycle = OperatorLocalHmacFreshChainLifecycleJournal(
            state_root / _LIFECYCLE_JOURNAL_FILE,
            authentication_key=_journal_key(secrets.one_shot_hmac_key, b"retrieval-lifecycle"),
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
            source_projection_commitment_sha256=source.projection_commitment_sha256,
        )
        retrieval = FreshChainMem0RetrievalCleanup(
            lane=extraction["capabilities"].http_lane,
            admission=extraction["capabilities"].admission,
            manifest=source.packed_manifest,
            unit=source.extraction_unit,
            operation_id_sha256=extraction["command"].operation_id_sha256,
            case_question=case.question,
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
            source_projection_commitment_sha256=source.projection_commitment_sha256,
            journal=lifecycle,
        )
        renderer = FreshChainOfficialRequestRenderer(
            case=case,
            extraction_request_body=extraction["request_body"],
            infinity_retrieval=infinity,
            mem0_memories=retrieval,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
        )
        return FreshChainCanaryRuntimeSession(
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
            source_projection_commitment_sha256=source.projection_commitment_sha256,
            extraction_boundary=one_shot,
            extraction_command=extraction["command"],
            extraction_receipt_verifier=extraction["capabilities"].runtime_receipt_verifier,
            extraction_absence=one_shot,
            bridge=bridge,
            renderer=renderer,
            retrieval=retrieval,
            cleanup=retrieval,
            extraction_token_ceiling=config.operator_extraction_token_ceiling,
            total_token_ceiling=config.operator_total_token_ceiling,
            close_callbacks=(infinity.close, bridge_journal.close),
        )
    except BaseException:
        if bridge_journal is not None:
            with suppress(BaseException):
                bridge_journal.close()
        if infinity is not None:
            with suppress(BaseException):
                infinity.close()
        raise


def _prepare_infinity_if_missing(
    *,
    config: FreshChainProviderConfig,
    secrets: FreshChainProviderSecrets,
    case: PublicBenchmarkCase,
) -> None:
    """Prepare only the sealed fixed-case Infinity lookup, never the 2,040-case suite."""

    path = config.infinity_retrieval_database_path
    if path.exists():
        return
    backend = InfinityContextHttpComparisonBackend(
        base_url=config.run.suite.infinity_base_url,
        auth_token=secrets.infinity_auth_token,
        timeout_seconds=config.request_timeout_seconds,
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        mirror_memories_as_documents=False,
    )
    try:
        result = backend.search(case, run_id=config.run.suite.locomo_run_id, top_k=10)
        prepare_sealed_fresh_chain_infinity_retrieval(
            database_path=path,
            authentication_key=secrets.run.retrieval_authentication_key,
            case=case,
            case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
            run_id=config.run.suite.locomo_run_id,
            infinity_target_identity_sha256=managed_backend_target_identity_sha256(
                backend_role="infinity-context",
                base_url=config.run.suite.infinity_base_url,
            ),
            mem0_target_identity_sha256=managed_backend_target_identity_sha256(
                backend_role="mem0",
                base_url=config.run.suite.mem0_base_url,
            ),
            infinity_memories=result.memories,
        )
    finally:
        backend.close()


def _official_case(config: FreshChainProviderConfig) -> PublicBenchmarkCase:
    projection = OfficialCaseProjection.load(config.run)
    matches = tuple(
        (case_index, identity, case)
        for case_index, (identity, case) in enumerate(
            zip(
                projection.identities[0],
                projection._by_benchmark["locomo"],
                strict=True,
            )
        )
        if identity.case_id == PUBLISHABLE_CANARY_CASE_ID
        and identity.case_alias == PUBLISHABLE_CANARY_CASE_ALIAS
        and case.case_id == PUBLISHABLE_CANARY_CASE_ID
    )
    if (
        config.run.locomo_dataset.sha256 != PUBLISHABLE_CANARY_DATASET_SHA256
        or projection.observed_dataset_sha256[0] != PUBLISHABLE_CANARY_DATASET_SHA256
        or len(matches) != 1
        or matches[0][0] != PUBLISHABLE_CANARY_CASE_INDEX
    ):
        _fail("fresh_chain_official_case_cross_wire")
    _, identity, case = matches[0]
    if (
        identity.case_id != PUBLISHABLE_CANARY_CASE_ID
        or identity.case_alias != PUBLISHABLE_CANARY_CASE_ALIAS
        or type(case) is not PublicBenchmarkCase
        or case.benchmark != "locomo"
        or case.case_id != PUBLISHABLE_CANARY_CASE_ID
    ):
        _fail("fresh_chain_official_case_cross_wire")
    return case


def _compose_extraction(
    *,
    config: FreshChainProviderConfig,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source: FreshChainWholeCorpusProjection,
) -> dict[str, object]:
    live_config, contract_path, contract_sha256 = load_managed_v5_live_cli_config(
        config.managed_v5_live_config_path
    )
    authority = validate_managed_v5_live_public_config(live_config)
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    if profile is None:
        _fail("fresh_chain_managed_profile_invalid")
    targets = tuple(
        FullComparisonBackendTarget(
            role,
            managed_backend_target_identity_sha256(backend_role=role, base_url=origin),
        )
        for role, origin in (
            ("infinity-context", config.run.suite.infinity_base_url),
            ("mem0", config.run.suite.mem0_base_url),
        )
    )
    bindings = create_full_comparison_run_bindings(
        run_id=namespace_id,
        run_nonce_commitment_sha256=namespace_commitment_sha256,
        runtime_probe_nonce_sha256=source.projection_commitment_sha256,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=config.run.locomo_dataset.sha256,
        selection_fingerprint_sha256=source.projection_commitment_sha256,
        backend_targets=targets,
        scope=FULL_COMPARISON_SCOPE_CANARY,
        mem0_expected_runtime_mode="oss",
    )
    projection = ManagedPublicRunProjection(
        cases=(source.managed_case,),
        bindings=bindings,
        case_manifest_sha256=source.projection_commitment_sha256,
        publishable_profile_commitment_sha256=(PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
    )
    public = compose_managed_v5_live_public_inputs(
        projection=projection,
        profile=profile,
        deadline=datetime.fromtimestamp(config.run.suite.dispatch_deadline_unix_ms / 1000, UTC),
        current_date=config.current_date,
        extraction_contract_binding=ManagedMem0V5ExtractionContractBinding(
            contract_path, contract_sha256
        ),
        operator_extraction_token_ceiling=config.operator_extraction_token_ceiling,
        operator_total_token_ceiling=config.operator_total_token_ceiling,
        runtime_authority=authority,
        config=live_config,
        timeout_seconds=config.request_timeout_seconds,
    )
    _require_runtime_cross_wire(config, authority, public, source, namespace_id)
    inputs = public.inputs
    capabilities = compose_managed_mem0_v5_extraction_capabilities(
        cases=inputs.cases,
        current_date=inputs.current_date,
        request=inputs.request,
        origin=inputs.mem0_origin,
        timeout_seconds=inputs.timeout_seconds,
        state_paths=inputs.state_paths,
        credential_paths=inputs.credential_paths,
        runtime_receipt_boundary=inputs.runtime_receipt_boundary,
        trusted_runtime_binding=inputs.trusted_runtime_binding,
        receipt_authority=inputs.receipt_authority,
        transport=inputs.mem0_transport,
    )
    if capabilities.admission != public.admission:
        _fail("fresh_chain_extraction_admission_cross_wire")
    operation = inputs.receipt_authority.operations[0]
    body = PinnedMem0V5ExtractionRequestProjector().render_request_body(
        source.extraction_unit, current_date=config.current_date
    )
    command = PublishableExtractionCommand(
        run_id=namespace_id,
        run_identity_commitment_sha256=canonical_sha256(
            {
                "admission_commitment_sha256": public.admission.commitment_sha256,
                "namespace_commitment_sha256": namespace_commitment_sha256,
                "namespace_id": namespace_id,
                "source_projection_commitment_sha256": source.projection_commitment_sha256,
            }
        ),
        logical_operation_id=canonical_sha256(
            {
                "namespace_commitment_sha256": namespace_commitment_sha256,
                "source_projection_commitment_sha256": source.projection_commitment_sha256,
                "stage": "mem0_extraction",
            }
        ),
        ordinal=0,
        admission_commitment_sha256=public.admission.commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        unit_identity_sha256=operation.unit_identity_sha256,
        unit_sha256=operation.unit_sha256,
        route_sha256=inputs.receipt_authority.route_binding_sha256,
        scope_sha256=operation.scope_sha256,
        request_body_sha256=operation.request_body_sha256,
    )
    if (
        hashlib.sha256(body).hexdigest() != source.extraction_request_body_sha256
        or command.request_body_sha256 != source.extraction_request_body_sha256
        or command.run_id != public.admission.request.run_id
    ):
        _fail("fresh_chain_extraction_command_cross_wire")
    return {
        "capabilities": capabilities,
        "command": command,
        "public": public,
        "request_body": body,
    }


def _one_shot(
    *,
    state_root: Path,
    secrets: FreshChainProviderSecrets,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source: FreshChainWholeCorpusProjection,
    extraction: dict[str, object],
) -> FreshChainMem0OneShotAdapter:
    capabilities = extraction["capabilities"]
    public = extraction["public"]
    command = extraction["command"]
    return FreshChainMem0OneShotAdapter(
        authority=source.packed_manifest,
        admission=capabilities.admission,
        unit=source.extraction_unit,
        command=command,
        lane=capabilities.http_lane,
        expected_runtime_binding_sha256=public.inputs.trusted_runtime_binding.commitment_sha256,
        journal=OperatorLocalHmacMem0OneShotJournal(
            state_root / _ONE_SHOT_JOURNAL_FILE,
            authentication_key=_journal_key(secrets.one_shot_hmac_key, b"extraction-one-shot"),
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
        ),
    )


def _bridge(config, secrets, readiness, journal) -> SubscriptionRuntimeBridgeAdapter:
    keys = _BridgeSecrets(secrets.run)
    return SubscriptionRuntimeBridgeAdapter(
        pool=scheduler_subscription_bridge_adapter.verify_fleet_launch_receipts(readiness, keys),
        secrets=keys,
        transport=HttpxRelayBridgeTransport(
            relay_origin=config.run.suite.mem0_base_url,
            maximum_request_bytes=config.run.maximum_bridge_request_bytes,
            connect_timeout_seconds=config.run.bridge_connect_timeout_seconds,
            read_timeout_seconds=config.run.bridge_read_timeout_seconds,
            write_timeout_seconds=config.run.bridge_write_timeout_seconds,
        ),
        journal=journal,
        output_cipher=Aes256GcmOutputCipher(
            key_resolver=_SingleOutputKeyResolver(
                key_id=config.run.output_cipher_key_id, key=secrets.run.output_cipher_key
            ),
            maximum_ciphertext_bytes=SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
        ),
        maximum_request_bytes=SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP,
        maximum_response_bytes=SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
    )


def _require_runtime_cross_wire(config, authority, public, source, namespace_id) -> None:
    run = config.run.runtime_authority
    inputs = public.inputs
    if (
        public.manifest_authority != source.packed_manifest
        or public.manifest_authority.operation_count != 1
        or inputs.request.run_id != namespace_id
        or inputs.mem0_origin != config.run.suite.mem0_base_url
        or authority.runtime_source_sha256 != run.runtime_source_sha256
        or authority.route_binding_sha256 != run.runtime_route_binding_sha256
        or authority.extraction_system_prompt_sha256 != run.extraction_system_prompt_sha256
        or authority.extraction_response_format_sha256 != run.extraction_response_format_sha256
        or authority.extraction_response_schema_sha256 != run.extraction_response_schema_sha256
        or inputs.trusted_runtime_binding.commitment_sha256
        != run.subscription_runtime_binding_commitment_sha256
    ):
        _fail("fresh_chain_runtime_cross_wire")


def _require_boundary(**values: object) -> None:
    inputs = values["inputs"]
    if (
        type(inputs) is not PublishableRunProviderInputs
        or values["state_root"] != inputs.state_root
        or type(values["resume"]) is not bool
        or not _identifier(values["namespace_id"])
        or not _sha(values["namespace_commitment_sha256"])
        or not _sha(values["source_commitment_sha256"])
    ):
        _fail("fresh_chain_provider_boundary_invalid")
    inputs.__post_init__()


def _journal_key(root: bytes, purpose: bytes) -> bytes:
    if type(root) is not bytes or len(root) != 32 or type(purpose) is not bytes or not purpose:
        _fail("fresh_chain_journal_key_invalid")
    return hmac.new(root, b"fresh-chain-canary/journal/v1\0" + purpose, hashlib.sha256).digest()


def _require_source_binding(inputs, expected: str) -> None:
    if (
        fresh_chain_source_commitment(
            adapter_config_json=inputs.adapter_config_json,
            dependency_provider=PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
        )
        != expected
    ):
        _fail("fresh_chain_provider_source_cross_wire")


def _require_token_policy(config: FreshChainProviderConfig) -> None:
    if (
        MEM0_V5_EXTRACTION_MAX_TOKENS != 4096
        or SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS != 4096
        or not 4096 <= config.operator_extraction_token_ceiling <= 10_000_000
        or not config.operator_extraction_token_ceiling
        + 4 * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
        <= config.operator_total_token_ceiling
        <= 50_000_000
        or config.run.maximum_bridge_request_bytes < SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP
        or config.run.maximum_ciphertext_bytes < SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP
    ):
        _fail("fresh_chain_provider_token_or_size_policy_invalid")


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = ("open_fresh_chain_session",)
