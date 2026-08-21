"""Canonical codecs for scheduler authority run and backend scopes."""

from __future__ import annotations

from infinity_context_server.publishable_durable_scheduler.contracts import SchedulerBenchmark
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
    SchedulerOfficialCaseRunScope,
    SchedulerRetrievalBackendScope,
    SchedulerRetrievalRunScope,
    validate_case_run_scopes,
    validate_retrieval_run_scopes,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_integrity import (
    require_exact_keys,
)

_CASE_SCOPE_KEYS = frozenset(
    {
        "benchmark",
        "case_count",
        "case_manifest_sha256",
        "dataset_sha256",
        "methodology_sha256",
        "publishable_profile_id",
        "publishable_profile_sha256",
        "run_authority_sha256",
        "run_binding_commitment_sha256",
        "run_id",
        "scheduler_profile_id",
        "suite_authority_sha256",
    }
)
_RETRIEVAL_SCOPE_KEYS = frozenset({"backends", "case_scope", "cutoff"})
_BACKEND_SCOPE_KEYS = frozenset({"backend_index", "backend_role", "target_identity_sha256"})


def case_run_scopes_material(
    scopes: tuple[SchedulerOfficialCaseRunScope, ...],
) -> list[dict[str, object]]:
    validate_case_run_scopes(scopes)
    return [scope.material() for scope in scopes]


def case_run_scopes_from_material(
    value: object,
) -> tuple[SchedulerOfficialCaseRunScope, ...]:
    if type(value) is not list:
        _fail("scheduler_official_case_authority_config_invalid")
    scopes: list[SchedulerOfficialCaseRunScope] = []
    try:
        for raw in value:
            if type(raw) is not dict:
                raise TypeError
            require_exact_keys(
                raw,
                _CASE_SCOPE_KEYS,
                code="scheduler_official_case_authority_config_invalid",
            )
            scopes.append(
                SchedulerOfficialCaseRunScope(
                    suite_authority_sha256=raw["suite_authority_sha256"],
                    run_authority_sha256=raw["run_authority_sha256"],
                    run_binding_commitment_sha256=raw["run_binding_commitment_sha256"],
                    run_id=raw["run_id"],
                    benchmark=SchedulerBenchmark(raw["benchmark"]),
                    scheduler_profile_id=raw["scheduler_profile_id"],
                    publishable_profile_id=raw["publishable_profile_id"],
                    publishable_profile_sha256=raw["publishable_profile_sha256"],
                    methodology_sha256=raw["methodology_sha256"],
                    dataset_sha256=raw["dataset_sha256"],
                    case_manifest_sha256=raw["case_manifest_sha256"],
                    case_count=raw["case_count"],
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_case_authority_config_invalid"
        ) from error
    return validate_case_run_scopes(tuple(scopes))


def retrieval_run_scopes_material(
    scopes: tuple[SchedulerRetrievalRunScope, ...],
) -> list[dict[str, object]]:
    validate_retrieval_run_scopes(scopes)
    return [scope.material() for scope in scopes]


def retrieval_run_scopes_from_material(
    value: object,
) -> tuple[SchedulerRetrievalRunScope, ...]:
    if type(value) is not list:
        _fail("scheduler_retrieval_evidence_authority_config_invalid")
    scopes: list[SchedulerRetrievalRunScope] = []
    try:
        for raw in value:
            if type(raw) is not dict:
                raise TypeError
            require_exact_keys(
                raw,
                _RETRIEVAL_SCOPE_KEYS,
                code="scheduler_retrieval_evidence_authority_config_invalid",
            )
            case_scope = case_run_scopes_from_material([raw["case_scope"]])[0]
            raw_backends = raw["backends"]
            if type(raw_backends) is not list:
                raise TypeError
            backends: list[SchedulerRetrievalBackendScope] = []
            for raw_backend in raw_backends:
                if type(raw_backend) is not dict:
                    raise TypeError
                require_exact_keys(
                    raw_backend,
                    _BACKEND_SCOPE_KEYS,
                    code="scheduler_retrieval_evidence_authority_config_invalid",
                )
                backends.append(
                    SchedulerRetrievalBackendScope(
                        backend_index=raw_backend["backend_index"],
                        backend_role=raw_backend["backend_role"],
                        target_identity_sha256=raw_backend["target_identity_sha256"],
                    )
                )
            scopes.append(
                SchedulerRetrievalRunScope(
                    case_scope=case_scope,
                    backends=tuple(backends),
                    cutoff=raw["cutoff"],
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_retrieval_evidence_authority_config_invalid"
        ) from error
    return validate_retrieval_run_scopes(tuple(scopes))


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "case_run_scopes_from_material",
    "case_run_scopes_material",
    "retrieval_run_scopes_from_material",
    "retrieval_run_scopes_material",
)
