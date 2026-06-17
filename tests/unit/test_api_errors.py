import asyncio
import json

from memo_stack_core.domain.errors import MemoryValidationError
from memo_stack_server.api.errors import memory_error_handler


def test_memory_error_handler_redacts_sensitive_message_text() -> None:
    response = asyncio.run(
        memory_error_handler(
            None,
            MemoryValidationError(
                "invalid value Authorization: Bearer sk-proj-api-error-secret-value"
            ),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert payload["error"]["code"] == "memory.validation"
    assert "sk-proj-api-error-secret-value" not in payload["error"]["message"]
    assert "[redacted]" in payload["error"]["message"]
