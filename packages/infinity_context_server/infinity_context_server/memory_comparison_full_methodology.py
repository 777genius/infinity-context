"""Deeply immutable frozen methodology and exact prompt provenance policy."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType

from infinity_context_server.memory_comparison_full_profiles import (
    INFINITY_COMPARISON_BACKEND,
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_MODEL,
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
    REQUIRED_FULL_COMPARISON_BACKENDS,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.memory_comparison_token_budget_contract import (
    token_budget_methodology_contract,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)

MEMORY_COMPARISON_PRIMARY_QUALITY_METRIC = "answer_accuracy"
MEMORY_COMPARISON_DIAGNOSTIC_ONLY_ROLE = "diagnostic_only"
FULL_METHODOLOGY_SCHEMA_VERSION = "memory-comparison-full-methodology.v1"
OFFICIAL_PROVIDER_ROUTE_SCHEMA_VERSION = "memory-comparison-official-provider-route.v1"
PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION = "memory-comparison-provider-call.v1"
OFFICIAL_OPENAI_ORIGIN = "https://api.openai.com"
OFFICIAL_OPENAI_ENDPOINT_PATH = "/v1/chat/completions"
OFFICIAL_PROVIDER = "openai-compatible"
OFFICIAL_TRANSPORT = "chat-completions"
OFFICIAL_PROVIDER_TRUST = "official_openai"
_LOCOMO_INGEST_MODE = "official-turns"
_LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA = "locomo-timestamp-transport-evidence.v5"
_LOCOMO_REQUEST_PROJECTION_SCHEMA = "locomo-add-request-producer-projection.v1"
_METHOD_CONSTRUCTION_SEAL = object()
_SHA256_LENGTH = 64


class FrozenFullComparisonMethodology(Mapping[str, object]):
    """Immutable view revalidated against primitive profile policy before serialization."""

    __slots__ = ("_profile_id", "_payload", "_commitment_sha256", "_seal")

    def __init__(
        self,
        *,
        profile_id: str,
        payload: MappingProxyType,
        commitment_sha256: str,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _METHOD_CONSTRUCTION_SEAL:
            raise TypeError("use full_comparison_methodology_contract")
        self._profile_id = profile_id
        self._payload = payload
        self._commitment_sha256 = commitment_sha256
        self._seal = _METHOD_CONSTRUCTION_SEAL

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FrozenFullComparisonMethodology is sealed")

    def __getitem__(self, key: str) -> object:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def __repr__(self) -> str:
        return f"FrozenFullComparisonMethodology(profile_id={self._profile_id!r})"


def full_comparison_methodology_contract(
    profile: FullComparisonProfile,
) -> FrozenFullComparisonMethodology:
    trusted = frozen_full_comparison_profile(profile)
    payload = _methodology_payload(trusted)
    return FrozenFullComparisonMethodology(
        profile_id=trusted.profile_id,
        payload=_deep_freeze(payload),
        commitment_sha256=_payload_sha256(payload),
        _construction_seal=_METHOD_CONSTRUCTION_SEAL,
    )


def public_full_comparison_methodology_contract(
    methodology: FrozenFullComparisonMethodology,
) -> dict[str, object]:
    """Reconstruct an exact JSON-safe projection; never trust stored mutable state."""

    if (
        type(methodology) is not FrozenFullComparisonMethodology
        or methodology._seal is not _METHOD_CONSTRUCTION_SEAL
        or type(methodology._profile_id) is not str
        or type(methodology._payload) is not MappingProxyType
        or not _is_deep_frozen(methodology._payload, depth=0)
        or type(methodology._commitment_sha256) is not str
    ):
        raise BenchmarkValidationError("methodology must have the exact sealed type")
    profile = resolve_full_comparison_profile(methodology._profile_id)
    if profile is None:
        raise BenchmarkValidationError("methodology profile is missing")
    expected = _methodology_payload(frozen_full_comparison_profile(profile))
    if _deep_thaw(
        methodology._payload
    ) != expected or methodology._commitment_sha256 != _payload_sha256(expected):
        raise BenchmarkValidationError("methodology differs from frozen primitives")
    return expected


def _methodology_payload(profile: FullComparisonProfile) -> dict[str, object]:
    locomo_required = profile.benchmark == "locomo"
    return {
        "schema_version": FULL_METHODOLOGY_SCHEMA_VERSION,
        "comparison_lane": "pinned_mem0_official_qa",
        "benchmark": profile.benchmark,
        "upstream_repository": "mem0ai/memory-benchmarks",
        "upstream_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "dataset_sha256": profile.expected_dataset_hash,
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "answerer_model": MEM0_OFFICIAL_MODEL,
        "judge_model": MEM0_OFFICIAL_MODEL,
        "official_provider_route": {
            "schema_version": OFFICIAL_PROVIDER_ROUTE_SCHEMA_VERSION,
            "provider": OFFICIAL_PROVIDER,
            "transport": OFFICIAL_TRANSPORT,
            "trust": OFFICIAL_PROVIDER_TRUST,
            "origin": OFFICIAL_OPENAI_ORIGIN,
            "endpoint_path": OFFICIAL_OPENAI_ENDPOINT_PATH,
        },
        "context_selection": "raw_retrieval_slice",
        "answer_case_gold_blind": True,
        "memory_order": "chronological_ascending",
        "case_source": "official_dataset_file_only",
        "primary_quality_metric": MEMORY_COMPARISON_PRIMARY_QUALITY_METRIC,
        "retrieval_label_metrics_role": MEMORY_COMPARISON_DIAGNOSTIC_ONLY_ROLE,
        "gold_aware_evidence_planner": "disabled",
        "judge_evidence_mode": "none",
        "retrieval_top_k": profile.retrieval_top_k,
        "answer_cutoff": profile.answer_cutoff,
        "locomo_transport": {
            "required": locomo_required,
            "ingest_mode": _LOCOMO_INGEST_MODE if locomo_required else None,
            "timestamps_required": locomo_required,
            "evidence_schema_version": (
                _LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA if locomo_required else None
            ),
            "request_projection_schema_version": (
                _LOCOMO_REQUEST_PROJECTION_SCHEMA if locomo_required else None
            ),
            "request_observation": (
                "producer_observed_canonical_projection" if locomo_required else None
            ),
            "expected_turn_contract": (
                "sealed_loader_projection_exact_match" if locomo_required else None
            ),
            "expected_turn_authenticity": (
                "deferred_to_dataset_composite_proof" if locomo_required else None
            ),
            "expected_loader_metadata": (
                "speaker_session_date_trigger_case_id_exact" if locomo_required else None
            ),
            "trigger_case_id_role": (
                "non_authoritative_ingestion_routing_observation" if locomo_required else None
            ),
            "trigger_case_id_receipt_binding": "sha256" if locomo_required else None,
            "trigger_case_id_in_logical_turn_identity": False if locomo_required else None,
            "corpus_receipt_reuse": (
                "permitted_after_corpus_reuse_proof" if locomo_required else None
            ),
            "serialized_expected_mapping_is_admission": (False if locomo_required else None),
            "benchmark_user_identity_policy": (
                "mem0-benchmark-user-id-sha256.v1" if locomo_required else None
            ),
            "runtime_http_identity_wiring": (
                "required_before_full_preflight" if locomo_required else None
            ),
            "runtime_source_timestamp_wiring": (
                "required_before_full_preflight" if locomo_required else None
            ),
            "provider_wire_bytes_attested": False if locomo_required else None,
            "counts_derived_from_projection": True if locomo_required else None,
        },
        "mem0_runtime": {
            "required_mode": profile.required_mem0_runtime_mode,
            "same_run_attestation_required": True,
            "max_attestation_age_seconds": 120,
            "trust_model": "client_observed_producer_validated",
            "trust_limit": (
                "validates adapter target, wrapper, SDK artifact, configuration, "
                "and live timestamp behavior; proprietary server revision is unattestable"
            ),
        },
        "answer_token_budget": token_budget_methodology_contract(
            profile.answer_token_budget_policy
        ),
        "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
        "single_pass": True,
        "provider_request_semantics": {
            "retrieval": "one request per backend case",
            "answerer": "one request per backend case at the frozen answer cutoff",
            "judge": "one no-evidence request per backend case at the frozen answer cutoff",
        },
        "publishable_only_when_eligible": True,
    }


def case_distribution(
    profile: FullComparisonProfile,
    cases: Sequence[PublicBenchmarkCase],
) -> dict[str, int]:
    trusted = frozen_full_comparison_profile(profile)
    values: Counter[str] = Counter()
    for case in cases:
        if trusted.benchmark == "locomo":
            group = {
                1: "multi-hop",
                2: "temporal",
                3: "open-domain",
                4: "single-hop",
                5: "adversarial",
            }.get(_exact_int(case.metadata.get("category")), "unknown")
        else:
            group = longmemeval_type(case.metadata.get("question_type"))
        values[group] += 1
    return dict(sorted(values.items()))


def longmemeval_type(value: object) -> str:
    normalized = str(value or "").strip().casefold().replace("_", "-")
    return {
        "knowledge-update": "knowledge-update",
        "multi-session": "multi-session",
        "single-session-assistant": "single-session-assistant",
        "single-session-preference": "single-session-preference",
        "single-session-user": "single-session-user",
        "temporal-reasoning": "temporal",
        "temporal": "temporal",
    }.get(normalized, normalized or "unknown")


def corpus_count(
    profile: FullComparisonProfile,
    cases: Sequence[PublicBenchmarkCase],
) -> int | None:
    trusted = frozen_full_comparison_profile(profile)
    if trusted.expected_corpus_count is None:
        return None
    corpus_ids = {
        str(case.metadata.get("sample_id") or case.memory_scope_external_ref or "").strip()
        for case in cases
    }
    corpus_ids.discard("")
    return len(corpus_ids)


def neutral_retrieval_policy_contract(
    evaluations: Sequence[Mapping[str, object]],
    *,
    expected_evaluation_count: int,
) -> dict[str, object]:
    expected = NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry()
    matched_count = 0
    missing_count = 0
    mismatched_count = 0
    observed_policy_ids: Counter[str] = Counter()
    for item in evaluations:
        if type(item) is not dict or item.get("backend") != INFINITY_COMPARISON_BACKEND:
            continue
        retrieval = item.get("retrieval")
        metadata = retrieval.get("metadata") if type(retrieval) is dict else None
        observed = metadata.get("retrieval_policy") if type(metadata) is dict else None
        if type(observed) is not dict:
            missing_count += 1
            continue
        observed_policy_ids[str(observed.get("policy_id") or "missing")] += 1
        if observed == expected:
            matched_count += 1
        else:
            mismatched_count += 1
    return {
        "matches": (
            type(expected_evaluation_count) is int
            and expected_evaluation_count >= 0
            and matched_count == expected_evaluation_count
            and missing_count == 0
            and mismatched_count == 0
        ),
        "expected": expected,
        "expected_evaluation_count": expected_evaluation_count,
        "matched_evaluation_count": matched_count,
        "missing_evaluation_count": missing_count,
        "mismatched_evaluation_count": mismatched_count,
        "observed_policy_ids": dict(sorted(observed_policy_ids.items())),
    }


def backend_set_contract(backend_names: Sequence[str]) -> dict[str, object]:
    valid_input = type(backend_names) in {tuple, list} and all(
        type(name) is str and name and name == name.strip() for name in backend_names
    )
    actual = tuple(backend_names) if valid_input else ()
    actual_counts = Counter(actual)
    required = set(REQUIRED_FULL_COMPARISON_BACKENDS)
    actual_set = set(actual_counts)
    duplicates = tuple(sorted(name for name, count in actual_counts.items() if count > 1))
    return {
        "required": list(REQUIRED_FULL_COMPARISON_BACKENDS),
        "actual": list(actual),
        "matches": (
            valid_input
            and actual_set == required
            and not duplicates
            and len(actual) == len(required)
        ),
        "missing": sorted(required - actual_set),
        "unexpected": sorted(actual_set - required),
        "duplicates": list(duplicates),
        "duplicate_count": sum(count - 1 for count in actual_counts.values() if count > 1),
    }


def prompt_provenance_issues(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    """Validate the exact frozen prompt and official OpenAI call projection."""

    issues: Counter[str] = Counter()
    if type(evaluations) not in {tuple, list}:
        return {"invalid_evaluations_schema": 1}
    for raw_item in evaluations:
        if type(raw_item) is not dict:
            issues["invalid_evaluation_schema"] += 1
            continue
        benchmark = raw_item.get("benchmark")
        if type(benchmark) is not str or benchmark not in MEM0_OFFICIAL_PROMPT_FILE_SHA256:
            issues["unknown_benchmark"] += 1
            continue
        telemetry = raw_item.get("execution_telemetry")
        expected_ingest_mode = _LOCOMO_INGEST_MODE if benchmark == "locomo" else None
        expected_telemetry = {
            "context_selection": "raw_retrieval_slice",
            "answer_case_gold_blind": True,
            "locomo_ingest_mode": expected_ingest_mode,
        }
        if type(telemetry) is not dict or telemetry != expected_telemetry:
            issues["execution_telemetry_schema"] += 1
        for stage_name, stage in (("generation", "answerer"), ("judgment", "judge")):
            _stage_provenance_issues(
                raw_item.get(stage_name),
                benchmark=benchmark,
                stage=stage,
                issues=issues,
            )
    return dict(sorted(issues.items()))


def _stage_provenance_issues(
    value: object,
    *,
    benchmark: str,
    stage: str,
    issues: Counter[str],
) -> None:
    if type(value) is not dict or set(value) != {"model", "metadata"}:
        issues[f"{stage}_stage_schema"] += 1
        return
    if type(value["model"]) is not str or value["model"] != MEM0_OFFICIAL_MODEL:
        issues[f"{stage}_model"] += 1
    metadata = value["metadata"]
    if type(metadata) is not dict:
        issues[f"{stage}_metadata_schema"] += 1
        return
    expected = _expected_stage_metadata(benchmark=benchmark, stage=stage)
    expected_keys = set(expected) | {"provider_provenance"}
    if set(metadata) != expected_keys:
        issues[f"{stage}_metadata_keys"] += 1
    for key, expected_value in expected.items():
        if (
            type(metadata.get(key)) is not type(expected_value)
            or metadata.get(key) != expected_value
        ):
            issues[f"{stage}_{key}"] += 1
    if not _official_provider_provenance(metadata.get("provider_provenance")):
        issues[f"{stage}_provider_provenance"] += 1


def _expected_stage_metadata(*, benchmark: str, stage: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider": OFFICIAL_PROVIDER,
        "transport": OFFICIAL_TRANSPORT,
        "stage": stage,
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "prompt_source_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "prompt_file_sha256": MEM0_OFFICIAL_PROMPT_FILE_SHA256[benchmark],
        "prompt_template": benchmark,
        "context_selection": "raw_retrieval_slice",
        "memory_order": "chronological_ascending",
        "temperature_policy": "zero_or_reasoning_model_default",
        "max_completion_tokens": 4096,
        "locomo_ingest_mode": _LOCOMO_INGEST_MODE if benchmark == "locomo" else None,
    }
    if stage == "answerer":
        metadata["answer_postprocess"] = (
            "last_answer_marker"
            if benchmark == "locomo"
            else "strip_mem_thinking_then_last_answer_marker"
        )
    else:
        metadata["judge_evidence_mode"] = "none"
        metadata["judge_parser"] = "json_correct_wrong" if benchmark == "locomo" else "final_yes_no"
    return metadata


def _official_provider_provenance(value: object) -> bool:
    keys = {
        "schema_version",
        "trust",
        "origin",
        "endpoint_path",
        "credential_bound",
        "credential_binding_id",
        "requested_model",
        "observed_model",
        "response_id",
        "system_fingerprint",
        "request_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        return False
    return bool(
        value["schema_version"] == PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION
        and type(value["schema_version"]) is str
        and value["trust"] == OFFICIAL_PROVIDER_TRUST
        and type(value["trust"]) is str
        and value["origin"] == OFFICIAL_OPENAI_ORIGIN
        and type(value["origin"]) is str
        and value["endpoint_path"] == OFFICIAL_OPENAI_ENDPOINT_PATH
        and type(value["endpoint_path"]) is str
        and value["credential_bound"] is True
        and _bounded_string(value["credential_binding_id"])
        and value["requested_model"] == MEM0_OFFICIAL_MODEL
        and type(value["requested_model"]) is str
        and value["observed_model"] == MEM0_OFFICIAL_MODEL
        and type(value["observed_model"]) is str
        and _bounded_string(value["response_id"])
        and _bounded_string(value["system_fingerprint"])
        and _sha256(value["request_sha256"])
    )


def observed_prompt_policies(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    policies: Counter[str] = Counter()
    if type(evaluations) not in {tuple, list}:
        return {}
    for item in evaluations:
        if type(item) is not dict:
            continue
        for stage_name in ("generation", "judgment"):
            stage = item.get(stage_name)
            metadata = stage.get("metadata") if type(stage) is dict else None
            policy = metadata.get("prompt_policy_id") if type(metadata) is dict else None
            if type(policy) is str and policy:
                policies[policy] += 1
    return dict(sorted(policies.items()))


def _deep_freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    if type(value) is tuple:
        return tuple(_deep_freeze(item) for item in value)
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise BenchmarkValidationError("methodology contains a non-JSON-safe value")


def _is_deep_frozen(value: object, *, depth: int) -> bool:
    if depth > 16:
        return False
    if type(value) is MappingProxyType:
        return all(
            type(key) is str and _is_deep_frozen(item, depth=depth + 1)
            for key, item in value.items()
        )
    if type(value) is tuple:
        return all(_is_deep_frozen(item, depth=depth + 1) for item in value)
    return value is None or type(value) in {str, int, float, bool}


def _deep_thaw(value: object) -> object:
    if type(value) is MappingProxyType:
        return {key: _deep_thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_deep_thaw(item) for item in value]
    return value


def _payload_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _bounded_string(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= 512 and value == value.strip()


def _sha256(value: object) -> bool:
    return bool(
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_int(value: object) -> int | None:
    return value if type(value) is int else None


__all__ = (
    "FULL_METHODOLOGY_SCHEMA_VERSION",
    "OFFICIAL_OPENAI_ENDPOINT_PATH",
    "OFFICIAL_OPENAI_ORIGIN",
    "OFFICIAL_PROVIDER",
    "OFFICIAL_PROVIDER_ROUTE_SCHEMA_VERSION",
    "OFFICIAL_PROVIDER_TRUST",
    "OFFICIAL_TRANSPORT",
    "FrozenFullComparisonMethodology",
    "backend_set_contract",
    "case_distribution",
    "corpus_count",
    "full_comparison_methodology_contract",
    "longmemeval_type",
    "neutral_retrieval_policy_contract",
    "observed_prompt_policies",
    "prompt_provenance_issues",
    "public_full_comparison_methodology_contract",
)
