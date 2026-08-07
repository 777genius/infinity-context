"""Identity-bound composition authority for managed runner seams."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    REQUIRED_FULL_COMPARISON_BACKENDS,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)


class ManagedRunnerBindingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _BindingState:
    run_id: str
    profile_id: str
    binding_commitment_sha256: str
    deadline: datetime
    target_pairs: tuple[tuple[str, str], ...]
    retrieval_top_k: int
    answer_cutoff: int
    integrity_mac: bytes


_BINDINGS: weakref.WeakKeyDictionary[ManagedRunnerCompositionBinding, _BindingState]


@final
class ManagedRunnerCompositionBinding:
    """Redacted live identity backed only by private immutable primitives."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        run_id: str,
        profile: FullComparisonProfile,
        binding_commitment_sha256: str,
        deadline: datetime,
        backend_targets: tuple[FullComparisonBackendTarget, ...],
        retrieval_top_k: int,
        answer_cutoff: int,
    ) -> None:
        try:
            trusted_profile = frozen_full_comparison_profile(profile)
        except Exception:
            raise ManagedRunnerBindingError("managed_runner_profile_invalid") from None
        if (
            type(run_id) is not str
            or _ID.fullmatch(run_id) is None
            or type(binding_commitment_sha256) is not str
            or _SHA256.fullmatch(binding_commitment_sha256) is None
            or type(deadline) is not datetime
            or deadline.tzinfo is None
            or deadline.utcoffset() is None
            or type(backend_targets) is not tuple
            or not backend_targets
            or any(type(item) is not FullComparisonBackendTarget for item in backend_targets)
            or type(retrieval_top_k) is not int
            or retrieval_top_k != trusted_profile.retrieval_top_k
            or type(answer_cutoff) is not int
            or answer_cutoff != trusted_profile.answer_cutoff
        ):
            raise ManagedRunnerBindingError("managed_runner_composition_binding_invalid")
        try:
            validated_targets = tuple(
                FullComparisonBackendTarget(item.backend_role, item.target_identity_sha256)
                for item in backend_targets
            )
        except Exception:
            raise ManagedRunnerBindingError(
                "managed_runner_composition_binding_invalid"
            ) from None
        target_pairs = tuple(
            (item.backend_role, item.target_identity_sha256) for item in validated_targets
        )
        if (
            tuple(role for role, _ in target_pairs) != REQUIRED_FULL_COMPARISON_BACKENDS
            or len({target for _, target in target_pairs}) != len(target_pairs)
        ):
            raise ManagedRunnerBindingError("managed_runner_composition_binding_invalid")
        state = _BindingState(
            run_id,
            trusted_profile.profile_id,
            binding_commitment_sha256,
            deadline,
            target_pairs,
            retrieval_top_k,
            answer_cutoff,
            b"",
        )
        state = replace(state, integrity_mac=_binding_mac(self, state))
        with _LOCK:
            _BINDINGS[self] = state

    @property
    def run_id(self) -> str:
        return _binding_state(self).run_id

    @property
    def profile(self) -> FullComparisonProfile:
        profile = resolve_full_comparison_profile(_binding_state(self).profile_id)
        if profile is None:  # pragma: no cover - registry primitives are issued above
            raise ManagedRunnerBindingError("managed_runner_composition_binding_invalid")
        return profile

    @property
    def profile_id(self) -> str:
        return _binding_state(self).profile_id

    @property
    def binding_commitment_sha256(self) -> str:
        return _binding_state(self).binding_commitment_sha256

    @property
    def deadline(self) -> datetime:
        return _binding_state(self).deadline

    @property
    def backend_targets(self) -> tuple[FullComparisonBackendTarget, ...]:
        return tuple(
            FullComparisonBackendTarget(*item) for item in _binding_state(self).target_pairs
        )

    @property
    def retrieval_top_k(self) -> int:
        return _binding_state(self).retrieval_top_k

    @property
    def answer_cutoff(self) -> int:
        return _binding_state(self).answer_cutoff

    def __repr__(self) -> str:
        return "ManagedRunnerCompositionBinding(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedRunnerCompositionBinding is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedRunnerCompositionBinding is nonserializable")


def _binding_state(value: object) -> _BindingState:
    if type(value) is not ManagedRunnerCompositionBinding:
        raise ManagedRunnerBindingError("managed_runner_composition_binding_invalid")
    with _LOCK:
        state = _BINDINGS.get(value)
    if state is None or not hmac.compare_digest(
        state.integrity_mac, _binding_mac(value, state)
    ):
        raise ManagedRunnerBindingError("managed_runner_composition_binding_invalid")
    return state


def _binding_mac(binding: ManagedRunnerCompositionBinding, state: _BindingState) -> bytes:
    material = json.dumps(
        {
            "binding_identity": id(binding),
            "run_id": state.run_id,
            "profile_id": state.profile_id,
            "binding_commitment_sha256": state.binding_commitment_sha256,
            "deadline_identity": id(state.deadline),
            "deadline": state.deadline.isoformat(),
            "target_pairs": state.target_pairs,
            "retrieval_top_k": state.retrieval_top_k,
            "answer_cutoff": state.answer_cutoff,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_SECRET, material, hashlib.sha256).digest()


_BINDINGS = weakref.WeakKeyDictionary()

__all__ = ("ManagedRunnerBindingError", "ManagedRunnerCompositionBinding")
