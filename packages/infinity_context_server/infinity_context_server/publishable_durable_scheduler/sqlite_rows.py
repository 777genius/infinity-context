"""Authenticated row codecs for the scheduler SQLite adapter."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerContractError,
    canonical_json,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerLogicalCall,
    SchedulerManifestShard,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteAuthenticator,
    SchedulerSQLiteError,
    SchedulerSQLiteEvent,
    ciphertext_material,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
    SchedulerRunPhase,
    SchedulerRunState,
)

_RUN_COLUMNS: Final = (
    "run_id",
    "run_authority_sha256",
    "bridge_boot_authority_sha256",
    "dispatch_not_before_unix_ms",
    "dispatch_deadline_unix_ms",
    "token_ceiling",
    "expected_call_count",
    "phase",
    "reserved_tokens",
    "consumed_tokens",
    "burned_tokens",
    "inflight_logical_call_id",
    "version",
    "event_head_sha256",
)
_CALL_COLUMNS: Final = (
    "run_id",
    "ordinal",
    "shard_index",
    "logical_call_id",
    "stage",
    "token_ceiling",
    "depends_on_logical_call_id",
    "phase",
    "attempt_count",
    "lease_id",
    "lease_expires_unix_ms",
    "request_sha256",
    "intent_sha256",
    "terminal_evidence_sha256",
    "charged_tokens",
    "answer_ciphertext_sha256",
    "answer_ciphertext_bytes",
    "version",
)


def signed_material(
    authenticator: SchedulerSQLiteAuthenticator,
    domain: str,
    values: dict[str, object],
) -> tuple[object, ...]:
    return (*values.values(), authenticator.sign(domain, values))


def verify_material(
    authenticator: SchedulerSQLiteAuthenticator,
    domain: str,
    values: dict[str, object],
    signature: object,
) -> None:
    if not authenticator.verify(domain, values, signature):
        raise SchedulerSQLiteError("scheduler_sqlite_row_authentication_failed")


def run_values(state: SchedulerRunState, *, event_head_sha256: str) -> dict[str, object]:
    return {
        "run_id": state.run_id,
        "run_authority_sha256": state.run_authority_sha256,
        "bridge_boot_authority_sha256": state.bridge_boot_authority_sha256,
        "dispatch_not_before_unix_ms": state.dispatch_not_before_unix_ms,
        "dispatch_deadline_unix_ms": state.dispatch_deadline_unix_ms,
        "token_ceiling": state.token_ceiling,
        "expected_call_count": state.expected_call_count,
        "phase": state.phase.value,
        "reserved_tokens": state.reserved_tokens,
        "consumed_tokens": state.consumed_tokens,
        "burned_tokens": state.burned_tokens,
        "inflight_logical_call_id": state.inflight_logical_call_id,
        "version": state.version,
        "event_head_sha256": event_head_sha256,
    }


def run_from_row(
    row: sqlite3.Row, authenticator: SchedulerSQLiteAuthenticator
) -> tuple[SchedulerRunState, str]:
    values = {name: row[name] for name in _RUN_COLUMNS}
    verify_material(authenticator, "run-row", values, row["row_mac"])
    try:
        return SchedulerRunState(
            run_id=values["run_id"],
            run_authority_sha256=values["run_authority_sha256"],
            bridge_boot_authority_sha256=values["bridge_boot_authority_sha256"],
            dispatch_not_before_unix_ms=values["dispatch_not_before_unix_ms"],
            dispatch_deadline_unix_ms=values["dispatch_deadline_unix_ms"],
            token_ceiling=values["token_ceiling"],
            expected_call_count=values["expected_call_count"],
            phase=SchedulerRunPhase(values["phase"]),
            reserved_tokens=values["reserved_tokens"],
            consumed_tokens=values["consumed_tokens"],
            burned_tokens=values["burned_tokens"],
            inflight_logical_call_id=values["inflight_logical_call_id"],
            version=values["version"],
        ), values["event_head_sha256"]
    except (TypeError, ValueError, SchedulerContractError) as error:
        raise SchedulerSQLiteError("scheduler_sqlite_run_row_invalid") from error


def call_values(
    state: SchedulerCallState,
    *,
    shard_index: int,
    answer_ciphertext: bytes | None,
) -> dict[str, object]:
    ciphertext_sha256, ciphertext_bytes = ciphertext_material(answer_ciphertext)
    return {
        "run_id": state.run_id,
        "ordinal": state.ordinal,
        "shard_index": shard_index,
        "logical_call_id": state.logical_call_id,
        "stage": state.stage.value,
        "token_ceiling": state.token_ceiling,
        "depends_on_logical_call_id": state.depends_on_logical_call_id,
        "phase": state.phase.value,
        "attempt_count": state.attempt_count,
        "lease_id": state.lease_id,
        "lease_expires_unix_ms": state.lease_expires_unix_ms,
        "request_sha256": state.request_sha256,
        "intent_sha256": state.intent_sha256,
        "terminal_evidence_sha256": state.terminal_evidence_sha256,
        "charged_tokens": state.charged_tokens,
        "answer_ciphertext_sha256": ciphertext_sha256,
        "answer_ciphertext_bytes": ciphertext_bytes,
        "version": state.version,
    }


def call_from_row(
    row: sqlite3.Row,
    authenticator: SchedulerSQLiteAuthenticator,
    *,
    expected: SchedulerLogicalCall,
) -> tuple[SchedulerCallState, bytes | None]:
    ciphertext = row["answer_ciphertext"]
    if ciphertext is not None:
        ciphertext = bytes(ciphertext)
    observed_sha256, observed_bytes = ciphertext_material(ciphertext)
    values = {name: row[name] for name in _CALL_COLUMNS}
    if (
        observed_sha256 != values["answer_ciphertext_sha256"]
        or observed_bytes != values["answer_ciphertext_bytes"]
    ):
        raise SchedulerSQLiteError("scheduler_sqlite_ciphertext_authentication_failed")
    verify_material(authenticator, "call-row", values, row["row_mac"])
    if (
        values["run_id"] != expected.run_id
        or values["ordinal"] != expected.ordinal
        or values["shard_index"] != expected.shard_index
        or values["logical_call_id"] != expected.logical_call_id
        or values["stage"] != expected.stage.value
        or values["token_ceiling"] != expected.token_ceiling
        or values["depends_on_logical_call_id"] != expected.depends_on_logical_call_id
    ):
        raise SchedulerSQLiteError("scheduler_sqlite_call_manifest_drift")
    try:
        state = SchedulerCallState(
            run_id=values["run_id"],
            run_authority_sha256=expected.run_authority_sha256,
            logical_call_id=values["logical_call_id"],
            ordinal=values["ordinal"],
            stage=expected.stage,
            token_ceiling=values["token_ceiling"],
            depends_on_logical_call_id=values["depends_on_logical_call_id"],
            phase=SchedulerCallPhase(values["phase"]),
            attempt_count=values["attempt_count"],
            lease_id=values["lease_id"],
            lease_expires_unix_ms=values["lease_expires_unix_ms"],
            request_sha256=values["request_sha256"],
            intent_sha256=values["intent_sha256"],
            terminal_evidence_sha256=values["terminal_evidence_sha256"],
            charged_tokens=values["charged_tokens"],
            version=values["version"],
        )
    except (TypeError, ValueError, SchedulerContractError) as error:
        raise SchedulerSQLiteError("scheduler_sqlite_call_row_invalid") from error
    if (state.stage.value == "answer") != (
        ciphertext is not None
    ) and state.phase.value == "committed":
        raise SchedulerSQLiteError("scheduler_sqlite_ciphertext_state_invalid")
    if state.phase.value != "committed" and ciphertext is not None:
        raise SchedulerSQLiteError("scheduler_sqlite_ciphertext_state_invalid")
    return state, ciphertext


def shard_values(run_id: str, shard: SchedulerManifestShard) -> dict[str, object]:
    return {
        "run_id": run_id,
        "shard_index": shard.shard_index,
        "shard_sha256": shard.commitment_sha256,
        "start_ordinal": shard.start_ordinal,
        "end_ordinal": shard.end_ordinal,
    }


def event(
    authenticator: SchedulerSQLiteAuthenticator,
    *,
    event_id: int,
    run_id: str,
    logical_call_id: str | None,
    event_kind: str,
    run_version: int,
    call_version: int | None,
    state_sha256: str,
    previous_event_sha256: str,
) -> SchedulerSQLiteEvent:
    provisional = SchedulerSQLiteEvent(
        event_id=event_id,
        run_id=run_id,
        logical_call_id=logical_call_id,
        event_kind=event_kind,
        run_version=run_version,
        call_version=call_version,
        state_sha256=state_sha256,
        previous_event_sha256=previous_event_sha256,
        event_sha256="0" * 64,
    )
    return SchedulerSQLiteEvent(
        **{
            **provisional.material(),
            "event_sha256": authenticator.sign("event", provisional.material()),
        }
    )


def event_from_row(
    row: sqlite3.Row, authenticator: SchedulerSQLiteAuthenticator
) -> SchedulerSQLiteEvent:
    try:
        result = SchedulerSQLiteEvent(
            event_id=row["event_id"],
            run_id=row["run_id"],
            logical_call_id=row["logical_call_id"],
            event_kind=row["event_kind"],
            run_version=row["run_version"],
            call_version=row["call_version"],
            state_sha256=row["state_sha256"],
            previous_event_sha256=row["previous_event_sha256"],
            event_sha256=row["event_sha256"],
        )
    except (TypeError, ValueError, SchedulerContractError) as error:
        raise SchedulerSQLiteError("scheduler_sqlite_event_row_invalid") from error
    if not authenticator.verify("event", result.material(), result.event_sha256):
        raise SchedulerSQLiteError("scheduler_sqlite_event_authentication_failed")
    return result


def state_sha256(
    run: SchedulerRunState,
    *,
    call: SchedulerCallState | None,
    ciphertext_sha256: str | None,
    ciphertext_bytes: int,
) -> str:
    material = {
        "call": None
        if call is None
        else {
            "logical_call_id": call.logical_call_id,
            "phase": call.phase.value,
            "version": call.version,
            "terminal_evidence_sha256": call.terminal_evidence_sha256,
            "charged_tokens": call.charged_tokens,
            "answer_ciphertext_sha256": ciphertext_sha256,
            "answer_ciphertext_bytes": ciphertext_bytes,
        },
        "run": {
            "phase": run.phase.value,
            "version": run.version,
            "reserved_tokens": run.reserved_tokens,
            "consumed_tokens": run.consumed_tokens,
            "burned_tokens": run.burned_tokens,
            "inflight_logical_call_id": run.inflight_logical_call_id,
        },
    }
    return hashlib.sha256(canonical_json(material)).hexdigest()


__all__ = (
    "call_from_row",
    "call_values",
    "event",
    "event_from_row",
    "run_from_row",
    "run_values",
    "shard_values",
    "signed_material",
    "state_sha256",
    "verify_material",
)
