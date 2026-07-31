"""Authoritative construction and one-shot admission for managed comparisons."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_case_loader import (
    cases_from_payload,
    parse_memory_comparison_dataset_bytes,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_methodology import (
    case_distribution,
    corpus_count,
    full_comparison_methodology_contract,
    public_full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FullComparisonProfile,
    frozen_full_comparison_profile,
    public_full_comparison_profile,
    select_full_comparison_profile_cases,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
    normalize_full_comparison_scope,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
    _managed_corpus_session_mapping,
    _managed_official_turn_count,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    ManagedRunError,
    ManagedRunPlan,
    _thaw_json,
    _unique_corpora,
    _validated_execution_case_manifest,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_checkpoint import selected_case_fingerprint
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_TOKEN = object()
_LOCK = threading.RLock()


@final
class VerifiedManagedRunPlan:
    """Opaque, noncopyable, single-use authority for one managed run."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedRunError("verified managed plans must be built authoritatively")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedManagedRunPlan is final")

    def __repr__(self) -> str:
        return "VerifiedManagedRunPlan(<sealed>)"

    def __copy__(self) -> object:
        raise TypeError("VerifiedManagedRunPlan is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("VerifiedManagedRunPlan is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("VerifiedManagedRunPlan is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("VerifiedManagedRunPlan is nonserializable")


@dataclass(frozen=True, slots=True)
class _VerifiedPlanState:
    plan: ManagedRunPlan
    cases: tuple[PublicBenchmarkCase, ...]
    answer_cases: tuple[ManagedAnswerCase, ...]
    case_aliases: tuple[str, ...]
    case_material_sha256: tuple[tuple[str, str], ...]
    secret: bytes
    commitment: str


@dataclass(frozen=True, slots=True)
class _VerifiedManagedRunMaterial:
    plan: ManagedRunPlan
    cases: tuple[PublicBenchmarkCase, ...]
    answer_cases: tuple[ManagedAnswerCase, ...]
    case_aliases: tuple[str, ...]
    case_material_sha256: tuple[tuple[str, str], ...]


_PLANS: weakref.WeakKeyDictionary[VerifiedManagedRunPlan, _VerifiedPlanState] = (
    weakref.WeakKeyDictionary()
)


def build_verified_managed_run_plan(
    *,
    run_id: str,
    run_nonce_commitment_sha256: str,
    runtime_probe_nonce_sha256: str,
    profile: FullComparisonProfile,
    dataset_bytes: bytes,
    backend_targets: tuple[FullComparisonBackendTarget, ...],
    provider_route: ProviderRouteAttestation,
    scope: str = FULL_COMPARISON_SCOPE_FULL,
    selected_case_ids: tuple[str, ...] = (),
) -> VerifiedManagedRunPlan:
    """Build and seal a plan from exact dataset bytes and frozen profile primitives."""

    if type(dataset_bytes) is not bytes:
        raise ManagedRunError("dataset_bytes must be exact bytes")
    trusted_profile = frozen_full_comparison_profile(profile)
    trusted_scope = normalize_full_comparison_scope(scope)
    payload = parse_memory_comparison_dataset_bytes(dataset_bytes)
    locomo_mode = trusted_profile.required_locomo_ingest_mode or LOCOMO_INGEST_OFFICIAL_TURNS
    loaded_cases = cases_from_payload(payload, locomo_ingest_mode=locomo_mode)
    profile_cases = select_full_comparison_profile_cases(
        profile=trusted_profile,
        cases=loaded_cases,
    )
    _validate_unique_case_ids(profile_cases)
    selected_cases = _select_cases(
        profile_cases,
        scope=trusted_scope,
        selected_case_ids=selected_case_ids,
    )
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    if trusted_scope == FULL_COMPARISON_SCOPE_FULL:
        _validate_full_dataset(
            trusted_profile,
            profile_cases,
            dataset_sha256=dataset_sha256,
        )

    managed_cases, manifest = _managed_cases_and_manifest(selected_cases)
    plan = ManagedRunPlan(
        run_id=run_id,
        run_nonce_commitment_sha256=run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=runtime_probe_nonce_sha256,
        profile=trusted_profile,
        methodology=full_comparison_methodology_contract(trusted_profile),
        dataset_sha256=dataset_sha256,
        selection_fingerprint_sha256=selected_case_fingerprint(selected_cases),
        backend_targets=backend_targets,
        case_manifest=manifest,
        provider_route=provider_route,
        cases=managed_cases,
        scope=trusted_scope,
    )
    _validate_plan(plan)
    return _seal_verified_plan(plan, selected_cases)


def _select_cases(
    cases: tuple[PublicBenchmarkCase, ...],
    *,
    scope: str,
    selected_case_ids: tuple[str, ...],
) -> tuple[PublicBenchmarkCase, ...]:
    if type(selected_case_ids) is not tuple or any(
        type(item) is not str or not item for item in selected_case_ids
    ):
        raise ManagedRunError("selected_case_ids must be an exact tuple of IDs")
    if scope == FULL_COMPARISON_SCOPE_FULL:
        if selected_case_ids:
            raise ManagedRunError("full scope cannot accept caller-selected case IDs")
        if not cases:
            raise ManagedRunError("full scope dataset has no profile cases")
        return cases
    if scope != FULL_COMPARISON_SCOPE_CANARY or not selected_case_ids:
        raise ManagedRunError("canary scope requires selected_case_ids")
    if len(set(selected_case_ids)) != len(selected_case_ids):
        raise ManagedRunError("selected_case_ids contains duplicates")
    requested = set(selected_case_ids)
    selected = tuple(case for case in cases if case.case_id in requested)
    if len(selected) != len(selected_case_ids):
        raise ManagedRunError("selected_case_ids contains an unknown profile case")
    if tuple(case.case_id for case in selected) != selected_case_ids:
        raise ManagedRunError("selected_case_ids must preserve authoritative dataset order")
    return selected


def _validate_full_dataset(
    profile: FullComparisonProfile,
    cases: tuple[PublicBenchmarkCase, ...],
    *,
    dataset_sha256: str,
) -> None:
    if dataset_sha256 != profile.expected_dataset_hash:
        raise ManagedRunError("full scope dataset hash differs from the frozen profile")
    if len(cases) != profile.expected_case_count:
        raise ManagedRunError("full scope case count differs from the frozen profile")
    if case_distribution(profile, cases) != dict(profile.expected_distribution):
        raise ManagedRunError("full scope distribution differs from the frozen profile")
    if corpus_count(profile, cases) != profile.expected_corpus_count:
        raise ManagedRunError("full scope corpus count differs from the frozen profile")


def _validate_unique_case_ids(cases: tuple[PublicBenchmarkCase, ...]) -> None:
    ids = tuple(case.case_id for case in cases)
    if len(set(ids)) != len(ids):
        raise ManagedRunError("profile dataset contains duplicate case IDs")


def _managed_cases_and_manifest(
    cases: tuple[PublicBenchmarkCase, ...],
) -> tuple[tuple[ManagedRunCase, ...], tuple[FullExecutionCaseManifestEntry, ...]]:
    managed: list[ManagedRunCase] = []
    manifest: list[FullExecutionCaseManifestEntry] = []
    for case in cases:
        corpus_id, thread_id = _managed_corpus_identity(case)
        case_alias = _managed_case_alias(case)
        record = _managed_corpus_record(case)
        session_roles, session_aliases = _managed_corpus_session_mapping(record)
        managed.append(ManagedRunCase(case_alias, corpus_id, record))
        manifest.append(
            FullExecutionCaseManifestEntry(
                case_alias,
                corpus_id,
                thread_id,
                session_roles,
                session_aliases,
                _managed_official_turn_count(record),
            )
        )
    return tuple(managed), tuple(manifest)


def _managed_case_alias(case: PublicBenchmarkCase) -> str:
    if type(case) is not PublicBenchmarkCase:
        raise ManagedRunError("managed case alias requires an exact benchmark case")
    digest = hashlib.sha256(f"{case.benchmark}\0case\0{case.case_id}".encode()).hexdigest()
    return f"{case.benchmark}-case-{digest}"


def _seal_verified_plan(
    plan: ManagedRunPlan,
    cases: tuple[PublicBenchmarkCase, ...],
) -> VerifiedManagedRunPlan:
    case_aliases = tuple(item.case_id for item in plan.cases)
    answer_cases = _managed_answer_cases(cases, case_aliases=case_aliases)
    material = _case_material_sha256(cases, case_aliases=case_aliases)
    secret = secrets.token_bytes(32)
    commitment = hmac.new(
        secret,
        _canonical_json(_admission_material(plan, material)),
        hashlib.sha256,
    ).hexdigest()
    admission = VerifiedManagedRunPlan(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _PLANS[admission] = _VerifiedPlanState(
            plan,
            cases,
            answer_cases,
            case_aliases,
            material,
            secret,
            commitment,
        )
    return admission


def _inspect_verified_managed_run_plan(admission: object) -> ManagedRunPlan:
    if type(admission) is not VerifiedManagedRunPlan:
        raise ManagedRunError("managed comparison requires a verified managed run plan")
    with _LOCK:
        state = _PLANS.get(admission)
        if state is None:
            raise ManagedRunError("verified managed run plan is unavailable or consumed")
        _validate_admission(admission, state)
        return state.plan


def _consume_verified_managed_run_plan(
    admission: VerifiedManagedRunPlan,
    *,
    expected_plan: ManagedRunPlan,
) -> _VerifiedManagedRunMaterial:
    with _LOCK:
        state = _PLANS.get(admission)
        if state is None:
            raise ManagedRunError("verified managed run plan is unavailable or consumed")
        if state.plan is not expected_plan:
            raise ManagedRunError("verified managed run plan changed during preflight")
        _validate_admission(admission, state)
        del _PLANS[admission]
        return _VerifiedManagedRunMaterial(
            state.plan,
            state.cases,
            state.answer_cases,
            state.case_aliases,
            state.case_material_sha256,
        )


def _validate_admission(
    admission: VerifiedManagedRunPlan,
    state: _VerifiedPlanState,
) -> None:
    try:
        observed = admission._VerifiedManagedRunPlan__commitment
        current_material = _case_material_sha256(
            state.cases,
            case_aliases=state.case_aliases,
        )
        current_answer_cases = _managed_answer_cases(
            state.cases,
            case_aliases=state.case_aliases,
        )
        expected = hmac.new(
            state.secret,
            _canonical_json(_admission_material(state.plan, current_material)),
            hashlib.sha256,
        ).hexdigest()
    except ManagedRunError:
        raise
    except Exception as exc:
        raise ManagedRunError("verified managed run plan integrity failed") from exc
    if (
        type(observed) is not str
        or current_answer_cases != state.answer_cases
        or current_material != state.case_material_sha256
        or not hmac.compare_digest(observed, state.commitment)
        or not hmac.compare_digest(expected, state.commitment)
    ):
        raise ManagedRunError("verified managed run plan integrity failed")


def _validate_plan(plan: ManagedRunPlan) -> None:
    if type(plan) is not ManagedRunPlan:
        raise ManagedRunError("managed run plan type must be exact")
    _validated_execution_case_manifest(
        plan.cases,
        plan.case_manifest,
        benchmark=plan.profile.benchmark,
    )
    public_full_comparison_profile(plan.profile)
    public_full_comparison_methodology_contract(plan.methodology)
    create_full_comparison_run_bindings(
        run_id=plan.run_id,
        run_nonce_commitment_sha256=plan.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=plan.runtime_probe_nonce_sha256,
        profile=plan.profile,
        methodology=plan.methodology,
        dataset_sha256=plan.dataset_sha256,
        selection_fingerprint_sha256=plan.selection_fingerprint_sha256,
        backend_targets=plan.backend_targets,
        scope=plan.scope,
    )
    _unique_corpora(plan.cases)


def _plan_material(plan: ManagedRunPlan) -> dict[str, object]:
    _validate_plan(plan)
    records = {
        corpus_id: hashlib.sha256(_canonical_json(_thaw_json(record))).hexdigest()
        for corpus_id, record in _unique_corpora(plan.cases)
    }
    return {
        "run_id": plan.run_id,
        "run_nonce_commitment_sha256": plan.run_nonce_commitment_sha256,
        "runtime_probe_nonce_sha256": plan.runtime_probe_nonce_sha256,
        "profile": public_full_comparison_profile(plan.profile),
        "methodology": public_full_comparison_methodology_contract(plan.methodology),
        "dataset_sha256": plan.dataset_sha256,
        "selection_fingerprint_sha256": plan.selection_fingerprint_sha256,
        "backend_targets": [
            {
                "backend_role": item.backend_role,
                "target_identity_sha256": item.target_identity_sha256,
            }
            for item in plan.backend_targets
        ],
        "case_manifest_sha256": execution_case_manifest_sha256(plan.case_manifest),
        "provider_route": plan.provider_route.public_payload(),
        "cases": [
            {
                "case_id": item.case_id,
                "corpus_id": item.corpus_id,
                "record_sha256": records[item.corpus_id],
            }
            for item in plan.cases
        ],
        "scope": plan.scope,
    }


def _admission_material(
    plan: ManagedRunPlan,
    case_material_sha256: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    return {
        "plan": _plan_material(plan),
        "private_case_material_sha256": [
            {"case_alias": case_alias, "sha256": digest}
            for case_alias, digest in case_material_sha256
        ],
    }


def _case_material_sha256(
    cases: tuple[PublicBenchmarkCase, ...],
    *,
    case_aliases: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    if (
        type(cases) is not tuple
        or type(case_aliases) is not tuple
        or len(cases) != len(case_aliases)
        or not cases
    ):
        raise ManagedRunError("private case material coverage differs")
    return tuple(
        (
            case_alias,
            managed_execution_case_material_sha256(case, case_alias=case_alias),
        )
        for case, case_alias in zip(cases, case_aliases, strict=True)
    )


def _managed_answer_cases(
    cases: tuple[PublicBenchmarkCase, ...],
    *,
    case_aliases: tuple[str, ...],
) -> tuple[ManagedAnswerCase, ...]:
    if (
        type(cases) is not tuple
        or type(case_aliases) is not tuple
        or len(cases) != len(case_aliases)
    ):
        raise ManagedRunError("answer case coverage differs")
    allowed_temporal_fields = ("question_type", "question_date", "reference_date")
    return tuple(
        ManagedAnswerCase(
            case_alias,
            case.question,
            {
                key: value
                for key in allowed_temporal_fields
                if (value := case.metadata.get(key)) is not None
                and type(value) in {str, int, float}
            },
        )
        for case, case_alias in zip(cases, case_aliases, strict=True)
    )


def managed_execution_case_material_sha256(
    case: PublicBenchmarkCase,
    *,
    case_alias: str,
) -> str:
    """Commit all private evaluator and corpus inputs without projecting their values."""

    if type(case) is not PublicBenchmarkCase:
        raise ManagedRunError("private case material requires an exact benchmark case")
    if case_alias != _managed_case_alias(case):
        raise ManagedRunError("private case alias differs from the authoritative case")
    return hashlib.sha256(_canonical_json(_private_case_material(case, case_alias))).hexdigest()


def _private_case_material(
    case: PublicBenchmarkCase,
    case_alias: str,
) -> dict[str, object]:
    if any(type(item) is not BenchmarkMemoryInput for item in case.memories):
        raise ManagedRunError("private case memory type differs")
    if any(type(item) is not BenchmarkDocumentInput for item in case.documents):
        raise ManagedRunError("private case document type differs")
    if any(type(item) is not BenchmarkConversationInput for item in case.conversations):
        raise ManagedRunError("private case conversation type differs")
    if any(
        type(message) is not BenchmarkMessageInput
        for conversation in case.conversations
        for message in conversation.messages
    ):
        raise ManagedRunError("private case message type differs")
    return {
        "case_alias": case_alias,
        "benchmark": case.benchmark,
        "raw_case_id": case.case_id,
        "question": case.question,
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "memory_scope_external_ref": case.memory_scope_external_ref,
        "thread_external_ref": case.thread_external_ref,
        "metadata": _private_json_mapping(case.metadata),
        "memories": [
            {
                "text": item.text,
                "kind": item.kind,
                "source_external_id": item.source_external_id,
                "metadata": _private_json_mapping(item.metadata),
            }
            for item in case.memories
        ],
        "documents": [
            {
                "title": item.title,
                "text": item.text,
                "source_type": item.source_type,
                "classification": item.classification,
                "source_external_id": item.source_external_id,
                "source_refs": _thaw_json(item.source_refs),
            }
            for item in case.documents
        ],
        "conversations": [
            {
                "source_external_id": item.source_external_id,
                "session_external_id": item.session_external_id,
                "session_date": item.session_date,
                "timestamp": item.timestamp,
                "metadata": _private_json_mapping(item.metadata),
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "source_external_id": message.source_external_id,
                        "timestamp": message.timestamp,
                        "metadata": _private_json_mapping(message.metadata),
                    }
                    for message in item.messages
                ],
            }
            for item in case.conversations
        ],
    }


def _private_json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    thawed = _thaw_json(value)
    if type(thawed) is not dict:
        raise ManagedRunError("private case metadata must be an exact JSON mapping")
    return thawed


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


__all__ = (
    "VerifiedManagedRunPlan",
    "build_verified_managed_run_plan",
    "managed_execution_case_material_sha256",
)
