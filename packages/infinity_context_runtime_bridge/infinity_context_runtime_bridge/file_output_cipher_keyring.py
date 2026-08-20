"""Provider-free AES output-key resolution from private local files."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, final

from .aes_gcm_output_cipher import OutputCipherKey
from .json_boundary import canonical_json_bytes
from .secure_secret_file import (
    SecureSecretFileReader,
    SecureSecretFileSnapshot,
)

OUTPUT_CIPHER_KEYRING_SCHEMA = "subscription-runtime-output-cipher-keyring.v1"
OUTPUT_CIPHER_KEYRING_MAXIMUM_BYTES = 64 * 1024
OUTPUT_CIPHER_KEYRING_MAXIMUM_KEYS = 32

_KEY_BYTES = 32
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEYRING_COMMITMENT_DOMAIN = b"infinity-context/subscription-runtime-bridge/output-keyring/v1\0"
_KEY_COMMITMENT_DOMAIN = b"infinity-context/subscription-runtime-bridge/output-key/aes-256-gcm/v1\0"
_RESOLVER_AUTHORITY_DOMAIN = (
    b"infinity-context/subscription-runtime-bridge/output-key-resolver/v1\0"
)
_DUPLICATE_SECRET_DOMAIN = b"infinity-context/subscription-runtime-bridge/output-key-duplicate/v1\0"

_INVALID = "bridge_output_cipher_keyring_invalid"
_DRIFT = "bridge_output_cipher_keyring_drift"
_UNAVAILABLE = "bridge_output_cipher_key_unavailable"


class OutputCipherKeyringError(RuntimeError):
    """Stable error that never contains key material, identifiers, or paths."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class FileOutputCipherKeyringSpec:
    """Public configuration authority for one immutable private keyring."""

    private_root: Path
    keyring_file: Path
    expected_keyring_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.private_root, Path)
            or not isinstance(self.keyring_file, Path)
            or not _is_sha256(self.expected_keyring_commitment_sha256)
        ):
            raise OutputCipherKeyringError(_INVALID) from None

    def __repr__(self) -> str:
        return (
            "FileOutputCipherKeyringSpec(private_root=<redacted>, "
            "keyring_file=<redacted>, expected_commitment=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class _KeyBinding:
    key_id: str
    key_file: Path
    key_commitment_sha256: str
    snapshot: SecureSecretFileSnapshot


@dataclass(frozen=True, slots=True, repr=False)
class _ParsedBinding:
    key_id: str
    key_file: Path
    key_commitment_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class _ParsedKeyring:
    active_key_id: str
    bindings: tuple[_ParsedBinding, ...]


@final
class PrivateFileOutputCipherKeyResolver:
    """Resolve an active or historical key from one pinned file authority.

    Construction preflights every key. Every later lookup re-attests both the
    keyring and the selected raw 32-byte key file. Any observed file drift latches
    the resolver closed for its remaining lifetime.
    """

    __slots__ = (
        "_active_key_id",
        "_authority_sha256",
        "_bindings",
        "_drifted",
        "_keyring_reader",
        "_keyring_snapshot",
        "_lock",
        "_private_root",
        "_spec",
    )

    def __init__(self, spec: FileOutputCipherKeyringSpec) -> None:
        if type(spec) is not FileOutputCipherKeyringSpec:
            raise OutputCipherKeyringError(_INVALID) from None
        self._spec = spec
        self._private_root = spec.private_root
        self._keyring_reader = SecureSecretFileReader(
            private_root=spec.private_root,
            path=spec.keyring_file,
            maximum_bytes=OUTPUT_CIPHER_KEYRING_MAXIMUM_BYTES,
        )
        self._lock = threading.RLock()
        self._drifted = False

        initialized: (
            tuple[
                str,
                dict[str, _KeyBinding],
                SecureSecretFileSnapshot,
                str,
            ]
            | None
        ) = None
        failed = False
        try:
            initialized = self._initialize()
        except Exception:
            failed = True
        if failed or initialized is None:
            raise OutputCipherKeyringError(_INVALID) from None
        (
            self._active_key_id,
            self._bindings,
            self._keyring_snapshot,
            self._authority_sha256,
        ) = initialized

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    @property
    def authority_sha256(self) -> str:
        """Return safe public authority material bound into production composition."""

        return self._authority_sha256

    @property
    def keyring_commitment_sha256(self) -> str:
        return self._spec.expected_keyring_commitment_sha256

    def active_key(self) -> OutputCipherKey:
        return self._resolve(self._active_key_id)

    def resolve_key(self, key_id: str, /) -> OutputCipherKey:
        if type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None:
            raise OutputCipherKeyringError(_UNAVAILABLE) from None
        return self._resolve(key_id)

    def preflight(self) -> None:
        """Re-attest the immutable manifest and every retained key version."""

        failed = False
        with self._lock:
            if self._drifted:
                raise OutputCipherKeyringError(_DRIFT) from None
            try:
                self._attest_keyring()
                for binding in self._bindings.values():
                    self._read_binding(binding, issue=False)
            except Exception:
                self._drifted = True
                failed = True
        if failed:
            raise OutputCipherKeyringError(_DRIFT) from None

    def __repr__(self) -> str:
        return (
            "PrivateFileOutputCipherKeyResolver("
            f"authority_sha256={self._authority_sha256!r}, "
            "active_key_id=<redacted>, keyring=<redacted>)"
        )

    def _initialize(
        self,
    ) -> tuple[str, dict[str, _KeyBinding], SecureSecretFileSnapshot, str]:
        with self._keyring_reader.read() as keyring:
            observed_commitment = output_cipher_keyring_commitment_sha256(keyring.value)
            if not hmac.compare_digest(
                observed_commitment,
                self._spec.expected_keyring_commitment_sha256,
            ):
                raise _InvalidKeyring
            parsed = _parse_keyring(keyring.value)
            keyring_snapshot = keyring.snapshot

        bindings: dict[str, _KeyBinding] = {}
        identities: set[tuple[int, int]] = set()
        paths: set[Path] = set()
        secret_fingerprints: list[bytes] = []
        for parsed_binding in parsed.bindings:
            reader = SecureSecretFileReader(
                private_root=self._private_root,
                path=parsed_binding.key_file,
                maximum_bytes=_KEY_BYTES,
            )
            with reader.read() as secret:
                if len(secret.value) != _KEY_BYTES:
                    raise _InvalidKeyring
                commitment = output_cipher_key_commitment_sha256(
                    parsed_binding.key_id,
                    secret.value,
                )
                if not hmac.compare_digest(
                    commitment,
                    parsed_binding.key_commitment_sha256,
                ):
                    raise _InvalidKeyring
                identity = secret.snapshot.file[:2]
                fingerprint_digest = hashlib.sha256()
                fingerprint_digest.update(_DUPLICATE_SECRET_DOMAIN)
                fingerprint_digest.update(secret.value)
                fingerprint = fingerprint_digest.digest()
                if (
                    parsed_binding.key_file in paths
                    or identity in identities
                    or any(hmac.compare_digest(fingerprint, prior) for prior in secret_fingerprints)
                ):
                    raise _InvalidKeyring
                paths.add(parsed_binding.key_file)
                identities.add(identity)
                secret_fingerprints.append(fingerprint)
                bindings[parsed_binding.key_id] = _KeyBinding(
                    key_id=parsed_binding.key_id,
                    key_file=parsed_binding.key_file,
                    key_commitment_sha256=parsed_binding.key_commitment_sha256,
                    snapshot=secret.snapshot,
                )

        authority = _resolver_authority_sha256(
            active_key_id=parsed.active_key_id,
            keyring_commitment_sha256=observed_commitment,
        )
        return parsed.active_key_id, bindings, keyring_snapshot, authority

    def _resolve(self, key_id: str) -> OutputCipherKey:
        result: OutputCipherKey | None = None
        failed = False
        with self._lock:
            if self._drifted:
                raise OutputCipherKeyringError(_DRIFT) from None
            binding = self._bindings.get(key_id)
            if binding is None:
                raise OutputCipherKeyringError(_UNAVAILABLE) from None
            try:
                self._attest_keyring()
                result = self._read_binding(binding, issue=True)
            except Exception:
                self._drifted = True
                failed = True
        if failed or result is None:
            raise OutputCipherKeyringError(_DRIFT) from None
        return result

    def _attest_keyring(self) -> None:
        with self._keyring_reader.read() as keyring:
            if keyring.snapshot != self._keyring_snapshot or not hmac.compare_digest(
                output_cipher_keyring_commitment_sha256(keyring.value),
                self._spec.expected_keyring_commitment_sha256,
            ):
                raise _InvalidKeyring
            parsed = _parse_keyring(keyring.value)
        if (
            parsed.active_key_id != self._active_key_id
            or len(parsed.bindings) != len(self._bindings)
            or any(
                self._bindings.get(item.key_id) is None
                or self._bindings[item.key_id].key_file != item.key_file
                or self._bindings[item.key_id].key_commitment_sha256 != item.key_commitment_sha256
                for item in parsed.bindings
            )
        ):
            raise _InvalidKeyring

    def _read_binding(self, binding: _KeyBinding, *, issue: bool) -> OutputCipherKey | None:
        reader = SecureSecretFileReader(
            private_root=self._private_root,
            path=binding.key_file,
            maximum_bytes=_KEY_BYTES,
        )
        with reader.read() as secret:
            if (
                secret.snapshot != binding.snapshot
                or len(secret.value) != _KEY_BYTES
                or not hmac.compare_digest(
                    output_cipher_key_commitment_sha256(binding.key_id, secret.value),
                    binding.key_commitment_sha256,
                )
            ):
                raise _InvalidKeyring
            if issue:
                return OutputCipherKey(binding.key_id, bytes(secret.value))
        return None


class _InvalidKeyring(Exception):
    pass


def output_cipher_keyring_commitment_sha256(raw: bytes | bytearray) -> str:
    """Commit exact canonical keyring bytes without exposing their contents."""

    if (
        type(raw) not in {bytes, bytearray}
        or not 1 <= len(raw) <= OUTPUT_CIPHER_KEYRING_MAXIMUM_BYTES
    ):
        raise OutputCipherKeyringError(_INVALID) from None
    digest = hashlib.sha256()
    digest.update(_KEYRING_COMMITMENT_DOMAIN)
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)
    return digest.hexdigest()


def output_cipher_key_commitment_sha256(
    key_id: str,
    secret: bytes | bytearray,
) -> str:
    """Return the domain-separated public commitment for one exact AES key."""

    if (
        type(key_id) is not str
        or _KEY_ID.fullmatch(key_id) is None
        or type(secret) not in {bytes, bytearray}
        or len(secret) != _KEY_BYTES
    ):
        raise OutputCipherKeyringError(_INVALID) from None
    encoded_key_id = key_id.encode("ascii")
    digest = hashlib.sha256()
    digest.update(_KEY_COMMITMENT_DOMAIN)
    digest.update(len(encoded_key_id).to_bytes(2, "big"))
    digest.update(encoded_key_id)
    digest.update(secret)
    return digest.hexdigest()


def _parse_keyring(raw: bytearray) -> _ParsedKeyring:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if type(value) is not dict or canonical_json_bytes(value) != raw:
            raise _InvalidKeyring
        if set(value) != {"active_key_id", "keys", "schema_version"}:
            raise _InvalidKeyring
        if value["schema_version"] != OUTPUT_CIPHER_KEYRING_SCHEMA:
            raise _InvalidKeyring
        active_key_id = value["active_key_id"]
        keys = value["keys"]
        if (
            type(active_key_id) is not str
            or _KEY_ID.fullmatch(active_key_id) is None
            or type(keys) is not dict
            or not 1 <= len(keys) <= OUTPUT_CIPHER_KEYRING_MAXIMUM_KEYS
            or active_key_id not in keys
        ):
            raise _InvalidKeyring

        bindings: list[_ParsedBinding] = []
        for key_id, entry in keys.items():
            if (
                type(key_id) is not str
                or _KEY_ID.fullmatch(key_id) is None
                or type(entry) is not dict
                or set(entry) != {"key_commitment_sha256", "key_file"}
                or type(entry["key_file"]) is not str
                or not _is_sha256(entry["key_commitment_sha256"])
            ):
                raise _InvalidKeyring
            bindings.append(
                _ParsedBinding(
                    key_id=key_id,
                    key_file=Path(entry["key_file"]),
                    key_commitment_sha256=entry["key_commitment_sha256"],
                )
            )
        return _ParsedKeyring(active_key_id=active_key_id, bindings=tuple(bindings))
    except Exception:
        raise _InvalidKeyring from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidKeyring
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise _InvalidKeyring


def _resolver_authority_sha256(
    *,
    active_key_id: str,
    keyring_commitment_sha256: str,
) -> str:
    encoded_key_id = active_key_id.encode("ascii")
    digest = hashlib.sha256()
    digest.update(_RESOLVER_AUTHORITY_DOMAIN)
    digest.update(len(encoded_key_id).to_bytes(2, "big"))
    digest.update(encoded_key_id)
    digest.update(bytes.fromhex(keyring_commitment_sha256))
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


__all__ = (
    "FileOutputCipherKeyringSpec",
    "OUTPUT_CIPHER_KEYRING_MAXIMUM_BYTES",
    "OUTPUT_CIPHER_KEYRING_MAXIMUM_KEYS",
    "OUTPUT_CIPHER_KEYRING_SCHEMA",
    "OutputCipherKeyringError",
    "PrivateFileOutputCipherKeyResolver",
    "output_cipher_key_commitment_sha256",
    "output_cipher_keyring_commitment_sha256",
)
