from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_DATASET_SHA256,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    PublishableRunProviderInputs,
)
from infinity_context_server.publishable_fresh_chain_canary import orchestrator
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
from infinity_context_server.publishable_fresh_chain_canary.source_pack import (
    project_fresh_chain_whole_corpus,
)
from publishable_mem0_v5 import fresh_chain_provider as subject

_SHA = "a" * 64


def test_provider_free_preparer_seals_only_the_fixed_infinity_case(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "one-case")
    path = root / "fresh-infinity.sqlite3"
    key = hashlib.sha256(b"one-case-retrieval-key").digest()
    case = _case()
    memories = (RetrievedMemory(text="Caroline planted basil.", rank=1, score=1.0),)
    authority = prepare_sealed_fresh_chain_infinity_retrieval(
        database_path=path,
        authentication_key=key,
        case=case,
        case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
        run_id="official-locomo-run",
        infinity_target_identity_sha256="1" * 64,
        mem0_target_identity_sha256="2" * 64,
        infinity_memories=memories,
    )
    replay = prepare_sealed_fresh_chain_infinity_retrieval(
        database_path=path,
        authentication_key=key,
        case=case,
        case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
        run_id="official-locomo-run",
        infinity_target_identity_sha256="1" * 64,
        mem0_target_identity_sha256="2" * 64,
        infinity_memories=memories,
    )
    opened = open_sealed_fresh_chain_infinity_retrieval(
        database_path=path,
        authentication_key=key,
        retrieval_authority_root_sha256=authority,
        case=case,
        case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
        expected_run_id="official-locomo-run",
    )
    try:
        assert replay == authority
        assert opened.retrieve() == memories
        assert opened.reader._terminal.group_count == 2
    finally:
        opened.close()


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True)
    os.chmod(path, 0o700)
    return path


def _memory(ordinal: int, *, speaker: str, role: str, text: str) -> BenchmarkMemoryInput:
    session = f"session_{ordinal}"
    date = f"{ordinal}:00 PM on {ordinal} May, 2023"
    dia_id = f"D{ordinal}:1"
    return BenchmarkMemoryInput(
        text=f"{session} date: {date}\n{dia_id} {speaker}: {text}",
        source_external_id=f"locomo:conv-26:{session}:{dia_id}:turn",
        metadata={
            "dia_id": dia_id,
            "official_mem0_content": f"{speaker}: {text}",
            "role": role,
            "session_date": date,
            "session_key": session,
            "speaker": speaker,
            "timestamp": 1_682_946_000 + ordinal,
        },
    )


def _case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:1",
        question="What herb was planted?",
        expected_terms=("basil",),
        forbidden_terms=("mint",),
        memories=(
            _memory(1, speaker="Caroline", role="user", text="I planted basil."),
            _memory(2, speaker="Melanie", role="assistant", text="Wonderful."),
        ),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={"locomo_ingest_mode": "official-turns", "sample_id": "conv-26"},
    )


def _run_config() -> SimpleNamespace:
    runtime = SimpleNamespace(
        runtime_source_sha256="1" * 64,
        runtime_route_binding_sha256="2" * 64,
        extraction_system_prompt_sha256="3" * 64,
        extraction_response_format_sha256="4" * 64,
        extraction_response_schema_sha256="5" * 64,
        subscription_runtime_binding_commitment_sha256="6" * 64,
    )
    suite = SimpleNamespace(
        infinity_base_url="http://127.0.0.1:8890",
        mem0_base_url="http://127.0.0.1:8765",
        locomo_run_id="official-locomo-run",
        dispatch_deadline_unix_ms=2_000_000_000_000,
    )
    return SimpleNamespace(
        locomo_dataset=SimpleNamespace(sha256=PUBLISHABLE_CANARY_DATASET_SHA256),
        runtime_authority=runtime,
        suite=suite,
        retrieval_database_path=Path("/private/retrieval.sqlite3"),
        retrieval_authority_root_sha256="7" * 64,
        maximum_bridge_request_bytes=4 * 1024 * 1024,
        maximum_ciphertext_bytes=1024 * 1024,
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        run=_run_config(),
        current_date="2026-08-12",
        managed_v5_live_config_path=Path("/private/live.json"),
        infinity_retrieval_database_path=Path("/private/fresh-infinity.sqlite3"),
        request_timeout_seconds=30.0,
        operator_extraction_token_ceiling=8_000,
        operator_total_token_ceiling=40_000,
    )


def _install_extraction_primitives(monkeypatch: pytest.MonkeyPatch):
    observed: list[SimpleNamespace] = []
    config = _config()
    runtime = config.run.runtime_authority
    authority = SimpleNamespace(
        runtime_source_sha256=runtime.runtime_source_sha256,
        route_binding_sha256=runtime.runtime_route_binding_sha256,
        extraction_system_prompt_sha256=runtime.extraction_system_prompt_sha256,
        extraction_response_format_sha256=runtime.extraction_response_format_sha256,
        extraction_response_schema_sha256=runtime.extraction_response_schema_sha256,
    )
    monkeypatch.setattr(
        subject,
        "load_managed_v5_live_cli_config",
        lambda _path: (object(), Path("/reviewed/extraction.py"), "8" * 64),
    )
    monkeypatch.setattr(subject, "validate_managed_v5_live_public_config", lambda _c: authority)
    monkeypatch.setattr(subject, "ManagedMem0V5ExtractionContractBinding", lambda *_a: object())

    def compose(**kwargs: object):
        projection = kwargs["projection"]
        namespace = projection.bindings.run_id
        source = project_fresh_chain_whole_corpus(_case(), current_date="2026-08-12")
        admission_sha = canonical_sha256(
            {
                "namespace": namespace,
                "namespace_nonce": projection.bindings.run_nonce_commitment_sha256,
                "source": projection.bindings.runtime_probe_nonce_sha256,
            }
        )
        admission = SimpleNamespace(
            commitment_sha256=admission_sha,
            request=SimpleNamespace(run_id=namespace),
        )
        operation = SimpleNamespace(
            operation_id_sha256=canonical_sha256(
                {"admission": admission_sha, "unit": source.extraction_unit.unit_identity_sha256}
            ),
            unit_identity_sha256=source.extraction_unit.unit_identity_sha256,
            unit_sha256=source.extraction_unit.unit_sha256,
            scope_sha256=source.extraction_unit.scope_sha256,
            request_body_sha256=source.extraction_request_body_sha256,
        )
        inputs = SimpleNamespace(
            cases=(source.managed_case,),
            current_date="2026-08-12",
            request=admission.request,
            mem0_origin=config.run.suite.mem0_base_url,
            timeout_seconds=30.0,
            state_paths=object(),
            credential_paths=object(),
            runtime_receipt_boundary=object(),
            trusted_runtime_binding=SimpleNamespace(
                commitment_sha256=runtime.subscription_runtime_binding_commitment_sha256
            ),
            receipt_authority=SimpleNamespace(
                operations=(operation,), route_binding_sha256=runtime.runtime_route_binding_sha256
            ),
            mem0_transport=None,
        )
        public = SimpleNamespace(
            inputs=inputs,
            admission=admission,
            manifest_authority=source.packed_manifest,
        )
        observed.append(SimpleNamespace(kwargs=kwargs, projection=projection, public=public))
        return public

    monkeypatch.setattr(subject, "compose_managed_v5_live_public_inputs", compose)

    def capabilities(**kwargs: object):
        return SimpleNamespace(
            admission=observed[-1].public.admission,
            http_lane=SimpleNamespace(name="genuine-lane-seam"),
            runtime_receipt_verifier=SimpleNamespace(name="genuine-verifier-seam"),
            kwargs=kwargs,
        )

    monkeypatch.setattr(subject, "compose_managed_mem0_v5_extraction_capabilities", capabilities)
    return config, observed


def test_extraction_composition_binds_fresh_namespace_and_full_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, observed = _install_extraction_primitives(monkeypatch)
    source = project_fresh_chain_whole_corpus(_case(), current_date=config.current_date)
    namespaces = ("fresh-chain-one", "fresh-chain-two")
    nonces = ("9" * 64, "b" * 64)

    results = tuple(
        subject._compose_extraction(
            config=config,
            namespace_id=namespace,
            namespace_commitment_sha256=nonce,
            source=source,
        )
        for namespace, nonce in zip(namespaces, nonces, strict=True)
    )

    for index, result in enumerate(results):
        projection = observed[index].projection
        command = result["command"]
        assert projection.bindings.run_id == namespaces[index]
        assert projection.bindings.run_nonce_commitment_sha256 == nonces[index]
        assert projection.bindings.runtime_probe_nonce_sha256 == source.projection_commitment_sha256
        assert (
            projection.bindings.selection_fingerprint_sha256 == source.projection_commitment_sha256
        )
        assert observed[index].public.admission.request.run_id == namespaces[index]
        assert command.run_id == namespaces[index]
        assert command.run_identity_commitment_sha256 == canonical_sha256(
            {
                "admission_commitment_sha256": observed[index].public.admission.commitment_sha256,
                "namespace_commitment_sha256": nonces[index],
                "namespace_id": namespaces[index],
                "source_projection_commitment_sha256": source.projection_commitment_sha256,
            }
        )
        assert command.admission_commitment_sha256 == (
            observed[index].public.admission.commitment_sha256
        )
        assert command.request_body_sha256 == source.extraction_request_body_sha256
        assert result["capabilities"].admission is observed[index].public.admission

    assert results[0]["command"].logical_operation_id != results[1]["command"].logical_operation_id
    assert results[0]["command"].run_identity_commitment_sha256 != (
        results[1]["command"].run_identity_commitment_sha256
    )
    assert results[0]["command"].admission_commitment_sha256 != (
        results[1]["command"].admission_commitment_sha256
    )
    assert results[0]["command"].operation_id_sha256 != results[1]["command"].operation_id_sha256


def test_one_shot_and_lifecycle_journal_keys_are_purpose_separated() -> None:
    root = hashlib.sha256(b"operator key").digest()

    extraction = subject._journal_key(root, b"extraction-one-shot")
    lifecycle = subject._journal_key(root, b"retrieval-lifecycle")

    assert extraction != lifecycle
    assert len(extraction) == len(lifecycle) == 32
    assert extraction == subject._journal_key(root, b"extraction-one-shot")


def _command(source, namespace: str) -> PublishableExtractionCommand:
    unit = source.extraction_unit
    return PublishableExtractionCommand(
        run_id=namespace,
        run_identity_commitment_sha256=source.projection_commitment_sha256,
        logical_operation_id="c" * 64,
        ordinal=0,
        admission_commitment_sha256="d" * 64,
        operation_id_sha256="e" * 64,
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256="f" * 64,
        scope_sha256=unit.scope_sha256,
        request_body_sha256=source.extraction_request_body_sha256,
    )


def test_provider_open_reuses_one_admission_for_extraction_retrieval_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = _private_directory(tmp_path / "provider")
    inputs = PublishableRunProviderInputs(
        state_root=state_root,
        adapter_config_json=json.dumps({"fresh": "config"}).encode(),
        adapter_secrets_json=json.dumps({"fresh": "secrets"}).encode(),
    )
    namespace = "fresh-chain-isolated"
    namespace_commitment = "9" * 64
    source_commitment = fresh_chain_source_commitment(
        adapter_config_json=inputs.adapter_config_json,
        dependency_provider=subject.PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
    )
    config = _config()
    config.run.bridge_journal_authentication_key = hashlib.sha256(b"bridge").digest()
    config.run.output_cipher_key = hashlib.sha256(b"output").digest()
    secrets = SimpleNamespace(
        run=SimpleNamespace(
            retrieval_authentication_key=hashlib.sha256(b"retrieval").digest(),
            bridge_journal_authentication_key=hashlib.sha256(b"bridge").digest(),
        ),
        one_shot_hmac_key=hashlib.sha256(b"one-shot").digest(),
    )
    source = project_fresh_chain_whole_corpus(_case(), current_date=config.current_date)
    admission = SimpleNamespace(commitment_sha256="d" * 64)
    lane = SimpleNamespace(name="one genuine lane")
    capabilities = SimpleNamespace(
        admission=admission,
        http_lane=lane,
        runtime_receipt_verifier=object(),
    )
    extraction = {
        "capabilities": capabilities,
        "command": _command(source, namespace),
        "public": SimpleNamespace(
            inputs=SimpleNamespace(trusted_runtime_binding=SimpleNamespace(commitment_sha256=_SHA))
        ),
        "request_body": b"extraction body",
    }
    observed: dict[str, object] = {}
    monkeypatch.setattr(subject, "parse_fresh_chain_provider_inputs", lambda _i: (config, secrets))
    monkeypatch.setattr(subject, "_official_case", lambda _c: _case())
    monkeypatch.setattr(subject, "project_fresh_chain_whole_corpus", lambda *_a, **_k: source)
    monkeypatch.setattr(subject, "_prepare_infinity_if_missing", lambda **_k: None)
    monkeypatch.setattr(subject, "_compose_extraction", lambda **_k: extraction)
    monkeypatch.setattr(subject, "preflight_run_provider", lambda **_k: object())
    infinity = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        subject, "open_sealed_fresh_chain_infinity_retrieval", lambda **_k: infinity
    )
    journal = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(subject, "_open_journal", lambda *_a, **_k: journal)
    monkeypatch.setattr(subject, "_bridge", lambda *_a, **_k: object())

    def one_shot(**kwargs: object):
        observed["one_shot"] = kwargs
        return object()

    def one_shot_journal(_path: Path, **kwargs: object):
        observed["one_shot_key"] = kwargs["authentication_key"]
        return object()

    def lifecycle_journal(_path: Path, **kwargs: object):
        observed["lifecycle_key"] = kwargs["authentication_key"]
        observed["lifecycle"] = kwargs
        return object()

    def retrieval(**kwargs: object):
        observed["retrieval"] = kwargs
        return object()

    monkeypatch.setattr(subject, "FreshChainMem0OneShotAdapter", one_shot)
    monkeypatch.setattr(subject, "OperatorLocalHmacMem0OneShotJournal", one_shot_journal)
    monkeypatch.setattr(subject, "OperatorLocalHmacFreshChainLifecycleJournal", lifecycle_journal)
    monkeypatch.setattr(subject, "FreshChainMem0RetrievalCleanup", retrieval)
    monkeypatch.setattr(subject, "FreshChainOfficialRequestRenderer", lambda **_k: object())
    monkeypatch.setattr(
        subject,
        "FreshChainCanaryRuntimeSession",
        lambda **kwargs: SimpleNamespace(arguments=kwargs),
    )

    session = subject.open_fresh_chain_session(
        inputs=inputs,
        state_root=state_root,
        namespace_id=namespace,
        namespace_commitment_sha256=namespace_commitment,
        source_commitment_sha256=source_commitment,
        resume=False,
    )

    one_shot_args = observed["one_shot"]
    retrieval_args = observed["retrieval"]
    assert one_shot_args["admission"] is admission
    assert one_shot_args["lane"] is lane
    assert retrieval_args["admission"] is admission
    assert retrieval_args["lane"] is lane
    assert retrieval_args["manifest"] == source.packed_manifest
    assert retrieval_args["unit"] == source.extraction_unit
    assert observed["lifecycle"]["source_projection_commitment_sha256"] == (
        source.projection_commitment_sha256
    )
    assert retrieval_args["source_projection_commitment_sha256"] == (
        source.projection_commitment_sha256
    )
    assert session.arguments["source_projection_commitment_sha256"] == (
        source.projection_commitment_sha256
    )
    assert session.arguments["extraction_boundary"] is session.arguments["extraction_absence"]
    assert session.arguments["retrieval"] is session.arguments["cleanup"]
    assert observed["one_shot_key"] != observed["lifecycle_key"]


def test_provider_rejects_outer_source_cross_wire_before_any_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = _private_directory(tmp_path / "provider")
    inputs = PublishableRunProviderInputs(
        state_root=state_root,
        adapter_config_json=b'{"config":true}',
        adapter_secrets_json=b'{"secrets":true}',
    )
    monkeypatch.setattr(
        subject,
        "parse_fresh_chain_provider_inputs",
        lambda _i: (_config(), SimpleNamespace()),
    )
    preflight: list[object] = []
    monkeypatch.setattr(
        subject,
        "preflight_run_provider",
        lambda **kwargs: preflight.append(kwargs),
    )

    with pytest.raises(PublishableRunError, match="fresh_chain_provider_source_cross_wire"):
        subject.open_fresh_chain_session(
            inputs=inputs,
            state_root=state_root,
            namespace_id="fresh-chain-isolated",
            namespace_commitment_sha256="9" * 64,
            source_commitment_sha256="0" * 64,
            resume=False,
        )

    assert preflight == []


def test_authenticated_pristine_ledger_allows_safe_provider_initialization_only(
    tmp_path: Path,
) -> None:
    provider_root = _private_directory(tmp_path / "provider-state")
    layout = SimpleNamespace(resume=True, provider_root=provider_root)
    pristine = SimpleNamespace(
        source_projection_commitment_sha256=None,
        event_count=0,
        intent_count=0,
        result_count=0,
        physical_attempt_count=0,
        retrieval_handoff=None,
        cleanup=None,
        terminal_outcome=None,
    )

    assert orchestrator._provider_state_requires_resume(layout, pristine) is False
    assert (
        orchestrator._provider_state_requires_resume(
            layout,
            SimpleNamespace(**{**vars(pristine), "intent_count": 1}),
        )
        is True
    )
    (provider_root / "durable-journal.sqlite3").touch(mode=0o600)
    assert orchestrator._provider_state_requires_resume(layout, pristine) is True
    assert (
        orchestrator._provider_state_requires_resume(
            layout,
            SimpleNamespace(**{**vars(pristine), "physical_attempt_count": 1}),
        )
        is True
    )
    assert (
        orchestrator._provider_state_requires_resume(
            layout,
            SimpleNamespace(**{**vars(pristine), "retrieval_handoff": object()}),
        )
        is True
    )
