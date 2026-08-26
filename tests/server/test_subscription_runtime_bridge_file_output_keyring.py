from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from infinity_context_runtime_bridge import (
    OUTPUT_CIPHER_KEYRING_SCHEMA,
    Aes256GcmOutputCipher,
    FileOutputCipherKeyringSpec,
    OutputCipherKeyringError,
    PrivateFileOutputCipherKeyResolver,
    output_cipher_key_commitment_sha256,
    output_cipher_keyring_commitment_sha256,
)
from infinity_context_runtime_bridge import (
    secure_secret_file as secure_file_module,
)
from infinity_context_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)

_KEY_V1 = bytes(range(32))
_KEY_V2 = bytes(reversed(range(32)))
_KEY_ID_V1 = "bridge-output-key-v1"
_KEY_ID_V2 = "bridge-output-key-v2"


def _root(tmp_path: Path, name: str = "output-keys") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _write_secret(root: Path, key_id: str, secret: bytes) -> Path:
    path = root / f"{key_id}.key"
    path.write_bytes(secret)
    path.chmod(0o600)
    return path


def _manifest(
    *,
    active_key_id: str,
    entries: dict[str, tuple[Path, bytes]],
) -> bytes:
    return canonical_json_bytes(
        {
            "active_key_id": active_key_id,
            "keys": {
                key_id: {
                    "key_commitment_sha256": output_cipher_key_commitment_sha256(
                        key_id,
                        secret,
                    ),
                    "key_file": str(path),
                }
                for key_id, (path, secret) in entries.items()
            },
            "schema_version": OUTPUT_CIPHER_KEYRING_SCHEMA,
        }
    )


def _write_keyring(root: Path, raw: bytes) -> Path:
    path = root / "keyring.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def _spec(root: Path, keyring: Path, raw: bytes) -> FileOutputCipherKeyringSpec:
    return FileOutputCipherKeyringSpec(
        private_root=root,
        keyring_file=keyring,
        expected_keyring_commitment_sha256=(output_cipher_keyring_commitment_sha256(raw)),
    )


def _provision(
    tmp_path: Path,
    *,
    active_key_id: str = _KEY_ID_V1,
    secrets: dict[str, bytes] | None = None,
    root_name: str = "output-keys",
) -> tuple[
    Path,
    Path,
    bytes,
    FileOutputCipherKeyringSpec,
    dict[str, Path],
]:
    root = _root(tmp_path, root_name)
    material = {_KEY_ID_V1: _KEY_V1, _KEY_ID_V2: _KEY_V2} if secrets is None else secrets
    paths = {key_id: _write_secret(root, key_id, secret) for key_id, secret in material.items()}
    raw = _manifest(
        active_key_id=active_key_id,
        entries={key_id: (paths[key_id], secret) for key_id, secret in material.items()},
    )
    keyring = _write_keyring(root, raw)
    return root, keyring, raw, _spec(root, keyring, raw), paths


class _NonceSequence:
    def __init__(self, *values: bytes) -> None:
        self._values = list(values)

    def __call__(self, size: int) -> bytes:
        assert size == 12
        return self._values.pop(0)


def test_active_and_historical_exact_keys_drive_aes_round_trip(tmp_path: Path) -> None:
    _, _, _, spec, _ = _provision(tmp_path, active_key_id=_KEY_ID_V2)
    resolver = PrivateFileOutputCipherKeyResolver(spec)

    assert resolver.active_key_id == _KEY_ID_V2
    assert resolver.active_key().secret == _KEY_V2
    assert resolver.resolve_key(_KEY_ID_V1).secret == _KEY_V1
    assert len(resolver.authority_sha256) == 64
    resolver.preflight()

    cipher = Aes256GcmOutputCipher(
        key_resolver=resolver,
        maximum_ciphertext_bytes=1_024,
        nonce_source=_NonceSequence(b"n" * 12),
    )
    sealed = cipher.seal(b"private completion", associated_data=b"exact-aad")
    assert _KEY_ID_V2.encode() in sealed
    assert cipher.open(sealed, associated_data=b"exact-aad") == b"private completion"


def test_rotation_uses_new_active_key_and_retains_old_decrypt_only_key(
    tmp_path: Path,
) -> None:
    root, keyring, raw_v1, spec_v1, paths = _provision(tmp_path)
    resolver_v1 = PrivateFileOutputCipherKeyResolver(spec_v1)
    cipher_v1 = Aes256GcmOutputCipher(
        key_resolver=resolver_v1,
        maximum_ciphertext_bytes=1_024,
        nonce_source=_NonceSequence(b"a" * 12),
    )
    old_envelope = cipher_v1.seal(b"old private output", associated_data=b"rotation")

    raw_v2 = _manifest(
        active_key_id=_KEY_ID_V2,
        entries={
            _KEY_ID_V1: (paths[_KEY_ID_V1], _KEY_V1),
            _KEY_ID_V2: (paths[_KEY_ID_V2], _KEY_V2),
        },
    )
    assert raw_v2 != raw_v1
    keyring.write_bytes(raw_v2)
    keyring.chmod(0o600)
    resolver_v2 = PrivateFileOutputCipherKeyResolver(_spec(root, keyring, raw_v2))
    cipher_v2 = Aes256GcmOutputCipher(
        key_resolver=resolver_v2,
        maximum_ciphertext_bytes=1_024,
        nonce_source=_NonceSequence(b"b" * 12),
    )

    assert cipher_v2.open(old_envelope, associated_data=b"rotation") == b"old private output"
    new_envelope = cipher_v2.seal(b"new private output", associated_data=b"rotation")
    assert _KEY_ID_V2.encode() in new_envelope
    with pytest.raises(OutputCipherKeyringError, match="keyring_drift"):
        resolver_v1.active_key()


@pytest.mark.parametrize(
    "key_id",
    (
        "missing-key",
        "BRIDGE-output-key-v1",
        "bridge-output-key-v1 ",
        "",
    ),
)
def test_wrong_key_id_is_exactly_rejected_without_poisoning_resolver(
    tmp_path: Path,
    key_id: str,
) -> None:
    _, _, _, spec, _ = _provision(tmp_path)
    resolver = PrivateFileOutputCipherKeyResolver(spec)

    with pytest.raises(OutputCipherKeyringError, match="key_unavailable"):
        resolver.resolve_key(key_id)

    assert resolver.active_key().secret == _KEY_V1


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_nonfinite_json_is_rejected_before_key_resolution(
    tmp_path: Path,
    constant: str,
) -> None:
    root = _root(tmp_path)
    path = _write_secret(root, _KEY_ID_V1, _KEY_V1)
    raw = (
        "{"
        f'"active_key_id":"{_KEY_ID_V1}",'
        f'"keys":{{"{_KEY_ID_V1}":{{'
        f'"key_commitment_sha256":"{output_cipher_key_commitment_sha256(_KEY_ID_V1, _KEY_V1)}",'
        f'"key_file":{json.dumps(str(path))}}}}},'
        f'"nonfinite":{constant},'
        f'"schema_version":"{OUTPUT_CIPHER_KEYRING_SCHEMA}"'
        "}"
    ).encode()
    keyring = _write_keyring(root, raw)

    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, raw))


@pytest.mark.parametrize("level", ("top", "keys", "entry"))
def test_duplicate_json_keys_at_every_object_level_are_rejected(
    tmp_path: Path,
    level: str,
) -> None:
    root = _root(tmp_path)
    path = _write_secret(root, _KEY_ID_V1, _KEY_V1)
    commitment = output_cipher_key_commitment_sha256(_KEY_ID_V1, _KEY_V1)
    entry = f'"key_commitment_sha256":"{commitment}","key_file":{json.dumps(str(path))}'
    if level == "entry":
        entry += f',"key_file":{json.dumps(str(path))}'
    keys = f'"{_KEY_ID_V1}":{{{entry}}}'
    if level == "keys":
        keys += f',"{_KEY_ID_V1}":{{{entry}}}'
    fields = (
        f'"active_key_id":"{_KEY_ID_V1}",'
        f'"keys":{{{keys}}},'
        f'"schema_version":"{OUTPUT_CIPHER_KEYRING_SCHEMA}"'
    )
    if level == "top":
        fields += f',"schema_version":"{OUTPUT_CIPHER_KEYRING_SCHEMA}"'
    raw = ("{" + fields + "}").encode()
    keyring = _write_keyring(root, raw)

    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, raw))


def test_noncanonical_or_unknown_json_schema_is_rejected(tmp_path: Path) -> None:
    root, keyring, raw, _, _ = _provision(tmp_path)
    pretty = json.dumps(json.loads(raw), indent=2, sort_keys=True).encode()
    keyring.write_bytes(pretty)
    keyring.chmod(0o600)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, pretty))

    payload = json.loads(raw)
    payload["unexpected"] = "metadata"
    unknown = canonical_json_bytes(payload)
    keyring.write_bytes(unknown)
    keyring.chmod(0o600)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, unknown))


def test_wrong_external_or_per_key_commitment_fails_closed(tmp_path: Path) -> None:
    root, keyring, raw, _, _ = _provision(tmp_path)
    wrong_spec = FileOutputCipherKeyringSpec(
        private_root=root,
        keyring_file=keyring,
        expected_keyring_commitment_sha256="0" * 64,
    )
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(wrong_spec)

    payload = json.loads(raw)
    payload["keys"][_KEY_ID_V1]["key_commitment_sha256"] = "0" * 64
    wrong_key = canonical_json_bytes(payload)
    keyring.write_bytes(wrong_key)
    keyring.chmod(0o600)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, wrong_key))


@pytest.mark.parametrize("size", (31, 33))
def test_every_raw_key_file_must_be_exactly_32_bytes(tmp_path: Path, size: int) -> None:
    root = _root(tmp_path)
    path = _write_secret(root, _KEY_ID_V1, b"x" * size)
    raw = canonical_json_bytes(
        {
            "active_key_id": _KEY_ID_V1,
            "keys": {
                _KEY_ID_V1: {
                    "key_commitment_sha256": "0" * 64,
                    "key_file": str(path),
                }
            },
            "schema_version": OUTPUT_CIPHER_KEYRING_SCHEMA,
        }
    )
    keyring = _write_keyring(root, raw)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(root, keyring, raw))


def test_duplicate_path_inode_or_secret_material_is_rejected(tmp_path: Path) -> None:
    duplicate_path_root = _root(tmp_path, "duplicate-path")
    shared = _write_secret(duplicate_path_root, "shared", _KEY_V1)
    raw = _manifest(
        active_key_id=_KEY_ID_V1,
        entries={
            _KEY_ID_V1: (shared, _KEY_V1),
            _KEY_ID_V2: (shared, _KEY_V1),
        },
    )
    keyring = _write_keyring(duplicate_path_root, raw)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(duplicate_path_root, keyring, raw))

    duplicate_secret_root = _root(tmp_path, "duplicate-secret")
    first = _write_secret(duplicate_secret_root, _KEY_ID_V1, _KEY_V1)
    second = _write_secret(duplicate_secret_root, _KEY_ID_V2, _KEY_V1)
    raw = _manifest(
        active_key_id=_KEY_ID_V1,
        entries={_KEY_ID_V1: (first, _KEY_V1), _KEY_ID_V2: (second, _KEY_V1)},
    )
    keyring = _write_keyring(duplicate_secret_root, raw)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(duplicate_secret_root, keyring, raw))

    hardlink_root = _root(tmp_path, "duplicate-inode")
    original = _write_secret(hardlink_root, _KEY_ID_V1, _KEY_V1)
    linked = hardlink_root / f"{_KEY_ID_V2}.key"
    os.link(original, linked)
    raw = _manifest(
        active_key_id=_KEY_ID_V1,
        entries={_KEY_ID_V1: (original, _KEY_V1), _KEY_ID_V2: (linked, _KEY_V1)},
    )
    keyring = _write_keyring(hardlink_root, raw)
    with pytest.raises(OutputCipherKeyringError, match="keyring_invalid"):
        PrivateFileOutputCipherKeyResolver(_spec(hardlink_root, keyring, raw))


@pytest.mark.parametrize("surface", ("key-replacement", "keyring-replacement"))
def test_inode_replacement_after_open_latches_resolver_closed(
    tmp_path: Path,
    surface: str,
) -> None:
    _, keyring, raw, spec, paths = _provision(tmp_path)
    resolver = PrivateFileOutputCipherKeyResolver(spec)

    if surface == "key-replacement":
        replacement = paths[_KEY_ID_V1].with_name("replacement.key")
        replacement.write_bytes(_KEY_V1)
        replacement.chmod(0o600)
        replacement.replace(paths[_KEY_ID_V1])
    else:
        replacement = keyring.with_name("replacement.json")
        replacement.write_bytes(raw)
        replacement.chmod(0o600)
        replacement.replace(keyring)

    with pytest.raises(OutputCipherKeyringError, match="keyring_drift"):
        resolver.active_key()
    with pytest.raises(OutputCipherKeyringError, match="keyring_drift"):
        resolver.active_key()


def test_same_inode_key_mutation_and_restore_cannot_clear_drift_latch(tmp_path: Path) -> None:
    _, _, _, spec, paths = _provision(tmp_path)
    resolver = PrivateFileOutputCipherKeyResolver(spec)
    path = paths[_KEY_ID_V1]
    before = path.stat()

    path.write_bytes(b"z" * 32)
    path.chmod(0o600)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    with pytest.raises(OutputCipherKeyringError, match="keyring_drift"):
        resolver.active_key()

    path.write_bytes(_KEY_V1)
    path.chmod(0o600)
    with pytest.raises(OutputCipherKeyringError, match="keyring_drift"):
        resolver.active_key()


def test_keyring_and_key_buffers_are_wiped_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, spec, _ = _provision(tmp_path)
    real_wipe = secure_file_module._wipe
    observed: list[bytearray] = []

    def tracking_wipe(value: bytearray) -> None:
        observed.append(value)
        real_wipe(value)

    monkeypatch.setattr(secure_file_module, "_wipe", tracking_wipe)
    resolver = PrivateFileOutputCipherKeyResolver(spec)
    assert observed and all(value == bytearray() for value in observed)

    assert resolver.active_key().secret == _KEY_V1
    assert all(value == bytearray() for value in observed)


def test_repr_and_direct_failures_never_retain_paths_ids_or_secret_material(
    tmp_path: Path,
) -> None:
    marker = "PRIVATE-KEY-MARKER"
    root, keyring, raw, spec, _ = _provision(
        tmp_path,
        root_name=marker,
        secrets={_KEY_ID_V1: b"S" * 32},
    )
    resolver = PrivateFileOutputCipherKeyResolver(spec)
    rendered = f"{spec!r} {resolver!r}"
    assert marker not in rendered
    assert str(root) not in rendered
    assert str(keyring) not in rendered
    assert _KEY_ID_V1 not in rendered
    assert "S" * 32 not in rendered

    bad_spec = FileOutputCipherKeyringSpec(
        private_root=root,
        keyring_file=keyring,
        expected_keyring_commitment_sha256="f" * 64,
    )
    with pytest.raises(OutputCipherKeyringError) as captured:
        PrivateFileOutputCipherKeyResolver(bad_spec)
    failure = f"{captured.value!r} {captured.value}"
    assert marker not in failure
    assert raw.decode() not in failure
    assert "S" * 32 not in failure
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
