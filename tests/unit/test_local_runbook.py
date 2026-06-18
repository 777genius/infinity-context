import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[2]


def test_docker_compose_bootstraps_local_server_before_http() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "pg_isready -U memo_stack -d memo_stack" in compose
    assert "condition: service_healthy" in compose
    assert "python -m memo_stack_server.db upgrade" in compose
    assert "python -m memo_stack_server.admin seed-defaults" in compose
    assert "http://127.0.0.1:7788/v1/health" in compose


def test_makefile_has_one_command_stack_smoke_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    quality_recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-test-quality"))

    assert ".PHONY: memo-stack-smoke" in makefile
    assert (
        "$(COMPOSE) --profile lite up -d memo_stack_server memo_stack_worker "
        "memo_stack_extraction_worker"
    ) in makefile
    assert (
        "memo-stack-test-quality: memo-stack-lint memo-stack-test-all memo-stack-eval"
        in makefile
    )
    assert "$(MAKE) memo-stack-secret-scan" in quality_recipe
    assert "$(PYTHON) -m memo_stack_server eval run --suite quality-golden" in makefile
    assert "$(PYTHON) -m memo_stack_server eval run --suite semantic-linking-golden" in makefile
    assert "$(PYTHON) -m memo_stack_server eval run --suite long-memory-golden" in makefile
    assert "$(PYTHON) -m pytest tests/e2e" in makefile
    assert ".PHONY: memo-stack-multimodal-production-e2e" in makefile
    assert (
        "$(PYTHON) -m pytest tests/e2e/test_multimodal_production_acceptance_e2e.py "
        "tests/e2e/test_multimodal_ingestion_edge_cases_e2e.py -q"
        in makefile
    )
    assert ".PHONY: memo-stack-multimodal-live-provider-canary" in makefile
    assert "$(PYTHON) scripts/multimodal_live_provider_canary.py" in makefile
    assert "curl -fsS http://127.0.0.1:7788/v1/health" in makefile
    assert "$(MAKE) memo-stack-api-smoke" in makefile


def test_makefile_has_frontend_quality_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "FRONTEND_DIR ?= frontend" in makefile
    assert "FLUTTER ?=" in makefile
    assert "MEMORY_FRONTEND_MARIONETTE_REPORT ?=" in makefile
    assert ".PHONY: memo-stack-frontend-pub-get" in makefile
    assert ".PHONY: memo-stack-frontend-analyze" in makefile
    assert ".PHONY: memo-stack-frontend-test" in makefile
    assert ".PHONY: memo-stack-frontend-build-macos" in makefile
    assert ".PHONY: memo-stack-frontend-check" in makefile
    assert ".PHONY: memo-stack-frontend-marionette-local-e2e" in makefile
    assert (
        "memo-stack-frontend-check: memo-stack-frontend-analyze memo-stack-frontend-test"
    ) in makefile
    assert "cd $(FRONTEND_DIR) && $(FLUTTER) pub get" in makefile
    assert "cd $(FRONTEND_DIR) && $(FLUTTER) analyze" in makefile
    assert "cd $(FRONTEND_DIR) && $(FLUTTER) test" in makefile
    assert "cd $(FRONTEND_DIR) && $(FLUTTER) build macos --debug" in makefile
    assert "--report-out \"$(MEMORY_FRONTEND_MARIONETTE_REPORT)\"" in makefile


def test_frontend_marionette_local_e2e_report_contract(tmp_path: Path) -> None:
    module = _load_frontend_marionette_local_e2e(
        ROOT / "scripts" / "frontend_marionette_local_e2e.py"
    )
    args = SimpleNamespace(
        device="macos",
        host="127.0.0.1",
        port=17789,
        space_slug="marionette-local-proof",
    )
    report = module._base_report(
        args,
        root=ROOT,
        frontend_dir=ROOT / "frontend",
        scope_ref="marionette-local-proof-unit",
        run_id="unit-run",
    )
    report["components"]["server"] = module._component("succeeded")
    report["components"]["worker"] = module._component("succeeded")
    report["components"]["flutter_marionette"] = module._component(
        "succeeded",
        exit_code=0,
    )
    report["components"]["flutter_runtime_log"] = module._component(
        "succeeded",
        forbidden_marker_count=0,
        markers=[],
    )
    report["ok"] = True
    report["exit_code"] = 0
    report["finished_at"] = module._utc_now()
    report_out = tmp_path / "frontend-marionette-report.json"
    flow_report = tmp_path / "frontend-marionette-flow-report.json"
    flow_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "succeeded",
                "run_marker": "unit-run",
                "completed_flow_count": 2,
                "completed_flows": [
                    "memory_scope_management",
                    "context_link_reject",
                ],
            }
        ),
        encoding="utf-8",
    )

    module._attach_flow_report(report, flow_report)
    module._write_report(report, str(report_out))
    persisted = json.loads(report_out.read_text(encoding="utf-8"))
    rendered = json.dumps(persisted, ensure_ascii=False)

    assert persisted["schema_version"] == 1
    assert persisted["suite"] == "memo-stack-frontend-marionette-local-e2e"
    assert persisted["ok"] is True
    assert persisted["secrets_redacted"] is True
    assert persisted["frontend"]["dir_name"] == "frontend"
    assert persisted["backend"] == {
        "database": "sqlite",
        "host": "127.0.0.1",
        "port": 17789,
        "profile": "test",
    }
    assert persisted["components"]["flutter_marionette"]["status"] == "succeeded"
    assert persisted["components"]["flutter_runtime_log"] == {
        "status": "succeeded",
        "forbidden_marker_count": 0,
        "markers": [],
    }
    assert persisted["flow_coverage"] == {
        "schema_version": 1,
        "status": "succeeded",
        "run_marker": "unit-run",
        "completed_flow_count": 2,
        "completed_flows": [
            "memory_scope_management",
            "context_link_reject",
        ],
    }
    assert set(persisted["git"]) == {"commit", "short_commit", "dirty"}
    assert str(ROOT) not in rendered
    assert "local-dev-token" not in rendered
    assert "OPENAI_API_KEY" not in rendered


def test_frontend_marionette_runtime_log_component_flags_flutter_errors() -> None:
    module = _load_frontend_marionette_local_e2e(
        ROOT / "scripts" / "frontend_marionette_local_e2e.py"
    )
    markers: list[dict[str, str]] = []

    module._collect_flutter_runtime_marker(
        "EXCEPTION CAUGHT BY WIDGETS LIBRARY: token Bearer sk-test-secret",
        markers,
    )
    module._collect_flutter_runtime_marker(
        "A RenderFlex overflowed by 42 pixels on the right.",
        markers,
    )

    component = module._flutter_runtime_log_component(markers)
    rendered = json.dumps(component)

    assert component["status"] == "failed"
    assert component["forbidden_marker_count"] == 2
    assert component["markers"][0]["marker"] == "EXCEPTION CAUGHT BY"
    assert "Bearer <redacted>" in rendered
    assert "sk-test-secret" not in rendered
    assert module._flutter_runtime_log_component([]) == {
        "status": "succeeded",
        "forbidden_marker_count": 0,
        "markers": [],
    }


def test_selfhost_compose_has_team_deployment_contract() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.selfhost.yml").read_text(encoding="utf-8")
    env = (ROOT / ".env.selfhost.example").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "self-hosted-team-deployment.md").read_text(
        encoding="utf-8"
    )
    smoke = (ROOT / "scripts" / "selfhost_smoke.py").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert 'CMD ["python", "-m", "memo_stack_server.main"]' in dockerfile
    assert 'ENTRYPOINT ["memo-stack-entrypoint"]' in dockerfile
    assert 'exec gosu memo "$@"' in dockerfile or (
        'exec gosu memo "$@"'
        in (ROOT / "docker" / "memo-stack-entrypoint.sh").read_text(encoding="utf-8")
    )
    assert "MEMORY_DEPLOY_PROFILE: server" in compose
    assert 'MEMORY_AUTO_CREATE_SCHEMA: "false"' in compose
    assert "memo_stack_migrate:" in compose
    assert "memo_stack_projection_worker:" in compose
    assert "memo_stack_extraction_worker:" in compose
    assert "--role projection" in compose
    assert "--role extraction" in compose
    assert "memo_stack_assets:/var/lib/memo-stack/assets" in compose
    assert (
        "MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS: "
        "${MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS:-1}" in compose
    )
    assert (
        "MEMORY_EXTRACTION_HEARTBEAT_SECONDS: "
        "${MEMORY_EXTRACTION_HEARTBEAT_SECONDS:-15}" in compose
    )
    assert "MEMORY_SERVICE_TOKEN=change-me" in env
    assert "MEMORY_POSTGRES_PASSWORD=change-me" in env
    assert "MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS=1" in env
    assert "MEMORY_EXTRACTION_HEARTBEAT_SECONDS=15" in env
    assert ".PHONY: memo-stack-selfhost-smoke" in makefile
    assert "$(PYTHON) scripts/selfhost_smoke.py" in makefile
    assert '"postgres/migrations/*.sql"' in pyproject
    assert "Back up Postgres and assets first" in runbook
    assert 'f"{base_url}/v1/assets?{query}"' in smoke
    assert 'f"{base_url}/v1/asset-extractions/{extraction_id}"' in smoke
    assert 'f"{base_url}/v1/documents/{document_ids[0]}/chunks"' in smoke


def test_makefile_runs_graph_native_eval_in_quality_gates() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    eval_recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-eval"))

    assert "$(PYTHON) -m memo_stack_server eval run --suite long-memory-golden" in eval_recipe
    assert "$(PYTHON) -m memo_stack_server eval run --suite semantic-linking-golden" in eval_recipe
    assert ".PHONY: memo-stack-graph-native-eval" in makefile
    assert "$(PYTHON) -m memo_stack_server eval run --suite graph-native-golden" in eval_recipe
    assert (
        "memo-stack-auto-memory-quality: memo-stack-capture-test "
        "memo-stack-hook-capture-smoke memo-stack-auto-memory-eval "
        "memo-stack-graph-native-eval"
    ) in makefile


def test_makefile_has_memory_quality_scorecard_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    eval_runner = (
        ROOT / "packages" / "memo_stack_server" / "memo_stack_server" / "eval.py"
    ).read_text(encoding="utf-8")
    bundle_script = (ROOT / "scripts" / "quality_evidence_bundle.py").read_text(
        encoding="utf-8"
    )
    top_evidence_preflight = (
        ROOT
        / "packages"
        / "memo_stack_server"
        / "memo_stack_server"
        / "top_evidence_preflight.py"
    ).read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-quality-scorecard" in makefile
    assert "$(PYTHON) -m memo_stack_server eval scorecard" in makefile
    assert ".PHONY: memo-stack-quality-scorecard-from-reports" in makefile
    assert ".PHONY: memo-stack-quality-scorecard-top-evidence" in makefile
    assert ".PHONY: memo-stack-quality-evidence-bundle" in makefile
    assert ".PHONY: memo-stack-top-evidence-preflight" in makefile
    assert ".PHONY: memo-stack-top-evidence-bundle" in makefile
    assert "MEMORY_SCORECARD_SUITE_REPORTS" in makefile
    assert "MEMORY_SCORECARD_EXTRA_REPORTS" in makefile
    assert "MEMORY_QUALITY_EVIDENCE_DIR" in makefile
    assert "MEMORY_QUALITY_EVIDENCE_REQUIRE_TOP" in makefile
    assert "$(PYTHON) scripts/quality_evidence_bundle.py" in makefile
    top_evidence_recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-top-evidence-bundle")
    )
    assert 'MEMORY_CLEAN_SMOKE_REPORT_OUT="$$external_report"' in top_evidence_recipe
    assert "$(PYTHON) -m memo_stack_server.top_evidence_preflight --json" in (
        top_evidence_recipe
    )
    assert "MEMORY_CLEAN_SMOKE_PUBLIC_BENCHMARK=true" in top_evidence_recipe
    assert "MEMORY_CLEAN_SMOKE_AGENT_BENCH=true" in top_evidence_recipe
    assert 'MEMORY_AGENT_BENCH_SCENARIO_SET="$${MEMORY_AGENT_BENCH_SCENARIO_SET:-all}"' in (
        top_evidence_recipe
    )
    assert "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET" in top_evidence_preflight
    assert "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET" in top_evidence_preflight
    assert "MEMORY_AGENT_BENCH_SCENARIO_SET=all" in top_evidence_preflight
    assert 'MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-all}"' in (
        top_evidence_recipe
    )
    assert (
        'MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-600}"'
        in top_evidence_recipe
    )
    assert (
        'MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.902}"'
        in top_evidence_recipe
    )
    assert '$(PYTHON) scripts/quality_evidence_bundle.py \\' in top_evidence_recipe
    assert '--output-dir "$$evidence_dir"' in top_evidence_recipe
    assert '--extra-report "$$external_report"' in top_evidence_recipe
    assert "--require-top-evidence" in top_evidence_recipe
    assert "--suite-report" in makefile
    assert "--require-top-evidence" in makefile
    assert 'scorecard.add_argument(\n        "--suite-report"' in eval_runner
    assert 'scorecard.add_argument(\n        "--require-top-evidence"' in eval_runner
    assert 'snapshots.add_argument("--report-out"' in eval_runner
    assert "from memo_stack_server.evidence_bundle import main" in bundle_script


def test_makefile_has_clean_full_mcp_smoke_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    clean_full_smoke = (ROOT / "scripts" / "clean_full_smoke.py").read_text(
        encoding="utf-8"
    )

    assert ".PHONY: memo-stack-clean-full-mcp-smoke" in makefile
    assert "memo-stack-clean-full-mcp-smoke:" in makefile
    assert "MEMORY_CLEAN_SMOKE_SKIP_MCP=false" in makefile
    assert "$(PYTHON) scripts/clean_full_smoke.py" in makefile
    assert "MEMORY_CLEAN_SMOKE_REPORT_OUT" in clean_full_smoke
    assert "memo-stack-full-provider-canary" in clean_full_smoke


def test_makefile_has_manual_prod_load_canary_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = _make_target_recipe(makefile, "memo-stack-prod-load-canary")

    assert ".PHONY: memo-stack-prod-load-canary" in makefile
    assert "MEMORY_CLEAN_SMOKE_PROD_LOAD=true" in "\n".join(recipe)
    assert "MEMORY_CLEAN_SMOKE_SKIP_MCP=false" in "\n".join(recipe)
    assert "MEMORY_OPENAI_API_KEY" in "\n".join(recipe)
    assert (
        "memo-stack-test-quality: memo-stack-lint memo-stack-test-all memo-stack-eval"
        in makefile
    )
    assert "memo-stack-test-quality: memo-stack-prod-load-canary" not in makefile


def test_makefile_has_memory_plugin_gate_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-plugin-test" in makefile
    assert (
        "memo-stack-plugin-test: memo-stack-plugin-check "
        "memo-stack-plugin-validate memo-stack-plugin-e2e"
        in makefile
    )
    assert "$(PYTHON) -m pytest tests/e2e/test_memo_stack_agent_plugin_e2e.py -q" in makefile


def test_makefile_has_prod_confidence_gate_with_cleanup() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-prod-confidence"))

    assert ".PHONY: memo-stack-prod-confidence" in makefile
    assert ".PHONY: memo-stack-secret-scan" in makefile
    assert "trap cleanup EXIT INT TERM" in recipe
    assert "$(MAKE) memo-stack-down" in recipe
    assert "$(MAKE) memo-stack-plugin-test" in recipe
    assert "$(MAKE) memo-stack-test-quality" in recipe
    assert "$(MAKE) memo-stack-agent-install-doctor" in recipe
    assert "$(MAKE) memo-stack-agent-live-smoke" in recipe
    assert "$(MAKE) memo-stack-agent-live-smoke-agents" in recipe
    assert "MEMORY_PROD_CONFIDENCE_POSTGRES_PORT" in recipe
    assert "MEMORY_PROD_CONFIDENCE_SERVER_PORT" in recipe
    assert "$(MAKE) memo-stack-agent-auth-doctor" in recipe
    assert "git diff --check" in recipe
    assert "$(MAKE) memo-stack-secret-scan" in recipe
    assert "memo-stack-full-provider-canary" not in recipe
    assert "memo-stack-agent-live-smoke-agents-strict" not in recipe


def test_makefile_secret_scan_covers_provider_api_keys() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-secret-scan"))

    assert "rg -n -P" in recipe
    assert r"sk-[A-Za-z0-9_-]{40,}" in recipe
    assert r"gh[pousr]_[A-Za-z0-9_]{12,}" in recipe
    assert r"AKIA[0-9A-Z]{12,}" in recipe
    assert "-----BEGIN [A-Z ]*PRIVATE KEY-----" in recipe
    assert "(?!ant-)" not in recipe
    assert "(proj-)?" not in recipe
    assert "-g '!frontend/test/**'" in recipe


def test_makefile_has_strict_full_prod_confidence_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-prod-confidence-strict"))
    preflight_recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-prod-confidence-strict-preflight")
    )

    assert ".PHONY: memo-stack-prod-confidence-strict" in makefile
    assert ".PHONY: memo-stack-prod-confidence-full" in makefile
    assert ".PHONY: memo-stack-prod-confidence-strict-preflight" in makefile
    assert "memo-stack-prod-confidence-full: memo-stack-prod-confidence-strict" in makefile
    assert "trap cleanup EXIT INT TERM" in recipe
    assert "$(MAKE) memo-stack-prod-confidence-strict-preflight" in recipe
    assert "$(MAKE) memo-stack-down" in recipe
    assert "$(MAKE) memo-stack-plugin-test" in recipe
    assert "$(MAKE) memo-stack-test-quality" in recipe
    assert "$(MAKE) memo-stack-agent-install-doctor" in recipe
    assert "$(MAKE) memo-stack-top-evidence-bundle" in recipe
    assert "$(MAKE) memo-stack-full-provider-public-benchmark-suite" not in recipe
    assert "$(MAKE) memo-stack-agent-live-smoke" in recipe
    assert "$(MAKE) memo-stack-agent-live-smoke-agents-strict" in recipe
    assert "MEMORY_PROD_CONFIDENCE_POSTGRES_PORT" in recipe
    assert "MEMORY_PROD_CONFIDENCE_SERVER_PORT" in recipe
    assert "git diff --check" in recipe
    assert "$(MAKE) memo-stack-secret-scan" in recipe
    assert "$(MAKE) memo-stack-top-evidence-preflight" in preflight_recipe
    assert "$(MAKE) memo-stack-agent-auth-doctor-strict" in preflight_recipe
    assert "$(MAKE) memo-stack-agent-live-smoke-agents;" not in recipe
    assert "$(MAKE) memo-stack-agent-auth-doctor;" not in recipe


def test_makefile_has_agent_install_and_full_canary_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    clean_full_smoke = (ROOT / "scripts" / "clean_full_smoke.py").read_text(
        encoding="utf-8"
    )

    assert ".PHONY: memo-stack-full-provider-canary" in makefile
    assert "memo-stack-full-provider-canary: memo-stack-clean-full-mcp-smoke" in makefile
    assert ".PHONY: memo-stack-full-provider-public-benchmark-canary" in makefile
    assert ".PHONY: memo-stack-full-provider-public-benchmark-suite" in makefile
    public_recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-full-provider-public-benchmark-canary")
    )
    public_suite_recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-full-provider-public-benchmark-suite")
    )
    assert "MEMORY_CLEAN_SMOKE_PUBLIC_BENCHMARK=true" in public_recipe
    assert (
        'MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-locomo}"'
        in public_recipe
    )
    assert (
        'MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-1}"'
        in public_recipe
    )
    assert "$(PYTHON) scripts/clean_full_smoke.py" in public_recipe
    assert "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET" in public_suite_recipe
    assert "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET" in public_suite_recipe
    assert 'MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-all}"' in (
        public_suite_recipe
    )
    assert (
        'MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-600}"'
        in public_suite_recipe
    )
    assert (
        'MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.902}"'
        in public_suite_recipe
    )
    assert "$(MAKE) memo-stack-full-provider-public-benchmark-canary" in public_suite_recipe
    assert "run_official_public_benchmark_canary" in clean_full_smoke
    assert 'locomo_dataset=_optional_path_env("MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")' in (
        clean_full_smoke
    )
    assert (
        'longmemeval_dataset=_optional_path_env("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")'
        in clean_full_smoke
    )
    assert "public_benchmark_ok" in clean_full_smoke
    assert ".PHONY: memo-stack-full-provider-canary-interactive" in makefile
    interactive_recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-full-provider-canary-interactive")
    )
    assert "stty -echo" in interactive_recipe
    assert "IFS= read -r OPENAI_KEY" in interactive_recipe
    assert "OpenAI key (input hidden)" in interactive_recipe
    assert "$(MAKE) memo-stack-full-provider-canary" in interactive_recipe
    assert "sk-" not in interactive_recipe
    assert ".PHONY: memo-stack-agent-install-dry-run" in makefile
    assert ".PHONY: memo-stack-agent-install" in makefile
    assert ".PHONY: memo-stack-agent-install-doctor" in makefile
    assert ".PHONY: memo-stack-agent-live-smoke" in makefile
    assert ".PHONY: memo-stack-agent-live-smoke-agents" in makefile
    assert ".PHONY: memo-stack-agent-live-smoke-agents-strict" in makefile
    assert ".PHONY: memo-stack-agent-auth-doctor" in makefile
    assert ".PHONY: memo-stack-agent-auth-doctor-strict" in makefile
    assert ".PHONY: memo-stack-agent-auth-repair" in makefile
    assert "MEMORY_AGENT_SMOKE_POSTGRES_PORT ?= 55429" in makefile
    assert "MEMORY_AGENT_SMOKE_SERVER_PORT ?= 17788" in makefile
    assert "MEMORY_PROD_CONFIDENCE_POSTGRES_PORT ?= 55431" in makefile
    assert "MEMORY_PROD_CONFIDENCE_SERVER_PORT ?= 17791" in makefile
    assert "MEMORY_AGENT_INSTALL_TARGETS ?= codex claude opencode cursor" in makefile
    assert "MEMORY_AGENT_GEMINI_HOOK_INSTALL_TARGETS ?= gemini" in makefile
    assert "cursor-workspace" not in re.search(
        r"MEMORY_AGENT_INSTALL_TARGETS \?= (?P<targets>.+)",
        makefile,
    ).group("targets")
    assert "$(PYTHON) scripts/agent_install_verification.py install-doctor" in makefile
    assert "$(PYTHON) scripts/install_memory_agent_plugin.py --dry-run" in makefile
    assert "$(PYTHON) scripts/install_memory_agent_plugin.py" in makefile
    assert (
        "$(PYTHON) scripts/agent_install_verification.py live-smoke\n"
    ) in makefile
    assert (
        "MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} "
        "MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} "
        "$(MAKE) memo-stack-up-lite"
    ) in makefile
    assert (
        "MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:"
        "$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}}"
    ) in makefile
    assert (
        "$(PYTHON) scripts/agent_install_verification.py live-smoke "
        "--run-agent-cli\n"
    ) in makefile
    assert (
        "$(PYTHON) scripts/agent_install_verification.py live-smoke "
        "--run-agent-cli --strict-agent-cli"
    ) in makefile
    assert "$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor\n" in makefile
    assert (
        "$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor --strict"
        in makefile
    )
    assert "Run this target from an interactive terminal" in makefile
    assert "claude auth login --claudeai" in makefile
    assert "opencode providers login --provider openai" in makefile
    assert "$(MAKE) memo-stack-agent-auth-doctor-strict" in makefile


def test_memory_agent_plugin_wrappers_support_runtime_env_overrides() -> None:
    wrappers = [
        ROOT / "plugins" / "memo-stack-agent-plugin" / "bin" / "memo-stack-mcp",
        ROOT / "plugins" / "memo-stack-agent-plugin-cursor-workspace" / "bin" / "memo-stack-mcp",
    ]

    for wrapper_path in wrappers:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        assert "MEMORY_MCP_RUNTIME_API_URL" in wrapper
        assert 'export MEMORY_MCP_API_URL="${MEMORY_MCP_RUNTIME_API_URL}"' in wrapper
        assert "MEMORY_MCP_RUNTIME_AUTH_TOKEN" in wrapper
        assert 'export MEMORY_MCP_AUTH_TOKEN="${MEMORY_MCP_RUNTIME_AUTH_TOKEN}"' in wrapper
        assert "MEMORY_MCP_RUNTIME_DEFAULT_THREAD_EXTERNAL_REF" in wrapper
        assert wrapper.index("MEMORY_MCP_RUNTIME_DEFAULT_THREAD_EXTERNAL_REF") < wrapper.index(
            "unset MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF"
        )


def test_makefile_has_paid_agent_behavior_benchmark_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-agent-behavior-bench" in makefile
    assert ".PHONY: memo-stack-agent-realistic-bench" in makefile
    assert ".PHONY: memo-stack-agent-live-session-bench" in makefile
    assert ".PHONY: memo-stack-agent-transcript-corpus-bench" in makefile
    assert ".PHONY: memo-stack-agent-transcript-corpus-redact" in makefile
    assert ".PHONY: memo-stack-agent-transcript-corpus-audit" in makefile
    assert ".PHONY: memo-stack-real-memory-confidence" in makefile
    assert "MEMORY_AGENT_BENCH_MODEL" in makefile
    assert "MEMORY_CLEAN_SMOKE_AGENT_BENCH=true" in makefile
    assert "MEMORY_AGENT_BENCH_SCENARIO_SET=realistic" in makefile
    assert "MEMORY_AGENT_BENCH_SCENARIO_SET=live" in makefile
    assert "MEMORY_AGENT_BENCH_SCENARIO_SET=transcript" in makefile
    assert "MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS" in makefile
    assert "MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS" in makefile
    assert "MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR" in makefile
    assert "MEMORY_AGENT_TRANSCRIPT_INPUT" in makefile
    assert "MEMORY_AGENT_TRANSCRIPT_OUTPUT" in makefile
    assert "MEMORY_AGENT_TRANSCRIPT_CORPUS_AUDIT_STRICT" in makefile
    assert "$(MAKE) memo-stack-top-evidence-bundle" in makefile
    assert "$(MAKE) memo-stack-prod-load-canary" in makefile
    assert "$(MAKE) memo-stack-agent-live-session-bench" in makefile
    assert "$(MAKE) memo-stack-agent-transcript-corpus-bench" in makefile
    assert "memo-stack-agent-behavior-bench" not in re.search(
        r"memo-stack-test-quality: (?P<deps>.+)",
        makefile,
    ).group("deps")
    assert "memo-stack-agent-realistic-bench" not in re.search(
        r"memo-stack-test-quality: (?P<deps>.+)",
        makefile,
    ).group("deps")
    assert "memo-stack-agent-live-session-bench" not in re.search(
        r"memo-stack-test-quality: (?P<deps>.+)",
        makefile,
    ).group("deps")
    assert "memo-stack-agent-transcript-corpus-bench" not in re.search(
        r"memo-stack-test-quality: (?P<deps>.+)",
        makefile,
    ).group("deps")
    assert "memo-stack-real-memory-confidence" not in re.search(
        r"memo-stack-test-quality: (?P<deps>.+)",
        makefile,
    ).group("deps")


def test_makefile_has_auto_memory_eval_quality_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-auto-memory-eval" in makefile
    assert "$(PYTHON) -m memo_stack_server eval run --suite auto-memory-golden" in makefile
    assert re.search(
        r"memo-stack-eval:\n(?:\t.+\n)+?\t\$\(PYTHON\) "
        r"-m memo_stack_server eval run --suite auto-memory-golden",
        makefile,
    )
    assert (
        "memo-stack-auto-memory-quality: "
        "memo-stack-capture-test memo-stack-hook-capture-smoke memo-stack-auto-memory-eval"
    ) in makefile


def test_makefile_has_public_memory_benchmark_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-public-benchmark" in makefile
    assert "MEMORY_PUBLIC_BENCHMARK_DATASET" in makefile
    assert "$(PYTHON) -m memo_stack_server eval public-benchmark" in makefile
    assert "MEMORY_PUBLIC_BENCHMARK_REPORT_OUT" in makefile
    assert "MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY" in makefile
    assert "MEMORY_PUBLIC_BENCHMARK_MAX_CASES" in makefile


def test_makefile_persists_and_reuses_memora_direct_smoke_report() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    smoke_recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-memora-direct-smoke"))
    compare_recipe = "\n".join(_make_target_recipe(makefile, "memo-stack-compare-memora"))

    assert "MEMORA_DIRECT_SMOKE_REPORT ?= .tmp/memora-direct-smoke.json" in makefile
    assert ".tmp/" in gitignore
    assert '--report-out "$(MEMORA_DIRECT_SMOKE_REPORT)"' in smoke_recipe
    assert "with_report_provenance(" in (
        ROOT / "scripts" / "memora_direct_mcp_smoke.py"
    ).read_text(encoding="utf-8")
    assert 'smoke_report="$${MEMORA_DIRECT_SMOKE_REPORT:-$(MEMORA_DIRECT_SMOKE_REPORT)}"' in (
        compare_recipe
    )
    assert '[ -f "$$smoke_report" ]' in compare_recipe
    assert "--memora-smoke-report" in compare_recipe


def test_makefile_has_official_public_benchmark_canary() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = "\n".join(
        _make_target_recipe(makefile, "memo-stack-official-public-benchmark-canary")
    )
    module = (
        ROOT
        / "packages"
        / "memo_stack_server"
        / "memo_stack_server"
        / "official_public_benchmark.py"
    ).read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "official_public_benchmark_canary.py").read_text(
        encoding="utf-8"
    )

    assert ".PHONY: memo-stack-official-public-benchmark-canary" in makefile
    assert "$(PYTHON) scripts/official_public_benchmark_canary.py" in recipe
    assert "MEMORY_PUBLIC_BENCHMARK_REPORT_OUT" in recipe
    assert "MEMORY_PUBLIC_BENCHMARK_MAX_CASES" in recipe
    assert "MEMORY_PUBLIC_BENCHMARK_API_URL" in recipe
    assert "MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN" in recipe
    assert "memo_stack_server.official_public_benchmark import main" in script
    assert "snap-research/locomo" in module
    assert "longmemeval_s_cleaned.json" in module


def test_paid_make_targets_do_not_put_openai_keys_in_python_command_line() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    for target in (
        "memo-stack-clean-full-smoke",
        "memo-stack-clean-full-mcp-smoke",
        "memo-stack-full-provider-public-benchmark-canary",
        "memo-stack-top-evidence-bundle",
        "memo-stack-agent-behavior-bench",
        "memo-stack-agent-realistic-bench",
        "memo-stack-agent-live-session-bench",
        "memo-stack-agent-transcript-corpus-bench",
    ):
        recipe = _make_target_recipe(makefile, target)
        python_lines = [line for line in recipe if "$(PYTHON) scripts/clean_full_smoke.py" in line]

        assert python_lines, target
        assert "export " in "\n".join(recipe)
        assert all("OPENAI_API_KEY=" not in line for line in python_lines)
        assert all("MEMORY_OPENAI_API_KEY=" not in line for line in python_lines)
        assert all("MEMORY_AGENT_BENCH_OPENAI_API_KEY=" not in line for line in python_lines)


def test_agent_behavior_docs_do_not_contain_raw_token_examples() -> None:
    docs = "\n".join(
        [
            (ROOT / "docs" / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "mcp-adapter.md").read_text(encoding="utf-8"),
        ]
    )

    assert "sk-" not in docs
    assert "Bearer " not in docs
    assert "MEMORY_MCP_AUTH_TOKEN=<" not in docs
    assert 'MEMORY_AGENT_BENCH_MODEL="$MODEL"' in docs


def test_mcp_docs_do_not_make_status_first_default() -> None:
    docs = (ROOT / "docs" / "mcp-adapter.md").read_text(encoding="utf-8").casefold()

    assert "call `memory_status` first" not in docs
    assert "call memory_status first" not in docs
    assert "call `memory_status`." not in docs
    assert "call `memory_search` before relying on memory" in docs
    assert "call `memory_status` only" in docs


def test_clean_full_smoke_uses_env_secrets_and_redacts_output(monkeypatch) -> None:
    script_path = ROOT / "scripts" / "clean_full_smoke.py"
    source = script_path.read_text(encoding="utf-8")
    assert "argparse" not in source
    assert "--auth-token" not in source
    assert "MEMORY_MCP_AUTH_TOKEN" in source
    assert "MEMORY_CLEAN_SMOKE_SKIP_MCP" in source

    module = _load_clean_full_smoke(script_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-unit-openai-secret")
    monkeypatch.setenv("MEMORY_MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "unit-service-token")
    payload = {
        "stdout": (
            "sk-unit-openai-secret unit-mcp-token unit-service-token "
            "sk-svcacct-abcdefghijklmnopqrstuvwxyz1234567890 "
            "token=[redacted-secret]"
        ),
        "nested": ["unit-mcp-token"],
        "OPENAI_API_KEY": "Authorization: Bearer sk-proj-unit-secret-value",
        "Authorization": "Bearer plain-header-secret-value",
        "Idempotency-Key": "idempotency-secret-value",
        "CUSTOM_TOKEN": "custom-token-secret-value",
        "token": "short",
        "password": "tiny",
        "api_key": "plain",
        "generic": "token=generic-secret-value-12345",
    }

    rendered = json.dumps(module._redact_payload(payload), ensure_ascii=False)

    assert "sk-unit-openai-secret" not in rendered
    assert "sk-svcacct" not in rendered
    assert "unit-mcp-token" not in rendered
    assert "unit-service-token" not in rendered
    assert "token=[redacted-secret]" in rendered
    assert "OPENAI_API_KEY" not in rendered
    assert "sk-proj-unit-secret-value" not in rendered
    assert "Authorization" not in rendered
    assert "Idempotency-Key" not in rendered
    assert "CUSTOM_TOKEN" not in rendered
    assert "plain-header-secret-value" not in rendered
    assert "idempotency-secret-value" not in rendered
    assert "custom-token-secret-value" not in rendered
    assert '"token"' not in rendered
    assert '"password"' not in rendered
    assert '"api_key"' not in rendered
    assert '"short"' not in rendered
    assert '"tiny"' not in rendered
    assert '"plain"' not in rendered
    assert "generic-secret-value-12345" not in rendered
    assert "<redacted>" in rendered


def test_clean_full_smoke_uses_current_postgres_database_name(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-unit-openai-secret")

    env = module._server_env(
        ports={"postgres": 15432, "qdrant": 16333, "neo4j_bolt": 17687, "server": 17788},
        token="unit-service-token",
        run_id="unit-run",
    )

    assert env["MEMORY_DATABASE_URL"].endswith(":15432/memo_stack")
    assert not env["MEMORY_DATABASE_URL"].endswith(":15432/memory")


def test_clean_full_smoke_report_provenance_is_safe_and_auditable() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    provenance = module._report_provenance(
        run_id="unit-run",
        project_name="unit-project",
    )
    redacted = module._redact_payload(provenance)

    assert provenance["schema_version"] == 1
    assert provenance["generated_by"] == "scripts/clean_full_smoke.py"
    assert provenance["suite"] == "memo-stack-full-provider-canary"
    assert provenance["run_id"] == "unit-run"
    assert provenance["project"] == "unit-project"
    assert set(provenance["git"]) == {"commit", "short_commit", "dirty"}
    assert "python_version" in provenance["runtime"]
    assert "platform" in provenance["runtime"]
    assert redacted == provenance


def test_clean_full_smoke_keeps_safe_check_names_with_token_word() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    rendered = json.dumps(
        module._redact_payload(
            {
                "checks": {
                    "mcp_text_fallback_does_not_leak_token": True,
                    "CUSTOM_TOKEN": "custom-token-secret-value",
                }
            }
        ),
        ensure_ascii=False,
    )

    assert "mcp_text_fallback_does_not_leak_token" in rendered
    assert "CUSTOM_TOKEN" not in rendered
    assert "custom-token-secret-value" not in rendered


def test_clean_full_smoke_redacts_camelcase_secret_keys_without_hiding_metrics() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    redacted = module._redact_payload(
        {
            "apiKey": "plain-api-key-value",
            "authToken": "plain-auth-token-value",
            "privateKey": "plain-private-key-value",
            "token_budget": 1200,
            "secret_leak_count": 0,
            "secret_leak_count_zero": True,
        }
    )

    assert redacted["<redacted-key>"] == "<redacted>"
    assert redacted["<redacted-key>-2"] == "<redacted>"
    assert redacted["<redacted-key>-3"] == "<redacted>"
    assert redacted["token_budget"] == 1200
    assert redacted["secret_leak_count"] == 0
    assert redacted["secret_leak_count_zero"] is True


def test_clean_full_smoke_keeps_secret_redaction_metric_failure_key() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    redacted = module._redact_payload(
        {
            "metric_failures": {
                "secret_redaction": [
                    {
                        "scenario_id": "secret_probe",
                        "locations": [{"location": "tool_raw_output"}],
                    }
                ],
                "authToken": "plain-auth-token-value",
            }
        }
    )

    assert redacted == {
        "metric_failures": {
            "secret_redaction": [
                {
                    "scenario_id": "secret_probe",
                    "locations": [{"location": "tool_raw_output"}],
                }
            ],
            "<redacted-key>": "<redacted>",
        }
    }


def test_clean_full_smoke_redacts_explicit_canary_env_without_process_env() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    rendered = json.dumps(
        module._redact_payload(
            {
                "message": (
                    "token=explicit-service-token "
                    "postgresql+asyncpg://memory:secret-db-pass@127.0.0.1/memory "
                    "neo4j password memostackgraph"
                )
            },
            env={
                "MEMORY_SERVICE_TOKEN": "explicit-service-token",
                "MEMORY_DATABASE_URL": (
                    "postgresql+asyncpg://memory:secret-db-pass@127.0.0.1/memory"
                ),
                "MEMORY_GRAPHITI_NEO4J_PASSWORD": "memostackgraph",
            },
        ),
        ensure_ascii=False,
    )

    assert "explicit-service-token" not in rendered
    assert "secret-db-pass" not in rendered
    assert "memostackgraph" not in rendered
    assert "<redacted>" in rendered


def test_clean_full_smoke_http_readiness_error_is_redacted(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    token = "unit-service-token-abcdefghijklmnopqrstuvwxyz"

    class Response:
        status_code = 503
        text = f'{{"message":"Bearer {token}"}}'

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, url, *, headers):
            return Response()

    ticks = iter([0.0, 0.0, 121.0])
    monkeypatch.setattr(module.httpx, "Client", Client)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    try:
        module._wait_for_http(
            "http://127.0.0.1:7788/v1/health",
            token=token,
            env={"MEMORY_SERVICE_TOKEN": token},
        )
    except module.CleanSmokeFailure as exc:
        message = str(exc)
        assert token not in message
        assert "<redacted>" in message
    else:
        raise AssertionError("Expected CleanSmokeFailure")


def test_clean_full_smoke_neo4j_readiness_error_is_redacted(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    class Driver:
        def verify_connectivity(self):
            raise RuntimeError("auth failed for password memostackgraph")

        def close(self):
            return None

    ticks = iter([0.0, 0.0, 121.0])
    monkeypatch.setattr(module.GraphDatabase, "driver", lambda *_args, **_kwargs: Driver())
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    try:
        module._wait_for_neo4j(
            17687,
            env={"MEMORY_GRAPHITI_NEO4J_PASSWORD": "memostackgraph"},
        )
    except module.CleanSmokeFailure as exc:
        message = str(exc)
        assert "memostackgraph" not in message
        assert "<redacted>" in message
    else:
        raise AssertionError("Expected CleanSmokeFailure")


def test_clean_full_smoke_mcp_text_secret_check_catches_generic_tokens() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    class Content:
        text = "Authorization: Bearer sk-proj-generic-fallback-token-value"

    class Result:
        content = [Content()]

    assert not module._mcp_text_has_no_secrets(Result(), env={})


def test_clean_full_smoke_redacts_private_key_blocks() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    rendered = module._redact_text(
        "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----",
        env={},
    )

    assert "PRIVATE KEY" not in rendered
    assert rendered == "<redacted>"


def test_clean_full_smoke_redacts_agent_benchmark_secret_markers() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    result = {
        "ok": False,
        "suite": "memory_mcp_agent_behavior",
        "metric_failures": {
            "leak_checks": [
                {
                    "scenario_id": "secret_case",
                    "leak_metric": "secret_leak_count",
                    "failures": ["found password=bench-secret-project-alpha"],
                }
            ]
        },
        "scenarios": [
            {
                "id": "secret_case",
                "category": "safety",
                "critical": True,
                "status": "failed",
                "tool_calls": [
                    {
                        "name": "memory_search",
                        "is_error": False,
                        "side_effects": [],
                        "arguments": {"query": "password=bench-secret-project-alpha"},
                        "output_preview": "Bearer canary-token-value",
                    }
                ],
                "failures": [],
                "memory_checks": [
                    {
                        "type": "final_answer_no_secret",
                        "passed": False,
                        "failures": ["found forbidden text: bench-secret-project-alpha"],
                    }
                ],
            }
        ],
    }

    summary = module._agent_behavior_failure_summary(result)
    rendered = module._redact_text(json.dumps(summary, ensure_ascii=False), env={})

    assert "bench-secret-project-alpha" not in rendered
    assert "canary-token-value" not in rendered
    assert summary["metric_failures"]["leak_checks"][0]["scenario_id"] == "secret_case"
    assert summary["failed_scenarios"][0]["tool_calls"][0]["name"] == "memory_search"
    assert "<redacted>" in rendered


def test_clean_full_smoke_keeps_mcp_import_lazy_for_api_only_mode() -> None:
    source = (ROOT / "scripts" / "clean_full_smoke.py").read_text(encoding="utf-8")
    before_mcp_lifecycle = source.split("async def _run_mcp_lifecycle", maxsplit=1)[0]

    assert "from mcp import" not in before_mcp_lifecycle
    assert "from mcp.client.stdio import" not in before_mcp_lifecycle


def test_clean_full_smoke_server_logs_do_not_use_unread_pipe() -> None:
    source = (ROOT / "scripts" / "clean_full_smoke.py").read_text(encoding="utf-8")

    assert "stdout=subprocess.PIPE" not in source
    assert "tempfile.TemporaryFile" in source
    assert "server_output_tail" in source


def test_clean_full_smoke_queries_graphiti_with_semantic_fact_text() -> None:
    source = (ROOT / "scripts" / "clean_full_smoke.py").read_text(encoding="utf-8")

    assert (
        'initial_graph_query = "Graphiti connects canonical facts to clean architecture memory"'
        in source
    )
    assert 'updated_graph_query = "Graphiti Qdrant recall updated memory"' in source
    assert (
        "initial_context = _context(base_url, headers, space_slug, memory_scope_ref, marker)"
        not in source
    )
    assert (
        "updated_context = _context(base_url, headers, space_slug, memory_scope_ref, marker)"
        not in source
    )


def test_clean_full_smoke_accepts_real_context_chunk_shape() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    assert module._search_has_chunk_item(
        {"data": {"items": [{"item_id": "mem_123", "item_type": "chunk", "source_refs": []}]}}
    )
    assert module._search_has_chunk_item(
        {
            "data": {
                "items": [
                    {
                        "item_id": "mem_123",
                        "item_type": "fact",
                        "source_refs": [{"chunk_id": "chunk-canonical-id"}],
                    }
                ]
            }
        }
    )
    assert not module._search_has_chunk_item(
        {"data": {"items": [{"item_id": "fact_123", "item_type": "fact", "source_refs": []}]}}
    )
    assert (
        module._search_diagnostic_status(
            {
                "data": {
                    "diagnostics": {
                        "vector_status": "ok",
                        "graph_status": "skipped",
                        "vector_hydrated_count": 1,
                    }
                }
            },
            "vector_status",
        )
        == "ok"
    )
    assert (
        module._search_diagnostic_int(
            {"data": {"diagnostics": {"vector_hydrated_count": 1}}},
            "vector_hydrated_count",
        )
        == 1
    )
    assert (
        module._context_diagnostic_int(
            {"diagnostics": {"graph_hydrated_count": 2}},
            "graph_hydrated_count",
        )
        == 2
    )


def test_clean_full_smoke_failure_diagnostics_are_safe_allowlists() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    search = {
        "data": {
            "diagnostics": {
                "graph_status": "ok",
                "graph_hydrated_count": 1,
                "token": "secret-token",
            }
        }
    }
    status = {
        "data": {
            "readiness": {
                "read_ready": True,
                "degraded_reasons": ["cognee.disabled"],
                "secret": "secret-token",
            },
            "capabilities": {
                "adapters": {
                    "qdrant": {
                        "enabled": True,
                        "healthy": True,
                        "status": "ok",
                        "token": "secret-token",
                    }
                }
            },
        }
    }

    assert module._safe_search_diagnostics(search) == {
        "graph_hydrated_count": 1,
        "graph_status": "ok",
    }
    assert module._safe_status_readiness(status) == {
        "read_ready": True,
        "degraded_reasons": ["cognee.disabled"],
    }
    assert module._safe_status_adapters(status) == {
        "qdrant": {"enabled": True, "healthy": True, "status": "ok"}
    }


def test_clean_full_smoke_summarizes_mcp_exception_groups_safely() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    env = {"MEMORY_MCP_AUTH_TOKEN": "unit-token-value-12345678"}
    group = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [
            RuntimeError("Bearer unit-token-value-12345678"),
            RuntimeError("Failed to read from defunct connection"),
        ],
    )

    summary = module._exception_summary(group, env=env)

    assert module._mcp_session_retryable(group) is True
    assert "ExceptionGroup(2)" in summary
    assert "defunct connection" in summary
    assert "unit-token-value-12345678" not in summary
    assert "<redacted>" in summary


def test_clean_full_smoke_mcp_env_does_not_inherit_provider_secrets(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-unit-openai-secret")
    monkeypatch.setenv("MEMORY_OPENAI_API_KEY", "sk-unit-memory-openai-secret")
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "unit-service-token")
    monkeypatch.setenv("MEMORY_GRAPHITI_NEO4J_PASSWORD", "unit-neo4j-password")
    monkeypatch.setenv("PYTHONPATH", "existing-pythonpath")

    env = module._mcp_process_env(
        base_url="http://127.0.0.1:7788",
        token="unit-mcp-token",
        space_slug="unit-space",
        memory_scope_ref="unit-memory_scope",
    )

    assert env["MEMORY_MCP_API_URL"] == "http://127.0.0.1:7788"
    assert env["MEMORY_MCP_AUTH_TOKEN"] == "unit-mcp-token"
    assert env["MEMORY_MCP_REQUEST_TIMEOUT_SECONDS"] == "90"
    assert "packages/memo_stack_mcp" in env["PYTHONPATH"]
    assert "existing-pythonpath" in env["PYTHONPATH"]
    assert "OPENAI_API_KEY" not in env
    assert "MEMORY_OPENAI_API_KEY" not in env
    assert "MEMORY_SERVICE_TOKEN" not in env
    assert "MEMORY_GRAPHITI_NEO4J_PASSWORD" not in env


def test_clean_full_smoke_required_mcp_adapters_ignore_optional_disabled() -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    status = {
        "data": {
            "capabilities": {
                "adapters": {
                    "qdrant": {"enabled": True, "healthy": True},
                    "graphiti": {"enabled": True, "healthy": True},
                    "embeddings": {"enabled": True, "healthy": True},
                    "cognee": {"enabled": False, "healthy": False},
                }
            }
        }
    }

    assert module._required_mcp_adapters_ready(
        status,
        ("qdrant", "graphiti", "embeddings"),
    )
    assert module._required_mcp_adapters_ready(
        {
            "data": {
                "capabilities": {
                    "capabilities": [
                        {
                            "adapter_name": "qdrant",
                            "enabled": True,
                            "healthy": True,
                            "status": "ok",
                        },
                        {
                            "adapter_name": "graphiti",
                            "enabled": True,
                            "healthy": True,
                            "status": "ok",
                        },
                        {
                            "adapter_name": "embeddings",
                            "enabled": True,
                            "healthy": True,
                            "status": "ok",
                        },
                        {
                            "adapter_name": "cognee",
                            "enabled": False,
                            "healthy": False,
                            "status": "disabled",
                        },
                    ]
                }
            }
        },
        ("qdrant", "graphiti", "embeddings"),
    )
    assert not module._required_mcp_adapters_ready(
        status,
        ("qdrant", "graphiti", "embeddings", "cognee"),
    )


def test_clean_full_smoke_missing_key_message_does_not_name_sensitive_envs(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_OPENAI_API_KEY", raising=False)

    try:
        module._server_env(
            ports={"postgres": 1, "qdrant": 2, "neo4j_bolt": 3, "server": 4},
            token="t",
            run_id="r",
        )
    except module.CleanSmokeFailure as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing key failure")

    assert "OPENAI_API_KEY" not in message
    assert "MEMORY_OPENAI_API_KEY" not in message
    assert "OpenAI API key" in message
    assert "MEMORY_OPENAI_API_KEY" not in message


def test_clean_full_smoke_openai_preflight_reports_safe_invalid_key(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")

    class FakeOpenAIAuthError(RuntimeError):
        status_code = 401
        code = "invalid_api_key"

    class FakeEmbeddings:
        async def create(self, **_kwargs: object) -> object:
            raise FakeOpenAIAuthError("raw provider error must stay hidden")

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.embeddings = FakeEmbeddings()
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    env = {
        "MEMORY_OPENAI_API_KEY": "sk-test-secret",
        "MEMORY_EMBEDDINGS_MODEL": "text-embedding-3-small",
        "MEMORY_EMBEDDINGS_DIMENSIONS": "1536",
    }

    try:
        asyncio.run(module._run_openai_provider_preflight(env))
    except module.CleanSmokeFailure as exc:
        message = str(exc)
    else:
        raise AssertionError("expected OpenAI preflight to fail")

    assert message == "OpenAI provider preflight failed: openai.invalid_api_key"
    assert "sk-test-secret" not in message
    assert "raw provider error" not in message


def test_clean_full_smoke_prod_load_settings_are_bounded(monkeypatch) -> None:
    module = _load_clean_full_smoke(ROOT / "scripts" / "clean_full_smoke.py")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_MEMORY_SCOPES", "4")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_FACTS_PER_MEMORY_SCOPE", "9")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_DOCUMENTS", "2")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_LARGE_DOC_SECTIONS", "11")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_CONCURRENCY", "5")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_CHAOS_REQUESTS", "7")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_CONTEXT_REQUESTS", "8")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_WORKER_ROUNDS", "12")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_MAX_P95_MS", "12345")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_RESTART_SERVER", "false")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_RESTART_PROVIDERS", "false")
    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_PROVIDER_OUTAGE", "false")

    assert module._prod_load_settings() == {
        "memory_scopes": 4,
        "facts_per_memory_scope": 9,
        "documents": 2,
        "large_doc_sections": 11,
        "concurrency": 5,
        "chaos_requests": 7,
        "context_requests": 8,
        "worker_rounds": 12,
        "max_p95_ms": 12345.0,
        "restart_server": False,
        "restart_providers": False,
        "provider_outage": False,
    }

    monkeypatch.setenv("MEMORY_CLEAN_SMOKE_LOAD_FACTS_PER_MEMORY_SCOPE", "1000")
    try:
        module._prod_load_settings()
    except module.CleanSmokeFailure as exc:
        assert "MEMORY_CLEAN_SMOKE_LOAD_FACTS_PER_MEMORY_SCOPE" in str(exc)
    else:
        raise AssertionError("expected bounded prod load setting failure")


def test_real_stack_mcp_canary_docs_are_env_based() -> None:
    docs = "\n".join(
        [
            (ROOT / "docs" / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "mcp-adapter.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "mcp-memory-foundation-plan.md").read_text(encoding="utf-8"),
        ]
    )

    assert "memo-stack-clean-full-mcp-smoke" in docs
    assert "memo-stack-prod-load-canary" in docs
    assert "memo-stack-agent-live-session-bench" in docs
    assert "memo-stack-agent-transcript-corpus-bench" in docs
    assert "memo-stack-agent-transcript-corpus-redact" in docs
    assert "memo-stack-agent-transcript-corpus-audit" in docs
    assert "memo-stack-multimodal-live-provider-canary" in docs
    assert "MEMORY_MULTIMODAL_PROVIDER_AUDIO_FIXTURE" in docs
    assert "MEMORY_MULTIMODAL_PROVIDER_CANARY_REPORT_OUT" in docs
    assert "MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR" in docs
    assert "MEMORY_AGENT_TRANSCRIPT_INPUT" in docs
    assert "memo-stack-real-memory-confidence" in docs
    assert "MEMORY_CLEAN_SMOKE_SKIP_MCP=true" in docs
    assert "--auth-token" not in docs
    assert "local-token" not in docs
    assert "local-dev-token" not in docs
    assert re.search(r"\bsk-[A-Za-z0-9]", docs) is None
    assert re.search(r"=<[A-Za-z0-9_-]+>", docs) is None
    assert (
        re.search(
            r'"[A-Z0-9_]*(TOKEN|KEY|SECRET|PASSWORD|DATABASE_URL|DB_URL|DSN)[A-Z0-9_]*"'
            r'\s*:\s*"<[^"]+>"',
            docs,
        )
        is None
    )


def _load_clean_full_smoke(path: Path):
    spec = importlib.util.spec_from_file_location("clean_full_smoke_for_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_frontend_marionette_local_e2e(path: Path):
    spec = importlib.util.spec_from_file_location(
        "frontend_marionette_local_e2e_for_test",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_target_recipe(makefile: str, target: str) -> list[str]:
    lines = makefile.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line == f"{target}:" or line.startswith(f"{target}: ")
    )
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        if line.startswith("\t"):
            recipe.append(line.strip())
    return recipe
