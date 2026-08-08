"""Deferred one-shot Infinity clean-state evidence source."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import NoReturn, final

from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    FullExecutionCleanStateEvidence,
    FullExecutionCleanStateEvidenceDescriptor,
    inspect_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256

_TOKEN = object()
_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedInfinityCleanStateSourceError(RuntimeError):
    """Stable secret-free deferred-source failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedInfinityCleanStateEvidencePublisher:
    """Opaque producer authority paired with exactly one evidence source."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed_infinity_clean_state_publisher_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is final")

    def __repr__(self) -> str:
        return "ManagedInfinityCleanStateEvidencePublisher(<opaque>)"

    def __copy__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidencePublisher is nonserializable")


@final
class ManagedInfinityCleanStateEvidenceSource:
    """Opaque source fulfilled after reset/ingest and consumed exactly once."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed_infinity_clean_state_source_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is final")

    def __repr__(self) -> str:
        return "ManagedInfinityCleanStateEvidenceSource(<opaque>)"

    def __copy__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("ManagedInfinityCleanStateEvidenceSource is nonserializable")


@dataclass(frozen=True, slots=True)
class _SourceState:
    publisher: ManagedInfinityCleanStateEvidencePublisher
    binding: ManagedRunnerCompositionBinding
    binding_snapshot: tuple[object, ...]
    target_pairs: tuple[tuple[str, str], ...]
    corpus_ids: tuple[str, ...]
    producer_implementation_sha256: str
    phase: str
    next_ingest: int
    evidence: FullExecutionCleanStateEvidence | None
    descriptor: FullExecutionCleanStateEvidenceDescriptor | None
    integrity_mac: bytes


_SOURCES: weakref.WeakKeyDictionary[ManagedInfinityCleanStateEvidenceSource, _SourceState]


@dataclass(frozen=True, slots=True)
class _PublisherState:
    source: ManagedInfinityCleanStateEvidenceSource
    binding: ManagedRunnerCompositionBinding
    producer_implementation_sha256: str
    phase: str
    integrity_mac: bytes


_PUBLISHERS: weakref.WeakKeyDictionary[
    ManagedInfinityCleanStateEvidencePublisher,
    _PublisherState,
]


def create_managed_infinity_clean_state_evidence_channel(
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
    producer_implementation_sha256: str,
) -> tuple[
    ManagedInfinityCleanStateEvidencePublisher,
    ManagedInfinityCleanStateEvidenceSource,
]:
    """Create paired producer/consumer authorities for one exact composition."""

    snapshot, targets = _validate_binding(composition_binding)
    corpora = _validate_corpus_ids(corpus_ids)
    implementation = _validate_sha256(producer_implementation_sha256)
    publisher = ManagedInfinityCleanStateEvidencePublisher(_token=_TOKEN)
    source = ManagedInfinityCleanStateEvidenceSource(_token=_TOKEN)
    _store(
        source,
        _SourceState(
            publisher,
            composition_binding,
            snapshot,
            targets,
            corpora,
            implementation,
            "issued",
            0,
            None,
            None,
            b"",
        ),
    )
    _store_publisher(
        publisher,
        _PublisherState(source, composition_binding, implementation, "live", b""),
    )
    return publisher, source


def authenticate_managed_infinity_clean_state_evidence_source(
    source: object,
    *,
    composition_binding: ManagedRunnerCompositionBinding,
) -> str:
    """Authenticate the source owner and return its bound producer hash."""

    with _LOCK:
        state = _state_locked(source)
        _require_binding(state, composition_binding)
        if state.phase not in {"issued", "ready"}:
            _fail("managed_infinity_clean_state_source_replay")
        return state.producer_implementation_sha256


def record_managed_infinity_clean_state_reset_evidence(
    publisher: object,
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
    producer_implementation_sha256: str,
    evidence: FullExecutionCleanStateEvidence,
) -> None:
    """Record exact reset evidence before any accepted Infinity ingest."""

    with _LOCK:
        publisher_state = _publisher_state_locked(publisher)
        source = publisher_state.source
        state = _state_locked(source)
        try:
            _require_publisher_link(publisher, publisher_state, state)
            _require_binding(state, composition_binding)
            corpora = _validate_corpus_ids(corpus_ids)
            implementation = _validate_sha256(producer_implementation_sha256)
            descriptor = inspect_full_execution_clean_state_evidence(evidence)
            valid = (
                publisher_state.phase == "live"
                and state.phase == "issued"
                and corpora == state.corpus_ids
                and hmac.compare_digest(implementation, state.producer_implementation_sha256)
                and _descriptor_matches(descriptor, state.binding, corpora)
            )
        except ManagedInfinityCleanStateSourceError:
            raise
        except Exception:
            valid = False
        if not valid:
            _terminalize_channel_locked(publisher, publisher_state, source, state)
            _fail("managed_infinity_clean_state_source_reset_invalid")
        _store_locked(
            source,
            replace(
                state,
                phase="reset",
                evidence=evidence,
                descriptor=descriptor,
                integrity_mac=b"",
            ),
        )


def record_managed_infinity_clean_state_ingest(
    publisher: object,
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    target_identity_sha256: str,
    corpus_id: str,
    producer_implementation_sha256: str,
) -> None:
    """Advance exact ordered Infinity ingest coverage and ready the source."""

    with _LOCK:
        publisher_state = _publisher_state_locked(publisher)
        source = publisher_state.source
        state = _state_locked(source)
        try:
            _require_publisher_link(publisher, publisher_state, state)
            _require_binding(state, composition_binding)
            implementation = _validate_sha256(producer_implementation_sha256)
            infinity_targets = tuple(
                target for role, target in state.target_pairs if role == "infinity-context"
            )
            valid = (
                publisher_state.phase == "live"
                and state.phase in {"reset", "ingesting"}
                and state.evidence is not None
                and len(infinity_targets) == 1
                and target_identity_sha256 == infinity_targets[0]
                and state.next_ingest < len(state.corpus_ids)
                and corpus_id == state.corpus_ids[state.next_ingest]
                and hmac.compare_digest(
                    implementation,
                    state.producer_implementation_sha256,
                )
            )
        except ManagedInfinityCleanStateSourceError:
            raise
        except Exception:
            valid = False
        if not valid:
            _terminalize_channel_locked(publisher, publisher_state, source, state)
            _fail("managed_infinity_clean_state_source_ingest_invalid")
        next_ingest = state.next_ingest + 1
        ready = next_ingest == len(state.corpus_ids)
        _store_locked(
            source,
            replace(
                state,
                phase="ready" if ready else "ingesting",
                next_ingest=next_ingest,
                integrity_mac=b"",
            ),
        )
        if ready:
            _store_publisher_locked(
                publisher,
                replace(publisher_state, phase="fulfilled", integrity_mac=b""),
            )


def consume_managed_infinity_clean_state_evidence_source(
    source: object,
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
    producer_implementation_sha256: str,
) -> FullExecutionCleanStateEvidence:
    """Atomically burn and return one authenticated ready Infinity claim."""

    with _LOCK:
        state = _state_locked(source)
        try:
            publisher_state = _publisher_state_locked(state.publisher)
            _require_publisher_link(state.publisher, publisher_state, state)
            _require_binding(state, composition_binding)
            corpora = _validate_corpus_ids(corpus_ids)
            implementation = _validate_sha256(producer_implementation_sha256)
            descriptor = inspect_full_execution_clean_state_evidence(state.evidence)
            valid = (
                state.phase == "ready"
                and publisher_state.phase == "fulfilled"
                and state.next_ingest == len(state.corpus_ids)
                and state.evidence is not None
                and state.descriptor == descriptor
                and corpora == state.corpus_ids
                and hmac.compare_digest(implementation, state.producer_implementation_sha256)
                and _descriptor_matches(descriptor, state.binding, corpora)
            )
        except ManagedInfinityCleanStateSourceError:
            raise
        except Exception:
            valid = False
        if not valid:
            code = (
                "managed_infinity_clean_state_source_not_ready"
                if state.phase in {"issued", "reset", "ingesting"}
                else "managed_infinity_clean_state_source_replay"
                if state.phase == "consumed"
                else "managed_infinity_clean_state_source_binding_invalid"
            )
            _fail(code)
        evidence = state.evidence
        assert evidence is not None
        _store_locked(
            source,
            replace(
                state,
                phase="consumed",
                evidence=None,
                descriptor=None,
                integrity_mac=b"",
            ),
        )
        return evidence


def _descriptor_matches(
    descriptor: FullExecutionCleanStateEvidenceDescriptor,
    binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
) -> bool:
    return (
        descriptor.variant == "infinity_di"
        and descriptor.backend_roles == ("infinity-context",)
        and descriptor.run_id_sha256 == hashlib.sha256(binding.run_id.encode()).hexdigest()
        and descriptor.admission_commitment_sha256 is None
        and descriptor.authority_commitment_sha256 is None
        and tuple(item[0] for item in descriptor.corpus_scopes)
        == tuple(canonical_sha256({"corpus_id": item}) for item in corpus_ids)
    )


def _validate_binding(
    value: object,
) -> tuple[tuple[object, ...], tuple[tuple[str, str], ...]]:
    if type(value) is not ManagedRunnerCompositionBinding:
        _fail("managed_infinity_clean_state_source_binding_invalid")
    try:
        targets = tuple(
            (item.backend_role, item.target_identity_sha256) for item in value.backend_targets
        )
        snapshot = (
            value.run_id,
            value.profile_id,
            value.binding_commitment_sha256,
            value.backend_targets,
            value.deadline,
        )
    except Exception:
        _fail("managed_infinity_clean_state_source_binding_invalid")
    if not targets or len(set(targets)) != len(targets):
        _fail("managed_infinity_clean_state_source_binding_invalid")
    return snapshot, targets


def _require_binding(state: _SourceState, value: object) -> None:
    snapshot, targets = _validate_binding(value)
    if (
        value is not state.binding
        or snapshot != state.binding_snapshot
        or targets != state.target_pairs
    ):
        _fail("managed_infinity_clean_state_source_binding_invalid")


def _validate_corpus_ids(value: object) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not str or not item or item != item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        _fail("managed_infinity_clean_state_source_corpora_invalid")
    return value


def _validate_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail("managed_infinity_clean_state_source_implementation_invalid")
    return value


def _state_locked(value: object) -> _SourceState:
    if type(value) is not ManagedInfinityCleanStateEvidenceSource:
        _fail("managed_infinity_clean_state_source_invalid")
    state = _SOURCES.get(value)
    if state is None:
        _fail("managed_infinity_clean_state_source_unknown")
    expected = _mac(value, replace(state, integrity_mac=b""))
    if not hmac.compare_digest(state.integrity_mac, expected):
        _fail("managed_infinity_clean_state_source_changed")
    return state


def _publisher_state_locked(value: object) -> _PublisherState:
    if type(value) is not ManagedInfinityCleanStateEvidencePublisher:
        _fail("managed_infinity_clean_state_publisher_invalid")
    state = _PUBLISHERS.get(value)
    if state is None:
        _fail("managed_infinity_clean_state_publisher_unknown")
    if not hmac.compare_digest(
        state.integrity_mac,
        _publisher_mac(value, replace(state, integrity_mac=b"")),
    ):
        _fail("managed_infinity_clean_state_publisher_changed")
    return state


def _require_publisher_link(
    publisher: object,
    publisher_state: _PublisherState,
    source_state: _SourceState,
) -> None:
    if (
        publisher is not source_state.publisher
        or publisher_state.source not in _SOURCES
        or publisher_state.binding is not source_state.binding
        or not hmac.compare_digest(
            publisher_state.producer_implementation_sha256,
            source_state.producer_implementation_sha256,
        )
    ):
        _fail("managed_infinity_clean_state_channel_changed")


def _store(source: ManagedInfinityCleanStateEvidenceSource, state: _SourceState) -> None:
    with _LOCK:
        _store_locked(source, state)


def _store_publisher(
    publisher: ManagedInfinityCleanStateEvidencePublisher,
    state: _PublisherState,
) -> None:
    with _LOCK:
        _store_publisher_locked(publisher, state)


def _store_locked(
    source: ManagedInfinityCleanStateEvidenceSource,
    state: _SourceState,
) -> None:
    _SOURCES[source] = replace(
        state,
        integrity_mac=_mac(source, replace(state, integrity_mac=b"")),
    )


def _store_publisher_locked(
    publisher: ManagedInfinityCleanStateEvidencePublisher,
    state: _PublisherState,
) -> None:
    _PUBLISHERS[publisher] = replace(
        state,
        integrity_mac=_publisher_mac(publisher, replace(state, integrity_mac=b"")),
    )


def _terminalize_channel_locked(
    publisher: ManagedInfinityCleanStateEvidencePublisher,
    publisher_state: _PublisherState,
    source: ManagedInfinityCleanStateEvidenceSource,
    source_state: _SourceState,
) -> None:
    _store_locked(
        source,
        replace(
            source_state,
            phase="terminal",
            evidence=None,
            descriptor=None,
            integrity_mac=b"",
        ),
    )
    _store_publisher_locked(
        publisher,
        replace(publisher_state, phase="terminal", integrity_mac=b""),
    )


def _mac(source: ManagedInfinityCleanStateEvidenceSource, state: _SourceState) -> bytes:
    payload = {
        "source_identity": id(source),
        "publisher_identity": id(state.publisher),
        "binding_identity": id(state.binding),
        "binding_snapshot": tuple(str(item) for item in state.binding_snapshot[:-1]),
        "deadline_identity": id(state.binding_snapshot[-1]),
        "targets": state.target_pairs,
        "corpora": state.corpus_ids,
        "implementation": state.producer_implementation_sha256,
        "phase": state.phase,
        "next_ingest": state.next_ingest,
        "evidence_identity": None if state.evidence is None else id(state.evidence),
        "evidence_commitment": (
            None if state.descriptor is None else state.descriptor.evidence_commitment_sha256
        ),
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


def _publisher_mac(
    publisher: ManagedInfinityCleanStateEvidencePublisher,
    state: _PublisherState,
) -> bytes:
    payload = {
        "publisher_identity": id(publisher),
        "source_identity": id(state.source),
        "binding_identity": id(state.binding),
        "implementation": state.producer_implementation_sha256,
        "phase": state.phase,
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


def _fail(code: str) -> NoReturn:
    raise ManagedInfinityCleanStateSourceError(code)


_SOURCES = weakref.WeakKeyDictionary()
_PUBLISHERS = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedInfinityCleanStateEvidencePublisher",
    "ManagedInfinityCleanStateEvidenceSource",
    "ManagedInfinityCleanStateSourceError",
    "authenticate_managed_infinity_clean_state_evidence_source",
    "consume_managed_infinity_clean_state_evidence_source",
    "create_managed_infinity_clean_state_evidence_channel",
    "record_managed_infinity_clean_state_ingest",
    "record_managed_infinity_clean_state_reset_evidence",
)
