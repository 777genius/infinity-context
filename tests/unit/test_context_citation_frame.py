"""Citation reliability: char ranges must map to source coordinates.

Mirrors the ``context_hydration`` chunk citation path: the quote snippet is built
over the clean chunk body (not the enriched retrieval text) and its range is mapped
to the source via ``chunk.char_start``. A regression here means the citation points
into the wrong coordinate space and/or quotes retrieval metadata (title / hints)
instead of the verbatim evidence.
"""

from infinity_context_core.application.context_snippets import (
    QuerySnippet,
    query_focused_snippet,
    source_refs_with_query_snippet,
)
from infinity_context_core.domain.entities import SourceRef

_CHUNK_BODY = (
    "user: What is the retry budget for the export job?\n"
    "assistant: The export retry budget is 20 records per run."
)
_CHUNK_CHAR_START = 500


def _cite(body: str, query: str) -> tuple[QuerySnippet, SourceRef]:
    snippet = query_focused_snippet(query=query, text=body)
    assert snippet is not None
    ref = SourceRef(
        source_type="conversation",
        source_id="thread-1",
        chunk_id="chunk-1",
        char_start=_CHUNK_CHAR_START,
        char_end=_CHUNK_CHAR_START + len(body),
    )
    ref = source_refs_with_query_snippet(
        (ref,),
        snippet,
        include_char_range=True,
        source_char_base=_CHUNK_CHAR_START,
    )[0]
    return snippet, ref


def test_citation_char_range_resolves_to_source_evidence() -> None:
    snippet, ref = _cite(_CHUNK_BODY, "What is the retry budget for the export job?")
    body = _CHUNK_BODY
    assert ref.char_start is not None and ref.char_end is not None
    # The cited slice in the source document contains the matched evidence.
    cited = body[ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START]
    assert "retry budget" in cited
    # The range is the snippet window shifted to the source origin.
    assert ref.char_start == _CHUNK_CHAR_START + snippet.char_start
    assert ref.char_end == _CHUNK_CHAR_START + snippet.char_end


def test_citation_range_stays_within_source_chunk_and_narrows() -> None:
    filler = "The team reviewed unrelated roadmap items and staffing notes. " * 8
    body = filler + _CHUNK_BODY + filler
    _s, ref = _cite(body, "What is the retry budget for the export job?")
    assert ref.char_start is not None and ref.char_end is not None
    assert ref.char_start >= _CHUNK_CHAR_START
    assert ref.char_end <= _CHUNK_CHAR_START + len(body)
    # Narrowed toward the evidence rather than spanning the whole padded body.
    assert ref.char_end - ref.char_start < len(body)
    cited = body[ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START]
    assert "retry budget" in cited


def test_citation_preview_is_verbatim_evidence_not_retrieval_hints() -> None:
    snippet, ref = _cite(_CHUNK_BODY, "What is the retry budget for the export job?")
    assert "Retrieval hints" not in ref.quote_preview
    assert ref.quote_preview == snippet.text
    assert "retry budget" in ref.quote_preview
