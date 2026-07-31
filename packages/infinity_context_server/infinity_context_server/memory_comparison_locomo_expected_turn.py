"""Sealed expected official LoCoMo turn projections and identity validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import weakref
from datetime import UTC, datetime
from threading import RLock
from typing import NamedTuple

from infinity_context_server.memory_comparison_benchmark_identity import (
    valid_benchmark_run_id,
)

EXPECTED_OFFICIAL_LOCOMO_TURN_SCHEMA_VERSION = "locomo-expected-official-turn.v2"
_MAX_ID_LENGTH = 512
_MAX_CONTENT_LENGTH = 1_000_000
_MIN_PLAUSIBLE_TIMESTAMP = 946_684_800
_MAX_PLAUSIBLE_TIMESTAMP = 4_102_444_800
_SOURCE_ID_MAX_LENGTH = 160
_CONSTRUCTION_SEAL = object()
_STATE_LOCK = RLock()
_INTEGRITY_STATE: weakref.WeakKeyDictionary[object, object] = weakref.WeakKeyDictionary()
_SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$", re.ASCII)
_SAFE_SOURCE_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$", re.ASCII)
_LOCOMO_SOURCE_EXTERNAL_ID_RE = re.compile(
    r"^locomo:[A-Za-z0-9][A-Za-z0-9._/-]*:session_[1-9][0-9]*:D[1-9][0-9]*:[1-9][0-9]*:turn$",
    re.ASCII,
)
_SESSION_KEY_RE = re.compile(r"^session_[1-9][0-9]*$", re.ASCII)
_DIA_ID_RE = re.compile(r"^D[1-9][0-9]*:[1-9][0-9]*$", re.ASCII)
_SPEAKER_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9.\x27-]*(?: [A-Za-z0-9][A-Za-z0-9.\x27-]*)*$",
    re.ASCII,
)
_SESSION_DATE_RE = re.compile(
    r"^(?:[1-9]|1[0-2]):[0-5][0-9] (?:am|pm) on "
    r"(?:[1-9]|[12][0-9]|3[01]) "
    r"(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec), [0-9]{4}$",
    re.ASCII,
)
_TRIGGER_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*:qa:[1-9][0-9]*$", re.ASCII)
_EXPECTED_KEYS = {
    "schema_version",
    "run_id",
    "corpus_key",
    "source_external_id",
    "source_id",
    "session_key",
    "dia_id",
    "speaker",
    "session_date",
    "trigger_case_id",
    "role",
    "content",
    "timestamp",
}
_PROJECTION_KEYS = _EXPECTED_KEYS - {"schema_version"}


class _IntegritySnapshot(NamedTuple):
    canonical_bytes: bytes
    commitment: bytes


class ExpectedOfficialLocomoTurn:
    """Sealed loader projection; authenticity requires a later dataset proof."""

    __slots__ = ("_canonical_bytes", "_seal", "__weakref__")

    def __init__(self, *, canonical_bytes: bytes, _construction_seal: object) -> None:
        if _construction_seal is not _CONSTRUCTION_SEAL:
            raise TypeError("use ExpectedOfficialLocomoTurn.create")
        _parse_expected_turn_bytes(canonical_bytes)
        self._canonical_bytes = canonical_bytes
        self._seal = _CONSTRUCTION_SEAL
        commitment = _integrity_commitment(canonical_bytes)
        with _STATE_LOCK:
            _INTEGRITY_STATE[self] = _IntegritySnapshot(canonical_bytes, commitment)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ExpectedOfficialLocomoTurn is sealed")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        corpus_key: str,
        source_external_id: str,
        source_id: str,
        session_key: str,
        dia_id: str,
        speaker: str,
        session_date: str,
        trigger_case_id: str,
        role: str,
        content: str,
        timestamp: int,
    ) -> ExpectedOfficialLocomoTurn:
        del cls
        payload = {
            "schema_version": EXPECTED_OFFICIAL_LOCOMO_TURN_SCHEMA_VERSION,
            "run_id": run_id,
            "corpus_key": corpus_key,
            "source_external_id": source_external_id,
            "source_id": source_id,
            "session_key": session_key,
            "dia_id": dia_id,
            "speaker": speaker,
            "session_date": session_date,
            "trigger_case_id": trigger_case_id,
            "role": role,
            "content": content,
            "timestamp": timestamp,
        }
        canonical_bytes = _canonical_json_bytes(payload)
        _parse_expected_turn_bytes(canonical_bytes)
        return ExpectedOfficialLocomoTurn(
            canonical_bytes=canonical_bytes,
            _construction_seal=_CONSTRUCTION_SEAL,
        )

    def __repr__(self) -> str:
        return "ExpectedOfficialLocomoTurn(<sealed>)"

    def __getstate__(self) -> object:
        raise TypeError("expected official turns must never be serialized as admission")


def validate_official_locomo_turn_projection(value: object) -> dict[str, object]:
    """Validate the exact identity/content/timestamp projection emitted by the loader."""

    if type(value) is not dict or set(value) != _PROJECTION_KEYS:
        raise ValueError("official LoCoMo turn projection fields are not exact")
    if not valid_benchmark_run_id(value["run_id"]):
        raise ValueError("run_id must match the adapter SafeIdentifier contract")
    if not _bounded_id(value["corpus_key"]):
        raise ValueError("corpus_key must be a bounded canonical string")
    source_external_id = value["source_external_id"]
    source_id = value["source_id"]
    if type(source_external_id) is not str or not _SAFE_SOURCE_EXTERNAL_ID_RE.fullmatch(
        source_external_id
    ):
        raise ValueError("source_external_id must match the exact adapter-safe ASCII pattern")
    if not _LOCOMO_SOURCE_EXTERNAL_ID_RE.fullmatch(source_external_id):
        raise ValueError("source_external_id must match the exact official loader shape")
    if type(source_id) is not str or not _SAFE_SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError("source_id must match the exact adapter SafeSourceIdentifier pattern")
    if source_id != canonical_locomo_source_id(source_external_id):
        raise ValueError("source_id is not the canonical source_external_id mapping")
    session_key = value["session_key"]
    dia_id = value["dia_id"]
    if type(session_key) is not str or not _SESSION_KEY_RE.fullmatch(session_key):
        raise ValueError("session_key must match the official loader pattern")
    if type(dia_id) is not str or not _DIA_ID_RE.fullmatch(dia_id):
        raise ValueError("dia_id must match the official loader pattern")
    if not source_external_id.endswith(f":{session_key}:{dia_id}:turn"):
        raise ValueError("source identity conflicts with session_key or dia_id")
    speaker = value["speaker"]
    if type(speaker) is not str or len(speaker) > 80 or not _SPEAKER_RE.fullmatch(speaker):
        raise ValueError("speaker must match the bounded canonical ASCII loader format")
    session_date = value["session_date"]
    session_epoch = _session_date_epoch(session_date)
    if session_epoch is None or session_epoch != value["timestamp"]:
        raise ValueError("session_date must be canonical and equal the loader timestamp")
    trigger_case_id = value["trigger_case_id"]
    if (
        type(trigger_case_id) is not str
        or not _SAFE_SOURCE_EXTERNAL_ID_RE.fullmatch(trigger_case_id)
        or not _TRIGGER_CASE_ID_RE.fullmatch(trigger_case_id)
    ):
        raise ValueError("trigger_case_id must match the exact official loader shape")
    sample_id = source_external_id.split(":", 2)[1]
    if not trigger_case_id.startswith(f"{sample_id}:qa:"):
        raise ValueError("trigger_case_id must belong to the source sample")
    if type(value["role"]) is not str or value["role"] not in {"user", "assistant"}:
        raise ValueError("role must be exactly user or assistant")
    content = value["content"]
    if type(content) is not str or not content.strip() or len(content) > _MAX_CONTENT_LENGTH:
        raise ValueError("content must be bounded and nonblank")
    if not _plausible_epoch_timestamp(value["timestamp"]):
        raise ValueError("timestamp must be a positive plausible exact epoch")
    return value


def trusted_expected_official_locomo_turn(
    value: object,
) -> tuple[dict[str, object], str] | None:
    """Return the exact projection and digest only for an intact sealed instance."""

    if type(value) is not ExpectedOfficialLocomoTurn:
        return None
    with _STATE_LOCK:
        state = _INTEGRITY_STATE.get(value)
    if type(state) is not _IntegritySnapshot:
        return None
    try:
        canonical_bytes = value._canonical_bytes
        seal = value._seal
    except AttributeError:
        return None
    if seal is not _CONSTRUCTION_SEAL or type(canonical_bytes) is not bytes:
        return None
    commitment = _integrity_commitment(canonical_bytes)
    if not (
        hmac.compare_digest(canonical_bytes, state.canonical_bytes)
        and hmac.compare_digest(commitment, state.commitment)
    ):
        return None
    parsed = _parse_expected_turn_bytes(canonical_bytes)
    return (
        {key: parsed[key] for key in _PROJECTION_KEYS},
        hashlib.sha256(canonical_bytes).hexdigest(),
    )


def canonical_locomo_source_id(source_external_id: str) -> str:
    if len(source_external_id) <= _SOURCE_ID_MAX_LENGTH:
        return source_external_id
    digest = hashlib.sha256(source_external_id.encode()).hexdigest()[:16]
    prefix = source_external_id[: _SOURCE_ID_MAX_LENGTH - len(digest) - 1]
    return f"{prefix}:{digest}"


def _parse_expected_turn_bytes(payload: object) -> dict[str, object]:
    if type(payload) is not bytes or not payload:
        raise ValueError("expected turn projection must be non-empty exact bytes")
    try:
        parsed = json.loads(payload, object_pairs_hook=_exact_json_object_pairs)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ValueError("expected turn projection is malformed") from error
    if type(parsed) is not dict or set(parsed) != _EXPECTED_KEYS:
        raise ValueError("expected turn projection fields are not exact")
    if _canonical_json_bytes(parsed) != payload:
        raise ValueError("expected turn projection bytes are not canonical")
    if parsed["schema_version"] != EXPECTED_OFFICIAL_LOCOMO_TURN_SCHEMA_VERSION:
        raise ValueError("expected turn projection schema is unsupported")
    validate_official_locomo_turn_projection({key: parsed[key] for key in _PROJECTION_KEYS})
    return parsed


def _exact_json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("expected turn projection must contain exact JSON values") from error


def _integrity_commitment(canonical_bytes: bytes) -> bytes:
    return hashlib.sha256(b"locomo-expected-turn-integrity\0" + canonical_bytes).digest()


def _session_date_epoch(value: object) -> int | None:
    if type(value) is not str or len(value) > 48 or not _SESSION_DATE_RE.fullmatch(value):
        return None
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=UTC).timestamp())
    return None


def _bounded_id(value: object) -> bool:
    return bool(type(value) is str and 0 < len(value) <= _MAX_ID_LENGTH and value == value.strip())


def _plausible_epoch_timestamp(value: object) -> bool:
    return bool(
        type(value) is int and _MIN_PLAUSIBLE_TIMESTAMP <= value <= _MAX_PLAUSIBLE_TIMESTAMP
    )


__all__ = ("EXPECTED_OFFICIAL_LOCOMO_TURN_SCHEMA_VERSION", "ExpectedOfficialLocomoTurn")
