from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing
from dataclasses import replace
from pathlib import Path

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    managed_benchmark_cleanup_plan_material_sha256,
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_server import memory_comparison_managed_v5_recovery_journal as subject
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    ManagedV5LiveRecoveryContractError,
    canonical_json,
    parse_recovery_authority,
    strict_json,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalError,
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(tmp_path: Path) -> ManagedV5LiveRecoveryAuthority:
    state = tmp_path / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    run_id = "mem0-v5-live-test-r1"
    infinity = "http://127.0.0.1:17789"
    return ManagedV5LiveRecoveryAuthority(
        run_id=run_id,
        run_id_sha256=_sha(run_id),
        binding_commitment_sha256=_sha("binding"),
        infinity_target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=infinity
        ),
        space_slug=managed_http_lifecycle_space_slug(run_id),
        profile_id="mem0-locomo-top50-v1",
        selected_case_ids=("conv-26:qa:1", "conv-26:qa:2"),
        current_date="2026-08-09",
        issued_at="2026-08-09T00:00:00Z",
        deadline="2026-08-09T06:00:00Z",
        run_nonce_commitment_sha256=_sha("run-nonce"),
        runtime_probe_nonce_sha256=_sha("probe-nonce"),
        dataset_path=tmp_path / "locomo.json",
        dataset_sha256=_sha("dataset"),
        managed_v5_config_commitment_sha256=_sha("config"),
        extraction_contract_file=tmp_path / "contract.json",
        extraction_contract_sha256=_sha("contract"),
        infinity_origin=infinity,
        mem0_origin="http://127.0.0.1:19091",
        max_extraction_tokens=17_500_000,
        max_total_tokens=17_600_000,
        mem0_runtime_implementation_sha256=_sha("implementation"),
        mem0_local_auth_disabled_managed=True,
        mem0_oss_ingress_protected=True,
        allowed_mem0_hosts=("127.0.0.1",),
        connect_timeout_seconds=5.0,
        request_timeout_seconds=120.0,
        run_timeout_seconds=21_600.0,
        adapter_runtime_pin_sha256=_sha("pin"),
        state_root=state,
        checkpoint_file=state / "checkpoint.json",
        checkpoint_head_file=state / "checkpoint-head.json",
        dispatch_journal=state / "dispatch.sqlite3",
        operation_journal=state / "operations.sqlite3",
        durable_clean_state=state / "durable-clean-state.json",
    )


def _store(tmp_path: Path, secret: bytes = b"s" * 64):
    authority = _authority(tmp_path)
    authenticator = RecoveryJournalAuthenticator(
        secret=secret, run_id_sha256=authority.run_id_sha256
    )
    store = ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=authenticator,
    )
    return authority, authenticator, store


def _prepared(authority: ManagedV5LiveRecoveryAuthority) -> dict[str, object]:
    return {"authority_sha256": authority.sha256}


def _hold_journal_lock(state_root: str, run_id_sha256: str, ready, release) -> None:
    signer = RecoveryJournalAuthenticator(secret=b"s" * 64, run_id_sha256=run_id_sha256)
    store = ManagedV5LiveRecoveryJournalStore(
        path=Path(state_root) / "recovery.json",
        state_root=Path(state_root),
        authenticator=signer,
    )
    ready.set()
    release.wait(timeout=10)
    store.close()


def _cleanup_plan(authority: ManagedV5LiveRecoveryAuthority) -> ManagedBenchmarkCleanupPlan:
    value, digest = cleanup_plan_pair(
        run_id=authority.run_id_sha256,
        binding=authority.binding_commitment_sha256,
        target=authority.infinity_target_identity_sha256,
        space_slug=authority.space_slug,
    )
    return validate_managed_benchmark_cleanup_plan(
        value,
        digest,
        run_id_sha256=authority.run_id_sha256,
        binding_commitment_sha256=authority.binding_commitment_sha256,
        infinity_target_identity_sha256=authority.infinity_target_identity_sha256,
        space_slug=authority.space_slug,
    )


def _plan(
    authority: ManagedV5LiveRecoveryAuthority, digest: str | None = None
) -> dict[str, object]:
    return {
        "cleanup_plan_sha256": (
            _cleanup_plan(authority).sha256 if digest is None else _sha(digest)
        ),
        "cleanup_target_authority_sha256": _sha("target-authority"),
    }


def _registration(
    authority: ManagedV5LiveRecoveryAuthority, digest: str | None = None
) -> dict[str, object]:
    return {
        "cleanup_plan_sha256": (
            _cleanup_plan(authority).sha256 if digest is None else _sha(digest)
        ),
        "cleanup_plan_state": "sealed",
        "space_id": f"benchmark-space-{authority.run_id_sha256[:48]}",
        "registration_commitment_sha256": _sha("registration"),
    }


def test_authority_canonical_round_trip_and_derived_values(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    parsed = parse_recovery_authority(strict_json(canonical_json(authority.payload())))
    assert parsed == authority
    assert parsed.sha256 == hashlib.sha256(canonical_json(authority.payload())).hexdigest()

    with pytest.raises(ManagedV5LiveRecoveryContractError):
        parse_recovery_authority({**authority.payload(), "run_id_sha256": "0" * 64})
    with pytest.raises(ManagedV5LiveRecoveryContractError):
        parse_recovery_authority({**authority.payload(), "space_slug": "wrong"})
    with pytest.raises(ManagedV5LiveRecoveryContractError):
        parse_recovery_authority(
            {**authority.payload(), "infinity_target_identity_sha256": "0" * 64}
        )
    for mutation in (
        {"current_date": "2026-8-9"},
        {"current_date": "2026-08-08"},
        {"infinity_origin": "http://example.com:17789"},
        {"mem0_origin": "http://127.0.0.1:19091/path"},
    ):
        with pytest.raises(ManagedV5LiveRecoveryContractError):
            parse_recovery_authority({**authority.payload(), **mutation})


def test_strict_json_rejects_duplicate_keys_and_nonfinite() -> None:
    with pytest.raises(ManagedV5LiveRecoveryContractError):
        strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ManagedV5LiveRecoveryContractError):
        canonical_json({"unsafe": float("nan")})


def test_hmac_domains_and_key_id_are_exact(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    secret = b"k" * 64
    signer = RecoveryJournalAuthenticator(secret=secret, run_id_sha256=authority.run_id_sha256)
    key = hmac.new(
        secret,
        b"infinity-context\0managed-v5-live-recovery-key.v1\0"
        + authority.run_id_sha256.encode("ascii"),
        hashlib.sha256,
    ).digest()
    body_sha = _sha("body")
    expected_mac = hmac.new(
        key,
        b"infinity-context\0managed-v5-live-recovery-journal.v1\0" + body_sha.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    signed = signer.sign(body_sha)
    assert signed.key_id == "managed-v5-recovery-v1-" + hashlib.sha256(key).hexdigest()[:16]
    assert signed.mac_sha256 == expected_mac


def test_session_lock_excludes_second_process_until_owner_exits(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_journal_lock,
        args=(str(authority.state_root), authority.run_id_sha256, ready, release),
    )
    process.start()
    assert ready.wait(timeout=10)
    signer = RecoveryJournalAuthenticator(secret=b"s" * 64, run_id_sha256=authority.run_id_sha256)
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        ManagedV5LiveRecoveryJournalStore(
            path=authority.state_root / "recovery.json",
            state_root=authority.state_root,
            authenticator=signer,
        )
    signer.close()
    release.set()
    process.join(timeout=10)
    assert process.exitcode == 0


def test_append_only_order_replay_and_projection_manifest(tmp_path: Path) -> None:
    authority, _, store = _store(tmp_path)
    journal = store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    assert journal.events[0].kind == "prepared"
    assert (authority.state_root / "recovery.json").stat().st_mode & 0o777 == 0o600

    journal = store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details=_plan(authority),
        cleanup_plan=_cleanup_plan(authority),
    )
    assert journal.cleanup_plan == _cleanup_plan(authority).value
    assert journal.cleanup_plan_sha256 == _cleanup_plan(authority).sha256
    replay = store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2099-01-01T00:00:00Z",
        details=_plan(authority),
        cleanup_plan=_cleanup_plan(authority),
    )
    assert replay.payload() == journal.payload()
    journal = store.append(
        expected_authority=authority,
        kind="registration_observed",
        recorded_at="2026-08-09T00:00:02Z",
        details=_registration(authority),
    )
    journal = store.append(
        expected_authority=authority,
        kind="execution_started",
        recorded_at="2026-08-09T00:00:03Z",
        details={"cleanup_plan_sha256": _cleanup_plan(authority).sha256},
    )
    manifest = {"schema_version": "projection.v1", "units": [1, 2]}
    journal = store.append(
        expected_authority=authority,
        kind="projection_manifest_persisted",
        recorded_at="2026-08-09T00:00:04Z",
        details={
            "projection_manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest()
        },
        projection_manifest=manifest,
    )
    assert journal.projection_manifest == manifest
    assert (
        journal.projection_manifest_sha256 == hashlib.sha256(canonical_json(manifest)).hexdigest()
    )
    assert store.load(expected_authority=authority).payload() == journal.payload()
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.append(
            expected_authority=authority,
            kind="projection_manifest_persisted",
            recorded_at="2026-08-09T00:00:05Z",
            details=journal.events[-1].details,
            projection_manifest={"different": True},
        )


def test_transition_regression_changed_replay_and_unknown_kind_rejected(
    tmp_path: Path,
) -> None:
    authority, _, store = _store(tmp_path)
    store.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    for kind, details in (
        ("registration_observed", {}),
        ("cleanup_plan_canonically_sealed", {}),
        ("execution_started", {}),
    ):
        with pytest.raises(ManagedV5LiveRecoveryJournalError):
            store.append(
                expected_authority=authority,
                kind=kind,
                recorded_at="2026-08-09T00:00:01Z",
                details=details,
            )
    store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details=_plan(authority),
        cleanup_plan=_cleanup_plan(authority),
    )
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.append(
            expected_authority=authority,
            kind="registration_observed",
            recorded_at="2026-08-09T00:00:02Z",
            details={
                "cleanup_plan_sha256": _sha("other"),
                "cleanup_plan_state": "sealed",
                "space_id": f"benchmark-space-{authority.run_id_sha256[:48]}",
                "registration_commitment_sha256": _sha("registration"),
            },
        )
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.append(
            expected_authority=authority,
            kind="cleanup_plan_prepared",
            recorded_at="2026-08-09T00:00:02Z",
            details=_plan(authority, "b"),
            cleanup_plan=_cleanup_plan(authority),
        )


def test_tamper_wrong_key_and_unsafe_existing_file_fail_closed(tmp_path: Path) -> None:
    authority, _, store = _store(tmp_path)
    store.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    path = authority.state_root / "recovery.json"
    raw = json.loads(path.read_bytes())
    raw["events"][0]["details"] = {"tampered": True}
    path.write_bytes(canonical_json(raw))
    path.chmod(0o600)
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.load(expected_authority=authority)

    store.close()
    path.unlink()
    _, writer_authenticator, writer = _store(tmp_path, b"a" * 64)
    writer.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    writer.close()
    wrong = RecoveryJournalAuthenticator(secret=b"b" * 64, run_id_sha256=authority.run_id_sha256)
    wrong_store = ManagedV5LiveRecoveryJournalStore(
        path=path, state_root=authority.state_root, authenticator=wrong
    )
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        wrong_store.load(expected_authority=authority)
    wrong_store.close()
    writer = ManagedV5LiveRecoveryJournalStore(
        path=path,
        state_root=authority.state_root,
        authenticator=writer_authenticator,
    )

    path.chmod(0o644)
    before = path.read_bytes()
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        writer.append(
            expected_authority=authority,
            kind="cleanup_plan_prepared",
            recorded_at="2026-08-09T00:00:01Z",
            details={},
            cleanup_plan=_cleanup_plan(authority),
        )
    assert path.read_bytes() == before


def test_cleanup_plan_material_is_authenticated_and_immutable(tmp_path: Path) -> None:
    authority, signer, store = _store(tmp_path)
    store.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    journal = store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details=_plan(authority),
        cleanup_plan=_cleanup_plan(authority),
    )
    assert journal.cleanup_plan == _cleanup_plan(authority).value
    path = authority.state_root / "recovery.json"
    raw = json.loads(path.read_bytes())
    raw["cleanup_plan"]["profile_id"] = "tampered"
    raw["cleanup_plan_sha256"] = managed_benchmark_cleanup_plan_material_sha256(raw["cleanup_plan"])
    body = {
        key: value for key, value in raw.items() if key not in {"body_sha256", "authentication"}
    }
    raw["body_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    raw["authentication"] = signer.sign(raw["body_sha256"]).payload()
    path.write_bytes(canonical_json(raw))
    path.chmod(0o600)
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.load(expected_authority=authority)


def test_authority_mismatch_and_secret_wipe(tmp_path: Path) -> None:
    authority, signer, store = _store(tmp_path)
    store.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.load(expected_authority=replace(authority, binding_commitment_sha256=_sha("other")))
    signer.close()
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        signer.sign(_sha("body"))


def test_failed_atomic_replace_preserves_old_valid_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, _, store = _store(tmp_path)
    store.initialize(
        authority=authority, recorded_at="2026-08-09T00:00:00Z", details=_prepared(authority)
    )
    path = authority.state_root / "recovery.json"
    before = path.read_bytes()

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError

    monkeypatch.setattr(subject.os, "replace", fail_replace)
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.append(
            expected_authority=authority,
            kind="cleanup_plan_prepared",
            recorded_at="2026-08-09T00:00:01Z",
            details=_plan(authority),
            cleanup_plan=_cleanup_plan(authority),
        )
    assert path.read_bytes() == before


def test_ranked_events_skip_unavailable_observations_but_never_backfill(
    tmp_path: Path,
) -> None:
    authority, _, store = _store(tmp_path)
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details=_prepared(authority),
    )
    store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details=_plan(authority),
        cleanup_plan=_cleanup_plan(authority),
    )
    store.append(
        expected_authority=authority,
        kind="registration_observed",
        recorded_at="2026-08-09T00:00:02Z",
        details=_registration(authority),
    )
    store.append(
        expected_authority=authority,
        kind="execution_started",
        recorded_at="2026-08-09T00:00:03Z",
        details={"cleanup_plan_sha256": _cleanup_plan(authority).sha256},
    )
    store.append(
        expected_authority=authority,
        kind="cleanup_observed",
        recorded_at="2026-08-09T00:00:04Z",
        details={
            "cleanup_plan_sha256": _cleanup_plan(authority).sha256,
            "cleanup_receipt_sha256": _sha("cleanup-receipt"),
            "projection_cleanup_state": "blocked",
        },
    )
    store.append(
        expected_authority=authority,
        kind="mem0_terminal_observed",
        recorded_at="2026-08-09T00:00:05Z",
        details={
            "terminal_state": "aborted",
            "terminal_commitment_sha256": _sha("terminal"),
            "cleanup_readback_witness_sha256": _sha("pass-two"),
        },
    )
    terminal = store.append(
        expected_authority=authority,
        kind="canonical_terminal_observed",
        recorded_at="2026-08-09T00:00:06Z",
        details={
            "state": "cleanup_aborted",
            "projection_cleanup_state": "unsealed_abort_complete",
            "completion_receipt_sha256": _sha("completion"),
            "cleanup_plan_sha256": _cleanup_plan(authority).sha256,
        },
    )
    assert [event.sequence for event in terminal.events] == [0, 1, 2, 3, 6, 7, 8]
    with pytest.raises(ManagedV5LiveRecoveryJournalError):
        store.append(
            expected_authority=authority,
            kind="projection_manifest_persisted",
            recorded_at="2026-08-09T00:00:07Z",
            details={"projection_manifest_sha256": _sha("manifest")},
            projection_manifest={"late": True},
        )


def test_event_details_reject_extra_keys_and_secret_shaped_material(tmp_path: Path) -> None:
    authority, _, store = _store(tmp_path)
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details=_prepared(authority),
    )
    for details in (
        {**_plan(authority), "exception": "raw stack"},
        {
            "cleanup_plan_sha256": "Bearer secret-token",
            "cleanup_target_authority_sha256": _sha("target"),
        },
    ):
        with pytest.raises((ManagedV5LiveRecoveryContractError, ManagedV5LiveRecoveryJournalError)):
            store.append(
                expected_authority=authority,
                kind="cleanup_plan_prepared",
                recorded_at="2026-08-09T00:00:01Z",
                details=details,
                cleanup_plan=_cleanup_plan(authority),
            )


def test_store_holds_exclusive_session_lock_until_close(tmp_path: Path) -> None:
    authority, _, first = _store(tmp_path)
    second_authenticator = RecoveryJournalAuthenticator(
        secret=b"s" * 64, run_id_sha256=authority.run_id_sha256
    )
    with pytest.raises(ManagedV5LiveRecoveryJournalError, match="journal_locked"):
        ManagedV5LiveRecoveryJournalStore(
            path=authority.state_root / "recovery.json",
            state_root=authority.state_root,
            authenticator=second_authenticator,
        )
    first.close()
    second = ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=second_authenticator,
    )
    second.close()
