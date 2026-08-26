from __future__ import annotations

import pytest
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionAdvance,
    PublishableExtractionAdvancePhase,
    PublishableExtractionWorkerError,
)
from infinity_context_server.publishable_input_preparation import (
    PublishableInputPreparationError,
)
from infinity_context_server.publishable_input_preparation import (
    composition as input_composition,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationJournalSnapshot,
)


def test_recovery_operator_action_survives_input_preparation_boundary() -> None:
    class AmbiguousWorker:
        def read_terminal(self):
            return None

        def advance_one(self) -> PublishableExtractionAdvance:
            snapshot = object.__new__(OperationJournalSnapshot)
            object.__setattr__(snapshot, "committed_count", 0)
            return PublishableExtractionAdvance(
                phase=PublishableExtractionAdvancePhase.RECONCILIATION_REQUIRED,
                journal_snapshot=snapshot,
            )

        def reconcile_one(self):
            raise PublishableExtractionWorkerError("extraction_recovery_operator_action_required")

    with pytest.raises(PublishableInputPreparationError) as error:
        input_composition._drive_worker(AmbiguousWorker(), max_steps=1)

    assert error.value.code == "publishable_input_extraction_recovery_operator_action_required"
