"""Write-once authenticated terminal handoffs consumed by the publishable run."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import final

from infinity_context_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_runtime_bridge.process_files import (
    read_private_json,
    verify_private_directory,
    write_private_json_once,
)

from infinity_context_server.processes.publishable_full_extraction_suite import (
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.processes.publishable_full_extraction_terminal_seal import (
    PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT,
    PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA,
    extraction_terminal_seal_hmac,
)

from .contracts import (
    PublishableExtractionTerminalSealReceipt,
    PublishableInputPreparationError,
    authentication_key_commitment,
    authentication_key_fingerprint,
)


def publishable_extraction_terminal_seal_hmac(
    terminal_payload: dict[str, object], *, authentication_key: bytes
) -> str:
    """Authenticate the exact consumer payload under its domain-separated key."""

    try:
        return extraction_terminal_seal_hmac(
            terminal_payload,
            authentication_key=authentication_key,
        )
    except Exception:
        _fail("publishable_input_terminal_store_invalid")


@final
class PublishableExtractionTerminalFileStore:
    """Persist two immutable HMAC envelopes and authenticate exact replay."""

    __slots__ = (
        "_authentication_keys",
        "_key_commitments",
        "_key_fingerprints",
        "_paths",
    )

    def __init__(
        self,
        *,
        paths: tuple[Path, Path],
        authentication_keys: tuple[bytes, bytes],
    ) -> None:
        if (
            type(paths) is not tuple
            or len(paths) != 2
            or any(not isinstance(path, Path) or not path.is_absolute() for path in paths)
            or len(set(paths)) != 2
            or type(authentication_keys) is not tuple
            or len(authentication_keys) != 2
            or any(
                type(key) is not bytes or not 32 <= len(key) <= 1024 for key in authentication_keys
            )
        ):
            _fail("publishable_input_terminal_store_invalid")
        commitments = tuple(
            authentication_key_commitment(key, purpose=f"extraction-terminal-{index}")
            for index, key in enumerate(authentication_keys)
        )
        fingerprints = tuple(authentication_key_fingerprint(key) for key in authentication_keys)
        if len(set(fingerprints)) != 2:
            _fail("publishable_input_terminal_store_key_reuse")
        try:
            for path in paths:
                verify_private_directory(path.parent, "extraction_terminal_parent")
            _require_distinct_existing_files(paths)
        except PublishableInputPreparationError:
            raise
        except Exception:
            _fail("publishable_input_terminal_store_invalid")
        self._paths = paths
        self._authentication_keys = authentication_keys
        self._key_commitments = commitments
        self._key_fingerprints = fingerprints

    @property
    def paths(self) -> tuple[Path, Path]:
        return self._paths

    @property
    def authentication_key_commitments(self) -> tuple[str, str]:
        return self._key_commitments

    @property
    def authentication_key_fingerprints(self) -> tuple[str, str]:
        return self._key_fingerprints

    def seal_exact(
        self, readback: PublishableExtractionSuiteReadback
    ) -> PublishableExtractionTerminalSealReceipt:
        """Create missing peers, or authenticate byte-exact existing envelopes."""

        if type(readback) is not PublishableExtractionSuiteReadback:
            _fail("publishable_input_terminal_readback_invalid")
        try:
            readback.__post_init__()
            terminals = (readback.locomo_terminal, readback.longmemeval_terminal)
            envelopes = tuple(
                _envelope(terminal, authentication_key=key)
                for terminal, key in zip(terminals, self._authentication_keys, strict=True)
            )
            missing: list[int] = []
            for index, (path, expected) in enumerate(zip(self.paths, envelopes, strict=True)):
                if not path.exists():
                    missing.append(index)
                    continue
                _require_exact_file(path, expected)
            for index in missing:
                write_private_json_once(
                    self.paths[index],
                    envelopes[index],
                    maximum_bytes=PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT,
                )
            for path, expected in zip(self.paths, envelopes, strict=True):
                _require_exact_file(path, expected)
            _require_distinct_existing_files(self.paths)
        except PublishableInputPreparationError:
            raise
        except Exception:
            _fail("publishable_input_terminal_store_authentication_failed")
        return PublishableExtractionTerminalSealReceipt(
            suite_readback_commitment_sha256=readback.suite_readback_commitment_sha256,
            ordered_terminal_commitment_sha256=tuple(
                terminal.terminal_commitment_sha256 for terminal in terminals
            ),
            ordered_authentication_hmac_sha256=tuple(
                envelope["authentication_hmac_sha256"] for envelope in envelopes
            ),
            created_file_count=len(missing),
        )

    def __repr__(self) -> str:
        return "PublishableExtractionTerminalFileStore(private_files=<bound>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("publishable extraction terminal store is nonserializable")


def _envelope(terminal: object, *, authentication_key: bytes) -> dict[str, object]:
    try:
        payload = {
            **terminal.body(),
            "terminal_commitment_sha256": terminal.terminal_commitment_sha256,
        }
    except Exception:
        _fail("publishable_input_terminal_payload_invalid")
    return {
        "authentication_hmac_sha256": publishable_extraction_terminal_seal_hmac(
            payload,
            authentication_key=authentication_key,
        ),
        "schema_version": PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA,
        "terminal": payload,
    }


def _require_exact_file(path: Path, expected: dict[str, object]) -> None:
    try:
        observed = read_private_json(
            path,
            maximum_bytes=PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT,
        )
        if not hmac.compare_digest(canonical_json_bytes(observed), canonical_json_bytes(expected)):
            _fail("publishable_input_terminal_store_divergent")
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_terminal_store_authentication_failed")


def _require_distinct_existing_files(paths: tuple[Path, Path]) -> None:
    identities = []
    for path in paths:
        if not path.exists():
            continue
        try:
            value = path.stat(follow_symlinks=False)
        except OSError:
            _fail("publishable_input_terminal_store_invalid")
        identities.append((value.st_dev, value.st_ino))
    if len(identities) != len(set(identities)):
        _fail("publishable_input_terminal_store_path_cross_wire")


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT",
    "PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA",
    "PublishableExtractionTerminalFileStore",
    "publishable_extraction_terminal_seal_hmac",
)
