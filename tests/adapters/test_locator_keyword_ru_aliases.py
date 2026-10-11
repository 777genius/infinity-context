import pytest
from infinity_context_adapters.postgres.locator_keyword_aliases import generated_keyword_aliases
from infinity_context_adapters.postgres.locator_retrieval import (
    _candidate_statement,
    _keyword_terms,
)
from sqlalchemy.dialects import postgresql
from test_locator_retrieval_adapters import _request


@pytest.mark.parametrize(
    "family",
    [
        ("встреча", "встрече", "встречу"),
        ("релиз", "релизе", "релиза"),
        ("документ", "документе", "документа"),
        ("решение", "решении", "решения"),
        ("настройка", "настройке", "настройки"),
    ],
)
def test_fullword_family_is_one_signal_in_both_directions(family):
    for word in family:
        terms = _keyword_terms(f"{word} {family[1]}")
        assert len(terms) == 1
        assert terms[0][0] == word
        assert set(terms[0]) == set(family)
        assert len(_keyword_terms(f"{word} {family[1]} roadmap")) == 2


def test_generated_aliases_require_word_boundary_and_indexable_prefilter():
    compiled = _candidate_statement(_request(), "релиз 100% release_candidate").compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "lower(" not in sql
    assert "ESCAPE '/'" in sql
    assert " ~ " in sql and " AND " in sql
    values = list(compiled.params.values())
    assert (
        r"(^|[^\wА-Яа-яЁё])релизе($|[^\wА-Яа-яЁё])" in values
        and r"(^|[^\wА-Яа-яЁё])релиза($|[^\wА-Яа-яЁё])" in values
    )
    assert r"(^|[^\wА-Яа-яЁё])релиз($|[^\wА-Яа-яЁё])" not in values
    assert "100/%" in values and "release/_candidate" in values
    assert _keyword_terms("Alice abc_42 100% неизвестное") == (
        ("alice",),
        ("abc_42",),
        ("100%",),
        ("неизвестное",),
    )
    assert generated_keyword_aliases("рeлиз") == ()
    assert _keyword_terms("что известно о") == ()
