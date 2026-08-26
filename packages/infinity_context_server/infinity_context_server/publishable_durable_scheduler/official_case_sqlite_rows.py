"""Canonical row authentication material for official-case SQLite."""

from __future__ import annotations

import sqlite3

from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerOfficialCaseKey,
)


def ingest_material(configuration_sha: str, values: tuple[object, ...]) -> dict[str, object]:
    return {"configuration_sha256": configuration_sha, "row": list(values)}


def sealed_row_material(
    configuration_sha: str,
    values: tuple[object, ...],
    material_sha: str,
    key: SchedulerOfficialCaseKey,
) -> dict[str, object]:
    return {
        "configuration_sha256": configuration_sha,
        "key": key.material(),
        "material_sha256": material_sha,
        "row": list(values),
    }


def page_mac_material(configuration_sha: str, values: tuple[object, ...]) -> dict[str, object]:
    return {"configuration_sha256": configuration_sha, "page": list(values)}


def verify_page_row(row, values, auth, configuration_sha: str) -> None:
    observed = tuple(
        row[name] for name in ("page_index", "start_sequence", "row_count", "page_sha256")
    )
    if observed != values or not auth.verify(
        "case/page", page_mac_material(configuration_sha, observed), row["page_mac"]
    ):
        _fail("scheduler_official_case_authority_page_divergent")


def case_count(connection: sqlite3.Connection) -> int:
    return _count(connection, "official_cases")


def page_count(connection: sqlite3.Connection) -> int:
    return _count(connection, "authority_pages")


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
    if row is None or type(row[0]) is not int:
        _fail("scheduler_official_case_authority_count_invalid")
    return row[0]


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "case_count",
    "ingest_material",
    "page_count",
    "page_mac_material",
    "sealed_row_material",
    "verify_page_row",
)
