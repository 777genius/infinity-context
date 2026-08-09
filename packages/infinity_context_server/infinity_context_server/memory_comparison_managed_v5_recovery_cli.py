"""Provider-free CLI for durable managed-v5 cleanup recovery."""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    build_managed_benchmark_cleanup_target_authority,
)

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpConfig,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    compose_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    read_managed_mem0_v5_private_secret,
    wipe_managed_mem0_v5_private_secret,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5Budget,
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_plan_builder import (
    build_managed_v5_cleanup_plan,
)
from infinity_context_server.memory_comparison_managed_v5_live_cli_config_loader import (
    load_managed_v5_live_cli_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_secret_snapshot import (
    load_recovery_distinct_secrets,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_mem0 import (
    ManagedV5RecoveryMem0Adapter,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_operation_authority import (
    build_managed_v5_recovery_pristine_verifier,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_projector import (
    rebuild_managed_v5_recovery_public_projection,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    ManagedV5RecoveryError,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_report import (
    ManagedV5RecoveryReport,
    write_recovery_report,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_runner import (
    ManagedV5RecoveryRunner,
)


def main(argv: Sequence[str] | None = None) -> int:
    return run_recovery_cli(argv=argv, env=os.environ)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_recovery_cli(
    *,
    argv: Sequence[str] | None,
    env: Mapping[str, str],
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    store: ManagedV5LiveRecoveryJournalStore | None = None
    mem0: ManagedV5RecoveryMem0Adapter | None = None
    pristine = None
    journal = None
    recovery_secret: bytearray | None = None
    authenticator: RecoveryJournalAuthenticator | None = None
    cleanup_readback_owner = None
    try:
        arguments = _arguments(argv)
        config, extraction_file, extraction_sha = load_managed_v5_live_cli_config(
            arguments.managed_v5_config_json
        )
        filesystem = config.filesystem
        if (
            arguments.report_out is not None
            and arguments.report_out != filesystem.recovery_report_file
        ):
            raise ValueError
        secret = read_managed_mem0_v5_private_secret(filesystem.recovery_hmac_secret_file)
        try:
            recovery_secret_sha = hashlib.sha256(secret.value).hexdigest()
            recovery_secret = bytearray(secret.value)
            authenticator = RecoveryJournalAuthenticator(
                secret=bytes(recovery_secret), run_id_sha256=arguments.expected_run_id_sha256
            )
        finally:
            wipe_managed_mem0_v5_private_secret(secret.value)
        store = ManagedV5LiveRecoveryJournalStore(
            path=filesystem.recovery_journal,
            state_root=filesystem.state_root,
            authenticator=authenticator,
        )
        authenticator = None
        journal = store.load_for_recovery(expected_run_id_sha256=arguments.expected_run_id_sha256)
        authority = journal.authority
        if (
            authority.extraction_contract_file != extraction_file
            or authority.extraction_contract_sha256 != extraction_sha
            or authority.mem0_origin != config.runtime.mem0_adapter_origin
        ):
            raise ValueError
        public = rebuild_managed_v5_recovery_public_projection(authority=authority, config=config)
        if journal.cleanup_plan is None:
            report = _no_registration_report(journal)
            write_recovery_report(
                filesystem.recovery_report_file,
                report_root=filesystem.report_root,
                report=report,
            )
            return 0
        if not arguments.allow_live_cleanup:
            raise ManagedV5RecoveryError(
                "managed_v5_recovery_live_cleanup_not_allowed", exit_code=3
            )
        cleanup_plan = ManagedBenchmarkCleanupPlan(
            journal.cleanup_plan, journal.cleanup_plan_sha256
        )
        target = build_managed_benchmark_cleanup_target_authority(
            infinity_target_identity_sha256=authority.infinity_target_identity_sha256,
            qdrant_target_commitment_sha256=cleanup_plan.value["qdrant"][
                "target_commitment_sha256"
            ],
            graphiti_target_commitment_sha256=cleanup_plan.value["graphiti"][
                "target_commitment_sha256"
            ],
        )
        target_event = next(item for item in journal.events if item.kind == "cleanup_plan_prepared")
        if target_event.details["cleanup_target_authority_sha256"] != target.authority_sha256:
            raise ValueError
        rebuilt = build_managed_v5_cleanup_plan(
            inputs=public.cleanup_plan_inputs, target_authority=target
        )
        if rebuilt != cleanup_plan:
            raise ValueError
        token = _token(env)
        budget = ManagedMem0V5Budget.for_authority(public.public_composition.manifest_authority)
        budget_policy = ManagedMem0V5BudgetPolicy(
            budget.total_call_count, public.public_composition.extraction_token_budget
        )
        material = load_recovery_distinct_secrets(
            filesystem=filesystem,
            credential_paths=public.public_composition.inputs.credential_paths,
            recovery_secret_sha256=recovery_secret_sha,
        )
        try:
            composition = _compose_mem0(public.public_composition, material.credentials)
            capabilities = composition.issue_recovery_capabilities(
                hmac_secret=bytes(recovery_secret)
            )
            cleanup_readback_owner = capabilities.cleanup_readback
            pristine = build_managed_v5_recovery_pristine_verifier(
                public=public.public_composition,
                budget_policy=budget_policy,
                operation_signer_secret=bytes(material.operation_signer_secret),
                checkpoint_head_secret=bytes(material.checkpoint_head_secret),
                durable_clean_state_secret=bytes(material.durable_clean_state_secret),
                dispatch_journal=filesystem.dispatch_journal,
                operation_journal=filesystem.operation_journal,
                durable_clean_state=filesystem.durable_clean_state,
            )
        finally:
            material.close()
        mem0 = ManagedV5RecoveryMem0Adapter(
            coordinator=composition.coordinator,
            authority=composition.authority,
            admission=public.public_composition.admission,
            request=composition.request,
            budget_policy=budget_policy,
            cleanup_readback=capabilities.cleanup_readback,
            clean_snapshot=capabilities.clean_snapshot,
            clean_verifier=capabilities.clean_verifier,
            pristine_state=pristine,
        )
        cleanup_readback_owner = None
        recovery_now = _clock_value(clock)
        registry_config = _registry_config(authority, token, clock, recovery_now)
        runner = ManagedV5RecoveryRunner(
            authority=authority,
            cleanup_plan=cleanup_plan,
            journal=store,
            registry_factory=lambda: ManagedBenchmarkRegistryHttpAdapter(registry_config),
            mem0=mem0,
            clock=clock,
        )
        report = runner.run()
        write_recovery_report(
            filesystem.recovery_report_file,
            report_root=filesystem.report_root,
            report=report,
        )
        return 0
    except ManagedV5RecoveryError as error:
        return _write_failure(locals(), error.code, error.exit_code)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return _write_failure(locals(), "managed_v5_recovery_cli_invalid", 3)
    finally:
        if mem0 is not None:
            _safe_close(mem0)
        elif cleanup_readback_owner is not None:
            _safe_close(cleanup_readback_owner)
        if pristine is not None:
            _safe_close(pristine)
        if store is not None:
            _safe_close(store)
        elif authenticator is not None:
            _safe_close(authenticator)
        if recovery_secret is not None:
            wipe_managed_mem0_v5_private_secret(recovery_secret)
            recovery_secret.clear()


def _safe_close(value: object) -> None:
    with suppress(Exception):
        close = value.close
        close()


def _compose_mem0(public, credentials):
    inputs = public.inputs
    return compose_managed_mem0_v5(
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
        credential_capabilities=credentials,
        transport=None,
    )


def _arguments(argv: Sequence[str] | None):
    parser = argparse.ArgumentParser(prog="infinity-context-managed-v5-recover")
    parser.add_argument("--managed-v5-config-json", type=Path, required=True)
    parser.add_argument("--expected-run-id-sha256", required=True)
    parser.add_argument("--allow-live-cleanup", action="store_true")
    parser.add_argument("--report-out", type=Path)
    value = parser.parse_args(argv)
    if (
        not value.managed_v5_config_json.is_absolute()
        or not _sha(value.expected_run_id_sha256)
        or (value.report_out is not None and not value.report_out.is_absolute())
    ):
        raise ValueError
    return value


def _token(env: Mapping[str, str]) -> str:
    value = env.get("MEMORY_EVAL_AUTH_TOKEN")
    if type(value) is not str or not value or value != value.strip() or len(value) > 4096:
        raise ValueError
    return value


def _no_registration_report(journal) -> ManagedV5RecoveryReport:
    authority = journal.authority
    return ManagedV5RecoveryReport(
        True,
        "completed",
        "no_registration",
        authority.run_id_sha256,
        authority.binding_commitment_sha256,
        authority.infinity_target_identity_sha256,
        authority.space_slug,
        None,
        None,
        "not_registered",
        None,
        journal.events[-1].event_sha256,
        journal.body_sha256,
    )


def _write_failure(scope: dict[str, object], reason: str, exit_code: int) -> int:
    journal = scope.get("journal")
    config = scope.get("config")
    store = scope.get("store")
    if journal is None or config is None or store is None:
        return 3
    authority = journal.authority
    try:
        current = store.load(expected_authority=authority)
    except Exception:
        return 3
    execution = any(item.kind == "execution_started" for item in current.events)
    report = ManagedV5RecoveryReport(
        False,
        "retry_required" if exit_code == 2 else "blocked",
        reason if reason.startswith("managed_v5_recovery_") else "managed_v5_recovery_cli_invalid",
        authority.run_id_sha256,
        authority.binding_commitment_sha256,
        authority.infinity_target_identity_sha256,
        authority.space_slug,
        None,
        None,
        "execution_started" if execution else "pre_execution",
        None,
        current.events[-1].event_sha256,
        current.body_sha256,
    )
    try:
        write_recovery_report(
            config.filesystem.recovery_report_file,
            report_root=config.filesystem.report_root,
            report=report,
        )
    except Exception:
        return 3
    return exit_code


def _registry_config(authority, token: str, clock, recovery_now: datetime):
    return ManagedBenchmarkRegistryHttpConfig(
        base_url=authority.infinity_origin,
        admin_bearer_token=token,
        target_identity_sha256=authority.infinity_target_identity_sha256,
        timeout_seconds=authority.request_timeout_seconds,
        benchmark_deadline=recovery_now + timedelta(seconds=authority.request_timeout_seconds),
        cleanup_recovery_timeout_seconds=authority.run_timeout_seconds,
        clock=clock,
    )


def _clock_value(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError
    return value.astimezone(UTC)


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


__all__ = ("main", "run_recovery_cli")
