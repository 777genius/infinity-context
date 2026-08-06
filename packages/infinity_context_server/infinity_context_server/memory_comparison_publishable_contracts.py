"""Immutable JSON contract helpers for publishable memory comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import final

from infinity_context_server.public_benchmark_models import BenchmarkValidationError

_SEAL = object()
_LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class FrozenPublishablePayload(Mapping[str, object]):
    """Deeply immutable payload with a canonical integrity commitment."""

    __slots__ = ("_commitment_sha256", "_payload", "_profile_id", "_seal")

    def __init__(
        self,
        *,
        profile_id: str,
        payload: MappingProxyType,
        commitment_sha256: str,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _SEAL:
            raise TypeError("use freeze_publishable_payload")
        self._profile_id = profile_id
        self._payload = payload
        self._commitment_sha256 = commitment_sha256
        self._seal = _SEAL

    def __getitem__(self, key: str) -> object:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def __repr__(self) -> str:
        return f"FrozenPublishablePayload(profile_id={self._profile_id!r})"

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def commitment_sha256(self) -> str:
        return self._commitment_sha256

    def __copy__(self) -> FrozenPublishablePayload:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> FrozenPublishablePayload:
        memo[id(self)] = self
        return self

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("FrozenPublishablePayload cannot be pickled")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FrozenPublishablePayload is sealed")


@final
@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    benchmark: str
    dataset_sha256: str
    prompt_file_sha256: str
    expected_case_count: int
    expected_corpus_count: int
    expected_message_count: int | None
    grouping_field: str
    expected_grouping: tuple[tuple[str, int], ...]
    ingestion_contract: str
    extraction_call_budget: int
    answer_judge_call_budget: int
    total_call_budget: int
    readiness_probe_calls: int = 1
    readiness_probe_in_total: bool = False
    commitment_sha256: str = field(init=False)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("BenchmarkSpec is sealed")

    def __copy__(self) -> BenchmarkSpec:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> BenchmarkSpec:
        memo[id(self)] = self
        return self

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("BenchmarkSpec cannot be pickled")

    def __post_init__(self) -> None:
        for name in (
            "benchmark",
            "dataset_sha256",
            "prompt_file_sha256",
            "grouping_field",
            "ingestion_contract",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise BenchmarkValidationError(f"{name} must be an exact non-empty string")
        for name in ("dataset_sha256", "prompt_file_sha256"):
            if _LOWERCASE_SHA256.fullmatch(getattr(self, name)) is None:
                raise BenchmarkValidationError(f"{name} must be an exact lowercase sha256")
        if type(self.expected_grouping) is not tuple or not self.expected_grouping or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or not item[0]
            or item[0] != item[0].strip()
            or type(item[1]) is not int
            or item[1] < 1
            for item in self.expected_grouping
        ):
            raise BenchmarkValidationError("expected grouping must be exact immutable pairs")
        grouping_keys = tuple(item[0] for item in self.expected_grouping)
        if len(set(grouping_keys)) != len(grouping_keys):
            raise BenchmarkValidationError("expected grouping keys must be unique")
        for name in (
            "expected_case_count",
            "expected_corpus_count",
            "extraction_call_budget",
            "answer_judge_call_budget",
            "total_call_budget",
            "readiness_probe_calls",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise BenchmarkValidationError(f"{name} must be a positive exact integer")
        if self.expected_message_count is not None and (
            type(self.expected_message_count) is not int or self.expected_message_count < 1
        ):
            raise BenchmarkValidationError("expected_message_count must be positive or None")
        if sum(item[1] for item in self.expected_grouping) != self.expected_case_count:
            raise BenchmarkValidationError("expected grouping must sum to expected case count")
        if self.answer_judge_call_budget != self.expected_case_count * 2 * 2:
            raise BenchmarkValidationError(
                "answer/judge budget must equal cases*2 backends*2 stages"
            )
        if self.total_call_budget != self.extraction_call_budget + self.answer_judge_call_budget:
            raise BenchmarkValidationError("total budget must equal extraction plus answer/judge")
        if self.readiness_probe_calls != 1 or self.readiness_probe_in_total is not False:
            raise BenchmarkValidationError("one readiness probe must be excluded from total calls")
        object.__setattr__(self, "commitment_sha256", canonical_payload_sha256(self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "benchmark": self.benchmark,
            "dataset_sha256": self.dataset_sha256,
            "prompt_file_sha256": self.prompt_file_sha256,
            "expected_case_count": self.expected_case_count,
            "expected_corpus_count": self.expected_corpus_count,
            "expected_message_count": self.expected_message_count,
            "grouping_field": self.grouping_field,
            "expected_grouping": dict(self.expected_grouping),
            "ingestion_contract": self.ingestion_contract,
            "extraction_call_budget": self.extraction_call_budget,
            "answer_judge_call_budget": self.answer_judge_call_budget,
            "total_call_budget": self.total_call_budget,
            "readiness_probe_calls": self.readiness_probe_calls,
            "readiness_probe_in_total": self.readiness_probe_in_total,
        }


def freeze_publishable_payload(
    *,
    profile_id: str,
    payload: Mapping[str, object],
) -> FrozenPublishablePayload:
    if type(profile_id) is not str or not profile_id or profile_id != profile_id.strip():
        raise BenchmarkValidationError("publishable profile id is invalid")
    exact = _exact_json_object(payload)
    return FrozenPublishablePayload(
        profile_id=profile_id,
        payload=_deep_freeze(exact),
        commitment_sha256=canonical_payload_sha256(exact),
        _construction_seal=_SEAL,
    )


def validated_publishable_payload(
    value: FrozenPublishablePayload,
    *,
    profile_id: str,
    expected: Mapping[str, object],
) -> dict[str, object]:
    exact_expected = _exact_json_object(expected)
    if (
        type(value) is not FrozenPublishablePayload
        or value._seal is not _SEAL
        or type(value._profile_id) is not str
        or value._profile_id != profile_id
        or type(value._payload) is not MappingProxyType
        or not _is_deep_frozen(value._payload)
        or type(value._commitment_sha256) is not str
    ):
        raise BenchmarkValidationError("publishable contract must have the exact sealed type")
    public = _deep_thaw(value._payload)
    if public != exact_expected or value._commitment_sha256 != canonical_payload_sha256(
        exact_expected
    ):
        raise BenchmarkValidationError("publishable contract differs from frozen primitives")
    return exact_expected


def canonical_payload_bytes(payload: Mapping[str, object]) -> bytes:
    exact = _exact_json_object(payload)
    return json.dumps(
        exact,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _exact_json_object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise BenchmarkValidationError("publishable payload must be an exact dict")
    normalized = _normalize_json(value, depth=0)
    if type(normalized) is not dict:
        raise BenchmarkValidationError("publishable payload must be a JSON object")
    return normalized


def _normalize_json(value: object, *, depth: int) -> object:
    if depth > 20:
        raise BenchmarkValidationError("publishable payload nesting is too deep")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise BenchmarkValidationError("publishable payload contains non-finite numbers")
        return value
    if type(value) is dict:
        if any(type(key) is not str or not key for key in value):
            raise BenchmarkValidationError("publishable payload keys must be non-empty strings")
        return {key: _normalize_json(item, depth=depth + 1) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_normalize_json(item, depth=depth + 1) for item in value]
    raise BenchmarkValidationError("publishable payload contains a non-JSON value")


def _deep_freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: object) -> object:
    if type(value) is MappingProxyType:
        return {key: _deep_thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_deep_thaw(item) for item in value]
    return value


def _is_deep_frozen(value: object, *, depth: int = 0) -> bool:
    if depth > 20:
        return False
    if value is None or type(value) in {str, bool, int, float}:
        return True
    if type(value) is MappingProxyType:
        return all(
            type(key) is str and _is_deep_frozen(item, depth=depth + 1)
            for key, item in value.items()
        )
    if type(value) is tuple:
        return all(_is_deep_frozen(item, depth=depth + 1) for item in value)
    return False


__all__ = (
    "BenchmarkSpec",
    "FrozenPublishablePayload",
    "canonical_payload_bytes",
    "canonical_payload_sha256",
    "freeze_publishable_payload",
    "validated_publishable_payload",
)
