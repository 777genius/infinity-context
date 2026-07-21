"""Deterministic tests for Postgres grouped lexical scoring."""

from infinity_context_adapters.postgres.repository_helpers import (
    _grouped_sql_matches,
    _grouped_sql_score,
    _score,
    _terms,
)
from sqlalchemy import create_engine, literal, or_, select


def test_aliases_for_one_raw_term_contribute_one_hit_in_sql_and_python() -> None:
    terms = _terms("work")

    assert tuple(term.raw for term in terms) == ("work",)
    assert {"work", "career", "job", "jobs", "profession", "occupation"} <= set(
        terms[0].variants
    )
    assert _score("career job jobs profession occupation", terms) == 1000
    assert _sql_score("career job jobs profession occupation", terms) == 1


def test_distinct_raw_terms_remain_additive_in_sql_and_python() -> None:
    terms = _terms("work project")

    assert tuple(term.raw for term in terms) == ("work", "project")
    assert _score("A career project", terms) == 2000
    assert _sql_score("a career project", terms) == 2


def test_typo_approximation_matches_an_alias_inside_its_raw_term_group() -> None:
    terms = _terms("daily work")

    assert _score("A daily professiin update", terms) == 2000


def test_commute_evidence_is_not_displaced_by_career_alias_inflation() -> None:
    terms = _terms("How long is the daily commute to work?")
    exact_evidence = "My daily commute to work takes 45 minutes each way."
    distractors = [
        f"Career note {index}: job jobs profession occupation career."
        for index in range(187)
    ]
    candidates = [*distractors, exact_evidence]

    python_ranked = sorted(candidates, key=lambda text: _score(text, terms), reverse=True)
    sql_ranked = sorted(candidates, key=lambda text: _sql_score(text.lower(), terms), reverse=True)

    assert _score(exact_evidence, terms) == 3000
    assert _score(distractors[0], terms) == 1000
    assert python_ranked.index(exact_evidence) + 1 == 1
    assert sql_ranked.index(exact_evidence) + 1 == 1
    assert sql_ranked.index(exact_evidence) + 1 <= 180


def _sql_score(text: str, terms) -> int:
    value = literal(text)
    matches = _grouped_sql_matches(value, terms)
    statement = select(_grouped_sql_score(matches)).where(or_(*matches))
    with create_engine("sqlite://").connect() as connection:
        score = connection.execute(statement).scalar_one_or_none()
    return int(score or 0)
