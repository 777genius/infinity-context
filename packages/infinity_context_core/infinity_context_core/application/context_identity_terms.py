"""Normalization policy for distinct-set identity terms."""

from __future__ import annotations


def singularize_identity_term(term: str) -> str:
    if term.endswith("'s"):
        return term
    if term.endswith("ies") and len(term) > 4:
        return f"{term[:-3]}y"
    if term.endswith(("sses", "shes", "ches", "xes", "zes")) and len(term) > 4:
        return term[:-2]
    if term.endswith("s") and not term.endswith(("is", "ss", "us")) and len(term) > 3:
        return term[:-1]
    return term
