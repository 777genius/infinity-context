"""Discriminated cleanup authority for legacy-v2 and strict-v4 runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, final

from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment, digest

CleanupAuthorityKind = Literal["legacy_v2_plan", "strict_v4_a2"]
AUTHORITY_KINDS: Final = ("legacy_v2_plan", "strict_v4_a2")
STRICT_V4_READBACK_SCHEMA: Final = "memory-comparison-strict-v4-cleanup-readback.v1"


class ManagedCleanupV4AuthorityError(MemoryValidationError):
    """Stable fail-closed rejection of cleanup authority material."""


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV4Authority:
    """Canonical authority selected before any cleanup lifecycle mutation."""

    kind: CleanupAuthorityKind
    authority_sha256: str
    run_id_sha256: str
    legacy_plan_sha256: str | None = None
    context_sha256: str | None = None
    a2_terminal_sha256: str | None = None
    expected_index_terminal_sha256: str | None = None

    def __post_init__(self) -> None:
        for value in (self.authority_sha256, self.run_id_sha256):
            _digest(value)
        if self.kind not in AUTHORITY_KINDS:
            _fail("managed_cleanup_v4_authority_invalid")
        legacy = self.kind == "legacy_v2_plan"
        strict_bindings = (
            self.context_sha256,
            self.a2_terminal_sha256,
            self.expected_index_terminal_sha256,
        )
        if legacy:
            _digest(self.legacy_plan_sha256)
            if any(value is not None for value in strict_bindings):
                _fail("managed_cleanup_v4_authority_invalid")
        else:
            if self.legacy_plan_sha256 is not None:
                _fail("managed_cleanup_v4_authority_invalid")
            for value in strict_bindings:
                _digest(value)
            if self.a2_terminal_sha256 != self.expected_index_terminal_sha256:
                _fail("managed_cleanup_v4_authority_invalid")
        if self.authority_sha256 != cleanup_authority_sha256(
            kind=self.kind,
            run_id_sha256=self.run_id_sha256,
            legacy_plan_sha256=self.legacy_plan_sha256,
            context_sha256=self.context_sha256,
            a2_terminal_sha256=self.a2_terminal_sha256,
            expected_index_terminal_sha256=self.expected_index_terminal_sha256,
        ):
            _fail("managed_cleanup_v4_authority_invalid")

    def payload(self, *, include_commitment: bool = True) -> dict[str, object]:
        value = _authority_body(
            kind=self.kind,
            run_id_sha256=self.run_id_sha256,
            legacy_plan_sha256=self.legacy_plan_sha256,
            context_sha256=self.context_sha256,
            a2_terminal_sha256=self.a2_terminal_sha256,
            expected_index_terminal_sha256=self.expected_index_terminal_sha256,
        )
        if include_commitment:
            value["authority_sha256"] = self.authority_sha256
        return value


@final
@dataclass(frozen=True, slots=True)
class StrictV4CleanupAuthorityReadback:
    """Authenticated preparation, registration, and writer binding for cleanup."""

    run_id_sha256: str
    context_sha256: str
    a2_terminal_sha256: str
    expected_index_terminal_sha256: str
    preparation_receipt_sha256: str
    preparation_receipt_mac_sha256: str
    registration_sha256: str
    registration_mac_sha256: str
    writer_authority_sha256: str
    writer_authority_mac_sha256: str
    authentication_key_id: str
    authentication_authority_sha256: str
    readback_sha256: str
    readback_mac_sha256: str
    schema_version: str = STRICT_V4_READBACK_SCHEMA

    def __post_init__(self) -> None:
        for value in (
            self.run_id_sha256,
            self.context_sha256,
            self.a2_terminal_sha256,
            self.expected_index_terminal_sha256,
            self.preparation_receipt_sha256,
            self.preparation_receipt_mac_sha256,
            self.registration_sha256,
            self.registration_mac_sha256,
            self.writer_authority_sha256,
            self.writer_authority_mac_sha256,
            self.authentication_authority_sha256,
            self.readback_sha256,
            self.readback_mac_sha256,
        ):
            _digest(value)
        if (
            self.schema_version != STRICT_V4_READBACK_SCHEMA
            or not _key_id(self.authentication_key_id)
            or self.a2_terminal_sha256 != self.expected_index_terminal_sha256
            or self.readback_sha256
            != commitment("strict-v4-cleanup-readback/v1", self.payload(False))
        ):
            _fail("managed_cleanup_v4_strict_readback_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, str]:
        value = {
            "schema_version": self.schema_version,
            "run_id_sha256": self.run_id_sha256,
            "context_sha256": self.context_sha256,
            "a2_terminal_sha256": self.a2_terminal_sha256,
            "expected_index_terminal_sha256": self.expected_index_terminal_sha256,
            "preparation_receipt_sha256": self.preparation_receipt_sha256,
            "preparation_receipt_mac_sha256": self.preparation_receipt_mac_sha256,
            "registration_sha256": self.registration_sha256,
            "registration_mac_sha256": self.registration_mac_sha256,
            "writer_authority_sha256": self.writer_authority_sha256,
            "writer_authority_mac_sha256": self.writer_authority_mac_sha256,
            "authentication_key_id": self.authentication_key_id,
            "authentication_authority_sha256": self.authentication_authority_sha256,
        }
        if include_commitment:
            value["readback_sha256"] = self.readback_sha256
            value["readback_mac_sha256"] = self.readback_mac_sha256
        return value


class StrictV4CleanupAuthorityReadPort(Protocol):
    async def read_registered_strict_v4(
        self, run_id_sha256: str
    ) -> StrictV4CleanupAuthorityReadback | None: ...


class ManagedCleanupV4AuthorityResolverPort(Protocol):
    async def resolve(self) -> ManagedCleanupV4Authority: ...


@final
class StrictV4CleanupAuthorityResolver:
    """Resolve strict authority without accepting or touching a legacy loader."""

    def __init__(
        self,
        *,
        run_id_sha256: str,
        reader: StrictV4CleanupAuthorityReadPort,
        authenticator: ProjectionReceiptAuthenticator,
        authentication_key_id: str,
    ) -> None:
        _digest(run_id_sha256)
        if not callable(getattr(reader, "read_registered_strict_v4", None)):
            _fail("managed_cleanup_v4_strict_port_invalid")
        if type(authenticator) is not ProjectionReceiptAuthenticator or not _key_id(
            authentication_key_id
        ):
            _fail("managed_cleanup_v4_authentication_invalid")
        self._run_id_sha256 = run_id_sha256
        self._reader = reader
        self._authenticator = authenticator
        self._authentication_key_id = authentication_key_id

    async def resolve(self) -> ManagedCleanupV4Authority:
        readback = await self._reader.read_registered_strict_v4(self._run_id_sha256)
        if type(readback) is not StrictV4CleanupAuthorityReadback:
            _fail("managed_cleanup_v4_strict_authority_missing")
        readback.__post_init__()
        authenticate_strict_v4_cleanup_authority_readback(
            readback,
            authenticator=self._authenticator,
            authentication_key_id=self._authentication_key_id,
        )
        if readback.run_id_sha256 != self._run_id_sha256:
            _fail("managed_cleanup_v4_strict_readback_invalid")
        return build_strict_v4_cleanup_authority(
            run_id_sha256=readback.run_id_sha256,
            context_sha256=readback.context_sha256,
            a2_terminal_sha256=readback.a2_terminal_sha256,
            expected_index_terminal_sha256=readback.expected_index_terminal_sha256,
        )


def build_legacy_v2_cleanup_authority(
    *, run_id_sha256: str, legacy_plan_sha256: str
) -> ManagedCleanupV4Authority:
    body = _authority_body(
        kind="legacy_v2_plan",
        run_id_sha256=run_id_sha256,
        legacy_plan_sha256=legacy_plan_sha256,
        context_sha256=None,
        a2_terminal_sha256=None,
        expected_index_terminal_sha256=None,
    )
    return ManagedCleanupV4Authority(
        kind="legacy_v2_plan",
        authority_sha256=commitment("cleanup-authority/v1", body),
        run_id_sha256=run_id_sha256,
        legacy_plan_sha256=legacy_plan_sha256,
    )


def build_strict_v4_cleanup_authority(
    *,
    run_id_sha256: str,
    context_sha256: str,
    a2_terminal_sha256: str,
    expected_index_terminal_sha256: str,
) -> ManagedCleanupV4Authority:
    body = _authority_body(
        kind="strict_v4_a2",
        run_id_sha256=run_id_sha256,
        legacy_plan_sha256=None,
        context_sha256=context_sha256,
        a2_terminal_sha256=a2_terminal_sha256,
        expected_index_terminal_sha256=expected_index_terminal_sha256,
    )
    return ManagedCleanupV4Authority(
        kind="strict_v4_a2",
        authority_sha256=commitment("cleanup-authority/v1", body),
        run_id_sha256=run_id_sha256,
        context_sha256=context_sha256,
        a2_terminal_sha256=a2_terminal_sha256,
        expected_index_terminal_sha256=expected_index_terminal_sha256,
    )


def build_strict_v4_cleanup_authority_readback(
    *,
    run_id_sha256: str,
    context_sha256: str,
    a2_terminal_sha256: str,
    expected_index_terminal_sha256: str,
    preparation_receipt_sha256: str,
    preparation_receipt_mac_sha256: str,
    registration_sha256: str,
    registration_mac_sha256: str,
    writer_authority_sha256: str,
    writer_authority_mac_sha256: str,
    authenticator: ProjectionReceiptAuthenticator,
    authentication_key_id: str,
) -> StrictV4CleanupAuthorityReadback:
    if type(authenticator) is not ProjectionReceiptAuthenticator or not _key_id(
        authentication_key_id
    ):
        _fail("managed_cleanup_v4_authentication_invalid")
    body = {
        "schema_version": STRICT_V4_READBACK_SCHEMA,
        "run_id_sha256": run_id_sha256,
        "context_sha256": context_sha256,
        "a2_terminal_sha256": a2_terminal_sha256,
        "expected_index_terminal_sha256": expected_index_terminal_sha256,
        "preparation_receipt_sha256": preparation_receipt_sha256,
        "preparation_receipt_mac_sha256": preparation_receipt_mac_sha256,
        "registration_sha256": registration_sha256,
        "registration_mac_sha256": registration_mac_sha256,
        "writer_authority_sha256": writer_authority_sha256,
        "writer_authority_mac_sha256": writer_authority_mac_sha256,
        "authentication_key_id": authentication_key_id,
        "authentication_authority_sha256": authenticator.authority_sha256,
    }
    readback_sha256 = commitment("strict-v4-cleanup-readback/v1", body)
    return StrictV4CleanupAuthorityReadback(
        **{key: value for key, value in body.items() if key != "schema_version"},
        readback_sha256=readback_sha256,
        readback_mac_sha256=authenticator.sign(
            "strict-v4-cleanup-authority-readback", readback_sha256
        ),
    )


def authenticate_strict_v4_cleanup_authority_readback(
    readback: StrictV4CleanupAuthorityReadback,
    *,
    authenticator: ProjectionReceiptAuthenticator,
    authentication_key_id: str,
) -> None:
    if type(readback) is not StrictV4CleanupAuthorityReadback:
        _fail("managed_cleanup_v4_strict_authority_missing")
    readback.__post_init__()
    if (
        type(authenticator) is not ProjectionReceiptAuthenticator
        or readback.authentication_key_id != authentication_key_id
        or readback.authentication_authority_sha256 != authenticator.authority_sha256
        or not authenticator.verify(
            "strict-v4-cleanup-authority-readback",
            readback.readback_sha256,
            readback.readback_mac_sha256,
        )
    ):
        _fail("managed_cleanup_v4_strict_readback_authentication_invalid")


def cleanup_authority_sha256(
    *,
    kind: CleanupAuthorityKind,
    run_id_sha256: str,
    legacy_plan_sha256: str | None,
    context_sha256: str | None,
    a2_terminal_sha256: str | None,
    expected_index_terminal_sha256: str | None,
) -> str:
    return commitment(
        "cleanup-authority/v1",
        _authority_body(
            kind=kind,
            run_id_sha256=run_id_sha256,
            legacy_plan_sha256=legacy_plan_sha256,
            context_sha256=context_sha256,
            a2_terminal_sha256=a2_terminal_sha256,
            expected_index_terminal_sha256=expected_index_terminal_sha256,
        ),
    )


def _authority_body(**values: object) -> dict[str, object]:
    return {"schema_version": "memory-comparison-cleanup-authority.v1", **values}


def _key_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _digest(value: object) -> str:
    try:
        return digest(value)
    except MemoryValidationError as exc:
        raise ManagedCleanupV4AuthorityError("managed_cleanup_v4_digest_invalid") from exc


def _fail(code: str) -> None:
    raise ManagedCleanupV4AuthorityError(code)


__all__ = tuple(
    name
    for name in globals()
    if name.startswith(("ManagedCleanupV4", "StrictV4", "LegacyV2", "build_", "cleanup_"))
    or name in {"AUTHORITY_KINDS", "CleanupAuthorityKind", "STRICT_V4_READBACK_SCHEMA"}
)
