"""Sealed pre-readiness CLI for managed production comparisons.

This composition root is intentionally limited to official dataset validation,
gold-free case projection, and the pure production policy gate. It never reads
environment variables, creates credential authorities, performs readiness, or
touches provider/backend transports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_full_profiles import (
    FULL_COMPARISON_PROFILES,
    FullComparisonProfile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_scope import FULL_COMPARISON_SCOPE_CANARY
from infinity_context_server.memory_comparison_managed_plan_builder import (
    MANAGED_CANARY_MAX_CASES,
    managed_policy_cases_from_dataset,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightError,
    managed_dataset_metadata_from_bytes,
)
from infinity_context_server.memory_comparison_managed_production_composition import (
    ManagedProductionCompositionDecision,
    ManagedProductionCompositionError,
    evaluate_managed_production_pre_readiness,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset,
    write_json_atomic,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

MANAGED_PRODUCTION_CLI_SUITE = "managed-comparison-production-pre-readiness"
MANAGED_PRODUCTION_CLI_SCHEMA_VERSION = "managed-comparison-production-pre-readiness.v1"
MANAGED_PRODUCTION_CLI_PROVIDER_KIND = "subscription-runtime"
MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES = 402_653_184
MANAGED_PRODUCTION_CLI_MAX_TOTAL_TOKENS = 2_000_000
MANAGED_PRODUCTION_CLI_READINESS_MAX_TOTAL_TOKENS = 512
MANAGED_PRODUCTION_CLI_READINESS_MAX_OUTPUT_TOKENS = 8
MANAGED_PRODUCTION_CLI_MAX_OUTPUT_TOKENS_PER_CALL = 4096

MANAGED_PRODUCTION_EXIT_READY = 2
MANAGED_PRODUCTION_EXIT_NO_GO = 1
MANAGED_PRODUCTION_EXIT_FAILURE = 3

_CASE_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")
_SAFE_ERROR_CODES = frozenset(
    {
        "artifact_path_invalid",
        "artifact_write_failed",
        "config_invalid",
        "dataset_invalid",
        "dataset_too_large",
        "dataset_unreadable",
        "decision_invalid",
        "production_pre_readiness_failed",
        "profile_invalid",
        "selection_invalid",
    }
)


class ManagedProductionCliError(RuntimeError):
    """Fixed-code CLI failure without paths, case IDs, gold, or credentials."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code if code in _SAFE_ERROR_CODES else "production_pre_readiness_failed"
        super().__init__(self.code)


@final
@dataclass(frozen=True, slots=True)
class ManagedProductionCliConfig:
    dataset_path: Path
    profile_id: str
    selected_case_ids: tuple[str, ...]
    max_total_tokens: int
    report_out: Path | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dataset_path, Path)
            or type(self.profile_id) is not str
            or not self.profile_id
            or type(self.selected_case_ids) is not tuple
            or not 1 <= len(self.selected_case_ids) <= MANAGED_CANARY_MAX_CASES
            or any(
                type(item) is not str or item != item.strip() or _CASE_ID.fullmatch(item) is None
                for item in self.selected_case_ids
            )
            or len(set(self.selected_case_ids)) != len(self.selected_case_ids)
            or type(self.max_total_tokens) is not int
            or not 1 <= self.max_total_tokens <= MANAGED_PRODUCTION_CLI_MAX_TOTAL_TOKENS
            or (self.report_out is not None and not isinstance(self.report_out, Path))
        ):
            raise ManagedProductionCliError("config_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProductionCliConfig is final")


def run_managed_production_cli(
    config: ManagedProductionCliConfig,
) -> dict[str, object]:
    """Evaluate the zero-I/O production gate and optionally write a private report."""

    if type(config) is not ManagedProductionCliConfig:
        raise ManagedProductionCliError("config_invalid")
    try:
        validate_artifact_paths_do_not_overwrite_dataset(
            dataset_path=config.dataset_path,
            error_factory=lambda _: ManagedProductionCliError("artifact_path_invalid"),
            report_out=config.report_out,
        )
    except ManagedProductionCliError as exc:
        return _failed_report(exc.code)

    try:
        profile = _profile(config.profile_id)
        dataset_bytes = _read_dataset_bytes(config.dataset_path)
        managed_dataset_metadata_from_bytes(
            profile=profile,
            dataset_bytes=dataset_bytes,
        )
        cases = managed_policy_cases_from_dataset(
            profile=profile,
            dataset_bytes=dataset_bytes,
            scope=FULL_COMPARISON_SCOPE_CANARY,
            selected_case_ids=config.selected_case_ids,
        )
        decision = evaluate_managed_production_pre_readiness(cases)
        report = _pre_readiness_report(
            config=config,
            profile=profile,
            dataset_bytes=dataset_bytes,
            decision=decision,
        )
    except ManagedProductionCliError as exc:
        report = _failed_report(exc.code)
    except ManagedPreflightError:
        report = _failed_report("dataset_invalid")
    except (ManagedRunError, BenchmarkValidationError, KeyError, TypeError, ValueError):
        report = _failed_report("selection_invalid")
    except ManagedProductionCompositionError:
        report = _failed_report("production_pre_readiness_failed")
    except OSError:
        report = _failed_report("dataset_unreadable")
    except Exception:
        report = _failed_report("production_pre_readiness_failed")

    if config.report_out is not None:
        try:
            write_json_atomic(config.report_out, report)
        except (OSError, TypeError, ValueError) as exc:
            raise ManagedProductionCliError("artifact_write_failed") from exc
    return report


def _profile(profile_id: str) -> FullComparisonProfile:
    try:
        profile = resolve_full_comparison_profile(profile_id)
    except (TypeError, ValueError):
        profile = None
    if profile is None:
        raise ManagedProductionCliError("profile_invalid")
    return profile


def _read_dataset_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES + 1)
    except OSError as exc:
        raise ManagedProductionCliError("dataset_unreadable") from exc
    if len(payload) > MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES:
        raise ManagedProductionCliError("dataset_too_large")
    if not payload:
        raise ManagedProductionCliError("dataset_unreadable")
    return payload


def _pre_readiness_report(
    *,
    config: ManagedProductionCliConfig,
    profile: FullComparisonProfile,
    dataset_bytes: bytes,
    decision: ManagedProductionCompositionDecision,
) -> dict[str, object]:
    if (
        type(decision) is not ManagedProductionCompositionDecision
        or decision.decision not in {"go", "no-go"}
        or decision.preparation_consumed is not False
        or decision.readiness_provider_calls_already_performed != 0
        or decision.additional_provider_calls_performed != 0
        or decision.additional_backend_calls_performed != 0
    ):
        raise ManagedProductionCliError("decision_invalid")
    selected_count = len(config.selected_case_ids)
    return {
        "suite": MANAGED_PRODUCTION_CLI_SUITE,
        "schema_version": MANAGED_PRODUCTION_CLI_SCHEMA_VERSION,
        "ok": decision.decision == "go",
        "status": f"{decision.decision}-pre-readiness",
        "provider_kind": MANAGED_PRODUCTION_CLI_PROVIDER_KIND,
        "profile_id": profile.profile_id,
        "scope": FULL_COMPARISON_SCOPE_CANARY,
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "selected_case_count": selected_count,
        "planned_limits": {
            "benchmark_answer_judge_provider_call_ceiling": selected_count * 4,
            "benchmark_provider_call_scope": "answer_judge_only",
            "readiness_provider_call_ceiling": 1,
            "answer_judge_and_readiness_provider_attempt_ceiling": selected_count * 4 + 1,
            "backend_internal_provider_calls": "unmeasured",
            "backend_internal_provider_cost": "unmeasured",
            "total_provider_calls_claimed": False,
            "benchmark_reserved_token_ceiling": config.max_total_tokens,
            "max_output_tokens_per_call": (MANAGED_PRODUCTION_CLI_MAX_OUTPUT_TOKENS_PER_CALL),
            "readiness_max_output_tokens": (MANAGED_PRODUCTION_CLI_READINESS_MAX_OUTPUT_TOKENS),
            "readiness_max_total_tokens": (MANAGED_PRODUCTION_CLI_READINESS_MAX_TOTAL_TOKENS),
        },
        "credentials_read": False,
        "provider_calls_performed": 0,
        "backend_calls_performed": 0,
        "live_state_touched": False,
        "execution_performed": False,
        "publishable": False,
        **decision.public_payload(),
    }


def _failed_report(code: str) -> dict[str, object]:
    safe_code = code if code in _SAFE_ERROR_CODES else "production_pre_readiness_failed"
    return {
        "suite": MANAGED_PRODUCTION_CLI_SUITE,
        "schema_version": MANAGED_PRODUCTION_CLI_SCHEMA_VERSION,
        "ok": False,
        "status": "sealed-failure",
        "reason_code": safe_code,
        "provider_kind": MANAGED_PRODUCTION_CLI_PROVIDER_KIND,
        "scope": FULL_COMPARISON_SCOPE_CANARY,
        "credentials_read": False,
        "readiness_provider_calls_already_performed": 0,
        "provider_calls_performed": 0,
        "backend_calls_performed": 0,
        "live_state_touched": False,
        "execution_performed": False,
        "publishable": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-managed-production-pre-readiness",
        description=(
            "Evaluate the sealed subscription-runtime canary production gate "
            "before credentials, readiness, provider calls, or backend calls; it does not execute."
        ),
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--profile", choices=FULL_COMPARISON_PROFILES, required=True)
    parser.add_argument("--case-id", dest="case_ids", action="append", required=True)
    parser.add_argument(
        "--max-total-tokens",
        type=int,
        required=True,
        help="Explicit benchmark token ceiling (1..2000000); no calls occur on NO-GO.",
    )
    parser.add_argument("--report-out", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = ManagedProductionCliConfig(
            dataset_path=args.dataset,
            profile_id=str(args.profile),
            selected_case_ids=tuple(args.case_ids),
            max_total_tokens=args.max_total_tokens,
            report_out=args.report_out,
        )
        report = run_managed_production_cli(config)
    except ManagedProductionCliError as exc:
        report = _failed_report(exc.code)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    if report.get("status") == "go-pre-readiness":
        return MANAGED_PRODUCTION_EXIT_READY
    if report.get("status") == "no-go-pre-readiness":
        return MANAGED_PRODUCTION_EXIT_NO_GO
    return MANAGED_PRODUCTION_EXIT_FAILURE


__all__ = (
    "MANAGED_PRODUCTION_CLI_MAX_DATASET_BYTES",
    "MANAGED_PRODUCTION_CLI_MAX_TOTAL_TOKENS",
    "MANAGED_PRODUCTION_CLI_PROVIDER_KIND",
    "MANAGED_PRODUCTION_CLI_SCHEMA_VERSION",
    "MANAGED_PRODUCTION_CLI_SUITE",
    "ManagedProductionCliConfig",
    "ManagedProductionCliError",
    "main",
    "run_managed_production_cli",
    "MANAGED_PRODUCTION_EXIT_READY",
)


if __name__ == "__main__":
    raise SystemExit(main())
