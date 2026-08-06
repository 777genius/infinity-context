from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from infinity_context_server.processes.fact_projections import FactProjectionOutboxProcess
from infinity_context_server.processes.outbox import ClaimedOutboxJob


@dataclass
class _CognitiveRecorder:
    events: list[str] = field(default_factory=list)

    async def handle_fact_changed(self, job: ClaimedOutboxJob) -> None:
        self.events.append(job.event_type)


@dataclass
class _ProjectionRecorder:
    events: list[str] = field(default_factory=list)

    async def handle_graph_upsert(self, job: ClaimedOutboxJob) -> None:
        self.events.append(job.event_type)

    async def handle_graph_delete(self, job: ClaimedOutboxJob) -> None:
        self.events.append(job.event_type)


def test_legacy_graph_commands_do_not_invalidate_canonical_cognition() -> None:
    process, cognitive, projections = _process()

    asyncio.run(process.handle_legacy_upsert(_job("graph.upsert_fact")))
    asyncio.run(process.handle_legacy_delete(_job("graph.delete_fact")))

    assert cognitive.events == []
    assert projections.events == ["graph.upsert_fact", "graph.delete_fact"]


def test_canonical_fact_change_fans_out_to_cognition_and_graph() -> None:
    process, cognitive, projections = _process()

    asyncio.run(process.handle_canonical_change(_job("fact.updated")))

    assert cognitive.events == ["fact.updated"]
    assert projections.events == ["fact.updated"]


def _process() -> tuple[
    FactProjectionOutboxProcess,
    _CognitiveRecorder,
    _ProjectionRecorder,
]:
    process = FactProjectionOutboxProcess(object())
    cognitive = _CognitiveRecorder()
    projections = _ProjectionRecorder()
    process._cognitive = cognitive  # type: ignore[assignment]
    process._projections = projections  # type: ignore[assignment]
    return process, cognitive, projections


def _job(event_type: str) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=1,
        event_type=event_type,
        aggregate_id="fact-1",
        aggregate_version=1,
        attempt_count=0,
        workload_class="projection",
        fairness_key="fact:fact-1",
        payload_json={},
    )
