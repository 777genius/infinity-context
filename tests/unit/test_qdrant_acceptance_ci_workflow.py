from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "infinity-context-ci.yml"


def _workflow_job(name: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = f"\n  {name}:\n"
    assert workflow.count(marker) == 1
    tail = workflow.split(marker, maxsplit=1)[1]
    next_job = re.search(r"\n  [a-zA-Z0-9_-]+:\n", tail)
    return tail if next_job is None else tail[: next_job.start()]


def test_real_qdrant_acceptance_is_exact_head_and_mandatory() -> None:
    job = _workflow_job("qdrant-locator-acceptance")
    quality = _workflow_job("quality")

    assert "name: Real Qdrant 16,385-point locator acceptance" in job
    assert "if:" not in job.replace("if: always()", "")
    assert "continue-on-error:" not in job
    assert "timeout-minutes: 45" in job
    assert "actions/checkout@v7.0.1" in job
    assert "actions/setup-python@v7.0.0" in job
    assert "actions/upload-artifact@v7.0.1" in job
    assert '"uv==0.11.28"' in job
    assert "uv sync --extra dev --extra qdrant --frozen --link-mode copy" in job
    assert "--all-extras" not in job
    assert job.count("${{ github.event.pull_request.head.sha || github.sha }}") == 3
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"' in job
    assert "persist-credentials: false" in job

    assert "- qdrant-locator-acceptance" in quality
    assert (
        "QDRANT_LOCATOR_ACCEPTANCE_RESULT: "
        "${{ needs.qdrant-locator-acceptance.result }}" in quality
    )
    assert 'test "$QDRANT_LOCATOR_ACCEPTANCE_RESULT" = "success"' in quality


def test_real_qdrant_acceptance_pins_services_resources_and_test_contract() -> None:
    job = _workflow_job("qdrant-locator-acceptance")

    assert "image: postgres:18" in job
    assert "image: qdrant/qdrant:v1.18.0" in job
    assert "--cpus 1.5" in job
    assert "--memory 2g" in job
    assert "--cpus 2" in job
    assert "--memory 3g" in job
    assert 'INFINITY_RUN_LOCATOR_QDRANT_E2E: "1"' in job
    preserved_environment = (
        "INFINITY_CONTEXT_TEST_POSTGRES_URL,"
        "INFINITY_SANDBOX_QDRANT_URL,"
        "INFINITY_RUN_LOCATOR_QDRANT_E2E,"
        "HF_HUB_OFFLINE,"
        "TRANSFORMERS_OFFLINE,"
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
    )
    assert f"sudo \\\n            --preserve-env={preserved_environment}" in job
    scoped_git_configuration = (
        'env \\\n'
        '            GIT_CONFIG_COUNT=1 \\\n'
        '            GIT_CONFIG_KEY_0=safe.directory \\\n'
        '            GIT_CONFIG_VALUE_0="$GITHUB_WORKSPACE" \\\n'
        "            timeout --signal=TERM --kill-after=30s 40m"
    )
    assert scoped_git_configuration in job
    assert "git config --global" not in job
    assert "git config --system" not in job
    assert "sudo -E" not in job
    assert "timeout --signal=TERM --kill-after=30s 40m" in job
    assert (
        "test_locator_retrieval_v2_qdrant_e2e.py::"
        "test_real_qdrant_large_profile_resumes_attests_and_physically_deletes" in job
    )
    assert "--junitxml=test-results/qdrant-locator-acceptance.xml" in job
    assert "if test ! -s test-results/qdrant-locator-acceptance.xml" in job
    assert 'exit "$acceptance_status"' in job
    assert "if: always()" in job
    assert "if-no-files-found: error" in job


def test_real_qdrant_acceptance_exposes_only_copied_runtime_artifacts() -> None:
    job = _workflow_job("qdrant-locator-acceptance")

    assert 'chmod -R o+rX "$GITHUB_WORKSPACE/.venv"' in job
    assert 'sudo -u nobody test -x "$GITHUB_WORKSPACE/.venv/bin/python"' in job
    assert (
        'sudo -u nobody "$GITHUB_WORKSPACE/.venv/bin/python" -c \\\n'
        '            "from importlib.metadata import version; '
        "assert version('qdrant-client')\""
    ) in job
    assert "--link-mode copy" in job
    assert "chmod -R o+rX \"$GITHUB_WORKSPACE\"" not in job
    assert job.index("--link-mode copy") < job.index("chmod -R o+rX")
    assert job.index("chmod -R o+rX") < job.index("Wait for real Qdrant")


def test_real_qdrant_acceptance_scrubs_provider_credentials() -> None:
    job = _workflow_job("qdrant-locator-acceptance")

    for name in (
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "MEMORY_OPENAI_API_KEY",
        "MEMORY_AGENT_BENCH_OPENAI_API_KEY",
        "MEM0_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "COHERE_API_KEY",
        "VOYAGE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "HF_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "QDRANT_API_KEY",
    ):
        assert f'{name}: ""' in job
    assert "${{ secrets." not in job
    assert 'HF_HUB_OFFLINE: "1"' in job
    assert 'TRANSFORMERS_OFFLINE: "1"' in job
    assert "GIT_CONFIG_COUNT: " not in job
    assert "GIT_CONFIG_KEY_0: " not in job
    assert "GIT_CONFIG_VALUE_0: " not in job

    preserve_option = re.search(r"--preserve-env=(\S+)", job)
    assert preserve_option is not None
    preserved_names = set(preserve_option.group(1).split(","))
    assert preserved_names == {
        "INFINITY_CONTEXT_TEST_POSTGRES_URL",
        "INFINITY_SANDBOX_QDRANT_URL",
        "INFINITY_RUN_LOCATOR_QDRANT_E2E",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    }
