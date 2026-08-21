"""Strict secret-free event contracts for the recovery journal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryContractError,
    canonical_sha256,
)

RECOVERY_EVENT_KINDS = (
    "prepared",
    "cleanup_plan_prepared",
    "registration_observed",
    "execution_started",
    "projection_manifest_persisted",
    "registry_seal_observed",
    "cleanup_observed",
    "mem0_terminal_observed",
    "canonical_terminal_observed",
)
_SHA = frozenset("0123456789abcdef")


@final
@dataclass(frozen=True, slots=True)
class RecoveryJournalEvent:
    sequence: int
    kind: str
    recorded_at: str
    details: dict[str, object]
    previous_event_sha256: str | None
    event_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int
            or not 0 <= self.sequence < len(RECOVERY_EVENT_KINDS)
            or self.kind != RECOVERY_EVENT_KINDS[self.sequence]
            or not _rfc3339(self.recorded_at)
            or not _valid_details(self.kind, self.details)
            or canonical_sha256(self.base_payload()) != self.event_sha256
            or (self.sequence == 0) != (self.previous_event_sha256 is None)
            or (self.previous_event_sha256 is not None and not _sha(self.previous_event_sha256))
        ):
            _fail()

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        kind: str,
        recorded_at: str,
        details: dict[str, object],
        previous_event_sha256: str | None,
    ) -> RecoveryJournalEvent:
        base = {
            "sequence": sequence,
            "kind": kind,
            "recorded_at": recorded_at,
            "details": details,
            "previous_event_sha256": previous_event_sha256,
        }
        return cls(**base, event_sha256=canonical_sha256(base))

    def base_payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "recorded_at": self.recorded_at,
            "details": self.details,
            "previous_event_sha256": self.previous_event_sha256,
        }

    def payload(self) -> dict[str, object]:
        return {**self.base_payload(), "event_sha256": self.event_sha256}


@final
@dataclass(frozen=True, slots=True)
class RecoveryJournalAuthentication:
    algorithm: str
    key_id: str
    mac_sha256: str

    def payload(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "key_id": self.key_id, "mac_sha256": self.mac_sha256}


def _valid_details(kind: str, value: object) -> bool:
    if type(value) is not dict:
        return False
    keys = {
        "prepared": {"authority_sha256"},
        "cleanup_plan_prepared": {"cleanup_plan_sha256", "cleanup_target_authority_sha256"},
        "registration_observed": {
            "cleanup_plan_sha256",
            "cleanup_plan_state",
            "space_id",
            "registration_commitment_sha256",
        },
        "execution_started": {"cleanup_plan_sha256"},
        "projection_manifest_persisted": {"projection_manifest_sha256"},
        "registry_seal_observed": {
            "cleanup_plan_sha256",
            "projection_manifest_sha256",
            "projection_cleanup_state",
        },
        "cleanup_observed": {
            "cleanup_plan_sha256",
            "cleanup_receipt_sha256",
            "projection_cleanup_state",
        },
        "mem0_terminal_observed": {
            "terminal_state",
            "terminal_commitment_sha256",
            "cleanup_readback_witness_sha256",
        },
        "canonical_terminal_observed": {
            "state",
            "projection_cleanup_state",
            "completion_receipt_sha256",
            "cleanup_plan_sha256",
        },
    }
    expected = keys.get(kind)
    if expected is None or set(value) != expected:
        return False
    nondigests = {
        "cleanup_plan_state",
        "space_id",
        "projection_cleanup_state",
        "terminal_state",
        "state",
    }
    if any(not _sha(value[key]) for key in expected - nondigests):
        return False
    if kind == "registration_observed":
        space = value["space_id"]
        return (
            value["cleanup_plan_state"] == "sealed"
            and type(space) is str
            and len(space) == len("benchmark-space-") + 48
            and space.startswith("benchmark-space-")
            and set(space.removeprefix("benchmark-space-")) <= _SHA
        )
    if kind == "registry_seal_observed":
        return value["projection_cleanup_state"] == "sealed"
    if kind == "cleanup_observed":
        return value["projection_cleanup_state"] in {"pending", "blocked"}
    if kind == "mem0_terminal_observed":
        return value["terminal_state"] in {"deleted", "aborted", "not_started"}
    if kind == "canonical_terminal_observed":
        return value["state"] in {"cleanup_complete", "cleanup_aborted"} and value[
            "projection_cleanup_state"
        ] in {"complete", "unsealed_abort_complete"}
    return True


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA


def _rfc3339(value: object) -> bool:
    if type(value) is not str or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.isoformat().endswith("+00:00")


def _fail() -> None:
    raise ManagedV5LiveRecoveryContractError("managed_v5_live_recovery_contract_invalid")


__all__ = (
    "RECOVERY_EVENT_KINDS",
    "RecoveryJournalAuthentication",
    "RecoveryJournalEvent",
)
