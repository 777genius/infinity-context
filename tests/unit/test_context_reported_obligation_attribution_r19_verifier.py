from __future__ import annotations

import ast
from pathlib import Path

import pytest
from infinity_context_core.application import context_source_sibling_policy
from infinity_context_core.application import context_source_siblings as facade
from infinity_context_core.application.context_attribution_lexicon import (
    REPORTING_BASE_FORMS,
    REPORTING_FINITE_FORMS,
    ReportingVerbKind,
    classify_reporting_verb,
)
from infinity_context_core.application.context_quote_scanner import scan_quotes
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_reported_obligation_attribution import (
    obligation_promotion_exclusion_spans,
    third_party_reported_obligation_spans,
)
from infinity_context_core.application.context_reporting_frames import (
    indirect_reporting_header_end,
    is_reporting_clause,
)

QUERY = "Which dispatch manifest must Morgan approve?"
DIRECT = "Morgan must approve the dispatch manifest"
ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "packages" / "infinity_context_core" / "infinity_context_core" / "application"

SPLIT_MODULES = {
    "context_attribution_lexicon": APPLICATION / "context_attribution_lexicon.py",
    "context_reporting_frames": APPLICATION / "context_reporting_frames.py",
    "context_quote_scanner": APPLICATION / "context_quote_scanner.py",
    "context_reported_obligation_attribution": (
        APPLICATION / "context_reported_obligation_attribution.py"
    ),
    "context_source_sibling_policy": APPLICATION / "context_source_sibling_policy.py",
    "context_source_siblings": APPLICATION / "context_source_siblings.py",
}


def _projection(*, query: str = QUERY, text: str):  # type: ignore[no-untyped-def]
    return facade.project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )


def _assert_reported_only(*, text: str, query: str = QUERY) -> None:
    spans = third_party_reported_obligation_spans(text)
    projection = _projection(query=query, text=text)

    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied
    assert spans
    assert any("approve" in text[start:end] for start, end in spans)


def _assert_direct(*, text: str, expected: str = DIRECT, query: str = QUERY) -> None:
    projection = _projection(query=query, text=text)

    assert facade.is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert projection.rank == 0
    assert projection.applied
    assert projection.text == expected
    assert projection.spans


@pytest.mark.parametrize("verb", sorted(REPORTING_FINITE_FORMS))
def test_r19_lexicon_and_reporting_frames_accept_every_declared_finite_verb(
    verb: str,
) -> None:
    assert classify_reporting_verb(verb) is ReportingVerbKind.FINITE
    assert is_reporting_clause(f"The cross-dock auditor {verb}")
    _assert_reported_only(text=f'The cross-dock auditor {verb}: "{DIRECT}."')


@pytest.mark.parametrize("verb", sorted(REPORTING_BASE_FORMS))
def test_r19_base_reporting_verbs_require_an_overt_plural_agent(verb: str) -> None:
    assert classify_reporting_verb(verb) is ReportingVerbKind.BASE
    assert is_reporting_clause(f"The rotating auditors {verb}")
    assert not is_reporting_clause(f"The archived news {verb}")


def test_r19_indirect_header_boundary_belongs_to_reporting_frames() -> None:
    text = f"The night auditors clearly stated that {DIRECT}."
    header_end = indirect_reporting_header_end(text=text, start=0, end=len(text))

    assert header_end is not None
    assert text[header_end:].strip() == f"{DIRECT}."
    _assert_reported_only(text=text)


@pytest.mark.parametrize(
    "header",
    (
        "the outage report",
        "the incident report",
        "status reports",
        "news reports",
        "daily reports",
        "quarterly reports",
    ),
)
def test_r19_noun_report_variants_do_not_impersonate_reporting_verbs(header: str) -> None:
    text = f'{header}: "{DIRECT}."'

    assert not is_reporting_clause(header)
    assert third_party_reported_obligation_spans(text) == ()
    assert facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )


@pytest.mark.parametrize(
    "reporter",
    (
        "D'Arcy",
        "O’Connor",
        "the crew's liaison",
        "the team’s night-shift coordinator",
        "the pilots' liaison",
        "O’Neill’s compliance auditor",
    ),
)
def test_r19_named_and_role_reporters_support_real_possessive_apostrophes(
    reporter: str,
) -> None:
    _assert_reported_only(text=f'{reporter} reported: "{DIRECT}."')


def test_r19_quote_scanner_records_balanced_nested_adjacent_and_suffix_metadata() -> None:
    text = (
        "The auditor stated: “Alex must sign the «loading» sheet.” and "
        f"“{DIRECT},” O’Connor confirmed."
    )
    scan = scan_quotes(text)

    assert scan.malformed_spans == ()
    assert len(scan.quotes) == 2
    first, second = scan.quotes
    assert text[first.body_start : first.body_end] == "Alex must sign the «loading» sheet."
    assert text[second.body_start : second.body_end] == f"{DIRECT},"
    assert second.previous_adjacent_quote == 0
    assert second.suffix_span is not None
    assert text[slice(*second.suffix_span)] == "O’Connor confirmed"


def test_r19_adjacent_and_multiple_quotes_inherit_only_the_local_reporter() -> None:
    alex = "Alex must sign the loading sheet."
    taylor = "Taylor should seal the route packet."
    text = f"The auditor stated: “{alex}” and “{DIRECT}.” or “{taylor}”; {DIRECT}."

    reported = tuple(text[start:end] for start, end in third_party_reported_obligation_spans(text))

    assert reported == (alex, f"{DIRECT}.", taylor)
    _assert_direct(text=text)


def test_r19_unreported_adjacent_quotes_do_not_invent_a_reporter() -> None:
    text = f"“Alex must sign the loading sheet.” and “{DIRECT}.”"

    assert third_party_reported_obligation_spans(text) == ()
    assert facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )


@pytest.mark.parametrize("connector", (" ", " and ", ", or "))
def test_r19_split_reported_quotes_are_excluded_from_direct_promotion(
    connector: str,
) -> None:
    text = f"The auditor stated: “Morgan must”{connector}“approve the dispatch manifest.”"
    exclusions = obligation_promotion_exclusion_spans(text)
    projection = _projection(text=text)

    assert exclusions
    assert any(start <= text.index("Morgan") < end for start, end in exclusions)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize("opener", ('"', "'", "“", "‘"))
def test_r19_unclosed_straight_and_curly_quotes_fail_closed_for_promotion(
    opener: str,
) -> None:
    text = f"The auditor reported: {opener}{DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    assert obligation_promotion_exclusion_spans(text)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert not _projection(text=text).applied


@pytest.mark.parametrize(
    "quoted",
    (
        f'"{DIRECT}.”',
        f'“{DIRECT}."',
        f"'{DIRECT}.’",
        f"‘{DIRECT}.'",
    ),
)
def test_r19_mixed_unclosed_quotes_fail_closed_for_promotion(quoted: str) -> None:
    text = f"The auditor reported: {quoted}"

    assert third_party_reported_obligation_spans(text) == ()
    assert obligation_promotion_exclusion_spans(text)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )


@pytest.mark.parametrize(
    "quoted",
    (
        f"”{DIRECT}.“",
        f"’{DIRECT}.‘",
    ),
)
def test_r19_reversed_curly_quotes_cannot_leak_into_direct_promotion(quoted: str) -> None:
    text = f"The auditor reported: {quoted}"

    assert third_party_reported_obligation_spans(text) == ()
    assert obligation_promotion_exclusion_spans(text)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert not _projection(text=text).applied


@pytest.mark.parametrize("opener", ('"', "“", "‘"))
def test_r19_unclosed_quote_state_stops_at_newline_before_a_direct_clause(
    opener: str,
) -> None:
    text = f"discarded {opener}fragment\n{DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(text=text)


@pytest.mark.parametrize(
    "text",
    (
        f'The auditor\nreported:\n"{DIRECT}."',
        f"The auditor reported that\n{DIRECT}.",
        f'"{DIRECT},"\nO\'Connor reported.',
        f"The crew’s liaison\nclearly stated —\n“{DIRECT}.”",
    ),
)
def test_r19_multiline_reporting_clauses_preserve_local_attribution(text: str) -> None:
    _assert_reported_only(text=text)


def test_r19_nested_quote_like_characters_do_not_change_outer_attribution() -> None:
    cases = (
        f"The auditor stated: “She wrote '{DIRECT}.' in the `handoff`.”",
        f"The auditor stated: “{DIRECT} for the «north-bound» route.”",
        f'The auditor stated: "She wrote ‘{DIRECT}.’ yesterday."',
    )

    for text in cases:
        _assert_reported_only(text=text)


@pytest.mark.parametrize(
    "text",
    (
        f'The auditor reported:: "{DIRECT}."',
        f"The auditor reported,: “{DIRECT}.”",
        f'The auditor reported —: "{DIRECT}."',
    ),
)
def test_r19_malformed_delimiters_neither_crash_nor_promote_reported_content(
    text: str,
) -> None:
    assert third_party_reported_obligation_spans(text) == ()
    assert obligation_promotion_exclusion_spans(text)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert not _projection(text=text).applied


def test_r19_hard_punctuation_boundary_prevents_false_suffix_attribution() -> None:
    text = f"“{DIRECT}.” The auditor reported a damaged pallet."

    assert third_party_reported_obligation_spans(text) == ()
    assert facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )


@pytest.mark.parametrize("reported_first", (False, True))
def test_r19_reported_and_direct_evidence_promote_only_the_direct_clause(
    reported_first: bool,
) -> None:
    reported = f"The auditor stated: “{DIRECT}.”"
    clauses = (reported, DIRECT) if reported_first else (DIRECT, reported)
    text = ";\n".join(clauses)

    assert len(third_party_reported_obligation_spans(text)) == 1
    _assert_direct(text=text)


def test_r19_reported_candidate_state_never_leaks_to_neighboring_candidates() -> None:
    reported = f"The auditor stated: “{DIRECT}.”"
    direct = DIRECT

    first_pass = (
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=reported),
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=direct),
    )
    second_pass = (
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=direct),
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=reported),
    )

    assert first_pass == (False, True)
    assert second_pass == (True, False)
    assert (_projection(text=reported).rank, _projection(text=direct).rank) == (3, 0)


def test_r19_reported_unrelated_candidate_does_not_suppress_matching_direct_evidence() -> None:
    text = f"The auditor stated: “Alex must sign the loading sheet.”; {DIRECT}."

    _assert_direct(text=text)


class _CountingText(str):
    reads: int

    def __new__(cls, value: str) -> _CountingText:
        instance = super().__new__(cls, value)
        instance.reads = 0
        return instance

    def __getitem__(self, key: int | slice) -> str:
        if isinstance(key, int):
            self.reads += 1
        return super().__getitem__(key)


def test_r19_quote_scanner_growth_is_linear_at_1k_4k_and_8k() -> None:
    reads: list[int] = []
    lengths: list[int] = []
    for quote_count in (1_000, 4_000, 8_000):
        text = _CountingText("“" * quote_count + f"\n{DIRECT}.")

        scan = scan_quotes(text)

        assert scan.quotes == ()
        assert scan.malformed_spans
        assert text.reads <= len(text) * 12
        reads.append(text.reads)
        lengths.append(len(text))

    for previous, current, factor in ((0, 1, 4), (1, 2, 2)):
        assert reads[current] <= reads[previous] * factor + 128
        previous_density = reads[previous] / lengths[previous]
        current_density = reads[current] / lengths[current]
        assert current_density <= previous_density * 1.10


def _tree(module: str) -> ast.Module:
    path = SPLIT_MODULES[module]
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _scoped_imports(module: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(module)):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        imported_name = node.module.rsplit(".", 1)[-1]
        if imported_name in SPLIT_MODULES:
            imported.add(imported_name)
    return imported


def test_r19_parser_split_dependency_direction_is_acyclic_and_layered() -> None:
    expected_edges = {
        "context_attribution_lexicon": set(),
        "context_reporting_frames": {"context_attribution_lexicon"},
        "context_quote_scanner": {"context_attribution_lexicon"},
        "context_reported_obligation_attribution": {
            "context_attribution_lexicon",
            "context_quote_scanner",
            "context_reporting_frames",
        },
        "context_source_sibling_policy": {
            "context_reported_obligation_attribution",
        },
        "context_source_siblings": {"context_source_sibling_policy"},
    }
    actual_edges = {module: _scoped_imports(module) for module in SPLIT_MODULES}

    assert actual_edges == expected_edges

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, f"parser-split import cycle reaches {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in actual_edges[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in SPLIT_MODULES:
        visit(module)


def test_r19_facade_reexports_candidate_promotion_without_reimplementing_it() -> None:
    assert (
        facade.is_direct_source_sibling_obligation_evidence
        is context_source_sibling_policy.is_direct_source_sibling_obligation_evidence
    )
    assert (
        facade.project_source_sibling_obligation_evidence
        is context_source_sibling_policy.project_source_sibling_obligation_evidence
    )


def test_r19_split_policy_responsibilities_have_one_definition_site() -> None:
    expected_owners = {
        "classify_reporting_verb": "context_attribution_lexicon",
        "is_reporting_clause": "context_reporting_frames",
        "indirect_reporting_header_end": "context_reporting_frames",
        "scan_quotes": "context_quote_scanner",
        "third_party_reported_obligation_spans": ("context_reported_obligation_attribution"),
        "obligation_promotion_exclusion_spans": ("context_reported_obligation_attribution"),
        "is_direct_source_sibling_obligation_evidence": ("context_source_sibling_policy"),
        "project_source_sibling_obligation_evidence": "context_source_sibling_policy",
    }
    owners: dict[str, list[str]] = {name: [] for name in expected_owners}
    for module in SPLIT_MODULES:
        for node in _tree(module).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in owners:
                owners[node.name].append(module)

    assert owners == {name: [owner] for name, owner in expected_owners.items()}


def test_r19_parser_split_has_no_fixture_sentence_literals_or_oversized_file() -> None:
    forbidden_literals = {
        "cafeteria",
        "dispatch manifest",
        "loading sheet",
        "morgan",
        "north-bound route",
    }
    for module, path in SPLIT_MODULES.items():
        source = path.read_text(encoding="utf-8")
        folded = source.casefold()

        assert len(source.splitlines()) <= 1_000, f"{module} exceeds 1000 lines"
        assert all(literal not in folded for literal in forbidden_literals)


def test_r19_parser_modules_import_without_optional_provider_dependencies() -> None:
    for module in (
        "context_attribution_lexicon",
        "context_reporting_frames",
        "context_quote_scanner",
        "context_reported_obligation_attribution",
    ):
        imports = {
            node.module.split(".", 1)[0]
            for node in ast.walk(_tree(module))
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert imports.isdisjoint(
            {
                "fastapi",
                "graphiti",
                "openai",
                "qdrant_client",
                "sqlalchemy",
            }
        )
