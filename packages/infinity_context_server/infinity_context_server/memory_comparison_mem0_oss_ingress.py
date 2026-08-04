"""One-run ingress credential authority for a true-keyless Mem0 OSS target."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_probe_transport import (
    VettedProbeTransport,
    vet_probe_target,
)

MEM0_OSS_INGRESS_API_KEY_ENV = "MEM0_OSS_INGRESS_API_KEY"
MEM0_OSS_INGRESS_AUTHORITY_SCHEMA_VERSION = "mem0-oss-ingress-authority.v1"

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SECRET_BYTES = 4_096
_TOKEN = object()


class Mem0OssIngressCredentialError(RuntimeError):
    """Fixed-code ingress authority failure without reflected private material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class Mem0OssIngressAuthorityDescriptor:
    """Secret-free identity for one exact ingress credential authority."""

    schema_version: str
    run_id_sha256: str
    target_identity_sha256: str
    credential_binding_id: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != MEM0_OSS_INGRESS_AUTHORITY_SCHEMA_VERSION
            or type(self.run_id_sha256) is not str
            or _SHA256.fullmatch(self.run_id_sha256) is None
            or type(self.target_identity_sha256) is not str
            or _SHA256.fullmatch(self.target_identity_sha256) is None
            or type(self.credential_binding_id) is not str
            or not self.credential_binding_id.startswith("sha256:")
            or _SHA256.fullmatch(self.credential_binding_id.removeprefix("sha256:")) is None
        ):
            raise Mem0OssIngressCredentialError("mem0_oss_ingress_descriptor_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0OssIngressAuthorityDescriptor is final")


@final
class Mem0OssIngressCredentialAuthority:
    """Nonserializable two-lane authority for data-plane and probe ingress."""

    __slots__ = (
        "__data_plane_phase",
        "__descriptor",
        "__lock",
        "__origin",
        "__probe_phase",
        "__run_id",
        "__secret",
        "__usage_probe_phase",
    )

    def __init__(
        self,
        *,
        run_id: str,
        origin: str,
        target_identity_sha256: str,
        secret: bytearray,
        _token: object,
    ) -> None:
        if (
            _token is not _TOKEN
            or type(run_id) is not str
            or _RUN_ID.fullmatch(run_id) is None
            or type(origin) is not str
            or not origin
            or type(target_identity_sha256) is not str
            or _SHA256.fullmatch(target_identity_sha256) is None
            or type(secret) is not bytearray
            or not secret
        ):
            _wipe(secret)
            raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid")
        self.__run_id = run_id
        self.__origin = origin
        self.__secret = secret
        self.__lock = threading.Lock()
        self.__data_plane_phase = "pending"
        self.__probe_phase = "pending"
        self.__usage_probe_phase = "pending"
        self.__descriptor = Mem0OssIngressAuthorityDescriptor(
            schema_version=MEM0_OSS_INGRESS_AUTHORITY_SCHEMA_VERSION,
            run_id_sha256=hashlib.sha256(run_id.encode()).hexdigest(),
            target_identity_sha256=target_identity_sha256,
            credential_binding_id="sha256:" + hashlib.sha256(bytes(secret)).hexdigest(),
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0OssIngressCredentialAuthority is final")

    def __repr__(self) -> str:
        return "Mem0OssIngressCredentialAuthority(<sealed-two-lane>)"

    def __reduce__(self) -> object:
        raise TypeError("Mem0 OSS ingress authority is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("Mem0 OSS ingress authority is nonserializable")

    def descriptor(self) -> Mem0OssIngressAuthorityDescriptor:
        return self.__descriptor

    def _claim(self, lane: str, *, run_id: str, target_identity_sha256: str) -> str:
        with self.__lock:
            attribute = "_Mem0OssIngressCredentialAuthority__" + lane + "_phase"
            if (
                lane not in {"data_plane", "probe", "usage_probe"}
                or getattr(self, attribute, None) != "pending"
                or type(run_id) is not str
                or type(target_identity_sha256) is not str
                or run_id != self.__run_id
                or not hmac.compare_digest(
                    target_identity_sha256,
                    self.__descriptor.target_identity_sha256,
                )
            ):
                if lane in {"data_plane", "probe", "usage_probe"}:
                    setattr(self, attribute, "terminal")
                raise Mem0OssIngressCredentialError("mem0_oss_ingress_context_mismatch")
            setattr(self, attribute, "consumed")
            try:
                value = bytes(self.__secret).decode("utf-8")
            except Exception:
                setattr(self, attribute, "terminal")
                raise Mem0OssIngressCredentialError(
                    "mem0_oss_ingress_configuration_invalid"
                ) from None
            if (
                self.__data_plane_phase
                == self.__probe_phase
                == self.__usage_probe_phase
                == "consumed"
            ):
                _wipe(self.__secret)
            return value


def issue_mem0_oss_ingress_credential_authority(
    *,
    run_id: str,
    base_url: str,
    ingress_api_key: str,
    allowed_target_hosts: Sequence[str],
    vetted_transport: VettedProbeTransport | None = None,
) -> Mem0OssIngressCredentialAuthority:
    """Issue ingress authority only for an explicitly allowed local/private target."""

    if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid")
    secret = _secret(ingress_api_key)
    try:
        target = vet_probe_target(
            base_url,
            allowed_hosts=allowed_target_hosts,
            vetted_transport=vetted_transport,
        )
        if target is None or not _target_is_local_or_private(
            target.base_url,
            host=target.host,
            allowed_target_hosts=allowed_target_hosts,
            vetted_transport=vetted_transport,
        ):
            raise Mem0OssIngressCredentialError("mem0_oss_ingress_target_unsafe")
        return Mem0OssIngressCredentialAuthority(
            run_id=run_id,
            origin=target.base_url,
            target_identity_sha256=target.identity_sha256,
            secret=secret,
            _token=_TOKEN,
        )
    except Mem0OssIngressCredentialError:
        _wipe(secret)
        raise
    except Exception:
        _wipe(secret)
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid") from None


def inspect_mem0_oss_ingress_authority(
    authority: object,
) -> Mem0OssIngressAuthorityDescriptor:
    if type(authority) is not Mem0OssIngressCredentialAuthority:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_authority_invalid")
    return authority.descriptor()


def _consume_mem0_oss_ingress_data_plane(
    authority: object,
    *,
    run_id: str,
    target_identity_sha256: str,
) -> str:
    if type(authority) is not Mem0OssIngressCredentialAuthority:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_authority_invalid")
    return authority._claim(
        "data_plane",
        run_id=run_id,
        target_identity_sha256=target_identity_sha256,
    )


def _consume_mem0_oss_ingress_probe(
    authority: object,
    *,
    run_id: str,
    target_identity_sha256: str,
) -> str:
    if type(authority) is not Mem0OssIngressCredentialAuthority:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_authority_invalid")
    return authority._claim(
        "probe",
        run_id=run_id,
        target_identity_sha256=target_identity_sha256,
    )


def _consume_mem0_oss_ingress_usage_probe(
    authority: object,
    *,
    run_id: str,
    target_identity_sha256: str,
) -> str:
    if type(authority) is not Mem0OssIngressCredentialAuthority:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_authority_invalid")
    return authority._claim(
        "usage_probe",
        run_id=run_id,
        target_identity_sha256=target_identity_sha256,
    )


def _target_is_local_or_private(
    origin: str,
    *,
    host: str,
    allowed_target_hosts: Sequence[str],
    vetted_transport: VettedProbeTransport | None,
) -> bool:
    allowed = {
        value.strip().casefold().removesuffix(".")
        for value in allowed_target_hosts
        if type(value) is str
    }
    if host not in allowed:
        return False
    parsed = urlsplit(origin)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return parsed.scheme == "https" and vetted_transport is not None
    if address.is_loopback:
        return parsed.scheme in {"http", "https"}
    private = (
        address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
    )
    return private and parsed.scheme == "https"


def _secret(value: object) -> bytearray:
    if type(value) is not str or not value or value != value.strip():
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid") from None
    if (
        not encoded
        or len(encoded) > _MAX_SECRET_BYTES
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise Mem0OssIngressCredentialError("mem0_oss_ingress_configuration_invalid")
    return bytearray(encoded)


def _wipe(value: object) -> None:
    if type(value) is bytearray:
        for index in range(len(value)):
            value[index] = 0


__all__ = (
    "MEM0_OSS_INGRESS_API_KEY_ENV",
    "MEM0_OSS_INGRESS_AUTHORITY_SCHEMA_VERSION",
    "Mem0OssIngressAuthorityDescriptor",
    "Mem0OssIngressCredentialAuthority",
    "Mem0OssIngressCredentialError",
    "inspect_mem0_oss_ingress_authority",
    "issue_mem0_oss_ingress_credential_authority",
)
