import pytest
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_text_sha256,
)


def test_text_commitment_rejects_non_utf8_surrogate_nominally() -> None:
    with pytest.raises(MemoryValidationError, match="text commitment is invalid"):
        managed_benchmark_text_sha256("\ud800")
