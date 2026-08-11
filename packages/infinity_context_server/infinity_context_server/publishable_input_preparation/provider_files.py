"""Descriptor-bound private files for the installed input provider."""

from __future__ import annotations

from pathlib import Path

from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    canonical_json_bytes,
    strict_json_loads,
)
from infinity_context_server.features.subscription_runtime_bridge.secure_secret_file import (
    SecureSecretFileReader,
)

from .contracts import (
    PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT,
    PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT,
    PublishableInputPreparationError,
)


def load_publishable_input_provider_files(
    *,
    private_root: Path,
    config_path: Path,
    secrets_path: Path,
    reserved_paths: tuple[Path, ...] = (),
) -> tuple[bytes, bytes]:
    """Read distinct 0600 strict-JSON files beneath the operator's 0700 root."""

    if (
        not isinstance(private_root, Path)
        or not isinstance(config_path, Path)
        or not isinstance(secrets_path, Path)
        or type(reserved_paths) is not tuple
        or any(not isinstance(path, Path) for path in reserved_paths)
    ):
        _fail("publishable_input_provider_files_invalid")
    declared = (config_path, secrets_path, *reserved_paths)
    if len(set(declared)) != len(declared):
        _fail("publishable_input_provider_file_cross_wire")
    try:
        readers = (
            SecureSecretFileReader(
                private_root=private_root,
                path=config_path,
                maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT,
            ),
            SecureSecretFileReader(
                private_root=private_root,
                path=secrets_path,
                maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT,
            ),
        )
        with readers[0].read() as config, readers[1].read() as secrets:
            identities = [config.snapshot.file[:2], secrets.snapshot.file[:2]]
            for path in reserved_paths:
                if path.exists():
                    value = path.stat(follow_symlinks=False)
                    identities.append((value.st_dev, value.st_ino))
            if len(identities) != len(set(identities)):
                _fail("publishable_input_provider_file_cross_wire")
            raw = (
                bytes(config.value),
                bytes(secrets.value),
            )
        parsed = (
            strict_json_loads(raw[0], maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT),
            strict_json_loads(raw[1], maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT),
        )
        if any(type(item) is not dict for item in parsed):
            _fail("publishable_input_provider_files_invalid")
        return canonical_json_bytes(parsed[0]), canonical_json_bytes(parsed[1])
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_provider_files_invalid")


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = ("load_publishable_input_provider_files",)
