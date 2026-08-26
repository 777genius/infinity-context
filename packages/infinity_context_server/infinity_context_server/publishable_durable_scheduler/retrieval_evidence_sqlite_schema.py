"""Exact schema, configuration, and terminal for retrieval evidence SQLite."""

from __future__ import annotations

import sqlite3
from typing import Final

from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    SchedulerOfficialAuthorityError,
    SchedulerRetrievalEvidenceAuthorityTerminal,
    SchedulerRetrievalRunScope,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_integrity import (
    SchedulerOfficialAuthorityAuthenticator,
    authority_digest,
    canonical_mapping,
    canonical_text,
    require_digest,
    require_exact_keys,
    schema_fingerprint,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_scope_codec import (
    retrieval_run_scopes_from_material,
    retrieval_run_scopes_material,
)

KIND: Final = "retrieval-evidence"
CONFIG_KEYS: Final = frozenset(
    {"authority_kind", "case_authority_root_sha256", "run_scopes", "schema_version"}
)
TERMINAL_BODY_KEYS: Final = frozenset(
    {
        "authority_kind",
        "configuration_sha256",
        "group_count",
        "groups_root_sha256",
        "page_count",
        "pages_root_sha256",
        "result_row_count",
        "result_rows_root_sha256",
        "schema_fingerprint_sha256",
        "schema_version",
    }
)
TERMINAL_KEYS: Final = TERMINAL_BODY_KEYS | {
    "authority_root_sha256",
    "terminal_commitment_sha256",
    "terminal_hmac_sha256",
}

SCHEMA: Final = (
    """CREATE TABLE authority_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version TEXT NOT NULL,
        schema_fingerprint_sha256 TEXT NOT NULL,
        configuration_sha256 TEXT NOT NULL,
        configuration_json TEXT NOT NULL,
        configuration_mac TEXT NOT NULL,
        terminal_json TEXT,
        terminal_mac TEXT
    ) STRICT""",
    """CREATE TABLE authority_pages(
        page_index INTEGER PRIMARY KEY CHECK(page_index>=0),
        start_sequence INTEGER NOT NULL UNIQUE CHECK(start_sequence>=0),
        group_count INTEGER NOT NULL CHECK(group_count>0 AND group_count<=64),
        result_row_count INTEGER NOT NULL CHECK(result_row_count>=0),
        page_sha256 TEXT NOT NULL UNIQUE,
        page_mac TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE retrieval_groups(
        sequence INTEGER PRIMARY KEY CHECK(sequence>=0),
        page_index INTEGER NOT NULL REFERENCES authority_pages(page_index),
        run_id TEXT NOT NULL,
        case_index INTEGER NOT NULL CHECK(case_index>=0),
        case_id TEXT NOT NULL,
        case_alias TEXT NOT NULL,
        backend_index INTEGER NOT NULL CHECK(backend_index IN (0,1)),
        case_key_json TEXT NOT NULL,
        case_material_sha256 TEXT NOT NULL,
        unrooted_key_json TEXT NOT NULL,
        result_count INTEGER NOT NULL CHECK(result_count>=0 AND result_count<=50),
        result_rows_root_sha256 TEXT NOT NULL,
        group_commitment_sha256 TEXT NOT NULL UNIQUE,
        ingest_mac TEXT NOT NULL,
        material_sha256 TEXT,
        sealed_mac TEXT,
        UNIQUE(run_id,case_index,backend_index)
    ) STRICT""",
    """CREATE UNIQUE INDEX retrieval_groups_exact_lookup
        ON retrieval_groups(run_id,case_index,case_id,case_alias,backend_index)""",
    """CREATE INDEX retrieval_groups_page_sequence
        ON retrieval_groups(page_index,sequence)""",
    """CREATE TABLE retrieval_rows(
        group_sequence INTEGER NOT NULL REFERENCES retrieval_groups(sequence),
        rank INTEGER NOT NULL CHECK(rank>=1 AND rank<=50),
        memory_json TEXT NOT NULL,
        row_commitment_sha256 TEXT NOT NULL UNIQUE,
        ingest_mac TEXT NOT NULL,
        sealed_mac TEXT,
        PRIMARY KEY(group_sequence,rank)
    ) STRICT""",
)


def configuration(
    scopes: tuple[SchedulerRetrievalRunScope, ...], case_authority_root_sha256: str
) -> dict[str, object]:
    return {
        "authority_kind": KIND,
        "case_authority_root_sha256": require_digest(
            case_authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_case_root_invalid",
        ),
        "run_scopes": retrieval_run_scopes_material(scopes),
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }


def scopes_from_configuration(
    value: dict[str, object],
) -> tuple[tuple[SchedulerRetrievalRunScope, ...], str]:
    require_exact_keys(
        value,
        CONFIG_KEYS,
        code="scheduler_retrieval_evidence_authority_config_invalid",
    )
    if (
        value.get("authority_kind") != KIND
        or value.get("schema_version") != SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION
    ):
        _fail("scheduler_retrieval_evidence_authority_config_invalid")
    root = require_digest(
        value.get("case_authority_root_sha256"),
        code="scheduler_retrieval_evidence_authority_config_invalid",
    )
    return retrieval_run_scopes_from_material(value.get("run_scopes")), root


def meta_values(configuration_value: dict[str, object]) -> tuple[object, ...]:
    configuration_sha = authority_digest("retrieval/configuration", configuration_value)
    return (
        1,
        SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
        schema_fingerprint(SCHEMA),
        configuration_sha,
        canonical_text(configuration_value),
    )


def verify_meta(
    connection: sqlite3.Connection,
    auth: SchedulerOfficialAuthorityAuthenticator,
    *,
    expected_configuration: dict[str, object] | None,
) -> tuple[
    dict[str, object],
    str,
    SchedulerRetrievalEvidenceAuthorityTerminal | None,
]:
    row = connection.execute("SELECT * FROM authority_meta WHERE singleton=1").fetchone()
    if row is None:
        _fail("scheduler_retrieval_evidence_authority_meta_missing")
    observed_configuration = canonical_mapping(
        row["configuration_json"],
        code="scheduler_retrieval_evidence_authority_config_invalid",
    )
    scopes_from_configuration(observed_configuration)
    if expected_configuration is not None and observed_configuration != expected_configuration:
        _fail("scheduler_retrieval_evidence_authority_config_cross_wire")
    expected = meta_values(observed_configuration)
    observed = tuple(
        row[name]
        for name in (
            "singleton",
            "schema_version",
            "schema_fingerprint_sha256",
            "configuration_sha256",
            "configuration_json",
        )
    )
    if observed != expected or not auth.verify(
        "retrieval/configuration", observed, row["configuration_mac"]
    ):
        _fail("scheduler_retrieval_evidence_authority_authentication_invalid")
    terminal = terminal_from_meta(
        row["terminal_json"],
        row["terminal_mac"],
        auth=auth,
        configuration_sha256=expected[3],
    )
    return observed_configuration, expected[3], terminal


def terminal_from_meta(
    terminal_json: object,
    terminal_mac: object,
    *,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
) -> SchedulerRetrievalEvidenceAuthorityTerminal | None:
    if terminal_json is None and terminal_mac is None:
        return None
    payload = canonical_mapping(
        terminal_json,
        code="scheduler_retrieval_evidence_authority_terminal_invalid",
    )
    require_exact_keys(
        payload,
        TERMINAL_KEYS,
        code="scheduler_retrieval_evidence_authority_terminal_invalid",
    )
    terminal = terminal_from_payload(payload)
    if not auth.verify(
        "retrieval/meta-terminal",
        {"configuration_sha256": configuration_sha256, "terminal": payload},
        terminal_mac,
    ):
        _fail("scheduler_retrieval_evidence_authority_authentication_invalid")
    verify_terminal_auth(auth, terminal)
    return terminal


def terminal_from_payload(
    payload: dict[str, object],
) -> SchedulerRetrievalEvidenceAuthorityTerminal:
    if (
        payload.get("authority_kind") != KIND
        or payload.get("schema_version") != SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION
    ):
        _fail("scheduler_retrieval_evidence_authority_terminal_invalid")
    return SchedulerRetrievalEvidenceAuthorityTerminal(
        schema_fingerprint_sha256=payload["schema_fingerprint_sha256"],
        configuration_sha256=payload["configuration_sha256"],
        group_count=payload["group_count"],
        result_row_count=payload["result_row_count"],
        page_count=payload["page_count"],
        pages_root_sha256=payload["pages_root_sha256"],
        groups_root_sha256=payload["groups_root_sha256"],
        result_rows_root_sha256=payload["result_rows_root_sha256"],
        terminal_commitment_sha256=payload["terminal_commitment_sha256"],
        terminal_hmac_sha256=payload["terminal_hmac_sha256"],
        authority_root_sha256=payload["authority_root_sha256"],
    )


def terminal_payload(
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal,
) -> dict[str, object]:
    return {
        **terminal_body(terminal),
        "authority_root_sha256": terminal.authority_root_sha256,
        "terminal_commitment_sha256": terminal.terminal_commitment_sha256,
        "terminal_hmac_sha256": terminal.terminal_hmac_sha256,
    }


def terminal_body(
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal,
) -> dict[str, object]:
    return {
        "authority_kind": KIND,
        "configuration_sha256": terminal.configuration_sha256,
        "group_count": terminal.group_count,
        "groups_root_sha256": terminal.groups_root_sha256,
        "page_count": terminal.page_count,
        "pages_root_sha256": terminal.pages_root_sha256,
        "result_row_count": terminal.result_row_count,
        "result_rows_root_sha256": terminal.result_rows_root_sha256,
        "schema_fingerprint_sha256": terminal.schema_fingerprint_sha256,
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }


def build_terminal(
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
    state: tuple[int, int, int, str, str, str],
) -> SchedulerRetrievalEvidenceAuthorityTerminal:
    group_count, result_count, page_count, pages_root, groups_root, rows_root = state
    body = {
        "authority_kind": KIND,
        "configuration_sha256": configuration_sha256,
        "group_count": group_count,
        "groups_root_sha256": groups_root,
        "page_count": page_count,
        "pages_root_sha256": pages_root,
        "result_row_count": result_count,
        "result_rows_root_sha256": rows_root,
        "schema_fingerprint_sha256": schema_fingerprint(SCHEMA),
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }
    commitment = authority_digest("retrieval/terminal", body)
    terminal_hmac = auth.sign("retrieval/terminal", {"body": body, "commitment": commitment})
    root = auth.sign(
        "retrieval/root",
        {"body": body, "commitment": commitment, "terminal_hmac": terminal_hmac},
    )
    return SchedulerRetrievalEvidenceAuthorityTerminal(
        schema_fingerprint_sha256=body["schema_fingerprint_sha256"],
        configuration_sha256=configuration_sha256,
        group_count=group_count,
        result_row_count=result_count,
        page_count=page_count,
        pages_root_sha256=pages_root,
        groups_root_sha256=groups_root,
        result_rows_root_sha256=rows_root,
        terminal_commitment_sha256=commitment,
        terminal_hmac_sha256=terminal_hmac,
        authority_root_sha256=root,
    )


def verify_terminal_auth(
    auth: SchedulerOfficialAuthorityAuthenticator,
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal,
) -> None:
    body = terminal_body(terminal)
    commitment = authority_digest("retrieval/terminal", body)
    if (
        terminal.schema_fingerprint_sha256 != schema_fingerprint(SCHEMA)
        or terminal.terminal_commitment_sha256 != commitment
        or not auth.verify(
            "retrieval/terminal",
            {"body": body, "commitment": commitment},
            terminal.terminal_hmac_sha256,
        )
        or not auth.verify(
            "retrieval/root",
            {
                "body": body,
                "commitment": commitment,
                "terminal_hmac": terminal.terminal_hmac_sha256,
            },
            terminal.authority_root_sha256,
        )
    ):
        _fail("scheduler_retrieval_evidence_authority_terminal_authentication_invalid")


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "KIND",
    "SCHEMA",
    "build_terminal",
    "configuration",
    "meta_values",
    "scopes_from_configuration",
    "terminal_payload",
    "verify_meta",
    "verify_terminal_auth",
)
