"""Private state layout and purpose-separated keys for a fresh-chain canary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import final

from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_DATASET_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunSecrets,
)

from .contracts import FRESH_CHAIN_CASE_ID, FreshChainCanaryError, canonical_sha256

FRESH_CHAIN_STATE_DIRECTORY = "fresh-chain-canary-v1"
FRESH_CHAIN_LEDGER_FILE = "five-call-ledger.sqlite3"
FRESH_CHAIN_EVIDENCE_FILE = "activation-evidence.json"
FRESH_CHAIN_PROVIDER_DIRECTORY = "provider"
FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE = "namespace-authority.json"
_KEY_DOMAIN = b"infinity-context/fresh-chain-canary/key/v1\0"
_NAMESPACE_AUTHENTICATION_DOMAIN = b"infinity-context/fresh-chain-canary/namespace-authority/v1\0"
_NAMESPACE_AUTHORITY_SCHEMA = "fresh-chain-namespace-authority.v1"


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainLayout:
    root: Path = field(repr=False)
    provider_root: Path = field(repr=False)
    ledger_path: Path = field(repr=False)
    evidence_path: Path = field(repr=False)
    namespace_id: str
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    ledger_authentication_key: bytes = field(repr=False)
    evidence_authentication_key: bytes = field(repr=False)
    resume: bool

    def __post_init__(self) -> None:
        if (
            any(not isinstance(path, Path) or not path.is_absolute() for path in self.paths)
            or type(self.namespace_id) is not str
            or not self.namespace_id.startswith("fresh-chain-")
            or any(
                not _sha(value)
                for value in (
                    self.namespace_commitment_sha256,
                    self.source_commitment_sha256,
                )
            )
            or any(type(key) is not bytes or len(key) != 32 for key in self.keys)
            or hmac.compare_digest(self.keys[0], self.keys[1])
            or hmac.compare_digest(
                self.namespace_commitment_sha256,
                self.source_commitment_sha256,
            )
            or type(self.resume) is not bool
        ):
            _fail("fresh_chain_layout_invalid")

    @property
    def paths(self) -> tuple[Path, Path, Path, Path]:
        return self.root, self.provider_root, self.ledger_path, self.evidence_path

    @property
    def keys(self) -> tuple[bytes, bytes]:
        return self.ledger_authentication_key, self.evidence_authentication_key


def open_fresh_chain_layout(
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
) -> FreshChainLayout:
    """Open one isolated generation without touching any provider capability."""

    if type(config) is not PublishableRunConfig or type(secrets) is not PublishableRunSecrets:
        _fail("fresh_chain_layout_inputs_invalid")
    parent = config.publication_receipt_path.parent
    root = parent / FRESH_CHAIN_STATE_DIRECTORY
    provider = root / FRESH_CHAIN_PROVIDER_DIRECTORY
    ledger = root / FRESH_CHAIN_LEDGER_FILE
    evidence = root / FRESH_CHAIN_EVIDENCE_FILE
    namespace_authority = root / FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE
    _require_no_overlap(root, config)
    resume = root.exists()
    namespace_resume = resume
    if resume:
        _require_private_directory(parent)
        _require_private_directory(root)
        _require_private_directory(provider)
        if not namespace_authority.exists():
            try:
                provider_empty = not any(provider.iterdir())
            except OSError:
                _fail("fresh_chain_state_generation_partial")
            if ledger.exists() or evidence.exists() or not provider_empty:
                _fail("fresh_chain_state_generation_partial")
            namespace_resume = False
        elif not ledger.exists():
            try:
                provider_empty = not any(provider.iterdir())
            except OSError:
                _fail("fresh_chain_state_generation_partial")
            if evidence.exists() or not provider_empty:
                _fail("fresh_chain_state_generation_partial")
    else:
        _require_private_directory(parent)
        try:
            root.mkdir(mode=0o700)
            provider.mkdir(mode=0o700)
        except OSError:
            _fail("fresh_chain_state_initialization_failed")
    source = fresh_chain_source_commitment(
        adapter_config_json=config.adapter_config_json,
        dependency_provider=config.dependency_provider,
    )
    namespace_key = _derive(secrets.publication_receipt_authentication_key, b"namespace")
    generation_nonce = _open_generation_nonce(
        namespace_authority,
        authentication_key=namespace_key,
        resume=namespace_resume,
    )
    namespace_suffix = hmac.new(
        namespace_key,
        bytes.fromhex(generation_nonce) + b"\0" + bytes.fromhex(source),
        hashlib.sha256,
    ).hexdigest()[:32]
    namespace_id = f"fresh-chain-{namespace_suffix}"
    namespace_commitment = canonical_sha256(
        {
            "case_id": FRESH_CHAIN_CASE_ID,
            "generation_nonce_sha256": hashlib.sha256(bytes.fromhex(generation_nonce)).hexdigest(),
            "namespace_id": namespace_id,
            "source_commitment_sha256": source,
        }
    )
    return FreshChainLayout(
        root=root,
        provider_root=provider,
        ledger_path=ledger,
        evidence_path=evidence,
        namespace_id=namespace_id,
        namespace_commitment_sha256=namespace_commitment,
        source_commitment_sha256=source,
        ledger_authentication_key=_derive(
            secrets.publication_receipt_authentication_key,
            b"five-call-ledger",
        ),
        evidence_authentication_key=_derive(
            secrets.publication_receipt_authentication_key,
            b"activation-evidence",
        ),
        resume=resume,
    )


def fresh_chain_source_commitment(
    *,
    adapter_config_json: bytes,
    dependency_provider: str,
) -> str:
    """Bind the exact provider envelope and immutable official case identity."""

    if (
        type(adapter_config_json) is not bytes
        or not adapter_config_json
        or type(dependency_provider) is not str
        or not dependency_provider
    ):
        _fail("fresh_chain_source_commitment_invalid")
    return canonical_sha256(
        {
            "adapter_config_sha256": hashlib.sha256(adapter_config_json).hexdigest(),
            "case_alias": PUBLISHABLE_CANARY_CASE_ALIAS,
            "case_id": FRESH_CHAIN_CASE_ID,
            "dataset_sha256": PUBLISHABLE_CANARY_DATASET_SHA256,
            "dependency_provider": dependency_provider,
        }
    )


def _open_generation_nonce(
    path: Path,
    *,
    authentication_key: bytes,
    resume: bool,
) -> str:
    if resume:
        return _read_generation_nonce(path, authentication_key=authentication_key)
    nonce = token_hex(32)
    unsigned = {
        "generation_nonce": nonce,
        "schema_version": _NAMESPACE_AUTHORITY_SCHEMA,
    }
    payload = {
        **unsigned,
        "hmac_sha256": hmac.new(
            authentication_key,
            _NAMESPACE_AUTHENTICATION_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        encoded = _canonical(payload)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError
            written += count
        os.fsync(descriptor)
    except OSError:
        _fail("fresh_chain_namespace_authority_create_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _fsync_directory(path.parent)
    return nonce


def _read_generation_nonce(path: Path, *, authentication_key: bytes) -> str:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= 4096
        ):
            raise OSError
        raw = path.read_bytes()
        pairs = json.loads(raw, object_pairs_hook=lambda value: value)
        if type(pairs) is not list or any(type(item) is not tuple for item in pairs):
            raise ValueError
        payload: dict[str, object] = {}
        for key, value in pairs:
            if type(key) is not str or key in payload:
                raise ValueError
            payload[key] = value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        _fail("fresh_chain_namespace_authority_invalid")
    if set(payload) != {"generation_nonce", "hmac_sha256", "schema_version"}:
        _fail("fresh_chain_namespace_authority_invalid")
    nonce = payload["generation_nonce"]
    observed = payload["hmac_sha256"]
    unsigned = {
        "generation_nonce": nonce,
        "schema_version": payload["schema_version"],
    }
    if (
        payload["schema_version"] != _NAMESPACE_AUTHORITY_SCHEMA
        or type(nonce) is not str
        or len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
        or not _sha(observed)
        or not hmac.compare_digest(
            observed,
            hmac.new(
                authentication_key,
                _NAMESPACE_AUTHENTICATION_DOMAIN + _canonical(unsigned),
                hashlib.sha256,
            ).hexdigest(),
        )
    ):
        _fail("fresh_chain_namespace_authority_invalid")
    return nonce


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        _fail("fresh_chain_namespace_authority_invalid")


def _require_no_overlap(root: Path, config: PublishableRunConfig) -> None:
    full_paths = (
        config.official_case_authority_path,
        *config.scheduler_database_paths,
        config.suite_seal_database_path,
        config.publication_receipt_path,
    )
    try:
        resolved_root = root.resolve(strict=False)
        resolved = tuple(path.resolve(strict=False) for path in full_paths)
    except (OSError, RuntimeError):
        _fail("fresh_chain_state_path_invalid")
    if any(
        resolved_root == path
        or resolved_root.is_relative_to(path)
        or path.is_relative_to(resolved_root)
        for path in resolved
    ):
        _fail("fresh_chain_state_path_overlap")


def _derive(source: bytes, label: bytes) -> bytes:
    if type(source) is not bytes or len(source) < 32 or type(label) is not bytes or not label:
        _fail("fresh_chain_key_derivation_invalid")
    return hmac.new(source, _KEY_DOMAIN + label, hashlib.sha256).digest()


def _require_private_directory(path: Path) -> None:
    try:
        value = path.lstat()
        valid = (
            path.is_absolute()
            and path.resolve(strict=True) == path
            and stat.S_ISDIR(value.st_mode)
            and not stat.S_ISLNK(value.st_mode)
            and value.st_uid == os.geteuid()
            and stat.S_IMODE(value.st_mode) == 0o700
        )
    except OSError:
        valid = False
    if not valid:
        _fail("fresh_chain_state_directory_invalid")


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        os.fsync(descriptor)
    except OSError:
        _fail("fresh_chain_namespace_authority_create_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FRESH_CHAIN_EVIDENCE_FILE",
    "FRESH_CHAIN_LEDGER_FILE",
    "FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE",
    "FRESH_CHAIN_PROVIDER_DIRECTORY",
    "FRESH_CHAIN_STATE_DIRECTORY",
    "FreshChainLayout",
    "fresh_chain_source_commitment",
    "open_fresh_chain_layout",
)
