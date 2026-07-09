"""Workflow-oriented query expansion rules for tasks and deadlines."""

from __future__ import annotations

_FOLLOWUP_TASK_EXPANSION = (
    "action item task todo follow up next step reminder assigned owner "
    "responsible assignee commitment promised agreed need needs must supposed "
    "expected left remaining open outstanding pending unfinished due date "
    "deadline meeting call decision status"
)
_RU_FOLLOWUP_TASK_EXPANSION = (
    "задача задачи поручение поручения назначено напоминание напомни "
    "action item task todo follow up next step owner responsible assigned "
    "commitment promised agreed need needs must supposed expected due date "
    "deadline meeting call decision"
)
_RU_RESPONSIBLE_TASK_EXPANSION = (
    "задача задачи поручение поручения назначено напоминание напомни "
    "ответственный responsible owner assignee action item task todo follow up "
    "next step commitment promised agreed need needs must supposed expected "
    "due date deadline meeting call decision"
)
_DEADLINE_COMMITMENT_EXPANSION = (
    "deadline due date target date schedule milestone timeline deliverable overdue "
    "upcoming commitment action item follow up meeting call decision promised agreed"
)
_RU_DEADLINE_COMMITMENT_EXPANSION = (
    "дедлайн срок сроки дата сдачи целевая дата просрочено просроченные график "
    "milestone timeline deliverable commitment action item follow up meeting call decision"
)
_GOTCHA_FAILURE_EXPANSION = (
    "gotcha pitfall caveat known issue known problem failure failed error broke "
    "blocked blocker blockers blocked on risk warning workaround root cause "
    "troubleshooting avoid do not repeat next time prerequisite limitation trap"
)
_RU_GOTCHA_FAILURE_EXPANSION = (
    "подводные камни известная проблема ошибка сбой сломалось упало заблокировано "
    "риск предупреждение обходной путь причина воркэраунд избегать не повторять "
    "gotcha pitfall known issue failure failed blocked workaround"
)

WORKFLOW_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"подводные"}),
        _RU_GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"ошибка"}),
        _RU_GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"воркэраунд"}),
        _RU_GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"gotcha_failure_request"}),
        _GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"known", "issue"}),
        _GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"known", "problem"}),
        _GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"failure"}),
        _GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"workaround"}),
        _GOTCHA_FAILURE_EXPANSION,
        "gotcha_failure_bridge",
    ),
    (
        frozenset({"workflow_commitment_request"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"action", "item"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"follow", "up"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"next", "step"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"task"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"todo"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"reminder"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"promise"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"promised"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"commitment"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"committed"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"agreed"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"owner"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"responsible"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"assigned"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"assignee"}),
        _FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"задача"}),
        _RU_FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"ответственный"}),
        _RU_RESPONSIBLE_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"напоминание"}),
        _RU_FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"поручение"}),
        _RU_FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"назначено"}),
        _RU_FOLLOWUP_TASK_EXPANSION,
        "followup_task_bridge",
    ),
    (
        frozenset({"deadline"}),
        _DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"due", "when"}),
        _DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"due", "date"}),
        _DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"overdue"}),
        _DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"upcoming"}),
        _DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"дедлайн"}),
        _RU_DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"срок"}),
        _RU_DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"просрочено"}),
        _RU_DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
    (
        frozenset({"просроченные"}),
        _RU_DEADLINE_COMMITMENT_EXPANSION,
        "deadline_commitment_bridge",
    ),
)
