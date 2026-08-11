from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionRunTerminal,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_run_orchestrator as orchestrator_module,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunError,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_orchestrator import (
    PublishableRunOrchestrator,
)
from publishable_mem0_v5 import run_provider as subject
from publishable_mem0_v5.run_provider_config import (
    OfficialDatasetConfig,
    RunProviderConfig,
    RunProviderSecrets,
    RunSuiteConfig,
    RuntimeAttestationConfig,
    RuntimeAuthorityConfig,
)
from publishable_mem0_v5.run_provider_extraction import (
    EXTRACTION_TERMINAL_SEAL_SCHEMA,
    extraction_terminal_seal_hmac,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _write_private_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)


def _alternate_locomo_payload() -> list[dict[str, object]]:
    return [
        {
            "conversation": {
                "session_1": [
                    {
                        "dia_id": "D1:1",
                        "speaker": "Alice",
                        "text": "This is alternate same-count LoCoMo material.",
                    }
                ],
                "speaker_a": "Alice",
            },
            "qa": [
                {
                    "answer": f"alternate-locomo-answer-{index}",
                    "category": 4,
                    "evidence": ["D1:1"],
                    "question": f"What is alternate LoCoMo value {index}?",
                }
                for index in range(LOCOMO_PROFILE.case_count)
            ],
            "sample_id": "alternate-locomo-authority",
        }
    ]


def _alternate_longmemeval_payload() -> list[dict[str, object]]:
    return [
        {
            "answer": f"alternate-longmemeval-answer-{index}",
            "answer_session_ids": [f"alternate-answer-session-{index}"],
            "haystack_dates": ["2026/08/11 (Tue) 12:00"],
            "haystack_session_ids": [f"alternate-answer-session-{index}"],
            "haystack_sessions": [
                [
                    {
                        "content": f"Alternate LongMemEval value {index} is recorded.",
                        "role": "user",
                    },
                    {
                        "content": "The alternate value was acknowledged.",
                        "role": "assistant",
                    },
                ]
            ],
            "question": f"What is alternate LongMemEval value {index}?",
            "question_date": "2026/08/11 (Tue) 13:00",
            "question_id": f"alternate-longmemeval-{index}",
            "question_type": "single-session-user",
        }
        for index in range(LONGMEMEVAL_PROFILE.case_count)
    ]


def _write_alternate_datasets(root: Path) -> tuple[OfficialDatasetConfig, OfficialDatasetConfig]:
    root.mkdir()
    locomo_path = root / "locomo.json"
    longmemeval_path = root / "longmemeval.json"
    locomo_bytes = canonical_json_bytes(_alternate_locomo_payload())
    longmemeval_bytes = canonical_json_bytes(_alternate_longmemeval_payload())
    locomo_path.write_bytes(locomo_bytes)
    longmemeval_path.write_bytes(longmemeval_bytes)
    locomo_path.chmod(0o600)
    longmemeval_path.chmod(0o600)
    return (
        OfficialDatasetConfig(
            path=locomo_path,
            sha256=hashlib.sha256(locomo_bytes).hexdigest(),
        ),
        OfficialDatasetConfig(
            path=longmemeval_path,
            sha256=hashlib.sha256(longmemeval_bytes).hexdigest(),
        ),
    )


def _profile_dataset_sha256() -> tuple[str, str]:
    profile = subject.public_publishable_comparison_profile(
        subject.publishable_priority_comparison_profile_v4()
    )
    return tuple(
        profile["benchmarks"][scheduler_profile.benchmark.value]["dataset_sha256"]
        for scheduler_profile in (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
    )


def _extraction_terminal(
    *,
    profile_id: str,
    run_id: str,
    dataset_sha256: str,
    runtime_binding_sha256: str,
    scheduler_runtime_sha256: str,
    index: int,
) -> PublishableExtractionRunTerminal:
    receipt_count = dict(PUBLISHABLE_EXTRACTION_BENCHMARKS)[profile_id]
    values = {
        "profile_id": profile_id,
        "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
        "binding_commitment_sha256": _sha(f"binding-{index}"),
        "methodology_commitment_sha256": (
            subject.PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        ),
        "admission_commitment_sha256": _sha(f"admission-{index}"),
        "ingestion_root_sha256": _sha(f"ingestion-{index}"),
        "a1_terminal_commitment_sha256": _sha(f"a1-terminal-{index}"),
        "a1_manifest_context_sha256": _sha(f"a1-manifest-{index}"),
        "runtime_binding_commitment_sha256": runtime_binding_sha256,
        "expected_receipt_count": receipt_count,
    }
    context_sha256 = canonical_sha256(
        {
            "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
            **values,
        }
    )
    page_count = (receipt_count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1) // (
        FULL_RUN_EXTRACTION_PAGE_SIZE
    )
    ledger_body = {
        "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
        "context_commitment_sha256": context_sha256,
        "receipt_count": receipt_count,
        "page_count": page_count,
        "receipt_pages_root_sha256": _sha(f"receipt-pages-{index}"),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    ledger = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context_sha256,
        receipt_count=receipt_count,
        page_count=page_count,
        receipt_pages_root_sha256=ledger_body["receipt_pages_root_sha256"],
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        terminal_commitment_sha256=canonical_sha256(ledger_body),
    )
    return PublishableExtractionRunTerminal(
        **values,
        scheduler_bridge_runtime_authority_sha256=scheduler_runtime_sha256,
        preparation_receipt_sha256=_sha(f"preparation-{index}"),
        dataset_sha256=dataset_sha256,
        a2_terminal_commitment_sha256=_sha(f"a2-terminal-{index}"),
        journal_manifest_commitment_sha256=_sha(f"journal-manifest-{index}"),
        journal_state_commitment_sha256=_sha(f"journal-state-{index}"),
        journal_head_event_sha256=_sha(f"journal-head-{index}"),
        ledger_terminal=ledger,
    )


def _write_extraction_terminal(
    path: Path,
    terminal: PublishableExtractionRunTerminal,
    *,
    authentication_key: bytes,
) -> None:
    terminal_payload = {
        **terminal.body(),
        "terminal_commitment_sha256": terminal.terminal_commitment_sha256,
    }
    _write_private_json(
        path,
        {
            "authentication_hmac_sha256": extraction_terminal_seal_hmac(
                terminal_payload,
                authentication_key=authentication_key,
            ),
            "schema_version": EXTRACTION_TERMINAL_SEAL_SCHEMA,
            "terminal": terminal_payload,
        },
    )


def _run_provider_config(
    tmp_path: Path,
    *,
    datasets: tuple[OfficialDatasetConfig, OfficialDatasetConfig],
    extraction_paths: tuple[Path, Path],
    runtime_binding_sha256: str,
) -> RunProviderConfig:
    return RunProviderConfig(
        locomo_dataset=datasets[0],
        longmemeval_dataset=datasets[1],
        suite=RunSuiteConfig(
            suite_id="alternate-dataset-authority-suite",
            locomo_run_id="alternate-authority-locomo-run",
            longmemeval_run_id="alternate-authority-longmemeval-run",
            publication_bundle_sha256=_sha("publication-bundle"),
            source_commit_sha256=_sha("source-commit"),
            infinity_base_url="http://127.0.0.1:29091",
            mem0_base_url="http://127.0.0.1:29092",
            dispatch_not_before_unix_ms=1,
            dispatch_deadline_unix_ms=2,
        ),
        extraction_terminal_paths=extraction_paths,
        retrieval_database_path=tmp_path / "sealed-input" / "retrieval.sqlite3",
        retrieval_authority_root_sha256=_sha("retrieval-authority"),
        fleet_pool_id="alternate-dataset-authority-pool",
        fleet_bridges=(),
        runtime_attestation=RuntimeAttestationConfig(
            directory=tmp_path / "runtime-attestations",
            endpoint="http://127.0.0.1:29092",
            endpoint_timeout_seconds=1.0,
            lane_project_name="alternate-dataset-authority-lane",
            maximum_age_seconds=60,
            required_fleet_mode="reopen",
        ),
        runtime_authority=RuntimeAuthorityConfig(
            adapter_image_id=f"sha256:{_sha('adapter-image')}",
            codex_executable_sha256=_sha("codex"),
            extraction_response_format_sha256=_sha("response-format"),
            extraction_response_schema_sha256=_sha("response-schema"),
            extraction_system_prompt_sha256=_sha("system-prompt"),
            node_executable_sha256=_sha("node"),
            runtime_artifact_manifest_sha256=_sha("runtime-manifest"),
            runtime_entrypoint_sha256=_sha("runtime-entrypoint"),
            runtime_pin_path=tmp_path / "authority" / "runtime-pin.json",
            runtime_pin_sha256=_sha("runtime-pin"),
            runtime_route_binding_sha256=_sha("runtime-route"),
            runtime_source_sha256=_sha("runtime-source"),
            source_manifest_sha256=_sha("source-manifest"),
            subscription_runtime_binding_commitment_sha256=runtime_binding_sha256,
        ),
        output_cipher_key_id="alternate-output-key",
        maximum_ciphertext_bytes=1024,
        maximum_bridge_request_bytes=1024,
        bridge_connect_timeout_seconds=1.0,
        bridge_read_timeout_seconds=1.0,
        bridge_write_timeout_seconds=1.0,
        lease_duration_ms=1,
    )


def _outer_authorities(state: Path) -> tuple[PublishableRunConfig, PublishableRunSecrets]:
    config = PublishableRunConfig(
        dependency_provider=subject.PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
        official_case_authority_path=state / "official-cases.sqlite3",
        scheduler_database_paths=(
            state / "locomo-scheduler.sqlite3",
            state / "longmemeval-scheduler.sqlite3",
        ),
        suite_seal_database_path=state / "suite-seal.sqlite3",
        publication_receipt_path=state / "publication.json",
        publication_key_id="alternate-dataset-authority-publication-key",
        max_dispatches_per_batch=1,
        adapter_config_json=b"{}",
    )
    secrets = PublishableRunSecrets(
        official_case_authentication_key=bytes([11]) * 32,
        scheduler_authentication_keys=(bytes([12]) * 32, bytes([13]) * 32),
        suite_seal_authentication_key=bytes([14]) * 32,
        publication_receipt_authentication_key=bytes([15]) * 32,
        adapter_secrets_json=b"{}",
    )
    return config, secrets


def test_alternate_authenticated_dataset_rejects_before_official_case_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    datasets = _write_alternate_datasets(tmp_path / "datasets")
    terminal_paths = (
        tmp_path / "locomo-terminal.json",
        tmp_path / "longmemeval-terminal.json",
    )
    extraction_keys = (bytes([21]) * 32, bytes([22]) * 32)
    runtime_binding_sha256 = _sha("subscription-runtime-binding")
    scheduler_runtime_sha256 = _sha("scheduler-runtime")
    profile_dataset_sha256 = _profile_dataset_sha256()
    run_config = _run_provider_config(
        tmp_path,
        datasets=datasets,
        extraction_paths=terminal_paths,
        runtime_binding_sha256=runtime_binding_sha256,
    )
    terminals = tuple(
        _extraction_terminal(
            profile_id=scheduler_profile.profile_id,
            run_id=run_id,
            dataset_sha256=dataset_sha256,
            runtime_binding_sha256=runtime_binding_sha256,
            scheduler_runtime_sha256=scheduler_runtime_sha256,
            index=index,
        )
        for index, (scheduler_profile, run_id, dataset_sha256) in enumerate(
            zip(
                (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE),
                (
                    run_config.suite.locomo_run_id,
                    run_config.suite.longmemeval_run_id,
                ),
                profile_dataset_sha256,
                strict=True,
            )
        )
    )
    for path, terminal, key in zip(terminal_paths, terminals, extraction_keys, strict=True):
        _write_extraction_terminal(path, terminal, authentication_key=key)

    projection = subject.OfficialCaseProjection.load(run_config)
    alternate_dataset_sha256 = tuple(item.sha256 for item in datasets)
    assert tuple(len(group) for group in projection.identities) == (
        LOCOMO_PROFILE.case_count,
        LONGMEMEVAL_PROFILE.case_count,
    )
    assert projection.observed_dataset_sha256 == alternate_dataset_sha256
    assert alternate_dataset_sha256 != profile_dataset_sha256
    extraction = subject.open_sealed_extraction_suite(
        terminal_paths,
        authentication_keys=extraction_keys,
    )
    assert (
        extraction.locomo_terminal.dataset_sha256,
        extraction.longmemeval_terminal.dataset_sha256,
    ) == profile_dataset_sha256

    run_secrets = RunProviderSecrets(
        extraction_authentication_keys=extraction_keys,
        retrieval_authentication_key=bytes([23]) * 32,
        bridge_journal_authentication_key=bytes([24]) * 32,
        output_cipher_key=bytes([25]) * 32,
        runtime_attestation_root_secret=bytes([26]) * 32,
        bridges=(),
    )
    monkeypatch.setattr(
        subject,
        "parse_run_provider_inputs",
        lambda _inputs: (run_config, run_secrets),
    )
    monkeypatch.setattr(subject, "preflight_run_provider", lambda **_kwargs: object())
    monkeypatch.setattr(
        orchestrator_module,
        "_issue_publishable_execution_authority",
        object,
    )
    outer_config, outer_secrets = _outer_authorities(state)

    with pytest.raises(PublishableRunError) as error:
        PublishableRunOrchestrator(
            dependency_factory=subject.Mem0InfinityPublishableRunDependencyFactory()
        ).run(config=outer_config, secrets=outer_secrets)

    assert error.value.code == "publishable_run_provider_official_dataset_cross_wire"
    durable_paths = (
        outer_config.official_case_authority_path,
        *outer_config.scheduler_database_paths,
        outer_config.suite_seal_database_path,
        outer_config.publication_receipt_path,
    )
    assert all(not path.exists() for path in durable_paths)
    assert all(
        not Path(f"{outer_config.official_case_authority_path}{suffix}").exists()
        for suffix in ("-journal", "-shm", "-wal")
    )
