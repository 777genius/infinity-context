"""One-shot provider-neutral calls for exact managed execution lanes."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
)

_STAGES = ("answerer", "judge")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedProviderCallError(RuntimeError):
    """Fixed-code failure without prompt or response text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedProviderLaneBinding:
    comparison_commitment_sha256: str
    run_id: str
    profile_id: str
    public_case_alias: str
    backend_role: str
    stage: str
    model: str
    ordinal: int

    def __post_init__(self) -> None:
        _digest(self.comparison_commitment_sha256)
        for value in (
            self.run_id,
            self.profile_id,
            self.public_case_alias,
            self.backend_role,
            self.model,
        ):
            _identifier(value)
        if type(self.stage) is not str or self.stage not in _STAGES:
            raise ManagedProviderCallError("managed_provider_stage_invalid")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ManagedProviderCallError("managed_provider_ordinal_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProviderLaneBinding is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedProviderCallOutcome:
    binding: ManagedProviderLaneBinding
    completion: ProviderChatCompletion
    provider_call: FullExecutionProviderCall

    def __post_init__(self) -> None:
        if (
            type(self.binding) is not ManagedProviderLaneBinding
            or type(self.completion) is not ProviderChatCompletion
            or type(self.provider_call) is not FullExecutionProviderCall
            or self.completion.provenance is not self.provider_call.provenance
        ):
            raise ManagedProviderCallError("managed_provider_outcome_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProviderCallOutcome is final")


def managed_provider_lane_bindings(
    *,
    comparison_commitment_sha256: str,
    run_id: str,
    profile_id: str,
    public_case_aliases: tuple[str, ...],
    backend_roles: tuple[str, str],
    answerer_model: str,
    judge_model: str,
) -> tuple[ManagedProviderLaneBinding, ...]:
    """Build exact case, backend, answerer, judge order: four calls per case."""

    _digest(comparison_commitment_sha256)
    for value in (run_id, profile_id, answerer_model, judge_model):
        _identifier(value)
    if (
        type(public_case_aliases) is not tuple
        or not public_case_aliases
        or any(type(item) is not str or _ID.fullmatch(item) is None for item in public_case_aliases)
        or len(set(public_case_aliases)) != len(public_case_aliases)
        or type(backend_roles) is not tuple
        or len(backend_roles) != 2
        or any(type(item) is not str or _ID.fullmatch(item) is None for item in backend_roles)
        or len(set(backend_roles)) != 2
    ):
        raise ManagedProviderCallError("managed_provider_plan_invalid")
    shapes = (
        (case_alias, backend_role, stage)
        for case_alias in public_case_aliases
        for backend_role in backend_roles
        for stage in _STAGES
    )
    return tuple(
        ManagedProviderLaneBinding(
            comparison_commitment_sha256,
            run_id,
            profile_id,
            case_alias,
            backend_role,
            stage,
            answerer_model if stage == "answerer" else judge_model,
            ordinal,
        )
        for ordinal, (case_alias, backend_role, stage) in enumerate(shapes)
    )


@final
class ManagedProviderCallCollector:
    """Serial authority for the ordered FullExecutionProviderCall tuple."""

    __slots__ = (
        "_active",
        "_calls",
        "_clock",
        "_deadline",
        "_expected",
        "_expected_snapshot",
        "_index",
        "_lock",
        "_phase",
        "_provider",
    )

    def __init__(
        self,
        *,
        provider: BoundedProviderChatCompletions,
        bindings: tuple[ManagedProviderLaneBinding, ...],
        deadline_monotonic: float,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(provider) is not BoundedProviderChatCompletions:
            raise ManagedProviderCallError("managed_provider_transport_invalid")
        trusted = _binding_plan(bindings)
        self._expected = tuple(_copy_binding(item) for item in trusted)
        self._expected_snapshot = _binding_snapshot(self._expected)
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, int | float)
            or not math.isfinite(deadline_monotonic)
            or deadline_monotonic <= 0
            or not callable(monotonic_clock)
        ):
            raise ManagedProviderCallError("managed_provider_deadline_invalid")
        self._provider = provider
        self._deadline = float(deadline_monotonic)
        self._clock = monotonic_clock
        self._lock = threading.RLock()
        self._index = 0
        self._calls: list[FullExecutionProviderCall] = []
        self._active: ManagedProviderLaneTransport | None = None
        self._phase = "open"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProviderCallCollector is final")

    def issue_lane(self, binding: ManagedProviderLaneBinding) -> ManagedProviderLaneTransport:
        if type(binding) is not ManagedProviderLaneBinding:
            raise ManagedProviderCallError("managed_provider_binding_invalid")
        binding.__post_init__()
        with self._lock:
            if self._phase != "open":
                raise ManagedProviderCallError("managed_provider_collector_terminal")
            self._validate_plan_current()
            if self._active is not None:
                raise ManagedProviderCallError("managed_provider_lane_concurrent")
            if self._index >= len(self._expected) or binding != self._expected[self._index]:
                raise ManagedProviderCallError("managed_provider_lane_order_invalid")
            owned_binding = self._expected[self._index]
            lane = ManagedProviderLaneTransport(
                owned_binding,
                self._provider,
                self._deadline,
                self._clock,
                self,
            )
            self._active = lane
            return lane

    def seal(self) -> tuple[FullExecutionProviderCall, ...]:
        with self._lock:
            if self._phase != "open":
                raise ManagedProviderCallError("managed_provider_collector_terminal")
            self._validate_plan_current()
            if self._active is not None:
                raise ManagedProviderCallError("managed_provider_lane_concurrent")
            if self._index != len(self._expected):
                raise ManagedProviderCallError("managed_provider_coverage_incomplete")
            self._phase = "sealed"
            return tuple(self._calls)

    def _finish(
        self,
        lane: ManagedProviderLaneTransport,
        outcome: ManagedProviderCallOutcome | None,
    ) -> None:
        with self._lock:
            if self._phase != "open" or self._active is not lane:
                self._phase = "failed"
                raise ManagedProviderCallError("managed_provider_authority_invalid")
            self._validate_plan_current()
            self._active = None
            if outcome is None:
                self._phase = "failed"
                return
            if outcome.binding != self._expected[self._index]:
                self._phase = "failed"
                raise ManagedProviderCallError("managed_provider_outcome_invalid")
            self._calls.append(outcome.provider_call)
            self._index += 1

    def _validate_plan_current(self) -> None:
        if _binding_snapshot(self._expected) != self._expected_snapshot:
            self._phase = "failed"
            raise ManagedProviderCallError("managed_provider_plan_mutated")
        _binding_plan(self._expected)


@final
class ManagedProviderLaneTransport:
    """One-shot exact lane; retries are forbidden and every attempt is terminal."""

    __slots__ = ("_binding", "_clock", "_collector", "_deadline", "_lock", "_phase", "_provider")

    def __init__(
        self,
        binding: ManagedProviderLaneBinding,
        provider: BoundedProviderChatCompletions,
        deadline: float,
        clock: Callable[[], float],
        collector: ManagedProviderCallCollector,
    ) -> None:
        self._binding = binding
        self._provider = provider
        self._deadline = deadline
        self._clock = clock
        self._collector = collector
        self._lock = threading.Lock()
        self._phase = "issued"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProviderLaneTransport is final")

    @property
    def binding(self) -> ManagedProviderLaneBinding:
        return self._binding

    def __repr__(self) -> str:
        return "ManagedProviderLaneTransport(<bound>)"

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
        retries: int = 0,
    ) -> ManagedProviderCallOutcome:
        with self._lock:
            if self._phase != "issued":
                raise ManagedProviderCallError("managed_provider_lane_terminal")
            self._phase = "attempting"
        try:
            if type(retries) is not int or retries != 0:
                raise ManagedProviderCallError("managed_provider_retries_forbidden")
            if self._deadline - self._clock() <= 0:
                raise ManagedProviderCallError("managed_provider_deadline")
            completion = self._provider.complete(
                model=self._binding.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                response_format=response_format,
            )
            if self._deadline - self._clock() <= 0:
                raise ManagedProviderCallError("managed_provider_deadline")
            outcome = _outcome(self._binding, completion)
        except BaseException as exc:
            self._terminal(None)
            if isinstance(exc, ManagedProviderCallError):
                raise
            if isinstance(exc, Exception):
                raise ManagedProviderCallError("managed_provider_call_failed") from None
            raise
        self._terminal(outcome)
        return outcome

    def _terminal(self, outcome: ManagedProviderCallOutcome | None) -> None:
        with self._lock:
            self._phase = "succeeded" if outcome is not None else "failed"
        self._collector._finish(self, outcome)


def create_managed_provider_call_collector(
    *,
    provider: BoundedProviderChatCompletions,
    bindings: tuple[ManagedProviderLaneBinding, ...],
    deadline_monotonic: float,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> ManagedProviderCallCollector:
    return ManagedProviderCallCollector(
        provider=provider,
        bindings=bindings,
        deadline_monotonic=deadline_monotonic,
        monotonic_clock=monotonic_clock,
    )


def _outcome(binding: ManagedProviderLaneBinding, completion: object) -> ManagedProviderCallOutcome:
    if type(completion) is not ProviderChatCompletion:
        raise ManagedProviderCallError("managed_provider_completion_invalid")
    provenance = completion.provenance
    if (
        type(provenance) is not ProviderCallProvenance
        or provenance.requested_model != binding.model
        or provenance.observed_model != binding.model
    ):
        raise ManagedProviderCallError("managed_provider_provenance_invalid")
    call = FullExecutionProviderCall(
        binding.comparison_commitment_sha256,
        binding.run_id,
        binding.profile_id,
        binding.public_case_alias,
        binding.backend_role,
        binding.stage,
        False,
        provenance,
    )
    return ManagedProviderCallOutcome(binding, completion, call)


def _binding_plan(value: object) -> tuple[ManagedProviderLaneBinding, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(value) % 4 != 0
        or any(type(item) is not ManagedProviderLaneBinding for item in value)
    ):
        raise ManagedProviderCallError("managed_provider_plan_invalid")
    bindings = value
    for item in bindings:
        item.__post_init__()
    first = bindings[0]
    aliases = tuple(dict.fromkeys(item.public_case_alias for item in bindings))
    backends = tuple(dict.fromkeys(item.backend_role for item in bindings))
    expected = tuple(
        (alias, backend, stage) for alias in aliases for backend in backends for stage in _STAGES
    )
    if (
        len(backends) != 2
        or tuple(item.ordinal for item in bindings) != tuple(range(len(bindings)))
        or tuple((item.public_case_alias, item.backend_role, item.stage) for item in bindings)
        != expected
        or any(
            (item.comparison_commitment_sha256, item.run_id, item.profile_id)
            != (first.comparison_commitment_sha256, first.run_id, first.profile_id)
            for item in bindings
        )
    ):
        raise ManagedProviderCallError("managed_provider_plan_invalid")
    return bindings


def _copy_binding(item: ManagedProviderLaneBinding) -> ManagedProviderLaneBinding:
    return ManagedProviderLaneBinding(
        item.comparison_commitment_sha256,
        item.run_id,
        item.profile_id,
        item.public_case_alias,
        item.backend_role,
        item.stage,
        item.model,
        item.ordinal,
    )


def _binding_snapshot(
    bindings: tuple[ManagedProviderLaneBinding, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.comparison_commitment_sha256,
            item.run_id,
            item.profile_id,
            item.public_case_alias,
            item.backend_role,
            item.stage,
            item.model,
            item.ordinal,
        )
        for item in bindings
    )


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ManagedProviderCallError("managed_provider_identifier_invalid")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedProviderCallError("managed_provider_digest_invalid")
    return value


__all__ = (
    "ManagedProviderCallCollector",
    "ManagedProviderCallError",
    "ManagedProviderCallOutcome",
    "ManagedProviderLaneBinding",
    "ManagedProviderLaneTransport",
    "create_managed_provider_call_collector",
    "managed_provider_lane_bindings",
)
