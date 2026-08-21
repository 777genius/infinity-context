"""Exact secret-free observation extracted from managed Mem0 cleanup pass two."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    ManagedMem0V5CleanupReadbackWitness,
)


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0TerminalObservation:
    terminal_state: str
    terminal_commitment_sha256: str
    cleanup_readback_witness_sha256: str

    def __post_init__(self) -> None:
        if self.terminal_state != "deleted" or not all(
            _sha(value)
            for value in (
                self.terminal_commitment_sha256,
                self.cleanup_readback_witness_sha256,
            )
        ):
            raise ValueError("managed_v5_live_mem0_terminal_observation_invalid")


def run_mem0_cleanup_pass(
    lifecycle: object,
    pass_index: int,
) -> tuple[dict[str, object], ManagedMem0TerminalObservation | None]:
    """Run one pass and authenticate pass-two evidence at its nominal source."""

    cleanup = getattr(lifecycle, "cleanup_pass_one" if pass_index == 1 else "cleanup_pass_two")
    result = cleanup()
    payload = result.public_payload()
    if (
        payload.get("residual_record_count") != 0
        or type(payload.get("residual_root_sha256")) is not str
        or (pass_index == 1 and payload.get("terminal_state") != "deleted")
    ):
        raise ValueError("managed_v5_policy_mem0_cleanup_invalid")
    if pass_index == 1:
        return payload, None
    if type(result) is not ManagedMem0V5CleanupReadbackWitness:
        raise ValueError("managed_v5_policy_mem0_cleanup_invalid")
    return payload, ManagedMem0TerminalObservation(
        terminal_state="deleted",
        terminal_commitment_sha256=result.terminal_commitment_sha256,
        cleanup_readback_witness_sha256=result.evidence_commitment_sha256,
    )


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


__all__ = ("ManagedMem0TerminalObservation", "run_mem0_cleanup_pass")
