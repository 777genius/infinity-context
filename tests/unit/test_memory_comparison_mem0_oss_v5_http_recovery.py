"""Recovery-specific Mem0 v5 HTTP status classification."""

import pytest
from test_memory_comparison_mem0_oss_v5_adapters import (
    Mem0V5HttpError,
    Mem0V5StatusRequest,
    _admission,
    _digest,
    _http,
    _operation_id,
    _Response,
    _Transport,
)


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (500, "mem0_v5_http_remote_failed"),
        (503, "mem0_v5_http_remote_failed"),
        (401, "mem0_v5_http_response_rejected"),
        (403, "mem0_v5_http_response_rejected"),
        (409, "mem0_v5_http_response_rejected"),
    ),
)
def test_recovery_http_status_classification(status: int, code: str) -> None:
    admission, _ = _admission()
    request = Mem0V5StatusRequest(
        admission.commitment_sha256,
        _operation_id(admission),
        _digest("recovery-status"),
    )

    with pytest.raises(Mem0V5HttpError, match=code):
        _http(_Transport(_Response(status, b"{}"))).status(request)
