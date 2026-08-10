from __future__ import annotations

from collections.abc import Callable

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    OutputCipherError,
    OutputCipherKey,
)
from infinity_context_server.features.subscription_runtime_bridge import (
    aes_gcm_output_cipher as cipher_module,
)

_KEY_ID = "bridge-output-key-v1"
_OTHER_KEY_ID = "bridge-output-key-v2"
_KEY = bytes(range(32))
_OTHER_KEY = bytes(reversed(range(32)))
_AAD = b'{"exact":"bridge-associated-data"}'
_PLAINTEXT = b"private subscription completion"
_DURABLE_RESPONSE_CAP = 256 * 1024


class _Resolver:
    __slots__ = ("active_id", "keys", "resolve_calls")

    def __init__(
        self,
        keys: dict[str, bytes] | None = None,
        *,
        active_id: str = _KEY_ID,
    ) -> None:
        self.active_id = active_id
        self.keys = {_KEY_ID: _KEY} if keys is None else keys
        self.resolve_calls: list[str] = []

    def active_key(self) -> OutputCipherKey:
        return OutputCipherKey(self.active_id, self.keys[self.active_id])

    def resolve_key(self, key_id: str, /) -> OutputCipherKey:
        self.resolve_calls.append(key_id)
        return OutputCipherKey(key_id, self.keys[key_id])


class _NonceSequence:
    __slots__ = ("calls", "_nonces")

    def __init__(self, *nonces: bytes) -> None:
        self._nonces = list(nonces)
        self.calls: list[int] = []

    def __call__(self, size: int) -> bytes:
        self.calls.append(size)
        return self._nonces.pop(0)


def _cipher(
    *,
    resolver: object | None = None,
    cap: int = _DURABLE_RESPONSE_CAP,
    nonce_source: Callable[[int], bytes] | None = None,
) -> Aes256GcmOutputCipher:
    return Aes256GcmOutputCipher(
        key_resolver=_Resolver() if resolver is None else resolver,  # type: ignore[arg-type]
        maximum_ciphertext_bytes=cap,
        nonce_source=_NonceSequence(bytes(range(12))) if nonce_source is None else nonce_source,
    )


def _replace(value: bytes, start: int, replacement: bytes) -> bytes:
    mutable = bytearray(value)
    mutable[start : start + len(replacement)] = replacement
    return bytes(mutable)


def test_v1_envelope_is_canonical_key_bound_and_round_trips_exact_bytes() -> None:
    nonce = bytes(range(12))
    cipher = _cipher(nonce_source=_NonceSequence(nonce))

    sealed = cipher.seal(_PLAINTEXT, associated_data=_AAD)

    key_id_bytes = _KEY_ID.encode("ascii")
    header_bytes = 24 + len(key_id_bytes)
    assert sealed[:4] == b"ICBO"
    assert sealed[4] == Aes256GcmOutputCipher.ENVELOPE_VERSION
    assert sealed[5] == 0
    assert int.from_bytes(sealed[6:8], "big") == len(key_id_bytes)
    assert int.from_bytes(sealed[8:12], "big") == len(_PLAINTEXT)
    assert sealed[12:24] == nonce
    assert sealed[24:header_bytes] == key_id_bytes
    assert len(sealed) == len(_PLAINTEXT) + cipher.envelope_overhead(_KEY_ID)
    assert cipher.open(sealed, associated_data=_AAD) == _PLAINTEXT


def test_default_nonce_source_is_os_csprng_and_each_nonce_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _NonceSequence(b"a" * 12, b"b" * 12)
    monkeypatch.setattr(cipher_module.os, "urandom", source)
    cipher = Aes256GcmOutputCipher(
        key_resolver=_Resolver(),
        maximum_ciphertext_bytes=_DURABLE_RESPONSE_CAP,
    )

    first = cipher.seal(b"first", associated_data=_AAD)
    second = cipher.seal(b"second", associated_data=_AAD)

    assert source.calls == [12, 12]
    assert first[12:24] == b"a" * 12
    assert second[12:24] == b"b" * 12


def test_reused_or_malformed_injected_nonce_fails_closed() -> None:
    reused = _NonceSequence(b"n" * 12, b"n" * 12)
    resolver = _Resolver({_KEY_ID: _KEY, _OTHER_KEY_ID: _OTHER_KEY})
    cipher = _cipher(resolver=resolver, nonce_source=reused)
    cipher.seal(b"first", associated_data=_AAD)
    resolver.active_id = _OTHER_KEY_ID
    with pytest.raises(OutputCipherError, match="nonce_reuse"):
        cipher.seal(b"second", associated_data=_AAD)

    for invalid in (lambda _size: b"short", lambda _size: bytearray(12)):
        with pytest.raises(OutputCipherError, match="nonce_invalid"):
            _cipher(nonce_source=invalid).seal(_PLAINTEXT, associated_data=_AAD)  # type: ignore[arg-type]


def test_wrong_secret_aad_bit_flip_and_key_id_binding_fail_authentication() -> None:
    resolver = _Resolver({_KEY_ID: _KEY, _OTHER_KEY_ID: _KEY})
    sealed = _cipher(resolver=resolver).seal(_PLAINTEXT, associated_data=_AAD)

    wrong_secret = _cipher(resolver=_Resolver({_KEY_ID: _OTHER_KEY}))
    with pytest.raises(OutputCipherError, match="authentication_failed"):
        wrong_secret.open(sealed, associated_data=_AAD)
    with pytest.raises(OutputCipherError, match="authentication_failed"):
        _cipher(resolver=resolver).open(sealed, associated_data=_AAD + b"\0")

    bit_flipped = bytearray(sealed)
    bit_flipped[-1] ^= 1
    with pytest.raises(OutputCipherError, match="authentication_failed"):
        _cipher(resolver=resolver).open(bytes(bit_flipped), associated_data=_AAD)

    assert len(_KEY_ID) == len(_OTHER_KEY_ID)
    rebound = _replace(sealed, 24, _OTHER_KEY_ID.encode("ascii"))
    with pytest.raises(OutputCipherError, match="authentication_failed"):
        _cipher(resolver=resolver).open(rebound, associated_data=_AAD)


def test_truncated_appended_or_noncanonical_envelopes_fail_before_resolution() -> None:
    sealed = _cipher().seal(_PLAINTEXT, associated_data=_AAD)
    malformed = (
        b"",
        sealed[:24],
        sealed[:-1],
        sealed + b"\0",
        _replace(sealed, 0, b"NOPE"),
        _replace(sealed, 4, b"\x02"),
        _replace(sealed, 5, b"\x01"),
        _replace(sealed, 6, b"\0\0"),
        _replace(sealed, 8, (len(_PLAINTEXT) + 1).to_bytes(4, "big")),
        _replace(sealed, 24, b"!"),
    )

    for candidate in malformed:
        resolver = _Resolver()
        with pytest.raises(OutputCipherError, match="envelope_invalid"):
            _cipher(resolver=resolver).open(candidate, associated_data=_AAD)
        assert resolver.resolve_calls == []


def test_resolver_miss_identifier_drift_and_secret_drift_fail_closed() -> None:
    sealed = _cipher().seal(_PLAINTEXT, associated_data=_AAD)

    missing = _Resolver({})
    with pytest.raises(OutputCipherError, match="key_resolution_failed"):
        _cipher(resolver=missing).open(sealed, associated_data=_AAD)

    class IdentifierDrift:
        def active_key(self) -> OutputCipherKey:
            return OutputCipherKey(_KEY_ID, _KEY)

        def resolve_key(self, _key_id: str, /) -> OutputCipherKey:
            return OutputCipherKey(_OTHER_KEY_ID, _KEY)

    with pytest.raises(OutputCipherError, match="key_resolution_failed"):
        _cipher(resolver=IdentifierDrift()).open(sealed, associated_data=_AAD)

    secret_drift = _Resolver({_KEY_ID: _OTHER_KEY})
    with pytest.raises(OutputCipherError, match="authentication_failed"):
        _cipher(resolver=secret_drift).open(sealed, associated_data=_AAD)


def test_expansion_never_crosses_the_bridge_durable_response_cap() -> None:
    cipher = _cipher(
        cap=_DURABLE_RESPONSE_CAP,
        nonce_source=_NonceSequence(b"a" * 12, b"b" * 12),
    )
    overhead = cipher.envelope_overhead(_KEY_ID)
    maximum_plaintext = b"x" * (_DURABLE_RESPONSE_CAP - overhead)

    sealed = cipher.seal(maximum_plaintext, associated_data=_AAD)

    assert len(sealed) == _DURABLE_RESPONSE_CAP
    assert overhead <= Aes256GcmOutputCipher.MAX_ENVELOPE_OVERHEAD_BYTES
    with pytest.raises(OutputCipherError, match="plaintext_too_large"):
        cipher.seal(maximum_plaintext + b"x", associated_data=_AAD)


def test_oversized_ciphertext_fails_before_key_resolution() -> None:
    cap = 128
    resolver = _Resolver()
    cipher = _cipher(resolver=resolver, cap=cap)

    with pytest.raises(OutputCipherError, match="envelope_invalid"):
        cipher.open(b"x" * (cap + 1), associated_data=_AAD)
    assert resolver.resolve_calls == []


def test_key_and_plaintext_are_redacted_from_repr_and_failures() -> None:
    key_marker = b"K" * 32
    plaintext_marker = b"PLAINTEXT-MARKER"
    key = OutputCipherKey(_KEY_ID, key_marker)

    class ExplodingResolver:
        def __repr__(self) -> str:
            return f"ExplodingResolver(secret={key_marker!r})"

        def active_key(self) -> OutputCipherKey:
            raise RuntimeError(key_marker.decode("ascii"))

        def resolve_key(self, _key_id: str, /) -> OutputCipherKey:
            raise RuntimeError(key_marker.decode("ascii"))

    cipher = _cipher(resolver=ExplodingResolver())
    assert key_marker.decode("ascii") not in repr(key)
    assert key_marker.decode("ascii") not in repr(cipher)
    assert plaintext_marker.decode("ascii") not in repr(cipher)

    with pytest.raises(OutputCipherError) as captured:
        cipher.seal(plaintext_marker, associated_data=_AAD)
    rendered = f"{captured.value!r} {captured.value}"
    assert key_marker.decode("ascii") not in rendered
    assert plaintext_marker.decode("ascii") not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_mutable_key_copies_are_zeroed_after_encrypt_and_decrypt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_aesgcm = cipher_module.AESGCM
    observed: list[bytearray] = []

    class ObservedAesGcm:
        def __init__(self, key: bytearray) -> None:
            observed.append(key)
            self._delegate = real_aesgcm(bytes(key))

        def encrypt(self, nonce: bytes, data: bytes, aad: bytes) -> bytes:
            return self._delegate.encrypt(nonce, data, aad)

        def decrypt(self, nonce: bytes, data: bytes, aad: bytes) -> bytes:
            return self._delegate.decrypt(nonce, data, aad)

    monkeypatch.setattr(cipher_module, "AESGCM", ObservedAesGcm)
    cipher = _cipher()
    sealed = cipher.seal(_PLAINTEXT, associated_data=_AAD)
    assert cipher.open(sealed, associated_data=_AAD) == _PLAINTEXT

    assert len(observed) == 2
    assert all(value == bytearray(32) for value in observed)


def test_key_identity_and_cipher_limits_are_strict_and_bounded() -> None:
    longest_key_id = "k" * 128
    assert (
        Aes256GcmOutputCipher.envelope_overhead(longest_key_id)
        == Aes256GcmOutputCipher.MAX_ENVELOPE_OVERHEAD_BYTES
    )
    with pytest.raises(OutputCipherError, match="key_invalid"):
        OutputCipherKey("k" * 129, _KEY)
    with pytest.raises(OutputCipherError, match="key_invalid"):
        OutputCipherKey(_KEY_ID, b"short")
    for invalid_cap in (True, 40, 64 * 1024 * 1024 + 1):
        with pytest.raises(OutputCipherError, match="byte_limit_invalid"):
            Aes256GcmOutputCipher(
                key_resolver=_Resolver(),
                maximum_ciphertext_bytes=invalid_cap,
            )
