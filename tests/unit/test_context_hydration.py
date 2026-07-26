import asyncio
from datetime import UTC, datetime, timedelta

from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.domain.entities import (
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)

NOW = datetime(2026, 6, 18, tzinfo=UTC)


def test_hydrator_revalidates_fact_items_with_single_batch_lookup() -> None:
    repo = _BatchOnlyFactRepo(
        facts={
            "fact_1": _fact("fact_1", text="Fact one is visible."),
            "fact_2": _fact("fact_2", text="Fact two is visible."),
        }
    )
    chunks = _FailingChunkRepo()
    hydrator = ContextHydrator(uow_factory=_FakeUowFactory(facts=repo, chunks=chunks))

    result = asyncio.run(
        hydrator.revalidate_visible_items(
            (
                _item("fact_1"),
                _item("fact_2"),
                _item("fact_missing"),
            ),
            query=_query(),
            memory_scope_ids=("scope_1",),
        )
    )

    assert [item.item_id for item in result] == ["fact_1", "fact_2"]
    assert [item.text for item in result] == ["Fact one is visible.", "Fact two is visible."]
    assert repo.get_by_ids_calls == [("fact_1", "fact_2", "fact_missing")]
    assert repo.get_by_id_calls == []
    assert chunks.hydrate_visible_chunks_calls == []


def test_hydrator_revalidates_anchor_items_with_one_unique_ordered_batch() -> None:
    anchor_1 = _anchor("anchor_1")
    anchor_2 = _anchor("anchor_2")
    anchors = _BatchOnlyAnchorRepo(
        anchors={
            "anchor_1": anchor_1,
            "anchor_2": anchor_2,
        }
    )
    uow_factory = _FakeUowFactory(
        facts=_BatchOnlyFactRepo(facts={}),
        chunks=_FailingChunkRepo(),
        anchors=anchors,
    )
    hydrator = ContextHydrator(uow_factory=uow_factory, clock=_FixedClock())
    ranked_first = _anchor_item(
        "anchor_2",
        text="Ranked anchor two projection.",
        score=0.93,
        is_instruction=True,
        diagnostics={"rank": 1, "retrieval_source": "test_anchor"},
    )
    ranked_second = _anchor_item(
        "anchor_1",
        text="Ranked anchor one projection.",
        score=0.81,
        diagnostics={"rank": 2, "retrieval_source": "test_anchor"},
    )
    duplicate = _anchor_item(
        "anchor_2",
        text="Later duplicate anchor two projection.",
        score=0.54,
        diagnostics={"rank": 4, "retrieval_source": "duplicate_anchor"},
    )

    result = asyncio.run(
        hydrator.revalidate_visible_items(
            (
                ranked_first,
                _anchor_item("anchor_missing", text="Missing anchor."),
                ranked_second,
                duplicate,
            ),
            query=_query(),
            memory_scope_ids=("scope_1",),
        )
    )

    assert anchors.get_by_ids_calls == [("anchor_2", "anchor_missing", "anchor_1")]
    assert anchors.get_by_id_calls == []
    assert uow_factory.calls == 1
    assert [item.item_id for item in result] == ["anchor_2", "anchor_1", "anchor_2"]
    assert [item.text for item in result] == [
        ranked_first.text,
        ranked_second.text,
        duplicate.text,
    ]
    assert [item.score for item in result] == [0.93, 0.81, 0.54]
    assert [item.source_refs for item in result] == [
        anchor_2.evidence_refs,
        anchor_1.evidence_refs,
        anchor_2.evidence_refs,
    ]
    assert [item.is_instruction for item in result] == [True, False, False]
    assert [item.diagnostics for item in result] == [
        ranked_first.diagnostics,
        ranked_second.diagnostics,
        duplicate.diagnostics,
    ]


def test_hydrator_batch_anchor_visibility_policy_is_unchanged() -> None:
    anchors_by_id = {
        "anchor_visible": _anchor("anchor_visible"),
        "anchor_inactive": _anchor("anchor_inactive").delete(
            reason="test inactive anchor",
            now=NOW,
        ),
        "anchor_cross_space": _anchor("anchor_cross_space", space_id="space_2"),
        "anchor_cross_scope": _anchor("anchor_cross_scope", memory_scope_id="scope_2"),
        "anchor_future": _anchor(
            "anchor_future",
            valid_from=NOW + timedelta(seconds=1),
        ),
        "anchor_expired": _anchor("anchor_expired", valid_to=NOW),
    }
    anchors = _BatchOnlyAnchorRepo(anchors=anchors_by_id)
    hydrator = ContextHydrator(
        uow_factory=_FakeUowFactory(
            facts=_BatchOnlyFactRepo(facts={}),
            chunks=_FailingChunkRepo(),
            anchors=anchors,
        ),
        clock=_FixedClock(),
    )
    anchor_ids = tuple(anchors_by_id)

    result = asyncio.run(
        hydrator.revalidate_visible_items(
            tuple(_anchor_item(anchor_id) for anchor_id in anchor_ids),
            query=_query(),
            memory_scope_ids=("scope_1",),
        )
    )

    assert [item.item_id for item in result] == ["anchor_visible"]
    assert anchors.get_by_ids_calls == [anchor_ids]
    assert anchors.get_by_id_calls == []


def test_hydrator_scalar_anchor_fallback_is_sequential_and_equivalent() -> None:
    anchors_by_id = {
        "anchor_1": _anchor("anchor_1"),
        "anchor_inactive": _anchor("anchor_inactive").delete(
            reason="test inactive anchor",
            now=NOW,
        ),
        "anchor_2": _anchor("anchor_2"),
    }
    items = (
        _anchor_item("anchor_1", text="First visible projection.", score=0.91),
        _anchor_item("anchor_missing", text="Missing projection.", score=0.83),
        _anchor_item("anchor_inactive", text="Inactive projection.", score=0.72),
        _anchor_item("anchor_2", text="Second visible projection.", score=0.64),
        _anchor_item("anchor_1", text="First duplicate projection.", score=0.51),
    )
    batch_repo = _BatchOnlyAnchorRepo(anchors=anchors_by_id)
    scalar_repo = _ScalarOnlyAnchorRepo(anchors=anchors_by_id)

    batch_result = asyncio.run(
        ContextHydrator(
            uow_factory=_FakeUowFactory(
                facts=_BatchOnlyFactRepo(facts={}),
                chunks=_FailingChunkRepo(),
                anchors=batch_repo,
            ),
            clock=_FixedClock(),
        ).revalidate_visible_items(items, query=_query(), memory_scope_ids=("scope_1",))
    )
    scalar_result = asyncio.run(
        ContextHydrator(
            uow_factory=_FakeUowFactory(
                facts=_BatchOnlyFactRepo(facts={}),
                chunks=_FailingChunkRepo(),
                anchors=scalar_repo,
            ),
            clock=_FixedClock(),
        ).revalidate_visible_items(items, query=_query(), memory_scope_ids=("scope_1",))
    )

    assert scalar_result == batch_result
    assert [item.item_id for item in scalar_result] == ["anchor_1", "anchor_2", "anchor_1"]
    assert scalar_repo.get_by_id_calls == [
        "anchor_1",
        "anchor_missing",
        "anchor_inactive",
        "anchor_2",
    ]
    assert scalar_repo.max_in_flight == 1
    assert batch_repo.get_by_ids_calls == [
        ("anchor_1", "anchor_missing", "anchor_inactive", "anchor_2")
    ]


def test_hydrator_keeps_non_anchor_fact_and_chunk_hydration_behavior() -> None:
    facts = _BatchOnlyFactRepo(
        facts={"fact_1": _fact("fact_1", text="Canonical visible fact text.")}
    )
    chunks = _BatchChunkRepo(chunks={"chunk_1": _chunk("chunk_1")})
    uow_factory = _FakeUowFactory(facts=facts, chunks=chunks)
    chunk_item = ContextItem(
        item_id="chunk_1",
        item_type="chunk",
        text="Stale chunk text.",
        score=0.63,
        source_refs=(),
        is_instruction=True,
        diagnostics={"retrieval_source": "test_chunk"},
    )

    result = asyncio.run(
        ContextHydrator(uow_factory=uow_factory).revalidate_visible_items(
            (chunk_item, _item("fact_1")),
            query=_query(),
            memory_scope_ids=("scope_1",),
        )
    )

    assert [item.item_id for item in result] == ["chunk_1", "fact_1"]
    assert result[0].text == "Canonical visible chunk text."
    assert result[0].score == chunk_item.score
    assert result[0].is_instruction is True
    assert result[0].diagnostics == chunk_item.diagnostics
    assert result[0].source_refs[0].source_id == "source_chunk_1"
    assert result[1].text == "Canonical visible fact text."
    assert chunks.hydrate_visible_chunks_calls == [("chunk_1",)]
    assert facts.get_by_ids_calls == [("fact_1",)]


def test_hydrator_hydrates_graph_facts_with_single_batch_lookup() -> None:
    repo = _BatchOnlyFactRepo(
        facts={
            "fact_1": _fact("fact_1", text="Graph fact one is visible."),
            "fact_2": _fact("fact_2", text="Graph fact two is visible."),
        }
    )
    hydrator = ContextHydrator(
        uow_factory=_FakeUowFactory(facts=repo, chunks=_FailingChunkRepo())
    )

    items, stale_count = asyncio.run(
        hydrator.hydrate_graph_facts(
            fact_ids=("fact_1", "fact_missing", "fact_2"),
            query=_query(),
            memory_scope_ids=("scope_1",),
        )
    )

    assert [item.item_id for item in items] == ["fact_1", "fact_2"]
    assert [item.text for item in items] == [
        "Graph fact one is visible.",
        "Graph fact two is visible.",
    ]
    assert stale_count == 1
    assert repo.get_by_ids_calls == [("fact_1", "fact_missing", "fact_2")]
    assert repo.get_by_id_calls == []


class _BatchOnlyFactRepo:
    def __init__(self, *, facts: dict[str, MemoryFact]) -> None:
        self._facts = facts
        self.get_by_ids_calls: list[tuple[str, ...]] = []
        self.get_by_id_calls: list[str] = []

    async def get_by_ids(self, fact_ids: tuple[str, ...]) -> list[MemoryFact]:
        self.get_by_ids_calls.append(fact_ids)
        return [fact for fact_id in fact_ids if (fact := self._facts.get(fact_id)) is not None]

    async def get_by_id(self, fact_id: str) -> MemoryFact | None:
        self.get_by_id_calls.append(fact_id)
        raise AssertionError("context hydration must use batch fact lookup")


class _BatchOnlyAnchorRepo:
    def __init__(self, *, anchors: dict[str, MemoryAnchor]) -> None:
        self._anchors = anchors
        self.get_by_ids_calls: list[tuple[str, ...]] = []
        self.get_by_id_calls: list[str] = []

    async def get_by_ids(self, anchor_ids: tuple[str, ...]) -> list[MemoryAnchor]:
        self.get_by_ids_calls.append(anchor_ids)
        return [
            anchor
            for anchor_id in reversed(anchor_ids)
            if (anchor := self._anchors.get(anchor_id)) is not None
        ]

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        self.get_by_id_calls.append(anchor_id)
        raise AssertionError("context hydration must use batch anchor lookup")


class _ScalarOnlyAnchorRepo:
    def __init__(self, *, anchors: dict[str, MemoryAnchor]) -> None:
        self._anchors = anchors
        self.get_by_id_calls: list[str] = []
        self._in_flight = 0
        self.max_in_flight = 0

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        self.get_by_id_calls.append(anchor_id)
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(0)
            return self._anchors.get(anchor_id)
        finally:
            self._in_flight -= 1


class _FailingAnchorRepo:
    async def get_by_ids(self, _anchor_ids: tuple[str, ...]) -> list[MemoryAnchor]:
        raise AssertionError("non-anchor hydration should not call anchor repository")

    async def get_by_id(self, _anchor_id: str) -> MemoryAnchor | None:
        raise AssertionError("non-anchor hydration should not call anchor repository")


class _FailingChunkRepo:
    def __init__(self) -> None:
        self.hydrate_visible_chunks_calls: list[tuple[str, ...]] = []

    async def hydrate_visible_chunks(self, *, chunk_ids: tuple[str, ...], **_kwargs):
        self.hydrate_visible_chunks_calls.append(chunk_ids)
        raise AssertionError("empty chunk hydration should not call chunk repository")


class _BatchChunkRepo:
    def __init__(self, *, chunks: dict[str, MemoryChunk]) -> None:
        self._chunks = chunks
        self.hydrate_visible_chunks_calls: list[tuple[str, ...]] = []

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        **_kwargs: object,
    ) -> list[MemoryChunk]:
        self.hydrate_visible_chunks_calls.append(chunk_ids)
        return [
            chunk for chunk_id in chunk_ids if (chunk := self._chunks.get(chunk_id)) is not None
        ]


class _FakeUow:
    def __init__(self, *, facts: object, chunks: object, anchors: object) -> None:
        self.facts = facts
        self.chunks = chunks
        self.anchors = anchors

    async def __aenter__(self) -> "_FakeUow":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeUowFactory:
    def __init__(
        self,
        *,
        facts: object,
        chunks: object,
        anchors: object | None = None,
    ) -> None:
        self._facts = facts
        self._chunks = chunks
        self._anchors = anchors or _FailingAnchorRepo()
        self.calls = 0

    def __call__(self) -> _FakeUow:
        self.calls += 1
        return _FakeUow(facts=self._facts, chunks=self._chunks, anchors=self._anchors)


def _fact(fact_id: str, *, text: str) -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        text=text,
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id=fact_id),),
        now=NOW,
    )


def _anchor(
    anchor_id: str,
    *,
    space_id: str = "space_1",
    memory_scope_id: str = "scope_1",
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> MemoryAnchor:
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId(space_id),
        memory_scope_id=MemoryScopeId(memory_scope_id),
        kind=MemoryAnchorKind.PERSON,
        normalized_key=anchor_id,
        label=anchor_id,
        evidence_refs=(
            SourceRef(source_type="manual", source_id=f"evidence_{anchor_id}"),
        ),
        valid_from=valid_from,
        valid_to=valid_to,
        now=NOW,
    )


def _chunk(chunk_id: str) -> MemoryChunk:
    text = "Canonical visible chunk text."
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        document_id=MemoryDocumentId(f"document_{chunk_id}"),
        source_type="document",
        source_external_id=f"source_{chunk_id}",
        source_hash=f"hash_{chunk_id}",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=5,
        now=NOW,
    )


def _item(item_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=f"Stale text for {item_id}",
        score=0.7,
        source_refs=(),
        diagnostics={"retrieval_source": "test"},
    )


def _anchor_item(
    item_id: str,
    *,
    text: str | None = None,
    score: float = 0.7,
    is_instruction: bool = False,
    diagnostics: dict[str, object] | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="anchor",
        text=text or f"Projected text for {item_id}",
        score=score,
        source_refs=(SourceRef(source_type="derived", source_id=f"stale_{item_id}"),),
        is_instruction=is_instruction,
        diagnostics=diagnostics or {"retrieval_source": "test"},
    )


class _FixedClock:
    def now(self) -> datetime:
        return NOW


def _query() -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space_1"),
        memory_scope_ids=(MemoryScopeId("scope_1"),),
        query="visible fact",
        token_budget=512,
    )
