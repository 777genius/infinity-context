"""Provider-free lifecycle receipts for discriminated cleanup authority."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Final, Literal, Protocol, cast, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment, digest
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    CleanupAuthorityKind,
    ManagedCleanupV4Authority,
    ManagedCleanupV4AuthorityError,
    ManagedCleanupV4ReceiptAuthenticatorPort,
)

INITIATION_SCHEMA: Final = "memory-comparison-cleanup-initiation.v4"
TERMINAL_SCHEMA: Final = "memory-comparison-cleanup-terminal.v4"
EVIDENCE_SCHEMA: Final = "memory-comparison-cleanup-terminal-bindings.v4"


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV4TerminalBindings:
    """Exact inventory and provider-absence terminals admitted for completion."""

    inventory_terminal_sha256: str
    qdrant_absence_pass_sha256: tuple[str, str]
    graphiti_absence_pass_sha256: tuple[str, str]
    cognee_disposition: Literal["not_projected"]
    cognee_projected_count: int
    cognee_evidence_sha256: str
    context_sha256: str | None
    a2_terminal_sha256: str | None
    bindings_sha256: str
    schema_version: str = EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        digest(self.inventory_terminal_sha256)
        digest(self.cognee_evidence_sha256)
        for passes in (
            self.qdrant_absence_pass_sha256,
            self.graphiti_absence_pass_sha256,
        ):
            if type(passes) is not tuple or len(passes) != 2 or passes[0] == passes[1]:
                _fail("managed_cleanup_v4_absence_terminal_invalid")
            for value in passes:
                digest(value)
        if self.context_sha256 is not None:
            digest(self.context_sha256)
        if self.a2_terminal_sha256 is not None:
            digest(self.a2_terminal_sha256)
        if (
            self.schema_version != EVIDENCE_SCHEMA
            or self.cognee_disposition != "not_projected"
            or type(self.cognee_projected_count) is not int
            or self.cognee_projected_count != 0
            or (self.context_sha256 is None) != (self.a2_terminal_sha256 is None)
            or self.bindings_sha256
            != commitment("cleanup-terminal-bindings/v4", self.payload(False))
        ):
            _fail("managed_cleanup_v4_absence_terminal_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "inventory_terminal_sha256": self.inventory_terminal_sha256,
            "qdrant_absence_pass_sha256": list(self.qdrant_absence_pass_sha256),
            "graphiti_absence_pass_sha256": list(self.graphiti_absence_pass_sha256),
            "cognee_disposition": self.cognee_disposition,
            "cognee_projected_count": self.cognee_projected_count,
            "cognee_evidence_sha256": self.cognee_evidence_sha256,
            "context_sha256": self.context_sha256,
            "a2_terminal_sha256": self.a2_terminal_sha256,
        }
        if include_commitment:
            value["bindings_sha256"] = self.bindings_sha256
        return value


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV4InitiationReceipt:
    run_id_sha256: str
    authority_kind: CleanupAuthorityKind
    authority_sha256: str
    authentication_key_id: str
    authentication_authority_sha256: str
    state: Literal["cleanup_pending"]
    receipt_sha256: str
    receipt_mac_sha256: str
    schema_version: str = INITIATION_SCHEMA

    def __post_init__(self) -> None:
        digest(self.run_id_sha256)
        digest(self.authority_sha256)
        digest(self.authentication_authority_sha256)
        digest(self.receipt_mac_sha256)
        if (
            self.schema_version != INITIATION_SCHEMA
            or self.authority_kind not in {"legacy_v2_plan", "strict_v4_a2"}
            or not _key_id(self.authentication_key_id)
            or self.state != "cleanup_pending"
            or self.receipt_sha256 != commitment("cleanup-initiation/v4", self.payload(False))
        ):
            _fail("managed_cleanup_v4_initiation_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, str]:
        value = {
            "schema_version": self.schema_version,
            "run_id_sha256": self.run_id_sha256,
            "authority_kind": self.authority_kind,
            "authority_sha256": self.authority_sha256,
            "authentication_key_id": self.authentication_key_id,
            "authentication_authority_sha256": self.authentication_authority_sha256,
            "state": self.state,
        }
        if include_commitment:
            value["receipt_sha256"] = self.receipt_sha256
            value["receipt_mac_sha256"] = self.receipt_mac_sha256
        return value


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV4TerminalReceipt:
    run_id_sha256: str
    authority_kind: CleanupAuthorityKind
    authority_sha256: str
    authentication_key_id: str
    authentication_authority_sha256: str
    cleanup_initiation_receipt_sha256: str
    terminal_bindings: ManagedCleanupV4TerminalBindings
    state: Literal["cleanup_complete"]
    receipt_sha256: str
    receipt_mac_sha256: str
    schema_version: str = TERMINAL_SCHEMA

    def __post_init__(self) -> None:
        for value in (
            self.run_id_sha256,
            self.authority_sha256,
            self.authentication_authority_sha256,
            self.cleanup_initiation_receipt_sha256,
            self.receipt_mac_sha256,
        ):
            digest(value)
        if type(self.terminal_bindings) is not ManagedCleanupV4TerminalBindings:
            _fail("managed_cleanup_v4_terminal_invalid")
        self.terminal_bindings.__post_init__()
        if (
            self.schema_version != TERMINAL_SCHEMA
            or self.authority_kind not in {"legacy_v2_plan", "strict_v4_a2"}
            or not _key_id(self.authentication_key_id)
            or self.state != "cleanup_complete"
            or self.receipt_sha256 != commitment("cleanup-terminal/v4", self.payload(False))
        ):
            _fail("managed_cleanup_v4_terminal_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id_sha256": self.run_id_sha256,
            "authority_kind": self.authority_kind,
            "authority_sha256": self.authority_sha256,
            "authentication_key_id": self.authentication_key_id,
            "authentication_authority_sha256": self.authentication_authority_sha256,
            "cleanup_initiation_receipt_sha256": self.cleanup_initiation_receipt_sha256,
            "terminal_bindings": self.terminal_bindings.payload(),
            "state": self.state,
        }
        if include_commitment:
            value["receipt_sha256"] = self.receipt_sha256
            value["receipt_mac_sha256"] = self.receipt_mac_sha256
        return value


class ManagedCleanupV4LifecyclePort(Protocol):
    """Exact-idempotent receipt persistence; implementations own serialization."""

    async def read_initiation(
        self, run_id_sha256: str
    ) -> ManagedCleanupV4InitiationReceipt | None: ...

    async def put_initiation(
        self, receipt: ManagedCleanupV4InitiationReceipt
    ) -> ManagedCleanupV4InitiationReceipt: ...

    async def read_terminal(self, run_id_sha256: str) -> ManagedCleanupV4TerminalReceipt | None: ...

    async def put_terminal(
        self, receipt: ManagedCleanupV4TerminalReceipt
    ) -> ManagedCleanupV4TerminalReceipt: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV4Transition:
    receipt: ManagedCleanupV4InitiationReceipt | ManagedCleanupV4TerminalReceipt
    replayed: bool


async def initiate_managed_cleanup_v4(
    *,
    authority: ManagedCleanupV4Authority,
    lifecycle: ManagedCleanupV4LifecyclePort,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> ManagedCleanupV4Transition:
    _authority(authority)
    _authentication(authenticator, authentication_key_id)
    expected = build_cleanup_v4_initiation_receipt(
        authority,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    existing = await lifecycle.read_initiation(authority.run_id_sha256)
    terminal = await lifecycle.read_terminal(authority.run_id_sha256)
    if terminal is not None:
        _terminal_matches_authority(
            terminal,
            authority,
            authenticator=authenticator,
            authentication_key_id=authentication_key_id,
        )
    if existing is not None:
        if type(existing) is not ManagedCleanupV4InitiationReceipt:
            _fail("managed_cleanup_v4_initiation_conflict")
        authenticate_cleanup_v4_initiation_receipt(
            existing,
            authenticator=authenticator,
            authentication_key_id=authentication_key_id,
        )
        if existing != expected:
            _fail("managed_cleanup_v4_initiation_conflict")
        return ManagedCleanupV4Transition(existing, True)
    if terminal is not None:
        _fail("managed_cleanup_v4_lifecycle_invalid")
    stored = await lifecycle.put_initiation(expected)
    if type(stored) is not ManagedCleanupV4InitiationReceipt:
        _fail("managed_cleanup_v4_initiation_readback_invalid")
    authenticate_cleanup_v4_initiation_receipt(
        stored,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    if stored != expected:
        _fail("managed_cleanup_v4_initiation_readback_invalid")
    return ManagedCleanupV4Transition(stored, False)


async def complete_managed_cleanup_v4(
    *,
    authority: ManagedCleanupV4Authority,
    terminal_bindings: ManagedCleanupV4TerminalBindings,
    lifecycle: ManagedCleanupV4LifecyclePort,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> ManagedCleanupV4Transition:
    _authority(authority)
    _authentication(authenticator, authentication_key_id)
    if type(terminal_bindings) is not ManagedCleanupV4TerminalBindings:
        _fail("managed_cleanup_v4_absence_terminal_invalid")
    terminal_bindings.__post_init__()
    _bindings_match_authority(terminal_bindings, authority)
    initiation = await lifecycle.read_initiation(authority.run_id_sha256)
    expected_initiation = build_cleanup_v4_initiation_receipt(
        authority,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    if type(initiation) is not ManagedCleanupV4InitiationReceipt:
        _fail("managed_cleanup_v4_lifecycle_invalid")
    authenticate_cleanup_v4_initiation_receipt(
        initiation,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    if initiation != expected_initiation:
        _fail("managed_cleanup_v4_lifecycle_invalid")
    expected = build_cleanup_v4_terminal_receipt(
        authority,
        initiation,
        terminal_bindings,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    existing = await lifecycle.read_terminal(authority.run_id_sha256)
    if existing is not None:
        if type(existing) is not ManagedCleanupV4TerminalReceipt:
            _fail("managed_cleanup_v4_terminal_conflict")
        authenticate_cleanup_v4_terminal_receipt(
            existing,
            authenticator=authenticator,
            authentication_key_id=authentication_key_id,
        )
        if existing != expected:
            _fail("managed_cleanup_v4_terminal_conflict")
        return ManagedCleanupV4Transition(existing, True)
    stored = await lifecycle.put_terminal(expected)
    if type(stored) is not ManagedCleanupV4TerminalReceipt:
        _fail("managed_cleanup_v4_terminal_readback_invalid")
    authenticate_cleanup_v4_terminal_receipt(
        stored,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    if stored != expected:
        _fail("managed_cleanup_v4_terminal_readback_invalid")
    return ManagedCleanupV4Transition(stored, False)


def build_cleanup_v4_terminal_bindings(
    *,
    inventory_terminal_sha256: str,
    qdrant_absence_pass_sha256: tuple[str, str],
    graphiti_absence_pass_sha256: tuple[str, str],
    cognee_evidence_sha256: str,
    context_sha256: str | None,
    a2_terminal_sha256: str | None,
) -> ManagedCleanupV4TerminalBindings:
    values: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA,
        "inventory_terminal_sha256": inventory_terminal_sha256,
        "qdrant_absence_pass_sha256": list(qdrant_absence_pass_sha256),
        "graphiti_absence_pass_sha256": list(graphiti_absence_pass_sha256),
        "cognee_disposition": "not_projected",
        "cognee_projected_count": 0,
        "cognee_evidence_sha256": cognee_evidence_sha256,
        "context_sha256": context_sha256,
        "a2_terminal_sha256": a2_terminal_sha256,
    }
    return ManagedCleanupV4TerminalBindings(
        inventory_terminal_sha256=inventory_terminal_sha256,
        qdrant_absence_pass_sha256=qdrant_absence_pass_sha256,
        graphiti_absence_pass_sha256=graphiti_absence_pass_sha256,
        cognee_disposition="not_projected",
        cognee_projected_count=0,
        cognee_evidence_sha256=cognee_evidence_sha256,
        context_sha256=context_sha256,
        a2_terminal_sha256=a2_terminal_sha256,
        bindings_sha256=commitment("cleanup-terminal-bindings/v4", values),
    )


def build_cleanup_v4_initiation_receipt(
    authority: ManagedCleanupV4Authority,
    *,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> ManagedCleanupV4InitiationReceipt:
    _authority(authority)
    capability, authentication_authority_sha256 = _authentication(
        authenticator, authentication_key_id
    )
    values = {
        "schema_version": INITIATION_SCHEMA,
        "run_id_sha256": authority.run_id_sha256,
        "authority_kind": authority.kind,
        "authority_sha256": authority.authority_sha256,
        "authentication_key_id": authentication_key_id,
        "authentication_authority_sha256": authentication_authority_sha256,
        "state": "cleanup_pending",
    }
    receipt_sha256 = commitment("cleanup-initiation/v4", values)
    return ManagedCleanupV4InitiationReceipt(
        run_id_sha256=authority.run_id_sha256,
        authority_kind=authority.kind,
        authority_sha256=authority.authority_sha256,
        authentication_key_id=authentication_key_id,
        authentication_authority_sha256=authentication_authority_sha256,
        state="cleanup_pending",
        receipt_sha256=receipt_sha256,
        receipt_mac_sha256=_sign(capability, "cleanup-initiation", receipt_sha256),
    )


def build_cleanup_v4_terminal_receipt(
    authority: ManagedCleanupV4Authority,
    initiation: ManagedCleanupV4InitiationReceipt,
    bindings: ManagedCleanupV4TerminalBindings,
    *,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> ManagedCleanupV4TerminalReceipt:
    _authority(authority)
    capability, authentication_authority_sha256 = _authentication(
        authenticator, authentication_key_id
    )
    if initiation != build_cleanup_v4_initiation_receipt(
        authority,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    ):
        _fail("managed_cleanup_v4_initiation_conflict")
    _bindings_match_authority(bindings, authority)
    values: dict[str, object] = {
        "schema_version": TERMINAL_SCHEMA,
        "run_id_sha256": authority.run_id_sha256,
        "authority_kind": authority.kind,
        "authority_sha256": authority.authority_sha256,
        "authentication_key_id": authentication_key_id,
        "authentication_authority_sha256": authentication_authority_sha256,
        "cleanup_initiation_receipt_sha256": initiation.receipt_sha256,
        "terminal_bindings": bindings.payload(),
        "state": "cleanup_complete",
    }
    receipt_sha256 = commitment("cleanup-terminal/v4", values)
    return ManagedCleanupV4TerminalReceipt(
        run_id_sha256=authority.run_id_sha256,
        authority_kind=authority.kind,
        authority_sha256=authority.authority_sha256,
        authentication_key_id=authentication_key_id,
        authentication_authority_sha256=authentication_authority_sha256,
        cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
        terminal_bindings=bindings,
        state="cleanup_complete",
        receipt_sha256=receipt_sha256,
        receipt_mac_sha256=_sign(capability, "cleanup-terminal", receipt_sha256),
    )


def authenticate_cleanup_v4_initiation_receipt(
    receipt: ManagedCleanupV4InitiationReceipt,
    *,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> None:
    if type(receipt) is not ManagedCleanupV4InitiationReceipt:
        _fail("managed_cleanup_v4_initiation_invalid")
    receipt.__post_init__()
    _authenticate_receipt(
        receipt.authentication_key_id,
        receipt.authentication_authority_sha256,
        receipt.receipt_sha256,
        receipt.receipt_mac_sha256,
        domain="cleanup-initiation",
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )


def authenticate_cleanup_v4_terminal_receipt(
    receipt: ManagedCleanupV4TerminalReceipt,
    *,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> None:
    if type(receipt) is not ManagedCleanupV4TerminalReceipt:
        _fail("managed_cleanup_v4_terminal_invalid")
    receipt.__post_init__()
    _authenticate_receipt(
        receipt.authentication_key_id,
        receipt.authentication_authority_sha256,
        receipt.receipt_sha256,
        receipt.receipt_mac_sha256,
        domain="cleanup-terminal",
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )


def _bindings_match_authority(
    bindings: ManagedCleanupV4TerminalBindings, authority: ManagedCleanupV4Authority
) -> None:
    expected = (
        (authority.context_sha256, authority.a2_terminal_sha256)
        if authority.kind == "strict_v4_a2"
        else (None, None)
    )
    if (bindings.context_sha256, bindings.a2_terminal_sha256) != expected:
        _fail("managed_cleanup_v4_terminal_authority_conflict")


def _terminal_matches_authority(
    terminal: ManagedCleanupV4TerminalReceipt,
    authority: ManagedCleanupV4Authority,
    *,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> None:
    if type(terminal) is not ManagedCleanupV4TerminalReceipt:
        _fail("managed_cleanup_v4_terminal_invalid")
    authenticate_cleanup_v4_terminal_receipt(
        terminal,
        authenticator=authenticator,
        authentication_key_id=authentication_key_id,
    )
    _bindings_match_authority(terminal.terminal_bindings, authority)
    if (
        terminal.run_id_sha256,
        terminal.authority_kind,
        terminal.authority_sha256,
    ) != (authority.run_id_sha256, authority.kind, authority.authority_sha256):
        _fail("managed_cleanup_v4_terminal_conflict")


def _authenticate_receipt(
    receipt_key_id: str,
    authority_sha256: str,
    receipt_sha256: str,
    receipt_mac_sha256: str,
    *,
    domain: str,
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    authentication_key_id: str,
) -> None:
    capability, authentication_authority_sha256 = _authentication(
        authenticator, authentication_key_id
    )
    if (
        receipt_key_id != authentication_key_id
        or authority_sha256 != authentication_authority_sha256
    ):
        _fail("managed_cleanup_v4_receipt_authentication_invalid")
    expected_mac_sha256 = _sign(capability, domain, receipt_sha256)
    if not hmac.compare_digest(expected_mac_sha256, receipt_mac_sha256):
        _fail("managed_cleanup_v4_receipt_authentication_invalid")


def _authentication(
    value: object, authentication_key_id: object
) -> tuple[ManagedCleanupV4ReceiptAuthenticatorPort, str]:
    if not _key_id(authentication_key_id):
        _fail("managed_cleanup_v4_authentication_invalid")
    capability = cast(ManagedCleanupV4ReceiptAuthenticatorPort, value)
    try:
        authority_sha256 = capability.authority_sha256
        signer = capability.sign
        digest(authority_sha256)
    except Exception as exc:
        raise ManagedCleanupV4AuthorityError("managed_cleanup_v4_authentication_invalid") from exc
    if not callable(signer):
        _fail("managed_cleanup_v4_authentication_invalid")
    return capability, cast(str, authority_sha256)


def _sign(
    authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
    domain: str,
    payload_sha256: str,
) -> str:
    try:
        digest(payload_sha256)
        mac_sha256 = authenticator.sign(domain, payload_sha256)
        digest(mac_sha256)
    except Exception as exc:
        raise ManagedCleanupV4AuthorityError("managed_cleanup_v4_authentication_invalid") from exc
    return mac_sha256


def _key_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _authority(value: object) -> None:
    if type(value) is not ManagedCleanupV4Authority:
        _fail("managed_cleanup_v4_authority_invalid")
    value.__post_init__()


def _fail(code: str) -> None:
    raise ManagedCleanupV4AuthorityError(code)


__all__ = tuple(
    name
    for name in globals()
    if name.startswith(("ManagedCleanupV4", "build_cleanup_v4", "complete_", "initiate_"))
    or name in {"EVIDENCE_SCHEMA", "INITIATION_SCHEMA", "TERMINAL_SCHEMA"}
)
