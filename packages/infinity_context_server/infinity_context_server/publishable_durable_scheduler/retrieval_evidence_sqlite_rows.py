"""Canonical row authentication material for retrieval evidence SQLite."""

from __future__ import annotations

import sqlite3

from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)


def group_values(row: sqlite3.Row) -> tuple[object, ...]:
    return tuple(
        row[name]
        for name in (
            "sequence",
            "page_index",
            "run_id",
            "case_index",
            "case_id",
            "case_alias",
            "backend_index",
            "case_key_json",
            "case_material_sha256",
            "unrooted_key_json",
            "result_count",
            "result_rows_root_sha256",
            "group_commitment_sha256",
        )
    )


def result_values(row: sqlite3.Row) -> tuple[object, ...]:
    return tuple(
        row[name] for name in ("group_sequence", "rank", "memory_json", "row_commitment_sha256")
    )


def group_ingest_material(configuration_sha: str, values: tuple[object, ...]) -> dict[str, object]:
    return {"configuration_sha256": configuration_sha, "group": list(values)}


def group_sealed_material(
    configuration_sha: str,
    values: tuple[object, ...],
    material_sha: str,
    key: object,
) -> dict[str, object]:
    return {
        "configuration_sha256": configuration_sha,
        "group": list(values),
        "key": key.material(),
        "material_sha256": material_sha,
    }


def result_ingest_material(
    configuration_sha: str,
    group_commitment: str,
    values: tuple[object, ...],
) -> dict[str, object]:
    return {
        "configuration_sha256": configuration_sha,
        "group_commitment_sha256": group_commitment,
        "result_row": list(values),
    }


def result_sealed_material(
    configuration_sha: str,
    group_commitment: str,
    material_sha: str,
    values: tuple[object, ...],
    key: object,
) -> dict[str, object]:
    return {
        "configuration_sha256": configuration_sha,
        "group_commitment_sha256": group_commitment,
        "group_material_sha256": material_sha,
        "key": key.material(),
        "result_row": list(values),
    }


def page_mac_material(configuration_sha: str, values: tuple[object, ...]) -> dict[str, object]:
    return {"configuration_sha256": configuration_sha, "page": list(values)}


def verify_page_row(row, values, auth, configuration_sha: str) -> None:
    observed = tuple(
        row[name]
        for name in (
            "page_index",
            "start_sequence",
            "group_count",
            "result_row_count",
            "page_sha256",
        )
    )
    if observed != values or not auth.verify(
        "retrieval/page", page_mac_material(configuration_sha, observed), row["page_mac"]
    ):
        _fail("scheduler_retrieval_evidence_authority_page_divergent")


def group_count(connection: sqlite3.Connection) -> int:
    return _count(connection, "retrieval_groups")


def result_count(connection: sqlite3.Connection) -> int:
    return _count(connection, "retrieval_rows")


def page_count(connection: sqlite3.Connection) -> int:
    return _count(connection, "authority_pages")


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
    if row is None or type(row[0]) is not int:
        _fail("scheduler_retrieval_evidence_authority_count_invalid")
    return row[0]


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "group_count",
    "group_ingest_material",
    "group_sealed_material",
    "group_values",
    "page_count",
    "page_mac_material",
    "result_count",
    "result_ingest_material",
    "result_sealed_material",
    "result_values",
    "verify_page_row",
)
