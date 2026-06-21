from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "multimodal_live_provider_canary.py"
PACKAGE_PATHS = (
    "packages/infinity_context_core",
    "packages/infinity_context_server",
    "packages/infinity_context_adapters",
    "packages/infinity_context_sdk",
    "packages/infinity_context_mcp",
    "packages/infinity_context_cli",
)


def test_multimodal_live_provider_canary_reports_missing_key_without_secret_leak(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "provider-canary.json"
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())
    sentinel = "sk-test-secret-that-must-not-leak"
    env = _test_env_without_openai_keys()
    env["MEMORY_AGENT_BENCH_OPENAI_API_KEY"] = sentinel
    env["MEMORY_MULTIMODAL_PROVIDER_AUDIO_FIXTURE"] = str(audio_fixture)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report-out",
            str(report_path),
            "--skip-invalid-key-probe",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    stdout_report = json.loads(result.stdout)
    file_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert stdout_report == file_report
    assert file_report["ok"] is False
    assert file_report["suite"] == "infinity-context-multimodal-live-provider-canary"
    assert file_report["required_env"] == [
        "MEMORY_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY_FILE"
    ]
    assert file_report["secrets_redacted"] is True
    assert isinstance(file_report["generated_at"], str)
    assert file_report["git"]["commit"]
    assert file_report["git"]["short_commit"]
    assert isinstance(file_report["git"]["dirty"], bool)
    assert file_report["provenance"]["schema_version"] == 1
    assert file_report["provenance"]["generated_by"] == (
        "scripts/multimodal_live_provider_canary.py"
    )
    assert file_report["provenance"]["suite"] == (
        "infinity-context-multimodal-live-provider-canary"
    )
    assert file_report["provenance"]["git"]["commit"]
    assert file_report["provenance"]["runtime"]["python_version"]
    assert file_report["provider_key_present"] is False
    assert file_report["provider_contract"]["timeout_probe_seconds"] == 0.001
    assert file_report["provider_contract"]["transcription"] == {
        "docs_url": "https://developers.openai.com/api/docs/guides/speech-to-text",
        "endpoint": "/v1/audio/transcriptions",
        "max_upload_bytes": 26214400,
        "model": "gpt-4o-mini-transcribe",
        "required_live_file_types": [".mp3", ".wav"],
        "request_contract": {
            "chunking_strategy": None,
            "requires_chunking_strategy": False,
            "response_format": "json",
            "speaker_segments_supported": False,
            "supports_prompt": True,
            "supports_segment_timestamps": False,
            "timestamp_granularities": [],
        },
        "supported_file_types": [
            ".flac",
            ".m4a",
            ".mp3",
            ".mp4",
            ".mpeg",
            ".mpga",
            ".ogg",
            ".wav",
            ".webm",
        ],
    }
    assert file_report["provider_contract"]["vision"] == {
        "detail": "low",
        "detail_levels": ["low", "high", "auto"],
        "docs_url": "https://developers.openai.com/api/docs/guides/images-vision",
        "endpoint_family": "responses",
        "max_images_per_request": 1500,
        "max_provider_binary_upload_bytes": 402650094,
        "max_provider_payload_bytes": 536870912,
        "model": "gpt-4.1-mini",
        "supported_file_types": [".gif", ".jpeg", ".jpg", ".png", ".webp"],
    }
    assert file_report["failure_policy_contract"] == _expected_failure_policy_contract()
    proof = file_report["proof_matrix"]
    assert proof["schema_version"] == "multimodal-provider-proof-matrix-v1"
    assert proof["summary"] == {
        "contract_requirements_passed": 8,
        "contract_requirements_total": 9,
        "live_requirements_passed": 0,
        "live_requirements_total": 7,
    }
    assert file_report["readiness"] == {
        "blocking_requirements": [
            "vision_real_provider",
            "vision_response_evidence",
            "audio_transcription_real_provider",
            "transcription_response_artifact",
            "audio_transcription_format_matrix",
            "audio_fixture_format_coverage",
            "invalid_key_live_probe",
            "timeout_live_probe",
        ],
        "live_provider_key_required": True,
        "next_steps": [
            "configure_provider_credential",
            "provide_wav_and_mp3_audio_fixtures",
            "run_invalid_key_probe",
        ],
        "operator_actions": [
            "configure_provider_credential",
            "inspect_provider_canary",
        ],
        "production_ready": False,
        "schema_version": "multimodal-provider-readiness-v1",
        "status": "blocked_by_provider_credential",
    }
    requirements = proof["requirements"]
    assert requirements["vision_real_provider"] == {
        "ok": False,
        "proof": "live_provider_call",
        "reason": "provider_credential_missing",
        "requires_provider_key": True,
        "status": "skipped",
    }
    assert requirements["vision_response_evidence"] == {
        "ok": False,
        "proof": "live_provider_evidence_shape",
        "reason": "provider_credential_missing",
        "requires_provider_key": True,
        "status": "skipped",
    }
    assert requirements["audio_transcription_real_provider"] == {
        "ok": False,
        "proof": "live_provider_call",
        "reason": "provider_credential_missing",
        "requires_provider_key": True,
        "status": "skipped",
    }
    assert requirements["transcription_response_artifact"] == {
        "ok": False,
        "proof": "live_provider_artifact_shape",
        "reason": "provider_credential_missing",
        "requires_provider_key": True,
        "status": "skipped",
    }
    assert requirements["audio_transcription_format_matrix"] == {
        "covered_suffixes": [],
        "ok": False,
        "proof": "live_provider_format_matrix",
        "reason": "provider_credential_missing",
        "required_suffixes": [".mp3", ".wav"],
        "requires_provider_key": True,
        "status": "skipped",
    }
    vision_fixture = requirements["vision_fixture_contract"]
    assert vision_fixture["ok"] is True
    assert vision_fixture["proof"] == "local_fixture_contract"
    assert vision_fixture["requires_provider_key"] is False
    assert vision_fixture["status"] == "contract_covered"
    assert vision_fixture["suffix"] == ".png"
    assert vision_fixture["content_type"] == "image/png"
    audio_contract = requirements["audio_fixture_contract"]
    assert audio_contract["ok"] is True
    assert audio_contract["proof"] == "local_fixture_contract"
    assert audio_contract["requires_provider_key"] is False
    assert audio_contract["status"] == "contract_covered"
    assert audio_contract["suffix"] == ".wav"
    assert audio_contract["content_type"] == "audio/wav"
    assert requirements["audio_fixture_format_coverage"] == {
        "covered_suffixes": [".wav"],
        "ok": False,
        "proof": "local_fixture_format_matrix",
        "required_suffixes": [".mp3", ".wav"],
        "requires_provider_key": False,
        "status": "degraded",
    }
    assert requirements["invalid_key_classification"]["status"] == "contract_covered"
    assert requirements["transcription_request_contract"] == {
        "ok": True,
        "proof": "adapter_request_contract",
        "requires_chunking_strategy": False,
        "requires_provider_key": False,
        "response_format": "json",
        "status": "contract_covered",
        "supports_prompt": True,
        "supports_segment_timestamps": False,
    }
    assert requirements["invalid_key_live_probe"] == {
        "ok": False,
        "proof": "live_invalid_credential_call",
        "reason": "invalid_key_probe_skipped_by_request",
        "requires_provider_key": False,
        "status": "skipped",
    }
    assert requirements["timeout_live_probe"] == {
        "ok": False,
        "proof": "live_timeout_call",
        "reason": "provider_credential_missing",
        "requires_provider_key": True,
        "status": "skipped",
    }
    assert requirements["rate_limit_classification"]["status"] == "contract_covered"
    assert requirements["timeout_classification"]["status"] == "contract_covered"
    assert requirements["no_secret_leak_guard"] == {
        "ok": True,
        "proof": "bounded_report_redaction",
        "requires_provider_key": False,
        "status": "contract_covered",
    }
    assert requirements["report_safety_contract"]["ok"] is True
    assert requirements["report_safety_contract"]["status"] == "contract_covered"
    assert file_report["components"]["provider_key"] == {
        "message": (
            "Set MEMORY_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY_FILE "
            "before running the live provider canary"
        ),
        "operator_action": "configure_provider_credential",
        "reason": "provider_credential_missing",
        "status": "degraded",
        "user_retryable": False,
    }
    assert file_report["components"]["vision"] == {
        "operator_action": "configure_provider_credential",
        "reason": "provider_credential_missing",
        "status": "skipped",
        "user_retryable": False,
    }
    assert file_report["components"]["transcription"] == {
        "operator_action": "configure_provider_credential",
        "reason": "provider_credential_missing",
        "status": "skipped",
        "user_retryable": False,
    }
    assert file_report["components"]["vision_fixture"]["status"] == "succeeded"
    assert file_report["components"]["vision_fixture"]["fixture"]["role"] == "image_vision"
    assert file_report["components"]["audio_fixture"]["status"] == "succeeded"
    assert file_report["components"]["audio_fixture"]["fixture"]["role"] == "audio_transcription"
    assert file_report["components"]["invalid_key_probe"] == {
        "operator_action": "inspect_provider_canary",
        "reason": "invalid_key_probe_skipped_by_request",
        "status": "skipped",
        "user_retryable": False,
    }
    combined_output = result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    assert sentinel not in combined_output
    assert "MEMORY_AGENT_BENCH_OPENAI_API_KEY" not in combined_output


def test_multimodal_live_provider_canary_allow_missing_key_is_contract_only(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "provider-contract-canary.json"
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())
    env = _test_env_without_openai_keys()
    env["MEMORY_MULTIMODAL_PROVIDER_AUDIO_FIXTURE"] = str(audio_fixture)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report-out",
            str(report_path),
            "--allow-missing-key",
            "--skip-invalid-key-probe",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["components"]["provider_key"]["status"] == "degraded"
    assert report["proof_matrix"]["requirements"]["invalid_key_live_probe"]["status"] == (
        "skipped"
    )
    assert report["readiness"]["production_ready"] is False
    assert report["readiness"]["status"] == "blocked_by_provider_credential"
    assert report["secrets_redacted"] is True


def test_multimodal_live_provider_canary_has_local_fixtures_and_redaction() -> None:
    module = _load_canary_module()

    assert module._content_type_for_path(Path("fixture.wav")) == "audio/wav"
    assert module._content_type_for_path(Path("fixture.mp3")) == "audio/mpeg"
    assert module._content_type_for_path(Path("fixture.bin")) == ("application/octet-stream")
    assert module._sample_png_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    sample_wav = module._sample_wav_bytes()
    assert sample_wav.startswith(b"RIFF")
    assert sample_wav[8:12] == b"WAVE"
    safe = module._safe_diagnostics(
        {
            "api_key": "sk-test-secret",
            "access_token": "secret-token",
            "authorization": "Bearer secret",
            "message": "provider echoed sk-test-secret-value and Bearer live-secret",
            "request_timeout_seconds": 10,
            "nested": {
                "detail": "Authorization failed for Bearer nested-secret",
                "api_key": "sk-nested-secret-value",
            },
            "events": ["ok", "sk-list-secret-value"],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    )
    component = module._component(
        "failed",
        reason="asset_extraction.vision.invalid_api_key",
        message="request used Bearer component-secret and sk-component-secret-value",
    )

    assert "api_key" not in safe
    assert "access_token" not in safe
    assert "authorization" not in safe
    assert safe["message"] == "provider echoed <redacted> and <redacted>"
    assert safe["request_timeout_seconds"] == 10
    assert safe["nested"] == {"detail": "Authorization failed for <redacted>"}
    assert safe["events"] == ["ok", "<redacted>"]
    assert safe["usage"] == {"input_tokens": 1, "output_tokens": 2}
    assert component["message"] == "request used <redacted> and <redacted>"


def test_multimodal_live_provider_canary_maps_invalid_key_to_operator_action() -> None:
    module = _load_canary_module()

    component = module._component(
        "failed",
        reason="asset_extraction.vision.invalid_api_key",
        message="provider rejected credential",
    )

    assert component == {
        "message": "provider rejected credential",
        "operator_action": "replace_provider_credential",
        "reason": "asset_extraction.vision.invalid_api_key",
        "status": "failed",
        "user_retryable": False,
    }


def test_multimodal_live_provider_canary_invalid_key_probe_is_redacted(
    monkeypatch,
) -> None:
    module = _load_canary_module()

    async def fake_run_vision(*, api_key: str, args: object) -> dict[str, object]:
        assert api_key == module.INVALID_KEY_PROBE_VALUE
        assert args is not None
        return {
            "diagnostics": {"message": f"provider rejected {api_key}"},
            "reason": "asset_extraction.vision.invalid_api_key",
            "status": "failed",
        }

    async def fake_run_transcription(*, args: object) -> dict[str, object]:
        assert args is not None
        return {
            "diagnostics": {"message": f"provider rejected {module.INVALID_KEY_PROBE_VALUE}"},
            "reason": "asset_extraction.transcription.invalid_api_key",
            "status": "failed",
        }

    monkeypatch.setattr(module, "_run_vision", fake_run_vision)
    monkeypatch.setattr(module, "_run_invalid_transcription_key_probe", fake_run_transcription)

    component = asyncio.run(
        module._run_invalid_key_probe(args=module._parse_args(["--probe-invalid-key"]))
    )
    rendered = json.dumps(component, sort_keys=True)

    assert component["status"] == "succeeded"
    assert component["proof"] == "live_invalid_credential_call"
    assert component["probe_mode"] == "explicit"
    assert component["observed_statuses"] == {
        "transcription": "failed",
        "vision": "failed",
    }
    assert component["observed_reasons"] == {
        "transcription": "asset_extraction.transcription.invalid_api_key",
        "vision": "asset_extraction.vision.invalid_api_key",
    }
    assert component["provider_probe_count"] == 2
    assert component["diagnostics"] == {
        "transcription": {"message": "provider rejected <redacted>"},
        "vision": {"message": "provider rejected <redacted>"},
    }
    assert module.INVALID_KEY_PROBE_VALUE not in rendered


def test_multimodal_live_provider_canary_auto_probes_invalid_key_without_real_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())
    monkeypatch.delenv("MEMORY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def fake_invalid_key_probe(
        *,
        args: object,
        probe_mode: str = "explicit",
    ) -> dict[str, object]:
        assert args is not None
        return module._component(
            "succeeded",
            proof="live_invalid_credential_call",
            probe_mode=probe_mode,
            observed_reason=(
                "vision:asset_extraction.vision.invalid_api_key; "
                "transcription:asset_extraction.transcription.invalid_api_key"
            ),
            observed_reasons={
                "vision": "asset_extraction.vision.invalid_api_key",
                "transcription": "asset_extraction.transcription.invalid_api_key",
            },
            observed_statuses={"vision": "failed", "transcription": "failed"},
            provider_probe_count=2,
            diagnostics={"message": "provider rejected <redacted>"},
        )

    monkeypatch.setattr(module, "_run_invalid_key_probe", fake_invalid_key_probe)

    report = asyncio.run(
        module.run_multimodal_live_provider_canary(
            module._parse_args(["--audio-fixture", str(audio_fixture)])
        )
    )

    assert report["ok"] is False
    assert report["provider_key_present"] is False
    assert report["components"]["provider_key"]["reason"] == "provider_credential_missing"
    assert report["components"]["timeout_probe"]["reason"] == "provider_credential_missing"
    assert report["components"]["invalid_key_probe"] == {
        "diagnostics": {"message": "provider rejected <redacted>"},
        "observed_reason": (
            "vision:asset_extraction.vision.invalid_api_key; "
            "transcription:asset_extraction.transcription.invalid_api_key"
        ),
        "observed_reasons": {
            "transcription": "asset_extraction.transcription.invalid_api_key",
            "vision": "asset_extraction.vision.invalid_api_key",
        },
        "observed_statuses": {"transcription": "failed", "vision": "failed"},
        "probe_mode": "auto_no_key",
        "proof": "live_invalid_credential_call",
        "provider_probe_count": 2,
        "status": "succeeded",
    }
    assert report["proof_matrix"]["requirements"]["invalid_key_live_probe"] == {
        "ok": True,
        "observed_reason": (
            "vision:asset_extraction.vision.invalid_api_key; "
            "transcription:asset_extraction.transcription.invalid_api_key"
        ),
        "observed_reasons": {
            "transcription": "asset_extraction.transcription.invalid_api_key",
            "vision": "asset_extraction.vision.invalid_api_key",
        },
        "proof": "live_invalid_credential_call",
        "provider_probe_count": 2,
        "requires_provider_key": False,
        "status": "succeeded",
    }
    assert report["proof_matrix"]["summary"] == {
        "contract_requirements_passed": 8,
        "contract_requirements_total": 9,
        "live_requirements_passed": 1,
        "live_requirements_total": 7,
    }
    assert report["provenance"]["generated_by"] == ("scripts/multimodal_live_provider_canary.py")
    assert report["provenance"]["suite"] == ("infinity-context-multimodal-live-provider-canary")


def test_multimodal_live_provider_canary_can_skip_auto_invalid_key_probe() -> None:
    module = _load_canary_module()
    args = module._parse_args(["--skip-invalid-key-probe"])

    assert module._invalid_key_probe_mode(args, has_provider_key=False) is None
    assert (
        module._invalid_key_probe_skip_reason(args, has_provider_key=False)
        == "invalid_key_probe_skipped_by_request"
    )
    assert module._invalid_key_probe_mode(args, has_provider_key=True) is None
    assert (
        module._invalid_key_probe_skip_reason(args, has_provider_key=True)
        == "invalid_key_probe_not_requested"
    )


def test_multimodal_live_provider_canary_requires_invalid_key_probe_by_default() -> None:
    module = _load_canary_module()
    args = module._parse_args([])

    assert module._invalid_key_probe_mode(args, has_provider_key=False) == "auto_no_key"
    assert module._invalid_key_probe_mode(args, has_provider_key=True) == "auto_with_key"


def test_multimodal_live_provider_canary_explicit_invalid_key_probe_overrides_skip() -> None:
    module = _load_canary_module()
    args = module._parse_args(["--probe-invalid-key", "--skip-invalid-key-probe"])

    assert module._invalid_key_probe_mode(args, has_provider_key=False) == "explicit"
    assert module._invalid_key_probe_mode(args, has_provider_key=True) == "explicit"


def test_multimodal_live_provider_canary_timeout_probe_modes() -> None:
    module = _load_canary_module()

    default_args = module._parse_args([])
    assert module._timeout_probe_mode(default_args, has_provider_key=False) is None
    assert module._timeout_probe_mode(default_args, has_provider_key=True) == "auto_with_key"

    skip_args = module._parse_args(["--skip-timeout-probe"])
    assert module._timeout_probe_mode(skip_args, has_provider_key=True) is None
    assert (
        module._timeout_probe_skip_reason(skip_args, has_provider_key=True)
        == "timeout_probe_skipped_by_request"
    )

    explicit_args = module._parse_args(["--probe-timeout", "--skip-timeout-probe"])
    assert module._timeout_probe_mode(explicit_args, has_provider_key=False) == "explicit"
    assert module._timeout_probe_mode(explicit_args, has_provider_key=True) == "explicit"


def test_multimodal_live_provider_canary_timeout_probe_succeeds_on_timeout(
    monkeypatch,
) -> None:
    module = _load_canary_module()
    observed_timeouts: list[float] = []

    async def fake_run_vision(
        *,
        api_key: str,
        args: object,
    ) -> dict[str, object]:
        assert api_key == "sk-test-provider-key"
        observed_timeouts.append(args.timeout_seconds)
        return module._component(
            "failed",
            reason="asset_extraction.vision.timeout",
            diagnostics={"request_timeout_seconds": args.timeout_seconds},
        )

    async def fake_run_timeout_transcription_probe(
        *,
        api_key: str,
        args: object,
    ) -> dict[str, object]:
        assert api_key == "sk-test-provider-key"
        observed_timeouts.append(args.timeout_seconds)
        return module._component(
            "failed",
            reason="asset_extraction.transcription.timeout",
            diagnostics={"request_timeout_seconds": args.timeout_seconds},
        )

    monkeypatch.setattr(module, "_run_vision", fake_run_vision)
    monkeypatch.setattr(
        module,
        "_run_timeout_transcription_probe",
        fake_run_timeout_transcription_probe,
    )

    result = asyncio.run(
        module._run_timeout_probe(
            api_key="sk-test-provider-key",
            args=module._parse_args(["--timeout-probe-seconds", "0.0001"]),
        )
    )

    assert observed_timeouts == [0.001, 0.001]
    assert result["status"] == "succeeded"
    assert result["proof"] == "live_timeout_call"
    assert result["observed_reason"] == (
        "vision:asset_extraction.vision.timeout; "
        "transcription:asset_extraction.transcription.timeout"
    )
    assert result["observed_reasons"] == {
        "vision": "asset_extraction.vision.timeout",
        "transcription": "asset_extraction.transcription.timeout",
    }
    assert result["provider_probe_count"] == 2
    assert result["requires_provider_key"] is True


def test_multimodal_live_provider_canary_timeout_probe_rejects_non_timeout(
    monkeypatch,
) -> None:
    module = _load_canary_module()

    async def fake_run_vision(
        *,
        api_key: str,
        args: object,
    ) -> dict[str, object]:
        return module._component(
            "failed",
            reason="asset_extraction.vision.rate_limited",
            diagnostics={"request_timeout_seconds": args.timeout_seconds},
        )

    async def fake_run_timeout_transcription_probe(
        *,
        api_key: str,
        args: object,
    ) -> dict[str, object]:
        return module._component(
            "failed",
            reason="asset_extraction.transcription.timeout",
            diagnostics={"request_timeout_seconds": args.timeout_seconds},
        )

    monkeypatch.setattr(module, "_run_vision", fake_run_vision)
    monkeypatch.setattr(
        module,
        "_run_timeout_transcription_probe",
        fake_run_timeout_transcription_probe,
    )

    result = asyncio.run(
        module._run_timeout_probe(
            api_key="sk-test-provider-key",
            args=module._parse_args(["--timeout-probe-seconds", "2.0"]),
        )
    )

    assert result["status"] == "failed"
    assert result["reason"] == "timeout_probe_unexpected_result"
    assert result["observed_reason"] == (
        "vision:asset_extraction.vision.rate_limited; "
        "transcription:asset_extraction.transcription.timeout"
    )
    assert result["observed_reasons"] == {
        "vision": "asset_extraction.vision.rate_limited",
        "transcription": "asset_extraction.transcription.timeout",
    }
    assert result["failed_providers"] == ["vision"]
    assert result["timeout_seconds"] == 0.25


def test_multimodal_live_provider_canary_proof_matrix_tracks_invalid_key_probe() -> None:
    module = _load_canary_module()
    components = {
        "vision": {"status": "skipped", "reason": "provider_credential_missing"},
        "transcription": {"status": "skipped", "reason": "provider_credential_missing"},
        "invalid_key_probe": {
            "observed_reason": (
                "vision:asset_extraction.vision.invalid_api_key; "
                "transcription:asset_extraction.transcription.invalid_api_key"
            ),
            "observed_reasons": {
                "vision": "asset_extraction.vision.invalid_api_key",
                "transcription": "asset_extraction.transcription.invalid_api_key",
            },
            "proof": "live_invalid_credential_call",
            "provider_probe_count": 2,
            "status": "succeeded",
        },
    }

    proof = module._proof_matrix(
        components=components,
        failure_policy_contract=module._failure_policy_contract(),
        provider_contract=module._base_report(
            module._parse_args([]),
            has_provider_key=False,
        )["provider_contract"],
        provider_key_present=False,
        secrets_redacted=True,
        report_safety_contract=module._report_safety_contract(
            {
                "components": components,
                "failure_policy_contract": module._failure_policy_contract(),
                "provider_contract": module._base_report(
                    module._parse_args([]),
                    has_provider_key=False,
                )["provider_contract"],
            }
        ),
    )

    assert proof["requirements"]["invalid_key_live_probe"] == {
        "ok": True,
        "observed_reason": (
            "vision:asset_extraction.vision.invalid_api_key; "
            "transcription:asset_extraction.transcription.invalid_api_key"
        ),
        "observed_reasons": {
            "transcription": "asset_extraction.transcription.invalid_api_key",
            "vision": "asset_extraction.vision.invalid_api_key",
        },
        "proof": "live_invalid_credential_call",
        "provider_probe_count": 2,
        "requires_provider_key": False,
        "status": "succeeded",
    }


def test_multimodal_live_provider_canary_proof_matrix_tracks_live_artifacts() -> None:
    module = _load_canary_module()
    args = module._parse_args([])
    request_contract = module.openai_transcription_request_contract(args.transcription_model)

    proof = module._proof_matrix(
        components={
            "vision": {
                "status": "succeeded",
                "summary_chars": 40,
                "visible_text_count": 1,
            },
            "transcription": {
                "status": "succeeded",
                "request_contract": request_contract,
                "transcript_chars": 52,
                "segment_count": 0,
                "word_count": 0,
            },
            "invalid_key_probe": {"status": "skipped"},
            "timeout_probe": {
                "status": "succeeded",
                "observed_reason": (
                    "vision:asset_extraction.vision.timeout; "
                    "transcription:asset_extraction.transcription.timeout"
                ),
                "observed_reasons": {
                    "vision": "asset_extraction.vision.timeout",
                    "transcription": "asset_extraction.transcription.timeout",
                },
                "provider_probe_count": 2,
                "timeout_seconds": 0.001,
            },
        },
        failure_policy_contract=module._failure_policy_contract(),
        provider_contract=module._base_report(args, has_provider_key=True)["provider_contract"],
        provider_key_present=True,
        secrets_redacted=True,
        report_safety_contract=module._report_safety_contract(
            {
                "components": {
                    "vision": {
                        "status": "succeeded",
                        "summary_chars": 40,
                        "visible_text_count": 1,
                    },
                    "transcription": {
                        "status": "succeeded",
                        "request_contract": request_contract,
                        "transcript_chars": 52,
                        "segment_count": 0,
                        "word_count": 0,
                    },
                    "invalid_key_probe": {"status": "skipped"},
                    "timeout_probe": {
                        "status": "succeeded",
                        "observed_reason": (
                            "vision:asset_extraction.vision.timeout; "
                            "transcription:asset_extraction.transcription.timeout"
                        ),
                        "observed_reasons": {
                            "vision": "asset_extraction.vision.timeout",
                            "transcription": "asset_extraction.transcription.timeout",
                        },
                        "provider_probe_count": 2,
                        "timeout_seconds": 0.001,
                    },
                },
                "failure_policy_contract": module._failure_policy_contract(),
                "provider_contract": module._base_report(args, has_provider_key=True)[
                    "provider_contract"
                ],
            }
        ),
    )

    assert proof["requirements"]["vision_response_evidence"] == {
        "ok": True,
        "proof": "live_provider_evidence_shape",
        "requires_provider_key": True,
        "status": "succeeded",
        "summary_chars": 40,
        "visible_text_count": 1,
    }
    assert proof["requirements"]["transcription_response_artifact"] == {
        "ok": True,
        "proof": "live_provider_artifact_shape",
        "requires_provider_key": True,
        "response_format": "json",
        "segment_count": 0,
        "status": "succeeded",
        "transcript_chars": 52,
        "word_count": 0,
    }
    assert proof["requirements"]["audio_transcription_format_matrix"] == {
        "covered_suffixes": [],
        "ok": False,
        "proof": "live_provider_format_matrix",
        "required_suffixes": [".mp3", ".wav"],
        "requires_provider_key": True,
        "status": "failed",
    }
    assert proof["requirements"]["timeout_live_probe"] == {
        "ok": True,
        "observed_reason": (
            "vision:asset_extraction.vision.timeout; "
            "transcription:asset_extraction.transcription.timeout"
        ),
        "observed_reasons": {
            "transcription": "asset_extraction.transcription.timeout",
            "vision": "asset_extraction.vision.timeout",
        },
        "proof": "live_timeout_call",
        "provider_probe_count": 2,
        "requires_provider_key": True,
        "status": "succeeded",
        "timeout_seconds": 0.001,
    }


def test_multimodal_live_provider_canary_redacts_configured_key_from_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    sentinel = "sk-live-secret-that-must-not-leak"
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())

    class FailedVisionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def analyze(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="failed",
                safe_error_code="asset_extraction.vision.invalid_api_key",
                safe_error_message=f"provider echoed {sentinel} and Bearer {sentinel}",
                provider_name="fake_vision",
                provider_model="fake-vision-model",
                provider_version="fake-version",
                diagnostics={
                    "api_key": sentinel,
                    "message": f"Authorization failed for Bearer {sentinel}",
                },
            )

    class FailedTranscriptionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def transcribe(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="failed",
                safe_error_code="asset_extraction.transcription.rate_limited",
                safe_error_message=f"provider echoed {sentinel}",
                provider_name="fake_transcription",
                provider_model="fake-transcription-model",
                provider_version="fake-version",
                diagnostics={
                    "authorization": f"Bearer {sentinel}",
                    "message": f"retry later for {sentinel}",
                },
            )

    monkeypatch.setenv("MEMORY_OPENAI_API_KEY", sentinel)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(module, "OpenAIImageVisionAdapter", FailedVisionAdapter)
    monkeypatch.setattr(module, "OpenAISpeechTranscriptionAdapter", FailedTranscriptionAdapter)

    report = asyncio.run(
        module.run_multimodal_live_provider_canary(
            module._parse_args(["--audio-fixture", str(audio_fixture)])
        )
    )

    rendered = json.dumps(report, sort_keys=True)
    assert report["provider_key_present"] is True
    assert report["secrets_redacted"] is True
    assert report["proof_matrix"]["requirements"]["no_secret_leak_guard"]["ok"] is True
    assert report["proof_matrix"]["requirements"]["report_safety_contract"]["ok"] is True
    assert report["report_safety"]["ok"] is True
    assert report["components"]["vision"]["operator_action"] == "replace_provider_credential"
    assert report["components"]["transcription"]["operator_action"] == "retry_later"
    assert sentinel not in rendered
    assert "Bearer sk-" not in rendered


def test_multimodal_live_provider_canary_rejects_unsafe_report_surface() -> None:
    module = _load_canary_module()
    args = module._parse_args([])
    components = {
        "vision": module._component(
            "failed",
            reason="asset_extraction.vision.timeout",
            message="x" * (module._MAX_REPORT_STRING_CHARS + 1),
            raw_provider_payload={"body": "provider response must not be public"},
        ),
        "transcription": module._component(
            "skipped",
            reason="provider_credential_missing",
        ),
        "invalid_key_probe": module._component(
            "skipped",
            reason="invalid_key_probe_not_requested",
        ),
        "timeout_probe": module._component(
            "skipped",
            reason="provider_credential_missing",
        ),
    }
    safety = module._report_safety_contract(
        {
            "components": components,
            "failure_policy_contract": module._failure_policy_contract(),
            "provider_contract": module._base_report(args, has_provider_key=True)[
                "provider_contract"
            ],
        }
    )
    proof = module._proof_matrix(
        components=components,
        failure_policy_contract=module._failure_policy_contract(),
        provider_contract=module._base_report(args, has_provider_key=True)["provider_contract"],
        provider_key_present=True,
        secrets_redacted=True,
        report_safety_contract=safety,
    )
    readiness = module._readiness_summary(
        {
            "components": components,
            "proof_matrix": proof,
            "provider_key_present": True,
        }
    )

    assert safety["ok"] is False
    assert set(safety["failed_checks"]) == {
        "bounded_strings",
        "no_raw_provider_payloads",
    }
    assert proof["requirements"]["report_safety_contract"]["ok"] is False
    assert "report_safety_contract" in readiness["blocking_requirements"]
    assert "inspect_provider_canary_report" in readiness["next_steps"]


def test_multimodal_live_provider_canary_transcribes_wav_and_mp3_matrix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    wav_fixture = tmp_path / "fixture.wav"
    mp3_fixture = tmp_path / "fixture.mp3"
    wav_fixture.write_bytes(_valid_wav_bytes())
    mp3_fixture.write_bytes(_valid_mp3_bytes())

    class SuccessfulTranscriptionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def transcribe(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="succeeded",
                text=f"transcribed {request.content_type}",
                segments=[],
                words=[],
                language="en",
                duration_seconds=1.0,
                provider_name="fake_transcription",
                provider_model="fake-transcription-model",
                provider_version="fake-version",
                diagnostics={"request_timeout_seconds": 1},
            )

    monkeypatch.setattr(module, "OpenAISpeechTranscriptionAdapter", SuccessfulTranscriptionAdapter)
    args = module._parse_args(
        [
            "--audio-fixture",
            str(wav_fixture),
            "--extra-audio-fixture",
            str(mp3_fixture),
            "--timeout-seconds",
            "1",
        ]
    )

    result = asyncio.run(module._run_transcription(api_key="sk-test-provider-key", args=args))
    proof = module._proof_matrix(
        components={
            "vision": {"status": "succeeded", "summary_chars": 10, "visible_text_count": 0},
            "transcription": result,
            "vision_fixture": module._vision_fixture_preflight(),
            "audio_fixtures": module._audio_fixtures_preflight(args),
            "audio_fixture": module._audio_fixture_preflight(args),
            "invalid_key_probe": {
                "status": "succeeded",
                "observed_reason": "asset_extraction.vision.invalid_api_key",
            },
        },
        failure_policy_contract=module._failure_policy_contract(),
        provider_contract=module._base_report(args, has_provider_key=True)["provider_contract"],
        provider_key_present=True,
        secrets_redacted=True,
        report_safety_contract=module._report_safety_contract(
            {
                "components": {
                    "vision": {"status": "succeeded", "summary_chars": 10, "visible_text_count": 0},
                    "transcription": result,
                    "vision_fixture": module._vision_fixture_preflight(),
                    "audio_fixtures": module._audio_fixtures_preflight(args),
                    "audio_fixture": module._audio_fixture_preflight(args),
                    "invalid_key_probe": {
                        "status": "succeeded",
                        "observed_reason": "asset_extraction.vision.invalid_api_key",
                    },
                },
                "failure_policy_contract": module._failure_policy_contract(),
                "provider_contract": module._base_report(args, has_provider_key=True)[
                    "provider_contract"
                ],
            }
        ),
    )

    assert result["status"] == "succeeded"
    assert result["covered_suffixes"] == [".mp3", ".wav"]
    assert len(result["format_results"]) == 2
    assert proof["requirements"]["audio_transcription_format_matrix"] == {
        "covered_suffixes": [".mp3", ".wav"],
        "ok": True,
        "proof": "live_provider_format_matrix",
        "required_suffixes": [".mp3", ".wav"],
        "requires_provider_key": True,
        "status": "succeeded",
    }
    assert proof["requirements"]["audio_fixture_format_coverage"] == {
        "covered_suffixes": [".mp3", ".wav"],
        "ok": True,
        "proof": "local_fixture_format_matrix",
        "required_suffixes": [".mp3", ".wav"],
        "requires_provider_key": False,
        "status": "contract_covered",
    }


def test_multimodal_live_provider_canary_failure_policy_contract_covers_provider_errors() -> None:
    module = _load_canary_module()

    assert module._failure_policy_contract() == _expected_failure_policy_contract()


def test_multimodal_live_provider_canary_default_report_matches_goal_audit(
    monkeypatch,
) -> None:
    module = _load_canary_module()
    monkeypatch.delenv("MEMORY_MULTIMODAL_PROVIDER_CANARY_REPORT_OUT", raising=False)

    args = module._parse_args([])

    assert args.report_out == ".e2e-artifacts/multimodal-live-provider-canary.json"
    assert args.allow_missing_key is False
    assert args.api_key_file is None


def test_multimodal_live_provider_canary_reads_api_key_file_without_report_leak(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    sentinel = "sk-live-file-secret-that-must-not-leak"
    key_file = tmp_path / "openai-key.env"
    key_file.write_text(
        f"# local secret file\nexport MEMORY_OPENAI_API_KEY='{sentinel}'\n",
        encoding="utf-8",
    )
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())

    class FailedVisionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def analyze(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="failed",
                safe_error_code="asset_extraction.vision.invalid_api_key",
                safe_error_message=f"provider echoed {sentinel}",
                provider_name="fake_vision",
                provider_model="fake-vision-model",
                provider_version="fake-version",
                diagnostics={"message": f"Authorization failed for Bearer {sentinel}"},
            )

    class FailedTranscriptionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def transcribe(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="failed",
                safe_error_code="asset_extraction.transcription.invalid_api_key",
                safe_error_message=f"provider echoed {sentinel}",
                provider_name="fake_transcription",
                provider_model="fake-transcription-model",
                provider_version="fake-version",
                diagnostics={"message": f"Authorization failed for Bearer {sentinel}"},
            )

    monkeypatch.delenv("MEMORY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(module, "OpenAIImageVisionAdapter", FailedVisionAdapter)
    monkeypatch.setattr(module, "OpenAISpeechTranscriptionAdapter", FailedTranscriptionAdapter)
    args = module._parse_args(
        [
            "--api-key-file",
            str(key_file),
            "--audio-fixture",
            str(audio_fixture),
            "--skip-invalid-key-probe",
            "--skip-timeout-probe",
        ]
    )

    assert module._provider_api_key(args) == sentinel
    report = asyncio.run(module.run_multimodal_live_provider_canary(args))
    rendered = json.dumps(report, sort_keys=True)

    assert report["provider_key_present"] is True
    assert report["components"]["provider_key"] == {"status": "configured"}
    assert report["secrets_redacted"] is True
    assert sentinel not in rendered
    assert str(key_file) not in rendered


def test_multimodal_live_provider_canary_api_key_file_parsing_and_precedence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    raw_file = tmp_path / "raw.key"
    raw_file.write_text("sk-file-secret\n", encoding="utf-8")
    env_file = tmp_path / "openai.env"
    env_file.write_text(
        'OTHER=value\nOPENAI_API_KEY="sk-env-file-secret"\n',
        encoding="utf-8",
    )

    monkeypatch.delenv("MEMORY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert module._provider_api_key(module._parse_args(["--api-key-file", str(raw_file)])) == (
        "sk-file-secret"
    )
    assert module._provider_api_key(module._parse_args(["--api-key-file", str(env_file)])) == (
        "sk-env-file-secret"
    )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-process-env-secret")
    assert module._provider_api_key(module._parse_args(["--api-key-file", str(raw_file)])) == (
        "sk-process-env-secret"
    )

    empty_file = tmp_path / "empty.env"
    empty_file.write_text("# no key here\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = module._parse_args(["--api-key-file", str(empty_file)])
    assert module._provider_api_key(args) is None
    assert module._provider_key_missing_reason(args) == "provider_credential_file_unusable"


def test_multimodal_live_provider_canary_reports_model_specific_vision_details() -> None:
    module = _load_canary_module()
    args = module._parse_args(["--vision-model", "gpt-5.5"])

    report = module._base_report(args, has_provider_key=False)

    assert report["provider_contract"]["vision"]["detail_levels"] == [
        "low",
        "high",
        "original",
        "auto",
    ]


def test_multimodal_live_provider_canary_preflights_audio_fixture_contract(
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    valid = tmp_path / "fixture.wav"
    valid.write_bytes(_valid_wav_bytes())
    unsupported = tmp_path / "fixture.aac"
    unsupported.write_bytes(b"ADTS")
    mismatch = tmp_path / "mismatch.wav"
    mismatch.write_bytes(b"not actually wav")
    huge = tmp_path / "fixture.mp3"
    with huge.open("wb") as handle:
        handle.truncate(module.OPENAI_AUDIO_MAX_UPLOAD_BYTES + 1)

    assert module._audio_fixture_contract_check(valid) == {"status": "succeeded"}
    assert module._audio_fixture_contract_check(mismatch) == {
        "content_type": "audio/wav",
        "filename_suffix": ".wav",
        "message": "Audio fixture bytes do not match the configured file type",
        "operator_action": "replace_audio_fixture",
        "reason": "audio_fixture_content_mismatch",
        "status": "degraded",
        "user_retryable": False,
    }
    assert module._audio_fixture_contract_check(unsupported) == {
        "filename_suffix": ".aac",
        "message": "Audio fixture type is not supported by OpenAI transcription upload",
        "operator_action": "replace_audio_fixture",
        "reason": "audio_fixture_unsupported_type",
        "status": "degraded",
        "supported_file_types": [
            ".flac",
            ".m4a",
            ".mp3",
            ".mp4",
            ".mpeg",
            ".mpga",
            ".ogg",
            ".wav",
            ".webm",
        ],
        "user_retryable": False,
    }
    too_large = module._audio_fixture_contract_check(huge)
    assert too_large["status"] == "degraded"
    assert too_large["reason"] == "audio_fixture_too_large"
    assert too_large["operator_action"] == "replace_audio_fixture"
    assert too_large["max_upload_bytes"] == 26214400


def test_multimodal_live_provider_canary_preflights_local_fixtures_without_key(
    tmp_path: Path,
) -> None:
    module = _load_canary_module()
    audio_fixture = tmp_path / "fixture.wav"
    audio_fixture.write_bytes(_valid_wav_bytes())
    args = module._parse_args(["--audio-fixture", str(audio_fixture)])

    vision = module._vision_fixture_preflight()
    audio = module._audio_fixture_preflight(args)
    components = {
        "vision": module._component("skipped", reason="provider_credential_missing"),
        "transcription": module._component("skipped", reason="provider_credential_missing"),
        "vision_fixture": vision,
        "audio_fixture": audio,
        "invalid_key_probe": module._component(
            "skipped",
            reason="invalid_key_probe_not_requested",
        ),
    }
    proof = module._proof_matrix(
        components=components,
        failure_policy_contract=module._failure_policy_contract(),
        provider_contract=module._base_report(args, has_provider_key=False)["provider_contract"],
        provider_key_present=False,
        secrets_redacted=True,
        report_safety_contract=module._report_safety_contract(
            {
                "components": components,
                "failure_policy_contract": module._failure_policy_contract(),
                "provider_contract": module._base_report(args, has_provider_key=False)[
                    "provider_contract"
                ],
            }
        ),
    )

    assert vision["status"] == "succeeded"
    assert vision["fixture"]["role"] == "image_vision"
    assert audio["status"] == "succeeded"
    assert audio["fixture"]["role"] == "audio_transcription"
    assert proof["requirements"]["vision_fixture_contract"]["ok"] is True
    assert proof["requirements"]["vision_fixture_contract"]["requires_provider_key"] is False
    assert proof["requirements"]["audio_fixture_contract"]["ok"] is True
    assert proof["requirements"]["audio_fixture_contract"]["requires_provider_key"] is False
    assert proof["summary"] == {
        "contract_requirements_passed": 8,
        "contract_requirements_total": 9,
        "live_requirements_passed": 0,
        "live_requirements_total": 7,
    }


def test_multimodal_live_provider_canary_requires_strong_synthetic_transcript() -> None:
    module = _load_canary_module()

    weak = module._transcript_check("memo", audio_path=None)
    strong = module._transcript_check(
        "Infinity Context live transcription canary",
        audio_path=None,
    )
    explicit_fixture = module._transcript_check("user supplied fixture", audio_path="voice.wav")

    assert weak == {
        "matched_terms": [],
        "message": "Synthetic speech transcript missed expected canary terms",
        "missing_terms": ["canary", "context", "infinity"],
        "min_similarity": 0.55,
        "min_term_matches": 2,
        "operator_action": "inspect_provider_canary",
        "reason": "synthetic_transcript_mismatch",
        "similarity": 0.043,
        "status": "failed",
        "term_match_count": 0,
        "user_retryable": False,
    }
    assert strong == {
        "matched_terms": ["canary", "context", "infinity"],
        "similarity": 1.0,
        "status": "succeeded",
        "term_match_count": 3,
    }
    assert module._transcript_check(
        "Infinite contacts live transcription canary.",
        audio_path=None,
    ) == {
        "matched_terms": ["canary", "context", "infinity"],
        "similarity": 0.918,
        "status": "succeeded",
        "term_match_count": 3,
    }
    assert explicit_fixture == {"status": "succeeded"}


def test_multimodal_live_provider_canary_rejects_empty_vision_evidence(
    monkeypatch,
) -> None:
    module = _load_canary_module()
    image = module._sample_png_bytes()
    fixture = module._bytes_fixture_summary(
        role="image_vision",
        source="generated_png_fixture",
        filename="infinity-context-live-vision-canary.png",
        content_type="image/png",
        content=image,
        expected_visible_text=module.SYNTHETIC_VISION_TEXT,
    )

    class EmptyVisionAdapter:
        def __init__(self, **_: object) -> None:
            pass

        async def analyze(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="succeeded",
                payload={"summary": "", "visible_text": []},
                payload_status="parsed",
                provider_name="fake_vision",
                provider_model="fake-model",
                provider_version="fake-version",
                diagnostics={"request_timeout_seconds": 1},
            )

    monkeypatch.setattr(module, "OpenAIImageVisionAdapter", EmptyVisionAdapter)

    result = asyncio.run(
        module._run_vision(
            api_key="sk-test-provider-key",
            args=module._parse_args(["--timeout-seconds", "1"]),
        )
    )

    assert result == {
        "diagnostics": {"request_timeout_seconds": 1},
        "fixture": fixture,
        "message": "Provider returned no visible text or image summary",
        "operator_action": "inspect_provider_canary",
        "payload_status": "parsed",
        "provider_model": "fake-model",
        "provider_name": "fake_vision",
        "provider_version": "fake-version",
        "reason": "vision_empty_evidence",
        "status": "failed",
        "summary_chars": 0,
        "user_retryable": False,
        "visible_text_count": 0,
    }


def _test_env_without_openai_keys() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("MEMORY_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env["PYTHONPATH"] = _pythonpath(env)
    return env


def _pythonpath(env: dict[str, str]) -> str:
    parts = [str(ROOT / path) for path in PACKAGE_PATHS]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    return os.pathsep.join(parts)


def _load_canary_module():
    for path in reversed(PACKAGE_PATHS):
        sys.path.insert(0, str(ROOT / path))
    spec = importlib.util.spec_from_file_location(
        "multimodal_live_provider_canary_for_test",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_failure_policy_contract() -> dict[str, dict[str, object]]:
    return {
        "provider_credential_missing": {
            "operator_action": "configure_provider_credential",
            "reason": "provider_credential_missing",
            "status": "degraded",
            "user_retryable": False,
        },
        "invalid_api_key": {
            "operator_action": "replace_provider_credential",
            "reason": "asset_extraction.vision.invalid_api_key",
            "status": "failed",
            "user_retryable": False,
        },
        "quota_exceeded": {
            "operator_action": "check_provider_billing",
            "reason": "asset_extraction.transcription.quota_exceeded",
            "status": "failed",
            "user_retryable": False,
        },
        "rate_limited": {
            "operator_action": "retry_later",
            "reason": "asset_extraction.transcription.rate_limited",
            "status": "failed",
            "user_retryable": True,
        },
        "timeout": {
            "operator_action": "retry_later",
            "reason": "asset_extraction.vision.timeout",
            "status": "failed",
            "user_retryable": True,
        },
    }


def _valid_wav_bytes() -> bytes:
    return b"RIFF$\x00\x00\x00WAVEfmt " + b"\0" * 32


def _valid_mp3_bytes() -> bytes:
    return b"ID3\x04\x00\x00\x00\x00\x00\x15TIT2\x00\x00\x00\x0b\x00\x00canary mp3"
