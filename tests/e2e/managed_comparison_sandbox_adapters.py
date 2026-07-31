"""Shared identities and trace state for deterministic managed sandbox ports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

INFINITY_BACKEND = "infinity-context"
MEM0_BACKEND = "mem0"
REQUIRED_MODEL = "gpt-5"
RUNTIME_NONCE = "managed-locomo-sandbox-runtime-nonce"
SANDBOX_SCOPE = "managed-locomo-sandbox-scope"


@dataclass(frozen=True, slots=True)
class SandboxScenario:
    scenario_id: str
    benchmark: str
    scope_id: str
    corpus_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        assert self.scenario_id and self.benchmark in {"locomo", "longmemeval"}
        assert self.scope_id and self.corpus_ids
        assert len(set(self.corpus_ids)) == len(self.corpus_ids)

    @property
    def runtime_nonce(self) -> str:
        return f"{self.scenario_id}-runtime-nonce"

    @property
    def delete_source_id(self) -> str:
        return f"{self.scenario_id}-all-corpora"

    def corpus_scope(self, corpus_id: str) -> str:
        assert corpus_id in self.corpus_ids
        return self.scope_id


LOCOMO_SCENARIO = SandboxScenario(
    "managed-locomo-sandbox",
    "locomo",
    SANDBOX_SCOPE,
    ("sandbox-locomo-1",),
)


def implementation_sha256(role: str, *, scenario_id: str = LOCOMO_SCENARIO.scenario_id) -> str:
    return hashlib.sha256(f"{scenario_id}:{role}".encode()).hexdigest()


@dataclass(slots=True)
class SandboxTrace:
    events: list[str]

    @classmethod
    def create(cls) -> SandboxTrace:
        return cls([])

    def add(self, event: str) -> None:
        self.events.append(event)


@dataclass(frozen=True, slots=True)
class DeleteObservation:
    backend_role: str
    pass_index: int
    deleted_count: int
    remaining_count: int


@dataclass(frozen=True, slots=True)
class StoredSource:
    corpus_id: str
    canonical_bytes: bytes
    source_sha256: str
    text: str


@dataclass(frozen=True, slots=True)
class CleanStateBundle:
    validation: object
    scopes: tuple[object, ...]
    attestation_key: bytes


@dataclass(slots=True)
class SandboxBackendState:
    scenario: SandboxScenario
    stores: dict[tuple[str, str, str], StoredSource]
    delete_observations: dict[tuple[str, int], DeleteObservation]
    clean_state: CleanStateBundle | None
    repopulate_on_second_pass: bool = False

    @classmethod
    def create(
        cls,
        scenario: SandboxScenario = LOCOMO_SCENARIO,
    ) -> SandboxBackendState:
        return cls(scenario, {}, {}, None)

    def require_pristine(self) -> None:
        if self.stores:
            raise RuntimeError("sandbox reset found dirty prestate")

    def seed_dirty(self) -> None:
        corpus_id = self.scenario.corpus_ids[0]
        raw = b'{"dirty":true}'
        self.stores[(INFINITY_BACKEND, self.scenario.corpus_scope(corpus_id), corpus_id)] = (
            StoredSource(corpus_id, raw, hashlib.sha256(raw).hexdigest(), "dirty prestate")
        )

    def ingest(self, backend_role: str, corpus_id: str, record: dict[str, object]) -> StoredSource:
        key = (backend_role, self.scenario.corpus_scope(corpus_id), corpus_id)
        assert key not in self.stores
        ingest_payload = _ingest_payload(record, benchmark=self.scenario.benchmark)
        canonical = json.dumps(
            ingest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        source = StoredSource(
            corpus_id,
            canonical,
            hashlib.sha256(canonical).hexdigest(),
            _source_text(ingest_payload, benchmark=self.scenario.benchmark),
        )
        self.stores[key] = source
        return source

    def source(self, backend_role: str, corpus_id: str) -> StoredSource:
        return self.stores[(backend_role, self.scenario.corpus_scope(corpus_id), corpus_id)]

    def delete(
        self,
        backend_role: str,
        scope_id: str,
        corpus_id: str,
        pass_index: int,
    ) -> DeleteObservation:
        key = (backend_role, scope_id, corpus_id)
        if self.repopulate_on_second_pass and pass_index == 2:
            first = self.delete_observations[(backend_role, 1)]
            assert first.remaining_count == 0
            raw = b'{"unexpected":"repopulation"}'
            self.stores[key] = StoredSource(
                corpus_id,
                raw,
                hashlib.sha256(raw).hexdigest(),
                "unexpected repopulation",
            )
        deleted = int(key in self.stores)
        self.stores.pop(key, None)
        observation = DeleteObservation(
            backend_role,
            pass_index,
            deleted,
            int(key in self.stores),
        )
        self.delete_observations[(backend_role, pass_index)] = observation
        return observation

    def delete_scope(
        self,
        backend_role: str,
        scope_id: str,
        pass_index: int,
    ) -> DeleteObservation:
        assert scope_id == self.scenario.scope_id
        if self.repopulate_on_second_pass and pass_index == 2:
            first = self.delete_observations[(backend_role, 1)]
            assert first.remaining_count == 0
            corpus_id = self.scenario.corpus_ids[0]
            raw = b'{"unexpected":"repopulation"}'
            self.stores[(backend_role, self.scenario.corpus_scope(corpus_id), corpus_id)] = (
                StoredSource(
                    corpus_id,
                    raw,
                    hashlib.sha256(raw).hexdigest(),
                    "unexpected repopulation",
                )
            )
        keys = tuple(
            key
            for key in self.stores
            if key[0] == backend_role and key[1] == scope_id and key[2] in self.scenario.corpus_ids
        )
        for key in keys:
            del self.stores[key]
        remaining = sum(
            key[0] == backend_role and key[1] == scope_id and key[2] in self.scenario.corpus_ids
            for key in self.stores
        )
        observation = DeleteObservation(
            backend_role,
            pass_index,
            len(keys),
            remaining,
        )
        self.delete_observations[(backend_role, pass_index)] = observation
        return observation


def _ingest_payload(record: Mapping[str, object], *, benchmark: str) -> dict[str, object]:
    if benchmark == "locomo":
        conversation = record.get("conversation")
        assert type(conversation) is dict
        return {"conversation": conversation, "sample_id": record.get("sample_id")}
    sessions = record.get("haystack_sessions")
    assert isinstance(sessions, Sequence) and not isinstance(sessions, str | bytes)
    return {
        "haystack_dates": record.get("haystack_dates"),
        "haystack_sessions": sessions,
    }


def _source_text(payload: Mapping[str, object], *, benchmark: str) -> str:
    if benchmark == "locomo":
        conversation = payload["conversation"]
        assert isinstance(conversation, Mapping)
        return "\n".join(
            str(turn["text"])
            for key, turns in sorted(conversation.items())
            if key.startswith("session_")
            and not key.endswith("_date_time")
            and isinstance(turns, Sequence)
            for turn in turns
            if isinstance(turn, Mapping) and isinstance(turn.get("text"), str)
        )
    sessions = payload["haystack_sessions"]
    assert isinstance(sessions, Sequence)
    return "\n".join(
        str(message["content"])
        for session in sessions
        if isinstance(session, Sequence)
        for message in session
        if isinstance(message, Mapping) and isinstance(message.get("content"), str)
    )


__all__ = (
    "INFINITY_BACKEND",
    "LOCOMO_SCENARIO",
    "MEM0_BACKEND",
    "REQUIRED_MODEL",
    "RUNTIME_NONCE",
    "SANDBOX_SCOPE",
    "CleanStateBundle",
    "DeleteObservation",
    "SandboxBackendState",
    "SandboxScenario",
    "SandboxTrace",
    "StoredSource",
    "implementation_sha256",
)
