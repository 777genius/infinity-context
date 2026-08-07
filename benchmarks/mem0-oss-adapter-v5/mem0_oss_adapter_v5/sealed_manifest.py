"""Exact read-only ingestion manifest boundary for adapter v5."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .domain import canonical_sha256

_SCHEMA_V1 = "mem0-oss-adapter-v5.sealed-input.v1"
_SCHEMA_V2 = "mem0-oss-adapter-v5.sealed-input.v2"


@dataclass(frozen=True, slots=True)
class InputUnit:
    sequence: int
    unit_identity_sha256: str
    unit_sha256: str
    source_sha256: str
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
        schema_version = root["schema_version"]
        if type(schema_version) is not str or schema_version not in {_SCHEMA_V1, _SCHEMA_V2}:
            raise ValueError("sealed_input_invalid")
        self.schema_version = schema_version
        self.ingestion_manifest_sha256 = _digest(root["ingestion_manifest_sha256"])
        self.ingestion_root_sha256 = _digest(root["ingestion_root_sha256"])
        self.current_date = _date(root["current_date"])
        unsigned = {key: value for key, value in root.items() if key != "sealed_payload_sha256"}
        if canonical_sha256(unsigned) != _digest(root["sealed_payload_sha256"]):
            raise ValueError("sealed_input_invalid")
        raw_units = root["units"]
        if type(raw_units) is not list or not 1 <= len(raw_units) <= 10_000:
            raise ValueError("sealed_input_invalid")
        self.units = tuple(
            _unit(value, index, schema_version=schema_version)
            for index, value in enumerate(raw_units)
        )
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


def _unit(value: object, sequence: int, *, schema_version: object) -> InputUnit:
    unit_keys = {
        "sequence",
        "unit_identity_sha256",
        "unit_sha256",
        "scope_sha256",
        "corpus_id",
        "source_id",
        "observation_date",
        "source_messages",
    }
    if schema_version == _SCHEMA_V2:
        unit_keys.add("source_sha256")
    raw = _exact(
        value,
        unit_keys,
    )
    messages = raw["source_messages"]
    if raw["sequence"] != sequence or type(messages) is not list or not messages:
        raise ValueError("sealed_input_invalid")
    normalized = []
    for message in messages:
        item = _exact(message, {"role", "content"})
        if item["role"] not in {"user", "assistant"} or type(item["content"]) is not str:
            raise ValueError("sealed_input_invalid")
        if schema_version == _SCHEMA_V2 and (
            not item["content"] or item["content"] != item["content"].strip()
        ):
            raise ValueError("sealed_input_invalid")
        normalized.append({"role": item["role"], "content": item["content"]})
    unit_sha256 = _digest(raw["unit_sha256"])
    source_sha256 = unit_sha256 if schema_version == _SCHEMA_V1 else _digest(raw["source_sha256"])
    scope_sha256 = _digest(raw["scope_sha256"])
    unit_identity_sha256 = _digest(raw["unit_identity_sha256"])
    corpus_id = _text(raw["corpus_id"])
    source_id = _text(raw["source_id"])
    if schema_version == _SCHEMA_V2:
        expected_unit = canonical_sha256({"source_messages": normalized})
        expected_scope = canonical_sha256(
            {
                "corpus_id": corpus_id,
                "source_id": source_id,
                "source_sha256": source_sha256,
                "unit_sha256": expected_unit,
            }
        )
        expected_identity = canonical_sha256(
            {
                "sequence": sequence,
                "scope_sha256": expected_scope,
                "unit_sha256": expected_unit,
            }
        )
        if (
            unit_sha256 != expected_unit
            or scope_sha256 != expected_scope
            or unit_identity_sha256 != expected_identity
        ):
            raise ValueError("sealed_input_invalid")
    return InputUnit(
        sequence=sequence,
        unit_identity_sha256=unit_identity_sha256,
        unit_sha256=unit_sha256,
        source_sha256=source_sha256,
        scope_sha256=scope_sha256,
        corpus_id=corpus_id,
        source_id=source_id,
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
