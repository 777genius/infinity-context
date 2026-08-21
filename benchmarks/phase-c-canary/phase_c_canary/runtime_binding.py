from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from weakref import ReferenceType, ref

from .authority import AuthorityPathBindingPort, immutable_authority
from .hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .receipt import ReceiptVerificationError

_COMPOSITION_SEAL = object()
_AUTHORITY_SEAL = object()
_OBSERVER_SEAL = object()
_OBSERVATION_SEAL = object()
_BINDING_SEAL = object()


class _PinnedRuntimeBindingAuthority:
    __slots__ = (
        "runtime_artifact",
        "runtime_artifact_sha256",
        "runtime_source_sha256",
        "transport_route",
        "_seal",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        runtime_artifact: Path,
        runtime_artifact_sha256: str,
        runtime_source_sha256: str,
        transport_route: str,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _AUTHORITY_SEAL:
            raise ReceiptVerificationError("runtime authority is composition-issued only")
        _set_once(self, "runtime_artifact", runtime_artifact)
        _set_once(self, "runtime_artifact_sha256", runtime_artifact_sha256)
        _set_once(self, "runtime_source_sha256", runtime_source_sha256)
        _set_once(self, "transport_route", transport_route)
        _set_once(self, "_seal", _seal)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("pinned runtime authority is immutable")


class _TransportObservation:
    __slots__ = ("runtime_artifact", "transport_route", "_seal", "__weakref__")

    def __init__(
        self,
        *,
        runtime_artifact: Path,
        transport_route: str,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _OBSERVATION_SEAL:
            raise ReceiptVerificationError("transport observations are observer-issued only")
        _set_once(self, "runtime_artifact", runtime_artifact)
        _set_once(self, "transport_route", transport_route)
        _set_once(self, "_seal", _seal)
        _remember_observation(self)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("transport observations are immutable")

    def _is_authentic(self) -> bool:
        registered = _OBSERVATION_SNAPSHOTS.get(id(self))
        return (
            getattr(self, "_seal", None) is _OBSERVATION_SEAL
            and registered is not None
            and registered[0]() is self
            and registered[1] == _observation_snapshot(self)
        )


class _ConfiguredTransportObserver:
    __slots__ = ("_runtime_artifact", "_transport_route", "_seal", "__weakref__")

    def __init__(
        self,
        *,
        runtime_artifact: Path,
        transport_route: str,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _OBSERVER_SEAL:
            raise ReceiptVerificationError("transport observer is composition-issued only")
        _set_once(self, "_runtime_artifact", runtime_artifact)
        _set_once(self, "_transport_route", transport_route)
        _set_once(self, "_seal", _seal)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("configured transport observer is immutable")

    def observe(self) -> _TransportObservation:
        return _TransportObservation(
            runtime_artifact=self._runtime_artifact,
            transport_route=self._transport_route,
            _seal=_OBSERVATION_SEAL,
        )


_BINDING_SNAPSHOTS: dict[int, tuple[ReferenceType[TrustedRuntimeBinding], str]] = {}
_SERVICE_SNAPSHOTS: dict[int, tuple[ReferenceType[PinnedRuntimeBindingService], str]] = {}
_OBSERVATION_SNAPSHOTS: dict[int, tuple[ReferenceType[_TransportObservation], str]] = {}


class TrustedRuntimeBinding:
    __slots__ = (
        "_commitment_sha256",
        "_route_binding_sha256",
        "_runtime_source_sha256",
        "_seal",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        runtime_source_sha256: str,
        route_binding_sha256: str,
        commitment_sha256: str,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _BINDING_SEAL:
            raise ReceiptVerificationError("trusted runtime bindings are validator-issued only")
        _set_once(self, "_runtime_source_sha256", runtime_source_sha256)
        _set_once(self, "_route_binding_sha256", route_binding_sha256)
        _set_once(self, "_commitment_sha256", commitment_sha256)
        _set_once(self, "_seal", _seal)
        _remember_binding(self)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("trusted runtime bindings are immutable")

    @property
    def runtime_source_sha256(self) -> str:
        return self._runtime_source_sha256

    @property
    def route_binding_sha256(self) -> str:
        return self._route_binding_sha256

    @property
    def commitment_sha256(self) -> str:
        return self._commitment_sha256

    def _is_authentic(self) -> bool:
        registered = _BINDING_SNAPSHOTS.get(id(self))
        return (
            getattr(self, "_seal", None) is _BINDING_SEAL
            and registered is not None
            and registered[0]() is self
            and registered[1] == _binding_snapshot(self)
        )


class PinnedRuntimeBindingService:
    __slots__ = ("_authority", "_observer", "_seal", "__weakref__")

    def __init__(
        self,
        *,
        authority: _PinnedRuntimeBindingAuthority,
        observer: _ConfiguredTransportObserver,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _COMPOSITION_SEAL:
            raise ReceiptVerificationError("runtime binding service is composition-issued only")
        _set_once(self, "_authority", authority)
        _set_once(self, "_observer", observer)
        _set_once(self, "_seal", _seal)
        _remember_service(self)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("runtime binding service is immutable")

    def issue(self) -> TrustedRuntimeBinding:
        if not self._is_authentic():
            raise ReceiptVerificationError("runtime binding service authority drifted")
        authority = self._authority
        observation = self._observer.observe()
        if not observation._is_authentic():
            raise ReceiptVerificationError("transport observation is not observer-issued")
        artifact_sha256 = _sha256(authority.runtime_artifact_sha256, "runtime artifact sha256")
        source_sha256 = _sha256(authority.runtime_source_sha256, "runtime source sha256")
        expected_route = _canonical_route(authority.transport_route)
        actual_route = _canonical_route(observation.transport_route)
        try:
            pinned = authority.runtime_artifact
            observed = observation.runtime_artifact
            if pinned.is_symlink() or observed.is_symlink():
                raise ReceiptVerificationError("runtime artifact must not be a symlink")
            pinned_resolved = pinned.resolve(strict=True)
            if pinned_resolved != observed.resolve(strict=True):
                raise ReceiptVerificationError("observed runtime artifact is not pinned")
            if not pinned_resolved.is_file() or not os.access(pinned_resolved, os.R_OK):
                raise ReceiptVerificationError("pinned runtime artifact is not readable")
            if sha256_file(pinned_resolved) != artifact_sha256:
                raise ReceiptVerificationError("pinned runtime artifact hash mismatch")
        except OSError as exc:
            raise ReceiptVerificationError("pinned runtime artifact validation failed") from exc
        if actual_route != expected_route:
            raise ReceiptVerificationError("actual transport route differs from pinned route")
        route_sha256 = sha256_bytes(expected_route.encode())
        commitment = sha256_bytes(
            canonical_json_bytes(
                {
                    "schema_version": 1,
                    "runtime_artifact_sha256": artifact_sha256,
                    "runtime_source_sha256": source_sha256,
                    "transport_route_sha256": route_sha256,
                }
            )
        )
        return TrustedRuntimeBinding(
            runtime_source_sha256=source_sha256,
            route_binding_sha256=route_sha256,
            commitment_sha256=commitment,
            _seal=_BINDING_SEAL,
        )

    def _is_authentic(self) -> bool:
        registered = _SERVICE_SNAPSHOTS.get(id(self))
        return (
            getattr(self, "_seal", None) is _COMPOSITION_SEAL
            and registered is not None
            and registered[0]() is self
            and registered[1] == _service_snapshot(self)
        )


class RuntimeBindingComposition:
    @staticmethod
    def compose_phase_c_canary(
        *, authority_binding: AuthorityPathBindingPort | None = None
    ) -> PinnedRuntimeBindingService:
        """Compose only the frozen authority and transport pinned by Phase C."""
        reviewed = (
            immutable_authority()
            if authority_binding is None
            else immutable_authority(authority_binding=authority_binding)
        )
        runtime_artifact = reviewed.runtime_artifact_manifest.path
        transport_route = "http://127.0.0.1:8890/v1"
        authority = _PinnedRuntimeBindingAuthority(
            runtime_artifact=runtime_artifact,
            runtime_artifact_sha256=reviewed.runtime_artifact_manifest.sha256,
            runtime_source_sha256=sha256_bytes(reviewed.runtime_commit.encode()),
            transport_route=transport_route,
            _seal=_AUTHORITY_SEAL,
        )
        observer = _ConfiguredTransportObserver(
            runtime_artifact=runtime_artifact,
            transport_route=transport_route,
            _seal=_OBSERVER_SEAL,
        )
        return PinnedRuntimeBindingService(
            authority=authority,
            observer=observer,
            _seal=_COMPOSITION_SEAL,
        )


def require_trusted_runtime_binding(binding: TrustedRuntimeBinding) -> None:
    if type(binding) is not TrustedRuntimeBinding or not binding._is_authentic():
        raise ReceiptVerificationError("publishable receipt requires a trusted runtime binding")


def _remember_binding(binding: TrustedRuntimeBinding) -> None:
    identity = id(binding)

    def discard(reference: ReferenceType[TrustedRuntimeBinding]) -> None:
        if (registered := _BINDING_SNAPSHOTS.get(identity)) is not None and registered[
            0
        ] is reference:
            _BINDING_SNAPSHOTS.pop(identity, None)

    reference = ref(binding, discard)
    _BINDING_SNAPSHOTS[identity] = (reference, _binding_snapshot(binding))


def _remember_service(service: PinnedRuntimeBindingService) -> None:
    identity = id(service)

    def discard(reference: ReferenceType[PinnedRuntimeBindingService]) -> None:
        if (registered := _SERVICE_SNAPSHOTS.get(identity)) is not None and registered[
            0
        ] is reference:
            _SERVICE_SNAPSHOTS.pop(identity, None)

    reference = ref(service, discard)
    _SERVICE_SNAPSHOTS[identity] = (reference, _service_snapshot(service))


def _remember_observation(observation: _TransportObservation) -> None:
    identity = id(observation)

    def discard(reference: ReferenceType[_TransportObservation]) -> None:
        if (registered := _OBSERVATION_SNAPSHOTS.get(identity)) is not None and registered[
            0
        ] is reference:
            _OBSERVATION_SNAPSHOTS.pop(identity, None)

    reference = ref(observation, discard)
    _OBSERVATION_SNAPSHOTS[identity] = (reference, _observation_snapshot(observation))


def _observation_snapshot(observation: _TransportObservation) -> str:
    try:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "runtime_artifact": str(observation.runtime_artifact),
                    "transport_route": observation.transport_route,
                }
            )
        )
    except (AttributeError, TypeError, ValueError):
        return "invalid"


def _service_snapshot(service: PinnedRuntimeBindingService) -> str:
    try:
        authority = service._authority
        observer = service._observer
        payload = {
            "authority": {
                "runtime_artifact": str(authority.runtime_artifact),
                "runtime_artifact_sha256": authority.runtime_artifact_sha256,
                "runtime_source_sha256": authority.runtime_source_sha256,
                "transport_route": authority.transport_route,
                "seal": authority._seal is _AUTHORITY_SEAL,
            },
            "observer": {
                "runtime_artifact": str(observer._runtime_artifact),
                "transport_route": observer._transport_route,
                "seal": observer._seal is _OBSERVER_SEAL,
            },
        }
        return sha256_bytes(canonical_json_bytes(payload))
    except (AttributeError, TypeError, ValueError):
        return "invalid"


def _binding_snapshot(binding: TrustedRuntimeBinding) -> str:
    try:
        payload = {
            "runtime_source_sha256": binding.runtime_source_sha256,
            "route_binding_sha256": binding.route_binding_sha256,
            "commitment_sha256": binding.commitment_sha256,
        }
        return sha256_bytes(canonical_json_bytes(payload))
    except (AttributeError, TypeError, ValueError):
        return "invalid"


def _set_once(instance: object, name: str, value: object) -> None:
    object.__setattr__(instance, name, value)


def _canonical_route(value: object) -> str:
    if type(value) is not str or not value or len(value) > 2048:
        raise ReceiptVerificationError("transport route must be bounded text")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReceiptVerificationError("transport route is not an admissible HTTP origin/path")
    hostname = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ReceiptVerificationError("transport route has an invalid port") from exc
    default_port = 80 if parsed.scheme == "http" else 443
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = rendered_host if port in {None, default_port} else f"{rendered_host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, authority, path, "", ""))


def _sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ReceiptVerificationError(f"{label} must be a lowercase sha256")
    return value
