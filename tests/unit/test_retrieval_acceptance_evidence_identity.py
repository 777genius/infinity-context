"""Execute the actual CI evidence guard against valid and substituted JUnit cases."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = (
    (
        "tests.e2e.test_locator_retrieval_qdrant_e2e",
        "test_real_qdrant_large_profile_resumes_attests_and_physically_deletes",
    ),
    *(
        ("tests.e2e.test_context_derived_collection_postgres", name)
        for name in (
            "test_mounted_postgres_context_revalidates_delete_after_early_lane_hydration",
            "test_postgres_connection_wait_cancellation_closes_uows_and_next_collection_runs",
            "test_populated_qdrant_mounted_context_preserves_output_and_rejects_stale_hit",
        )
    ),
    *(
        (
            "tests.e2e.test_context_vector_recall_qdrant",
            f"test_real_qdrant_reserve_recovers_evidence_without_widening_healthy_context[{kind}]",
        )
        for kind in ("missing", "deleted", "foreign")
    ),
    (
        "tests.e2e.test_context_vector_recall_qdrant",
        "test_mounted_real_store_query_fanout_records_paired_latency_without_timing_gate",
    ),
)


@pytest.mark.parametrize(
    "mutation",
    ["none", "name", "module", "duplicate", "missing", "extra", "skipped", "error", "failure"],
)
def test_ci_evidence_requires_exact_case_identities_and_success(tmp_path, monkeypatch, mutation):
    workflow = (ROOT / ".github/workflows/infinity-context-ci.yml").read_text()
    guard = dedent(workflow.split("<<'PYTEST_EVIDENCE'\n", 1)[1].split("PYTEST_EVIDENCE", 1)[0])
    suite = ET.Element("testsuite")
    cases = [
        ET.SubElement(suite, "testcase", classname=module, name=name) for module, name in EXPECTED
    ]
    if mutation == "name":
        cases[0].set("name", "unrelated_passing_case")
    elif mutation == "module":
        cases[0].set("classname", "wrong.module")
    elif mutation == "duplicate":
        cases[0].attrib.update(cases[1].attrib)
    elif mutation == "missing":
        suite.remove(cases[0])
    elif mutation == "extra":
        ET.SubElement(suite, "testcase", classname="wrong.module", name="extra")
    elif mutation in {"skipped", "error", "failure"}:
        ET.SubElement(cases[0], mutation)
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "test-results"
    destination.mkdir()
    ET.ElementTree(suite).write(destination / "qdrant-locator-acceptance.xml")
    (destination / "retrieval-benchmark.json").write_text("{}")
    if mutation == "none":
        exec(guard, {})
    else:
        with pytest.raises(AssertionError):
            exec(guard, {})
