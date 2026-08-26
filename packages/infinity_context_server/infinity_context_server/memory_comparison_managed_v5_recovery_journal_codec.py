"""Strict decoder for authenticated managed-v5 recovery journal bodies."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.ports.benchmark_cleanup_plan import (
    validate_managed_benchmark_cleanup_plan,
)

from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    JOURNAL_SCHEMA,
    ManagedV5LiveRecoveryAuthority,
    ManagedV5LiveRecoveryContractError,
    canonical_sha256,
    parse_recovery_authority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_events import (
    RecoveryJournalAuthentication,
    RecoveryJournalEvent,
)


def parse_recovery_journal_payload(
    value: object,
) -> tuple[
    ManagedV5LiveRecoveryAuthority,
    str,
    dict[str, object] | None,
    str | None,
    dict[str, object] | None,
    str | None,
    tuple[RecoveryJournalEvent, ...],
    str,
    RecoveryJournalAuthentication,
]:
    keys = {
        "schema_version",
        "authority",
        "authority_sha256",
        "cleanup_plan",
        "cleanup_plan_sha256",
        "projection_manifest",
        "projection_manifest_sha256",
        "events",
        "body_sha256",
        "authentication",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or value["schema_version"] != JOURNAL_SCHEMA
        or type(value["events"]) is not list
    ):
        _fail()
    authority = parse_recovery_authority(value["authority"])
    events = _events(value["events"])
    auth = value["authentication"]
    if type(auth) is not dict or set(auth) != {"algorithm", "key_id", "mac_sha256"}:
        _fail()
    projection = value["projection_manifest"]
    projection_sha = value["projection_manifest_sha256"]
    if (projection is None) != (projection_sha is None) or (
        projection is not None
        and (type(projection) is not dict or canonical_sha256(projection) != projection_sha)
    ):
        _fail()
    plan = value["cleanup_plan"]
    plan_sha = value["cleanup_plan_sha256"]
    if (plan is None) != (plan_sha is None):
        _fail()
    if plan is not None:
        try:
            validate_managed_benchmark_cleanup_plan(
                plan,
                plan_sha,
                run_id_sha256=authority.run_id_sha256,
                binding_commitment_sha256=authority.binding_commitment_sha256,
                infinity_target_identity_sha256=authority.infinity_target_identity_sha256,
                space_slug=authority.space_slug,
            )
        except Exception:
            _fail()
    _cross_wire(events, plan, plan_sha, projection, projection_sha)
    return (
        authority,
        value["authority_sha256"],
        plan,
        plan_sha,
        projection,
        projection_sha,
        events,
        value["body_sha256"],
        RecoveryJournalAuthentication(**auth),
    )


def _events(value: list[object]) -> tuple[RecoveryJournalEvent, ...]:
    events: list[RecoveryJournalEvent] = []
    for raw in value:
        if type(raw) is not dict or set(raw) != {
            "sequence",
            "kind",
            "recorded_at",
            "details",
            "previous_event_sha256",
            "event_sha256",
        }:
            _fail()
        events.append(RecoveryJournalEvent(**raw))
    if (
        not events
        or events[0].sequence != 0
        or any(
            (index and event.sequence <= events[index - 1].sequence)
            or (index and event.previous_event_sha256 != events[index - 1].event_sha256)
            or (index and _timestamp(event.recorded_at) < _timestamp(events[index - 1].recorded_at))
            for index, event in enumerate(events)
        )
    ):
        _fail()
    return tuple(events)


def _cross_wire(
    events: tuple[RecoveryJournalEvent, ...],
    plan: object,
    plan_sha: object,
    projection: object,
    projection_sha: object,
) -> None:
    plan_events = [event for event in events if event.kind == "cleanup_plan_prepared"]
    manifest_events = [event for event in events if event.kind == "projection_manifest_persisted"]
    if (
        (plan is None) != (len(plan_events) == 0)
        or len(plan_events) > 1
        or (plan is not None and plan_events[0].details.get("cleanup_plan_sha256") != plan_sha)
        or (projection is None) != (len(manifest_events) == 0)
        or len(manifest_events) > 1
        or (
            projection is not None
            and manifest_events[0].details.get("projection_manifest_sha256") != projection_sha
        )
        or any(
            event.details.get("cleanup_plan_sha256") != plan_sha
            for event in events
            if "cleanup_plan_sha256" in event.details
        )
    ):
        _fail()


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError):
        _fail()


def _fail() -> None:
    raise ManagedV5LiveRecoveryContractError("managed_v5_live_recovery_contract_invalid")


__all__ = ("parse_recovery_journal_payload",)
