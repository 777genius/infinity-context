import pytest
from memo_stack_core.application.capture_policy import CaptureAdmissionService


@pytest.mark.parametrize(
    "text,raw_secret",
    [
        (
            "Remember: Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
            "Bearer abcdefghijklmnopqrstuvwxyz123456",
        ),
        (
            "Remember: ghp_abcdefghijklmnopqrstuvwxyz1234567890 should not leak",
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        ),
        (
            "Remember: AWS key AKIA1234567890ABCDEF should not leak",
            "AKIA1234567890ABCDEF",
        ),
        (
            "Remember: PASSWORD=super-secret-password-12345 should not leak",
            "PASSWORD=super-secret-password-12345",
        ),
        (
            (
                "Remember: -----BEGIN PRIVATE KEY-----\n"
                "abcdefghijklmnopqrstuvwxyz1234567890\n"
                "-----END PRIVATE KEY----- should not leak"
            ),
            "abcdefghijklmnopqrstuvwxyz1234567890",
        ),
    ],
)
def test_capture_admission_redacts_common_credential_forms(
    text: str,
    raw_secret: str,
) -> None:
    result = CaptureAdmissionService().admit(text)

    assert result.accepted is True
    assert result.redacted is True
    assert result.reason == "redacted"
    assert "[redacted-secret]" in result.text
    assert raw_secret not in result.text


def test_capture_admission_rejects_secret_only_capture() -> None:
    result = CaptureAdmissionService().admit("Bearer abcdefghijklmnopqrstuvwxyz123456")

    assert result.accepted is False
    assert result.redacted is True
    assert result.reason == "secret_rejected"
    assert result.text == "[redacted-secret]"
