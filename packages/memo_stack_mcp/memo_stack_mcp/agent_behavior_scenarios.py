"""Scenario routing for the agent behavior benchmark."""

from __future__ import annotations

from memo_stack_mcp.agent_behavior_scenarios_core import default_scenarios
from memo_stack_mcp.agent_behavior_scenarios_realistic import (
    live_session_scenarios,
    realistic_scenarios,
)
from memo_stack_mcp.agent_behavior_scenarios_transcript import (
    transcript_corpus_scenarios,
)
from memo_stack_mcp.agent_behavior_types import AgentBenchFailure, AgentBenchScenario


def scenarios_for_set(name: str) -> tuple[AgentBenchScenario, ...]:
    if name == "core":
        return default_scenarios()
    if name == "realistic":
        return realistic_scenarios()
    if name == "live":
        return live_session_scenarios()
    if name == "transcript":
        return transcript_corpus_scenarios()
    if name == "all":
        return (
            default_scenarios()
            + realistic_scenarios()
            + live_session_scenarios()
            + transcript_corpus_scenarios()
        )
    raise AgentBenchFailure(
        "MEMORY_AGENT_BENCH_SCENARIO_SET must be one of: core, realistic, live, "
        "transcript, all"
    )
