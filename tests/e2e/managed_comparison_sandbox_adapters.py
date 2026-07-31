"""Shared identities and trace state for deterministic managed sandbox ports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

INFINITY_BACKEND = "infinity-context"
MEM0_BACKEND = "mem0"
REQUIRED_MODEL = "gpt-5"
RUNTIME_NONCE = "managed-locomo-sandbox-runtime-nonce"
SANDBOX_SCOPE = "managed-locomo-sandbox-scope"


def implementation_sha256(role: str) -> str:
    return hashlib.sha256(f"managed-locomo-sandbox:{role}".encode()).hexdigest()


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
    stores: dict[tuple[str, str, str], StoredSource]
    delete_observations: dict[tuple[str, int], DeleteObservation]
    clean_state: CleanStateBundle | None
    repopulate_on_second_pass: bool = False

    @classmethod
    def create(cls) -> SandboxBackendState:
        return cls({}, {}, None)

    def require_pristine(self) -> None:
        if self.stores:
            raise RuntimeError("sandbox reset found dirty prestate")

    def seed_dirty(self) -> None:
        raw = b'{"dirty":true}'
        self.stores[(INFINITY_BACKEND, SANDBOX_SCOPE, "dirty-corpus")] = StoredSource(
            "dirty-corpus",
            raw,
            hashlib.sha256(raw).hexdigest(),
            "dirty prestate",
        )

    def ingest(self, backend_role: str, corpus_id: str, record: dict[str, object]) -> StoredSource:
        key = (backend_role, SANDBOX_SCOPE, corpus_id)
        assert key not in self.stores
        canonical = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        conversation = record["conversation"]
        assert type(conversation) is dict
        turns = conversation["session_1"]
        assert type(turns) is list and len(turns) == 1 and type(turns[0]) is dict
        source = StoredSource(
            corpus_id,
            canonical,
            hashlib.sha256(canonical).hexdigest(),
            str(turns[0]["text"]),
        )
        self.stores[key] = source
        return source

    def source(self, backend_role: str, corpus_id: str) -> StoredSource:
        return self.stores[(backend_role, SANDBOX_SCOPE, corpus_id)]

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


__all__ = (
    "INFINITY_BACKEND",
    "MEM0_BACKEND",
    "REQUIRED_MODEL",
    "RUNTIME_NONCE",
    "SANDBOX_SCOPE",
    "CleanStateBundle",
    "DeleteObservation",
    "SandboxBackendState",
    "SandboxTrace",
    "StoredSource",
    "implementation_sha256",
)
