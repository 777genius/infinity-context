from __future__ import annotations

import ast
from pathlib import Path

import pytest
from infinity_context_core.application import context_source_sibling_policy
from infinity_context_core.application import context_source_siblings as facade
from infinity_context_core.application.context_attribution_lexicon import (
    ReportingVerbKind,
    classify_reporting_verb,
    is_word_apostrophe,
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
    malformed_reporting_header_end,
)

QUERY = "Which dispatch manifest must Morgan approve?"
DIRECT = "Morgan must approve the dispatch manifest"
ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "packages" / "infinity_context_core" / "infinity_context_core" / "application"

PARSER_MODULES = {
    "context_attribution_lexicon": APPLICATION / "context_attribution_lexicon.py",
    "context_reporting_frames": APPLICATION / "context_reporting_frames.py",
    "context_quote_scanner": APPLICATION / "context_quote_scanner.py",
    "context_reported_obligation_attribution": (
        APPLICATION / "context_reported_obligation_attribution.py"
    ),
    "context_source_sibling_policy": APPLICATION / "context_source_sibling_policy.py",
    "context_source_siblings": APPLICATION / "context_source_siblings.py",
}


def _projection(*, text: str, query: str = QUERY):  # type: ignore[no-untyped-def]
    return facade.project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )


def _assert_reported(*, text: str, query: str = QUERY) -> None:
    projection = _projection(query=query, text=text)

    assert third_party_reported_obligation_spans(text)
    assert obligation_promotion_exclusion_spans(text)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert not projection.applied
    assert projection.rank != 0


def _assert_direct(*, text: str, expected: str = DIRECT, query: str = QUERY) -> None:
    projection = _projection(query=query, text=text)

    assert facade.is_direct_source_sibling_obligation_evidence(
        query_text=query,
        text=text,
    )
    assert projection.applied
    assert projection.rank == 0
    assert expected in projection.text
    assert projection.spans


def _assert_malformed_is_not_promoted(*, text: str, needle: str = DIRECT) -> None:
    exclusions = obligation_promotion_exclusion_spans(text)
    needle_start = text.index(needle)

    assert third_party_reported_obligation_spans(text) == ()
    assert exclusions
    assert any(start <= needle_start < end for start, end in exclusions)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert not _projection(text=text).applied


@pytest.mark.parametrize(
    ("clause", "expected"),
    (
        ("the dock auditor reports", True),
        ("the dock auditors report", True),
        ("Morgan reports", True),
        ("The Night Auditor Reports", True),
        ("Night Auditors Report", True),
        ("the incident report", False),
        ("the incident reports", False),
        ("incident reporting", False),
        ("the reporting dashboard", False),
        ("Status Reports", False),
        ("The Incident Reports", False),
        ("Quarterly Reporting", False),
    ),
)
def test_r20_report_noun_and_verb_surfaces_have_grammatical_roles(
    clause: str,
    expected: bool,
) -> None:
    assert is_reporting_clause(clause) is expected


@pytest.mark.parametrize(
    "header",
    (
        "Status Reports",
        "News Reports",
        "The Incident Reports",
        "Quarterly Reporting",
    ),
)
def test_r20_title_cased_report_nouns_do_not_become_reporters(header: str) -> None:
    text = f'{header}: "{DIRECT}."'

    assert third_party_reported_obligation_spans(text) == ()
    assert obligation_promotion_exclusion_spans(text) == ()
    _assert_direct(text=text)


@pytest.mark.parametrize(
    "header",
    (
        "The Night Auditor Reports",
        "Night Auditors Report",
        "Morgan Reports",
        "Mary-Jane O’Connor Reports",
    ),
)
def test_r20_title_cased_agentive_reporters_remain_reporting_verbs(header: str) -> None:
    _assert_reported(text=f'{header}: "{DIRECT}."')


def test_r20_present_participle_is_a_verb_only_with_an_auxiliary_and_agent() -> None:
    verbal = f'The dock auditor is reporting: "{DIRECT}."'
    noun = f'Incident reporting: "{DIRECT}."'

    _assert_reported(text=verbal)
    assert third_party_reported_obligation_spans(noun) == ()
    _assert_direct(text=noun)


@pytest.mark.parametrize(
    "header",
    (
        "The incident report states",
        "The incident reports state",
        "The quarterly reporting states",
    ),
)
def test_r20_report_nouns_can_be_explicit_sources_of_a_reporting_verb(
    header: str,
) -> None:
    _assert_reported(text=f'{header}: "{DIRECT}."')


def test_r20_reporting_verb_classification_does_not_classify_nouns_by_context() -> None:
    assert classify_reporting_verb("report") is ReportingVerbKind.BASE
    assert classify_reporting_verb("reports") is ReportingVerbKind.FINITE
    assert classify_reporting_verb("reporting") is None
    assert classify_reporting_verb("reporter") is None
    assert classify_reporting_verb("reports'") is None


@pytest.mark.parametrize("separator", (":", ",", " — ", " – ", " - "))
def test_r20_one_reporting_separator_keeps_valid_attribution(separator: str) -> None:
    _assert_reported(text=f'The dock auditor reported{separator}"{DIRECT}."')


@pytest.mark.parametrize("separator", ("::", ",:", "—:", "- —", ": ,"))
def test_r20_duplicate_or_mixed_prefix_separators_fail_closed(separator: str) -> None:
    text = f'The dock auditor reported{separator} "{DIRECT}."'

    _assert_malformed_is_not_promoted(text=text)


@pytest.mark.parametrize("separator", ("::", ",:", "—:", "- —", ": ,"))
def test_r20_duplicate_or_mixed_suffix_separators_fail_closed(separator: str) -> None:
    text = f'"{DIRECT}." {separator} the dock auditor reported'

    _assert_malformed_is_not_promoted(text=text)


@pytest.mark.parametrize("separator", ("::", ",:", "—:", "- —", ": ,"))
def test_r20_malformed_indirect_separators_are_exclusions_not_attribution(
    separator: str,
) -> None:
    text = f"The dock auditor reported{separator} {DIRECT}."

    assert indirect_reporting_header_end(text=text, start=0, end=len(text)) is None
    assert malformed_reporting_header_end(text=text, start=0, end=len(text)) is not None
    _assert_malformed_is_not_promoted(text=text)


@pytest.mark.parametrize("separator", (":/", ",/", "—/"))
def test_r20_unknown_mixed_separators_also_fail_closed(separator: str) -> None:
    quoted = f'The dock auditor reported{separator} "{DIRECT}."'
    indirect = f"The dock auditor reported{separator} {DIRECT}."

    _assert_malformed_is_not_promoted(text=quoted)
    _assert_malformed_is_not_promoted(text=indirect)


@pytest.mark.parametrize(
    "quoted",
    (
        f'"{DIRECT}."',
        f"'{DIRECT}.'",
        f"“{DIRECT}.”",
        f"‘{DIRECT}.’",
    ),
)
def test_r20_balanced_straight_and_curly_quote_orientation_is_attributed(
    quoted: str,
) -> None:
    text = f"The dock auditor reported: {quoted}"

    assert len(scan_quotes(text).quotes) == 1
    _assert_reported(text=text)


@pytest.mark.parametrize(
    "quoted",
    (
        f'"{DIRECT}.”',
        f'“{DIRECT}."',
        f"'{DIRECT}.’",
        f"‘{DIRECT}.'",
        f"”{DIRECT}.“",
        f"’{DIRECT}.‘",
        f"“{DIRECT}.’",
        f"‘{DIRECT}.”",
    ),
)
def test_r20_mixed_or_reversed_quote_pairs_are_never_direct_evidence(
    quoted: str,
) -> None:
    text = f"The dock auditor reported: {quoted}"

    assert scan_quotes(text).malformed_spans
    _assert_malformed_is_not_promoted(text=text)


@pytest.mark.parametrize("apostrophe", ("'", "’"))
def test_r20_internal_and_trailing_possessives_are_lexical(apostrophe: str) -> None:
    internal = f"D{apostrophe}Arcy"
    trailing = f"pilots{apostrophe} liaison"

    assert is_word_apostrophe(text=internal, index=1)
    assert is_word_apostrophe(text=trailing, index=6)


@pytest.mark.parametrize(
    "reporter",
    (
        "D'Arcy's night auditor",
        "D’Arcy’s night auditor",
        "the pilots' overnight liaison",
        "the pilots’ overnight liaison",
        "O'Donnell's compliance lead",
        "O’Donnell’s compliance lead",
    ),
)
def test_r20_internal_and_trailing_possessive_reporters_are_attributed(
    reporter: str,
) -> None:
    _assert_reported(text=f'{reporter} reported: "{DIRECT}."')


@pytest.mark.parametrize(
    ("opener", "closer"),
    (
        ("'", "'"),
        ("‘", "’"),
    ),
)
def test_r20_punctuation_free_single_quote_ending_in_s_closes_before_suffix(
    opener: str,
    closer: str,
) -> None:
    body = f"{DIRECT} reports"
    text = f"{opener}{body}{closer} the dock auditor reported"
    scan = scan_quotes(text)

    assert scan.malformed_spans == ()
    assert len(scan.quotes) == 1
    assert text[scan.quotes[0].body_start : scan.quotes[0].body_end] == body
    _assert_reported(text=text)


@pytest.mark.parametrize(
    ("opener", "closer"),
    (
        ("'", "'"),
        ("‘", "’"),
    ),
)
def test_r20_punctuation_free_single_quote_ending_in_s_closes_before_adjacency(
    opener: str,
    closer: str,
) -> None:
    first = "Alex must sign the route reports"
    second = f"{DIRECT} files"
    text = f"The dock auditor stated: {opener}{first}{closer} and {opener}{second}{closer}"
    scan = scan_quotes(text)

    assert scan.malformed_spans == ()
    assert tuple(text[quote.body_start : quote.body_end] for quote in scan.quotes) == (
        first,
        second,
    )
    assert len(third_party_reported_obligation_spans(text)) == 2
    _assert_reported(text=text)


@pytest.mark.parametrize("reported_first", (False, True))
@pytest.mark.parametrize("boundary", ("; ", ".\n"))
def test_r20_reported_and_direct_clauses_promote_only_the_direct_local_clause(
    reported_first: bool,
    boundary: str,
) -> None:
    reported = f"The dock auditor stated: “{DIRECT}.”"
    clauses = (reported, DIRECT) if reported_first else (DIRECT, reported)
    text = boundary.join(clauses)

    assert len(third_party_reported_obligation_spans(text)) == 1
    _assert_direct(text=text)
    assert _projection(text=text).text == DIRECT


def test_r20_adjacent_quotes_inherit_only_an_explicit_local_reporter() -> None:
    first = "Alex must sign the route sheet."
    second = f"{DIRECT}."
    reported = f"The dock auditor stated: “{first}” and “{second}”"
    unreported = f"“{first}” and “{second}”"

    assert len(third_party_reported_obligation_spans(reported)) == 2
    _assert_reported(text=reported)
    assert third_party_reported_obligation_spans(unreported) == ()
    _assert_direct(text=unreported)


def test_r20_split_adjacent_reported_predicate_is_excluded_from_promotion() -> None:
    text = "The dock auditor stated: “Morgan must” and “approve the dispatch manifest.”"
    exclusions = obligation_promotion_exclusion_spans(text)

    assert exclusions
    assert any(start <= text.index("Morgan") < end for start, end in exclusions)
    assert not facade.is_direct_source_sibling_obligation_evidence(
        query_text=QUERY,
        text=text,
    )
    assert not _projection(text=text).applied


def test_r20_malformed_quote_stops_at_newline_before_a_direct_clause() -> None:
    text = f"The dock auditor reported: “Alex must sign the route sheet.\n{DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    exclusions = obligation_promotion_exclusion_spans(text)
    assert exclusions
    assert all(not (start <= text.index(DIRECT) < end) for start, end in exclusions)
    _assert_direct(text=text)


def test_r20_malformed_and_valid_clauses_keep_their_own_candidate_state() -> None:
    malformed = f'The dock auditor reported:: "{DIRECT}."'
    reported = f'The dock auditor reported: "{DIRECT}."'
    direct = DIRECT

    first = tuple(
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=text)
        for text in (malformed, reported, direct)
    )
    second = tuple(
        facade.is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=text)
        for text in (direct, reported, malformed)
    )

    assert first == (False, False, True)
    assert second == (True, False, False)
    assert tuple(_projection(text=text).rank for text in (malformed, reported, direct)) == (
        3,
        3,
        0,
    )


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


@pytest.mark.parametrize("analyze", (False, True))
def test_r20_quote_scanning_is_linear_at_1k_4k_and_8k(analyze: bool) -> None:
    reads: list[int] = []
    lengths: list[int] = []
    for quote_count in (1_000, 4_000, 8_000):
        text = _CountingText("“" * quote_count + f"\n{DIRECT}.")

        if analyze:
            assert third_party_reported_obligation_spans(text) == ()
        else:
            scan = scan_quotes(text)
            assert scan.quotes == ()
            assert scan.malformed_spans
        assert text.reads <= len(text) * 16
        reads.append(text.reads)
        lengths.append(len(text))

    for previous, current, factor in ((0, 1, 4), (1, 2, 2)):
        assert reads[current] <= reads[previous] * factor + 128
        assert reads[current] / lengths[current] <= (reads[previous] / lengths[previous] * 1.10)


def _tree(module: str) -> ast.Module:
    path = PARSER_MODULES[module]
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parser_imports(module: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(module)):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        imported_name = node.module.rsplit(".", 1)[-1]
        if imported_name in PARSER_MODULES:
            imported.add(imported_name)
    return imported


def test_r20_parser_dependency_graph_remains_layered_and_acyclic() -> None:
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
    actual_edges = {module: _parser_imports(module) for module in PARSER_MODULES}

    assert actual_edges == expected_edges

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, f"parser import cycle reaches {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in actual_edges[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in PARSER_MODULES:
        visit(module)


def test_r20_new_parser_responsibilities_have_exactly_one_owner() -> None:
    expected_owners = {
        "classify_reporting_verb": "context_attribution_lexicon",
        "is_word_apostrophe": "context_attribution_lexicon",
        "is_reporting_clause": "context_reporting_frames",
        "indirect_reporting_header_end": "context_reporting_frames",
        "malformed_reporting_header_end": "context_reporting_frames",
        "scan_quotes": "context_quote_scanner",
        "third_party_reported_obligation_spans": ("context_reported_obligation_attribution"),
        "obligation_promotion_exclusion_spans": ("context_reported_obligation_attribution"),
        "is_direct_source_sibling_obligation_evidence": ("context_source_sibling_policy"),
        "project_source_sibling_obligation_evidence": "context_source_sibling_policy",
    }
    owners: dict[str, list[str]] = {name: [] for name in expected_owners}
    for module in PARSER_MODULES:
        for node in _tree(module).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in owners:
                owners[node.name].append(module)

    assert owners == {name: [owner] for name, owner in expected_owners.items()}
    assert (
        facade.is_direct_source_sibling_obligation_evidence
        is context_source_sibling_policy.is_direct_source_sibling_obligation_evidence
    )
    assert (
        facade.project_source_sibling_obligation_evidence
        is context_source_sibling_policy.project_source_sibling_obligation_evidence
    )


def test_r20_parser_modules_have_no_fixture_literals_providers_or_oversized_file() -> None:
    forbidden_literals = {
        "dispatch manifest",
        "dock auditor",
        "incident reports",
        "morgan",
        "route reports",
        "status reports",
    }
    forbidden_import_roots = {
        "fastapi",
        "graphiti",
        "infinity_context_adapters",
        "infinity_context_server",
        "openai",
        "qdrant_client",
        "sqlalchemy",
    }

    for module, path in PARSER_MODULES.items():
        source = path.read_text(encoding="utf-8")
        imported_roots: set[str] = set()
        for node in ast.walk(_tree(module)):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots.add(node.module.split(".", 1)[0])

        assert len(source.splitlines()) <= 1_000, f"{module} exceeds 1000 lines"
        assert all(literal not in source.casefold() for literal in forbidden_literals)
        assert imported_roots.isdisjoint(forbidden_import_roots)
