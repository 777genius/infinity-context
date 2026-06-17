PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
COMPOSE ?= docker compose
SELFHOST_ENV ?= .env.selfhost
SELFHOST_COMPOSE ?= $(COMPOSE) --env-file $(SELFHOST_ENV) -f docker-compose.selfhost.yml
MEMO_STACK_PYTHONPATH ?= packages/memo_stack_core:packages/memo_stack_server:packages/memo_stack_adapters:packages/memo_stack_sdk:packages/memo_stack_obsidian:packages/memo_stack_mcp:packages/memo_stack_cli
export PYTHONPATH := $(MEMO_STACK_PYTHONPATH)$(if $(PYTHONPATH),:$(PYTHONPATH))
FRONTEND_DIR ?= frontend
FLUTTER ?= $(shell command -v flutter 2>/dev/null || if [ -x "$$HOME/dev/flutter/bin/flutter" ]; then echo "$$HOME/dev/flutter/bin/flutter"; elif [ -x "$$HOME/dev/projects/flutter/bin/flutter" ]; then echo "$$HOME/dev/projects/flutter/bin/flutter"; else echo flutter; fi)
MEMORY_SERVER_ENV ?= MEMORY_AUTO_CREATE_SCHEMA=true MEMORY_SERVICE_TOKEN=local-dev-token
PLUGIN_KIT_AI ?= scripts/plugin-kit-ai-local
MEMORY_AGENT_PLUGIN_ROOT ?= plugins/memo-stack-agent-plugin
MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT ?= plugins/memo-stack-agent-plugin-cursor-workspace
MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT ?= plugins/memo-stack-agent-plugin-gemini-hooks
MEMORY_AGENT_PLUGIN_ROOTS ?= $(MEMORY_AGENT_PLUGIN_ROOT) $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT) $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT)
MEMORY_AGENT_PLUGIN_VALIDATE_TARGETS ?= codex-package claude gemini opencode cursor
MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_VALIDATE_TARGETS ?= cursor-workspace
MEMORY_AGENT_GEMINI_HOOK_PLUGIN_VALIDATE_TARGETS ?= gemini
MEMORY_AGENT_INSTALL_TARGETS ?= codex claude opencode cursor
MEMORY_AGENT_GEMINI_HOOK_INSTALL_TARGETS ?= gemini
MEMORY_AGENT_SMOKE_POSTGRES_PORT ?= 55429
MEMORY_AGENT_SMOKE_SERVER_PORT ?= 17788
MEMORY_PROD_CONFIDENCE_POSTGRES_PORT ?= 55431
MEMORY_PROD_CONFIDENCE_SERVER_PORT ?= 17791
MEMORA_DIRECT_SMOKE_REPORT ?= .tmp/memora-direct-smoke.json
OBSIDIAN_PLUGIN_DIR ?= packages/memo_stack_obsidian_plugin

.PHONY: memo-stack-format
memo-stack-format:
	$(RUFF) format .

.PHONY: memo-stack-lint
memo-stack-lint:
	$(RUFF) check .

.PHONY: memo-stack-test-unit
memo-stack-test-unit:
	$(PYTHON) -m pytest tests/unit

.PHONY: memo-stack-test-all
memo-stack-test-all:
	$(PYTHON) -m pytest

.PHONY: memo-stack-test-application
memo-stack-test-application:
	$(PYTHON) -m pytest tests/unit/test_domain_fact.py tests/unit/test_facts_api.py tests/unit/test_legacy_and_context_api.py tests/unit/test_suggestions_api.py

.PHONY: memo-stack-test-integration
memo-stack-test-integration:
	$(PYTHON) -m pytest tests/unit/test_provider_adapters.py tests/unit/test_worker_eval.py

.PHONY: memo-stack-test-e2e
memo-stack-test-e2e:
	$(PYTHON) -m pytest tests/e2e

.PHONY: memo-stack-frontend-pub-get
memo-stack-frontend-pub-get:
	cd $(FRONTEND_DIR) && $(FLUTTER) pub get

.PHONY: memo-stack-frontend-analyze
memo-stack-frontend-analyze:
	cd $(FRONTEND_DIR) && $(FLUTTER) analyze

.PHONY: memo-stack-frontend-test
memo-stack-frontend-test:
	cd $(FRONTEND_DIR) && $(FLUTTER) test

.PHONY: memo-stack-frontend-build-macos
memo-stack-frontend-build-macos:
	cd $(FRONTEND_DIR) && $(FLUTTER) build macos --debug

.PHONY: memo-stack-frontend-check
memo-stack-frontend-check: memo-stack-frontend-analyze memo-stack-frontend-test

.PHONY: memo-stack-frontend-marionette-memory-e2e
memo-stack-frontend-marionette-memory-e2e: memo-stack-up-lite
	for i in $$(seq 1 90); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 90 ]; then $(COMPOSE) logs --tail=120 memo_stack_server; exit 1; fi; sleep 1; done
	cd $(FRONTEND_DIR) && dart_bin="$$(dirname "$(FLUTTER)")/dart"; if [ ! -x "$$dart_bin" ]; then dart_bin=dart; fi; FLUTTER_BIN="$(FLUTTER)" MEMO_STACK_BACKEND_HOST=127.0.0.1 MEMO_STACK_BACKEND_PORT=7788 MEMO_STACK_SERVICE_TOKEN=local-dev-token MEMO_STACK_SPACE_SLUG=marionette-anchor-e2e "$$dart_bin" run tool/marionette_anchor_lifecycle_e2e.dart

.PHONY: memo-stack-frontend-marionette-anchor-e2e
memo-stack-frontend-marionette-anchor-e2e: memo-stack-frontend-marionette-memory-e2e

.PHONY: memo-stack-desktop-confidence
memo-stack-desktop-confidence:
	@set -e; \
	cleanup() { $(MAKE) memo-stack-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) memo-stack-test-quality; \
	$(MAKE) memo-stack-frontend-check; \
	$(MAKE) memo-stack-frontend-marionette-memory-e2e; \
	git diff --check; \
	$(MAKE) memo-stack-secret-scan

.PHONY: memo-stack-scale-chaos-load-e2e
memo-stack-scale-chaos-load-e2e:
	$(PYTHON) -m pytest tests/e2e/test_memory_scale_chaos_load_e2e.py -q

.PHONY: memo-stack-obsidian-python-test
memo-stack-obsidian-python-test:
	$(PYTHON) -m pytest tests/unit/test_obsidian_note_format.py tests/unit/test_obsidian_sync.py tests/unit/test_obsidian_cli.py tests/unit/test_mcp_obsidian_prepare.py tests/unit/test_mcp_obsidian_tools.py tests/unit/test_mcp_adapter.py tests/e2e/test_obsidian_cli_e2e.py -q

.PHONY: memo-stack-obsidian-live-smoke
memo-stack-obsidian-live-smoke:
	$(PYTHON) scripts/obsidian_connector_live_smoke.py
	$(PYTHON) scripts/obsidian_mcp_smoke.py

.PHONY: memo-stack-obsidian-plugin-check
memo-stack-obsidian-plugin-check:
	cd $(OBSIDIAN_PLUGIN_DIR) && npm run typecheck
	cd $(OBSIDIAN_PLUGIN_DIR) && npm run build

.PHONY: memo-stack-obsidian-test
memo-stack-obsidian-test: memo-stack-obsidian-python-test memo-stack-obsidian-live-smoke memo-stack-obsidian-plugin-check

.PHONY: memo-stack-obsidian-ui-e2e
memo-stack-obsidian-ui-e2e:
	cd $(OBSIDIAN_PLUGIN_DIR) && MEMO_STACK_RUN_OBSIDIAN_E2E=1 npm run test:e2e:obsidian

.PHONY: memo-stack-eval
memo-stack-eval:
	$(PYTHON) -m memo_stack_server eval run --suite small-golden
	$(PYTHON) -m memo_stack_server eval run --suite quality-golden
	$(PYTHON) -m memo_stack_server eval run --suite semantic-linking-golden
	$(PYTHON) -m memo_stack_server eval run --suite long-memory-golden
	$(PYTHON) -m memo_stack_server eval run --suite auto-memory-golden
	$(PYTHON) -m memo_stack_server eval run --suite graph-native-golden
	$(PYTHON) -m memo_stack_server eval snapshots --suite prompt-contract

.PHONY: memo-stack-quality-scorecard
memo-stack-quality-scorecard:
	$(PYTHON) -m memo_stack_server eval scorecard

.PHONY: memo-stack-quality-scorecard-from-reports
memo-stack-quality-scorecard-from-reports:
	@test -n "$${MEMORY_SCORECARD_SUITE_REPORTS:-}" || (echo "Set MEMORY_SCORECARD_SUITE_REPORTS to one or more eval report paths."; exit 1)
	$(PYTHON) -m memo_stack_server eval scorecard $$(printf ' --suite-report %s' $${MEMORY_SCORECARD_SUITE_REPORTS})

.PHONY: memo-stack-quality-scorecard-top-evidence
memo-stack-quality-scorecard-top-evidence:
	@test -n "$${MEMORY_SCORECARD_SUITE_REPORTS:-}" || (echo "Set MEMORY_SCORECARD_SUITE_REPORTS to deterministic eval, full-provider canary, agent behavior and public benchmark report paths."; exit 1)
	$(PYTHON) -m memo_stack_server eval scorecard --require-top-evidence $$(printf ' --suite-report %s' $${MEMORY_SCORECARD_SUITE_REPORTS})

.PHONY: memo-stack-quality-evidence-bundle
memo-stack-quality-evidence-bundle:
	@set -e; \
	set -- --output-dir "$${MEMORY_QUALITY_EVIDENCE_DIR:-.tmp/memo-stack-quality-evidence}"; \
	if [ "$${MEMORY_QUALITY_EVIDENCE_REQUIRE_TOP:-false}" = "true" ]; then set -- "$$@" --require-top-evidence; fi; \
	for report in $${MEMORY_SCORECARD_EXTRA_REPORTS:-}; do set -- "$$@" --extra-report "$$report"; done; \
	$(PYTHON) scripts/quality_evidence_bundle.py "$$@"

.PHONY: memo-stack-top-evidence-preflight
memo-stack-top-evidence-preflight:
	@$(PYTHON) -m memo_stack_server.top_evidence_preflight --json

.PHONY: memo-stack-top-evidence-bundle
memo-stack-top-evidence-bundle:
	@set -e; \
	$(PYTHON) -m memo_stack_server.top_evidence_preflight --json; \
	evidence_dir="$${MEMORY_QUALITY_EVIDENCE_DIR:-.tmp/memo-stack-top-evidence}"; \
	external_report="$$evidence_dir/full-provider-agent-public.json"; \
	expected_git_commit="$$(git rev-parse HEAD)"; \
	allow_dirty_arg=""; \
	case "$${MEMORY_QUALITY_EVIDENCE_ALLOW_DIRTY_TOP:-}" in 1|true|yes|on) allow_dirty_arg="--allow-dirty-top-evidence";; esac; \
	mkdir -p "$$evidence_dir"; \
	export MEMORY_CLEAN_SMOKE_REPORT_OUT="$$external_report"; \
	export MEMORY_CLEAN_SMOKE_PUBLIC_BENCHMARK=true; \
	export MEMORY_CLEAN_SMOKE_AGENT_BENCH=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_AGENT_BENCH_SCENARIO_SET="$${MEMORY_AGENT_BENCH_SCENARIO_SET:-all}"; \
	export MEMORY_AGENT_BENCH_OPENAI_API_KEY="$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}}"; \
	export MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-all}"; \
	export MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-600}"; \
	export MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.902}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	$(PYTHON) scripts/clean_full_smoke.py; \
	$(PYTHON) scripts/quality_evidence_bundle.py \
		--output-dir "$$evidence_dir" \
		--extra-report "$$external_report" \
		--expected-git-commit "$$expected_git_commit" \
		$$allow_dirty_arg \
		--require-top-evidence

.PHONY: memo-stack-public-benchmark
memo-stack-public-benchmark:
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_DATASET to a LoCoMo/LongMemEval-like JSON or JSONL file."; exit 1)
	@set -e; \
	set -- --dataset "$${MEMORY_PUBLIC_BENCHMARK_DATASET}"; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT:-}" ]; then set -- "$$@" --report-out "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_API_URL:-}" ]; then set -- "$$@" --api-url "$${MEMORY_PUBLIC_BENCHMARK_API_URL}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_NAME:-}" ]; then set -- "$$@" --benchmark "$${MEMORY_PUBLIC_BENCHMARK_NAME}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-}" ]; then set -- "$$@" --min-accuracy "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-}" ]; then set -- "$$@" --max-cases "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES}"; fi; \
	$(PYTHON) -m memo_stack_server eval public-benchmark "$$@"

.PHONY: memo-stack-memora-direct-smoke
memo-stack-memora-direct-smoke:
	@$(PYTHON) scripts/memora_direct_mcp_smoke.py --report-out "$(MEMORA_DIRECT_SMOKE_REPORT)"

.PHONY: memo-stack-compare-memora
memo-stack-compare-memora:
	@set -e; \
	smoke_report="$${MEMORA_DIRECT_SMOKE_REPORT:-$(MEMORA_DIRECT_SMOKE_REPORT)}"; \
	if [ -n "$$smoke_report" ] && [ -f "$$smoke_report" ]; then \
		$(PYTHON) -m memo_stack_server.memora_comparison --memora-smoke-report "$$smoke_report"; \
	else \
		$(PYTHON) -m memo_stack_server.memora_comparison; \
	fi

.PHONY: memo-stack-official-public-benchmark-canary
memo-stack-official-public-benchmark-canary:
	@set -e; \
	set --; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_NAME:-}" ]; then set -- "$$@" --benchmark "$${MEMORY_PUBLIC_BENCHMARK_NAME}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-}" ]; then set -- "$$@" --max-cases "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-}" ]; then set -- "$$@" --min-accuracy "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_API_URL:-}" ]; then set -- "$$@" --api-url "$${MEMORY_PUBLIC_BENCHMARK_API_URL}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN:-}" ]; then set -- "$$@" --auth-token "$${MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT:-}" ]; then set -- "$$@" --report-out "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT}"; fi; \
	$(PYTHON) scripts/official_public_benchmark_canary.py "$$@"

.PHONY: memo-stack-test-quality
memo-stack-test-quality: memo-stack-lint memo-stack-test-all memo-stack-eval

.PHONY: memo-stack-secret-scan
memo-stack-secret-scan:
	@! rg -n '\bsk-(proj-)?[A-Za-z0-9_-]{40,}\b' . \
		-g '!**/__pycache__/**' \
		-g '!tests/**' \
		-g '!frontend/test/**' \
		-g '!*.lock' \
		-g '!uv.lock' \
		-g '!poetry.lock'

.PHONY: memo-stack-prod-confidence
memo-stack-prod-confidence:
	@set -e; \
	cleanup() { $(MAKE) memo-stack-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) memo-stack-plugin-test; \
	$(MAKE) memo-stack-test-quality; \
	$(MAKE) memo-stack-agent-install-doctor; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) memo-stack-agent-live-smoke; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) memo-stack-agent-live-smoke-agents; \
	$(MAKE) memo-stack-agent-auth-doctor; \
	git diff --check; \
	$(MAKE) memo-stack-secret-scan

.PHONY: memo-stack-prod-confidence-strict
memo-stack-prod-confidence-strict:
	@set -e; \
	cleanup() { $(MAKE) memo-stack-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) memo-stack-prod-confidence-strict-preflight; \
	$(MAKE) memo-stack-plugin-test; \
	$(MAKE) memo-stack-test-quality; \
	$(MAKE) memo-stack-agent-install-doctor; \
	$(MAKE) memo-stack-top-evidence-bundle; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) memo-stack-agent-live-smoke; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) memo-stack-agent-live-smoke-agents-strict; \
	git diff --check; \
	$(MAKE) memo-stack-secret-scan

.PHONY: memo-stack-prod-confidence-full
memo-stack-prod-confidence-full: memo-stack-prod-confidence-strict

.PHONY: memo-stack-prod-confidence-strict-preflight
memo-stack-prod-confidence-strict-preflight:
	$(MAKE) memo-stack-top-evidence-preflight
	$(MAKE) memo-stack-agent-auth-doctor-strict

.PHONY: memo-stack-api-smoke
memo-stack-api-smoke:
	MEMORY_SMOKE_API_URL=$${MEMORY_SMOKE_API_URL:-http://127.0.0.1:7788} MEMORY_SMOKE_AUTH_TOKEN=$${MEMORY_SMOKE_AUTH_TOKEN:-local-dev-token} $(PYTHON) examples/integration_memory_smoke.py

.PHONY: memo-stack-snapshot-thread-smoke
memo-stack-snapshot-thread-smoke:
	MEMORY_SMOKE_API_URL=$${MEMORY_SMOKE_API_URL:-http://127.0.0.1:7788} MEMORY_SMOKE_AUTH_TOKEN=$${MEMORY_SMOKE_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/memory_scope_snapshot_thread_smoke.py

.PHONY: memo-stack-mcp-smoke
memo-stack-mcp-smoke:
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} MEMORY_MCP_WRITE_MODE=direct MEMORY_MCP_DELETE_MODE=explicit MEMORY_MCP_INGEST_MODE=allowed $(PYTHON) examples/mcp_agent_smoke.py

.PHONY: memo-stack-plugin-generate
memo-stack-plugin-generate:
	@set -e; \
	for plugin_root in $(MEMORY_AGENT_PLUGIN_ROOTS); do \
		$(PLUGIN_KIT_AI) generate $$plugin_root; \
	done

.PHONY: memo-stack-plugin-check
memo-stack-plugin-check:
	@set -e; \
	for plugin_root in $(MEMORY_AGENT_PLUGIN_ROOTS); do \
		$(PLUGIN_KIT_AI) generate $$plugin_root --check; \
	done

.PHONY: memo-stack-plugin-validate
memo-stack-plugin-validate:
	@set -e; \
	for target in $(MEMORY_AGENT_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Memo Stack agent plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_PLUGIN_ROOT) --platform $$target --strict; \
	done; \
	for target in $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Memo Stack agent cursor workspace plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT) --platform $$target --strict; \
	done; \
	for target in $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Memo Stack agent Gemini hooks plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT) --platform $$target --strict; \
	done

.PHONY: memo-stack-plugin-doctor
memo-stack-plugin-doctor:
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_PLUGIN_ROOT)/bin/memo-stack-mcp-doctor
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT)/bin/memo-stack-mcp-doctor
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT)/bin/memo-stack-mcp-doctor

.PHONY: memo-stack-plugin-e2e
memo-stack-plugin-e2e: memo-stack-plugin-check
	$(PYTHON) -m pytest tests/e2e/test_memo_stack_agent_plugin_e2e.py -q

.PHONY: memo-stack-plugin-test
memo-stack-plugin-test: memo-stack-plugin-check memo-stack-plugin-validate memo-stack-plugin-e2e

.PHONY: memo-stack-capture-test
memo-stack-capture-test:
	$(PYTHON) -m pytest tests/unit/test_capture_api.py tests/unit/test_capture_worker.py tests/unit/test_memory_taxonomy_mapping.py tests/unit/test_schema_migrations.py -q

.PHONY: memo-stack-capture-e2e
memo-stack-capture-e2e:
	$(PYTHON) -m pytest tests/unit/test_capture_api.py tests/unit/test_capture_worker.py -q

.PHONY: memo-stack-hook-capture-smoke
memo-stack-hook-capture-smoke:
	$(PYTHON) -m pytest tests/unit/test_plugin_hook_capture.py tests/unit/test_capture_host_fixtures.py -q

.PHONY: memo-stack-auto-memory-eval
memo-stack-auto-memory-eval:
	$(PYTHON) -m memo_stack_server eval run --suite auto-memory-golden

.PHONY: memo-stack-graph-native-eval
memo-stack-graph-native-eval:
	$(PYTHON) -m memo_stack_server eval run --suite graph-native-golden

.PHONY: memo-stack-auto-memory-quality
memo-stack-auto-memory-quality: memo-stack-capture-test memo-stack-hook-capture-smoke memo-stack-auto-memory-eval memo-stack-graph-native-eval
	$(PYTHON) -m pytest tests/unit/test_mcp_adapter.py -q

.PHONY: memo-stack-agent-install-dry-run
memo-stack-agent-install-dry-run:
	$(PYTHON) scripts/install_memory_agent_plugin.py --dry-run

.PHONY: memo-stack-agent-install
memo-stack-agent-install:
	$(PYTHON) scripts/install_memory_agent_plugin.py

.PHONY: memo-stack-agent-install-doctor
memo-stack-agent-install-doctor:
	$(PLUGIN_KIT_AI) integrations list
	$(PLUGIN_KIT_AI) integrations doctor
	$(PYTHON) scripts/agent_install_verification.py install-doctor

.PHONY: memo-stack-agent-live-smoke
memo-stack-agent-live-smoke:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) memo-stack-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke

.PHONY: memo-stack-agent-live-smoke-agents
memo-stack-agent-live-smoke-agents:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) memo-stack-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke --run-agent-cli

.PHONY: memo-stack-agent-live-smoke-agents-strict
memo-stack-agent-live-smoke-agents-strict:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) memo-stack-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke --run-agent-cli --strict-agent-cli

.PHONY: memo-stack-agent-auth-doctor
memo-stack-agent-auth-doctor:
	$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor

.PHONY: memo-stack-agent-auth-doctor-strict
memo-stack-agent-auth-doctor-strict:
	$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor --strict

.PHONY: memo-stack-agent-auth-repair
memo-stack-agent-auth-repair:
	@if [ ! -t 0 ]; then \
		echo "Run this target from an interactive terminal: make memo-stack-agent-auth-repair"; \
		exit 1; \
	fi
	@echo "Repairing Claude auth through the official Claude CLI login flow..."
	claude auth login --claudeai
	@echo "Repairing OpenCode OpenAI auth through the official OpenCode provider login flow..."
	opencode providers login --provider openai
	$(MAKE) memo-stack-agent-auth-doctor-strict

.PHONY: memo-stack-doctor
memo-stack-doctor:
	$(PYTHON) -m memo_stack_server.doctor

.PHONY: memo-stack-db-upgrade
memo-stack-db-upgrade:
	$(PYTHON) -m memo_stack_server.db upgrade

.PHONY: memo-stack-seed-defaults
memo-stack-seed-defaults:
	$(PYTHON) -m memo_stack_server.admin seed-defaults

.PHONY: memo-stack-worker-once
memo-stack-worker-once:
	$(PYTHON) -m memo_stack_server.worker --once

.PHONY: memo-stack-postgres-up
memo-stack-postgres-up:
	$(COMPOSE) up -d memo_stack_postgres

.PHONY: memo-stack-full-deps-up
memo-stack-full-deps-up:
	$(COMPOSE) --profile full up -d memo_stack_postgres memo_stack_qdrant memo_stack_neo4j

.PHONY: memo-stack-up
memo-stack-up:
	$(MAKE) memo-stack-up-lite

.PHONY: memo-stack-up-lite
memo-stack-up-lite:
	$(COMPOSE) --profile lite up -d memo_stack_server memo_stack_worker memo_stack_extraction_worker

.PHONY: memo-stack-up-full
memo-stack-up-full:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before starting the full profile."; exit 1)
	MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}" OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}" $(COMPOSE) --profile full up -d memo_stack_server_full memo_stack_worker_full memo_stack_extraction_worker_full

.PHONY: memo-stack-selfhost-config
memo-stack-selfhost-config:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) config >/dev/null

.PHONY: memo-stack-selfhost-up
memo-stack-selfhost-up:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) up -d --build

.PHONY: memo-stack-selfhost-up-full
memo-stack-selfhost-up-full:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) --profile full up -d --build

.PHONY: memo-stack-selfhost-down
memo-stack-selfhost-down:
	$(SELFHOST_COMPOSE) down

.PHONY: memo-stack-selfhost-smoke
memo-stack-selfhost-smoke:
	$(PYTHON) scripts/selfhost_smoke.py --env-file "$(SELFHOST_ENV)"

.PHONY: memo-stack-smoke
memo-stack-smoke:
	$(MAKE) memo-stack-up-lite
	for i in $$(seq 1 90); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 90 ]; then $(COMPOSE) logs --tail=120 memo_stack_server; exit 1; fi; sleep 1; done
	$(MAKE) memo-stack-api-smoke
	$(MAKE) memo-stack-snapshot-thread-smoke

.PHONY: memo-stack-smoke-full
memo-stack-smoke-full:
	$(MAKE) memo-stack-up-full
	for i in $$(seq 1 120); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 120 ]; then $(COMPOSE) logs --tail=120 memo_stack_server_full; exit 1; fi; sleep 1; done
	$(MAKE) memo-stack-api-smoke
	$(MAKE) memo-stack-snapshot-thread-smoke
	$(MAKE) memo-stack-mcp-smoke

.PHONY: memo-stack-clean-full-smoke
memo-stack-clean-full-smoke:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running clean full smoke."; exit 1)
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-clean-full-mcp-smoke
memo-stack-clean-full-mcp-smoke:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running clean full MCP smoke."; exit 1)
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-agent-behavior-bench
memo-stack-agent-behavior-bench:
	@test -n "$${MEMORY_AGENT_BENCH_MODEL:-}" || (echo "Set MEMORY_AGENT_BENCH_MODEL before running agent behavior benchmark."; exit 1)
	@test -n "$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-}}}" || (echo "Set MEMORY_AGENT_BENCH_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY before running agent behavior benchmark."; exit 1)
	export MEMORY_CLEAN_SMOKE_AGENT_BENCH=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS="$${MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS:-360}"; \
	export MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR="$${MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR:-true}"; \
	export MEMORY_AGENT_BENCH_OPENAI_API_KEY="$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-agent-realistic-bench
memo-stack-agent-realistic-bench:
	@test -n "$${MEMORY_AGENT_BENCH_MODEL:-}" || (echo "Set MEMORY_AGENT_BENCH_MODEL before running realistic agent behavior benchmark."; exit 1)
	@test -n "$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-}}}" || (echo "Set MEMORY_AGENT_BENCH_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY before running realistic agent behavior benchmark."; exit 1)
	export MEMORY_CLEAN_SMOKE_AGENT_BENCH=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_AGENT_BENCH_SCENARIO_SET=realistic; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS="$${MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS:-360}"; \
	export MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR="$${MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR:-true}"; \
	export MEMORY_AGENT_BENCH_OPENAI_API_KEY="$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-agent-live-session-bench
memo-stack-agent-live-session-bench:
	@test -n "$${MEMORY_AGENT_BENCH_MODEL:-}" || (echo "Set MEMORY_AGENT_BENCH_MODEL before running live-session agent behavior benchmark."; exit 1)
	@test -n "$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-}}}" || (echo "Set MEMORY_AGENT_BENCH_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY before running live-session agent behavior benchmark."; exit 1)
	export MEMORY_CLEAN_SMOKE_AGENT_BENCH=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_AGENT_BENCH_SCENARIO_SET=live; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS="$${MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS:-360}"; \
	export MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR="$${MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR:-true}"; \
	export MEMORY_AGENT_BENCH_OPENAI_API_KEY="$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-agent-transcript-corpus-bench
memo-stack-agent-transcript-corpus-bench:
	@test -n "$${MEMORY_AGENT_BENCH_MODEL:-}" || (echo "Set MEMORY_AGENT_BENCH_MODEL before running transcript corpus agent behavior benchmark."; exit 1)
	@test -n "$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-}}}" || (echo "Set MEMORY_AGENT_BENCH_OPENAI_API_KEY, OPENAI_API_KEY or MEMORY_OPENAI_API_KEY before running transcript corpus agent behavior benchmark."; exit 1)
	export MEMORY_CLEAN_SMOKE_AGENT_BENCH=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_AGENT_BENCH_SCENARIO_SET=transcript; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS="$${MEMORY_AGENT_BENCH_LLM_TIMEOUT_SECONDS:-360}"; \
	export MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR="$${MEMORY_AGENT_BENCH_FAIL_ON_WORKER_ERROR:-true}"; \
	export MEMORY_AGENT_BENCH_OPENAI_API_KEY="$${MEMORY_AGENT_BENCH_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-agent-transcript-corpus-redact
memo-stack-agent-transcript-corpus-redact:
	@test -n "$${MEMORY_AGENT_TRANSCRIPT_INPUT:-}" || (echo "Set MEMORY_AGENT_TRANSCRIPT_INPUT to a transcript file or directory."; exit 1)
	@test -n "$${MEMORY_AGENT_TRANSCRIPT_OUTPUT:-}" || (echo "Set MEMORY_AGENT_TRANSCRIPT_OUTPUT to the redacted corpus output directory."; exit 1)
	$(PYTHON) scripts/agent_transcript_corpus_redactor.py "$${MEMORY_AGENT_TRANSCRIPT_INPUT}" "$${MEMORY_AGENT_TRANSCRIPT_OUTPUT}"

.PHONY: memo-stack-agent-transcript-corpus-audit
memo-stack-agent-transcript-corpus-audit:
	@test -n "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR:-}" || (echo "Set MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR to a redacted corpus directory."; exit 1)
	@if [ "$${MEMORY_AGENT_TRANSCRIPT_CORPUS_AUDIT_STRICT:-false}" = "true" ]; then \
		$(PYTHON) scripts/agent_transcript_corpus_audit.py "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR}" --strict; \
	else \
		$(PYTHON) scripts/agent_transcript_corpus_audit.py "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR}"; \
	fi

.PHONY: memo-stack-full-provider-canary
memo-stack-full-provider-canary: memo-stack-clean-full-mcp-smoke

.PHONY: memo-stack-full-provider-public-benchmark-canary
memo-stack-full-provider-public-benchmark-canary:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running full-provider public benchmark canary."; exit 1)
	export MEMORY_CLEAN_SMOKE_PUBLIC_BENCHMARK=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-locomo}"; \
	export MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-1}"; \
	export MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.5}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-full-provider-public-benchmark-suite
memo-stack-full-provider-public-benchmark-suite:
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET to a representative LoCoMo dataset before running public benchmark suite."; exit 1)
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET to a representative LongMemEval dataset before running public benchmark suite."; exit 1)
	MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-all}" \
	MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-600}" \
	MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.902}" \
	$(MAKE) memo-stack-full-provider-public-benchmark-canary

.PHONY: memo-stack-full-provider-canary-interactive
memo-stack-full-provider-canary-interactive:
	@if [ -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" ]; then \
		$(MAKE) memo-stack-full-provider-canary; \
	else \
		if [ ! -t 0 ]; then \
			echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY, or run this target from an interactive terminal."; \
			exit 1; \
		fi; \
		printf "OpenAI key (input hidden): " >&2; \
		old_stty=$$(stty -g); \
		trap 'stty "$$old_stty" 2>/dev/null || true' EXIT INT TERM; \
		stty -echo; \
		IFS= read -r OPENAI_KEY; \
		stty "$$old_stty"; \
		trap - EXIT INT TERM; \
		printf "\n" >&2; \
		test -n "$$OPENAI_KEY" || (echo "OpenAI key is required."; exit 1); \
		MEMORY_OPENAI_API_KEY="$$OPENAI_KEY" OPENAI_API_KEY="$$OPENAI_KEY" $(MAKE) memo-stack-full-provider-canary; \
		unset OPENAI_KEY; \
	fi

.PHONY: memo-stack-prod-load-canary
memo-stack-prod-load-canary:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running prod load canary."; exit 1)
	export MEMORY_CLEAN_SMOKE_PROD_LOAD=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: memo-stack-real-memory-confidence
memo-stack-real-memory-confidence:
	@set -e; \
	cleanup() { $(MAKE) memo-stack-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) memo-stack-top-evidence-bundle; \
	$(MAKE) memo-stack-prod-load-canary; \
	$(MAKE) memo-stack-agent-live-session-bench; \
	$(MAKE) memo-stack-agent-transcript-corpus-bench; \
	git diff --check; \
	$(MAKE) memo-stack-secret-scan

.PHONY: memo-stack-down
memo-stack-down:
	$(COMPOSE) --profile lite --profile full down

.PHONY: memo-stack-server
memo-stack-server:
	$(MEMORY_SERVER_ENV) $(PYTHON) -m memo_stack_server.main
