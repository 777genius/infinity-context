"""Authenticate immutable extraction terminal handoffs for the run provider."""

from __future__ import annotations

import hmac
from pathlib import Path

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    ManagedFullRunExtractionTerminal,
)
from infinity_context_runtime_bridge.json_boundary import exact_object
from infinity_context_runtime_bridge.process_files import (
    read_private_json,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA,
    PublishableExtractionRunTerminal,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.processes.publishable_full_extraction_terminal_seal import (
    PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT,
    PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA,
    extraction_terminal_seal_hmac,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)

EXTRACTION_TERMINAL_SEAL_SCHEMA = PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_SCHEMA
_MAX_TERMINAL_BYTES = PUBLISHABLE_EXTRACTION_TERMINAL_SEAL_BYTES_LIMIT


def open_sealed_extraction_suite(
    paths: tuple[Path, Path],
    *,
    authentication_keys: tuple[bytes, bytes],
) -> PublishableExtractionSuiteReadback:
    """Read two HMAC-authenticated, already sealed extraction terminals."""

    if (
        type(paths) is not tuple
        or len(paths) != 2
        or type(authentication_keys) is not tuple
        or len(authentication_keys) != 2
    ):
        _fail("publishable_run_provider_extraction_invalid")
    terminals = tuple(
        _read_terminal(path, authentication_key=key)
        for path, key in zip(paths, authentication_keys, strict=True)
    )
    try:
        return PublishableExtractionSuiteReadback(
            locomo_terminal=terminals[0],
            longmemeval_terminal=terminals[1],
        )
    except Exception:
        _fail("publishable_run_provider_extraction_invalid")


def _read_terminal(path: Path, *, authentication_key: bytes) -> PublishableExtractionRunTerminal:
    try:
        payload = read_private_json(path, maximum_bytes=_MAX_TERMINAL_BYTES)
        sealed = exact_object(
            payload,
            required=frozenset({"authentication_hmac_sha256", "schema_version", "terminal"}),
            label="publishable_extraction_terminal_seal",
        )
        if sealed["schema_version"] != EXTRACTION_TERMINAL_SEAL_SCHEMA:
            raise ValueError
        terminal_payload = sealed["terminal"]
        if type(terminal_payload) is not dict:
            raise ValueError
        expected = extraction_terminal_seal_hmac(
            terminal_payload, authentication_key=authentication_key
        )
        observed = sealed["authentication_hmac_sha256"]
        if type(observed) is not str or not hmac.compare_digest(expected, observed):
            raise ValueError
        return _terminal(terminal_payload)
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_provider_extraction_invalid")


def _terminal(value: dict[str, object]) -> PublishableExtractionRunTerminal:
    keys = frozenset(
        {
            "a1_manifest_context_sha256",
            "a1_terminal_commitment_sha256",
            "a2_terminal_commitment_sha256",
            "admission_commitment_sha256",
            "binding_commitment_sha256",
            "dataset_sha256",
            "expected_receipt_count",
            "ingestion_root_sha256",
            "journal_head_event_sha256",
            "journal_manifest_commitment_sha256",
            "journal_state_commitment_sha256",
            "ledger_terminal",
            "methodology_commitment_sha256",
            "paid_go_ready",
            "preparation_receipt_sha256",
            "profile_id",
            "run_id_sha256",
            "runtime_binding_commitment_sha256",
            "scheduler_bridge_runtime_authority_sha256",
            "schema_version",
            "terminal_commitment_sha256",
        }
    )
    item = exact_object(value, required=keys, label="publishable_extraction_terminal")
    if (
        item["schema_version"] != PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA
        or item["paid_go_ready"] is not False
    ):
        raise ValueError
    ledger = _ledger(item["ledger_terminal"])
    terminal = PublishableExtractionRunTerminal(
        profile_id=item["profile_id"],
        run_id_sha256=item["run_id_sha256"],
        binding_commitment_sha256=item["binding_commitment_sha256"],
        methodology_commitment_sha256=item["methodology_commitment_sha256"],
        admission_commitment_sha256=item["admission_commitment_sha256"],
        ingestion_root_sha256=item["ingestion_root_sha256"],
        a1_terminal_commitment_sha256=item["a1_terminal_commitment_sha256"],
        a1_manifest_context_sha256=item["a1_manifest_context_sha256"],
        runtime_binding_commitment_sha256=item["runtime_binding_commitment_sha256"],
        scheduler_bridge_runtime_authority_sha256=(
            item["scheduler_bridge_runtime_authority_sha256"]
        ),
        preparation_receipt_sha256=item["preparation_receipt_sha256"],
        dataset_sha256=item["dataset_sha256"],
        a2_terminal_commitment_sha256=item["a2_terminal_commitment_sha256"],
        expected_receipt_count=item["expected_receipt_count"],
        journal_manifest_commitment_sha256=item["journal_manifest_commitment_sha256"],
        journal_state_commitment_sha256=item["journal_state_commitment_sha256"],
        journal_head_event_sha256=item["journal_head_event_sha256"],
        ledger_terminal=ledger,
    )
    if terminal.terminal_commitment_sha256 != item["terminal_commitment_sha256"]:
        raise ValueError
    return terminal


def _ledger(value: object) -> ManagedFullRunExtractionTerminal:
    item = exact_object(
        value,
        required=frozenset(
            {
                "context_commitment_sha256",
                "page_count",
                "receipt_count",
                "receipt_pages_root_sha256",
                "schema_version",
                "terminal_commitment_sha256",
                "usage",
            }
        ),
        label="publishable_extraction_ledger_terminal",
    )
    usage = exact_object(
        item["usage"],
        required=frozenset({"completion_tokens", "prompt_tokens", "total_tokens"}),
        label="publishable_extraction_ledger_usage",
    )
    if item["schema_version"] != FULL_RUN_EXTRACTION_LEDGER_SCHEMA:
        raise ValueError
    return ManagedFullRunExtractionTerminal(
        context_commitment_sha256=item["context_commitment_sha256"],
        receipt_count=item["receipt_count"],
        page_count=item["page_count"],
        receipt_pages_root_sha256=item["receipt_pages_root_sha256"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
        terminal_commitment_sha256=item["terminal_commitment_sha256"],
    )


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "EXTRACTION_TERMINAL_SEAL_SCHEMA",
    "extraction_terminal_seal_hmac",
    "open_sealed_extraction_suite",
)
