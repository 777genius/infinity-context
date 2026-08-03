"""Opaque admission capability for a fully sealed gold-blind execution."""

from __future__ import annotations

import hashlib
import hmac
import threading
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
)

_TOKEN = object()


@final
class VerifiedGoldBlindExecutionValidation:
    """Issued admission capability; serialized reports are never admission input."""

    __slots__ = ("__commitment", "__run_id", "__weakref__")

    def __init__(self, *, run_id: str, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Execution validations must be issued")
        self.__run_id = run_id
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("VerifiedGoldBlindExecutionValidation is final")

    def __repr__(self) -> str:
        return "VerifiedGoldBlindExecutionValidation(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("VerifiedGoldBlindExecutionValidation is nonserializable")


@dataclass(frozen=True, slots=True, repr=False)
class _ValidationSnapshot:
    ledger: object
    run_id: str
    generation: int
    commitment: str
    report: MappingProxyType[str, object]

    def __repr__(self) -> str:
        return "_ValidationSnapshot(<redacted>)"


@final
class _GoldBlindExecutionValidationRegistry:
    """Private issuer and integrity verifier for execution admission."""

    __slots__ = ("__lock", "__validations")

    def __init__(self) -> None:
        self.__lock = threading.RLock()
        self.__validations: weakref.WeakKeyDictionary[
            VerifiedGoldBlindExecutionValidation, _ValidationSnapshot
        ] = weakref.WeakKeyDictionary()

    def issue(
        self,
        *,
        ledger: object,
        run_id: str,
        generation: int,
        secret: bytes,
        report_fields: dict[str, object],
        schema_version: str,
    ) -> VerifiedGoldBlindExecutionValidation:
        commitment = _commitment(
            secret,
            schema_version=schema_version,
            fields=report_fields,
        )
        validation = VerifiedGoldBlindExecutionValidation(
            run_id=run_id,
            commitment=commitment,
            _token=_TOKEN,
        )
        report = MappingProxyType(
            {
                "schema_version": schema_version,
                **report_fields,
                "commitment": commitment,
            }
        )
        with self.__lock:
            self.__validations[validation] = _ValidationSnapshot(
                ledger,
                run_id,
                generation,
                commitment,
                report,
            )
        return validation

    def ledger_for(self, validation: object) -> object:
        if type(validation) is not VerifiedGoldBlindExecutionValidation:
            raise GoldBlindContractError("Execution validation type must be exact")
        with self.__lock:
            snapshot = self.__validations.get(validation)
        if snapshot is None:
            raise GoldBlindContractError("Execution validation registration is missing")
        return snapshot.ledger

    def report(
        self,
        validation: object,
        *,
        ledger: object,
        state_run_id: str,
        state_generation: int,
        sealed: bool,
        secret: bytes,
        report_fields: dict[str, object],
        schema_version: str,
    ) -> dict[str, object]:
        if type(validation) is not VerifiedGoldBlindExecutionValidation:
            raise GoldBlindContractError("Execution validation type must be exact")
        with self.__lock:
            snapshot = self.__validations.get(validation)
        if snapshot is None:
            raise GoldBlindContractError("Execution validation registration is missing")
        try:
            run_id = validation._VerifiedGoldBlindExecutionValidation__run_id
            commitment = validation._VerifiedGoldBlindExecutionValidation__commitment
        except Exception:
            raise GoldBlindContractError("Execution validation integrity failed") from None
        current = _commitment(
            secret,
            schema_version=schema_version,
            fields=report_fields,
        )
        expected_report = {
            "schema_version": schema_version,
            **report_fields,
            "commitment": current,
        }
        valid = (
            snapshot.ledger is ledger
            and sealed
            and state_generation == snapshot.generation
            and type(run_id) is str
            and run_id == snapshot.run_id == state_run_id
            and type(commitment) is str
            and hmac.compare_digest(commitment, snapshot.commitment)
            and hmac.compare_digest(current, snapshot.commitment)
            and dict(snapshot.report) == expected_report
        )
        if not valid:
            raise GoldBlindContractError("Execution validation integrity failed")
        return dict(snapshot.report)


def _commitment(secret: bytes, *, schema_version: str, fields: dict[str, object]) -> str:
    return hmac.new(
        secret,
        canonical_dispatch_json({"schema_version": schema_version, **fields}),
        hashlib.sha256,
    ).hexdigest()
