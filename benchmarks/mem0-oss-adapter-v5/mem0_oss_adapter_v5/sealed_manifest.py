"""Exact read-only ingestion manifest boundary for adapter v5."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .domain import canonical_sha256

_SCHEMA = "mem0-oss-adapter-v5.sealed-input.v1"


@dataclass(frozen=True, slots=True)
class InputUnit:
    sequence: int
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    corpus_id: str
    source_id: str
    observation_date: str
    source_messages: tuple[dict[str, str], ...]


class SealedInputManifest:
    """One immutable source lookup; HTTP callers submit hashes only."""

    def __init__(self, path: Path) -> None:
        payload = _read(path)
        root = _exact(
            payload,
            {
                "schema_version",
                "ingestion_manifest_sha256",
                "ingestion_root_sha256",
                "current_date",
                "units",
                "sealed_payload_sha256",
            },
        )
        if root["schema_version"] != _SCHEMA:
            raise ValueError("sealed_input_invalid")
        self.ingestion_manifest_sha256 = _digest(root["ingestion_manifest_sha256"])
        self.ingestion_root_sha256 = _digest(root["ingestion_root_sha256"])
        self.current_date = _date(root["current_date"])
        unsigned = {key: value for key, value in root.items() if key != "sealed_payload_sha256"}
        if canonical_sha256(unsigned) != _digest(root["sealed_payload_sha256"]):
            raise ValueError("sealed_input_invalid")
        raw_units = root["units"]
        if type(raw_units) is not list or not 1 <= len(raw_units) <= 10_000:
            raise ValueError("sealed_input_invalid")
        self.units = tuple(_unit(value, index) for index, value in enumerate(raw_units))
        if len({unit.unit_identity_sha256 for unit in self.units}) != len(self.units):
            raise ValueError("sealed_input_invalid")
        public = [
            {
                "unit_identity_sha256": unit.unit_identity_sha256,
                "unit_sha256": unit.unit_sha256,
                "scope_sha256": unit.scope_sha256,
            }
            for unit in self.units
        ]
        if canonical_sha256({"units": public}) != self.ingestion_root_sha256:
            raise ValueError("sealed_input_invalid")
        self._by_identity = {unit.unit_identity_sha256: unit for unit in self.units}

    def get(self, identity: str) -> InputUnit:
        try:
            return self._by_identity[identity]
        except KeyError:
            raise KeyError("operation_not_found") from None


def _unit(value: object, sequence: int) -> InputUnit:
    raw = _exact(
        value,
        {
            "sequence",
            "unit_identity_sha256",
            "unit_sha256",
            "scope_sha256",
            "corpus_id",
            "source_id",
            "observation_date",
            "source_messages",
        },
    )
    messages = raw["source_messages"]
    if raw["sequence"] != sequence or type(messages) is not list or not messages:
        raise ValueError("sealed_input_invalid")
    normalized = []
    for message in messages:
        item = _exact(message, {"role", "content"})
        if item["role"] not in {"user", "assistant"} or type(item["content"]) is not str:
            raise ValueError("sealed_input_invalid")
        normalized.append({"role": item["role"], "content": item["content"]})
    return InputUnit(
        sequence=sequence,
        unit_identity_sha256=_digest(raw["unit_identity_sha256"]),
        unit_sha256=_digest(raw["unit_sha256"]),
        scope_sha256=_digest(raw["scope_sha256"]),
        corpus_id=_text(raw["corpus_id"]),
        source_id=_text(raw["source_id"]),
        observation_date=_date(raw["observation_date"]),
        source_messages=tuple(normalized),
    )


def _read(path: Path) -> object:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("sealed_input_invalid")
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO | stat.S_IWUSR):
        raise ValueError("sealed_input_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= 32 * 1024 * 1024:
        raise ValueError("sealed_input_invalid")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("sealed_input_invalid") from None


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("sealed_input_invalid")
    return value


def _digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("sealed_input_invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise ValueError("sealed_input_invalid")
    return value


def _date(value: object) -> str:
    if type(value) is not str or len(value) != 10:
        raise ValueError("sealed_input_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("sealed_input_invalid") from None
    if parsed.isoformat() != value:
        raise ValueError("sealed_input_invalid")
    return value


__all__ = ("InputUnit", "SealedInputManifest")
