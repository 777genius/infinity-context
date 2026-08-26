"""Authenticated append-only journal for managed-v5 live recovery."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    managed_benchmark_cleanup_plan_material_sha256,
    validate_managed_benchmark_cleanup_plan,
)

from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    JOURNAL_SCHEMA,
    ManagedV5LiveRecoveryAuthority,
    ManagedV5LiveRecoveryContractError,
    canonical_json,
    canonical_sha256,
    strict_json,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_events import (
    RECOVERY_EVENT_KINDS,
    RecoveryJournalAuthentication,
    RecoveryJournalEvent,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal_codec import (
    parse_recovery_journal_payload,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_storage import (
    ManagedV5RecoveryStorageError,
    acquire_session_lock,
    atomic_write_private_json,
    read_private_file,
    require_private_root,
)

_KEY_DOMAIN = b"infinity-context\0managed-v5-live-recovery-key.v1\0"
_JOURNAL_DOMAIN = b"infinity-context\0managed-v5-live-recovery-journal.v1\0"
_KINDS = RECOVERY_EVENT_KINDS


class ManagedV5LiveRecoveryJournalError(RuntimeError):
    """Stable fail-closed recovery journal error."""


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveRecoveryJournal:
    authority: ManagedV5LiveRecoveryAuthority
    authority_sha256: str
    cleanup_plan: dict[str, object] | None
    cleanup_plan_sha256: str | None
    projection_manifest: dict[str, object] | None
    projection_manifest_sha256: str | None
    events: tuple[RecoveryJournalEvent, ...]
    body_sha256: str
    authentication: RecoveryJournalAuthentication
    schema_version: str = JOURNAL_SCHEMA

    def body_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority.payload(),
            "authority_sha256": self.authority_sha256,
            "cleanup_plan": self.cleanup_plan,
            "cleanup_plan_sha256": self.cleanup_plan_sha256,
            "projection_manifest": self.projection_manifest,
            "projection_manifest_sha256": self.projection_manifest_sha256,
            "events": [event.payload() for event in self.events],
        }

    def payload(self) -> dict[str, object]:
        return {
            **self.body_payload(),
            "body_sha256": self.body_sha256,
            "authentication": self.authentication.payload(),
        }


@final
class RecoveryJournalAuthenticator:
    __slots__ = ("_key", "key_id")

    def __init__(self, *, secret: bytes, run_id_sha256: str) -> None:
        if type(secret) is not bytes or len(secret) < 32 or not _sha(run_id_sha256):
            _fail("managed_v5_live_recovery_key_invalid")
        source = bytearray(secret)
        try:
            derived = hmac.new(
                source, _KEY_DOMAIN + run_id_sha256.encode("ascii"), hashlib.sha256
            ).digest()
            self._key = bytearray(derived)
            self.key_id = "managed-v5-recovery-v1-" + hashlib.sha256(derived).hexdigest()[:16]
        finally:
            _wipe(source)

    def sign(self, body_sha256: str) -> RecoveryJournalAuthentication:
        if not _sha(body_sha256) or not self._key:
            _fail("managed_v5_live_recovery_key_invalid")
        mac = hmac.new(
            self._key, _JOURNAL_DOMAIN + body_sha256.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return RecoveryJournalAuthentication("hmac-sha256", self.key_id, mac)

    def verify(self, body_sha256: str, value: RecoveryJournalAuthentication) -> bool:
        expected = self.sign(body_sha256)
        return (
            value.algorithm == expected.algorithm
            and value.key_id == expected.key_id
            and hmac.compare_digest(value.mac_sha256.encode(), expected.mac_sha256.encode())
        )

    def close(self) -> None:
        _wipe(self._key)
        self._key.clear()


@final
class ManagedV5LiveRecoveryJournalStore:
    __slots__ = ("_path", "_root", "_authenticator", "_lock_fd")

    def __init__(
        self, *, path: Path, state_root: Path, authenticator: RecoveryJournalAuthenticator
    ) -> None:
        self._lock_fd: int | None = None
        try:
            require_private_root(state_root)
        except ManagedV5RecoveryStorageError as error:
            _fail(str(error))
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.parent != state_root
            or path.name in {"", ".", ".."}
            or type(authenticator) is not RecoveryJournalAuthenticator
        ):
            _fail("managed_v5_live_recovery_journal_path_invalid")
        self._path = path
        self._root = state_root
        self._authenticator = authenticator
        try:
            self._lock_fd = acquire_session_lock(state_root, path.name)
        except ManagedV5RecoveryStorageError as error:
            _fail(str(error))

    def close(self) -> None:
        descriptor = self._lock_fd
        if descriptor is not None:
            self._lock_fd = None
            os.close(descriptor)
            self._authenticator.close()

    def __del__(self) -> None:
        if hasattr(self, "_lock_fd"):
            self.close()

    def initialize(
        self,
        *,
        authority: ManagedV5LiveRecoveryAuthority,
        recorded_at: str,
        details: dict[str, object],
    ) -> ManagedV5LiveRecoveryJournal:
        if self._path.exists() or self._path.is_symlink():
            _fail("managed_v5_live_recovery_journal_conflict")
        if details != {"authority_sha256": authority.sha256}:
            _fail("managed_v5_live_recovery_event_invalid")
        event = RecoveryJournalEvent.create(
            sequence=0,
            kind="prepared",
            recorded_at=recorded_at,
            details=details,
            previous_event_sha256=None,
        )
        journal = self._seal(
            authority=authority,
            events=(event,),
            cleanup_plan=None,
            projection_manifest=None,
        )
        self._write(journal.payload())
        return journal

    def load(
        self, *, expected_authority: ManagedV5LiveRecoveryAuthority
    ) -> ManagedV5LiveRecoveryJournal:
        try:
            value = strict_json(self._read())
            journal = _parse_journal(value)
        except ManagedV5LiveRecoveryContractError:
            _fail("managed_v5_live_recovery_journal_invalid")
        if (
            journal.authority_sha256 != expected_authority.sha256
            or journal.authority.payload() != expected_authority.payload()
            or canonical_sha256(journal.body_payload()) != journal.body_sha256
            or not self._authenticator.verify(journal.body_sha256, journal.authentication)
        ):
            _fail("managed_v5_live_recovery_journal_authentication_invalid")
        return journal

    def load_for_recovery(self, *, expected_run_id_sha256: str) -> ManagedV5LiveRecoveryJournal:
        """Authenticate a journal when its embedded authority is the restart input."""

        try:
            value = strict_json(self._read())
            journal = _parse_journal(value)
        except ManagedV5LiveRecoveryContractError:
            _fail("managed_v5_live_recovery_journal_invalid")
        if (
            not _sha(expected_run_id_sha256)
            or journal.authority.run_id_sha256 != expected_run_id_sha256
            or journal.authority_sha256 != journal.authority.sha256
            or canonical_sha256(journal.body_payload()) != journal.body_sha256
            or not self._authenticator.verify(journal.body_sha256, journal.authentication)
        ):
            _fail("managed_v5_live_recovery_journal_authentication_invalid")
        return journal

    def append(
        self,
        *,
        expected_authority: ManagedV5LiveRecoveryAuthority,
        kind: str,
        recorded_at: str,
        details: dict[str, object],
        cleanup_plan: ManagedBenchmarkCleanupPlan | None = None,
        projection_manifest: dict[str, object] | None = None,
    ) -> ManagedV5LiveRecoveryJournal:
        current = self.load(expected_authority=expected_authority)
        last = current.events[-1]
        if kind == last.kind:
            if (
                canonical_json(details) != canonical_json(last.details)
                or (
                    kind == "cleanup_plan_prepared"
                    and (
                        type(cleanup_plan) is not ManagedBenchmarkCleanupPlan
                        or canonical_json(cleanup_plan.value)
                        != canonical_json(current.cleanup_plan)
                        or cleanup_plan.sha256 != current.cleanup_plan_sha256
                    )
                )
                or (
                    kind == "projection_manifest_persisted"
                    and canonical_json(projection_manifest)
                    != canonical_json(current.projection_manifest)
                )
            ):
                _fail("managed_v5_live_recovery_journal_conflict")
            return current
        try:
            sequence = _KINDS.index(kind)
        except ValueError:
            _fail("managed_v5_live_recovery_transition_invalid")
        if sequence <= last.sequence:
            _fail("managed_v5_live_recovery_transition_invalid")
        if _timestamp(recorded_at) < _timestamp(last.recorded_at):
            _fail("managed_v5_live_recovery_transition_invalid")
        plan = current.cleanup_plan
        if kind == "cleanup_plan_prepared":
            if (
                type(cleanup_plan) is not ManagedBenchmarkCleanupPlan
                or details.get("cleanup_plan_sha256") != cleanup_plan.sha256
            ):
                _fail("managed_v5_live_recovery_event_invalid")
            try:
                validated_plan = validate_managed_benchmark_cleanup_plan(
                    cleanup_plan.value,
                    cleanup_plan.sha256,
                    run_id_sha256=expected_authority.run_id_sha256,
                    binding_commitment_sha256=expected_authority.binding_commitment_sha256,
                    infinity_target_identity_sha256=(
                        expected_authority.infinity_target_identity_sha256
                    ),
                    space_slug=expected_authority.space_slug,
                )
                plan = strict_json(canonical_json(validated_plan.value))
            except Exception:
                _fail("managed_v5_live_recovery_cleanup_plan_invalid")
        elif cleanup_plan is not None:
            _fail("managed_v5_live_recovery_cleanup_plan_invalid")
        if kind == "registration_observed":
            prepared_events = [
                event for event in current.events if event.kind == "cleanup_plan_prepared"
            ]
            if len(prepared_events) != 1:
                _fail("managed_v5_live_recovery_transition_invalid")
            prepared = prepared_events[0].details
            if (
                not _details_digest(details, "cleanup_plan_sha256")
                or details["cleanup_plan_sha256"] != prepared["cleanup_plan_sha256"]
                or details.get("cleanup_plan_state") != "sealed"
            ):
                _fail("managed_v5_live_recovery_event_invalid")
        observed_kinds = {event.kind for event in current.events}
        prepared_plan = next(
            (
                event.details["cleanup_plan_sha256"]
                for event in current.events
                if event.kind == "cleanup_plan_prepared"
            ),
            None,
        )
        if (
            kind != "cleanup_plan_prepared"
            and "cleanup_plan_sha256" in details
            and details["cleanup_plan_sha256"] != prepared_plan
        ):
            _fail("managed_v5_live_recovery_event_invalid")
        if kind == "execution_started" and "registration_observed" not in observed_kinds:
            _fail("managed_v5_live_recovery_transition_invalid")
        if kind == "registry_seal_observed" and (
            "projection_manifest_persisted" not in observed_kinds
            or details.get("projection_manifest_sha256") != current.projection_manifest_sha256
        ):
            _fail("managed_v5_live_recovery_transition_invalid")
        if kind == "canonical_terminal_observed" and not {
            "cleanup_observed",
            "mem0_terminal_observed",
        }.issubset(observed_kinds):
            _fail("managed_v5_live_recovery_transition_invalid")
        manifest = current.projection_manifest
        if kind == "projection_manifest_persisted":
            if type(projection_manifest) is not dict:
                _fail("managed_v5_live_recovery_projection_manifest_invalid")
            manifest = projection_manifest
            if details.get("projection_manifest_sha256") != canonical_sha256(manifest):
                _fail("managed_v5_live_recovery_projection_manifest_invalid")
        elif projection_manifest is not None:
            _fail("managed_v5_live_recovery_projection_manifest_invalid")
        event = RecoveryJournalEvent.create(
            sequence=sequence,
            kind=kind,
            recorded_at=recorded_at,
            details=details,
            previous_event_sha256=last.event_sha256,
        )
        updated = self._seal(
            authority=expected_authority,
            events=(*current.events, event),
            cleanup_plan=plan,
            projection_manifest=manifest,
        )
        self._write(updated.payload())
        return updated

    def _seal(
        self,
        *,
        authority: ManagedV5LiveRecoveryAuthority,
        events: tuple[RecoveryJournalEvent, ...],
        cleanup_plan: dict[str, object] | None,
        projection_manifest: dict[str, object] | None,
    ) -> ManagedV5LiveRecoveryJournal:
        plan_sha = (
            None
            if cleanup_plan is None
            else managed_benchmark_cleanup_plan_material_sha256(cleanup_plan)
        )
        manifest_sha = (
            None if projection_manifest is None else canonical_sha256(projection_manifest)
        )
        body = {
            "schema_version": JOURNAL_SCHEMA,
            "authority": authority.payload(),
            "authority_sha256": authority.sha256,
            "cleanup_plan": cleanup_plan,
            "cleanup_plan_sha256": plan_sha,
            "projection_manifest": projection_manifest,
            "projection_manifest_sha256": manifest_sha,
            "events": [event.payload() for event in events],
        }
        body_sha = canonical_sha256(body)
        return ManagedV5LiveRecoveryJournal(
            authority,
            authority.sha256,
            cleanup_plan,
            plan_sha,
            projection_manifest,
            manifest_sha,
            events,
            body_sha,
            self._authenticator.sign(body_sha),
        )

    def _read(self) -> bytes:
        try:
            return read_private_file(self._path)
        except ManagedV5RecoveryStorageError as error:
            _fail(str(error))

    def _write(self, payload: dict[str, object]) -> None:
        try:
            atomic_write_private_json(self._root, self._path, payload)
        except ManagedV5RecoveryStorageError as error:
            _fail(str(error))


def _parse_journal(value: object) -> ManagedV5LiveRecoveryJournal:
    return ManagedV5LiveRecoveryJournal(*parse_recovery_journal_payload(value))


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= frozenset("0123456789abcdef")


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError):
        _fail("managed_v5_live_recovery_event_invalid")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _fail(code: str) -> None:
    raise ManagedV5LiveRecoveryJournalError(code)


__all__ = (
    "ManagedV5LiveRecoveryJournal",
    "ManagedV5LiveRecoveryJournalError",
    "ManagedV5LiveRecoveryJournalStore",
    "RecoveryJournalAuthenticator",
    "RecoveryJournalEvent",
)


def _details_digest(details: object, key: str) -> bool:
    return type(details) is dict and _sha(details.get(key))
